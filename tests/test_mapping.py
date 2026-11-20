"""别名与单位冲突裁定、映射版本治理、复核锁定与回退的规范测试。"""
import pytest
from app.engine import evaluate
from app.errors import BusinessError
from app.mapping import resolve_header, resolve_unit, REGISTRY, ACTIVE_VERSION, get_version
from fastapi.testclient import TestClient
from app import main

# ---------- 单位裁定：兼容换算与待查 ----------

def test_chinese_unit_aliases_convert():
    s = evaluate({'dataset': 'mixed'})
    r1 = next(r for r in s['records'] if r['id'] == 'MX-R1-00')
    assert r1['unit_raw'] == '兆瓦' and r1['power_kw'] == '100.0'
    assert r1['unit_factor'] == '1000' and r1['unit_canonical'] == 'MW'
    assert '兆瓦' in r1['conversion_basis']
    b = next(r for r in s['records'] if r['id'] == 'MX-B-00')
    assert b['power_raw'] == '0.03' and b['power_kw'] == '30.00'
    kw = next(r for r in s['records'] if r['id'] == 'MX-A-00')
    assert kw['unit_raw'] == '千瓦' and kw['power_kw'] == '60' and kw['unit_factor'] == '1'


def test_watt_is_pending_not_silently_scaled():
    s = evaluate({'dataset': 'mixed'})
    q = next(r for r in s['quarantine'] if r['id'] == 'MX-A-30-W')
    assert q['code'] == 'UNIT_PENDING'
    assert not any(r['id'] == 'MX-A-30-W' for r in s['records'])


def test_unknown_unit_rejected():
    s = evaluate({'dataset': 'mixed'})
    q = next(r for r in s['quarantine'] if r['id'] == 'MX-A-40-BADUNIT')
    assert q['code'] == 'BAD_UNIT' and q['raw']['unit'] == '匹'


def test_unit_resolve_registry_codes():
    assert resolve_unit('kW', ACTIVE_VERSION)['code'] == 'unit_alias'
    assert resolve_unit('兆瓦', ACTIVE_VERSION)['factor'] == '1000'
    assert resolve_unit('W', ACTIVE_VERSION)['pending'] is True
    assert resolve_unit('匹', ACTIVE_VERSION)['code'] == 'unit_unknown'


# ---------- 同设备同时刻：换算后不得产生两条观测 ----------

def test_equivalent_cross_unit_duplicates_collapse_to_one():
    s = evaluate({'dataset': 'mixed'})
    # 60千瓦 与 0.06兆瓦 换算等价：保留稳定编号 MX-A-00，另一条隔离为重复
    kept = [r for r in s['records'] if r['device'] == 'INV-A'
            and r['at'] == '2026-10-15T02:00:00+00:00']
    assert len(kept) == 1 and kept[0]['id'] == 'MX-A-00'
    dup = next(r for r in s['quarantine'] if r['id'] == 'MX-A-00-MW')
    assert dup['code'] == 'SAMPLE_DUPLICATE' and dup['duplicate_of'] == 'MX-A-00'


def test_conflicting_cross_unit_both_isolated():
    s = evaluate({'dataset': 'mixed'})
    # 60千瓦 vs 0.055兆瓦(=55kW)：换算后仍冲突，两条全部隔离
    ids = {r['id'] for r in s['quarantine'] if r['code'] == 'SAMPLE_CONFLICT'}
    assert {'MX-A-10', 'MX-A-10-CONFLICT'} <= ids
    at = '2026-10-15T02:10:00+00:00'
    assert not any(r['device'] == 'INV-A' and r['at'] == at for r in s['records'])


def test_no_device_time_has_two_observations():
    s = evaluate({'dataset': 'mixed'})
    seen = {}
    for r in s['records']:
        if r['kind'] != 'TELEMETRY':
            continue
        key = (r['device'], r['at'])
        assert key not in seen, f'同一设备同一时刻出现两条观测：{key}'
        seen[key] = r


# ---------- 待查值不进基线与损失 ----------

def test_pending_values_excluded_from_baseline_and_loss():
    s = evaluate({'dataset': 'mixed'})
    used = {rid for row in s['estimates'] for rid in row['reference_ids']}
    used |= {row['sample_id'] for row in s['energy_rows']}
    forbidden = {'MX-A-30-W', 'MX-A-40-BADUNIT', 'MX-A-00-MW',
                 'MX-A-10', 'MX-A-10-CONFLICT'}
    assert forbidden.isdisjoint(used)
    # 待查造成的缺测保持未定，不填 0
    gap = next(r for r in s['estimates'] if r['sample_id'] == '' or r['code'] == 'TARGET_GAP')
    assert gap['baseline_kw'] is None


# ---------- 中文列名别名与表头审计 ----------

def test_chinese_headers_resolve_via_aliases():
    s = evaluate({'dataset': 'mixed'})
    assert s['header_audit'][0] == {'raw_header': '编号', 'canonical': 'id',
                                    'code': 'alias', 'detail': '别名映射→id',
                                    'mapping_version': ACTIVE_VERSION}
    assert all(a['canonical'] for a in s['header_audit'])
    assert s['records'][0]['device']


def test_pending_field_alias_quarantines_row():
    header = '编号,类型,设备,采样时刻,发电量,计量单位,辐照度,状态,开始,结束'
    line = 'P1,TELEMETRY,INV-A,2026-10-15T10:00:00+08:00,60,kW,800,健康,,'
    s = evaluate({'csv_text': header + '\n' + line + '\n'})
    q = next(r for r in s['quarantine'] if r['id'] == 'P1')
    assert q['code'] == 'FIELD_PENDING'
    assert s['counts']['pending'] == 1
    assert not s['records']
    audit = next(a for a in s['header_audit'] if a['raw_header'] == '发电量')
    assert audit['code'] == 'pending' and audit['canonical'] == 'power'


def test_unknown_column_rejected():
    header = '编号,类型,设备,采样时刻,功率,计量单位,辐照度,状态,开始,神秘列'
    line = 'U1,TELEMETRY,INV-A,2026-10-15T10:00:00+08:00,60,kW,800,健康,,x'
    s = evaluate({'csv_text': header + '\n' + line + '\n'})
    q = next(r for r in s['quarantine'] if r['id'] == 'U1')
    assert q['code'] == 'UNKNOWN_COLUMN'


def test_missing_required_header_raises():
    # 旧映射版本不认识中文列名 -> 缺必需列，整批拒绝
    text = '编号,类型,设备,采样时刻,功率,计量单位,辐照度,状态,开始时间,结束时间\n'
    with pytest.raises(BusinessError) as e:
        evaluate({'csv_text': text, 'mapping_version': '2026.11.17-m1'})
    assert e.value.code == 'BAD_HEADER'


# ---------- 映射版本治理：旧版失效、digest 区分、不可变 ----------

def test_mapping_version_part_of_digest_and_manifest():
    s = evaluate({'dataset': 'mixed'})
    assert s['manifest']['mapping_version'] == ACTIVE_VERSION
    assert s['input_snapshot']['mapping_version'] == ACTIVE_VERSION
    # 不同映射版本 -> 不同批号（digest 纳入版本）
    a = evaluate({'dataset': 'clean'})
    b = evaluate({'dataset': 'clean', 'mapping_version': '2026.11.17-m1'})
    assert a['manifest']['run_id'] != b['manifest']['run_id']
    assert b['manifest']['mapping_version'] == '2026.11.17-m1'


def test_unknown_mapping_version_rejected():
    with pytest.raises(BusinessError) as e:
        evaluate({'dataset': 'clean', 'mapping_version': '1999-never'})
    assert e.value.code == 'UNKNOWN_MAPPING'


def test_registry_versions_immutable_and_listed():
    assert REGISTRY['2026.11.17-m1']['status'] == 'superseded'
    assert REGISTRY[ACTIVE_VERSION]['status'] == 'active'
    # 旧版仍保留且单位表较窄：不识别中文单位与 W
    assert '千瓦' not in REGISTRY['2026.11.17-m1']['units']
    assert get_version(None) == ACTIVE_VERSION


def test_lineage_carries_original_column_and_basis():
    s = evaluate({'dataset': 'mixed'})
    r = next(x for x in s['records'] if x['id'] == 'MX-B2-00')
    assert r['power_raw'] == '0.05' and r['unit_raw'] == '兆瓦'
    assert r['power_kw'] == '50.00'
    assert r['header_map'] and r['header_map'][4]['raw_header'] == '功率'


# ---------- API：复核锁定、切换失败回退、版本清单 ----------

def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DB_PATH', str(tmp_path / 't.sqlite'))
    return TestClient(main.app)


def test_reviewed_batch_cannot_be_overwritten(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'mixed'}).json()
    rid = run['manifest']['run_id']
    first = c.post(f'/api/runs/{rid}/review', json={'revision': 1})
    assert first.status_code == 200 and first.json()['status'] == '已复核'
    # 重复复核被锁定拒绝
    again = c.post(f'/api/runs/{rid}/review', json={'revision': 2})
    assert again.status_code == 409 and again.json()['code'] == 'BATCH_REVIEWED'
    # 同输入重跑返回同一批号，且复核状态不被覆盖
    rerun = c.post(f'/api/runs/{rid}/rerun', json={}).json()
    assert rerun['manifest']['run_id'] == rid
    assert c.get(f'/api/runs/{rid}').json()['status'] == '已复核'


def test_rerun_switch_mapping_creates_new_batch_keeps_old(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'clean'}).json()
    rid = run['manifest']['run_id']
    switched = c.post(f'/api/runs/{rid}/rerun',
                      json={'mapping_version': '2026.11.17-m1'})
    assert switched.status_code == 200
    new = switched.json()
    assert new['manifest']['run_id'] != rid
    assert new['manifest']['mapping_version'] == '2026.11.17-m1'
    # 旧版结果仍在
    assert c.get(f'/api/runs/{rid}').status_code == 200
    assert len(c.get('/api/runs').json()) == 2


def test_incompatible_switch_keeps_old_result_409(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    # mixed 是中文表头；切到不认中文列的旧映射版本应失败并回退
    run = c.post('/api/runs', json={'dataset': 'mixed'}).json()
    rid = run['manifest']['run_id']
    resp = c.post(f'/api/runs/{rid}/rerun',
                  json={'mapping_version': '2026.11.17-m1'})
    assert resp.status_code == 409
    body = resp.json()
    assert body['code'] == 'MAPPING_INCOMPATIBLE'
    assert body['fallback_run_id'] == rid
    # 旧批次未被破坏
    assert c.get(f'/api/runs/{rid}').json()['manifest']['mapping_version'] == ACTIVE_VERSION


def test_mappings_listing_endpoint(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    data = c.get('/api/mappings').json()
    assert data['active'] == ACTIVE_VERSION
    versions = {v['version']: v['status'] for v in data['versions']}
    assert versions == {'2026.11.17-m1': 'superseded', '2026.11.20-m2': 'active'}


def test_pages_show_mapping_source_and_pending(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    run = c.post('/api/runs', json={'dataset': 'mixed'}).json()
    rid = run['manifest']['run_id']
    intake_html = c.get(f'/intake?run_id={rid}').text
    assert '列名映射来源' in intake_html and '计量单位' in intake_html
    devices_html = c.get(f'/devices?run_id={rid}').text
    assert '单位换算与血缘' in devices_html and '换算依据' in devices_html
    assert '待查' in intake_html
