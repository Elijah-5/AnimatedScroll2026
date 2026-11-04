"""SDK client with opt-in, durable live-acceptance accounting. Never log credentials."""
import fcntl
import inspect
import json
import os
import time
from pathlib import Path
import httpx
from openai import AsyncOpenAI as OpenAIClient


def update_ledger(fn):
    folder=Path(os.environ['CREATION_LIVE_RUN_DIR']);folder.mkdir(parents=True,exist_ok=True)
    with (folder/'requests.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=folder/'requests.json'
        ledger=json.loads(path.read_text()) if path.exists() else dict(limit=int(os.getenv('CREATION_LIVE_REQUEST_LIMIT','100')),requests=[])
        if os.getenv('CREATION_LIVE_BUDGET_USD'):ledger['limit']=min(ledger['limit'],60)
        result=fn(ledger)
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(ledger,ensure_ascii=False,indent=2));temp.replace(path)
        return result


async def request_hook(request):
    if request.method!='POST':return
    caller=next((f.function for f in inspect.stack() if '/backend/' in f.filename and not f.filename.endswith('model_client.py')),'model')
    def reserve(ledger):
        if len(ledger['requests'])>=ledger['limit']:raise ValueError('真实模型请求已达到本轮上限，已保存进度，未继续调用')
        row=dict(id=len(ledger['requests'])+1,time=time.time(),stage=caller,status='started',host=request.url.host)
        try:
            body=json.loads(request.content);row['requestedModel']=body.get('model','')
            if os.getenv('CREATION_LIVE_BUDGET_USD'):
                from .live_budget import reserve as reserve_budget
                row.update(reserve_budget(ledger,body))
        except AttributeError:pass
        if os.getenv('CREATION_LIVE_BUDGET_USD') and 'reservedUsd' not in row:raise ValueError('验收费用预算校验未通过，未发送请求')
        ledger['requests'].append(row);return row['id']
    request.extensions['acceptance_request_id']=update_ledger(reserve)


async def response_hook(response):
    rid=response.request.extensions.get('acceptance_request_id')
    if not rid:return
    await response.aread()
    try:body=response.json()
    except ValueError:body={}
    def finish(ledger):
        row=ledger['requests'][rid-1]
        row.update(status=response.status_code,elapsedSeconds=round(time.time()-row['time'],3),model=body.get('model',''),usage=body.get('usage',{}))
        if row.get('rates'):
            from .live_budget import account
            account(row,body.get('usage',{}))
        if body.get('choices'):row['finishReason']=body['choices'][0].get('finish_reason')
    update_ledger(finish)


class AsyncOpenAI(OpenAIClient):
    def __init__(self,*args,**kwargs):
        if os.getenv('CREATION_LIVE_RUN_DIR') and 'http_client' not in kwargs:
            kwargs['http_client']=httpx.AsyncClient(event_hooks=dict(request=[request_hook],response=[response_hook]))
        super().__init__(*args,**kwargs)
