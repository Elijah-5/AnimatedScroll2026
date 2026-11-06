"""Explicit, durable research runs. No model calls or automatic screen capture."""
import base64
import contextvars
import copy
import csv
import hashlib
import io
import json
import re
import time
import uuid
import zipfile
from pathlib import Path
from typing import Literal
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from . import snapshot_store

TABLES=('experiment_runs','experiment_events','experiment_artifacts','experiment_notes')
_current=contextvars.ContextVar('experiment_context',default=None)
SENSITIVE=re.compile(r'password|secret|api.?key|authorization|access.?token|credential|cookie',re.I)
PAGES={'overview':'概览','library':'资料库','outline':'剧本','clues':'线索','characters':'人物档案','storyboards':'分镜','experience':'作品体验','experiment':'实验面板','feedback':'截图便笺'}


def schema(c):
    for table in TABLES:c.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY, project TEXT, body TEXT)')


def clean(value):
    if isinstance(value,dict):
        if SENSITIVE.search(str(value.get('path',''))):return {k:('[已省略敏感输入]' if k in ('value','before','after') else clean(v)) for k,v in value.items()}
        return {k:('[已省略敏感输入]' if SENSITIVE.search(k) else clean(v)) for k,v in value.items()}
    if isinstance(value,list):return [clean(v) for v in value]
    return value


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def now():return int(time.time()*1000)
def new_id():return uuid.uuid4().hex


def load(c,rid,lock=False):
    sql='SELECT body FROM experiment_runs WHERE id=?'
    if lock and getattr(c,'dialect','')=='mysql':sql+=' FOR UPDATE'
    row=c.execute(sql,(rid,)).fetchone()
    if not row:raise HTTPException(404,'实验记录不存在')
    return json.loads(row[0])


def store(c,run):c.execute('UPDATE experiment_runs SET body=? WHERE id=?',(json.dumps(run,ensure_ascii=False),run['id']))


def snapshot(p,c=None):
    if not p:return dict(projectId=None,title='',version=0,entities={})
    entities={k:dict(kind=r['kind'],id=r['id'],state=r['state'],revision=r.get('revision',0),draft=copy.deepcopy(r['draft']),published=copy.deepcopy(r.get('published'))) for k,r in p.get('workspace',{}).get('entities',{}).items()}
    if c:
        for table in ('video_jobs','media_preview_jobs'):
            for body, in c.execute('SELECT body FROM '+table+' WHERE project=?',(p['id'],)):
                job=json.loads(body)
                if job.get('test'):continue
                fields={k:job.get(k) for k in ('id','title','status','model','prompt','storyboardId','videoUrl','imageUrl','review','reviewStatus')}
                entities['media:'+table+':'+job['id']]=dict(kind='media',id=job['id'],state=job.get('status'),revision=0,draft=fields,published=None)
    return dict(projectId=p['id'],title=p['title'],version=p['version'],entities=clean(entities))


def artifact(c,run,pid,stage,value):
    key=digest([run['id'],pid,stage]);body=snapshot_store.pack(json.dumps(value,ensure_ascii=False),c)
    existing=c.execute('SELECT id FROM experiment_artifacts WHERE id=?',(key,)).fetchone()
    if not existing:c.execute('INSERT INTO experiment_artifacts VALUES (?,?,?)',(key,run['id'],body))
    return key


def read_artifact(c,key):
    row=c.execute('SELECT body FROM experiment_artifacts WHERE id=?',(key,)).fetchone()
    if not row:raise HTTPException(404,'实验产出快照不存在')
    return json.loads(snapshot_store.decode(row[0],c))


def baseline(c,run,pid,p):
    if pid and pid not in run['projects']:
        run['projects'][pid]=dict(title=p['title'] if p else '实验中新建项目',before=artifact(c,run,pid,'before',snapshot(p,c)),after=None)


def append(c,run,event):
    key=event['id'];old=c.execute('SELECT project,body FROM experiment_events WHERE id=?',(key,)).fetchone()
    if old:
        if old[0]!=run['id'] or digest(json.loads(old[1]).get('original'))!=digest(event.get('original')):raise HTTPException(409,'事件编号已用于不同的记录')
        return False
    c.execute('INSERT INTO experiment_events VALUES (?,?,?)',(key,run['id'],json.dumps(event,ensure_ascii=False)));return True


def record_save(c,old,p,action,meta):
    context=_current.get()
    if not context:return
    try:run=load(c,context['runId'],True)
    except HTTPException:return
    if run['status']!='running':return
    baseline(c,run,p['id'],old)
    changed=[k for k,r in p.get('workspace',{}).get('entities',{}).items() if not old or r.get('draft')!=old.get('workspace',{}).get('entities',{}).get(k,{}).get('draft')]
    eid=digest([run['id'],p['id'],p['version'],action,context['requestId']])
    event=dict(id=eid,kind='server_action',page=context.get('page',''),projectId=p['id'],clientId=context['clientId'],elapsedMs=max(0,now()-run['startedAt']),receivedAt=now(),data=clean(dict(action=action,version=p['version'],changedKeys=changed,metadata=meta or {})),original=dict(action=action,version=p['version']))
    if changed:
        partial=snapshot(p);partial['entities']={k:v for k,v in partial['entities'].items() if k in changed}
        event['data']['artifactId']=artifact(c,run,p['id'],'version-'+str(p['version']),partial)
    append(c,run,event);store(c,run)


def union(intervals):
    result=[]
    for start,end in sorted(intervals):
        if end<=start:continue
        if result and start<=result[-1][1]:result[-1][1]=max(result[-1][1],end)
        else:result.append([start,end])
    return sum(end-start for start,end in result)


def output_diff(before,after,pid):
    def content(row):
        value=copy.deepcopy(row)
        if value and value.get('kind')=='material':
            for stage in ('draft','published'):
                structured=(value.get(stage) or {}).get('structured')
                if isinstance(structured,dict):
                    structured.pop('summaryBlocks',None)
                    for field in ('personRedirects','mergedNames','summaryOverrides'):
                        if not structured.get(field):structured.pop(field,None)
        return value
    out=[]
    for key in sorted(set(before['entities'])|set(after['entities'])):
        a=before['entities'].get(key);b=after['entities'].get(key)
        if content(a)==content(b):continue
        if a and b and a.get('draft')==b.get('draft') and a.get('published')==b.get('published') and a.get('state')==b.get('state'):continue
        row=b or a;data=(row or {}).get('draft') or {};name=data.get('name') or data.get('title') or row['id']
        out.append(dict(projectId=pid,key=key,kind=row['kind'],name=name,change='created' if a is None else 'removed' if b is None or b.get('state')=='deleted' else 'updated',before=a,after=b))
    return out


def public_run(run):return {k:v for k,v in run.items() if k not in ('projects','startSignature')}


class Start(BaseModel):
    requestId:str=Field(min_length=1,max_length=100)
    clientId:str=Field(min_length=1,max_length=100)
    name:str=Field(default='',max_length=160)
    projectId:str|None=None
    page:str=Field(default='overview',max_length=40)

class Event(BaseModel):
    id:str=Field(min_length=1,max_length=100)
    kind:str=Field(min_length=1,max_length=40)
    page:str=Field(default='',max_length=40)
    projectId:str|None=None
    clientId:str=Field(min_length=1,max_length=100)
    sequence:int=Field(ge=0)
    elapsedMs:int=Field(ge=0)
    data:dict=Field(default_factory=dict)

class Batch(BaseModel):events:list[Event]=Field(max_length=100)
class End(BaseModel):
    requestId:str=Field(min_length=1,max_length=100)
    elapsedMs:int=Field(ge=0)
class Note(BaseModel):
    id:str=Field(min_length=16,max_length=100)
    runId:str|None=None
    projectId:str|None=None
    page:str=Field(default='',max_length=40)
    text:str=Field(default='',max_length=12000)
    category:Literal['think_aloud','bug','discomfort','idea']='think_aloud'
    image:str=Field(default='',max_length=12_000_000)
    region:dict=Field(default_factory=dict)
    elapsedMs:int|None=Field(default=None,ge=0)


def install(app,get,db,data):
    @app.middleware('http')
    async def context(request:Request,call_next):
        rid=request.headers.get('x-experiment-id','')
        value=dict(runId=rid,clientId=request.headers.get('x-experiment-client','')[:100],requestId=request.headers.get('x-experiment-request','')[:100],page=request.headers.get('x-experiment-page','')[:40]) if rid and len(rid)<=100 and not request.url.path.startswith('/api/experiment') else None
        token=_current.set(value)
        try:return await call_next(request)
        finally:_current.reset(token)

    @app.get('/api/experiments')
    def list_runs():
        with db() as c:rows=[public_run(json.loads(r[0])) for r in c.execute('SELECT body FROM experiment_runs')]
        return sorted(rows,key=lambda r:r['startedAt'],reverse=True)

    @app.post('/api/experiments/start')
    def start(req:Start):
        p=get(req.projectId) if req.projectId else None
        rid=digest(['experiment',req.clientId,req.requestId])[:32]
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT body FROM experiment_runs WHERE id=?',(rid,)).fetchone()
            if old:
                run=json.loads(old[0])
                if run['startSignature']!=digest(req.model_dump()):raise HTTPException(409,'同一请求编号不能开始不同实验')
                return dict(**public_run(run),serverNow=now())
            active=[json.loads(r[0]) for r in c.execute('SELECT body FROM experiment_runs')]
            if any(r['status']=='running' and r['ownerClientId']==req.clientId for r in active):raise HTTPException(409,'此标签页已有进行中的实验，请先结束或恢复记录')
            run=dict(id=rid,name=req.name.strip() or '未命名实验',ownerClientId=req.clientId,projectId=req.projectId,status='running',startedAt=now(),endedAt=None,durationMs=None,projects={},startSignature=digest(req.model_dump()),initialPage=req.page)
            baseline(c,run,req.projectId,p)
            c.execute('INSERT INTO experiment_runs VALUES (?,?,?)',(rid,req.projectId or '',json.dumps(run,ensure_ascii=False)))
            return dict(**public_run(run),serverNow=now())

    @app.post('/api/experiments/{rid}/events')
    def events(rid:str,req:Batch):
        if len(json.dumps(req.model_dump(),ensure_ascii=False).encode())>8*1024*1024:raise HTTPException(413,'单批实验记录过大，请分批发送')
        with db() as c:initial=load(c,rid)
        known=initial['projects'];new_projects={}
        for pid in {e.projectId for e in req.events if e.projectId and e.projectId not in known}:
            try:new_projects[pid]=get(pid)
            except HTTPException:pass
        acknowledged=[]
        with db() as c:
            c.execute('BEGIN IMMEDIATE');run=load(c,rid,True)
            for e in req.events:
                original=clean(e.model_dump());old=c.execute('SELECT project,body FROM experiment_events WHERE id=?',(e.id,)).fetchone()
                if old:
                    if old[0]!=rid or json.loads(old[1]).get('original')!=original:raise HTTPException(409,'事件编号与已有记录冲突')
                    acknowledged.append(e.id);continue
                if run['status']!='running':raise HTTPException(409,'实验已结束；本地未同步记录仍保留')
                if e.projectId in new_projects:baseline(c,run,e.projectId,new_projects[e.projectId])
                value=original.copy();value.update(original=original,receivedAt=now(),elapsedMs=min(e.elapsedMs,max(0,now()-run['startedAt'])+3000))
                if e.kind=='dwell':
                    a=value['data'].get('fromMs',value['elapsedMs']);b=value['data'].get('toMs',value['elapsedMs'])
                    if not isinstance(a,(int,float)) or not isinstance(b,(int,float)) or not 0<=a<=b or b-a>30000:raise HTTPException(422,'前台停留区间无效')
                    value['data']=dict(fromMs=min(int(a),value['elapsedMs']),toMs=min(int(b),value['elapsedMs']))
                append(c,run,value);acknowledged.append(e.id)
            store(c,run)
        return dict(acknowledged=acknowledged,serverNow=now())

    @app.post('/api/experiments/{rid}/end')
    def end(rid:str,req:End):
        with db() as c:initial=load(c,rid)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            current={}
            for pid in sorted(initial['projects']):
                row=c.execute('SELECT body FROM projects WHERE id=?',(pid,)).fetchone()
                current[pid]=json.loads(row[0]) if row else None
            run=load(c,rid,True)
            if run['status']=='ended':return public_run(run)
            if set(run['projects'])-set(current):raise HTTPException(409,'实验仍有内容正在同步，请重试结束')
            for pid,project in run['projects'].items():
                project['after']=artifact(c,run,pid,'after',snapshot(current[pid],c))
            run.update(status='ended',durationMs=min(req.elapsedMs,max(0,now()-run['startedAt'])),endedAt=now(),snapshotCapturedAt=now(),endRequestId=req.requestId)
            store(c,run);return public_run(run)

    def report(rid,include_content=False,include_versions=False):
        with db() as c:
            run=load(c,rid);events=[json.loads(r[0]) for r in c.execute('SELECT body FROM experiment_events WHERE project=?',(rid,))]
            notes=[json.loads(r[0]) for r in c.execute('SELECT body FROM experiment_notes WHERE project=?',(rid,))]
            outputs=[]
            for pid,project in run['projects'].items():
                before=read_artifact(c,project['before'])
                if project['after']:after=read_artifact(c,project['after'])
                else:
                    # Don't call get() while holding a SQLite write transaction.
                    row=c.execute('SELECT body FROM projects WHERE id=?',(pid,)).fetchone();after=snapshot(json.loads(row[0]),c) if row else snapshot(None)
                outputs+=output_diff(before,after,pid)
            versions=[dict(eventId=e['id'],elapsedMs=e['elapsedMs'],projectId=e.get('projectId'),action=e['data'].get('action'),content=read_artifact(c,e['data']['artifactId']) if include_versions else None) for e in events if e['data'].get('artifactId')]
        duration=run['durationMs'] if run['status']=='ended' else max(0,now()-run['startedAt'])
        events.sort(key=lambda e:(e['elapsedMs'],e.get('clientId',''),e.get('sequence',0),e['id']))
        modules={};all_intervals=[];order=[]
        for e in events:
            page=e.get('page') or 'other';m=modules.setdefault(page,dict(page=page,label=PAGES.get(page,page),visits=0,clicks=0,inputs=0,agentMessages=0,intervals=[]))
            if e['kind']=='dwell':
                interval=[max(0,min(duration,e['data']['fromMs'])),max(0,min(duration,e['data']['toMs']))];m['intervals'].append(interval);all_intervals.append(interval)
            if e['kind']=='navigation':
                m['visits']+=1;order.append(dict(page=page,label=m['label'],elapsedMs=e['elapsedMs'],projectId=e.get('projectId')))
            if e['kind']=='click':m['clicks']+=1
            if e['kind']=='input_change':m['inputs']+=1
            if e['kind']=='agent_submit':m['agentMessages']+=1
        for m in modules.values():
            m['foregroundMs']=union(m.pop('intervals'));m['actionsPerMinute']=round((m['clicks']+m['inputs'])*60000/m['foregroundMs'],2) if m['foregroundMs']>=1000 else None
        if not include_content:outputs=[{k:v for k,v in o.items() if k not in ('before','after')} for o in outputs]
        return dict(run=public_run(run),durationMs=duration,foregroundMs=union(all_intervals),modules=list(modules.values()),order=order,eventCount=len(events),outputs=outputs,versionCount=len(versions),contentVersions=versions if include_content else None,notes=notes,events=events if include_content else None,serverNow=now())

    @app.get('/api/experiments/{rid}')
    def get_report(rid:str):return report(rid)

    @app.get('/api/experiments/{rid}/events')
    def timeline(rid:str,offset:int=0,limit:int=100,page:str='',kind:str=''):
        with db() as c:
            load(c,rid);rows=[json.loads(e[0]) for e in c.execute('SELECT body FROM experiment_events WHERE project=?',(rid,))]
        rows=[e for e in rows if (not page or e['page']==page) and (not kind or e['kind']==kind)]
        rows.sort(key=lambda e:(e['elapsedMs'],e.get('clientId',''),e.get('sequence',0),e['id']))
        return dict(total=len(rows),events=rows[max(0,offset):max(0,offset)+min(200,max(1,limit))])

    @app.get('/api/experiments/{rid}/outputs')
    def outputs(rid:str):return report(rid,True)['outputs']

    @app.get('/api/experiments/{rid}/versions')
    def versions(rid:str,offset:int=0,limit:int=50):
        with db() as c:
            load(c,rid);events=[json.loads(e[0]) for e in c.execute('SELECT body FROM experiment_events WHERE project=?',(rid,))]
            events=sorted([e for e in events if e['data'].get('artifactId')],key=lambda e:e['elapsedMs'])
            return [dict(eventId=e['id'],elapsedMs=e['elapsedMs'],projectId=e.get('projectId'),action=e['data'].get('action'),content=read_artifact(c,e['data']['artifactId'])) for e in events[max(0,offset):max(0,offset)+min(50,max(1,limit))]]

    @app.get('/api/experiments/{rid}/export')
    def export(rid:str,format:Literal['json','csv','zip']='json'):
        value=report(rid,True,True)
        for event in value['events']:event.pop('original',None)
        payload=json.dumps(value,ensure_ascii=False,indent=2).encode()
        if format=='json':return Response(payload,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="experiment-{rid}.json"'})
        text=io.StringIO();writer=csv.writer(text);writer.writerow(['elapsed_ms','module','event','project','client','data'])
        for e in value['events']:
            # Prefix formula-like values, including inside JSON exports to CSV.
            fields=[str(e['elapsedMs']),e['page'],e['kind'],e.get('projectId') or '',e.get('clientId',''),json.dumps(e['data'],ensure_ascii=False)]
            writer.writerow(["'"+v if v.startswith(('=','+','-','@','\t','\r')) else v for v in fields])
        csv_bytes=('\ufeff'+text.getvalue()).encode()
        if format=='csv':return Response(csv_bytes,media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="experiment-{rid}.csv"'})
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('experiment.json',payload);z.writestr('events.csv',csv_bytes)
            for note in value['notes']:
                path=Path(data())/'experiment-notes'/(note['id']+'.png')
                if note.get('imageUrl') and path.is_file():z.write(path,'notes/'+note['id']+'.png')
        return Response(out.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="experiment-{rid}.zip"'})

    @app.post('/api/experiment-notes')
    def add_note(req:Note):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{16,100}',req.id):raise HTTPException(422,'便笺编号无效')
        if not req.text.strip() and not req.image:raise HTTPException(422,'请填写便笺或附上截图')
        if req.projectId:get(req.projectId)
        image=None
        if req.image:
            try:
                raw=base64.b64decode(req.image.split(',',1)[-1],validate=True)
                if len(raw)>8*1024*1024:raise ValueError('截图超过8MB')
                with Image.open(io.BytesIO(raw)) as source:
                    if source.width*source.height>20_000_000:raise ValueError('截图尺寸过大')
                    image=source.convert('RGB');image.thumbnail((4096,4096))
            except (ValueError,UnidentifiedImageError,OSError) as exc:raise HTTPException(422,'截图格式无效：'+str(exc))
        signature=digest(req.model_dump());value=dict(id=req.id,runId=req.runId,projectId=req.projectId,page=req.page,text=req.text,category=req.category,region=req.region,elapsedMs=req.elapsedMs,createdAt=now(),imageUrl=f'/api/experiment-notes/{req.id}/image' if image else '',signature=signature)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if req.runId:load(c,req.runId,True)
            old=c.execute('SELECT body FROM experiment_notes WHERE id=?',(req.id,)).fetchone()
            if old:
                previous=json.loads(old[0])
                if previous['signature']!=signature:raise HTTPException(409,'便笺编号已用于不同的内容')
                return previous
            if image:
                folder=Path(data())/'experiment-notes';folder.mkdir(exist_ok=True);path=folder/(req.id+'.png');temp=folder/(req.id+'.part');image.save(temp,format='PNG');temp.replace(path)
            c.execute('INSERT INTO experiment_notes VALUES (?,?,?)',(req.id,req.runId or '',json.dumps(value,ensure_ascii=False)))
        return value

    @app.get('/api/experiment-notes')
    def list_notes(projectId:str=''):
        with db() as c:rows=[json.loads(r[0]) for r in c.execute('SELECT body FROM experiment_notes')]
        return sorted([r for r in rows if not projectId or r.get('projectId')==projectId],key=lambda r:r['createdAt'],reverse=True)

    @app.get('/api/experiment-notes/{nid}/image')
    def note_image(nid:str):
        with db() as c:row=c.execute('SELECT body FROM experiment_notes WHERE id=?',(nid,)).fetchone()
        if not row:raise HTTPException(404,'截图不存在')
        note=json.loads(row[0]);path=Path(data())/'experiment-notes'/(note['id']+'.png')
        if not note.get('imageUrl') or not path.is_file():raise HTTPException(404,'截图不存在')
        return FileResponse(path,media_type='image/png')
