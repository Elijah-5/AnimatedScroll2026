"""Versioned role preparation and strict, character-local dialogue inputs."""
import copy
from typing import Literal
from pydantic import BaseModel, Field
from . import workspace as ws, consumption as consume, revisions
from .task_runtime import digest

DEFAULT_CONFIG=dict(enabled=True,offTopicThreshold=3,viewpoint='depicted')
PRESETS=['沉稳克制','温和谨慎','爽朗直接','机敏含蓄','自定义']
BOUNDARY='身处画中事件当时；只依已确认且当时可知的资料交谈。不预知未来，不新增生平、关系或历史事件。性格、口吻及即时反应属于演绎，不是史实。'

class Timing(BaseModel):
    clueId:str
    status:Literal['known','after','uncertain']='uncertain'
    access:Literal['explicit','assumed','excluded']='explicit'
    reason:str=Field(default='',max_length=600)
    topic:str=Field(default='',max_length=80)
    question:str=Field(default='',max_length=300)

class Persona(BaseModel):
    characterId:str
    selfReference:str=Field(default='我',max_length=60)
    automatic:bool=False
    viewpoint:Literal['depicted','lifetime']='depicted'
    situation:str=Field(default='画中事件当时，具体年代未确定',max_length=1200)
    temperament:str=Field(default='沉稳克制',max_length=600)
    speechStyle:str=Field(default='自然简短的第一人称中文，使用符合身份的称谓，不作博物馆导览。',max_length=1000)
    addressStyle:str=Field(default='依已确认身份称呼，不编造官职与亲属关系。',max_length=600)
    reactions:str=Field(default='用克制的停顿、语气与即时反应表达，不增加过去经历。',max_length=600)
    historicalBoundary:str=Field(default=BOUNDARY,max_length=1600)
    prompt:str=Field(min_length=1,max_length=12000)
    knowledgeTiming:list[Timing]=Field(default_factory=list,max_length=200)
    profileTiming:dict[str,Literal['known','after','uncertain']]=Field(default_factory=lambda:dict(identity='known',biography='uncertain',summary='uncertain'))

class Suggestion(BaseModel):
    personas:list[Persona]=Field(min_length=1,max_length=100)

def empty(cid):
    return dict(characterId=cid,situation='画中事件当时，具体年代未确定',temperament=PRESETS[0],
                speechStyle='自然简短的第一人称中文，使用符合身份的称谓，不作博物馆导览。',
                addressStyle='依已确认身份称呼，不编造官职与亲属关系。',reactions='只补全语气、停顿和即时反应。',
                historicalBoundary=BOUNDARY,prompt='',knowledgeTiming=[],profileTiming=dict(identity='known',biography='uncertain',summary='uncertain'))

def ensure(w):
    entities=w['entities']
    if 'experience_config:main' not in entities:entities['experience_config:main']=ws.record('experience_config','main',DEFAULT_CONFIG)
    for r in list(entities.values()):
        if r['kind']=='character' and r['state']!='deleted' and r['draft'].get('depictionScope')!='background':
            k='persona:'+r['id']
            if k not in entities:entities[k]=ws.record('persona',r['id'],empty(r['id']))

def phases(p,clue):
    """Only exact linked quotations establish an event's time, never keywords."""
    material=consume.confirmed(p,'material','main');structured=material.get('structured') or {}
    quotes=[ref.get('quote') for u in clue.get('units',[]) for ref in u.get('references',[]) if ref.get('quote')]
    evidence={e['id'] for e in structured.get('evidence',[]) if e.get('quote') in quotes}
    return {e.get('phase') for e in structured.get('events',[]) if evidence.intersection(e.get('referenceIds',[]))}

def knowledge(p,cid):
    binding=consume.confirmed(p,'knowledge',cid)
    return [(clue_id,consume.bound(p,'knowledge',cid,'clue',clue_id)) for clue_id in binding.get('clueIds',[])]

def accessible(row,role):
    return row.get('access')!='excluded' and (row['status']=='known' or role.get('automatic') and row['status']=='uncertain' and row.get('access')=='assumed')

def validate(p,w,r):
    if r['kind']=='experience_config':
        value=r['draft'];n=value.get('offTopicThreshold')
        if type(value.get('enabled')) is not bool or type(n) is not int or not 1<=n<=20:raise ValueError('引导开关须为布尔值，偏离轮数须为1–20的整数')
        if value.get('viewpoint','depicted') not in ('depicted','lifetime'):raise ValueError('请选择画中当时或人物生平回忆视角')
        return
    if not isinstance(r['draft'].get('prompt'),str) or not r['draft']['prompt'].strip():raise ValueError('请生成或填写角色提示词')
    try:value=Persona.model_validate(r['draft']).model_dump()
    except ValueError as exc:raise ValueError('角色设定字段格式无效，请核对时间分类、内容长度及引导问题') from exc
    if set(value['profileTiming'])!={'identity','biography','summary'}:raise ValueError('请核对身份、经历及简介的可知时间')
    if value['characterId']!=r['id']:raise ValueError('角色设定必须关联原人物ID')
    if not value['prompt'].strip():raise ValueError('请生成或填写角色提示词')
    person=consume.confirmed(p,'character',r['id'])
    if person.get('depictionScope')=='background':raise ValueError('背景人物不自动开放入画角色')
    clues=dict(knowledge(p,r['id']));rows=value['knowledgeTiming'];ids=[v['clueId'] for v in rows]
    if len(ids)!=len(set(ids)) or set(ids)!=set(clues):raise ValueError('请逐条核对当前已确认知识的可知时间，不得重复或新增线索')
    for row in rows:
        if accessible(row,value):
            if config(p).get('viewpoint','depicted')=='depicted' and '后续' in phases(p,clues[row['clueId']]):raise ValueError('明确属于后续事件的线索不能设为画中当时可知')
            if not row['topic'].strip() or not row['question'].strip():raise ValueError('可知线索须填写引导话题和建议问题')

def ready(p,cid):
    role=consume.confirmed(p,'persona',cid)
    # Resolve the original bindings, rather than silently reinterpreting an old role.
    person=consume.confirmed(p,'character',cid)
    binding=consume.bound(p,'persona',cid,'knowledge',cid)
    ids={v['clueId'] for v in role['knowledgeTiming'] if accessible(v,role)}
    if role['characterId']!=cid or person.get('depictionScope')=='background' or not ids<=set(binding['clueIds']):raise ValueError('角色时间范围或知识绑定无法核对')
    # A deletion is a hard error; ordinary published changes remain a notice.
    frozen=pinned(p,cid)
    for clue_id in ids:consume.bound(frozen,'knowledge',cid,'clue',clue_id)
    return role

def pinned(p,cid):
    w=p['workspace'];frozen=dict(p,workspace=dict(w,entities=dict(w['entities']),revisionArchive={k:dict(v) for k,v in w.get('revisionArchive',{}).items()}))
    for item in revisions.bases(p['workspace'],'persona:'+cid).values():
        record=dict(frozen['workspace']['entities'][item['key']])
        record.update(published=item['data'],revision=item['revision'],refs=item['refs'])
        frozen['workspace']['entities'][item['key']]=record
    return frozen

def candidates(p,target=''):
    result=[]
    for r in ws.ensure(p)['entities'].values():
        if r['kind']!='character' or not ws.valid(r) or (target and r['id']!=target) or r['published'].get('depictionScope')=='background':continue
        existing=p['workspace']['entities'].get('persona:'+r['id'])
        if not target and existing and (existing.get('published') or existing.get('draft',{}).get('prompt')):continue
        try:consume.confirmed(p,'material','main');knowledge(p,r['id'])
        except ValueError:continue
        result.append(r['id'])
    return sorted(result)

def generation_context(p,target=''):
    from .experience import dialogue_context
    roles=[]
    for cid in candidates(p,target):
        context=dialogue_context(p,cid)
        for clue in context['clues']:clue['phases']=sorted(phases(p,dict(knowledge(p,cid))[clue['id']]))
        roles.append(dict(characterId=cid,**context))
    return dict(roles=roles,presets=PRESETS,boundary=BOUNDARY)

def apply(p,output,context):
    values=Suggestion.model_validate(output).model_dump()['personas']
    allowed={v['characterId'] for v in context['roles']}
    if len(values)!=len(allowed) or {v['characterId'] for v in values}!=allowed:raise ValueError('角色候选必须与本次所选人物逐一对应')
    for value in values:
        cid=value['characterId'];record=p['workspace']['entities']['persona:'+cid]
        proposed=dict(record,draft=value)
        # Uncertain-only proposals are editable drafts; all IDs and explicit future
        # assertions must still be checked before accepting any model output.
        permitted={v['id'] for ctx in context['roles'] if ctx['characterId']==cid for v in ctx['clues']}
        ids=[v['clueId'] for v in value['knowledgeTiming']]
        if len(ids)!=len(set(ids)) or set(ids)!=permitted:raise ValueError('角色候选知识编号无效')
        for row in value['knowledgeTiming']:
            if config(p).get('viewpoint','depicted')=='depicted' and row['status']=='known' and '后续' in phases(p,dict(knowledge(p,cid))[row['clueId']]):raise ValueError('角色候选错误地预知后续事件')
        refs=ws.refs_for(p['workspace'],proposed)
        if record['draft'].get('prompt') or record.get('published'):
            record.update(suggestion=value,suggestionRefs=refs)
        else:record.update(draft=value,draftRefs=refs,generationRefs=copy.deepcopy(refs),regenerated=True)

def edit_timing(w,record,data):
    rows=record['draft'].get('knowledgeTiming',[]);incoming=data.get('knowledgeTiming',[])
    if not isinstance(rows,list) or not isinstance(incoming,list) or not all(isinstance(v,dict) and isinstance(v.get('clueId'),str) for v in rows+incoming):return
    old={v['clueId'] for v in rows};new={v['clueId'] for v in incoming}
    if old!=new:record['draftRefs']=ws.refs_for(w,dict(record,draft=data))

def context(p,cid,collected):
    """Construct an allowlist of exact published spans before calling a model."""
    from .experience import dialogue_context
    role=ready(p,cid);w=p['workspace'];r=w['entities']['persona:'+cid]
    # Role revision pins the profile and knowledge; do not mix current evidence
    # into a role generated against older confirmed content.
    frozen=pinned(p,cid)
    result=dialogue_context(frozen,cid)
    known={v['clueId'] for v in role['knowledgeTiming'] if accessible(v,role)}
    result['clues']=[c for c in result['clues'] if c['id'] in known]
    basis=[]
    def add(text,category,evidence,clue_id='',origin='confirmed_profile'):
        if not text or not text.strip():return
        key='b-'+digest([cid,text,category,evidence,clue_id,origin])[:24]
        if not any(v['id']==key for v in basis):basis.append(dict(id=key,text=text,category=category,evidence=evidence,clueId=clue_id,origin=origin))
    known_fields={'name'}|{k for k,v in role.get('profileTiming',{}).items() if v=='known'}
    result['character']={k:v for k,v in result['character'].items() if k in known_fields}
    basis=[]
    for field,text in result['character'].items():add(text,'fiction',[],origin='profile:'+field)
    facts=result['characterFacts'];evidence={e['id']:e for e in facts['evidence']}
    for row in facts['statements']:
        if row.get('profileField') not in known_fields:continue
        refs=[evidence[k] for k in row.get('referenceIds',[]) if k in evidence]
        add(row['text'],row.get('category','uncertain'),refs,origin='character_statement')
        for ref in refs:add(ref['quote'],row.get('category','uncertain'),[ref],origin=ref.get('level','source'))
    for clue in result['clues']:
        for unit in clue['units']:
            add(unit['text'],unit.get('category','fiction'),clue['evidence'],clue['id'],'clue_unit')
        for ref in clue['evidence']:add(ref['quote'],ref.get('category','fiction'),[ref],clue['id'],'clue_source')
    safe_role=copy.deepcopy(role);safe_role['knowledgeTiming']=[v for v in safe_role['knowledgeTiming'] if accessible(v,role)]
    viewpoint=config(p).get('viewpoint','depicted')
    boundary=BOUNDARY if viewpoint=='depicted' else '以本人一生的回忆视角交谈，不知身后之事；不新增生平、关系或历史事件。性格与即时反应为演绎。'
    return dict(character=result['character'],persona=safe_role,basis=basis,clues=[{k:c[k] for k in ('id','name')} for c in result['clues']],
                unrecordedClueIds=sorted(known-set(collected)),historicalBoundary=boundary,timePolicy=viewpoint)

class Segment(BaseModel):
    text:str=Field(min_length=1,max_length=2000)
    basisIds:list[str]=Field(default_factory=list,max_length=30)
    clueIds:list[str]=Field(default_factory=list,max_length=10)

class Reply(BaseModel):
    segments:list[Segment]=Field(min_length=1,max_length=8)
    disposition:Literal['grounded','smalltalk','unknown']='grounded'

def verify_reply(result,ctx):
    value=Reply.model_validate(result).model_dump();basis={b['id']:b for b in ctx['basis']};allowed={c['id'] for c in ctx['clues']};segments=[];ids=[]
    for row in value['segments']:
        if not row['text'].strip():raise ValueError('回答段落不能为空')
        if not set(row['basisIds'])<=basis.keys() or not set(row['clueIds'])<=allowed:raise ValueError('回答引用了角色范围外的依据或线索')
        refs=[basis[k] for k in dict.fromkeys(row['basisIds'])]
        if not set(row['clueIds'])<={b['clueId'] for b in refs if b['clueId']}:raise ValueError('线索编号必须有该线索的实际段落依据')
        exact=[b for b in refs if row['text']==b['text']]
        category='fiction'
        if exact and all(b['category']=='supported' for b in exact):category='supported'
        elif exact and all(b['category'] in ('supported','inference') for b in exact) and any(b['category']=='inference' for b in exact):category='inference'
        if value['disposition'] in ('smalltalk','unknown'):
            if row['clueIds'] or row['basisIds']:raise ValueError('问候或不知情回答不能夹带事实、依据或线索')
            category='fiction'
        if value['disposition']=='grounded' and not refs:raise ValueError('涉及资料的回答须提供本角色依据；问候或未知问题请标明类型')
        segments.append(dict(**row,category=category,evidence=[dict(basisId=b['id'],text=b['text'],origin=b['origin'],sources=b['evidence']) for b in refs],verification='exact' if exact else 'performance',kind=value['disposition']))
        ids.extend(row['clueIds'])
    return dict(dialogueVersion=2,segments=segments,answer='\n\n'.join(v['text'] for v in segments),basis=value['disposition'],clueIds=list(dict.fromkeys(ids)))

def config(p):
    try:return consume.confirmed(p,'experience_config','main')
    except ValueError:return copy.deepcopy(DEFAULT_CONFIG)
