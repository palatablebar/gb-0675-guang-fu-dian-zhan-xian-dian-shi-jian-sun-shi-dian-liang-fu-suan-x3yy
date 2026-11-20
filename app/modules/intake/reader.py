import csv, io
from app.errors import BusinessError
from app.reasons import reject
from app.mapping import header_audit, get_version

# 业务记录必须存在的规范字段
REQUIRED_FIELDS = ['id', 'kind', 'device']


def read_source(state, fields, aliases):
    raw = state['raw_bytes']
    if not raw: raise BusinessError('EMPTY_FILE', '请选择非空文件')
    if not raw.strip(b'\xef\xbb\xbf\r\n \t'): raise BusinessError('BLANK_FILE', '文件只有空行')
    mapping_version = get_version(state.get('mapping_version'))
    state['mapping_version'] = mapping_version
    text = None
    encoding = None
    for enc in ('utf-8-sig', 'gb18030'):
        try:
            text = raw.decode(enc); encoding = enc; break
        except UnicodeDecodeError:
            continue
    if text is None: raise BusinessError('BAD_ENCODING', '文件编码无法识别')
    stream = csv.reader(io.StringIO(text, newline=''), strict=True)
    try:
        original = next(stream)
    except StopIteration:
        raise BusinessError('HEADER_ONLY', '文件只有表头')
    # 逐列裁定别名，保留原始列名与映射来源，绝不静默改名。
    audit = header_audit(original, mapping_version)
    state['header_audit'] = audit
    header = [a['canonical'] for a in audit]
    missing = [f for f in REQUIRED_FIELDS if f not in [h for h in header if h]]
    if missing:
        raise BusinessError('BAD_HEADER', f'缺少必需列（映射版本{mapping_version}）：{",".join(missing)}')
    state['counts'] = {'input': 0, 'blank': 0, 'repeated_header': 0,
                       'duplicate': 0, 'pending': 0, 'unknown_column': 0}
    pending_columns = {i for i, a in enumerate(audit) if a['code'] == 'pending'}
    records = []
    try:
        for cells in stream:
            line = stream.line_num
            state['counts']['input'] += 1
            if not cells or not any(v.strip() for v in cells):
                state['counts']['blank'] += 1; continue
            if cells == original:
                state['counts']['repeated_header'] += 1; continue
            if len(cells) != len(header):
                row = {'_line': line, 'id': cells[0].strip() if cells and cells[0].strip() else ''}
                reject(state, row, 'COLUMN_COUNT', f'需要{len(header)}列，实际{len(cells)}列'); continue
            row = {h: cells[i] for i, h in enumerate(header) if h is not None}
            row['_line'] = line
            row['_header_map'] = [dict(a) for a in audit]
            # 语义未证实的列：整行待查，不得进入基线与损失。
            hit_pending = [audit[i]['raw_header'] for i in pending_columns if i < len(cells) and cells[i].strip()]
            if hit_pending:
                state['counts']['pending'] += 1
                reject(state, row, 'FIELD_PENDING',
                       f'列“{hit_pending[0]}”语义未证实（映射版本{mapping_version}），待人工裁定'); continue
            unknown = [a['raw_header'] for a in audit if a['code'] == 'unknown']
            if unknown:
                state['counts']['unknown_column'] += 1
                reject(state, row, 'UNKNOWN_COLUMN', f'未登记列名：{unknown[0]}'); continue
            if not row.get('id', '').strip():
                reject(state, row, 'MISSING_ID', '编号不能为空'); continue
            row['id'] = row['id'].strip()
            records.append(row)
    except csv.Error:
        raise BusinessError('BROKEN_CSV', 'CSV引号或末行损坏')
    if not state['counts']['input']: raise BusinessError('HEADER_ONLY', '文件只有表头')
    by_id = {}
    for row in records: by_id.setdefault(row['id'], []).append(row)
    selected = []
    for key, rows in by_id.items():
        identities = {tuple((k, v) for k, v in r.items() if not k.startswith('_')) for r in rows}
        if len(identities) > 1:
            for row in rows: reject(state, row, 'DUPLICATE_CONFLICT', '同一编号存在不同原值')
        else:
            selected.append(rows[0]); state['counts']['duplicate'] += len(rows) - 1
    state['records'] = selected
    state['encoding'] = encoding
    state['views'][state['context']['keys'][0]] = {
        'rows': [dict(r) for r in selected],
        'metrics': {'采信行': len(selected), '隔离行': len(state['quarantine']),
                    '重复行': state['counts']['duplicate'], '待查行': state['counts']['pending']},
        'title': '原始证据'}
