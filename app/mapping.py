"""版本化字段别名与功率单位注册表。

裁定原则（可发布规范）：
- 字段别名在某一映射版本中登记到唯一规范字段 -> 兼容，按别名采信并留痕；
- 别名被列入 pending（语义未证实）-> 待查，整行隔离，不进入基线与损失；
- 表头无法解析到任何规范字段 -> 未知列，记录原因但不静默改名；
- 单位别名可解释且换算系数确定 -> 兼容，换算为 kW 并保留原单位/原值/系数/依据；
- 单位语义未证实（如 W）或完全无法识别 -> 待查/拒收，隔离原值。

注册表只允许追加新版本，旧版本必须保留以供同批复算与复核追溯，不得就地改写。
"""
from app.errors import BusinessError

# 规范字段（顺序即标准表头顺序）
CANONICAL_FIELDS = ['id', 'kind', 'device', 'at', 'power', 'unit',
                    'irradiance', 'status', 'start', 'end']

# 每个映射版本独立声明，保证历史版本不可变。
REGISTRY = {
    '2026.11.17-m1': {
        'status': 'superseded',
        'released_at': '2026-11-17',
        'superseded_by': '2026.11.20-m2',
        'note': '初版：仅英文规范列与编号中文别名；单位仅支持 kW/MW。',
        'field_aliases': {
            'id': 'id', 'kind': 'kind', 'device': 'device', 'at': 'at',
            'power': 'power', 'unit': 'unit', 'irradiance': 'irradiance',
            'status': 'status', 'start': 'start', 'end': 'end',
            '编号': 'id',
        },
        # 语义未证实的表头：命中即待查
        'pending_field_aliases': {},
        'units': {
            'kw': {'canonical': 'kW', 'factor': '1', 'pending': False,
                   'basis': '规范单位千瓦，系数1'},
            'mw': {'canonical': 'MW', 'factor': '1000', 'pending': False,
                   'basis': '兆瓦换算千瓦，1MW=1000kW'},
        },
        'pending_units': {},
    },
    '2026.11.20-m2': {
        'status': 'active',
        'released_at': '2026-11-20',
        'supersedes': '2026.11.17-m1',
        'note': '供应商拆分功率/计量单位并混用中英文列名：登记中文列别名与中文单位别名；'
                'W 与发电量语义未证实，一律待查。',
        'field_aliases': {
            # 规范英文名
            'id': 'id', 'kind': 'kind', 'device': 'device', 'at': 'at',
            'power': 'power', 'unit': 'unit', 'irradiance': 'irradiance',
            'status': 'status', 'start': 'start', 'end': 'end',
            # 已证实语义的中文列名
            '编号': 'id',
            '类型': 'kind',
            '设备': 'device', '设备编号': 'device',
            '采样时刻': 'at', '时间': 'at', '时刻': 'at',
            '功率': 'power', '有功功率': 'power', '功率值': 'power',
            '计量单位': 'unit', '单位': 'unit', '功率单位': 'unit',
            '辐照度': 'irradiance', '辐照': 'irradiance',
            '状态': 'status', '设备状态': 'status',
            '开始时间': 'start', '开始': 'start',
            '结束时间': 'end', '结束': 'end',
        },
        'pending_field_aliases': {
            # 同名但语义未证实：可能是电量(kWh)而非功率(kW)，禁止猜解
            '发电量': 'power',
            '电量': 'power',
            '电度量': 'power',
        },
        'units': {
            'kw': {'canonical': 'kW', 'factor': '1', 'pending': False,
                   'basis': '规范单位千瓦，系数1'},
            '千瓦': {'canonical': 'kW', 'factor': '1', 'pending': False,
                    'basis': '中文千瓦登记别名，等同kW，系数1'},
            'mw': {'canonical': 'MW', 'factor': '1000', 'pending': False,
                   'basis': '兆瓦换算千瓦，1MW=1000kW'},
            '兆瓦': {'canonical': 'MW', 'factor': '1000', 'pending': False,
                    'basis': '中文兆瓦登记别名，1兆瓦=1000千瓦'},
        },
        'pending_units': {
            # 瓦与现场功率量级不符，语义未证实，转待查而非静默除以1000
            'w': {'canonical': 'W', 'pending': True,
                  'basis': '瓦(W)量级与逆变器功率不符，待人工证实'},
            '瓦': {'canonical': 'W', 'pending': True,
                   'basis': '中文瓦量级与逆变器功率不符，待人工证实'},
        },
    },
}

ACTIVE_VERSION = '2026.11.20-m2'


def get_version(version):
    if version is None:
        version = ACTIVE_VERSION
    if version not in REGISTRY:
        raise BusinessError('UNKNOWN_MAPPING', f'映射版本不存在：{version}')
    return version


def registry(version):
    return REGISTRY[get_version(version)]


def resolve_header(raw_name, version):
    """返回 (规范字段或None, 裁定码, 说明)。

    裁定码：canonical 规范列名 / alias 已登记别名 / pending 语义待查 / unknown 未知列。
    """
    name = (raw_name or '').strip()
    spec = registry(version)
    if name in CANONICAL_FIELDS:
        return name, 'canonical', '规范列名'
    if name in spec['field_aliases']:
        return spec['field_aliases'][name], 'alias', f'别名映射→{spec["field_aliases"][name]}'
    if name in spec['pending_field_aliases']:
        return spec['pending_field_aliases'][name], 'pending', '列名语义未证实，待查'
    return None, 'unknown', '未登记列名'


def resolve_unit(raw_unit, version):
    """返回 dict(canonical, factor, pending, basis, code)。

    code：unit_alias 兼容并换算 / unit_pending 语义待查 / unit_unknown 无法识别。
    """
    text = (raw_unit or '').strip()
    spec = registry(version)
    key = text.lower()
    if key in spec['units']:
        item = spec['units'][key]
        return {'raw': text, 'canonical': item['canonical'], 'factor': item['factor'],
                'pending': False, 'basis': item['basis'], 'code': 'unit_alias'}
    if key in spec['pending_units']:
        item = spec['pending_units'][key]
        return {'raw': text, 'canonical': item['canonical'], 'factor': None,
                'pending': True, 'basis': item['basis'], 'code': 'unit_pending'}
    return {'raw': text, 'canonical': None, 'factor': None,
            'pending': True, 'basis': '单位未登记，无法证实换算关系', 'code': 'unit_unknown'}


def header_audit(original_headers, version):
    """对整行表头做兼容性审计，供页面展示映射来源。"""
    audit = []
    for raw in original_headers:
        canonical, code, detail = resolve_header(raw, version)
        audit.append({'raw_header': raw, 'canonical': canonical,
                      'code': code, 'detail': detail,
                      'mapping_version': get_version(version)})
    return audit


def listing():
    return [
        {'version': v, 'status': s['status'], 'released_at': s['released_at'],
         'note': s['note'],
         'supersedes': s.get('supersedes'), 'superseded_by': s.get('superseded_by')}
        for v, s in REGISTRY.items()
    ]
