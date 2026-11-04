"""Role preparation, exact paragraph labels, director state and snapshot isolation."""
import asyncio
import copy
import json
import threading
import time
import io
import zipfile
import pytest
from backend import main,workspace as ws,persona,experience,studio_agent,narrative,dialogue_guidance as guide
from test_merged_features import ready,merged_client,session as legacy_session
from test_studio import draft,confirm
from test_parallel_tasks import finish_studio

def new_session(c,p):
    r=c.post(f"/api/projects/{p['id']}/experience/sessions");assert r.status_code==200,r.text
    value=r.json();assert value['session']['dialogueVersion']==2
    return value,f"/api/projects/{p['id']}/experience/sessions/{value['session']['id']}"

def send(c,base,cid,key='one',text='你好'):
    response=c.post(base+'/messages',json=dict(characterId=cid,requestId=key,text=text));assert response.status_code==200,response.text
    return response.json()

def smalltalk(*_):return dict(disposition='smalltalk',segments=[dict(text='来，且在此歇一歇。')])

def generated(ctx):
    roles=[]
    for item in ctx['roles']:
        value=persona.empty(item['characterId']);value.update(prompt='以本人的身份自然交谈，不预知后来事件。',knowledgeTiming=[dict(clueId=c['id'],status='known',reason='替身候选，待核对',topic='当时见闻',question='方才发生了什么？') for c in item['clues']]);roles.append(value)
    return dict(personas=roles)

def test_missing_persona_blocks_only_new_role_and_old_sessions_continue(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);old=legacy_session(c,p)
    current=main.get(p['id']);current['workspace']['entities']['persona:'+cid]['published']=None
    current=main.save(current,current['version'],'studio:test_remove_role')
    assert not experience.available_people(current)
    assert c.post(f"/api/projects/{p['id']}/experience/sessions").status_code==422
    value=c.get(f"/api/projects/{p['id']}/experience/sessions/{old['session']['id']}").json()
    assert value['people'] and value['oldVersion']
    async def provider(*_):return dict(answer='旧版回答',clueIds=['c'])
    monkeypatch.setattr(experience,'answer',provider)
    assert send(c,f"/api/projects/{p['id']}/experience/sessions/{old['session']['id']}",cid)['answer']=='旧版回答'

def test_greetings_unknown_and_profile_expressions_are_not_replaced(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);_,base=new_session(c,p);before=main.get(p['id'])
    async def provider(ctx,message,history):
        assert 'persona' in ctx and '不能透露的秘密' not in json.dumps(ctx,ensure_ascii=False)
        assert not any(v in ctx['character'] for v in ('biography','summary'))
        if message=='未来':return dict(disposition='unknown',segments=[dict(text='那是将来的事，我此刻如何知道？')])
        return smalltalk()
    monkeypatch.setattr(experience,'answer',provider)
    assert send(c,base,cid)['answer']=='来，且在此歇一歇。'
    answer=send(c,base,cid,'two','未来');assert answer['answer']!='现有的已确认知识中没有这方面的信息，我无法回答。'
    assert answer['segments'][0]['category']=='fiction' and not answer['clueIds']
    assert main.get(p['id'])==before

def test_exact_paragraph_labels_and_rewrites_cannot_promote_themselves():
    ctx=dict(clues=[dict(id='c')],basis=[dict(id='s',text='原资料文字',category='supported',evidence=[],clueId='c',origin='source'),dict(id='i',text='研究者推断其身份未定',category='inference',evidence=[],clueId='c',origin='research')])
    result=persona.verify_reply(dict(segments=[dict(text='原资料文字',basisIds=['s'],clueIds=['c']),dict(text='研究者推断其身份未定',basisIds=['i']),dict(text='我略一沉吟，此事尚难断言。',basisIds=['i'])]),ctx)
    assert [v['category'] for v in result['segments']]==['supported','inference','fiction']
    assert result['clueIds']==['c'] and result['answer'].count('\n\n')==2
    assert result['segments'][2]['verification']=='performance'

@pytest.mark.parametrize('row',[
    dict(text='越权',basisIds=['outside']),dict(text='越权',clueIds=['not-known']),
    dict(text='仅贴编号',clueIds=['c']),dict(text='凭空新增历史事实'),
])
def test_invalid_or_id_only_paragraphs_are_rejected(row):
    with pytest.raises(ValueError):persona.verify_reply(dict(segments=[row]),dict(basis=[],clues=[dict(id='c')]))

@pytest.mark.parametrize('disposition',['unknown','smalltalk'])
def test_unknown_and_greetings_cannot_smuggle_citations(disposition):
    with pytest.raises(ValueError):persona.verify_reply(dict(disposition=disposition,segments=[dict(text='伪装',basisIds=['a'])]),dict(basis=[dict(id='a',text='伪装',category='supported',evidence=[],clueId='',origin='source')],clues=[]))

def test_three_turn_counter_idempotency_hint_dismissal_and_cooldown(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);_,base=new_session(c,p);calls=[]
    async def provider(*_):calls.append(True);return smalltalk()
    monkeypatch.setattr(experience,'answer',provider)
    for i in range(3):
        turn=send(c,base,cid,str(i));assert turn['status']=='completed'
        state=c.get(base).json()['session']['guidance'];assert state['offTopicCount']==i+1
        assert bool(state['hint'])==(i==2)
    assert send(c,base,cid,'2')==turn and len(calls)==3
    h=state['hint'];req=dict(hintId=h['id'],requestId='dismiss')
    assert c.post(base+'/guidance/dismiss',json=req).status_code==200
    assert c.post(base+'/guidance/dismiss',json=req).status_code==200
    send(c,base,cid,'3');state=c.get(base).json()['session']['guidance'];assert state['offTopicCount']==1 and state['hint'] is None
    req['hintId']='different';assert c.post(base+'/guidance/dismiss',json=req).status_code==409

def test_grounded_clue_resets_count_collect_unlocks_and_completed_game_has_no_hint(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);_,base=new_session(c,p)
    async def provider(ctx,message,*_):
        if message=='线索':
            b=next(v for v in ctx['basis'] if v['clueId']=='c');return dict(segments=[dict(text=b['text'],basisIds=[b['id']],clueIds=['c'])])
        return smalltalk()
    monkeypatch.setattr(experience,'answer',provider)
    send(c,base,cid,'0');send(c,base,cid,'1')
    turn=send(c,base,cid,'clue','线索');view=c.get(base).json()
    assert view['session']['guidance']['offTopicCount']==0 and not view['media']
    view=c.post(base+'/collect',json=dict(turnId=turn['id'],clueId='c')).json();assert view['media'][0]['storyboardId']=='c'
    for i in range(4):send(c,base,cid,'idle-'+str(i))
    view=c.get(base).json();assert view['session']['guidance']['offTopicCount']==4 and view['session']['guidance']['hint'] is None
    # Repeating a previously collected clue is no new progress.
    send(c,base,cid,'again','线索');assert c.get(base).json()['session']['guidance']['offTopicCount']==5

def test_failures_and_invalid_ids_never_count_or_unlock(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);_,base=new_session(c,p)
    async def provider(*_):return dict(segments=[dict(text='越权',clueIds=['not-known'])])
    monkeypatch.setattr(experience,'answer',provider)
    turn=send(c,base,cid);assert turn['status']=='failed'
    assert c.get(base).json()['session']['guidance']==guide.initial()
    assert c.post(base+'/collect',json=dict(turnId=turn['id'],clueId='not-known')).status_code==422
    async def fail(*_):raise ValueError('模拟失败，输入保留')
    monkeypatch.setattr(experience,'answer',fail);assert send(c,base,cid,'retry')['status']=='failed'
    assert c.get(base).json()['session']['guidance']==guide.initial()

def test_future_clues_are_filtered_and_cannot_be_confirmed_as_known(merged_client):
    c=merged_client;p,cid=ready(c);w=p['workspace'];clue=w['entities']['clue:c']['published']
    mat=w['entities']['material:main'];quote='后续事件'
    clue['units'][0]['references']=[dict(sourceId='later',sourceVersion=1,quote=quote)]
    # Only the temporal mapping is under test; exact source remains fully present.
    mat['published']['structured']=dict(sources=[dict(id='later',version=1,title='测试后续资料',text=quote)],evidence=[dict(id='later-e',quote=quote,sourceId='later',sourceVersion=1)],events=[dict(phase='后续',referenceIds=['later-e'])])
    with pytest.raises(ValueError,match='后续'):persona.validate(p,w,w['entities']['persona:'+cid])

def test_group_shares_one_preparation_and_changes_do_not_revoke_video_review(merged_client):
    c=merged_client;p,cid=ready(c);assert len(experience.available_people(p))==2
    roles=[r for r in p['workspace']['entities'].values() if r['kind']=='persona' and r['id']==cid];assert len(roles)==1
    shot=copy.deepcopy(p['workspace']['entities']['storyboard:c']);role=p['workspace']['entities']['persona:'+cid]
    body=dict(role['draft'],temperament='温和谨慎');p=draft(c,p,'persona',cid,body);result=confirm(c,p,'persona',cid);assert result.status_code==200,result.text
    p=result.json();assert p['workspace']['entities']['storyboard:c']==shot

def test_generation_is_explicit_keeps_manual_edits_and_reuses_job_system(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);calls=[]
    async def provider(task,ctx):assert task=='persona';calls.append(ctx);return generated(ctx)
    monkeypatch.setattr(studio_agent,'run',provider)
    c.get(f"/api/projects/{p['id']}/studio");c.get(f"/api/projects/{p['id']}/studio/checklist");assert not calls
    before=p['workspace']['entities']['persona:'+cid]['draft']
    r=c.post(f"/api/projects/{p['id']}/studio/jobs",json=dict(version=p['version'],task='persona',target=cid));assert r.status_code==200,r.text
    p,job=finish_studio(c,p['id']);assert job['state']=='completed',job
    role=p['workspace']['entities']['persona:'+cid];assert role['draft']==before and role['suggestion']['prompt']
    assert len(calls)==1 and '不能透露的秘密' not in json.dumps(calls,ensure_ascii=False)

def test_input_changed_during_generation_is_saved_as_old_input_suggestion(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);started=threading.Event();release=threading.Event()
    async def provider(task,ctx):
        started.set()
        while not release.is_set():await asyncio.sleep(.005)
        return generated(ctx)
    monkeypatch.setattr(studio_agent,'run',provider)
    c.post(f"/api/projects/{p['id']}/studio/jobs",json=dict(version=p['version'],task='persona',target=cid));assert started.wait(2)
    try:
        p=draft(c,p,'persona',cid,dict(p['workspace']['entities']['persona:'+cid]['draft'],prompt='人工修改应保留'))
    finally:release.set()
    current,job=finish_studio(c,p['id']);assert job['state']=='completed',job
    assert current['workspace']['entities']['persona:'+cid]['draft']['prompt']=='人工修改应保留'
    assert current['workspace']['generationSuggestions'][-1]['status']=='pending'

def test_one_transaction_batch_prepares_role_after_knowledge_and_config(merged_client):
    c=merged_client;p,cid=ready(c)
    p=draft(c,p,'persona',cid,dict(p['workspace']['entities']['persona:'+cid]['draft'],prompt='新的人工角色设定'))
    body=dict(version=p['version'],scope='project');base=f"/api/projects/{p['id']}/studio/batch-confirm"
    plan=c.post(base+'/preview',json=body).json();keys=[i['key'] for i in plan['eligible']]
    assert 'persona:'+cid in keys and 'experience_config:main' in keys
    req=dict(**body,requestId='roles-batch',previewHash=plan['previewHash'])
    result=c.post(base,json=req);assert result.status_code==200,result.text
    assert result.json()['project']['version']==p['version']+1
    assert c.post(base,json=req).json()['replayed']
    req['requestId']='stale';assert c.post(base,json=req).status_code==409

def test_old_and_new_v2_sessions_pin_personality_and_guidance_settings(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);_,old=new_session(c,p)
    p=draft(c,p,'experience_config','main',dict(enabled=True,offTopicThreshold=5));p=confirm(c,p,'experience_config','main').json()
    p=draft(c,p,'persona',cid,dict(p['workspace']['entities']['persona:'+cid]['draft'],temperament='温和谨慎'));p=confirm(c,p,'persona',cid).json()
    _,new=new_session(c,p);seen=[]
    async def provider(ctx,*_):seen.append(ctx['persona']['temperament']);return smalltalk()
    monkeypatch.setattr(experience,'answer',provider)
    send(c,old,cid);send(c,new,cid);assert seen==['沉稳克制','温和谨慎']
    assert c.get(old).json()['oldVersion'] and c.get(old).json()['session']['guidanceConfig']['offTopicThreshold']==3
    assert c.get(new).json()['session']['guidanceConfig']['offTopicThreshold']==5

@pytest.mark.parametrize('value',[0,21,3.5,True,'3'])
def test_guidance_configuration_rejects_invalid_thresholds(merged_client,value):
    c=merged_client;p,cid=ready(c);p=draft(c,p,'experience_config','main',dict(enabled=True,offTopicThreshold=value))
    assert confirm(c,p,'experience_config','main').status_code==422

def test_package_includes_roles_and_config_but_no_director_or_chat(merged_client):
    c=merged_client;p,cid=ready(c);new_session(c,p)
    p=draft(c,p,'experience_config','main',dict(enabled=True,offTopicThreshold=3));p=confirm(c,p,'experience_config','main').json()
    bundle=narrative.package(p,main.DATA,[],True)
    assert bundle['schemaVersion']=='3.4' and 'persona:'+cid in bundle['entities'] and 'experience_config:main' in bundle['entities']
    text=json.dumps(bundle,ensure_ascii=False);assert 'offTopicCount' not in text and 'experience_turns' not in text


def test_director_transaction_failure_preserves_counter_and_marks_answer_retryable(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);_,base=new_session(c,p)
    async def provider(*_):return smalltalk()
    monkeypatch.setattr(experience,'answer',provider)
    def fail_after_mutation(p,session,turn):
        session['guidance']['offTopicCount']=100
        raise RuntimeError('injected director failure')
    monkeypatch.setattr(guide,'completed',fail_after_mutation)
    turn=send(c,base,cid);assert turn['status']=='failed' and 'segments' not in turn
    assert c.get(base).json()['session']['guidance']==guide.initial()


def test_cross_character_count_and_model_history_stay_separate(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);w=p['workspace'];other=next(r['id'] for r in w['entities'].values() if r['kind']=='character' and r['id']!=cid)
    k=w['entities']['knowledge:'+other];k.update(draft=dict(characterId=other,clueIds=['c'],reasons={}),state='confirmed',revision=1)
    k['published']=copy.deepcopy(k['draft']);k['refs']=ws.refs_for(w,k)
    value=persona.empty(other);value.update(prompt='另一个角色的人设',knowledgeTiming=[dict(clueId='c',status='known',reason='已核对',topic='殿前',question='有什么见闻？')])
    w['entities']['persona:'+other]=ws.record('persona',other,value,True);w['entities']['persona:'+other]['refs']=ws.refs_for(w,w['entities']['persona:'+other])
    mat=w['entities']['material:main'];mat['published']['annotations'][1]['characterId']=other
    p=main.save(p,p['version'],'studio:test_two_roles');_,base=new_session(c,p);seen=[]
    async def provider(ctx,message,history):seen.append((ctx['persona']['characterId'],message,history));return smalltalk()
    monkeypatch.setattr(experience,'answer',provider)
    send(c,base,cid,'a','甲的问题');send(c,base,other,'b','乙的问题');send(c,base,cid,'c','甲的第二问')
    state=c.get(base).json()['session']['guidance'];assert state['offTopicCount']==3 and state['hint']['characterId']==cid
    assert seen[1][2]==[] and [v['question'] for v in seen[2][2]]==['甲的问题']


def test_guide_can_be_disabled_and_old_manifest_does_not_invent_roles(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);p=draft(c,p,'experience_config','main',dict(enabled=False,offTopicThreshold=1));p=confirm(c,p,'experience_config','main').json();_,base=new_session(c,p)
    async def provider(*_):return smalltalk()
    monkeypatch.setattr(experience,'answer',provider)
    send(c,base,cid);assert c.get(base).json()['session']['guidance']['hint'] is None
    old=dict(kind='animatedscroll-narrative',schemaVersion='3.2',title='旧包',state='draft',entities={})
    value=narrative.read_package(json.dumps(old));assert value['interaction']['dialogueVersion']==1 and not value['entities']
    assert '旧包' in narrative.markdown(old)


def test_role_job_can_be_explicitly_cancelled_without_writing_or_retrying(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);started=threading.Event();calls=[]
    async def provider(*_):
        calls.append(True);started.set()
        await asyncio.sleep(100)
    monkeypatch.setattr(studio_agent,'run',provider)
    path=f"/api/projects/{p['id']}/studio"
    response=c.post(path+'/jobs',json=dict(version=p['version'],task='persona',target=cid));assert response.status_code==200,response.text
    assert started.wait(2);job=response.json()['workspace']['jobs'][0]
    req=dict(version=p['version'],kind='persona',id=cid)
    response=c.post(path+f"/jobs/{job['id']}/cancel",json=req);assert response.status_code==200,response.text
    assert response.json()['workspace']['jobs'][0]['state']=='interrupted'
    assert c.post(path+f"/jobs/{job['id']}/cancel",json=req).status_code==200
    assert main.get(p['id'])==p and len(calls)==1


def test_adopting_persona_suggestion_pins_its_generation_references(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c)
    async def provider(task,ctx):return generated(ctx)
    monkeypatch.setattr(studio_agent,'run',provider)
    base=f"/api/projects/{p['id']}/studio"
    c.post(base+'/jobs',json=dict(version=p['version'],task='persona',target=cid));p,job=finish_studio(c,p['id'])
    refs=copy.deepcopy(p['workspace']['entities']['persona:'+cid]['suggestionRefs'])
    response=c.post(base+f'/personas/{cid}/adopt-suggestion',json=dict(version=p['version'],kind='persona',id=cid));assert response.status_code==200,response.text
    p=response.json();assert p['workspace']['entities']['persona:'+cid]['draftRefs']==refs
    p=confirm(c,p,'persona',cid).json();assert p['workspace']['entities']['persona:'+cid]['generationRefs']==refs


def test_manual_timing_sync_uses_new_binding_without_rewriting_generation_origin(merged_client):
    c=merged_client;p,cid=ready(c);r=p['workspace']['entities']['persona:'+cid];origin=copy.deepcopy(r['refs']);r['generationRefs']=origin
    p=main.save(p,p['version'],'studio:test_origin')
    p=draft(c,p,'knowledge',cid,dict(characterId=cid,clueIds=['c','not-known'],reasons={}))
    result=confirm(c,p,'knowledge',cid);assert result.status_code==200,result.text;p=result.json()
    body=copy.deepcopy(p['workspace']['entities']['persona:'+cid]['draft']);body['knowledgeTiming'].append(dict(clueId='not-known',status='known',reason='显式授权新增知识',topic='新增话题',question='还有什么？'))
    p=draft(c,p,'persona',cid,body);result=confirm(c,p,'persona',cid);assert result.status_code==200,result.text;p=result.json()
    assert p['workspace']['entities']['persona:'+cid]['generationRefs']==origin
    ctx=persona.context(p,cid,[]);assert {v['id'] for v in ctx['clues']}=={'c','not-known'}
