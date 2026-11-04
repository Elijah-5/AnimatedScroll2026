"""One versioned material library. Evidence remains exact and never becomes verified by model output."""
import copy
import re
from pydantic import BaseModel, Field
from typing import Literal
from .task_runtime import digest

FIELDS={'name':'作品名称','artist':'作者','period':'绘画年代','storyPeriod':'故事时代','medium':'材质与技法','dimensions':'尺寸','collection':'收藏机构','accession':'馆藏编号','description':'作品说明','circulation':'作品流传','storyOneLiner':'画中故事'}
CATEGORIES={'supported','inference','uncertain','fiction'}

def stable(kind,value):return kind+'-'+digest(value)[:20]
def cell(value='',refs=None,origin='generated'):
    return dict(value=value,referenceIds=refs or [],origin=origin,generatedValue=value if origin=='generated' else None)
def empty():return dict(schemaVersion='1.0',artwork={k:cell() for k in FIELDS},people=[],events=[],relations=[],statements=[],research=[],sources=[],evidence=[],missing=[],conflicts=[])

def seed(p,tables=None):
    """Local conversion: no calls, no publication, no independent people or evidence invented."""
    out=empty();mat=p['workspace']['entities']['material:main']['draft'];analysis=p.get('documentAnalysis') or {}
    sources=copy.deepcopy(mat.get('sources',p.get('sources',[])))
    for s in mat.get('structured',{}).get('sources',[]):
        if not any(v['id']==s['id'] and v['version']==s['version'] for v in sources):sources.append(copy.deepcopy(s))
    # Parsing candidates may not have been adopted into the legacy summaries yet.
    for s in p.get('sources',[]):
        if not any(v['id']==s['id'] and v['version']==s['version'] for v in sources):sources.append(copy.deepcopy(s))
    out['sources']=sources;lookup={(s['id'],s['version']):s for s in sources}
    for e in mat.get('structured',{}).get('evidence',[]):
        s=lookup.get((e.get('sourceId'),e.get('sourceVersion')))
        if s and s['text'][e.get('start',0):e.get('end',0)]==e.get('quote'):out['evidence'].append(copy.deepcopy(e))
    def evidence(ref,level=None):
        source=lookup.get((ref.get('sourceId'),ref.get('sourceVersion')));quote=ref.get('quote','')
        if not source or not quote:return None
        start=ref.get('start',source['text'].find(quote));end=start+len(quote)
        if start<0 or source['text'][start:end]!=quote:return None
        key=stable('e',[source['id'],source['version'],start,end])
        if not any(v['id']==key for v in out['evidence']):
            kind=level or ('creator' if source.get('method')=='material_input' else 'research')
            out['evidence'].append(dict(id=key,sourceId=source['id'],sourceVersion=source['version'],quote=quote,start=start,end=end,documentId=source.get('documentId'),page=source.get('page'),level=kind,verification='unverified',edition=source.get('citation',''),sourceTitle=source.get('title','')))
        elif level=='indirect':
            next(v for v in out['evidence'] if v['id']==key)['level']='indirect'
        return key
    def refs(items):return list(dict.fromkeys(r for item in items or [] if (r:=evidence(item,'indirect' if item.get('indirectSource') else None))))
    painting=mat.get('paintingInfo',{})
    for k in FIELDS:
        if painting.get(k):out['artwork'][k]=cell(painting[k],origin='legacy')
    if not out['artwork']['name']['value']:out['artwork']['name']=cell(p.get('artworkName') or p['title'],origin='project')
    chars=[r for r in p['workspace']['entities'].values() if r['kind']=='character' and r['state']!='deleted']
    chars += [dict(id=c['id'],draft=c) for c in p.get('characters',[]) if not any(r['id']==c['id'] for r in chars)]
    for r in chars:
        c=r['draft'];rid=r['id'];rr=refs(c.get('mentions',[]));annotations=[a['id'] for a in mat.get('annotations',[]) if a.get('characterId')==rid]
        out['people'].append(dict(id=rid,characterId=rid,name=c['name'],roleType=c.get('roleType','role'),scope=c.get('depictionScope','unknown'),contextRoles=[],annotationIds=annotations,referenceIds=rr))
        for aspect,field in [('身份','identity'),('行事','biography'),('关系','relationships'),('概述','summary')]:
            if c.get(field):out['statements'].append(dict(id=stable('line',[rid,field]),personId=rid,aspect=aspect,text=c[field],category='uncertain' if not rr else 'inference',referenceIds=rr,origin='profile',profileField=field))
    for c in analysis.get('people',[]):
        matches=[v for v in out['people'] if v['name']==c['name'] and v['scope']==c.get('scope','unknown')]
        if len(matches)==1:continue
        rid=stable('person',[p['id'],c.get('id') or c['name'],c.get('scope'),c.get('contextRoles')])
        out['people'].append(dict(id=rid,characterId='',name=c['name'],roleType=c.get('roleType','named'),scope=c.get('scope','unknown'),contextRoles=c.get('contextRoles',[]),annotationIds=[],referenceIds=refs(c.get('references',[]))))
    for a in mat.get('annotations',[]):
        if not a.get('confirmed') or not a.get('description') or not any(v['id']==a.get('characterId') for v in out['people']):continue
        text=a['description'];sid=stable('observation',[p['id'],mat.get('image'),a['id'],text,{k:a.get(k) for k in ('x','y','w','h')}]);version=max(1,mat.get('imageVersion',0))
        source=dict(id=sid,version=version,title='已确认画面观察 · '+a['id'],text=text,citation='画面实例 '+a['id'],sourceType='visual_observation',annotationId=a['id'],confirmed=True)
        if (sid,version) not in lookup:out['sources'].append(source);lookup[(sid,version)]=source
        eid=evidence(dict(sourceId=sid,sourceVersion=version,quote=text),'observation')
        out['statements'].append(dict(id=stable('observation-line',[a['id'],text]),personId=a['characterId'],aspect='画面观察',text=text,category='uncertain',referenceIds=[eid],origin='observation',annotationId=a['id']))
    for c in analysis.get('claims',[]):
        rr=refs([dict(r,indirectSource=c.get('indirectSource')) for r in c.get('references',[])])
        if not rr:continue
        for e in out['evidence']:
            if e['id'] in rr:
                context=dict(topic=c.get('topic','uncertain'),assertion=c.get('assertion'),indirectSource=c.get('indirectSource',''),targetArtwork=analysis.get('targetArtwork',p.get('artworkName',p['title'])))
                if context not in e.setdefault('contexts',[]):e['contexts'].append(context)
        kind=c.get('assertion');category='inference' if kind=='interpretation' else 'uncertain' if kind=='uncertain' else 'supported'
        row=dict(id=c.get('id') or stable('claim',c),text=c['text'],referenceIds=rr,category=category,origin='generated',generatedValue=c['text'],topic=c.get('topic','uncertain'))
        out['research'].append(row)
        if c.get('topic')=='story':out['events'].append(dict(row,title=c['text'][:45],phase='未明',time=''))
    for e in mat.get('historicalEvents',[]):
        out['events'].append(dict(id=e['id'],title=e.get('title',''),text=e.get('description',''),time=e.get('time',''),phase='未明',referenceIds=refs([e.get('evidence',{})]),category='uncertain',origin='legacy'))
    for r in p['workspace']['entities'].values():
        if r['kind']!='clue' or r['state']=='deleted':continue
        for e in r['draft'].get('relations',[]):out['relations'].append(dict(id=stable('relation',[r['id'],e]),fromId=e['fromId'],toId=e['toId'],label=e['label'],referenceIds=refs([e]),category='inference',origin='legacy'))
    # Short exact source passages make unclassified/manual material available too.
    for s in sources:
        if s.get('sourceType')=='creative_intent':continue
        if any(e['sourceId']==s['id'] and e['sourceVersion']==s['version'] for e in out['evidence']):continue
        if s.get('method') in ('extracted','ocr'):continue
        text=s.get('text','')
        for match in re.finditer(r'[^。\n]{1,650}[。\n]?',text):evidence(dict(sourceId=s['id'],sourceVersion=s['version'],quote=match[0],start=match.start()))
    imported=tables or mat.get('historySnapshot',{}).get('tables') or p.get('workspace',{}).get('historyLibrary',{}).get('draft')
    if imported:import_legacy(out,p,imported)
    for e in out['evidence']:
        for k,label in FIELDS.items():
            m=re.search(re.escape(label)+r'[：:]\s*([^。；\n]{1,120})',e['quote'])
            if m and not out['artwork'][k]['value']:out['artwork'][k]=cell(m[1].strip(),[e['id']])
    return finish(out)

def import_legacy(out,p,tables):
    """Keep every old row and review marker; only verified primary spans enter direct evidence."""
    out['legacyTables']=copy.deepcopy(tables)
    works=tables.get('works',[])
    if works:
        for old,new in [('title','name'),('artist','artist'),('circulation','circulation'),('story_one_liner','storyOneLiner')]:
            value=works[0].get(old,'')
            if value and not out['artwork'][new]['value']:out['artwork'][new]=cell(value,origin='legacy')
            elif value and value!=out['artwork'][new]['value']:out['conflicts'].append(dict(id=stable('conflict',[new,value]),field='artwork.'+new,current=out['artwork'][new]['value'],candidate=value,reason='旧资料值不同，保留现值'))
    smap={s['id']:s for s in tables.get('hist_sources',[])};qmap={};links={r['person_id']:r for r in tables.get('work_persons',[])}
    for q in tables.get('quotations',[]):
        s=smap.get(q['source_id'],{});text=s.get('snapshot_text','');a=q.get('source_start');b=q.get('source_end');valid=isinstance(a,int) and isinstance(b,int) and 0<=a<b<=len(text) and text[a:b]==q['original_text'] and bool(s.get('edition'))
        if not valid:
            out.setdefault('importWarnings',[]).append(dict(field='legacy.quotations.'+q['id'],label='旧史书原话',reason='版本、核对文本或原文位置无法恢复；未伪造核验依据'))
            continue
        sid='history-'+s['id'];version=max(1,s.get('revision',0));source=dict(id=sid,version=version,title=s['title'],text=text,citation=s['edition'],sourceType='historical_primary',confirmed=True,genre=s.get('genre'),resource_uri=s.get('resource_uri'),historySourceId=s['id'],verification_note=s.get('verification_note',''))
        if not any(v['id']==sid and v['version']==version for v in out['sources']):out['sources'].append(source)
        eid='history-'+q['id'];qmap[q['id']]=eid
        out['evidence'].append(dict(id=eid,sourceId=sid,sourceVersion=version,quote=q['original_text'],start=a,end=b,edition=s['edition'],locator=q.get('locator',''),level='direct',verification='edition_verified' if q.get('revision',0)>0 and s.get('revision',0)>0 else 'unverified',legacyId=q['id']))
    personmap={}
    for person in tables.get('persons',[]):
        link=links.get(person['id'],{});cid=link.get('character_id');rid=cid if any(v['id']==cid for v in out['people']) else person['id'];personmap[person['id']]=rid
        if not any(v['id']==rid for v in out['people']):out['people'].append(dict(id=rid,characterId='',name=person['canonical_name'],roleType='named',scope='depicted' if link.get('presence')=='画中' else 'background' if link.get('presence')=='画外' else 'unknown',annotationIds=[],contextRoles=[],referenceIds=[]))
    imap={i['id']:i for i in tables.get('inferences',[])}
    for i in tables.get('inferences',[]):out['research'].append(dict(id=i['id'],text=i['claim'],author=i['author'],publication=i['publication'],category='inference',origin='legacy',referenceIds=[qmap[i['quotation_id']]] if i['quotation_id'] in qmap else []))
    for line in tables.get('person_lines',[]):
        qid=line.get('quotation_id') or imap.get(line.get('inference_id'),{}).get('quotation_id')
        out['statements'].append(dict(id=line['id'],personId=personmap.get(line['person_id'],line['person_id']),aspect=line['aspect'],text=line['line_text'],category='supported' if line['grounding']=='原话' else 'inference',origin='legacy',referenceIds=[qmap[qid]] if qid in qmap else []))
    for event in tables.get('background_episodes',[]):out['events'].append(dict(id=event['id'],title=event['summary'][:45],text=event['summary'],phase=event['phase'],time='',origin='legacy',category='supported',referenceIds=[qmap[q['id']] for q in tables.get('quotations',[]) if q.get('episode_id')==event['id'] and q['id'] in qmap]))

def finish(out):
    out['missing']=[dict(field='artwork.'+k,label=label,reason='现有资料未提供或尚未定位依据') for k,label in FIELDS.items() if not out['artwork'][k]['value']]
    out['missing']+=copy.deepcopy(out.get('importWarnings',[]))
    for collection,label in [('events','历史背景'),('relations','人物关系'),('statements','人物画像')]:
        if not out[collection]:out['missing'].append(dict(field=collection,label=label,reason='现有资料尚未形成有依据的条目'))
    for e in out['evidence']:
        if e.get('level')=='indirect' and e.get('verification')!='edition_verified':out['missing'].append(dict(field='evidence.'+e['id'],label='转引史书版本',reason='经研究资料转引，未独立核对原书版本'))
        elif e.get('level')=='direct' and e.get('verification')!='edition_verified':out['missing'].append(dict(field='evidence.'+e['id'],label='原书版本核对',reason='已保留所提供文本，尚未人工独立核对指定原书版本'))
    for key in ('people','events','relations','statements','research','evidence'):
        out[key]=list({r['id']:r for r in out[key]}.values())
    out['conflicts']=list({r['id']:r for r in out.get('conflicts',[])}.values())
    return out

class SuggestedField(BaseModel):
    field:str
    value:str
    referenceIds:list[str]=Field(min_length=1)
class SuggestedRow(BaseModel):
    text:str
    referenceIds:list[str]=Field(min_length=1)
    category:Literal['supported','inference','uncertain']='uncertain'
    title:str=''
    phase:Literal['前因','画中','后续','未明']='未明'
    time:str=''
    personId:str=''
    aspect:str='概述'
    fromId:str=''
    toId:str=''
    label:str=''
    author:str=''
    publication:str=''
class Suggestion(BaseModel):
    artwork:list[SuggestedField]=Field(default_factory=list)
    events:list[SuggestedRow]=Field(default_factory=list)
    statements:list[SuggestedRow]=Field(default_factory=list)
    relations:list[SuggestedRow]=Field(default_factory=list)
    research:list[SuggestedRow]=Field(default_factory=list)

def apply_suggestion(out,result):
    result=Suggestion.model_validate(result).model_dump();known={e['id'] for e in out['evidence']};people={p['id'] for p in out['people']}
    for collection,rows in result.items():
        for row in rows:
            if not set(row['referenceIds'])<=known:raise ValueError('结构化结果引用了不存在的原文依据')
            cited=' '.join(e.get('quote','')+' '+e.get('edition','')+' '+e.get('sourceTitle','') for e in out['evidence'] if e['id'] in row['referenceIds'])
            if any(row.get(k) and row[k] not in cited for k in ('author','publication')):raise ValueError('研究作者或出处未在所提供依据中定位')
            if collection=='artwork':
                k=row['field']
                if k not in FIELDS:raise ValueError('作品档案字段无效')
                existing=out['artwork'][k]
                if not existing['value']:out['artwork'][k]=cell(row['value'],row['referenceIds'])
                elif existing['value']!=row['value']:out['conflicts'].append(dict(id=stable('conflict',[k,row]),field='artwork.'+k,current=existing['value'],candidate=row['value'],referenceIds=row['referenceIds'],reason='存在不同资料值，需人工核对'))
                continue
            if collection=='statements' and row['personId'] not in people:raise ValueError('人物画像关联了未知人物')
            if collection=='relations' and (row['fromId'] not in people or row['toId'] not in people or row['fromId']==row['toId']):raise ValueError('关系两端必须是已提供的不同人物')
            if collection=='research':row['category']='inference' if row['category']=='supported' else row['category']
            row.update(id=stable(collection,[row['text'],row['referenceIds'],row['personId'],row['fromId'],row['toId']]),origin='generated',generatedValue=row['text']);out[collection].append(row)
    return finish(out)

def merge(existing,incoming):
    if not existing:return finish(incoming)
    out=copy.deepcopy(incoming);out['conflicts']+=copy.deepcopy(existing.get('conflicts',[]))
    for k,old in existing.get('artwork',{}).items():
        if k not in FIELDS:continue
        generated=old.get('origin')=='generated' and old.get('value')==old.get('generatedValue')
        if old.get('value') and (not generated or not out['artwork'][k]['value']):
            new=out['artwork'][k]
            if new['value'] and old['value']!=new['value']:out['conflicts'].append(dict(id=stable('conflict',[k,new['value']]),field='artwork.'+k,current=old['value'],candidate=new['value'],referenceIds=new['referenceIds'],reason='保留人工或旧资料值'))
            out['artwork'][k]=copy.deepcopy(old)
    for key in ('people','events','relations','statements','research'):
        new={r['id']:r for r in out[key]}
        for row in existing.get(key,[]):
            protected=row.get('origin')!='generated' or row.get('text')!=row.get('generatedValue')
            if protected and row['id'] in new and row.get('text') and row.get('text')!=new[row['id']].get('text'):
                candidate=new[row['id']]
                out['conflicts'].append(dict(id=stable('conflict',[key,row['id'],candidate.get('text')]),field=key+'.'+row['id']+'.text',current=row['text'],candidate=candidate.get('text',''),referenceIds=candidate.get('referenceIds',[]),reason='保留人工条目，新资料值待核对'))
            if row['id'] not in new or protected:new[row['id']]=copy.deepcopy(row)
        out[key]=list(new.values())
    # Historic evidence is preserved with its original source text and version.
    for key,identity in [('evidence',lambda r:r['id']),('sources',lambda r:(r['id'],r['version']))]:
        new={identity(r):r for r in out[key]}
        for row in existing.get(key,[]):new.setdefault(identity(row),copy.deepcopy(row))
        out[key]=list(new.values())
    if existing.get('legacyTables'):out.setdefault('legacyTables',copy.deepcopy(existing['legacyTables']))
    out['importWarnings']=list({digest(r):r for r in out.get('importWarnings',[])+existing.get('importWarnings',[])}.values())
    versions=out.get('legacyVersions',[])+copy.deepcopy(existing.get('legacyVersions',[]))
    if versions:out['legacyVersions']=list({digest(v):v for v in versions}.values())
    return finish(out)

async def ask(context):
    from . import studio_agent,task_runtime as tr
    tr.model_request.get()()
    return await studio_agent.run('structure_materials',context)

async def organize(p,cache_get=lambda k:None,cache_put=lambda k,v:None,base=None):
    from .documents import bounded_groups
    from . import task_runtime as tr
    from .config import model_settings
    settings=model_settings(require_key=False)
    base=base or seed(p);existing=p['workspace']['entities']['material:main']['draft'].get('structured')
    for group in bounded_groups(base['evidence'],limit=14000):
        tr.checkpoint.get()()
        ctx=dict(title=base['artwork']['name']['value'],fields=FIELDS,people=[{k:v.get(k) for k in ('id','name','scope','roleType','contextRoles')} for v in base['people']],evidence=group)
        key='structured-v1-'+digest([settings.provider,settings.base_url,settings.model,ctx]);result=cache_get(key);fresh=result is None
        if fresh:result=await ask(ctx);result=Suggestion.model_validate(result).model_dump()
        try:apply_suggestion(base,result)
        except ValueError:
            if not fresh:cache_put(key,None)
            raise
        if fresh:cache_put(key,result)
    return merge(existing,base)

def install_draft(p,value):
    validate(value)
    p['workspace']['entities']['material:main']['draft']['structured']=copy.deepcopy(value)
    p['structured']=copy.deepcopy(value)

def validate(value):
    if not isinstance(value,dict) or value.get('schemaVersion')!='1.0':raise ValueError('作品资料库格式版本无效')
    for k in ('artwork','people','events','relations','statements','research','sources','evidence','missing','conflicts'):
        if k not in value:raise ValueError('作品资料库缺少字段：'+k)
        if k!='artwork' and (not isinstance(value[k],list) or any(not isinstance(r,dict) for r in value[k])):raise ValueError('作品资料库集合格式无效：'+k)
    if not isinstance(value['artwork'],dict) or set(value['artwork'])!=set(FIELDS) or any(not isinstance(r,dict) or not isinstance(r.get('value'),str) for r in value['artwork'].values()):raise ValueError('作品档案字段格式无效')
    sources={(s['id'],s['version']):s for s in value['sources']};evidence={e['id']:e for e in value['evidence']};people={p['id']:p for p in value['people']}
    if len(sources)!=len(value['sources']):raise ValueError('作品资料库同一来源版本重复')
    if any(not isinstance(s['version'],int) or isinstance(s['version'],bool) or s['version']<1 or not isinstance(s.get('text'),str) for s in sources.values()):raise ValueError('来源文本或版本格式无效')
    for collection in ('people','events','relations','statements','research','evidence'):
        if len({r['id'] for r in value[collection]})!=len(value[collection]):raise ValueError('作品资料库条目编号重复')
    for e in evidence.values():
        s=sources.get((e['sourceId'],e['sourceVersion']));a=e.get('start');b=e.get('end')
        if not s or not isinstance(a,int) or not isinstance(b,int) or not 0<=a<b<=len(s['text']) or s['text'][a:b]!=e['quote']:raise ValueError('作品资料库引文与原文版本／位置不符')
        if e.get('level') not in ('direct','indirect','research','creator','observation') or e.get('verification') not in ('unverified','edition_verified'):raise ValueError('资料依据核验类型无效')
        if e.get('verification')=='edition_verified' and (e.get('level')!='direct' or not e.get('edition') or s.get('sourceType')!='historical_primary' or e['edition']!=s.get('citation')):raise ValueError('不能把转引、研究资料或不符的版本升级为直接核对史书')
    for row in list(value['artwork'].values())+sum([value[k] for k in ('people','events','relations','statements','research')],[]):
        if not set(row.get('referenceIds',[]))<=evidence.keys():raise ValueError('作品资料库引用不存在')
        if row.get('category') and row['category'] not in CATEGORIES:raise ValueError('资料事实属性无效')
    for row in value['statements']:
        if row.get('personId') and row['personId'] not in people:raise ValueError('人物画像关联不存在')
    for row in value['relations']:
        if row['fromId'] not in people or row['toId'] not in people or row['fromId']==row['toId']:raise ValueError('人物关系关联无效')

def view(p,published=True):
    """Legacy fallback is derived from exactly the chosen material, never live drafts."""
    from . import workspace as ws
    w=ws.ensure(p);record=w['entities']['material:main'];mat=record['published'] if published else record['draft']
    if mat is None:raise ValueError('资料尚未确认')
    if mat.get('structured'):return copy.deepcopy(mat['structured'])
    frozen=copy.deepcopy(p);frozen['workspace']['entities']['material:main']['draft']=copy.deepcopy(mat)
    for r in frozen['workspace']['entities'].values():
        if published:r['draft']=copy.deepcopy(r.get('published') or {})
    if published:
        frozen['workspace']['entities']={k:r for k,r in frozen['workspace']['entities'].items() if r.get('published') is not None}
        frozen['documentAnalysis']={};frozen['sources']=copy.deepcopy(mat.get('sources',[]));frozen['workspace'].pop('historyLibrary',None)
    return seed(frozen)

def role_context(p,cid):
    from .consumption import confirmed
    person=confirmed(p,'character',cid);data=view(p)
    rows=[r for r in data['statements'] if r.get('personId')==cid and (not r.get('profileField') or r['text']==person.get(r['profileField']))]
    ids={ref for r in rows for ref in r.get('referenceIds',[])}
    return dict(statements=rows,evidence=[e for e in data['evidence'] if e['id'] in ids])

def compact(value):
    result={k:copy.deepcopy(v) for k,v in value.items() if k not in ('sources','legacyTables','legacyVersions')}
    result['sources']=[{k:s.get(k) for k in ('id','version','title','citation','sourceType')} for s in value['sources']]
    return result

def published_payload(value):
    result={k:copy.deepcopy(v) for k,v in value.items() if k not in ('legacyTables','legacyVersions')}
    used={(e['sourceId'],e['sourceVersion']) for e in result['evidence']}
    result['sources']=[s for s in result['sources'] if (s['id'],s['version']) in used]
    return result

def material_sources(material):
    sources=copy.deepcopy(material.get('sources',[]));data=material.get('structured')
    if data:
        used={(e['sourceId'],e['sourceVersion']) for e in data['evidence']}
        extras=[dict(s,confirmed=True) for s in data['sources'] if (s['id'],s['version']) in used]
        lookup={(s['id'],s['version']):s for s in sources}
        lookup.update({(s['id'],s['version']):s for s in extras});sources=list(lookup.values())
    return sources

def preview(p,db):
    from .history import read_tables
    mat=p['workspace']['entities']['material:main']['draft']
    if mat.get('structured'):return copy.deepcopy(mat['structured'])
    with db() as conn:tables=read_tables(conn,p['id'])
    out=seed(p,tables if tables['works'] else None)
    pending=p['workspace'].get('historyLibrary',{}).get('draft')
    out['legacyVersions']=[]
    if tables['works']:out['legacyVersions'].append(dict(state='published',revision=p['workspace'].get('historyLibrary',{}).get('revision',0),tables=copy.deepcopy(tables)))
    if pending:
        out['legacyVersions'].append(dict(state='draft',tables=copy.deepcopy(pending)))
        import_legacy(out,p,pending)
    return finish(out)

def projection(p,value):
    from . import history
    pid=p['id'];out=history.empty();a=value['artwork'];v=lambda k:a.get(k,{}).get('value','')
    out['works']=[dict(id=pid,title=v('name') or p['title'],artist=v('artist'),circulation=v('circulation'),story_one_liner=v('storyOneLiner'))]
    legacy=value.get('legacyTables',{});oldlinks={r.get('character_id'):r['person_id'] for r in legacy.get('work_persons',[]) if r.get('character_id')};person_ids={}
    for person in value['people']:
        if person['roleType']!='named' or person['scope'] not in ('depicted','background') or set(person.get('contextRoles',[]))&{'creator','collector','scholar','inscriber','other_artwork'}:continue
        rid=oldlinks.get(person.get('characterId')) or person['id'];person_ids[person['id']]=rid
        out['persons'].append(dict(id=rid,canonical_name=person['name']));out['work_persons'].append(dict(work_id=pid,person_id=rid,presence='画中' if person['scope']=='depicted' else '画外',character_id=person.get('characterId','')))
    for index,event in enumerate(value['events']):
        if event.get('phase') in ('前因','画中','后续'):out['background_episodes'].append(dict(id=event['id'],work_id=pid,phase=event['phase'],summary=event['text'],sort_order=index))
    # Existing strict rows remain available, but unsupported research is never
    # squeezed into the eight-table primary-history subset.
    sources={s['id']:s for s in legacy.get('hist_sources',[])}
    direct={e.get('legacyId'):e for e in value['evidence'] if e.get('verification')=='edition_verified' and e.get('legacyId')}
    episodes={e['id'] for e in out['background_episodes']}
    for q in legacy.get('quotations',[]):
        if q['id'] not in direct or q['source_id'] not in sources:continue
        s=sources[q['source_id']]
        if not any(r['id']==s['id'] for r in out['hist_sources']):out['hist_sources'].append(copy.deepcopy(s))
        q=copy.deepcopy(q)
        if q.get('episode_id') not in episodes:q['episode_id']=None
        out['quotations'].append(q)
    canonical_sources={(s['id'],s['version']):s for s in value['sources']}
    from .history_schema import ENUMS
    for e in value['evidence']:
        if e.get('verification')!='edition_verified' or e.get('legacyId'):continue
        source=canonical_sources[(e['sourceId'],e['sourceVersion'])]
        if source.get('genre') not in ENUMS['genre'] or not str(source.get('resource_uri','')).startswith(('https://','document:')):continue
        sid=stable('book',[source['id'],source['version']])
        if not any(r['id']==sid for r in out['hist_sources']):out['hist_sources'].append(dict(id=sid,title=source['title'],genre=source['genre'],edition=e['edition'],resource_uri=source['resource_uri'],snapshot_text=source['text'],verification_note=source.get('verification_note','创作者在统一资料中核对')))
        episode=next((r['id'] for r in value['events'] if r['id'] in episodes and e['id'] in r['referenceIds']),None)
        out['quotations'].append(dict(id=e['id'],source_id=sid,work_id=pid,episode_id=episode,locator=e.get('locator') or '核对文本位置 '+str(e['start'])+'–'+str(e['end']),original_text=e['quote'],source_start=e['start'],source_end=e['end']))
    qids={q['id'] for q in out['quotations']}
    out['inferences']=[copy.deepcopy(i) for i in legacy.get('inferences',[]) if i.get('quotation_id') in qids]
    mapped={link['person_id']:oldlinks.get(link.get('character_id')) or link['person_id'] for link in legacy.get('work_persons',[])}
    pids={r['id'] for r in out['persons']};iids={i['id'] for i in out['inferences']}
    for line in legacy.get('person_lines',[]):
        rid=mapped.get(line['person_id'],line['person_id'])
        if rid in pids and (line.get('quotation_id') in qids or line.get('inference_id') in iids):out['person_lines'].append(dict(line,person_id=rid))
    result=history.normalize(pid,out)
    # A broken legacy subset stays in legacyVersions for review; it cannot block
    # unrelated unified facts or silently become verified relational data.
    if history.validate(pid,result):
        for k in ('person_lines','inferences','quotations','hist_sources'):result[k]=[]
    return result

def synchronize(conn,old,p):
    r=p.get('workspace',{}).get('entities',{}).get('material:main',{});value=(r.get('published') or {}).get('structured')
    before=((old or {}).get('workspace',{}).get('entities',{}).get('material:main',{}).get('published') or {}).get('structured')
    if value is None or value==before:return
    from .history import read_tables,publish
    publish(conn,p['id'],read_tables(conn,p['id']),projection(p,value))

def install(app,get,save,db):
    @app.get('/api/projects/{pid}/structured')
    def inspect(pid:str):
        p=get(pid);r=p['workspace']['entities']['material:main']
        return dict(projectId=pid,version=p['version'],revision=r['revision'],draft=preview(p,db),derivedPreview=not bool(r['draft'].get('structured')),fields=FIELDS)
    @app.middleware('http')
    async def retired_history(request,call_next):
        if '/history/' in request.url.path and request.method in ('POST','PUT','PATCH','DELETE'):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=410,content=dict(detail='历史资料已合并到作品资料库，请刷新网页，使用同一份资料草稿与确认入口。'))
        return await call_next(request)
