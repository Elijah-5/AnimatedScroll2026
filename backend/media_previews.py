"""Explicit, quoted AIHubMix previews with a durable, shared ten-yuan ceiling.

Paid submissions are never retried. Unknown costs/submissions keep their entire
reservation and block further paid work, including work in other projects.
"""
import asyncio
import base64
import copy
import hashlib
import io
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from . import consumption as consume, workspace as ws, video, video_generation, video_budget
from .cutouts import valid_box
from .task_runtime import digest

ORIGIN = 'https://aihubmix.com'
LIMIT_CNY = 10.0
MARGIN = 1.25
VIDEO_MODEL = 'wan3.0-video'
ACTIVE = {'queued', 'submitting', 'pending', 'downloading'}


def schema(db):
    for table in ('media_preview_jobs', 'media_preview_quotes'):
        db.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY, project TEXT, body TEXT)')


def scoped_ids(p, scope='narrative'):
    return [r['id'] for r in p['workspace']['entities'].values()
            if r['kind']=='clue' and r['state']!='deleted'
            and (scope=='all' or r['draft'].get('type')=='narrative')]


def snapshot(p, sid, data):
    shot = consume.confirmed(p, 'storyboard', sid)
    clue = consume.bound(p, 'storyboard', sid, 'clue', shot['clueId'])
    mat = consume.confirmed(p, 'material', 'main')
    path = Path(data)/Path(mat.get('image','')).name
    if not mat.get('image','').startswith('/api/images/') or not path.is_file():
        raise ValueError('原画文件不存在')
    if not valid_box(shot.get('region')):
        raise ValueError('请先设置并确认此分镜的画面区域')
    value = dict(storyboardId=sid, clueId=shot['clueId'], title=clue['name'],
                 storyboard=shot, clue=clue, region=shot['region'],
                 narrationText=ws.narrative_text(clue) if clue.get('type')=='narrative' else clue.get('summary',''),
                 sourceVersion=p['version'], imageSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                 characterReferences=[dict(characterId=cid,character=consume.confirmed(p,'character',cid),
                    boxes=[a for a in mat.get('annotations',[]) if a.get('characterId')==cid and a.get('identityConfirmed')]) for cid in shot.get('characterIds',[])])
    value['fingerprint']=digest({k:v for k,v in value.items() if k!='sourceVersion'})
    return value, path


def reference_image(path, box=None):
    with Image.open(path) as source:
        image=ImageOps.exif_transpose(source).convert('RGB')
        if box:
            w,h=image.size
            image=image.crop((round(box['x']*w),round(box['y']*h),round((box['x']+box['w'])*w),round((box['y']+box['h'])*h)))
        image.thumbnail((1600,1600))
        if min(image.size)<240:
            scale=240/min(image.size);image=image.resize((round(image.width*scale),round(image.height*scale)))
        out=io.BytesIO();image.save(out,format='PNG')
    return out.getvalue()


def prompt(value):
    shot=value['storyboard']
    return (video.STYLE+'\n仅表现下列已审阅情节，动作简单克制，固定或缓慢移动镜头。'
            '不添加字幕、不编造对白、不新增人物或历史事件。\n情节：'+value['narrationText']+
            '\n分镜：'+shot.get('prompt','')+'\n起始：'+shot.get('startFrame','')+'\n结束：'+shot.get('endFrame',''))


def headers():
    key=os.getenv('AIHUBMIX_API_KEY','')
    if not key:raise ValueError('未配置 AIHUBMIX_API_KEY')
    return {'Authorization':'Bearer '+key}


def unit_price(row, kind):
    """Only accept explicit per-second/per-image billing, never token defaults."""
    candidates=[]
    for line in row.get('pricing_lines',[]):
        if line.get('billable') not in ('generate','video_generation','image_generation'):continue
        if line.get('unit')!=('second' if kind=='video' else 'image'):continue
        variant=line.get('variant') or {}
        if variant.get('fallback'):continue
        variant=variant.get('match',variant)
        if any(not isinstance(v,(str,int,float,bool)) for v in variant.values()):continue
        if kind=='video' and str(variant.get('size','')).lower()!='480p':continue
        if kind=='image' and variant.get('quality') not in (None,'standard','low'):continue
        cost=line.get('cost_usd')
        if isinstance(cost,(int,float)) and math.isfinite(cost) and cost>0:candidates.append((cost,variant))
    # A variable tariff needs an exact matching variant rather than a guessed minimum.
    return min(candidates,key=lambda v:v[0]) if candidates else None


async def pricing(kind):
    if kind=='crop':return dict(model='local-crop',unitUsd=0,fx=0,endpoint='',parameters={})
    async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
        response=await client.get(ORIGIN+'/api/v1/models',params={'schema_checked':'true','sort_by':'order'})
        response.raise_for_status();rows=response.json()['data']
        fx_response=await client.get('https://open.er-api.com/v6/latest/USD');fx_response.raise_for_status()
        fx=float(fx_response.json()['rates']['CNY'])
        if not math.isfinite(fx) or not 3<fx<20:raise ValueError('汇率无法核实，暂停付费生成')
        candidates=[]
        for row in rows:
            if kind=='video' and row.get('model_id')!=VIDEO_MODEL:continue
            if kind=='image' and 'image' not in str(row.get('output_modalities','')):continue
            # A flat output quote is insufficient for token-billed image models.
            if kind=='image' and any(l.get('unit')=='million_tokens' and l.get('cost_usd',0)>0 for l in row.get('pricing_lines',[])):continue
            tariff=unit_price(row,kind)
            if tariff:candidates.append((tariff[0],row,tariff[1]))
        for price,row,variant in sorted(candidates,key=lambda v:v[0]):
            response=await client.get(ORIGIN+'/call/schema/models/'+row['model_id']+'/endpoints')
            if response.status_code!=200:continue
            endpoints=response.json().get('endpoints',[])
            for ep in endpoints:
                expected='/ai/v1/videos' if kind=='video' else '/ai/v1/images/generations'
                if ep.get('path')!=expected:continue
                spec=ep['request']['schema'];props=spec.get('properties',{})
                reference='input_references' if 'input_references' in props else 'images' if 'images' in props else ''
                if not reference:continue
                params={}
                if kind=='video':
                    if not {'duration','resolution','generate_audio'}<=props.keys():continue
                    params=dict(duration=5,resolution='480p',generate_audio=False,aspect_ratio='adaptive',extra={'prompt_extend':False})
                else:
                    # Image fallback is usable only if its exact priced variant and
                    # reference input can be represented by the published schema.
                    if reference!='images' or 'response_format' not in props:continue
                    if any(k not in props for k in variant):continue
                    params=dict(variant)
                    # Synchronous image output also works for accounts without
                    # async task permission. Inline results avoid a second query.
                    params.update({'async':False,'response_format':'b64_json'})
                    if 'n' in props:params['n']=1
                    if 'output_format' in props:params['output_format']='png'
                    if 'size' in spec.get('required',[]) and 'size' not in params:continue
                compat=next((e for e in endpoints if e.get('path')=='/v1/images/edits' and {'image','response_format'}<=e.get('request',{}).get('schema',{}).get('properties',{}).keys()),None) if kind=='image' else None
                return dict(model=row['model_id'],unitUsd=price,fx=fx,endpoint=expected,compatEndpoint=compat['path'] if compat else '',
                            parameters=params,referenceField=reference,maxReferences=props.get(reference,{}).get('maxItems',10),
                            inputUnitUsd=sum(l['cost_usd'] for l in row.get('pricing_lines',[]) if l.get('billable')=='image_input' and l.get('unit')=='image'),
                            priceSource=ORIGIN+'/api/v1/models',checkedAt=time.time())
    raise ValueError('未找到已核实参考图能力和固定报价的模型，请使用原画局部预览')


def public(job):
    return {k:v for k,v in job.items() if k not in ('providerBody','remoteOutput','quoteInputs')}


def accepted_jobs(pid,db):
    with db() as c:rows=[json.loads(r[0]) for r in c.execute('SELECT body FROM media_preview_jobs WHERE project=?',(pid,))]
    return [j for j in rows if j['status']=='succeeded' and j.get('review')=='accepted']


def media_for(p, sid, db, data, rows=None):
    """Match the fixed production content, never attach newer content to old chats."""
    rows=accepted_jobs(p['id'],db) if rows is None else rows
    matches=[j for j in rows if j['storyboardId']==sid]
    if not matches:return None
    try:value,_=snapshot(p,sid,data)
    except (ValueError,KeyError):return None
    matches=[j for j in matches if j['fingerprint']==value['fingerprint']]
    for job in sorted(matches,key=lambda j:j['createdAt'],reverse=True):
        if (Path(data)/'media-previews'/(job['id']+job['extension'])).is_file():
            return dict(mediaKind=job['kind'],videoUrl=job.get('videoUrl',''),imageUrl=job.get('imageUrl',''),mediaLabel=job['mediaLabel'],region=value['region'],narrationText=value['narrationText'],previewJobId=job['id'],sourceVersion=job['sourceVersion'])
    return None


class Quote(BaseModel):
    version:int
    scope:Literal['narrative','all']='narrative'
    storyboardIds:list[str]=Field(min_length=1,max_length=3)
    kind:Literal['video','image','crop']='video'

class Submit(BaseModel):
    quoteId:str
    requestId:str=Field(min_length=1,max_length=100)

class Review(BaseModel):
    accepted:bool


def install(app,get,db,data):
    lock=asyncio.Lock();workers={}
    def jobs(pid=None):
        with db() as c:
            return [json.loads(r[0]) for r in c.execute('SELECT body FROM media_preview_jobs'+(' WHERE project=?' if pid else ''),(pid,) if pid else ())]
    def budget(pid=None,kind=None):
        if kind=='video' and pid:
            with db() as c:return video_budget.summary(c,pid)
        rows=jobs();used=sum(j.get('reservedCny',0) for j in rows)
        return dict(limitCny=LIMIT_CNY,reservedCny=round(used,4),remainingCny=round(max(0,LIMIT_CNY-used),4),
                    blocked=any(j['status'] in ('submission_unknown','cost_unknown') for j in rows))
    def read(pid,jid):
        with db() as c:row=c.execute('SELECT body FROM media_preview_jobs WHERE id=? AND project=?',(jid,pid)).fetchone()
        if not row:raise HTTPException(404,'预览任务不存在')
        return json.loads(row[0])
    def store(j):
        with db() as c:c.execute('UPDATE media_preview_jobs SET body=? WHERE id=?',(json.dumps(j,ensure_ascii=False),j['id']))
    def message(exc):
        if isinstance(exc,httpx.HTTPStatusError):
            try:
                error=exc.response.json().get('error',{});code=str(error.get('code') or exc.response.status_code)
                return {'async_not_enabled':'账户未开启异步视频权限，请改用分镜图片或原画局部预览',
                        'insufficient_quota':'账户可用额度不足，可改用免费原画局部预览',
                        'permission_denied':'当前 Key 无此模型权限，可改用图片或免费局部预览',
                        'no_available_channel':'供应商当前无可用生成通道，请使用免费原画局部预览'}.get(code,code)
            except ValueError:return 'HTTP '+str(exc.response.status_code)
        return str(exc)[:180] if isinstance(exc,ValueError) else type(exc).__name__
    def stop_waiting(job):
        for other in jobs(job['projectId']):
            if other['batchId']==job['batchId'] and other['status']=='waiting_review':
                other.update(status='skipped',reservedCny=0,message='前一条未通过，尚未提交的任务已停止');store(other)
    def write_image(job,blob):
        if len(blob)>40*1024*1024:raise ValueError('分镜图片超过大小限制')
        with Image.open(io.BytesIO(blob)) as im:im.verify()
        folder=Path(data())/'media-previews';folder.mkdir(exist_ok=True)
        path=folder/(job['id']+'.png');temp=path.with_suffix('.part')
        with Image.open(io.BytesIO(blob)) as im:im.save(temp,format='PNG')
        temp.replace(path)
        job.update(status='succeeded',message='预览已保存，请检查画面后继续',review='pending',imageUrl=f"/api/projects/{job['projectId']}/media-previews/{job['id']}/file")
        store(job)
    async def download(client,job):
        # Native content lives on the authenticated origin. Do not follow a
        # redirect with a credential; cross-origin content is fetched separately.
        url=job.get('remoteOutput') or ORIGIN+job['endpoint']+'/'+job['remoteId']+'/content'
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname!='aihubmix.com':raise ValueError('媒体结果地址不是已核实的 AIHubMix 内容接口')
        response=await client.get(url,headers=headers())
        if response.is_redirect:
            target=response.headers.get('location','');host=urlparse(target)
            if host.scheme!='https' or not host.hostname or not host.hostname.endswith(('.aliyuncs.com','.aihubmix.com')):raise ValueError('媒体下载重定向地址不受支持')
            response=await client.get(target)  # deliberately no credentials
        response.raise_for_status()
        if len(response.content)>150*1024*1024 or len(response.content)<100:raise ValueError('媒体文件大小异常')
        if job['kind']=='image':
            with Image.open(io.BytesIO(response.content)) as im:im.verify()
        elif b'ftyp' not in response.content[:64]:raise ValueError('结果不是可识别的 MP4 文件')
        folder=Path(data())/'media-previews';folder.mkdir(exist_ok=True)
        path=folder/(job['id']+job['extension']);temp=path.with_suffix('.part')
        if job['kind']=='image':
            with Image.open(io.BytesIO(response.content)) as im:im.save(temp,format='PNG')
        else:temp.write_bytes(response.content)
        temp.replace(path)
        job.update(status='succeeded',message='预览已保存，请检查画面后继续',review='pending')
        job['videoUrl' if job['kind']=='video' else 'imageUrl']=f"/api/projects/{job['projectId']}/media-previews/{job['id']}/file"
        store(job)
    async def work(job):
        try:
            if job['kind']=='crop':
                folder=Path(data())/'media-previews';folder.mkdir(exist_ok=True)
                blob=base64.b64decode(job['providerBody']['crop'])
                (folder/(job['id']+'.png')).write_bytes(blob)
                job.update(status='succeeded',message='原画局部预览已保存',imageUrl=f"/api/projects/{job['projectId']}/media-previews/{job['id']}/file",review='pending');store(job);return
            async with httpx.AsyncClient(timeout=180,follow_redirects=False) as client:
                if job.get('remoteId') and job['status']=='download_failed':await download(client,job);return
                if not job.get('remoteId'):
                    job.update(status='submitting',message='正在提交');store(job)
                    try:
                        if job['endpoint']=='/v1/images/edits':
                            body=dict(job['providerBody']);image=base64.b64decode(body.pop('image').split(',',1)[1])
                            response=await client.post(ORIGIN+job['endpoint'],headers=headers(),data=body,files={'image':('painting.png',image,'image/png')})
                        else:response=await client.post(ORIGIN+job['endpoint'],headers=headers(),json=job['providerBody'])
                        response.raise_for_status();value=response.json()
                    except (httpx.TransportError,ValueError) as exc:
                        job.update(status='submission_unknown',message='提交状态不明，已停止付费请求：'+message(exc));store(job);stop_waiting(job);return
                    except httpx.HTTPStatusError as exc:
                        known=400<=exc.response.status_code<500 and exc.response.status_code not in (408,)
                        try:code=str(exc.response.json().get('error',{}).get('code',''))
                        except ValueError:code=''
                        job.update(status='failed' if known else 'submission_unknown',message='提交未完成：'+message(exc),errorCode=code,submissionKnownRejected=known)
                        # Retain the reservation even on rejection; no presumed refund.
                        store(job);stop_waiting(job);return
                    if job['endpoint']=='/v1/images/edits' and isinstance(value.get('data'),list) and value['data'] and value['data'][0].get('b64_json'):
                        job['responseReceived']=True;store(job)
                        write_image(job,base64.b64decode(value['data'][0]['b64_json'],validate=True));return
                    if not value.get('id'):
                        job.update(status='submission_unknown',message='未收到任务编号，停止新增付费请求');store(job);stop_waiting(job);return
                    job.update(remoteId=value['id'],status='pending',message='等待生成');store(job)
                    if value.get('status')=='completed':
                        output=value.get('output') or []
                        if job['kind']=='image' and output and output[0].get('b64_json'):
                            write_image(job,base64.b64decode(output[0]['b64_json'],validate=True));return
                        job.update(status='downloading',message='正在保存媒体',remoteOutput=output[0].get('content_url','') if output else '')
                        store(job);await download(client,job);return
                for _ in range(120):
                    response=await client.get(ORIGIN+job['endpoint'].removesuffix('/generations')+'/'+job['remoteId'],headers=headers())
                    response.raise_for_status();value=response.json();state=value.get('status')
                    if state=='completed':
                        output=value.get('output') or []
                        job.update(status='downloading',message='正在保存媒体',remoteOutput=output[0].get('content_url','') if output else '')
                        store(job);await download(client,job);return
                    if state in ('failed','cancelled'):
                        job.update(status='failed',message='生成未成功：'+str((value.get('error') or {}).get('code') or state));store(job);stop_waiting(job);return
                    if state not in ('pending','in_progress'):raise ValueError('无法确认远端任务状态')
                    await asyncio.sleep(15)
                job.update(status='paused',message='等待较久，可继续查询原任务');store(job)
        except Exception as exc:
            job.update(status='download_failed' if job.get('remoteOutput') or job['status']=='downloading' else 'paused' if job.get('remoteId') else 'failed',message=message(exc));store(job)
        finally:workers.pop(job['id'],None)
    def launch(job):
        if job['id'] not in workers:workers[job['id']]=asyncio.create_task(work(job))

    @app.get('/api/projects/{pid}/media-previews')
    def list_previews(pid:str):
        with db() as c:exists=c.execute('SELECT id FROM projects WHERE id=?',(pid,)).fetchone()
        if not exists:raise HTTPException(404,'项目不存在')
        return dict(jobs=[public(j) for j in sorted(jobs(pid),key=lambda j:j['createdAt'],reverse=True)],budget=budget())

    @app.post('/api/projects/{pid}/media-previews/quote')
    async def quote(pid:str,req:Quote):
        p=get(pid)
        if p['version']!=req.version:raise HTTPException(409,'内容已变化，请重新查看预览费用')
        if p.get('archived'):raise HTTPException(422,'项目已归档')
        if req.kind=='video' and video_generation.active() is None:raise HTTPException(503,'视频生成已迁移至正式分镜接口；模型待接入，本次不扣额度')
        allowed=set(scoped_ids(p,req.scope))
        if len(set(req.storyboardIds))!=len(req.storyboardIds) or not set(req.storyboardIds)<=allowed:raise HTTPException(422,'所选分镜不属于当前生成范围')
        inputs=[]
        try:
            for sid in req.storyboardIds:
                value,path=snapshot(p,sid,data());refs=[dict(type='image_url',url='data:image/png;base64,'+base64.b64encode(reference_image(path)).decode())]
                # Preserve the same calibrated character reference strategy as video.
                if req.kind!='crop':
                    original,_=video.shot_inputs(p,sid,data())
                    for ref in original['references'][1:]:refs.append(dict(type='image_url',url='data:image/png;base64,'+base64.b64encode(reference_image(path,ref['box'])).decode()))
                value['references']=refs;value['crop']=base64.b64encode(reference_image(path,value['region'])).decode();inputs.append(value)
            price=await pricing(req.kind)
            if req.kind=='image' and price.get('compatEndpoint') and any(j.get('errorCode')=='async_not_enabled' or 'async_not_enabled' in j.get('message','') for j in jobs()):
                price['endpoint']=price['compatEndpoint'];price['referenceField']='image'
                price['parameters']={k:v for k,v in price['parameters'].items() if k not in ('async','output_format','n')}
                for value in inputs:value['references']=value['references'][:1]
            if req.kind!='crop':headers()
        except (ValueError,KeyError,httpx.HTTPError) as exc:raise HTTPException(422,message(exc)) from exc
        units=5 if req.kind=='video' else 1
        max_refs=max(len(v['references']) for v in inputs)
        if max_refs>price.get('maxReferences',10):raise HTTPException(422,'参考人物数量超过此模型限制，请减少分镜参与人物')
        unit_usd=price['unitUsd']*units+price.get('inputUnitUsd',0)*max_refs
        reserve=round(unit_usd*price['fx']*MARGIN,4)
        q=dict(id=digest([pid,req.model_dump(),price,time.time()])[:32],projectId=pid,createdAt=time.time(),scope=req.scope,kind=req.kind,price=price,inputs=inputs,unitReservedCny=reserve,totalReservedCny=round(reserve*len(inputs),4),version=p['version'])
        with db() as c:c.execute('INSERT INTO media_preview_quotes VALUES (?,?,?)',(q['id'],pid,json.dumps(q,ensure_ascii=False)))
        return dict(quoteId=q['id'],kind=req.kind,model=price['model'],duration=5 if req.kind=='video' else 0,resolution='480P' if req.kind=='video' else '',unitUsd=price['unitUsd'],fx=price['fx'],estimatedCny=round(unit_usd*price['fx']*len(inputs),4),reservedCny=q['totalReservedCny'],budget=budget(pid,req.kind),items=[dict(storyboardId=v['storyboardId'],title=v['title'],prompt=prompt(v),region=v['region'],narrationText=v['narrationText'],referenceCount=len(v['references'])) for v in inputs])

    @app.post('/api/projects/{pid}/media-previews')
    async def submit(pid:str,req:Submit):
        async with lock:
            existing=[j for j in jobs(pid) if j.get('requestId')==req.requestId]
            if existing:
                if any(j['quoteId']!=req.quoteId for j in existing):raise HTTPException(409,'请求编号已用于其他预览')
                return dict(jobs=[public(j) for j in existing],budget=budget())
            with db() as c:row=c.execute('SELECT body FROM media_preview_quotes WHERE id=? AND project=?',(req.quoteId,pid)).fetchone()
            if not row:raise HTTPException(404,'报价不存在')
            q=json.loads(row[0]);p=get(pid)
            if q['kind']=='video' and video_generation.active() is None:raise HTTPException(503,'视频模型尚未接入；本次未提交或扣额度')
            if time.time()-q['createdAt']>900:raise HTTPException(409,'报价已过期，请重新查看费用')
            if p.get('archived'):raise HTTPException(422,'项目已归档')
            for value in q['inputs']:
                try:current,_=snapshot(p,value['storyboardId'],data())
                except (ValueError,KeyError) as exc:raise HTTPException(409,'分镜依据已变化，请重新预览') from exc
                if current['fingerprint']!=value['fingerprint']:raise HTTPException(409,'分镜依据已变化，请重新预览')
            old=jobs(pid) if q['kind']=='video' else jobs();b=budget(pid,q['kind'])
            if q['kind']!='crop' and b['blocked']:raise HTTPException(409,'有提交状态或费用待核实，暂停新增付费请求')
            # A new quote cannot silently create a second paid take of the same content.
            def duplicate(j,v):
                known_permission_rejection=j['status']=='failed' and (j.get('errorCode')=='async_not_enabled' or 'async_not_enabled' in j.get('message',''))
                return j.get('kind')==q['kind'] and j.get('fingerprint')==v['fingerprint'] and j['status']!='skipped' and not (known_permission_rejection and j.get('endpoint')!=q['price']['endpoint'])
            if any(duplicate(j,v) for j in old for v in q['inputs']):raise HTTPException(409,'该内容已有同类预览任务，请查看或继续原任务')
            created=[]
            for index,value in enumerate(q['inputs']):
                body={'model':q['price']['model'],'prompt':prompt(value),**q['price']['parameters']}
                if q['kind']=='crop':body={'crop':value['crop']}
                else:body[q['price']['referenceField']]=(value['references'][0]['url'] if q['price']['referenceField']=='image' else [{'url':r['url']} for r in value['references']] if q['price']['referenceField']=='images' else value['references'])
                if len(json.dumps(body).encode())>32*1024*1024:raise HTTPException(422,'参考图片超过接口大小限制，请减少参与人物')
                j={k:copy.deepcopy(v) for k,v in value.items() if k not in ('references','crop')}
                j.update(id=digest([pid,req.requestId,index])[:32],projectId=pid,batchId=req.requestId,requestId=req.requestId,quoteId=req.quoteId,
                         kind=q['kind'],model=q['price']['model'],endpoint=q['price']['endpoint'],providerBody=body,
                         status='queued' if index==0 else 'waiting_review',message='等待检查前一条' if index else '等待提交',
                         reservedCny=q['unitReservedCny'],createdAt=time.time()+index*.001,extension='.mp4' if q['kind']=='video' else '.png',
                         mediaLabel='AI 生成叙事预览' if q['kind']!='crop' else '原画局部预览（非生成画面）')
                created.append(j)
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                video_budget.lock_project(c,pid)
                locked_jobs=[json.loads(r[0]) for r in c.execute('SELECT body FROM media_preview_jobs'+(' WHERE project=?' if q['kind']=='video' else ''),(pid,) if q['kind']=='video' else ())]
                if q['kind']!='crop' and any(j['status'] in ('submission_unknown','cost_unknown') for j in locked_jobs):raise HTTPException(409,'付费请求状态待核实')
                if any(duplicate(j,v) for j in locked_jobs for v in q['inputs']):raise HTTPException(409,'该内容已有同类预览任务')
                reserved=sum(j.get('reservedCny',0) for j in locked_jobs)
                if q['kind']=='video':video_budget.require(c,pid,count=len(created),amount=q['totalReservedCny'])
                elif reserved+q['totalReservedCny']>LIMIT_CNY:raise HTTPException(422,'本次提交会超过 ¥10 总预算')
                for j in created:c.execute('INSERT INTO media_preview_jobs VALUES (?,?,?)',(j['id'],pid,json.dumps(j,ensure_ascii=False)))
            launch(created[0]);return dict(jobs=[public(j) for j in created],budget=budget())

    @app.post('/api/projects/{pid}/media-previews/{jid}/review')
    async def review(pid:str,jid:str,req:Review):
        async with lock:
            j=read(pid,jid)
            if j['status']!='succeeded':raise HTTPException(422,'请先等待当前预览成功')
            if j.get('review') in ('accepted','rejected'):return public(j)
            j['review']='accepted' if req.accepted else 'rejected';store(j)
            if not req.accepted:stop_waiting(j)
            else:
                pending=sorted([r for r in jobs(pid) if r['batchId']==j['batchId'] and r['status']=='waiting_review'],key=lambda r:r['createdAt'])
                if pending:
                    following=pending[0]
                    if following['kind']=='video' and video_generation.active() is None:raise HTTPException(503,'视频模型尚未接入，不会提交后续视频任务')
                    if following['kind']!='crop' and budget()['blocked']:raise HTTPException(409,'付费请求状态待核实，未提交下一条')
                    following.update(status='queued',message='等待提交');store(following);launch(following)
            return public(j)

    @app.post('/api/projects/{pid}/media-previews/{jid}/resume')
    async def resume(pid:str,jid:str):
        j=read(pid,jid)
        if j.get('remoteId') and j['status'] in ('paused','pending','download_failed'):launch(j)
        else:raise HTTPException(422,'只能继续查询或下载已知远端任务，不会重新提交')
        return public(j)

    @app.get('/api/projects/{pid}/media-previews/{jid}/file')
    def file(pid:str,jid:str):
        j=read(pid,jid);path=Path(data())/'media-previews'/(j['id']+j['extension'])
        if j['status']!='succeeded' or not path.is_file():raise HTTPException(404,'媒体文件不存在')
        return FileResponse(path,media_type='video/mp4' if j['kind']=='video' else 'image/png')

    async def recover():
        for j in jobs():
            if j['status'] in ('queued','submitting') and not j.get('remoteId'):
                j.update(status='submission_unknown',message='服务重启，提交状态待核实；不会自动重提');store(j);stop_waiting(j)
            elif j.get('remoteId') and j['status'] in ('pending','downloading'):launch(j)
    async def shutdown():
        tasks=list(workers.values())
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
    app.router.add_event_handler('startup',recover);app.router.add_event_handler('shutdown',shutdown)
