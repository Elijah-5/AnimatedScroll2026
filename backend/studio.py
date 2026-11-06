import asyncio,copy,hashlib,json
from datetime import datetime,timezone
from pydantic import BaseModel,Field
from fastapi import HTTPException
from . import workspace as ws,studio_agent,materials,task_runtime as tr
from .domain import uid

LABELS={'culture':'文化背景线索','relationship':'人物关系线索','plots':'剧情及叙事线索','plot_clues':'剧情子叙事线索','knowledge':'人物知识建议','storyboard':'分镜提示词','check':'一致性检查','plot':'本剧情及线索','clue':'单条线索重生成','history':'历史资料八表候选'}
LABELS['structure_materials']='统一作品资料整理'
LABELS['persona']='入画角色提示词'

def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def context(p,task='check',target=''):
    if task=='persona':
        from .persona import generation_context
        return generation_context(p,target)
    if task=='structure_materials':
        return dict(material=p['workspace']['entities']['material:main']['draft'],analysis=p.get('documentAnalysis'),characters=[r['draft'] for r in p['workspace']['entities'].values() if r['kind']=='character' and r['state']!='deleted'],legacy=p['workspace'].get('historyLibrary'))
    if task=='history':
        from .history import generation_context
        return generation_context(p)
    from .documents import relevant_sources,evidence_refs,character_allowed
    w=ws.ensure(p)
    chosen=lambda r:copy.deepcopy(r['published'] if r['published'] is not None else r['draft'])
    rows=lambda kind:[r for r in w['entities'].values() if r['kind']==kind and r['state']!='deleted']
    from .structured import material_sources
    mat=chosen(w['entities']['material:main']);mat['sources']=[v for v in material_sources(mat) if v.get('confirmed',True) and v.get('sourceType')!='creative_intent']
    mat.pop('literatureInput',None)  # Editor buffer is not a second, unbounded evidence channel.
    chars=[dict(chosen(r),id=r['id']) for r in rows('character') if character_allowed(chosen(r),p)]
    refs=evidence_refs(mat.get('materialInputOrigins',{}))+evidence_refs(chars)+evidence_refs(mat.get('structured',{}))
    mat['sources']=relevant_sources(mat['sources'],refs)
    for c in chars:
        for field in ('faceRegion','knowledge'):c.pop(field,None)
    ctx=dict(characters=chars)
    if task!='knowledge':
        from . import structured
        ctx['structuredMaterial']=structured.compact(structured.view(p,published=w['entities']['material:main']['published'] is not None))
    if mat.get('structured'):
        from .structured import compact
        mat['structured']=compact(mat['structured'])
    elif mat.get('historySnapshot'):ctx['historicalLibrary']=mat['historySnapshot']
    if task!='knowledge':ctx.update(material=mat,sources=mat.get('sources',[]))
    if task not in ('culture','relationship','knowledge'):ctx['intent']=chosen(w['entities']['intent:main'])
    if task in ('knowledge','check'):
        from .consumption import confirmed
        ctx['clues']=[]
        for r in rows('clue'):
            if not ws.valid(r):continue
            try:value=confirmed(p,'clue',r['id'])
            except ValueError:continue
            ctx['clues'].append(dict(value,id=r['id']))
    if task=='check':
        ctx['knowledge']=[dict(r['published'],id=r['id']) for r in rows('knowledge') if ws.valid(r)]
        ctx['plots']=[chosen(r) for r in rows('plot')];ctx['storyboards']=[chosen(r) for r in rows('storyboard')]
    if task in ('plot','plot_clues'):
        ctx['targetPlot']=dict(ws.find(w,'plot',target)['draft'],id=target)
        ctx['existingChildren']=[r['draft'] for r in rows('clue') if r['draft'].get('plotIds')==[target]]
    if task=='clue':ctx['targetClue']=ws.find(w,'clue',target)['draft']
    if task=='relationship':ctx['targetCharacter']=chosen(ws.find(w,'character',target))
    if task=='storyboard':
        from .consumption import character_id
        ctx['storyboard']=copy.deepcopy(ws.find(w,'storyboard',target)['draft']);ids=list(dict.fromkeys(character_id(p,cid) for cid in ctx['storyboard'].get('characterIds',[])))
        ctx['storyboard']['characterIds']=ids
        ctx['characters']=[c for c in chars if c['id'] in ids]
        ctx['clues']=[dict(r['published'],id=r['id']) for r in rows('clue') if r['id']==ctx['storyboard']['clueId'] and ws.valid(r)]
        ctx['knowledge']=[dict(r['published'],id=r['id']) for r in rows('knowledge') if r['id'] in ids and ws.valid(r)]
        from .structured import role_context
        ctx['structuredMaterial']={'roles':[role_context(p,cid) for cid in ids]}
        for field in ('structured','historySnapshot','materialInputOrigins','matches','observations'):mat.pop(field,None)
    if task!='knowledge':
        from . import revisions
        required=evidence_refs(ctx);existing={(s['id'],s['version']) for s in mat['sources']}
        for key,r in w['entities'].items():
            if task=='storyboard' and key not in {'material:main','storyboard:'+target,'clue:'+ctx['storyboard']['clueId']}|{kind+':'+cid for cid in ids for kind in ('character','knowledge')}:continue
            if not ws.valid(r):continue
            try:materials=revisions.materials_for(w,key)
            except ValueError:continue
            for material in materials:
                candidates=[s for s in material_sources(material) if s.get('confirmed') is not False and (s['id'],s['version']) not in existing and any(ref['sourceId']==s['id'] and ref['sourceVersion']==s['version'] for ref in required if ref.get('sourceId'))]
                for source in relevant_sources(candidates,required):mat['sources'].append(source);existing.add((source['id'],source['version']))
        ctx['sources']=mat['sources']
    # One canonical structured projection; duplicated source/history/editor payloads
    # are not model instructions and made a single shot cost hundreds of K tokens.
    if 'material' in ctx:
        for field in ('structured','historySnapshot','materialInputOrigins','sources','matches','observations'):
            ctx['material'].pop(field,None)
    from .feedback import rebind
    record=w['entities']['material:main'];redirects=((record.get('published') or record['draft']).get('structured') or {}).get('personRedirects',{})
    if redirects:
        ctx=copy.deepcopy(ctx);rebind(ctx,redirects)
    return ctx

def task_paths(p,task,target):
    if task=='persona':
        from .persona import candidates
        ids=candidates(p,target)
        return ['/workspace/entities/material:main/published']+['/workspace/entities/'+kind+':'+cid+'/published' for cid in ids for kind in ('character','knowledge')]+['/workspace/entities/'+k+'/published' for k,r in ws.ensure(p)['entities'].items() if r['kind']=='clue'],['/workspace/entities/persona:'+cid for cid in ids]
    if task=='structure_materials':return ['/workspace/entities/material:main/draft','/documentAnalysis','/workspace/historyLibrary']+['/workspace/entities/'+k+'/draft' for k,r in ws.ensure(p)['entities'].items() if r['kind']=='character'],['/structured','/workspace/entities/material:main/draft/structured']
    if task=='history':return ['/workspace/historyLibrary/draft','/documentAnalysis','/materialInputs','/workspace/entities'],['/workspace/historyLibrary/draft','/workspace/historyLibrary/researchNotes']
    w=ws.ensure(p);read=[];write=[]
    kinds={'character'}
    if task!='knowledge':kinds.add('material')
    if task not in ('culture','relationship','knowledge'):kinds.add('intent')
    if task in ('knowledge','check','storyboard'):kinds.add('clue')
    if task in ('check','storyboard'):kinds.add('knowledge')
    for k,r in w['entities'].items():
        if r['kind'] in kinds and r['state']!='deleted':read.append('/workspace/entities/'+k+('/published' if r['published'] is not None else '/draft'))
        output=(task=='knowledge' and r['kind']=='knowledge') or (task=='plots' and r['kind']=='plot' and r['published'] is None)
        output=output or (task in ('plot','clue') and k==task+':'+target)
        output=output or (task in ('culture','relationship') and r['kind']=='clue' and r['published'] is None and r.get('generatedFrom')==('material:main' if task=='culture' else 'character:'+target))
        if task=='plot' and ((r['kind']=='clue' and r['draft'].get('plotIds')==[target]) or (r['kind']=='storyboard' and w['entities'].get('clue:'+r['id'],{}).get('draft',{}).get('plotIds')==[target])):output=True
        if output:write.append('/workspace/entities/'+k)
    if task in ('plot','plot_clues'):read+=['/workspace/entities/plot:'+target+'/draft']+['/workspace/entities/'+k+'/draft' for k,r in w['entities'].items() if r['kind']=='clue' and r['draft'].get('plotIds')==[target]]
    if task=='clue':read.append('/workspace/entities/clue:'+target+'/draft')
    if task=='storyboard':
        root='/workspace/entities/storyboard:'+target
        read.append(root+'/draft');write += [root+'/draft/'+f for f in ('prompt','startFrame','endFrame','action','camera','style','promptConfigHash')]+[root+'/regenerated',root+'/refs']
    if task=='plot_clues':
        root='/workspace/entities/plot:'+target;write += [root+'/draft/clueIds',root+'/state',root+'/linkReviewOnly']
    if task=='culture':write+=['/materialAnalysis','/materialSegments']
    if task=='check':
        read += ['/workspace/entities/'+k+('/published' if r['published'] is not None else '/draft') for k,r in w['entities'].items() if r['kind'] in ('plot','storyboard') and r['state']!='deleted'];write.append('/workspace/consistencyChecks')
    return read,write

def add_clue(w,c,kind,plot_ids=None,source=None):
    cid=uid();units=[]
    for u in c.get('units',[]):units.append(dict(u,id=u.get('id') or uid(),status='pending',locked=False))
    body=dict(name=c['name'],summary=c.get('summary',''),type=kind,parentId=kind,plotIds=plot_ids or [],characterIds=c.get('characterIds',[]),units=units)
    if kind=='relationship' and c.get('relations'):body['relations']=copy.deepcopy(c['relations'])
    if kind=='narrative' and 'content' in c:
        body['content']=c['content'];body=ws.narrative_draft(body)
        owner=w['entities'].get('plot:'+body['plotIds'][0]) if body['plotIds'] else None
        if owner:body['characterIds']=copy.deepcopy(owner['draft'].get('characterIds',[]))
    r=ws.record('clue',cid,body)
    r['refs']=ws.refs_for(w,r);r['draftRefs']=copy.deepcopy(r['refs']);r['generatedFrom']=source
    w['entities'][ws.key('clue',cid)]=r
    return cid


def self_replace_generated(w,kind,source):
    for r in w['entities'].values():
        if r['kind']=='clue' and r['draft']['type']==kind and r['published'] is None and r.get('generatedFrom')==source:r['state']='deleted'

def apply_output(p,task,target,output,ctx,analysis=None):
    w=p['workspace']
    current=copy.deepcopy(p);cw=ws.ensure(current)
    if task=='persona':
        from .persona import apply
        apply(current,output,ctx)
    if task=='structure_materials':
        from .structured import install_draft
        install_draft(current,output)
    if task=='culture':
        current['materialAnalysis']=analysis;current['materialSegments']=analysis['segments']
        for c in analysis['characters']:
            existing=next((r for r in cw['entities'].values() if r['kind']=='character' and r['draft']['name']==c['name'] and r['state']!='deleted'),None)
            if not existing:
                cw['entities']['character:'+c['id']]=ws.record('character',c['id'],c)
                cw['entities']['knowledge:'+c['id']]=ws.record('knowledge',c['id'],dict(characterId=c['id'],clueIds=[],reasons={}))
        self_replace_generated(cw,'culture','material:main')
        for clue in output['clues']:add_clue(cw,clue,'culture',source='material:main')
    if task=='relationship':
        self_replace_generated(cw,'relationship','character:'+target)
        for clue in output['clues']:add_clue(cw,clue,'relationship',source='character:'+target)
    if task=='clue':
        r=ws.find(cw,'clue',target);new=output['clues'][0]
        if r['draft']['type']=='narrative' and 'content' in new:r['draft']=ws.narrative_draft(dict(r['draft'],**new),r['draft'])
        else:new['units']=ws.merge_locked(r['draft'].get('units',[]),new['units']);r['draft'].update(new)
        r['regenerated']=True;r['draftRefs']=ws.refs_for(cw,r)
    if task=='plot_clues':
        plot=ws.find(cw,'plot',target);body=plot['draft']
        names={r['draft']['name'] for r in cw['entities'].values() if r['kind']=='clue' and r['state']!='deleted' and r['draft'].get('plotIds')==[target]}
        new_clues=list({c['name']:c for c in output['clues'] if c['name'] not in names}.values())
        if not new_clues:raise ValueError('没有生成新的子叙事线索，已有内容未改变')
        # Old UI allowed a plot to point at another plot's child. Repair only
        # these draft links; the original clue and its owner are preserved.
        body['clueIds']=[r['id'] for r in cw['entities'].values() if r['kind']=='clue' and r['state']!='deleted' and r['draft'].get('type')=='narrative' and r['draft'].get('plotIds')==[target]]
        for clue in new_clues:body.setdefault('clueIds',[]).append(add_clue(cw,clue,'narrative',[target],source='plot:'+target))
        if plot['published'] is not None:plot['state']='review';plot['linkReviewOnly']=True
    if task in ('plots','plot'):
        if task=='plots':
            for previous in cw['entities'].values():
                if previous['kind']=='plot' and previous['published'] is None:previous['state']='deleted'
        if task=='plot':
            previous=ws.find(cw,'plot',target)
            for cid in previous['draft'].get('clueIds',[]):
                old=cw['entities'].get('clue:'+cid)
                shared=any(r['kind']=='plot' and r['id']!=target and r['state']!='deleted' and cid in r['draft'].get('clueIds',[]) for r in cw['entities'].values())
                if old and not shared:
                    old['state']='deleted'
                    if 'storyboard:'+cid in cw['entities']:cw['entities']['storyboard:'+cid]['state']='deleted'
        for plot in output['plots']:
            pid=target if task=='plot' else uid();body={k:v for k,v in plot.items() if k!='clues'};body.update(region=None,clueIds=[])
            if 'plot:'+pid not in cw['entities']:cw['entities']['plot:'+pid]=ws.record('plot',pid,body)
            cw['entities']['plot:'+pid]['draft']=body
            for clue in plot['clues']:body['clueIds'].append(add_clue(cw,clue,'narrative',[pid],source='plot:'+pid))
            cw['entities']['plot:'+pid]['draft']=body;cw['entities']['plot:'+pid]['draftRefs']=ws.refs_for(cw,cw['entities']['plot:'+pid]);cw['entities']['plot:'+pid]['regenerated']=True
    if task=='knowledge':
        for a in output['assignments']:
            kk='knowledge:'+a['characterId'];body=dict(characterId=a['characterId'],clueIds=a['clueIds'],reasons={cid:a['reason'] for cid in a['clueIds']})
            if kk not in cw['entities']:cw['entities'][kk]=ws.record('knowledge',a['characterId'],body)
            elif cw['entities'][kk]['published'] is None and not cw['entities'][kk]['draft'].get('clueIds'):
                cw['entities'][kk]['draft']=body;cw['entities'][kk]['regenerated']=True;cw['entities'][kk]['draftRefs']=ws.refs_for(cw,cw['entities'][kk])
            else:
                cw['entities'][kk]['suggestion']=body;cw['entities'][kk]['regenerated']=True
                cw['entities'][kk]['suggestionRefs']=[dict(key='clue:'+cid,revision=cw['entities']['clue:'+cid]['revision']) for cid in a['clueIds']]
    if task=='storyboard':
        r=ws.find(cw,'storyboard',target);r['draft'].update(output);r['draft']['promptConfigHash']=ws.config_hash(r['draft']);r['regenerated']=True;r['draftRefs']=ws.refs_for(cw,r)
    if task=='history':
        from .history import apply_suggestion
        h=cw.setdefault('historyLibrary',{});h['draft']=apply_suggestion(current,output);h['researchNotes']=output['research_notes'];h['baseRevision']=h.get('revision',0)
    if task=='check':cw['consistencyChecks']=[dict(id=uid(),message=c['message'],resolved=False) for c in output['checks']]
    from .revisions import pin_citations
    for key,r in cw['entities'].items():
        previous=w['entities'].get(key)
        if not previous or previous['draft']!=r['draft']:
            r.setdefault('draftRefs',ws.refs_for(cw,r));pin_citations(cw,r)
    return current

class DraftRequest(BaseModel):
    version:int
    kind:str
    id:str
    data:dict
class Action(BaseModel):
    version:int
    kind:str
    id:str
    acceptRisk:bool=False
    generate:bool=False
class JobRequest(BaseModel):
    version:int
    task:str
    target:str=''
    trigger:str='user_button'


def install(app,get,save,db):
    runners={}
    def tables():
        with db() as c:c.execute('CREATE TABLE IF NOT EXISTS studio_jobs(id TEXT PRIMARY KEY,project TEXT,body TEXT)')
    def jobs(pid):
        tables()
        with db() as c:rows=[json.loads(r[0]) for r in c.execute('SELECT body FROM studio_jobs WHERE project=? ORDER BY rowid DESC',(pid,))]
        for j in rows:
            if j['task'] in ('culture','plots','knowledge','check'):j['target']=''
            if 'EOF while parsing' in j.get('error','') and "input_value=''" in j.get('error',''):j['error']='模型返回空内容，未获得可解析结果。资料已保留，请点击重试。';j['errorCode']='empty_response'
        return rows
    def job_save(j):
        tables()
        with db() as c:c.execute('INSERT OR REPLACE INTO studio_jobs VALUES (?,?,?)',(j['id'],j['projectId'],json.dumps(j,ensure_ascii=False)))
    def visible_jobs(pid):
        result=jobs(pid);seen=set()
        for job in result:
            if job.get('task')=='history':job.update(dismissed=True,retired=True,label='旧历史整理记录（已并入作品资料库）')
        labels={'detect':'人物检测','vision':'人物外观分析','vision_match':'外观与身份匹配','match':'身份匹配','ocr':'资料 OCR','materials':'资料整理','legacy_materials':'旧资料整理','supplement':'视觉补检漏检人物','document_parse':'本地解析文献','document_analysis':'长文献整理'}
        with db() as c:rows=[json.loads(r[0]) for r in c.execute('SELECT body FROM tasks WHERE project=? ORDER BY rowid DESC',(pid,))]
        for task in rows:
            request=task.get('request',{});signature=(task['kind'],request.get('documentId',''),tuple(sorted(request.get('pages',[]))),tr.digest(request.get('documents',[])),request.get('targetArtwork',''))
            if signature in seen:continue
            seen.add(signature)
            if task['status']=='completed':continue
            result.append(dict(id='analysis-'+task['id'],family='analysis',task=task['kind'],target='',request=request,label=labels.get(task['kind'],task['kind']),page='library',state=task['status'],error=task.get('progress','') if task['status'] in ('failed','stale','interrupted') else '',progress=task.get('progress',''),**{k:task[k] for k in ('readSet','writeSet','startedAt','time','inputHash','outputHashes','inputsChanged') if k in task}))
        with db() as c:feedback_rows=[json.loads(r[0]) for r in c.execute('SELECT body FROM feedback_jobs WHERE project=?',(pid,))]
        for job in feedback_rows:
            if job['status'] in ('queued','running'):
                result.append(dict(id=job['id'],family='feedback',task='feedback',target='',label='智能修改',page='library',state=job['status'],progress=job.get('progress',''),time=job['time']))
        if any(j.get('state') in ('queued','running') for j in result):
            latest=get(pid)
            for j in result:
                if j.get('family') not in ('completion','feedback') and j.get('state') in ('queued','running') and j.get('inputHash'):
                    try:
                        read_value=tr.analysis_inputs(latest,j['task'],j.get('request',{})) if j.get('family')=='analysis' else context(latest,j['task'],j['target'])
                        tr.ensure_fresh(latest,j,read_value);j['inputsChanged']=False
                    except (ValueError,KeyError):j['inputsChanged']=True
        return result
    def startup():
        tables()
        with db() as c:
            for id,body in c.execute('SELECT id,body FROM studio_jobs'):
                j=json.loads(body)
                if j['state'] in ('queued','running'):
                    j.update(state='interrupted',error='服务重启，任务已中断；请点击重试')
                    c.execute('UPDATE studio_jobs SET body=? WHERE id=?',(json.dumps(j,ensure_ascii=False),id))
    app.router.add_event_handler('startup',startup)
    def read(pid):
        p=get(pid);ws.ensure(p);p['workspace']['jobs']=visible_jobs(pid)
        from .revisions import decorate
        decorate(p['workspace']);return p
    def check_version(p,v):
        if p['version']!=v:raise HTTPException(409,'项目已变化，请重新加载；未覆盖你的编辑')
    def persist(p,version,action):
        ws.mirror(p)
        return save(p,version,'studio:'+action)
    def response(p):
        p['workspace']['jobs']=visible_jobs(p['id'])
        from .revisions import decorate
        decorate(p['workspace']);return p
    app.state.studio_response=response
    app.state.studio_jobs=visible_jobs
    from .batch_confirmation import install as install_batch
    install_batch(app,read,save,response)
    @app.post('/api/projects/{pid}/studio/acknowledge')
    def acknowledge(pid:str,req:Action):
        from .revisions import acknowledge
        p=read(pid);check_version(p,req.version)
        try:acknowledge(p['workspace'],ws.find(p['workspace'],req.kind,req.id))
        except ValueError as exc:raise HTTPException(422,str(exc))
        return response(persist(p,req.version,'acknowledge:'+req.kind+':'+req.id))
    @app.post('/api/projects/{pid}/studio/suggestions/{sid}/adopt')
    def adopt_suggestion(pid:str,sid:str,payload:dict):
        p=read(pid);check_version(p,payload['version'])
        item=next((v for v in p['workspace'].get('generationSuggestions',[]) if v['id']==sid),None)
        if not item:raise HTTPException(404,'生成建议不存在')
        if item['status']!='pending':return response(p)
        applied=[];conflicts=[]
        for change in item['changes']:
            path=change['path']
            if tr.value_at(p,path)!=change['before']:conflicts.append(path);continue
            tokens=path.strip('/').split('/');parent=p
            for token in tokens[:-1]:parent=parent.setdefault(token,{})
            if change['after'] is None:parent.pop(tokens[-1],None)
            else:parent[tokens[-1]]=copy.deepcopy(change['after'])
            applied.append(path)
        if not applied:raise HTTPException(409,'结果位置已有人工修改；建议保留，可查看并手动合入')
        item.update(status='partial' if conflicts else 'adopted',applied=applied,conflicts=conflicts)
        return response(persist(p,payload['version'],'adopt_old_input_suggestion'))
    @app.post('/api/projects/{pid}/studio/personas/{cid}/adopt-suggestion')
    def adopt_persona(pid:str,cid:str,req:Action):
        p=get(pid);check_version(p,req.version)
        try:r=ws.find(ws.ensure(p),'persona',cid)
        except ValueError as exc:raise HTTPException(422,str(exc))
        if not r.get('suggestion'):raise HTTPException(422,'没有待采用的角色建议')
        r['draft']=copy.deepcopy(r['suggestion']);r['draftRefs']=copy.deepcopy(r.get('suggestionRefs',[]));r['generationRefs']=copy.deepcopy(r['draftRefs']);r['regenerated']=True
        return response(persist(p,req.version,'adopt_persona_suggestion:'+cid))
    def start_job(p,task,target=''):
        if task=='history':raise ValueError('历史整理已合并，请使用“根据现有资料补充整理”')
        if task in ('culture','plots','knowledge','check'):target=''
        if task not in LABELS:raise ValueError('未知生成任务')
        w=ws.ensure(p)
        if task=='persona' and not context(p,task,target)['roles']:raise ValueError('没有可准备的角色：请确认人物、画作和知识；批量准备会跳过已有提示词的角色')
        if any(j['state'] in ('queued','running') for j in jobs(p['id'])):raise ValueError('本项目已有生成任务，请等待完成')
        if task in ('culture','relationship','plots','plot','plot_clues','clue') and not ws.valid(w['entities']['material:main']):raise ValueError('请先确认古画资料')
        if task=='plot_clues':
            plot=ws.find(w,'plot',target)
            if not plot['draft'].get('title','').strip() or not (plot['draft'].get('body','').strip() or plot['draft'].get('goal','').strip()):raise ValueError('请先填写剧情标题和具体内容或目标')
            if not ws.valid(w['entities']['intent:main']):raise ValueError('请先确认创作设置与历史框架')
            for cid in plot['draft'].get('characterIds',[]):
                if not ws.valid(w['entities'].get('character:'+cid)):raise ValueError('请先确认剧情中使用的人物资料')
        if task=='relationship' and not ws.valid(w['entities'].get('character:'+target)):raise ValueError('请先确认人物资料')
        if task=='plots':
            if not ws.valid(w['entities']['intent:main']):raise ValueError('请先确认创作设置')
            from .documents import character_allowed
            chars=[r for r in w['entities'].values() if r['kind']=='character' and r['state']!='deleted' and character_allowed(r['published'] or r['draft'],p)]
            if not chars or any(not ws.valid(r) for r in chars):raise ValueError('请先确认人物资料：'+'、'.join(ws.named(r) for r in chars if not ws.valid(r)))
        if task=='knowledge' and not any(r['kind']=='clue' and ws.valid(r) for r in w['entities'].values()):raise ValueError('请先确认线索')
        if task=='knowledge' and not context(p,'knowledge')['clues']:raise ValueError('没有可以核对原文依据的有效确认线索')
        if task=='storyboard':
            r=ws.find(w,'storyboard',target);d=r['draft']
            if not d.get('region') or not d.get('participantsConfirmed'):raise ValueError('请选择区域并确认参与人物')
            if not ws.valid(w['entities'].get('clue:'+d['clueId'])):raise ValueError('请先确认对应线索')
            for cid in d.get('characterIds',[]):
                if not ws.valid(w['entities'].get('character:'+cid)) or not ws.valid(w['entities'].get('knowledge:'+cid)):raise ValueError('参与人物资料或知识尚未确认')
        if task=='clue':
            clue=ws.find(w,'clue',target)
            if clue['draft']['type']=='narrative' and any(u.get('locked') for u in clue['draft'].get('units',[])):raise ValueError('叙事情节已锁定，请先解锁并保存')
        if task=='plot':
            for cid in ws.find(w,'plot',target)['draft'].get('clueIds',[]):
                clue=w['entities'].get('clue:'+cid)
                if clue and any(u.get('locked') for u in clue['draft'].get('units',[])):raise ValueError('关联线索有锁定单元，请先解锁或单独重写线索')
        if task=='plots':
            existing=[r for r in w['entities'].values() if r['kind']=='plot' and r['state']!='deleted']
            if existing and any(r['published'] is not None for r in existing):raise ValueError('已有剧情，请对具体剧情使用重生成，避免覆盖整个大纲')
        from . import consumption as consume
        required=[]
        if task in ('culture','relationship','plots','plot','plot_clues','clue'):required.append(('material','main'))
        if task=='relationship':required.append(('character',target))
        if task=='storyboard':
            shot=w['entities']['storyboard:'+target]['draft'];required.append(('clue',shot['clueId']))
            required += [(kind,cid) for cid in shot.get('characterIds',[]) for kind in ('character','knowledge')]
        for kind,rid in required:consume.confirmed(p,kind,rid)
        j=dict(id=uid(),projectId=p['id'],task=task,target=target,label=LABELS[task],page={'culture':'library','relationship':'characters','plots':'outline','plot_clues':'outline','knowledge':'characters','storyboard':'storyboards','check':'checks','plot':'outline','clue':'clues','history':'library','structure_materials':'library','persona':'characters'}[task],state='queued',error='',trigger='user_button',time=datetime.now(timezone.utc).isoformat())
        j.update(model=studio_agent.config.model_settings(require_key=False).model,promptVersion='persona-1.0' if task=='persona' else 'studio-2.1-paragraphs')
        reads,writes=task_paths(p,task,target);j.update(tr.contract(p,context(p,task,target),reads,writes));j['inputs']={'context':j['inputHash']}
        tr.reserve(db,'studio_jobs',j);runner=asyncio.create_task(work(copy.deepcopy(p),j));runners[j['id']]=runner;runner.add_done_callback(lambda _:runners.pop(j['id'],None))
        return j
    async def work(p,j):
        token=tr.checkpoint.set(lambda:tr.note_changes(get,p['id'],j,lambda value:context(value,j['task'],j['target'])))
        try:
            j['state']='running';j['startedAt']=tr.now();j['progress']='准备已确认输入';job_save(j);task=j['task'];ctx=context(p,task,j['target']);w=p['workspace']
            if task=='culture':
                mat=ctx['material'];prep=copy.deepcopy(p);prep.update(mat)
                # Reuse exact-span extraction; confirmation is retained on provider failure.
                j['progress']='整理原文与人物提及';job_save(j)
                if mat.get('materialInputOrigins'):
                    # Already accepted literature claims keep original PDF provenance;
                    # do not re-extract roles from generated summaries.
                    analysis=dict(segments=[],characters=[],eventFramework=[],summary='使用已采用文献摘要及原页依据',inputVersion=prep['materialInputs']['version'],stale=False)
                else:analysis=await materials.organize(prep)
                ctx['analysis']=analysis
            else:analysis=None
            tr.note_changes(get,p['id'],j,lambda value:context(value,task,j['target']))
            j['progress']='生成'+LABELS[task];job_save(j)
            if task=='structure_materials':
                from . import structured
                def cache_get(key):
                    with db() as c:row=c.execute('SELECT body FROM document_cache WHERE key=?',(key,)).fetchone()
                    return json.loads(row[0]) if row else None
                def cache_put(key,value):
                    with db() as c:c.execute('INSERT OR REPLACE INTO document_cache VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))
                base=structured.preview(p,db) if not p['workspace']['entities']['material:main']['draft'].get('structured') else None
                output=await structured.organize(p,cache_get,cache_put,base=base)
            else:output=await studio_agent.run(task,ctx)
            current=apply_output(p,task,j['target'],output,ctx,analysis)
            tr.apply_result(get,save,p['id'],p,current,j,lambda value:context(value,task,j['target']),'studio:generated:'+task,dict(taskId=j['id'],model=j['model'],promptVersion=j['promptVersion'],trigger='user_button'),lambda old,new:ws.mirror(new))
            j.update(state='completed',error='')
            if j.get('savedAsSuggestion'):j['progress']='基于旧输入的结果已保留为建议，未覆盖当前编辑'
            for previous in jobs(p['id']):
                if previous['id']!=j['id'] and previous['task']==task and previous['target']==j['target'] and previous['state'] in ('failed','stale','interrupted'):previous['dismissed']=True;job_save(previous)
        except asyncio.CancelledError:j.update(state='interrupted',error='角色准备已取消，已有草稿与确认内容保留；不会自动重试')
        except tr.StaleTask as exc:j.update(state='stale',error=str(exc))
        except Exception as exc:
            j.update(state='failed',errorCode=getattr(exc,'code','generation_failed'),diagnostics=getattr(exc,'diagnostics',{}),error=str(exc) if isinstance(exc,ValueError) else f'{type(exc).__name__}：生成失败，已确认资料保留，可重试')
        finally:job_save(j);tr.checkpoint.reset(token)
    def self_replace_generated(w,kind,source):
        for r in w['entities'].values():
            if r['kind']=='clue' and r['draft']['type']==kind and r.get('generatedFrom')==source and r['published'] is None:r['state']='deleted'
    @app.get('/api/projects/{pid}/studio')
    def studio_get(pid:str):return read(pid)
    @app.get('/api/projects/{pid}/studio/poll')
    def studio_poll(pid:str,version:int=0,compact:bool=False):
        # Idle polling must not rebuild/serialize the whole authoring workspace.
        from .read_models import metadata
        with db() as c:heads=metadata(c,pid)
        if not heads:raise HTTPException(404,'项目不存在')
        current_version=heads[0]['version']
        if current_version!=version:
            project=app.state.studio_editor(pid) if compact and hasattr(app.state,'studio_editor') else read(pid)
            if compact and not hasattr(app.state,'studio_editor'):
                from .review_units import compact_project
                project=compact_project(project)
            return dict(version=project['version'],changed=True,project=project)
        return dict(version=current_version,changed=False,jobs=visible_jobs(pid))
    @app.put('/api/projects/{pid}/studio/draft')
    def save_draft(pid:str,req:DraftRequest):
        p=get(pid);check_version(p,req.version);w=ws.ensure(p);k=ws.key(req.kind,req.id)
        if req.kind not in ws.PAGES:raise HTTPException(422,'条目类型无效')
        if req.kind=='clue':
            try:req.data=ws.narrative_draft(req.data,w['entities'].get(k,{}).get('draft'))
            except ValueError as exc:raise HTTPException(422,str(exc))
        if k not in w['entities']:w['entities'][k]=ws.record(req.kind,req.id,req.data)
        else:
            try:ws.check_locked(w['entities'][k],req.data)
            except ValueError as exc:raise HTTPException(422,str(exc))
            if req.kind=='persona':
                from .persona import edit_timing
                edit_timing(w,w['entities'][k],req.data)
            ws.track_manual(w['entities'][k],req.data)
            w['entities'][k]['draft']=copy.deepcopy(req.data)
        return response(persist(p,req.version,'draft:'+k))
    @app.put('/api/projects/{pid}/studio/drafts')
    def bulk_drafts(pid:str,payload:dict):
        p=get(pid);check_version(p,payload['version']);w=ws.ensure(p)
        for item in payload.get('entries',[]):
            if item['kind'] not in ws.PAGES:raise HTTPException(422,'条目类型无效')
            k=ws.key(item['kind'],item['id'])
            if item['kind']=='clue':
                try:item['data']=ws.narrative_draft(item['data'],w['entities'].get(k,{}).get('draft'))
                except ValueError as exc:raise HTTPException(422,str(exc))
            if k not in w['entities']:w['entities'][k]=ws.record(item['kind'],item['id'],item['data'])
            else:
                try:ws.check_locked(w['entities'][k],item['data'])
                except ValueError as exc:raise HTTPException(422,str(exc))
                if item['kind']=='persona':
                    from .persona import edit_timing
                    edit_timing(w,w['entities'][k],item['data'])
                ws.track_manual(w['entities'][k],item['data'])
                w['entities'][k]['draft']=copy.deepcopy(item['data'])
        return response(persist(p,payload['version'],'bulk_draft'))
    @app.post('/api/projects/{pid}/studio/preview')
    def preview(pid:str,req:Action):
        p=get(pid);check_version(p,req.version)
        try:return ws.preview(ws.ensure(p),ws.find(p['workspace'],req.kind,req.id))
        except ValueError as exc:raise HTTPException(422,str(exc))
    @app.post('/api/projects/{pid}/studio/confirm')
    async def confirm(pid:str,req:Action):
        p=get(pid);check_version(p,req.version);w=ws.ensure(p)
        try:
            r=ws.find(w,req.kind,req.id);changed=ws.dirty(r);first=r['published'] is None
            ws.commit(p,w,r,req.acceptRisk)
            # A change to already consumed data never starts regeneration implicitly.
            do_generate=req.generate and first and req.kind!='material'
            p=persist(p,req.version,'confirm:'+ws.key(req.kind,req.id))
            if do_generate:
                task={'material':'culture','character':'relationship','intent':'plots','clue':'knowledge'}.get(req.kind)
                if task:
                    try:start_job(p,task,req.id)
                    except ValueError as exc:p['generationNotice']=str(exc)
            return response(p)
        except ws.Risk as exc:raise HTTPException(409,dict(code='risk_confirmation_required',**exc.plan))
        except ValueError as exc:raise HTTPException(422,str(exc))
    @app.post('/api/projects/{pid}/studio/discard')
    def discard(pid:str,req:Action):
        p=get(pid);check_version(p,req.version)
        try:
            r=ws.find(ws.ensure(p),req.kind,req.id)
            if r['published'] is None:raise ValueError('首次草稿尚无确认版本可撤回')
            r['draft']=copy.deepcopy(r['published'])
            if r['kind']=='material':p.update(r['draft'])
            return response(persist(p,req.version,'discard'))
        except ValueError as exc:raise HTTPException(422,str(exc))
    @app.post('/api/projects/{pid}/studio/delete')
    def delete(pid:str,req:Action):
        p=get(pid);check_version(p,req.version);w=ws.ensure(p)
        try:
            r=ws.find(w,req.kind,req.id);affected=ws.impact(w,ws.key(req.kind,req.id))
            if affected and not req.acceptRisk:raise HTTPException(409,dict(code='risk_confirmation_required',changes=[dict(field='删除',before=ws.named(r),after=None)],affected=affected,requiresRisk=True))
            for a in affected:w['entities'][a['key']]['state']=a['mode']
            r['state']='deleted'
            if req.kind=='character':
                knowledge=w['entities'].get('knowledge:'+req.id)
                if knowledge:knowledge['state']='deleted'
                persona=w['entities'].get('persona:'+req.id)
                if persona:persona['state']='deleted'
            if req.kind=='clue':
                shot=w['entities'].get('storyboard:'+req.id)
                if shot:shot['state']='deleted'
                for rr in w['entities'].values():
                    if rr['kind']=='plot' and req.id in rr['draft'].get('clueIds',[]):rr['draft']['clueIds'].remove(req.id);rr['state']='review'
            return response(persist(p,req.version,'delete'))
        except ValueError as exc:raise HTTPException(422,str(exc))
    @app.post('/api/projects/{pid}/studio/jobs')
    async def generate(pid:str,req:JobRequest):
        p=get(pid);check_version(p,req.version)
        if req.trigger!='user_button':raise HTTPException(422,'生成必须由用户按钮触发')
        try:start_job(p,req.task,req.target);return response(p)
        except ValueError as exc:raise HTTPException(422,str(exc))
    @app.get('/api/projects/{pid}/studio/checklist')
    def get_checklist(pid:str):
        from .review_units import workflow
        p=read(pid);return dict(ws.checklist(p),**app.state.review_report(p))
    @app.post('/api/projects/{pid}/studio/jobs/{jid}/cancel')
    async def cancel_role_job(pid:str,jid:str,req:Action):
        p=get(pid);check_version(p,req.version)
        job=next((j for j in jobs(pid) if j['id']==jid),None)
        if not job:raise HTTPException(404,'任务不存在')
        if job['task']!='persona':raise HTTPException(422,'此取消入口仅用于入画角色准备')
        if job['state'] in ('queued','running'):
            runner=runners.get(jid)
            if runner:
                runner.cancel()
                try:await runner
                except asyncio.CancelledError:pass
            # Cancellation before a coroutine's first execution skips its finally.
            latest=next(j for j in jobs(pid) if j['id']==jid)
            if latest['state'] in ('queued','running'):
                latest.update(state='interrupted',error='角色准备已取消，已有内容保留；不会自动重试');job_save(latest)
        return response(p)
    @app.put('/api/projects/{pid}/studio/folders')
    def folders(pid:str,payload:dict):
        p=get(pid);check_version(p,payload['version']);w=ws.ensure(p);items=payload['folders'];by={f['id']:f for f in items}
        from .tree_management import validate_folders
        try:validate_folders(items,w['entities'],w['folders'])
        except (ValueError,KeyError) as exc:raise HTTPException(422,str(exc))
        w['folders']=items;return response(persist(p,payload['version'],'folders'))
    @app.post('/api/projects/{pid}/studio/checks/{cid}')
    def resolve(pid:str,cid:str,payload:dict):
        p=get(pid);check_version(p,payload['version']);w=ws.ensure(p)
        check=next((c for c in w.get('consistencyChecks',[]) if c['id']==cid),None)
        if not check:raise HTTPException(404)
        check['resolved']=bool(payload['resolved']);return response(persist(p,payload['version'],'resolve_check'))
