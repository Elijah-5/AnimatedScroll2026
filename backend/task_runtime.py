"""Shared task reservation, dependency guards and optimistic, field-wise result merge."""
import copy,fnmatch,hashlib,json
from contextvars import ContextVar
checkpoint=ContextVar("creation_task_checkpoint",default=lambda:None)
report_progress=ContextVar("creation_task_progress",default=lambda text:None)
model_request=ContextVar("creation_model_request",default=lambda:None)
from datetime import datetime,timezone
from fastapi import HTTPException

class StaleTask(ValueError):pass

def now():return datetime.now(timezone.utc).isoformat()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def value_at(value,path):
    nodes=[value]
    for token in path.strip('/').split('/') if path.strip('/') else []:
        found=[]
        for node in nodes:
            if isinstance(node,dict):
                if '*' in token:found.append({k:v for k,v in node.items() if fnmatch.fnmatchcase(k,token)})
                else:found.append(node.get(token))
            elif isinstance(node,list) and token.startswith('@'):
                found.append(next((r for r in node if isinstance(r,dict) and r.get('id')==token[1:]),None))
            else:found.append(None)
        nodes=found
    return nodes[0] if len(nodes)==1 else nodes

def contract(project,read_value,read_set,write_set):
    return dict(inputHash=digest(read_value),readSet=read_set,writeSet=list(dict.fromkeys(write_set)),outputHashes={path:digest(value_at(project,path)) for path in write_set})

def ensure_fresh(project,task,read_value):
    if task.get('inputHash') and digest(read_value)!=task['inputHash']:raise StaleTask('任务输入已变化，结果未应用；请按新内容重试')
    for path,h in task.get('outputHashes',{}).items():
        if digest(value_at(project,path))!=h:raise StaleTask('任务结果区已被修改，原编辑已保留；请重试')


def note_changes(get,pid,task,read_fn):
    try:ensure_fresh(get(pid),task,read_fn(get(pid)))
    except (ValueError,KeyError):task['inputsChanged']=True


def delta_entries(before,after,path=''):
    if before==after:return []
    if isinstance(before,dict) and isinstance(after,dict):
        return [entry for key in sorted(set(before)|set(after)) for entry in delta_entries(before.get(key),after.get(key),path+'/'+key)]
    return [dict(path=path,before=copy.deepcopy(before),after=copy.deepcopy(after))]

_MISSING=object()
def merge_delta(base,result,current):
    """Apply only generated changes. ID lists retain unrelated concurrent additions."""
    if base==result:return copy.deepcopy(current)
    if isinstance(base,dict) and isinstance(result,dict) and isinstance(current,dict):
        merged=copy.deepcopy(current)
        for k in set(base)|set(result):
            if k not in result:
                if k in base:merged.pop(k,None)
            elif k not in base:
                if k in current and current[k]!=result[k]:raise StaleTask('新增结果与当前内容冲突，原内容保留')
                merged[k]=copy.deepcopy(result[k])
            else:merged[k]=merge_delta(base[k],result[k],current.get(k))
        return merged
    keyed=lambda rows:isinstance(rows,list) and all(isinstance(r,dict) and 'id' in r for r in rows)
    if keyed(base) and keyed(result) and keyed(current):
        old={r['id']:r for r in base};new={r['id']:r for r in result};latest={r['id']:r for r in current}
        merged=[]
        for row in current:
            rid=row['id']
            if rid in old and rid not in new:continue
            merged.append(merge_delta(old[rid],new[rid],row) if rid in old and rid in new else copy.deepcopy(row))
        for row in result:
            if row['id'] not in old:
                if row['id'] in latest and latest[row['id']]!=row:raise StaleTask('新增结果ID冲突')
                if row['id'] not in latest:merged.append(copy.deepcopy(row))
        return merged
    if current!=base and current!=result:raise StaleTask('任务结果与并行编辑冲突，原内容已保留')
    return copy.deepcopy(result)

def apply_result(get,save,pid,base,result,task,read_fn,action,meta=None,reconcile_fn=None):
    for attempt in range(4):
        latest=get(pid)
        try:
            ensure_fresh(latest,task,read_fn(latest))
            merged=merge_delta(base,result,latest)
            if reconcile_fn:merged=reconcile_fn(latest,merged)
        except (ValueError,KeyError) as exc:
            candidate=dict(id=task['id'],label=task.get('label') or task.get('kind') or task.get('task'),baseVersion=base['version'],time=now(),reason=str(exc),changes=delta_entries(base,result),status='pending')
            latest.setdefault('workspace',{}).setdefault('generationSuggestions',[]).append(candidate)
            try:
                saved=save(latest,latest['version'],'studio:old_input_suggestion',dict(taskId=task['id']))
                task['savedAsSuggestion']=candidate['id'];return saved
            except HTTPException as conflict:
                if conflict.status_code!=409 or attempt==3:raise
                continue
        try:return save(merged,latest['version'],action,meta)
        except HTTPException as exc:
            if exc.status_code!=409 or attempt==3:raise
    raise StaleTask('项目持续变化，请重试')

def reserve(db,table,task):
    if table not in ('tasks','studio_jobs'):raise ValueError('invalid task table')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS studio_jobs(id TEXT PRIMARY KEY,project TEXT,body TEXT)')
        for other in ('tasks','studio_jobs'):
            for body, in c.execute('SELECT body FROM '+other+' WHERE project=?',(task['projectId'],)):
                existing=json.loads(body)
                if existing.get('status',existing.get('state')) in ('queued','running'):raise ValueError('本项目已有任务正在运行，请勿重复提交')
        c.execute('INSERT INTO '+table+' VALUES (?,?,?)',(task['id'],task['projectId'],json.dumps(task,ensure_ascii=False)))

def analysis_inputs(p,kind,request):
    structured_inputs=dict(structured=p.get('workspace',{}).get('entities',{}).get('material:main',{}).get('draft',{}).get('structured'),characters=[r['draft'] for r in p.get('workspace',{}).get('entities',{}).values() if r['kind']=='character' and r['state']!='deleted'])
    if kind=='document_parse':
        d=next((d for d in p['documents'] if d['id']==request['documentId']),{})
        return {k:d.get(k) for k in ('id','filename','contentHash')}
    if kind=='document_analysis':
        from .documents import inputs
        return dict(document=inputs(p,request),**structured_inputs)
    image=dict(image=p.get('image'),imageVersion=p.get('imageVersion'))
    if kind=='detect':return image
    if kind=='ocr':
        did=request.get('documentId');pages=request.get('pages',[])
        return dict(document=next((d for d in p.get('documents',[]) if d['id']==did),None),pages=pages,existing=[s for s in p['sources'] if s.get('documentId')==did and s.get('page') in pages and s.get('method')=='ocr'])
    if kind in ('materials','legacy_materials'):
        return dict(inputs=p.get('materialInputs'),sources=p['sources'],**structured_inputs) if kind=='materials' else p['sources']
    boxes=[{k:a.get(k) for k in ('id','kind','x','y','w','h')} for a in p['annotations']]
    if kind=='supplement':return dict(**image,boxes=boxes)
    if kind=='vision':return dict(**image,boxes=boxes)
    return dict(**image,boxes=boxes,characters=p['characters'],sources=p['sources'],observations=p.get('observations',[]) if kind=='match' else [])

def analysis_paths(p,kind,request):
    read=['/image','/imageVersion'];write=[]
    if kind=='document_parse':
        root='/documents/@'+request['documentId'];read=[root+'/filename',root+'/contentHash'];write=[root+'/'+k for k in ('pages','pageCount','parseStatus','parseVersion')]+['/sources/@'+s['id'] for s in p['sources'] if s.get('documentId')==request['documentId'] and s.get('method')=='extracted']
    elif kind=='document_analysis':
        from .documents import selected_sources
        read=['/sources/@'+r['source']['id'] for r in selected_sources(p,request) if r['source']];write=['/documentAnalysis']
    elif kind=='detect':write=['/annotations','/observations','/matches']
    elif kind=='supplement':read+=['/annotations'];write=['/visualDetectionProposal']
    elif kind in ('materials','legacy_materials'):
        read=['/materialInputs','/sources'] if kind=='materials' else ['/sources']
        write=['/legacyMaterialProposal'] if kind=='legacy_materials' else ['/materialAnalysis','/materialSegments']
    elif kind=='ocr':
        did=request.get('documentId');read=['/documents/@'+did]+['/sources/@'+s['id'] for s in p['sources'] if s.get('documentId')==did and s.get('page') in request.get('pages',[])]
        write=['/documentResults/'+did]
    else:
        read+=['/annotations']
        if kind in ('match','vision_match'):read+=['/characters','/sources']
        if kind=='match':read+=['/observations']
        if kind in ('vision','vision_match'):write+=['/observations','/visualOverview']
        if kind in ('match','vision_match'):write+=['/matches']
        fields=['description','faceRegion'] if kind in ('vision','vision_match') else []
        if kind in ('match','vision_match'):fields+=['characterId','identityConfirmed','needsReview']
        write += ['/annotations/@'+a['id']+'/'+field for a in p['annotations'] for field in fields]
    if kind in ('materials','document_analysis'):
        read+=['/workspace/entities/material:main/draft/structured']+['/workspace/entities/'+k+'/draft' for k,r in p.get('workspace',{}).get('entities',{}).items() if r['kind']=='character']
        write+=['/structured','/workspace/entities/material:main/draft/structured']
    return read,write
