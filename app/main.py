from contextlib import asynccontextmanager
from importlib import import_module
from fastapi import FastAPI, Request, Body
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from app.config import ROOT, META, MODULES, DB_PATH
from app.errors import BusinessError
from app.engine import evaluate
from app import store
from app.archive import serialize
from app import mapping

@asynccontextmanager
async def lifespan(app):
    store.save(DB_PATH,evaluate())
    yield
app=FastAPI(title=META['title'],lifespan=lifespan)
app.mount('/static',StaticFiles(directory=str(ROOT/'app/static')),name='static')
@app.exception_handler(BusinessError)
async def business_error(request:Request,error:BusinessError):
    return JSONResponse({'code':error.code,'detail':error.message},status_code=error.status)
@app.get('/')
def home():
    return RedirectResponse('/'+MODULES[0],status_code=303)
@app.get('/healthz')
def health():
    return {'status':'ok','project':META['short']}
@app.get('/api/mappings')
def mappings():
    return {'active':mapping.ACTIVE_VERSION,'versions':mapping.listing()}
@app.post('/api/runs')
def create(payload:dict=Body(default={})):
    return store.save(DB_PATH,evaluate(payload))
@app.post('/api/runs/{run_id}/rerun')
def rerun(run_id:str,payload:dict=Body(default={})):
    previous=store.get(DB_PATH,run_id)
    if 'input_snapshot' not in previous:
        raise BusinessError('INPUT_SNAPSHOT_MISSING','旧批缺少源快照，请重新导入')
    target=(payload or {}).get('mapping_version')
    # 未指定版本则沿用本批快照版本，规则未变时批号不变（幂等重跑）。
    target=target or previous['input_snapshot'].get('mapping_version')
    try:
        fresh=evaluate({'dataset':previous['source'],'mapping_version':target},
                       snapshot=previous['input_snapshot'])
    except BusinessError as error:
        # 兼容切换失败：保留旧版结果，返回409与旧批号，前端不得改写已复核记录。
        return JSONResponse(status_code=409,content={
            'code':'MAPPING_INCOMPATIBLE','detail':f'映射版本{target}切换失败，已保留旧版结果：{error.message}',
            'fallback_run_id':run_id,'old_mapping_version':previous['manifest'].get('mapping_version'),
            'requested_mapping_version':target})
    return store.save(DB_PATH,fresh)
@app.get('/api/runs')
def runs():
    return store.history(DB_PATH)
@app.get('/api/runs/{run_id}')
def run(run_id:str):
    return store.get(DB_PATH,run_id)
@app.post('/api/runs/{run_id}/review')
def review(run_id:str,payload:dict=Body(...)):
    revision=payload.get('revision')
    if not isinstance(revision,int) or revision<1: raise BusinessError('BAD_REVISION','版本号须为正整数')
    current=store.get(DB_PATH,run_id)
    if current.get('status')=='已复核':
        raise BusinessError('BATCH_REVIEWED','该批次已复核锁定，不能重复提交或覆盖',409)
    return store.review(DB_PATH,run_id,revision)
@app.get('/api/export/{run_id}')
def export(run_id:str):
    result=store.get(DB_PATH,run_id)
    return Response(serialize(result),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{run_id}.zip"'})
for key in MODULES:
    app.include_router(import_module(f'app.modules.{key}.handler').router)
