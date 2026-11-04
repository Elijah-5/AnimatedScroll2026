"""Durable local presentation jobs, separate from creation and dialogue state."""
import copy,hashlib,json,os,threading,uuid
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel,Field
from typing import Literal
from . import cutouts,consumption as consume
from .task_runtime import digest

_guard=threading.RLock()
_running={}

class Prepare(BaseModel):
    requestId:str=Field(min_length=1,max_length=100)
    mode:Literal['resume','refresh']='refresh'
    sessionId:str|None=None


def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False));os.replace(temp,path)

def manifest(data,pid,sid):
    path=Path(data)/'experience-presentations'/(digest([pid,sid])+'.json')
    if not path.is_file():return None
    try:
        value=json.loads(path.read_text())
        return value if value['projectId']==pid and value['sessionId']==sid else None
    except (ValueError,KeyError,OSError):return None

def active_count(data):
    prefix=str(Path(data).resolve())
    with _guard:return sum(thread.is_alive() for (root,_),thread in _running.items() if root==prefix)

def install(app,get,db,data,current,create_record,painting_people,available_people,catalog):
    def path(jid):return Path(data())/'experience-preparations'/(jid+'.json')
    def read_job(pid,jid):
        if len(jid)!=64 or any(c not in '0123456789abcdef' for c in jid):raise HTTPException(404,'准备任务不存在')
        try:value=json.loads(path(jid).read_text())
        except (OSError,ValueError):raise HTTPException(404,'准备任务不存在')
        if value['projectId']!=pid:raise HTTPException(404,'准备任务不存在')
        return value
    def public(job):return {k:v for k,v in job.items() if k not in ('requestSignature','catalog','figures','people','imageHash','creationFingerprint','renderFingerprint')}
    def session_owner(pid,sid):
        with db() as c:row=c.execute('SELECT project FROM experience_sessions WHERE id=?',(sid,)).fetchone()
        if not row or row[0]!=pid:raise HTTPException(404,'体验记录不存在')
    def process(root,job):
        jid=job['id'];target=Path(root)/'experience-preparations'/(jid+'.json')
        def save(**changes):
            with _guard:
                latest=json.loads(target.read_text())
                if latest['state']=='cancelled':raise InterruptedError('已取消准备，成功缓存已保留')
                latest.update(changes);atomic(target,latest);return latest
        try:
            # Never read live creation here. Source and inputs were pinned at submission.
            with db() as c:body=c.execute('SELECT body FROM experience_sessions WHERE id=?',(job['sessionId'],)).fetchone()[0]
            p=json.loads(body)['contentSnapshot'];p=copy.deepcopy(p)
            mat=p['workspace']['entities']['material:main'];mat['published']['image']=job['image'];mat['draft']['image']=job['image']
            save(state='running',stage='准备人物轮廓',completed=0,total=len(job['figures']),errors=[])
            def progress(row,index,total):save(completed=index,total=total,current=next((p['name'] for p in job['figures'] if p['annotationId']==row['annotationId']),'人物轮廓'))
            rows=cutouts.prepare(p,job['figures'],root,progress=progress)
            errors=[dict(annotationId=r['annotationId'],name=next((p['name'] for p in job['figures'] if p['annotationId']==r['annotationId']),'人物'),message=r['error']) for r in rows if r.get('error')]
            if errors:save(state='failed',stage='人物轮廓准备未完成',errors=errors);return
            for r in rows:r['url']=f"/api/projects/{job['projectId']}/experience/assets/{r['key']}.png"
            value=dict(schema=1,projectId=job['projectId'],sessionId=job['sessionId'],id=job['renderFingerprint'],creationFingerprint=job['creationFingerprint'],image=job['image'],imageHash=job['imageHash'],policy=cutouts.POLICY,figures=job['figures'],people=job['people'],cutouts=rows,mediaCatalog=job['catalog'])
            with _guard:
                save(stage='本地资源已准备',completed=len(rows))
                atomic(Path(root)/'experience-presentations'/(digest([job['projectId'],job['sessionId']])+'.json'),value)
                for r in rows:
                    atomic(Path(root)/'experience-asset-owners'/(digest([job['projectId'],r['key']])+'.json'),dict(projectId=job['projectId'],sessionId=job['sessionId'],key=r['key']))
                save(state='ready',stage='等待载入图片与交互',manifestId=value['id'])
        except InterruptedError:pass
        except Exception as exc:
            try:save(state='failed',stage='作品准备失败',errors=[dict(message=str(exc)[:250])])
            except InterruptedError:pass
        finally:
            with _guard:_running.pop((str(Path(root).resolve()),jid),None)
    def launch(job):
        root=str(Path(data()).resolve());key=(root,job['id'])
        with _guard:
            if key in _running:return
            job.update(state='queued',stage='等待准备',completed=0,errors=[]);atomic(path(job['id']),job)
            worker=threading.Thread(target=process,args=(root,job),daemon=True,name='experience-'+job['id'][:10]);_running[key]=worker;worker.start()
    def state(pid,jid):
        with _guard:
            job=read_job(pid,jid)
            if job['state'] in ('running','queued') and (str(Path(data()).resolve()),jid) not in _running:
                job.update(state='interrupted',stage='准备已中断，请重试未完成项');atomic(path(jid),job)
            return job
    @app.post('/api/projects/{pid}/experience/preparations')
    def prepare(pid:str,req:Prepare):
        root=Path(data());receipt=root/'experience-preparation-requests'/(digest([pid,req.requestId])+'.json');signature=digest(req.model_dump())
        with _guard:
            if receipt.is_file():
                saved=json.loads(receipt.read_text())
                if saved['signature']!=signature:raise HTTPException(409,'请求编号已用于其他准备操作')
                return public(state(pid,saved['id']))
            old_manifest=None
            if req.sessionId:
                session_owner(pid,req.sessionId);old_manifest=manifest(root,pid,req.sessionId)
            if req.mode=='resume' and not req.sessionId:raise HTTPException(422,'请选择需要恢复的体验')
            p,s=current(pid,req.sessionId) if req.mode=='resume' else (get(pid),None)
            if req.mode=='refresh' and (p.get('archived') or not available_people(p)):raise HTTPException(422,'暂无准备好的角色，请前往人物档案准备对话设定')
            if req.mode=='resume' and old_manifest:
                jid=digest([pid,req.sessionId,old_manifest['id'],'restore'])
                job=dict(id=jid,projectId=pid,sessionId=req.sessionId,state='ready',stage='恢复已准备作品',completed=len(old_manifest['cutouts']),total=len(old_manifest['cutouts']),errors=[],manifestId=old_manifest['id'])
                atomic(path(jid),job);atomic(receipt,dict(signature=signature,id=jid));return public(job)
            try:source=cutouts.source(p,root);raw=source.read_bytes()
            except (ValueError,OSError) as exc:raise HTTPException(422,'原画读取失败，请在资料页检查图片：'+str(exc)[:180])
            image_hash=hashlib.sha256(raw).hexdigest()
            image_path=root/('experience-source-'+image_hash+source.suffix.lower())
            if not image_path.exists():
                temp=image_path.with_suffix(image_path.suffix+'.'+uuid.uuid4().hex+'.tmp');temp.write_bytes(raw);os.replace(temp,image_path)
            legacy=bool(s and s.get('dialogueVersion',1)<2)
            figures=painting_people(p,legacy);people=available_people(p,legacy)
            media=catalog(p);content=consume.snapshot(p);render=digest([content,image_hash,figures,media,cutouts.POLICY])
            same=old_manifest and old_manifest['id']==render
            sid=req.sessionId if req.mode=='resume' or same else None
            # New viewers must never inherit each other's chats merely because
            # they opened identical production content. Only exact requests dedupe.
            jid=digest([pid,req.sessionId,render,req.mode,req.requestId if not req.sessionId else None])
            if path(jid).exists():
                job=state(pid,jid);atomic(receipt,dict(signature=signature,id=jid));return public(job)
            if sid is None:sid=create_record(p,True,digest([pid,signature])[:24])['id']
            job=dict(id=jid,projectId=pid,sessionId=sid,state='ready' if same else 'queued',stage='复用已准备作品' if same else '读取作品',completed=len(figures) if same else 0,total=len(figures),errors=[],image='/api/images/'+image_path.name,imageHash=image_hash,figures=figures,people=people,catalog=media,creationFingerprint=content,renderFingerprint=render)
            atomic(path(jid),job);atomic(receipt,dict(signature=signature,id=jid))
            if not same:launch(job)
            return public(job)
    @app.get('/api/projects/{pid}/experience/preparations/{jid}')
    def inspect(pid:str,jid:str):return public(state(pid,jid))
    @app.get('/api/projects/{pid}/experience/assets/{key}.png')
    def asset(pid:str,key:str):
        from fastapi.responses import FileResponse
        if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise HTTPException(404)
        try:owner=json.loads((Path(data())/'experience-asset-owners'/(digest([pid,key])+'.json')).read_text())
        except (OSError,ValueError):raise HTTPException(404)
        session_owner(pid,owner['sessionId']);m=manifest(data(),pid,owner['sessionId'])
        if not m or key not in {r['key'] for r in m['cutouts']}:raise HTTPException(404)
        target=Path(data())/'experience-cutouts'/(key+'.png')
        if not target.is_file():raise HTTPException(404,'人物轮廓文件缺失，请重试准备')
        return FileResponse(target,media_type='image/png',headers={'Cache-Control':'private, max-age=31536000, immutable'})
    @app.post('/api/projects/{pid}/experience/preparations/{jid}/retry')
    def retry(pid:str,jid:str):
        with _guard:
            job=state(pid,jid)
            if job['state'] not in ('queued','running'):
                # Restore jobs are receipts only. Reconstruct explicit retry inputs from the pinned session.
                if 'figures' not in job:
                    p,s=current(pid,job['sessionId']);m=manifest(data(),pid,s['id'])
                    if not m:raise HTTPException(422,'准备清单丢失，请刷新作品')
                    job.update(figures=m['figures'],people=m['people'],catalog=m['mediaCatalog'],image=m['image'],imageHash=m['imageHash'],creationFingerprint=m['creationFingerprint'],renderFingerprint=m['id'])
                launch(job)
            return public(job)
    @app.post('/api/projects/{pid}/experience/preparations/{jid}/cancel')
    def cancel(pid:str,jid:str):
        with _guard:
            job=state(pid,jid)
            if job['state']!='ready':job.update(state='cancelled',stage='已取消准备，缓存保留');atomic(path(jid),job)
            return public(job)
    app.state.experience_preparation_count=lambda:active_count(data())
    app.state.experience_manifest=lambda pid,sid:manifest(data(),pid,sid)
    def recover():
        folder=Path(data())/'experience-preparations'
        if not folder.exists():return
        with _guard:
            for file in folder.glob('*.json'):
                try:
                    job=json.loads(file.read_text())
                    if job['state'] in ('running','queued') and (str(Path(data()).resolve()),job['id']) not in _running:
                        job.update(state='interrupted',stage='准备已中断，请重试未完成项');atomic(file,job)
                except (OSError,ValueError,KeyError):continue
    app.router.add_event_handler('startup',recover)
