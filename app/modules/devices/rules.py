from decimal import Decimal
from app.coerce import number, instant
from app.errors import BusinessError
from app.reasons import reject
from app.mapping import resolve_unit
from collections import defaultdict


def normalize(row, context):
    mapping_version = context.get('mapping_version')
    if row['device'] not in context['devices']:
        raise BusinessError('UNKNOWN_DEVICE', '设备不存在')
    device = context['devices'][row['device']]
    if row['kind'] == 'EVENT':
        start, end = instant(row['start']), instant(row['end'])
        if not start < end or (end - start).total_seconds() > 86400:
            raise BusinessError('INVALID_RANGE', '限电区间无效或超过24小时')
        return {**row, 'start': start.isoformat(), 'end': end.isoformat(), 'zone': device['zone']}
    if row['kind'] != 'TELEMETRY':
        raise BusinessError('BAD_KIND', '记录类型无效')
    # 单位裁定：兼容则带系数换算并留痕；待查/未知则隔离，原值不进基线与损失。
    verdict = resolve_unit(row.get('unit', ''), mapping_version)
    lineage = {'power_raw': row.get('power', ''), 'unit_raw': verdict['raw'],
               'unit_canonical': verdict['canonical'], 'unit_factor': verdict['factor'],
               'conversion_basis': verdict['basis'], 'unit_code': verdict['code'],
               'header_map': row.get('_header_map', [])}
    if verdict['pending']:
        code = 'UNIT_PENDING' if verdict['code'] == 'unit_pending' else 'BAD_UNIT'
        raise BusinessError(code, f"单位“{verdict['raw']}”{verdict['basis']}")
    factor = Decimal(verdict['factor'])
    power = number(row['power']) * factor
    irr = number(row['irradiance'])
    if power < 0 or irr < 0 or power > number(device['capacity_kw']) * number('1.2'):
        raise BusinessError('INVALID_RANGE', '功率或辐照度超出范围')
    if row['status'] not in {'健康', '故障'}:
        raise BusinessError('BAD_STATUS', '设备状态无效')
    return {**row, 'at': instant(row['at']).isoformat(), 'power_kw': str(power),
            'irradiance': str(irr), 'zone': device['zone'], **lineage}


def apply(state):
    good = []
    for row in state['records']:
        try:
            good.append(normalize(row, state['context']))
        except BusinessError as e:
            reject(state, row, e.code, e.message)
    grouped = defaultdict(list)
    for row in good:
        if row['kind'] == 'TELEMETRY':
            grouped[(row['device'], row['at'])].append(row)
    bad_ids = set()
    for rows in grouped.values():
        if len(rows) > 1:
            # 换算后再比较：不同原单位但数值等价（如 0.06MW 与 60kW）视为同一观测，按稳定编号保留一条；
            # 换算后仍不同则两条全部隔离，绝不让同一设备同一时刻出现两条观测。
            identities = {(number(r['power_kw']), number(r['irradiance']), r['status']) for r in rows}
            if len(identities) > 1:
                for row in rows:
                    reject(state, row, 'SAMPLE_CONFLICT',
                            '设备同一时刻换算后存在不同观测，全部隔离待查')
                    bad_ids.add(row['id'])
            else:
                keep = sorted(rows, key=lambda r: r['id'])[0]
                for row in rows[1:]:
                    merged = dict(row)
                    merged['duplicate_of'] = keep['id']
                    reject(state, merged, 'SAMPLE_DUPLICATE',
                            f"与{keep['id']}换算后等价（{row['power_raw']}{row['unit_raw']}="
                            f"{row['power_kw']}kW），保留稳定编号{keep['id']}")
                    bad_ids.add(row['id'])
    state['records'] = [r for r in good if r['id'] not in bad_ids]
    converted = [r for r in state['records'] if r.get('kind') == 'TELEMETRY'
                 and r.get('unit_factor') not in (None, '1')]
    state['views']['devices'] = {
        'title': '设备与单位', 'rows': state['records'],
        'metrics': {'设备': len(state['context']['devices']), '规范记录': len(state['records']),
                    '隔离': len(state['quarantine']), '单位换算行': len(converted)}}
