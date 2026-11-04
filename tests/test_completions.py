import asyncio,copy,json,time,threading
import pytest
from backend import main,completions,studio_agent,authoring_defaults,persona,experience,workspace as ws,live_budget
from test_merged_features import ready,merged_client
from test_studio import draft,setup


def unit(text='默认创作过渡'):
    return dict(text=text,kind='action',category='fiction',speakerId='',rationale='明确的创作默认',references=[])

async def defaults(ctx):return dict(theme='殿前相遇',goal='理解画中人物',brief='以画中人物的视角讲述画面故事',audience='普通观众',tone='自然',framework=[],fiction=['允许即时反应'],forbidden=['不新增史实'],plotCount=1)

async def provider(task,ctx):
    if task in ('culture','relationship'):return dict(clues=[dict(name='默认'+task,summary='创作过渡',characterIds=[c['id'] for c in ctx['characters']][:1],units=[unit()])])
    if task=='plots':return dict(plots=[dict(title='眼前之事',goal='与画中人相遇',body='画面中的人物自然交谈。',connection='',characterIds=[c['id'] for c in ctx['characters']][:1],clues=[dict(name='一段相遇',content='人物相互行礼。')])])
    if task=='knowledge':return dict(assignments=[dict(characterId=c['id'],clueIds=[v['id'] for v in ctx['clues'] if v['id']!='not-known'][:1],reason='AI默认，按身份推定知晓') for c in ctx['characters']])
    if task=='persona':
        values=[]
        for role in ctx['roles']:
            value=persona.empty(role['characterId']);value.update(prompt='我身处此时，依自己的身份自然交谈，不知未来。',selfReference='朕' if '太宗' in role['character']['name'] else '我',temperament='爽朗直接',knowledgeTiming=[dict(clueId=c['id'],status='uncertain',reason='年份未确定',topic='眼前之事',question='此处有什么见闻？') for c in role['clues']]);values.append(value)
        return dict(personas=values)
    if task=='storyboard':return dict(prompt='保持原画构图，人物轻轻抬袖。',startFrame='人物静立',endFrame='恢复静立',action='抬袖',camera='固定',style='古画')
    raise ValueError(task)

@pytest.fixture
def automatic(merged_client,monkeypatch):
    monkeypatch.setattr(studio_agent,'run',provider);monkeypatch.setattr(authoring_defaults,'intent',defaults)
    return merged_client


def start(c,p,page='characters',rid='complete'):
    r=c.post(f"/api/projects/{p['id']}/studio/completions",json=dict(version=p['version'],requestId=rid,page=page));assert r.status_code==200,r.text
    return r.json()

def wait(c,p,j):
    for _ in range(400):
        value=c.get(f"/api/projects/{p['id']}/studio/completions/{j['id']}").json()
        if value['state'] not in ('queued','running'):return c.get(f"/api/projects/{p['id']}/studio").json(),value
        time.sleep(.01)
    raise AssertionError('completion not finished')


def test_legacy_uncertain_persona_becomes_usable_in_one_action(automatic):
    c=automatic;p,cid=ready(c);r=p['workspace']['entities']['persona:'+cid]
    r.update(published=None,state='draft',revision=0);r['draft'].update(knowledgeTiming=[dict(clueId='c',status='uncertain',reason='未注明年份',topic='',question='')]);manual=r['draft']['prompt'];p=main.save(p,p['version'],'studio:fixture')
    j=start(c,p);p,j=wait(c,p,j);assert j['state']=='completed',j
    r=p['workspace']['entities']['persona:'+cid]
    assert r['published']['prompt']==manual and r['activation']['method']=='auto'
    assert experience.available_people(p) and persona.context(p,cid,[])['unrecordedClueIds']==['c']
    assert j['capabilities']['chatCharacters']>=1
    s=c.post(f"/api/projects/{p['id']}/experience/sessions");assert s.status_code==200,s.text


def test_completed_stages_skip_models_on_repeated_page_and_request_ids(automatic,monkeypatch):
    c=automatic;p,cid=ready(c);calls=[]
    async def model(task,ctx):calls.append(task);return await provider(task,ctx)
    monkeypatch.setattr(studio_agent,'run',model)
    before=p['version'];j=start(c,p);p,j=wait(c,p,j);count=len(calls)
    replay=c.post(f"/api/projects/{p['id']}/studio/completions",json=dict(version=before,requestId='complete',page='characters'));assert replay.status_code==200,replay.text
    assert replay.json()['id']==j['id']
    j2=start(c,p,rid='second');p,j2=wait(c,p,j2);assert j2['state']=='completed',j2
    assert len(calls)==count


def test_all_pages_auto_defaults_and_no_video_calls(automatic):
    c=automatic;p,cid=ready(c);j=start(c,p,'all');p,j=wait(c,p,j);assert j['state']=='completed',j
    assert j['capabilities']['storyboards']>=1
    assert all(v['state']=='completed' for v in j['steps'])
    bundle=c.get(f"/api/projects/{p['id']}/narrative/inspect").json();assert bundle['schemaVersion']=='3.4' and bundle['activationInfo']
    assert c.get(f"/api/projects/{p['id']}/videos").json()['jobs']==[]


def test_page_failure_resumes_without_repeating_finished_stages(automatic,monkeypatch):
    c=automatic;p,cid=ready(c);calls=[]
    async def fail(task,ctx):
        calls.append(task)
        if task=='culture':raise ValueError('模拟中断')
        return await provider(task,ctx)
    for row in p['workspace']['entities'].values():
        if row['kind']=='clue' and row['draft']['type']=='culture':row['state']='deleted'
    p=main.save(p,p['version'],'studio:fixture')
    monkeypatch.setattr(studio_agent,'run',fail);j=start(c,p);p,j=wait(c,p,j);assert j['state']=='failed'
    assert [s['state'] for s in j['steps'][:4]]==['completed']*4
    monkeypatch.setattr(studio_agent,'run',provider)
    body=dict(version=p['version'],requestId='resume');r=c.post(f"/api/projects/{p['id']}/studio/completions/{j['id']}/continue",json=body);assert r.status_code==200,r.text
    p,j=wait(c,p,j);assert j['state']=='completed',j
    assert c.post(f"/api/projects/{p['id']}/studio/completions/{j['id']}/continue",json=body).status_code==200


def test_manual_values_and_prior_human_confirmation_are_not_overwritten(automatic):
    c=automatic;p,cid=ready(c);person=copy.deepcopy(p['workspace']['entities']['character:'+cid]);shot=copy.deepcopy(p['workspace']['entities']['storyboard:c'])
    r=p['workspace']['entities']['persona:'+cid];r.update(published=None,state='draft',revision=0);p=main.save(p,p['version'],'studio:fixture')
    p=draft(c,p,'persona',cid,dict(r['draft'],temperament='我指定的谨慎性格',prompt='我手写的整段人设'))
    j=start(c,p);p,j=wait(c,p,j);assert j['state']=='completed',j
    assert p['workspace']['entities']['persona:'+cid]['published']['prompt']=='我手写的整段人设'
    assert p['workspace']['entities']['persona:'+cid]['published']['temperament']=='我指定的谨慎性格'
    assert p['workspace']['entities']['character:'+cid]['published']==person['published']
    assert p['workspace']['entities']['storyboard:c']['published']==shot['published']


def test_profile_only_role_can_talk_without_any_bound_clue(automatic):
    c=automatic;p,cid=ready(c);k=p['workspace']['entities']['knowledge:'+cid];k['published']=dict(characterId=cid,clueIds=[],reasons={},profileOnly=True);k['draft']=copy.deepcopy(k['published'])
    r=p['workspace']['entities']['persona:'+cid];r['published']['knowledgeTiming']=[];r['draft']=copy.deepcopy(r['published']);r['refs']=ws.refs_for(p['workspace'],r)
    p=main.save(p,p['version'],'studio:fixture');assert experience.available_people(p)
    ctx=persona.context(p,cid,[]);assert ctx['clues']==[] and ctx['basis']


def test_missing_picture_or_sources_are_actionable_not_fake_completion(automatic):
    c=automatic;p=c.post('/api/projects',json=dict(title='空项目')).json();j=start(c,p,'library');p,j=wait(c,p,j)
    assert j['state']=='failed' and '图片' in j['error']


def test_apply_manual_edits_is_one_publish_without_false_human_review(automatic):
    c=automatic;p,cid=ready(c);p=draft(c,p,'character',cid,dict(p['workspace']['entities']['character:'+cid]['draft'],summary='我修改的小传'))
    response=c.post(f"/api/projects/{p['id']}/studio/apply",json=dict(version=p['version'],keys=['character:'+cid]));assert response.status_code==200,response.text
    r=response.json()['workspace']['entities']['character:'+cid];assert r['published']['summary']=='我修改的小传' and r['activation']['method']=='manual'


def test_completion_cancel_is_durable_and_does_not_restart_model(automatic,monkeypatch):
    c=automatic;p,cid=ready(c);started=threading.Event()
    async def slow(task,ctx):
        started.set();await asyncio.sleep(100)
    monkeypatch.setattr(studio_agent,'run',slow);j=start(c,p);assert started.wait(2)
    current=c.get(f"/api/projects/{p['id']}/studio").json()
    r=c.post(f"/api/projects/{p['id']}/studio/completions/{j['id']}/cancel",json=dict(version=current['version'],requestId='cancel'));assert r.status_code==200,r.text
    assert r.json()['state']=='interrupted'


def test_live_budget_reserves_before_network_and_retains_unknown_cost(monkeypatch):
    monkeypatch.setenv('CREATION_LIVE_BUDGET_USD','1')
    ledger=dict(requests=[])
    body=dict(model='qwen3.7-plus',messages=[dict(role='user',content='你好')],max_tokens=1000)
    value=live_budget.reserve(ledger,body);assert value['reservedUsd']>0
    ledger['requests']=[dict(reservedUsd=.9999)]
    with pytest.raises(ValueError,match='预算'):live_budget.reserve(ledger,body)
    with pytest.raises(ValueError):live_budget.reserve(dict(requests=[]),dict(body,model='unknown'))
    with pytest.raises(ValueError):live_budget.reserve(dict(requests=[]),dict(body,tools=[dict(type='web_search')]))

@pytest.mark.parametrize('page',['library','outline','clues','storyboards','experience'])
def test_each_page_finishes_with_existing_prerequisites(automatic,page):
    c=automatic;p,cid=ready(c);j=start(c,p,page);p,j=wait(c,p,j)
    assert j['state']=='completed',j
    assert all(s['state']=='completed' for s in j['steps'])


def test_completion_rejects_version_conflict_and_request_id_repurposing(automatic):
    c=automatic;p,cid=ready(c)
    assert c.post(f"/api/projects/{p['id']}/studio/completions",json=dict(version=p['version']-1,requestId='stale',page='all')).status_code==409
    j=start(c,p);latest,j=wait(c,p,j)
    assert c.post(f"/api/projects/{p['id']}/studio/completions",json=dict(version=p['version'],requestId='complete',page='all')).status_code==409
    other=c.post('/api/projects',json=dict(title='别的画')).json()
    assert c.get(f"/api/projects/{other['id']}/studio/completions/{j['id']}").status_code==404


def test_concurrent_edit_is_preserved_as_old_input_suggestion(automatic,monkeypatch):
    c=automatic;p,cid=ready(c);entered=threading.Event();release=threading.Event()
    role=p['workspace']['entities']['persona:'+cid];role.update(published=None,state='draft',revision=0);p=main.save(p,p['version'],'studio:fixture')
    async def paused(task,ctx):
        if task!='persona':return await provider(task,ctx)
        entered.set()
        while not release.is_set():await asyncio.sleep(.01)
        return await provider(task,ctx)
    monkeypatch.setattr(studio_agent,'run',paused)
    j=start(c,p);assert entered.wait(3)
    latest=c.get(f"/api/projects/{p['id']}/studio").json();r=latest['workspace']['entities']['persona:'+cid]
    latest=draft(c,latest,'persona',cid,dict(r['draft'],prompt='运行中手写的完整人设'))
    release.set();latest,j=wait(c,latest,j)
    assert latest['workspace']['entities']['persona:'+cid]['draft']['prompt']=='运行中手写的完整人设'
    assert j['state']=='partial' and latest['workspace'].get('generationSuggestions')


def test_activation_failure_keeps_other_valid_roles_usable(automatic):
    c=automatic;p,cid=ready(c)
    bad=ws.record('character','bad',dict(name='',identity='身份未知',summary='',biography='',relationships='',evidence='',knowledge='',depictionScope='depicted'))
    p['workspace']['entities']['character:bad']=bad;p=main.save(p,p['version'],'studio:fixture')
    j=start(c,p,'library');p,j=wait(c,p,j)
    assert j['state']=='completed' and experience.available_people(p)
    assert any(s.get('notes') for s in j['steps'])
    assert not p['workspace']['entities']['character:bad'].get('published')


def test_stage_failure_rolls_back_its_partial_project_changes(automatic,monkeypatch):
    c=automatic;p,cid=ready(c)
    for row in p['workspace']['entities'].values():
        if row['kind']=='clue' and row['draft']['type']=='culture':row['state']='deleted'
    p=main.save(p,p['version'],'studio:fixture');original=completions.stage_result
    async def fail(snapshot,stage,*args):
        if stage=='culture':
            snapshot['workspace']['entities']['character:'+cid]['draft']['name']='不应保存'
            raise ValueError('事务前失败')
        return await original(snapshot,stage,*args)
    monkeypatch.setattr(completions,'stage_result',fail);j=start(c,p);p,j=wait(c,p,j)
    assert j['state']=='failed' and p['workspace']['entities']['character:'+cid]['draft']['name']!='不应保存'


def test_budget_request_limit_cannot_be_increased_above_sixty(tmp_path,monkeypatch):
    from backend.model_client import update_ledger
    monkeypatch.setenv('CREATION_LIVE_RUN_DIR',str(tmp_path));monkeypatch.setenv('CREATION_LIVE_BUDGET_USD','1');monkeypatch.setenv('CREATION_LIVE_REQUEST_LIMIT','1000')
    assert update_ledger(lambda v:v['limit'])==60


def test_automatic_scope_never_enables_explicit_future_clues(automatic):
    c=automatic;p,cid=ready(c);r=p['workspace']['entities']['persona:'+cid]
    r['published']['automatic']=True;r['published']['knowledgeTiming']=[dict(clueId='c',status='after',access='assumed',reason='明确后续')]
    r['draft']=copy.deepcopy(r['published']);p=main.save(p,p['version'],'studio:fixture')
    assert persona.context(p,cid,[])['clues']==[]


def test_each_storyboard_is_saved_before_a_later_generation_fails(automatic,monkeypatch):
    c=automatic;p,cid=ready(c);calls=[]
    async def model(task,ctx):
        if task=='storyboard':
            calls.append(ctx['storyboard']['clueId'])
            if len(calls)==2:raise ValueError('第二镜头中断')
        return await provider(task,ctx)
    monkeypatch.setattr(studio_agent,'run',model);j=start(c,p,'all');p,j=wait(c,p,j)
    assert j['state']=='failed',j
    first=calls[0];assert p['workspace']['entities']['storyboard:'+first]['published']
    monkeypatch.setattr(studio_agent,'run',provider)
    assert c.post(f"/api/projects/{p['id']}/studio/completions/{j['id']}/continue",json=dict(version=p['version'],requestId='continue-shots')).status_code==200
    p,j=wait(c,p,j);assert j['state']=='completed',j
    assert calls.count(first)==1


def test_completed_model_result_is_cached_if_later_stage_application_fails(automatic,monkeypatch):
    c=automatic;p,cid=ready(c)
    for r in p['workspace']['entities'].values():
        if r['kind']=='clue' and r['draft']['type']=='culture':r['state']='deleted'
    p=main.save(p,p['version'],'studio:fixture');calls=[];original=completions.studio.apply_output
    async def model(task,ctx):calls.append(task);return await provider(task,ctx)
    def fail(*args,**kwargs):
        if args[1]=='culture':raise ValueError('模型成功后应用失败')
        return original(*args,**kwargs)
    monkeypatch.setattr(studio_agent,'run',model);monkeypatch.setattr(completions.studio,'apply_output',fail)
    j=start(c,p);p,j=wait(c,p,j);assert j['state']=='failed'
    monkeypatch.setattr(completions.studio,'apply_output',original)
    c.post(f"/api/projects/{p['id']}/studio/completions/{j['id']}/continue",json=dict(version=p['version'],requestId='cached'))
    p,j=wait(c,p,j);assert j['state']=='completed' and calls.count('culture')==1


def test_enabled_export_does_not_require_another_human_review(automatic):
    c=automatic;p,cid=ready(c)
    response=c.get(f"/api/projects/{p['id']}/narrative/export?format=json&draft=false&version={p['version']}")
    assert response.status_code==200,response.text
    assert response.json()['exportReview']==dict(manualReviewed=False)
    assert response.json()['state']=='enabled'


def test_changed_document_analysis_refreshes_an_existing_structured_library(automatic,monkeypatch):
    c=automatic;p,cid=ready(c);mat=p['workspace']['entities']['material:main'];mat['needsStructuredRefresh']=True;calls=[]
    from backend import structured
    async def refresh(*args,**kwargs):calls.append('refresh');return structured.empty()
    monkeypatch.setattr(structured,'organize',refresh)
    job=dict(id='refresh-fixture',manualFields={})
    result,notes=asyncio.run(completions.stage_result(p,'materials',job,lambda:main.DATA,lambda _:None,lambda *a:None))
    assert calls==['refresh'] and not result['workspace']['entities']['material:main'].get('needsStructuredRefresh')


def test_shot_context_does_not_scan_unrelated_knowledge_histories(automatic,monkeypatch):
    c=automatic;p,cid=ready(c);keys=[]
    from backend import revisions,studio
    original=revisions.materials_for
    def counted(w,key,*args):keys.append(key);return original(w,key,*args)
    monkeypatch.setattr(revisions,'materials_for',counted)
    ctx=studio.context(p,'storyboard','c')
    assert 'clue:c' in keys and 'clue:not-known' not in keys
    assert ctx['clues'][0]['id']=='c' and 'structured' not in ctx['material']
