REASONS = {
    'COLUMN_COUNT':'列数错误', 'MISSING_ID':'编号缺失', 'DUPLICATE_CONFLICT':'重复编号冲突',
    'MISSING_VALUE':'数值缺失', 'BAD_NUMBER':'数值格式错误', 'BAD_TIME':'时间格式错误',
    'BAD_UNIT':'单位不受支持', 'UNKNOWN_REFERENCE':'引用对象不存在', 'INVALID_RANGE':'范围错误',
    'VERSION_CONFLICT':'版本冲突', 'EMPTY_FILE':'空文件', 'BLANK_FILE':'全空行',
    'HEADER_ONLY':'仅有表头', 'STALE_VERSION':'复核版本已更新', 'NOT_FOUND':'批次不存在',
    'FIELD_PENDING':'列名语义待查', 'UNKNOWN_COLUMN':'未登记列名',
    'UNIT_PENDING':'单位语义待查', 'UNKNOWN_MAPPING':'映射版本不存在',
    'MAPPING_INCOMPATIBLE':'映射切换不兼容', 'BATCH_REVIEWED':'批次已复核锁定',
}
def reject(state, record, code, detail):
    entry={'line':record.get('_line',0),'id':record.get('id',''),
       'code':code,'detail':detail,'raw':{k:v for k,v in record.items() if not k.startswith('_')}}
    # 保留显式溯源字段（如并入编号），便于复核追到原观测
    for extra in ('duplicate_of',):
        if extra in record: entry[extra]=record[extra]
    state['quarantine'].append(entry)
