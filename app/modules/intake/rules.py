from .reader import read_source
FIELDS = ['id', 'kind', 'device', 'at', 'power', 'unit', 'irradiance', 'status', 'start', 'end']


def apply(state):
    read_source(state, FIELDS, {'编号': 'id'})
    # 映射来源审计：页面展示每一列的原始列名、裁定码与映射依据。
    state['views']['mapping'] = {
        'title': '列名映射来源',
        'rows': state['header_audit'],
        'metrics': {
            '映射版本': state['mapping_version'],
            '规范列': sum(1 for a in state['header_audit'] if a['code'] == 'canonical'),
            '别名列': sum(1 for a in state['header_audit'] if a['code'] == 'alias'),
            '待查列': sum(1 for a in state['header_audit'] if a['code'] == 'pending'),
            '未知列': sum(1 for a in state['header_audit'] if a['code'] == 'unknown'),
        }}
