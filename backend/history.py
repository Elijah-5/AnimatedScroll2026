"""Project-isolated history library: relational publication, versioned workspace drafts."""
import copy
import hashlib
import json
from datetime import datetime,timezone
from pydantic import BaseModel,Field
from fastapi import HTTPException
from .history_schema import TABLES,ENUMS,NUMBERS,NULLABLE,INSERT_ORDER,DELETE_ORDER,columns
from .domain import uid
from .task_runtime import digest


def empty():return {name:[] for name in TABLES}
def info(p):return p['workspace'].get('historyLibrary',{})


def read_tables(conn,pid):
    result=empty()
    for table in TABLES:
        cols=columns(table)
        result[table]=[dict(zip(cols,row)) for row in conn.execute('SELECT '+','.join(cols)+' FROM '+table+' WHERE project_id=?',(pid,)).fetchall()]
        result[table].sort(key=lambda r:(r.get('sort_order',0),r.get('id',r.get('person_id',''))))
    return result


def normalize(pid,tables):
    if set(tables)-set(TABLES):raise ValueError('存在未知历史数据表')
    out=empty()
    for table in TABLES:
        if not isinstance(tables.get(table,[]),list):raise ValueError('表内容必须为记录列表')
        for raw in tables.get(table,[]):
            if not isinstance(raw,dict):raise ValueError('记录必须为对象')
            if raw.get('project_id',pid)!=pid:raise ValueError('不能写入其他项目的历史资料')
            if set(raw)-set(columns(table)):raise ValueError('历史字段无效：'+table)
            row={field:copy.deepcopy(raw.get(field,0 if field in NUMBERS else None if field in NULLABLE else '')) for field in TABLES[table]['fields']}
            revision=raw.get('revision',0)
            if not isinstance(revision,int) or isinstance(revision,bool) or revision<0:raise ValueError('记录版本必须为非负整数')
            for field,value in row.items():
                if value is None and field not in NULLABLE and field not in NUMBERS:row[field]='';value=''
                if field in NUMBERS:
                    if not isinstance(value,int) or isinstance(value,bool):raise ValueError(field+'必须是整数')
                elif value is not None and not isinstance(value,str):raise ValueError(field+'必须是文本')
            row.update(project_id=pid,revision=revision)
            if 'work_id' in row and not row['work_id']:row['work_id']=pid
            if table=='works':row['id']=row['id'] or pid
            elif 'id' in row:row['id']=row['id'] or uid()
            for key in NULLABLE:
                if key in row and not row[key]:row[key]=None
            if table=='hist_sources':row['content_hash']=hashlib.sha256(row['snapshot_text'].encode()).hexdigest()
            out[table].append(row)
    return out


def validate(pid,tables):
    issues=[]
    def issue(table,r,message):issues.append(dict(table=table,id=r.get('id') or r.get('person_id',''),message=message))
    if len(tables['works'])!=1:issues.append(dict(table='works',id=pid,message='每个项目必须有且仅有一条画作档案'))
    lookup={t:{r.get('id'):r for r in rows} for t,rows in tables.items() if t!='work_persons'}
    for table,rows in tables.items():
        seen=set()
        for r in rows:
            key=r.get('id') if table!='work_persons' else (r['work_id'],r['person_id'])
            if key in seen:issue(table,r,'记录编号重复')
            seen.add(key)
            if r.get('project_id')!=pid or ('work_id' in r and r['work_id']!=pid) or table=='works' and r['id']!=pid:issue(table,r,'画作与所属项目必须一致')
            for field in TABLES[table]['fields']:
                value=r.get(field)
                optional=field in NULLABLE or field in ('artist','circulation','story_one_liner','character_id','publication_locator')
                if field in NUMBERS:
                    if not isinstance(value,int) or isinstance(value,bool) or value<0:issue(table,r,field+'必须是非负整数')
                elif not optional and (not isinstance(value,str) or not value.strip()):issue(table,r,field+'不能为空')
                if field in ENUMS and value not in ENUMS[field]:issue(table,r,field+'只能填写：'+'、'.join(ENUMS[field]))
            if table=='work_persons' and r['person_id'] not in lookup['persons']:issue(table,r,'人物不存在于本项目')
            if table=='hist_sources':
                if r['content_hash']!=hashlib.sha256(r['snapshot_text'].encode()).hexdigest():issue(table,r,'核对文本哈希不匹配')
                if not r['resource_uri'].startswith(('https://','document:')):issue(table,r,'请提供版本原文的HTTPS位置或本地文献定位')
            if table=='quotations':
                source=lookup['hist_sources'].get(r['source_id'])
                if not source:issue(table,r,'书目版本不在本项目')
                elif not (isinstance(r['source_start'],int) and isinstance(r['source_end'],int) and 0<=r['source_start']<r['source_end']<=len(source['snapshot_text']) and source['snapshot_text'][r['source_start']:r['source_end']]==r['original_text']):issue(table,r,'必须逐字定位到指定版本核对文本；不允许改写或拼接')
                if r['episode_id'] and r['episode_id'] not in lookup['background_episodes']:issue(table,r,'背景事件不在本项目')
                if r['original_text'].rstrip().endswith(('…','...')):issue(table,r,'原话不能用省略号截断')
            if table=='inferences' and r['quotation_id'] not in lookup['quotations']:issue(table,r,'推断必须指向本项目的一句史书原话')
            if table=='person_lines':
                if (pid,r['person_id']) not in {(v['work_id'],v['person_id']) for v in tables['work_persons']}:issue(table,r,'人物画像必须先建立画作与人物关联')
                if r['grounding']=='原话':
                    if r['quotation_id'] not in lookup['quotations'] or r['inference_id']:issue(table,r,'原话画像必须且只能关联史书原话')
                elif r['grounding']=='推断':
                    if r['inference_id'] not in lookup['inferences'] or r['quotation_id']:issue(table,r,'推断画像必须且只能关联历史推断')
    return issues


def row_key(table,row):return row['id'] if table!='work_persons' else row['work_id']+':'+row['person_id']
def business(row):return {k:v for k,v in row.items() if k!='revision'}


def changes(before,after):
    out=[]
    for table in TABLES:
        old={row_key(table,r):r for r in before[table]};new={row_key(table,r):r for r in after[table]}
        for key in sorted(set(old)|set(new)):
            if business(old.get(key,{}))!=business(new.get(key,{})):out.append(dict(table=table,id=key,before=old.get(key),after=new.get(key)))
    return out


def publish(conn,pid,before,after):
    for table in DELETE_ORDER:conn.execute('DELETE FROM '+table+' WHERE project_id=?',(pid,))
    for table in INSERT_ORDER:
        old={row_key(table,r):r for r in before[table]};cols=columns(table)
        for r in after[table]:
            prior=old.get(row_key(table,r))
            r['revision']=(prior['revision'] if prior and business(prior)==business(r) else (prior['revision'] if prior else 0)+1)
            conn.execute('INSERT INTO '+table+' ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',tuple(r[k] for k in cols))


def legacy_candidates(p):
    out=empty();mat=p['workspace']['entities']['material:main']['draft'];painting=mat.get('paintingInfo',{})
    out['works']=[dict(id=p['id'],title=painting.get('name') or p.get('artworkName',p['title']),artist=painting.get('artist',''),circulation=painting.get('description',''),story_one_liner='')]
    # Only suggestions: group roles, authors and uncertain scope are never forced into named historical people.
    for r in p['workspace']['entities'].values():
        if r['kind']!='character' or r['state']=='deleted':continue
        c=r['draft']
        if c.get('roleType')!='named' or c.get('depictionScope') not in ('depicted','background'):continue
        hid='hp-'+digest([p['id'],r['id']])[:20]
        out['persons'].append(dict(id=hid,canonical_name=c['name']))
        out['work_persons'].append(dict(work_id=p['id'],person_id=hid,presence='画中' if c['depictionScope']=='depicted' else '画外',character_id=r['id'] if c['depictionScope']=='depicted' else ''))
    return normalize(p['id'],out)


class SuggestedLine(BaseModel):
    aspect:str
    line_text:str
    grounding:str
    quotation_id:str=''
    inference_id:str=''
class SuggestedPerson(BaseModel):
    id:str
    canonical_name:str
    presence:str
    character_id:str=''
    lines:list[SuggestedLine]=Field(default_factory=list)
class SuggestedEpisode(BaseModel):
    id:str
    phase:str
    summary:str
    quotation_ids:list[str]=Field(default_factory=list)
class SuggestedInference(BaseModel):
    id:str
    author:str
    publication:str
    publication_locator:str=''
    claim:str
    quotation_id:str
class HistorySuggestion(BaseModel):
    artist:str=''
    circulation:str=''
    story_one_liner:str=''
    episodes:list[SuggestedEpisode]=Field(default_factory=list)
    persons:list[SuggestedPerson]=Field(default_factory=list)
    inferences:list[SuggestedInference]=Field(default_factory=list)
    research_notes:list[str]=Field(default_factory=list)


def generation_context(p):
    h=info(p);draft=h.get('draft') or empty()
    sources=[{k:v for k,v in s.items() if k!='snapshot_text'} for s in draft['hist_sources']]
    characters=[dict(id=r['id'],name=r['draft']['name'],scope=r['draft'].get('depictionScope'),roleType=r['draft'].get('roleType')) for r in p['workspace']['entities'].values() if r['kind']=='character' and r['state']!='deleted']
    analysis=p.get('documentAnalysis',{})
    return dict(projectId=p['id'],title=p.get('artworkName',p['title']),historicalSources=sources,quotations=draft['quotations'],
                researchClaims=analysis.get('claims',[])[:100],researchPeople=analysis.get('people',[]),characters=characters,
                materialInputs=p.get('materialInputs',{}),researchDocuments=[dict(id=d['id'],title=d.get('title'),citation=d.get('citation','')) for d in p.get('documents',[])])


def apply_suggestion(p,result):
    out=copy.deepcopy(info(p).get('draft') or empty());pid=p['id']
    if not out['works']:out['works']=[dict(id=pid,title=p.get('artworkName',p['title']))]
    for k in ('artist','circulation','story_one_liner'):
        if result.get(k):out['works'][0][k]=result[k]
    allowed={q['id'] for q in out['quotations']};person_ids={};episode_ids={};inference_ids={}
    stable=lambda kind,key:'h'+kind+'-'+digest([pid,key])[:20]
    for e in result['episodes']:episode_ids[e['id']]=stable('e',e['id'])
    for i in result['inferences']:inference_ids[i['id']]=stable('i',i['id'])
    for c in result['persons']:person_ids[c['id']]=stable('p',c['id'])
    out['background_episodes']=[];out['persons']=[];out['work_persons']=[];out['person_lines']=[];out['inferences']=[]
    for index,e in enumerate(result['episodes']):
        if not set(e['quotation_ids'])<=allowed:raise ValueError('背景引用了未提供的史书原话')
        out['background_episodes'].append(dict(id=episode_ids[e['id']],work_id=pid,phase=e['phase'],summary=e['summary'],sort_order=index))
    for q in out['quotations']:q['episode_id']=next((episode_ids[e['id']] for e in result['episodes'] if q['id'] in e['quotation_ids']),None)
    for i in result['inferences']:
        if i['quotation_id'] not in allowed:raise ValueError('推断引用了未提供的史书原话')
        out['inferences'].append(dict(i,id=inference_ids[i['id']],work_id=pid))
    existing={r['id'] for r in p['workspace']['entities'].values() if r['kind']=='character' and r['state']!='deleted'}
    for person in result['persons']:
        hid=person_ids[person['id']]
        if person['character_id'] and person['character_id'] not in existing:raise ValueError('关联创作人物ID无效')
        out['persons'].append(dict(id=hid,canonical_name=person['canonical_name']))
        out['work_persons'].append(dict(work_id=pid,person_id=hid,presence=person['presence'],character_id=person['character_id']))
        for index,line in enumerate(person['lines']):
            if line['quotation_id'] and line['quotation_id'] not in allowed:raise ValueError('画像引用了未提供的史书原话')
            out['person_lines'].append(dict(line,id=stable('l',[hid,index]),work_id=pid,person_id=hid,inference_id=inference_ids.get(line['inference_id']) if line['inference_id'] else None,sort_order=index))
    return normalize(pid,out)


def public_snapshot(tables,revision):
    out=copy.deepcopy(tables)
    for source in out['hist_sources']:source.pop('snapshot_text',None)
    return dict(revision=revision,tables=out)


def adopt_into_creation(p,tables,revision):
    from . import workspace as ws
    w=p['workspace'];qmap={q['id']:q for q in tables['quotations']};sources={s['id']:s for s in tables['hist_sources']}
    derived=[]
    for q in qmap.values():
        s=sources[q['source_id']]
        derived.append(dict(id='history-'+q['id'],version=q['revision'],title=s['title']+' '+q['locator'],text=q['original_text'],citation=s['edition'],location=q['locator'],sourceType='historical_primary',method='history_library',confirmed=True,historyQuotationId=q['id'],historyRevision=revision))
    p['sources']=[s for s in p['sources'] if s.get('method')!='history_library']+derived
    mat=w['entities']['material:main'];mat['draft']['sources']=copy.deepcopy(p['sources']);mat['draft']['historySnapshot']=public_snapshot(tables,revision)
    p['historySnapshot']=copy.deepcopy(mat['draft']['historySnapshot'])
    for link in tables['work_persons']:
        cid=link.get('character_id');r=w['entities'].get('character:'+cid) if cid else None
        if not r or r['state']=='deleted' or link['presence']!='画中':continue
        d=r['draft'];lines=[v for v in tables['person_lines'] if v['person_id']==link['person_id']]
        if not lines:continue
        d['historyPersonId']=link['person_id'];d['historyRevision']=revision
        d['historyLines']=copy.deepcopy(lines)
        for aspect,field in [('身份','identity'),('行事','biography'),('关系','relationships')]:
            values=[('研究推断：' if v['grounding']=='推断' else '史书记载：')+v['line_text'] for v in lines if v['aspect']==aspect]
            if values:d[field]='\n'.join(values)
        d['historyEvidence']=[dict(quotationId=q['id'],quote=q['original_text'],sourceId='history-'+q['id'],sourceVersion=q['revision']) for q in qmap.values() if any(v['quotation_id']==q['id'] for v in lines)]
    return ws.mirror(p)


class Draft(BaseModel):
    version:int
    baseRevision:int
    baseDraftHash:str
    tables:dict
class Action(BaseModel):
    version:int
    acceptRisk:bool=False


def install(app,get,save,db):
    def current(pid):
        p=get(pid)
        with db() as c:tables=read_tables(c,pid)
        return p,tables
    def check(p,v):
        if p['version']!=v:raise HTTPException(409,'项目版本已变化，当前历史资料编辑已保留')
    def result(p,tables):
        h=info(p);draft=h.get('draft')
        return dict(projectId=p['id'],version=p['version'],revision=h.get('revision',0),tables=tables,draft=draft,draftHash=digest(draft),
                    definitions=TABLES,enums=ENUMS,issues=validate(p['id'],draft) if draft is not None else [],researchNotes=h.get('researchNotes',[]))
    @app.get('/api/projects/{pid}/history')
    def read(pid:str):return result(*current(pid))
    @app.put('/api/projects/{pid}/history/draft')
    def draft(pid:str,req:Draft):
        p,tables=current(pid);check(p,req.version);h=p['workspace'].setdefault('historyLibrary',{})
        if req.baseRevision!=h.get('revision',0) or req.baseDraftHash!=digest(h.get('draft')):raise HTTPException(409,'历史版本或草稿已变化，当前编辑未覆盖')
        try:h['draft']=normalize(pid,req.tables)
        except (ValueError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc
        h['baseRevision']=h.get('revision',0)
        p=save(p,req.version,'studio:history:draft');return result(p,tables)
    @app.post('/api/projects/{pid}/history/legacy-candidates')
    def legacy(pid:str,req:Action):
        p,tables=current(pid);check(p,req.version);h=p['workspace'].setdefault('historyLibrary',{})
        if h.get('draft') is not None:raise HTTPException(409,'已有历史草稿，请先保存、确认或撤回；不会覆盖')
        h.update(draft=legacy_candidates(p) if not tables['works'] else copy.deepcopy(tables),baseRevision=h.get('revision',0))
        p=save(p,req.version,'studio:history:legacy_candidates');return result(p,tables)
    @app.post('/api/projects/{pid}/history/preview')
    def preview(pid:str,req:Action):
        p,tables=current(pid);check(p,req.version);draft=info(p).get('draft')
        if draft is None:raise HTTPException(422,'没有待确认的历史草稿')
        changed=changes(tables,draft);affected=[]
        mat=p['workspace']['entities']['material:main']
        if changed and (mat.get('published') or {}).get('historySnapshot'):affected=[dict(key='material:main',name='已采用的历史资料',mode='available_update')]
        return dict(changes=changed,issues=validate(pid,draft),affected=affected,requiresRisk=bool(affected))
    @app.post('/api/projects/{pid}/history/confirm')
    def confirm(pid:str,req:Action):
        p,tables=current(pid);check(p,req.version);h=p['workspace'].setdefault('historyLibrary',{});draft=h.get('draft')
        if draft is None:raise HTTPException(422,'没有待确认的历史草稿')
        issues=validate(pid,draft)
        if issues:raise HTTPException(422,dict(message='历史资料未通过校验',issues=issues))
        for link in draft['work_persons']:
            if link.get('character_id') and 'character:'+link['character_id'] not in p['workspace']['entities']:raise HTTPException(422,'关联的创作人物不存在')
        changed=changes(tables,draft)
        if changed and (p['workspace']['entities']['material:main'].get('published') or {}).get('historySnapshot') and not req.acceptRisk:raise HTTPException(409,dict(code='risk_confirmation_required',message='已采用旧历史版本；新版本不会自动覆盖制作稿，请确认后再明确采用',changes=changed))
        after=copy.deepcopy(draft);h.update(revision=h.get('revision',0)+int(bool(changed)),draft=None)
        def commit(conn,old,project):publish(conn,pid,tables,after)
        p=save(p,req.version,'studio:history:confirm',dict(historyBefore=tables,historyAfter=after,historyRevision=h['revision']),transaction_hook=commit)
        return result(p,after)
    @app.post('/api/projects/{pid}/history/discard')
    def discard(pid:str,req:Action):
        p,tables=current(pid);check(p,req.version);p['workspace'].setdefault('historyLibrary',{})['draft']=None
        p=save(p,req.version,'studio:history:discard');return result(p,tables)
    @app.post('/api/projects/{pid}/history/adopt')
    def adopt(pid:str,req:Action):
        p,tables=current(pid);check(p,req.version)
        if not tables['works']:raise HTTPException(422,'请先确认历史资料库')
        adopt_into_creation(p,tables,info(p).get('revision',0))
        p=save(p,req.version,'studio:history:adopt');return p
