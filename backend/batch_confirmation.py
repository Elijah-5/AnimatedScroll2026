"""Preview and atomically confirm eligible content, without model side effects."""
import copy
from typing import Literal
from pydantic import BaseModel,Field
from fastapi import HTTPException
from . import workspace as ws,revisions
from .task_runtime import digest

class Preview(BaseModel):
    version:int
    scope:Literal['page','project']='project'
    page:Literal['library','characters','outline','clues','storyboards']='library'
    keys:list[str]|None=None
class Commit(Preview):
    previewHash:str
    requestId:str=Field(min_length=1,max_length=100)


def locked(p,path):
    for job in p['workspace'].get('jobs',[]):
        if job.get('state',job.get('status')) not in ('queued','running'):continue
        for target in job.get('writeSet',[]):
            if path==target or path.startswith(target+'/') or target.startswith(path+'/'):return True
    return False


def prepare(project,req):
    p=copy.deepcopy(project);w=ws.ensure(p);eligible=[];skipped=[]
    choose=lambda key,page:(req.scope=='project' or req.page==page) and (req.keys is None or key in req.keys)
    def skip(key,name,reason):skipped.append(dict(key=key,name=name,reason=reason))
    if req.scope=='project' or req.page=='library':
        mat=w['entities']['material:main'];people={r['id']:r for r in w['entities'].values() if r['kind']=='character' and r['state']!='deleted'}
        for a in mat['draft'].get('annotations',[]):
            k='identity:'+a['id']
            if a.get('kind')!='character' or not choose(k,'library') or a.get('identityConfirmed') and not a.get('needsReview'):continue
            person=people.get(a.get('characterId'));instances=[v for v in mat['draft'].get('annotations',[]) if v.get('characterId')==a.get('characterId')]
            ordinal='（'+str(next(i+1 for i,v in enumerate(instances) if v['id']==a['id']))+'）' if len(instances)>1 else ''
            name=(ws.named(person) if person else '未匹配人物')+ordinal+'的画面对应'
            match=next((m for m in mat['draft'].get('matches',[]) if m.get('annotationId')==a['id']),{})
            if locked(p,'/annotations') or locked(p,'/workspace/entities/material:main'):skip(k,name,'人物对应正在生成');continue
            if not person:skip(k,name,'尚未选择有效角色');continue
            if match.get('conflicts') or match.get('rejectionReason'):skip(k,name,'对应存在明确冲突，请单独核对');continue
            a.update(identityConfirmed=True,needsReview=False)
            for target in p.get('annotations',[]):
                if target['id']==a['id']:target.update(identityConfirmed=True,needsReview=False)
            for target in mat['draft'].get('matches',[]):
                if target.get('annotationId')==a['id']:target.update(confirmed=True,stale=False)
            eligible.append(dict(key=k,name=name,action='identity'))
    for kind in ('material','character','intent','experience_config','plot','clue','knowledge','persona','storyboard'):
        records=[r for r in list(w['entities'].values()) if r['kind']==kind and r['state']!='deleted']
        for r in records:
            k=ws.key(kind,r['id']);name=ws.named(r)
            if kind=='knowledge':
                person=w['entities'].get('character:'+r['id']);name=(ws.named(person) if person else '未关联人物')+'的知识库'
            elif kind=='storyboard':name+='分镜'
            elif kind=='persona':name=ws.named(w['entities'].get('character:'+r['id'],r))+'的入画角色设定'
            elif kind=='clue':name+='线索'
            if not choose(k,ws.PAGES[kind]):continue
            notices=revisions.warnings(w,r)
            if ws.valid(r) and not ws.dirty(r) and not any(not v['reviewed'] for v in notices):continue
            if locked(p,'/workspace/entities/'+k):skip(k,name,'该内容正在生成');continue
            if kind=='knowledge' and not r['draft'].get('clueIds'):skip(k,name,'请先配置至少一条知识绑定；不会自动采用模型建议');continue
            before=dict(revision=r['revision'],refs=copy.deepcopy(r.get('refs',[])))
            try:ws.commit(p,w,r,True)
            except (ValueError,KeyError,TypeError) as exc:skip(k,name,str(exc));continue
            eligible.append(dict(key=k,name=name,action='publish' if r['revision']!=before['revision'] else 'acknowledge',versionWarnings=notices))
    plan=dict(projectId=p['id'],version=req.version,scope=req.scope,page=req.page,keys=req.keys,eligible=eligible,skipped=skipped,excluded=['AI一致性建议','模型建议采用','模型调用及视频生成'])
    plan['previewHash']=digest(plan)
    return p,plan


def install(app,get,save,response):
    @app.post('/api/projects/{pid}/studio/batch-confirm/preview')
    def preview(pid:str,req:Preview):
        p=get(pid)
        if p['version']!=req.version:raise HTTPException(409,'项目版本已变化，请重新预览批量清单')
        return prepare(p,req)[1]
    @app.post('/api/projects/{pid}/studio/batch-confirm')
    def confirm(pid:str,req:Commit):
        p=get(pid);identity=digest(req.model_dump());receipts=p['workspace'].get('batchReceipts',{})
        if req.requestId in receipts:
            entry=receipts[req.requestId]
            if entry['requestHash']!=identity:raise HTTPException(409,'请求编号已用于其他批量操作')
            return dict(project=response(p),result=entry['result'],replayed=True)
        if p['version']!=req.version:raise HTTPException(409,'项目版本已变化，未执行批量确认')
        updated,plan=prepare(p,req)
        if req.previewHash!=plan['previewHash']:raise HTTPException(409,'批量清单已变化，请重新预览；未覆盖任何内容')
        if not plan['eligible']:return dict(project=response(p),result=plan,replayed=False)
        updated['workspace'].setdefault('batchReceipts',{})[req.requestId]=dict(requestHash=identity,result=plan)
        ws.mirror(updated)
        try:updated=save(updated,req.version,'studio:batch_confirm',dict(requestId=req.requestId,result=plan))
        except HTTPException as exc:
            if exc.status_code==409:
                latest=get(pid);receipt=latest['workspace'].get('batchReceipts',{}).get(req.requestId)
                if receipt and receipt['requestHash']==identity:return dict(project=response(latest),result=receipt['result'],replayed=True)
            raise
        return dict(project=response(updated),result=plan,replayed=False)
