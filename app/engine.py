from importlib import import_module
from pathlib import Path
from copy import deepcopy
import json, time, base64
from app.config import ROOT, MODULES, MAX_BYTES, DEFAULT_MAPPING_VERSION
from app.errors import BusinessError
from app.manifest import digest, make_manifest
from app.mapping import get_version

def evaluate(payload=None, until=7, snapshot=None):
    payload=payload or {}
    dataset=payload.get('dataset','dirty')
    if dataset not in {'dirty','clean','legacy','mixed'}: raise BusinessError('BAD_DATASET','样例名称无效')
    if not isinstance(payload.get('overrides',{}),dict): raise BusinessError('BAD_CONTEXT','参数须为对象')
    raw=(base64.b64decode(snapshot['bytes_b64'],validate=True) if snapshot is not None else (str(payload['csv_text']).encode() if 'csv_text' in payload else (ROOT/'sample_data'/f'{dataset}.csv').read_bytes()))
    if len(raw)>MAX_BYTES: raise BusinessError('TOO_LARGE','文件超过2MB',413)
    context=deepcopy(snapshot['context']) if snapshot is not None else json.loads((ROOT/'sample_data/context.json').read_text())
    context.update(deepcopy(payload.get('overrides',{})))
    # 映射版本：显式参数优先，其次快照，最后当前生效版本。版本不存在立即报错，绝不静默回退。
    requested=payload.get('mapping_version') or (snapshot.get('mapping_version') if snapshot else None) or DEFAULT_MAPPING_VERSION
    mapping_version=get_version(requested)
    context['mapping_version']=mapping_version
    start=time.perf_counter()
    state={'raw_bytes':raw,'context':context,'records':[],'quarantine':[], 'counts':{},'views':{},'source':dataset,'mapping_version':mapping_version}
    for index,key in enumerate(MODULES,1):
        if index>until: break
        import_module(f'app.modules.{key}.rules').apply(state)
    state['input_snapshot']={'bytes_b64':base64.b64encode(raw).decode(),'context':deepcopy(context),'mapping_version':mapping_version}
    state.pop('raw_bytes',None)
    state['manifest']=make_manifest(digest(raw,context,mapping_version),dataset,time.perf_counter()-start,mapping_version)
    return state
