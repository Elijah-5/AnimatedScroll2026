"""Content availability and human review are independent. Stable, coarse review units."""
import copy,json,re,hashlib
from functools import lru_cache
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel,Field,ValidationError
from . import workspace as ws,revisions,task_runtime as tr

ORDER=['library','outline','clues','characters','storyboards','experience']
TITLES=dict(library='资料与基础人物',outline='剧本大纲',clues='线索库',characters='人物档案与对话设定',storyboards='分镜管理',experience='欣赏作品')
IGNORE={'id','basisChanged','stale','needsReview','identityConfirmed','identityManual','faceConfirmed','promptConfigHash','confirmed','state','status','revision','version','sourceVersion','imageVersion','activation','humanReviewed','generatedValue','origin','time','parseStatus','parseVersion','quality','engine','lastAdoption','inputHash','modelCalls','validationWarnings','legacyTables','legacyVersions','source_start','source_end'}
ROOT_FIELDS={'authoringDrafts','image','imageVersion','sources','annotations','observations','matches','documents','documentAnalysis','materialInputs','materialInputOrigins','targetArtwork','visualDetectionProposal','visualOverview'}

def semantic(v):
    if isinstance(v,dict):return {k:semantic(x) for k,x in v.items() if k not in IGNORE}
    if isinstance(v,list):return [semantic(x) for x in v]
    return v

def records(p,kind):return [r for r in ws.ensure(p)['entities'].values() if r['kind']==kind and r['state']!='deleted']
def meta(p):return p['workspace'].setdefault('reviewUnits',dict(policy=1,members={},units={},receipts={}))
def record_unit(r):return {'material':'library:main','intent':'outline:main','experience_config':'outline:main','plot':'outline:main','clue':'clues:main','knowledge':'character:'+r['id'],'persona':'character:'+r['id'],'character':'character:'+r['id'],'storyboard':'storyboard:'+r['id']}.get(r['kind'])

def visual_groups(p):
    w=ws.ensure(p);roles={r['id'] for r in records(p,'character') if r['draft'].get('roleType')=='group'}
    groups={}
    for a in w['entities']['material:main']['draft'].get('annotations',[]):
        if a.get('kind')=='character' and a.get('characterId') in roles:groups.setdefault(a['characterId'],[]).append(a)
    return groups

def members(p,unit):
    w=ws.ensure(p);kind,_,rid=unit.partition(':');out={}
    if kind=='visual':
        a=next((a for a in w['entities']['material:main']['draft'].get('annotations',[]) if a['id']==rid),None)
        if a:out[unit]=a
        observations=[o for o in w['entities']['material:main']['draft'].get('observations',[]) if o.get('annotationId')==rid]
        if observations:out['observation:'+rid]=observations
    elif kind=='visual-group':
        mat=w['entities']['material:main']['draft']
        for a in mat.get('annotations',[]):
            if a.get('kind')=='character' and a.get('characterId')==rid:out.update(members(p,'visual:'+a['id']))
        shared=mat.get('visualGroups',{}).get(rid)
        if shared:out['visual-shared:'+rid]=shared
    elif kind=='documents':
        out['documents:main']=dict(documents=p.get('documents',[]),sources=[s for s in p['sources'] if s.get('documentId')],analysis=p.get('documentAnalysis') or {})
    elif kind=='video':
        job=next((v for v in p.get('_reviewVideos',[]) if v['id']==rid),None)
        if job:out[unit]={k:job.get(k) for k in ('requestFingerprint','storyboardId','parameters','model','prompt')}
    elif kind=='library':
        m=w['entities']['material:main']['draft'];out['library:main']=dict(structured=m.get('structured'),materialInputs=m.get('materialInputs',{}))
    else:
        kinds={'outline':{'intent','plot','experience_config'},'clues':{'clue'},'character':{'character','knowledge','persona'},'storyboard':{'storyboard'}}.get(kind,set())
        for k,r in w['entities'].items():
            if r['state']=='deleted':continue
            if r['kind'] in kinds and (kind not in ('character','storyboard') or r['id']==rid):out[k]=r['draft']
            if kind=='outline' and r['kind']=='clue' and r['draft'].get('type')=='narrative':out[k]=r['draft']
    return out

def fingerprint(values):return tr.digest(semantic(values))

def comparable_basis(basis):
    # Older receipts included presentation-only folder IDs in clue dependencies.
    if not isinstance(basis,dict):return basis
    return {k:({f:v for f,v in item.items() if f!='parentId'} if k.startswith('clue:') and isinstance(item,dict) else item) for k,item in basis.items()}

def dependencies(p,unit):
    """Only selected roles, linked clues/plots, image and actual quoted spans count."""
    if unit.startswith('video:') and asset_data:
        from . import video
        job=next((v for v in p.get('_reviewVideos',[]) if v['id']==unit.split(':',1)[1]),{})
        try:
            inputs,_=video.shot_inputs(p,job['storyboardId'],asset_data())
            text=p['workspace'].get('media',{}).get(job['storyboardId'],{}).get('prompt','')
            return dict(request=video.approval_hash(inputs,text))
        except (ValueError,KeyError):return {}
    values=members(p,unit);w=p['workspace'];refs=[];cids=set();pids=set();clids=set();image=False
    def visit(v):
        nonlocal image
        if isinstance(v,list):
            for x in v:visit(x)
        elif isinstance(v,dict):
            if v.get('quote') and v.get('sourceId'):refs.append(v)
            cids.update(v.get('characterIds',[]));pids.update(v.get('plotIds',[]));clids.update(v.get('clueIds',[]))
            if v.get('clueId'):clids.add(v['clueId'])
            for x in v.values():visit(x)
    visit(values)
    if unit.startswith(('visual:','visual-group:','storyboard:')):image=True
    if unit.startswith('visual-group:'):cids.add(unit.split(':',1)[1])
    result={}
    for ref in refs:
        s=next((s for s in p['sources'] if s['id']==ref['sourceId']),None)
        if s:result['source:'+s['id']+':'+tr.digest(ref['quote'])[:12]]=dict(quote=ref['quote'] if ref['quote'] in s['text'] else None,citation=s.get('citation',''))
    for cid in cids:
        r=w['entities'].get('character:'+cid)
        if r and 'character:'+cid not in values:result['character:'+cid]={k:r['draft'].get(k) for k in ('identity','summary')}
    for prefix,ids in [('clue',clids),('plot',pids)]:
        for rid in ids:
            k=prefix+':'+rid;r=w['entities'].get(k)
            if r and k not in values:result[k]=semantic({f:v for f,v in r['draft'].items() if f not in ('name','title','parentId')})
    if image:result['image']=image_fingerprint(p)
    return result

def problems(p,unit,values):
    w=p['workspace'];kind=unit.split(':')[0];issues=[]
    if kind=='visual':
        a=values.get(unit,{})
        if not p.get('image'):issues.append('请上传画作图片')
        if not a.get('characterId') or not w['entities'].get('character:'+a.get('characterId','')):issues.append('请选择此画中人物对应的角色')
        if not all(isinstance(a.get(k),(int,float)) for k in ('x','y','w','h')) or a.get('w',0)<=0 or a.get('h',0)<=0:issues.append('请补充有效人物框')
    elif kind=='visual-group':
        group=visual_groups(p).get(unit.split(':',1)[1],[])
        if not group:issues.append('此群体已无关联的画中人物，请重新选择角色')
        for i,a in enumerate(group):
            issues.extend('身影 '+str(i+1)+'：'+message for message in problems(p,'visual:'+a['id'],members(p,'visual:'+a['id'])))
    elif kind=='video':
        job=next((v for v in p.get('_reviewVideos',[]) if v['id']==unit.split(':',1)[1]),{})
        if job.get('status')!='succeeded':issues.append('视频尚未生成完成')
        elif asset_data and not (asset_data()/'videos'/(job['id']+'.mp4')).is_file():issues.append('视频文件缺失，请重新下载原任务')
    elif kind=='documents':
        if not p.get('documents') and not p.get('sources'):issues.append('上传文献文件或输入资料文本')
        elif not p.get('documentAnalysis') and not any(p.get('materialInputs',{}).get(k) for k in ('background','relationships','narrative')):issues.append('尚未整理文献资料')
    elif kind=='library':
        m=w['entities']['material:main']['draft']
        if not m.get('structured'):issues.append('尚未整理作品资料库')
    elif kind=='character':
        cid=unit.split(':',1)[1];r=w['entities'].get('character:'+cid)
        if not r or not r['draft'].get('name','').strip():issues.append('请填写姓名或称谓')
        role=w['entities'].get('persona:'+cid)
        if r and r['draft'].get('depictionScope')!='background' and (not role or not role['draft'].get('prompt','').strip()):issues.append('尚未生成人物对话设定')
    elif kind=='outline':
        r=w['entities']['intent:main']
        if not r['draft'].get('theme') or not r['draft'].get('goal'):issues.append('尚未生成创作方向')
        if not records(p,'plot'):issues.append('尚未生成剧情')
    elif kind=='clues' and not records(p,'clue'):issues.append('尚未整理线索')
    if kind in ('outline','clues','storyboard','character'):
        for key,value in values.items():
            r=w['entities'].get(key)
            if not r:continue
            # An absent knowledge binding is optional; a nonexistent reference is not.
            if r['kind']=='knowledge' and not value.get('clueIds'):continue
            checks=ws.validate_entity(p,w,r)
            if r['kind']=='character':checks=[v for v in checks if '上游尚未确认' not in v]
            issues.extend(ws.named(r)+'：'+issue for issue in checks)
    return list(dict.fromkeys(issues))

def inferred_origin(p,key,value):
    rm=p.get('workspace',{}).get('reviewUnits',{}).get('members',{}).get(key,{})
    if rm.get('hash')==fingerprint(value):return rm.get('origin','unknown')
    r=p['workspace']['entities'].get(key,{})
    method=r.get('activation',{}).get('method')
    if method=='human' and r.get('published')==value:return 'human'
    if method=='auto':return 'AI'
    if method=='manual':return 'AI' if r.get('generationRefs') or r.get('autoValues') or r.get('regenerated') else 'unknown'
    if key.startswith('visual:'):
        if value.get('activation',{}).get('method')=='human':return 'human'
        if value.get('activation',{}).get('method')=='auto':return 'AI'
    if key.startswith('observation:'):return 'AI'
    if key.startswith('video:'):return 'AI'
    if key=='documents:main' and p.get('documentAnalysis'):return 'AI'
    if key=='library:main' and r=={} and p['workspace']['entities']['material:main'].get('activation',{}).get('method')=='auto':return 'AI'
    if r.get('generationRefs') or r.get('regenerated') or r.get('suggestion'):return 'AI'
    return 'unknown'

def unit(p,uid):
    values=members(p,uid);saved=p['workspace'].get('reviewUnits',{});issues=problems(p,uid,values)
    hard_issues=list(issues)
    origins={key:inferred_origin(p,key,value) for key,value in values.items()}
    # Reusable receipts follow shared members across pages.
    for key,value in values.items():
        receipt=saved.get('members',{}).get(key,{})
        if receipt.get('reviewedHash')==fingerprint(value):origins[key]='human'
    unknown=[k for k,v in origins.items() if v=='unknown']
    if not issues and unknown:issues=['旧内容缺少可恢复的来源记录，可查看后统一确认']
    status='incomplete' if issues else 'human' if origins and all(v=='human' for v in origins.values()) else 'AI'
    basis=dependencies(p,uid);old=saved.get('units',{}).get(uid,{});outdated=status!='incomplete' and old.get('basis') is not None and comparable_basis(old['basis'])!=comparable_basis(basis)
    if uid.startswith('visual-group:') and old.get('basis') is None:
        outdated=status!='incomplete' and any(saved.get('units',{}).get('visual:'+a['id'],{}).get('basis') is not None and saved['units']['visual:'+a['id']]['basis']!=dependencies(p,'visual:'+a['id']) for a in visual_groups(p).get(uid.split(':',1)[1],[]))
    name=''
    if uid.startswith('visual-group:'):
        cid=uid.split(':',1)[1];role=p['workspace']['entities'].get('character:'+cid,{})
        name=role.get('draft',{}).get('name','群体')+'（'+str(len(visual_groups(p).get(cid,[])))+'个身影）'
    return dict(name=name,id=uid,status=status,outdated=outdated,contentHash=fingerprint(values),dependencyHash=tr.digest(basis),issues=issues,canConfirm=bool(values) and not hard_issues,members=list(values),ready=bool(values) and not hard_issues)

def unit_ids(p):
    ws.ensure(p);ids=['documents:main','library:main','outline:main','clues:main']
    groups=visual_groups(p)
    ids += ['visual:'+a['id'] for a in p['workspace']['entities']['material:main']['draft'].get('annotations',[]) if a.get('kind')=='character' and a.get('characterId') not in groups]
    ids += ['visual-group:'+cid for cid in groups]
    ids += ['character:'+r['id'] for r in records(p,'character') if r['draft'].get('depictionScope')!='background']
    ids += ['storyboard:'+r['id'] for r in records(p,'storyboard')]
    ids += ['video:'+j['id'] for j in p.get('_reviewVideos',[])]
    return ids

def all_units(p):return {uid:unit(p,uid) for uid in unit_ids(p)}

def make_available(p,origin='auto'):
    """Automatic operational snapshots are not human review receipts."""
    w=ws.ensure(p)
    mat=w['entities']['material:main']
    for s in mat['draft'].get('sources',[]):s['confirmed']=True
    for a in mat['draft'].get('annotations',[]):
        if a.get('characterId') and w['entities'].get('character:'+a['characterId']):a.update(identityConfirmed=True,needsReview=False,confirmed=True)
    for o in mat['draft'].get('observations',[]):o.update(confirmed=True,stale=False)
    for _ in range(2):
        for kind in ('material','character','experience_config','intent','plot','clue','knowledge','persona','storyboard'):
            for r in records(p,kind):
                if kind=='knowledge' and not r['draft'].get('clueIds'):r['draft']['profileOnly']=True
                if kind=='storyboard' and r['draft'].get('region'):
                    r['draft']['participantsConfirmed']=True
                    if all(r['draft'].get(f,'').strip() for f in ('prompt','startFrame','endFrame')):r['draft']['promptConfigHash']=ws.config_hash(r['draft'])
                if not ws.dirty(r):continue
                try:
                    w['_autoEnabling']=True;ws.commit(p,w,r,True)
                    r['activation']=dict(method='manual' if origin=='manual' else 'auto',revision=r['revision'])
                except (ValueError,KeyError,TypeError):pass
                finally:w.pop('_autoEnabling',None)
    ws.mirror(p)

def preserve_origins(before,after):
    """Availability-only normalization must retain a proven AI origin."""
    info=meta(after)
    for uid in set(unit_ids(before))&set(unit_ids(after)):
        old=members(before,uid)
        for key,value in members(after,uid).items():
            if key in old and fingerprint(old[key])==fingerprint(value) and inferred_origin(before,key,old[key])=='AI' and inferred_origin(after,key,value)=='unknown':
                info['members'][key]=dict(info['members'].get(key,{}),hash=fingerprint(value),origin='AI')

def changed_members(before,after,origin):
    preserve_origins(before,after)
    info=meta(after);ids=set(unit_ids(before))|set(unit_ids(after))
    previous_members={key:value for uid in unit_ids(before) for key,value in members(before,uid).items()}
    for uid in ids:
        a=members(before,uid);b=members(after,uid)
        for key,value in b.items():
            if key not in a and key in previous_members:a[key]=previous_members[key]
            if fingerprint(a.get(key))==fingerprint(value):continue
            old=info['members'].get(key,{})
            previous=inferred_origin(before,key,a.get(key,{}))
            if old.get('reviewedHash')==fingerprint(a.get(key)):previous='human'
            effective='human' if origin=='manual' and (previous=='human' or key not in a or not a.get(key)) else origin if origin!='manual' else 'AI' if previous=='AI' else 'human'
            if origin=='manual' and previous=='unknown' and before.get('workspace',{}).get('reviewUnits',{}).get('legacyAuditRecovered') and a.get(key):effective='unknown'
            info['members'][key]=dict(hash=fingerprint(value),origin=effective)
            if effective=='human':info['members'][key]['reviewedHash']=fingerprint(value)
        if origin=='AI' and fingerprint(a)!=fingerprint(b):info['units'][uid]=dict(basis=dependencies(after,uid))


def workflow(p):
    units=all_units(p);pages=[];mat=p['workspace']['entities']['material:main'];base=bool(mat.get('published'))
    available_clues=[r for r in records(p,'clue') if ws.valid(r)]
    from .experience import available_people
    people=available_people(p)
    raw=bool(p.get('documents') or p.get('sources') or mat['draft'].get('literatureInput',{}).get('text','').strip() or any(p.get('materialInputs',{}).get(k,'').strip() for k in ('background','relationships','narrative')))
    predicates=dict(library=bool(p.get('image')) and raw,outline=base,clues=base,characters=base and bool(records(p,'character')),storyboards=bool(available_clues),experience=bool(people))
    for page in ORDER:
        ids=[uid for uid in units if (page=='library' and uid.startswith(('visual:','visual-group:','documents:','library:'))) or (page=='characters' and uid.startswith('character:')) or (page=='outline' and uid=='outline:main') or (page=='clues' and uid=='clues:main') or (page=='storyboards' and uid.startswith(('storyboard:','video:')))]
        if page=='experience':ids=[uid for uid in units if uid.startswith('character:')]
        rows=[units[i] for i in ids];done=sum(r['ready'] for r in rows)
        complete=bool(rows) and done==len(rows)
        if page=='library':complete=base and units['library:main']['ready'] and units['documents:main']['ready']
        if page=='clues':
            done=sum(usable for usable in [ws.valid(r) for r in records(p,'clue')]);complete=bool(available_clues)
        if page=='characters':complete=bool(people)
        if page=='storyboards':complete=any(u['ready'] for u in rows if u['id'].startswith('storyboard:')) and all(u['ready'] for u in rows if u['id'].startswith('storyboard:'))
        if page=='experience':
            complete=bool(people);done=len({person['characterId'] for person in people})
        blocker='' if predicates[page] else {'library':'请上传画作并输入或上传资料','outline':'请先整理资料','clues':'请先整理资料','characters':'请先从资料提取基础人物','storyboards':'请先生成至少一条可用线索','experience':'请先准备至少一位人物的对话设定'}[page]
        pages.append(dict(id=page,name=TITLES[page],complete=complete,done=done,total=len(records(p,'clue')) if page=='clues' else len(rows),unitIds=ids,canGenerate=predicates[page],blocker=blocker,issues=[dict(unitId=u['id'],message=reason) for u in rows for reason in u['issues']],reviewCount=sum(u['status']=='AI' or u['outdated'] for u in rows)))
    for index,page in enumerate(pages):
        following=pages[min(index+1,len(pages)-1)]
        if following['canGenerate']:
            page['nextAction']=dict(page=following['id'],label='开始体验' if following['id']=='experience' else '前往'+following['name'])
        elif not page['canGenerate']:
            target='clues' if page['id']=='storyboards' else 'characters' if page['id']=='experience' and records(p,'character') else 'library'
            page['nextAction']=dict(page=target,label='前往'+TITLES[target])
    next_page=next((v for v in pages if not v['complete']),pages[-1])
    if not next_page['canGenerate']:
        if next_page['id']=='storyboards':next_page=pages[2]
        elif next_page['id']=='experience':next_page=pages[3] if records(p,'character') else pages[0]
        elif next_page['id']!='library':next_page=pages[0]
    return dict(units=units,pages=pages,nextAction=dict(page=next_page['id'],label=dict(library='整理资料',outline='生成剧本大纲',clues='整理线索',characters='准备人物对话设定',storyboards='生成分镜提示词',experience='开始体验')[next_page['id']],reason=next_page['blocker']))

class Confirm(BaseModel):
    contentHash:str
    dependencyHash:str
    requestId:str=Field(min_length=1,max_length=100)
class Autosave(BaseModel):
    version:int
    requestId:str=Field(min_length=1,max_length=100)
    changes:list[dict]=Field(max_length=1000)

def assign(p,path,value,delete=False):
    tokens=path.strip('/').split('/');parent=p
    for token in tokens[:-1]:
        if isinstance(parent,list):parent=next(x for x in parent if x.get('id')==token[1:])
        else:parent=parent.setdefault(token,{})
    last=tokens[-1]
    if isinstance(parent,list):
        index=next((i for i,x in enumerate(parent) if x.get('id')==last[1:]),None)
        if delete:
            if index is not None:parent.pop(index)
        elif index is None:parent.append(copy.deepcopy(value))
        else:parent[index]=copy.deepcopy(value)
    elif delete:parent.pop(last,None)
    else:parent[last]=copy.deepcopy(value)

def compact_project(p,jobs=None):
    result=dict(p);w=dict(p['workspace'])
    from .people_policy import view as people_view
    result['peoplePolicy']=people_view(p)
    w.pop('revisionArchive',None);w.pop('historyLibrary',None);w.pop('batchReceipts',None)
    w['entities']={k:{f:v for f,v in r.items() if f not in ('history','basisWarnings')} for k,r in w['entities'].items()}
    if jobs is not None:w['jobs']=jobs
    result['workspace']=w
    return result

asset_data=None
@lru_cache(maxsize=64)
def _image_hash(path,mtime,size):
    value=hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()
def image_fingerprint(p):
    if asset_data and p.get('image'):
        path=asset_data()/Path(p['image']).name
        if path.is_file():
            st=path.stat();return _image_hash(str(path),st.st_mtime_ns,st.st_size)
    return p.get('image')

def install(app,get,save,db,data):
    global asset_data
    asset_data=data
    def with_videos(p):
        with db() as c:p['_reviewVideos']=[json.loads(r[0]) for r in c.execute('SELECT body FROM video_jobs WHERE project=?',(p['id'],))]
        return p
    def report(p):return workflow(with_videos(p))
    app.state.review_report=report
    def present(p):
        jobs=app.state.studio_jobs(p['id']) if hasattr(app.state,'studio_jobs') else []
        return compact_project(p,jobs)
    @app.get('/api/projects/{pid}/studio/editor')
    def editor(pid:str):return app.state.studio_editor(pid) if hasattr(app.state,'studio_editor') else present(get(pid))
    @app.get('/api/projects/{pid}/studio/units')
    def read_units(pid:str):return app.state.studio_checks(pid) if hasattr(app.state,'studio_checks') else report(get(pid))
    @app.patch('/api/projects/{pid}/studio/units/{uid}')
    def autosave(pid:str,uid:str,req:Autosave):
        signature=tr.digest(req.model_dump())
        for attempt in range(4):
            old=get(pid);ws.ensure(old);receipt=old['workspace'].get('reviewUnits',{}).get('receipts',{}).get(req.requestId)
            if receipt:
                if receipt!=signature:raise HTTPException(409,'保存编号已用于其他内容')
                return present(old)
            p=copy.deepcopy(old)
            for change in req.changes:
                path=change.get('path','');tokens=path.strip('/').split('/')
                valid_path=tokens[0] in ROOT_FIELDS or len(tokens)>=4 and tokens[:2]==['workspace','entities'] and tokens[3]=='draft' and tokens[2].split(':')[0] in ws.PAGES
                if not valid_path:raise HTTPException(422,'不允许保存此内容位置')
                current=tr.value_at(old,path);value=change.get('value')
                if current!=change.get('before') and current!=value:raise HTTPException(409,dict(message='同一字段已有其他修改，输入已保留',path=path,current=current))
                if tokens[:2]==['workspace','entities'] and tokens[2] not in p['workspace']['entities']:
                    kind,rid=tokens[2].split(':',1);p['workspace']['entities'][tokens[2]]=ws.record(kind,rid,{})
                assign(p,path,value,change.get('delete',False))
            from .tree_management import validate_moves
            try:validate_moves(old,p)
            except (ValueError,KeyError) as exc:raise HTTPException(422,str(exc))
            from .models import Project
            try:Project.model_validate(p)
            except ValidationError as exc:raise HTTPException(422,dict(message='部分输入格式尚未完成，输入已在浏览器保留',fields=[dict(path='.'.join(map(str,e['loc'])),reason=e['msg']) for e in exc.errors()]))
            if any(c['path'].strip('/').split('/')[0] in ROOT_FIELDS for c in req.changes):
                from .domain import reconcile
                try:p=reconcile(old,p);ws.ingest(old,p)
                except (ValueError,KeyError,TypeError) as exc:raise HTTPException(422,str(exc))
            for k,r in p['workspace']['entities'].items():
                before=old['workspace']['entities'].get(k)
                if before and r['draft']!=before['draft']:
                    r['manualFields']=sorted(set(r.get('manualFields',[]))|{f for f in r['draft'] if r['draft'].get(f)!=before['draft'].get(f)})
            def source_input(value):return [dict(id=s['id'],text=s.get('text',''),citation=s.get('citation','')) for s in value.get('sources',[])]
            if source_input(old)!=source_input(p) or old.get('materialInputs')!=p.get('materialInputs'):
                p['workspace']['entities']['material:main']['needsStructuredRefresh']=True
            make_available(p,'manual')
            try:Project.model_validate(p)
            except ValidationError:raise HTTPException(422,'部分输入格式尚未完成，输入已在浏览器保留')
            changed_members(old,p,'manual')
            meta(p)['receipts'][req.requestId]=signature
            try:return present(save(p,old['version'],'studio:unit_autosave'))
            except HTTPException as exc:
                if exc.status_code!=409 or attempt==3:raise
    @app.post('/api/projects/{pid}/studio/units/{uid}/confirm')
    def confirm(pid:str,uid:str,req:Confirm):
        p=with_videos(get(pid));ws.ensure(p);signature=tr.digest([uid,req.model_dump()]);info=meta(p)
        if req.requestId in info['receipts']:
            if info['receipts'][req.requestId]!=signature:raise HTTPException(409,'确认编号已用于其他内容')
            return present(p)
        current=unit(p,uid)
        if current['contentHash']!=req.contentHash or current['dependencyHash']!=req.dependencyHash:raise HTTPException(409,'内容刚更新，请查看后再确认')
        if not current['canConfirm']:raise HTTPException(422,dict(message='请补充此卡片的必要内容',issues=current['issues']))
        make_available(p)
        for key,value in members(p,uid).items():
            info['members'][key]=dict(origin='human',hash=fingerprint(value),reviewedHash=fingerprint(value))
        info['units'][uid]=dict(basis=dependencies(p,uid));info['receipts'][req.requestId]=signature
        p.pop('_reviewVideos',None)
        return present(save(p,p['version'],'studio:unit_confirm',dict(unitId=uid)))


def recover_reviews(p,events):
    """Explicit migration only: recover actual confirmation actions, never infer from state."""
    info=meta(p);proofs={}
    for action,body,metadata in events:
        after=json.loads(body) if isinstance(body,str) else body
        details=json.loads(metadata) if isinstance(metadata,str) else metadata
        w=after.get('workspace',{});keys=[]
        if action.startswith('studio:confirm:'):keys=[action[len('studio:confirm:'):]]
        elif action=='studio:batch_confirm':keys=[v['key'] for v in details.get('result',{}).get('eligible',[])]
        for key in keys:
            r=w.get('entities',{}).get(key)
            if r and r.get('published') is not None:
                proofs[key]=fingerprint(r['published'])
                if key=='material:main':
                    material=r['published']
                    if material.get('structured'):proofs['library:main']=fingerprint(dict(structured=material['structured'],materialInputs=material.get('materialInputs',{})))
                    for annotation in material.get('annotations',[]):
                        if annotation.get('identityConfirmed'):proofs['visual:'+annotation['id']]=fingerprint(annotation)
                        observations=[o for o in material.get('observations',[]) if o.get('annotationId')==annotation['id']]
                        if observations and all(o.get('confirmed') for o in observations):proofs['observation:'+annotation['id']]=fingerprint(observations)
        if action=='confirm_person':
            for a in after.get('annotations',[]):
                if a.get('id')!=details.get('annotationId'):continue
                if a.get('identityConfirmed') and not a.get('needsReview'):proofs['visual:'+a['id']]=fingerprint(a)
    for uid in unit_ids(p):
        for key,value in members(p,uid).items():
            if key not in proofs:continue
            current=info['members'].get(key,{})
            if current.get('origin')=='AI' and current.get('hash')==fingerprint(value):continue
            info['members'][key]=dict(current,reviewedHash=proofs[key])
            if fingerprint(value)==proofs[key]:info['members'][key].update(origin='human',hash=proofs[key])
    info['legacyAuditRecovered']=True
    return p
