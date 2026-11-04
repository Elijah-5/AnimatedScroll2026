"""Versioned seven-page authoring workspace. Draft saves never invalidate dependents."""
import copy
import hashlib
import json
from .domain import uid, citation_errors

ROOTS={'culture':'文化背景','relationship':'人物关系','narrative':'叙事线索'}
PAGES={'material':'library','character':'characters','intent':'outline','plot':'outline','clue':'clues','knowledge':'characters','persona':'characters','experience_config':'outline','storyboard':'storyboards'}

def key(kind,id):return kind+':'+id

def content(value):return {k:copy.deepcopy(v) for k,v in value.items() if k not in ('confirmed','status','locked')}

def record(kind,id,draft,published=False,refs=None):
    return dict(id=id,kind=kind,draft=copy.deepcopy(draft),published=copy.deepcopy(draft) if published else None,revision=1 if published else 0,state='confirmed' if published else 'draft',refs=refs or [],history=[])

def data_material(p):
    result={k:copy.deepcopy(p.get(k,{} if k=='materialInputs' else [] if k in ('sources','annotations','observations','matches') else '')) for k in ('image','imageVersion','materialInputs','sources','annotations','observations','matches')}
    for k in ('materialInputOrigins','targetArtwork','paintingInfo','historicalEvents','historySnapshot','structured','literatureInput'):
        if k in p:result[k]=copy.deepcopy(p[k])
    return result

def intent_data(p):
    i=p['intent']
    return dict(theme=i['theme'],audience=i['audience'],tone=i['tone'],goal=i['goal'],framework=[v for v in i['fixed'].splitlines() if v.strip()],fiction=[v for v in i['allowed'].splitlines() if v.strip()],forbidden=[v for v in i['forbidden'].splitlines() if v.strip()],plotCount=p.get('sceneCount',3))

def build(p):
    w=dict(schemaVersion='2.0',entities={},folders=[dict(id=k,name=v,parentId='',type=k,root=True) for k,v in ROOTS.items()],jobs=[])
    w['entities']['material:main']=record('material','main',data_material(p))
    w['entities']['intent:main']=record('intent','main',intent_data(p),p.get('outlineConfirmed',False))
    for c in p['characters']:
        w['entities'][key('character',c['id'])]=record('character',c['id'],content(c),c.get('confirmed',False))
        w['entities'][key('knowledge',c['id'])]=record('knowledge',c['id'],dict(characterId=c['id'],clueIds=[],reasons={},legacyText=c.get('knowledge','')))
    for s in p['scenes']:
        plot=content(s);plot.pop('units',None);plot.setdefault('body',s.get('goal',''));plot['clueIds']=[];plot['region']=None
        if s.get('units'):
            cid='legacy-'+s['id'];plot['clueIds']=[cid]
            clue=dict(name=s['title'],type='narrative',parentId='narrative',summary=s['goal'],plotIds=[s['id']],characterIds=s.get('characterIds',[]),units=copy.deepcopy(s['units']))
            w['entities'][key('clue',cid)]=record('clue',cid,clue,all(u.get('status')=='approved' for u in s['units']))
        w['entities'][key('plot',s['id'])]=record('plot',s['id'],plot,p.get('outlineConfirmed',False))
    for r in w['entities'].values():r['refs']=refs_for(w,r)
    return w

def ensure(p):
    if 'workspace' not in p:p['workspace']=build(p)
    from .persona import ensure as ensure_personas
    ensure_personas(p['workspace'])
    from .revisions import upgrade
    upgrade(p)
    return p['workspace']

def clean_equal(a,b):return a==b

def dirty(r):return r['published'] is None or not clean_equal(r['draft'],r['published'])

def valid(r):return r is not None and r['published'] is not None and r['state']!='deleted' and not r.get('basisError')

def narrative_text(d):
    if isinstance(d.get('content'),str):return d['content']
    return '\n'.join(u.get('text','') for u in d.get('units',[])) or d.get('summary','')

def narrative_draft(d,old=None):
    """A paragraph editor over the existing audit-compatible unit storage."""
    d=copy.deepcopy(d)
    if d.get('type')!='narrative':return d
    if len(d.get('plotIds',[]))>1:raise ValueError('叙事线索只能属于一个剧情，请选择唯一所属剧情')
    if 'content' in d and not isinstance(d['content'],str):raise ValueError('叙事情节必须是文本')
    if 'content' in d and (old is None or d['content']!=narrative_text(old)):
        if old and any(u.get('locked') for u in old.get('units',[])):raise ValueError('叙事情节已锁定，请先解锁并保存')
        if old and old.get('units') and not d.get('legacyUnits'):d['legacyUnits']=copy.deepcopy(old['units'])
        d['units']=[dict(id=uid(),text=d['content'],kind='event',category='fiction',speakerId='',rationale='剧情情节的创作表述，不作为史料原文',references=[],status='pending',locked=False)]
        d['summary']=d['content']
    return d

def ingest(old,p):
    """Legacy image/file/analysis endpoints edit workspace drafts only."""
    if 'workspace' not in old:return
    # Shared visual notes live in the material draft. Root-level geometry/file
    # edits must not replace them with the older legacy material projection.
    visual_groups=copy.deepcopy(p.get('workspace',{}).get('entities',{}).get('material:main',{}).get('draft',{}).get('visualGroups'))
    w=copy.deepcopy(old['workspace']);p['workspace']=w
    if data_material(old)!=data_material(p):w['entities']['material:main']['draft']=data_material(p)
    if visual_groups is not None:w['entities']['material:main']['draft']['visualGroups']=visual_groups
    def comparable(c):
        body=content(c)
        for k,v in dict(roleType='unknown',depictionScope='unknown',visualHints=[]).items():body.setdefault(k,v)
        return body
    old_chars={c['id']:comparable(c) for c in old['characters']}
    for c in p['characters']:
        k=key('character',c['id']);body=content(c)
        if k not in w['entities']:w['entities'][k]=record('character',c['id'],body)
        elif old_chars.get(c['id'])!=comparable(c):w['entities'][k]['draft']=body
        kk=key('knowledge',c['id'])
        if kk not in w['entities']:w['entities'][kk]=record('knowledge',c['id'],dict(characterId=c['id'],clueIds=[],reasons={}))

def mirror(p):
    w=ensure(p)
    for field in ('paintingInfo','historicalEvents','historySnapshot','structured','literatureInput'):
        if field in w['entities']['material:main']['draft']:p[field]=copy.deepcopy(w['entities']['material:main']['draft'][field])
    p['characters']=[dict(r['draft'],id=r['id'],confirmed=valid(r) and not dirty(r)) for r in w['entities'].values() if r['kind']=='character' and r['state']!='deleted']
    return p

def named(r):return r['draft'].get('name') or r['draft'].get('title') or {'material':'古画资料','intent':'创作设置','knowledge':'人物知识','persona':'入画角色设定','experience_config':'体验引导设置','storyboard':'分镜'}.get(r['kind'],r['id'])

def find(w,kind,id):
    r=w['entities'].get(key(kind,id))
    if not r or r['state']=='deleted':raise ValueError('条目不存在')
    return r

def refs_for(w,r):
    d=r['draft'];kind=r['kind'];targets=[]
    if kind=='character':targets=['material:main'] if d.get('namingOrigin')!='creator' else []
    if kind=='intent':targets=['material:main']
    if kind=='plot':targets=['intent:main','material:main']+[key('character',cid) for cid in d.get('characterIds',[])]
    if kind=='clue':
        targets=['material:main']+[key('character',cid) for cid in d.get('characterIds',[])]
        targets += [key('character',u['speakerId']) for u in d.get('units',[]) if u.get('speakerId')]
        if d['type']=='narrative':targets += [key('plot',pid) for pid in d.get('plotIds',[])]
    if kind=='knowledge':targets=[key('character',r['id'])]+[key('clue',cid) for cid in d.get('clueIds',[])]
    if kind=='persona':targets=['material:main',key('character',r['id']),key('knowledge',r['id'])]
    if kind=='storyboard':targets=[key('clue',d['clueId'])]+[k for cid in d.get('characterIds',[]) for k in (key('character',cid),key('knowledge',cid))]
    return [dict(key=k,revision=w['entities'][k]['revision']) for k in dict.fromkeys(targets) if k in w['entities']]

def impact(w,target):
    affected={};queue=[target]
    while queue:
        upstream=queue.pop(0)
        for k,r in w['entities'].items():
            if k==target or k in affected or r['state']=='deleted':continue
            dependent=any(ref['key']==upstream for ref in r.get('refs',[])+r.get('suggestionRefs',[]))
            # Plot->clue generation is directional; reverse shared references are review-only.
            reverse=w['entities'].get(upstream,{}).get('kind')=='clue' and r['kind']=='plot' and upstream.split(':',1)[1] in r['draft'].get('clueIds',[])
            if dependent or reverse:
                mode='review' if reverse else 'stale'
                affected[k]=dict(key=k,name=named(r),kind=r['kind'],page=PAGES.get(r['kind'],'library'),mode=mode)
                if mode=='stale':queue.append(k)
    return list(affected.values())

def validate_entity(p,w,r):
    d=r['draft'];kind=r['kind'];issues=[]
    try:
        if kind in ('persona','experience_config'):
            from .persona import validate
            validate(p,w,r)
        from . import catalog
        if kind=='material':catalog.validate_material(d)
        if kind=='material' and d.get('structured'):
            from .structured import validate
            validate(d['structured'])
        if kind=='clue' and d.get('type')=='relationship':catalog.validate_relations(d,w)
    except (ValueError,TypeError,KeyError) as exc:issues.append(str(exc))
    if kind=='material' and (not d.get('image') or not any(d.get('materialInputs',{}).get(k,'').strip() for k in ('background','relationships','narrative'))):issues.append('需要古画图片和至少一段资料')
    if kind=='character' and not d.get('name','').strip():issues.append('请填写人物姓名或称谓')
    if kind=='intent':
        if not d.get('theme','').strip() or not d.get('goal','').strip():issues.append('请填写主题与故事目标')
        if not 1<=int(d.get('plotCount',3))<=12:issues.append('剧情数应为1–12')
    if kind=='plot':
        if not d.get('title','').strip():issues.append('剧情缺少标题')
        if not (d.get('body','').strip() or d.get('goal','').strip()):issues.append('请填写剧情目标或具体内容')
        if not d.get('clueIds'):issues.append('每个剧情至少需要一条叙事线索')
        for cid in d.get('clueIds',[]):
            c=w['entities'].get(key('clue',cid))
            if not c or c['state']=='deleted' or c['draft']['type']!='narrative':issues.append('剧情关联了无效叙事线索')
            elif c['draft'].get('plotIds')!=[r['id']]:issues.append('叙事线索只能归属于当前剧情，不能跨剧情共享')
    if kind=='clue':
        if not d.get('name','').strip():issues.append('请填写线索名称')
        if d.get('type') not in ROOTS:issues.append('线索分类无效')
        if d.get('type')=='narrative':
            if len(d.get('plotIds',[]))!=1:issues.append('叙事线索必须且只能属于一个剧情')
            if not narrative_text(d).strip():issues.append('请填写一小段情节')
        if not d.get('units'):issues.append('线索至少包含一个内容单元')
        for u in d.get('units',[]):
            from .agent import Unit
            try:Unit.model_validate(u)
            except ValueError:issues.append('线索单元类型或字段无效')
            if not str(u.get('text','')).strip():issues.append('线索内容不能为空')
            if u.get('speakerId') and ('character:'+u['speakerId'] not in w['entities'] or w['entities']['character:'+u['speakerId']]['state']=='deleted'):issues.append('说话人物不存在')
        from .revisions import citation_issues
        try:issues.extend(citation_issues(w,key(kind,r['id']),d,editing=dirty(r)))
        except (ValueError,KeyError,TypeError) as exc:issues.append(str(exc))
    if kind=='knowledge':
        if not valid(w['entities'].get(key('character',r['id']))):issues.append('人物资料尚未确认、已删除或不存在')
        if not d.get('profileOnly') and not any(c['kind']=='clue' and valid(c) for c in w['entities'].values()):issues.append('尚无已确认线索，请先确认线索后再配置人物知识')
        for cid in d.get('clueIds',[]):
            if not valid(w['entities'].get(key('clue',cid))):issues.append('知识绑定包含未确认或失效线索')
    if kind=='storyboard':
        if not valid(w['entities'].get(key('clue',d['clueId']))):issues.append('对应线索尚未确认或已失效')
        if not d.get('region'):issues.append('请选择分镜画作区域')
        if not d.get('participantsConfirmed'):issues.append('请确认参与人物（可明确选择无人出镜）')
        if not all(d.get(k,'').strip() for k in ('prompt','startFrame','endFrame')):issues.append('分镜提示词及首尾画面尚未完备')
        if d.get('promptConfigHash')!=config_hash(d):issues.append('分镜设置已变化，请重新生成提示词')
    for cid in d.get('characterIds',[]):
        if not w['entities'].get('character:'+cid) or w['entities']['character:'+cid]['state']=='deleted':issues.append('人物引用不存在')
    for pid in d.get('plotIds',[]):
        if not w['entities'].get('plot:'+pid) or w['entities']['plot:'+pid]['state']=='deleted':issues.append('剧情引用不存在')
    if kind!='material':
        for ref in refs_for(w,r):
            if not valid(w['entities'][ref['key']]):issues.append('上游尚未确认或已失效：'+named(w['entities'][ref['key']]))
    return list(dict.fromkeys(issues))

def config_hash(d):return hashlib.sha256(json.dumps({k:d.get(k) for k in ('clueId','characterIds','region','participantsConfirmed','style')},sort_keys=True).encode()).hexdigest()

def preview(w,r):
    changes=[]
    old=r['published'] or {}
    for k in set(old)|set(r['draft']):
        if old.get(k)!=r['draft'].get(k):changes.append(dict(field=k,before=old.get(k),after=r['draft'].get(k)))
    semantic=[c for c in changes if c['field']!='parentId']
    if r.get('linkReviewOnly') and all(c['field']=='clueIds' for c in semantic):semantic=[]
    affected=impact(w,key(r['kind'],r['id'])) if r['published'] is not None and semantic else []
    return dict(changes=changes,affected=affected,requiresRisk=False,revision=r['revision'])

def commit(p,w,r,accept_risk=False):
    if r['kind']=='material' and r['draft'].get('structured'):
        from .structured import finish
        finish(r['draft']['structured'])
    issues=validate_entity(p,w,r)
    if issues:raise ValueError('；'.join(issues))
    plan=preview(w,r)
    # Reconfirmation after a shared clue review does not re-generate clues.
    changed=dirty(r)
    if changed:
        from .revisions import archive
        previous_materials=[]
        if r['kind']=='clue' and r.get('published') is not None:
            from .revisions import bases
            previous_materials=[v for v in bases(w,key(r['kind'],r['id'])).values() if v['key']=='material:main']
        archive(w,key(r['kind'],r['id']),r)
        if r['published'] is not None:r['history'].append(dict(revision=r['revision'],data=copy.deepcopy(r['published']),refs=copy.deepcopy(r.get('refs',[]))))
        r['revision']+=1;r['published']=copy.deepcopy(r['draft'])
        generated=r.pop('draftRefs',None)
        if generated is not None and (r['kind']!='persona' or not r.get('generationRefs')):r['generationRefs']=copy.deepcopy(generated)
        r['refs']=copy.deepcopy(generated or refs_for(w,r));r.pop('reviewedRefs',None)
        # A co-generated plot and its children have revision 0 until the author
        # confirms them. Keep that origin, then bind the first confirmed parent.
        for ref in r['refs']:
            if ref['revision']==0:ref['revision']=w['entities'].get(ref['key'],{}).get('revision',0)
        for material in previous_materials:
            from .structured import material_sources
            if any(s['id']==ref.get('sourceId') and s['version']==ref.get('sourceVersion') for s in material_sources(material['data']) for u in r['draft'].get('units',[]) for ref in u.get('references',[])):
                oldref=dict(key='material:main',revision=material['revision'])
                if oldref not in r['refs']:r['refs'].append(oldref)
    else:
        from .revisions import acknowledge
        acknowledge(w,r)
    r['state']='confirmed';r['regenerated']=False;r.pop('basisError',None)
    if not w.get('_autoEnabling'):r['activation']=dict(method='human',revision=r['revision'])
    from .revisions import archive
    archive(w,key(r['kind'],r['id']),r)
    if r['kind']=='plot':
        r.pop('linkReviewOnly',None)
        if changed:r['linkedBasisRefs']={key('clue',cid):w['entities'][key('clue',cid)]['revision'] for cid in r['draft']['clueIds']}
        for cid in r['draft']['clueIds']:
            c=find(w,'clue',cid)
            # Ownership is validated before confirmation; never silently share a clue.
            c['draft']['plotIds']=[r['id']]
    if r['kind']=='clue':
        ensure_shot(w,r)
        cid=r['id']
        for plot in w['entities'].values():
            if plot['kind']!='plot' or plot['state']=='deleted':continue
            linked=cid in plot['draft'].get('clueIds',[]);wanted=plot['id'] in r['draft'].get('plotIds',[]) and r['draft']['type']=='narrative'
            if linked and plot['published'] is not None and not plot.setdefault('linkedBasisRefs',{}).get(key('clue',cid)):
                plot['linkedBasisRefs'][key('clue',cid)]=r['revision']
            if linked!=wanted:
                if wanted:plot['draft'].setdefault('clueIds',[]).append(cid)
                else:plot['draft']['clueIds'].remove(cid)
                if plot['published'] is not None:plot['linkReviewOnly']=True
    if r['kind'] in ('knowledge','persona'):r.pop('suggestion',None);r.pop('suggestionRefs',None)
    return plan

class Risk(Exception):
    def __init__(self,plan):self.plan=plan

def ensure_shot(w,clue):
    cid=clue['id'];k=key('storyboard',cid)
    if k not in w['entities']:
        w['entities'][k]=record('storyboard',cid,dict(clueId=cid,name=clue['draft']['name'],characterIds=clue['draft'].get('characterIds',[]),participantsConfirmed=False,region=None,prompt='',startFrame='',endFrame='',action='',camera='',style='保留古画笔触与构图，动作克制',promptConfigHash=''))
        w['entities'][k]['refs']=refs_for(w,w['entities'][k])

def checklist(p):
    w=ensure(p);rows=[];notices=[]
    def add(page,name,state,target='',reason='',kind='entity',item_id='',job_id='',dependency=None,action=None):
        rows.append(dict(id=item_id or target or 'missing:'+page+':'+name,page=page,name=name,state=state,target=target,reason=reason,kind=kind,jobId=job_id,dependency=dependency,action=action))
    for kind in ('material','character','intent','plot','clue','knowledge','persona','experience_config','storyboard'):
        entities=[r for r in w['entities'].values() if r['kind']==kind and r['state']!='deleted']
        if not entities:add(PAGES[kind],dict(character='人物资料',plot='剧情',clue='线索',knowledge='人物知识',storyboard='分镜').get(kind,kind),'missing')
        for r in entities:
            state='changed' if r['published'] is not None and dirty(r) else r['state']
            issues=validate_entity(p,w,r)
            from .revisions import warnings,resolve
            if valid(r):
                try:resolve(w,key(r['kind'],r['id']))
                except ValueError as exc:issues.append(str(exc))
            for warning in warnings(w,r):
                notices.append(dict(warning,entity=key(r['kind'],r['id']),entityName=named(r),page=PAGES[kind]))
            if state=='confirmed' and issues:state='incomplete'
            name=named(r);dependency=None
            if kind=='persona':
                person=w['entities'].get(key('character',r['id']))
                name=(named(person) if person else r['id'])+'的入画角色设定'
                if not r['draft'].get('prompt') and r['published'] is None:state='waiting'
            if kind=='knowledge':
                person=w['entities'].get(key('character',r['id']))
                name=(named(person) if person else '未命名人物')+'的知识库'
                # Initial empty knowledge is not actionable until its inputs exist.
                # Keep genuinely stale or edited knowledge visible as an issue.
                if r['published'] is None and r['state']=='draft' and not r['draft'].get('clueIds') and not r.get('suggestion'):
                    if not valid(person):
                        state='waiting';issues=['等待人物资料确认后配置人物知识']
                        dependency=dict(page='characters',target=key('character',r['id']),name='人物资料')
                    elif not any(c['kind']=='clue' and valid(c) for c in w['entities'].values()):
                        state='waiting';issues=['人物资料已确认；等待线索确认后配置人物知识']
                        dependency=dict(page='clues',target='',name='线索库')
            if kind=='storyboard':
                clue=w['entities'].get(key('clue',r['draft'].get('clueId','')))
                name=(named(clue) if clue else name)+'分镜'
            action=dict(task='plot_clues',target=r['id'],label='一键生成子叙事线索') if kind=='plot' else None
            add(PAGES[kind],name,state,key(kind,r['id']),'；'.join(issues),dependency=dependency,action=action)
    for j in w['jobs']:
        if j['state'] in ('queued','running','failed','interrupted','stale') and not j.get('dismissed'):
            task=j.get('task');target=j.get('target','')
            location={'culture':'material:main','plots':'intent:main','plot_clues':'plot:'+target,'relationship':'character:'+target,'storyboard':'storyboard:'+target,'plot':'plot:'+target,'clue':'clue:'+target}.get(task,'')
            if j.get('family')=='analysis':location='material:main'
            add(j.get('page','checks'),j['label'],j['state'],location,reason=j.get('error','') or j.get('progress',''),kind='job',item_id='job:'+j['id'],job_id=j['id'])
    for check in w.get('consistencyChecks',[]):
        if not check.get('resolved'):add('checks','一致性建议','review',reason=check['message'],kind='suggestion',item_id='suggestion:'+check['id'])
    production=[r for r in rows if r['kind']!='suggestion' and not r['target'].startswith(('persona:','experience_config:'))]
    result=dict(ready=bool(production) and all(r['state']=='confirmed' for r in production),items=rows,versionWarnings=notices,videoGenerated=False)
    return result


def check_locked(r,new):
    if r['kind']!='clue':return
    after={u.get('id'):u for u in new.get('units',[])}
    for old in r['draft'].get('units',[]):
        if not old.get('locked'):continue
        other=after.get(old.get('id'))
        if not other or any(old.get(k)!=other.get(k) for k in ('text','kind','category','speakerId','rationale','references')):raise ValueError('请先单独解锁并保存，再编辑或删除锁定内容')

def track_manual(r,new):
    changes={k for k in set(r['draft'])|set(new) if r['draft'].get(k)!=new.get(k)}
    if changes:r['manualFields']=sorted(set(r.get('manualFields',[]))|changes)

def merge_locked(old,new):
    texts={u['text'] for u in old if u.get('locked')};fresh=[dict(u,id=uid(),status='pending',locked=False) for u in new if u['text'] not in texts];result=[]
    for u in old:
        if u.get('locked'):result.append(copy.deepcopy(u))
        elif fresh:result.append(fresh.pop(0))
    return result+fresh
