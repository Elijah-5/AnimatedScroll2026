import copy
import pytest
from backend import feedback, main, structured
from backend.people_policy import view, character_allowed, duplicate_groups, intake_ids
from test_merged_features import merged_client, ready
from test_feedback import setup, submit, wait


@pytest.mark.parametrize('kind,rid,field,value',[
 ('intent','main','theme','更集中地呈现劝谏'),('plot','p','body','保留原有史实，缩短冲突的铺垫。'),
 ('clue','c','content','朱云停顿片刻，再次进言。'),('storyboard','c','camera','保持原画构图，缓慢推近。'),
 ('character',None,'summary','根据当前资料整理后的简短小传。'),('persona',None,'temperament','爽朗直接'),
])
def test_adapters_update_only_selected_content_and_undo(merged_client,monkeypatch,kind,rid,field,value):
    c=merged_client;p,cid=setup(c);rid=rid or cid
    old=copy.deepcopy(p['workspace']['entities'])
    async def model(ctx):return dict(operations=[dict(op='update',section=kind,itemId=rid,field=field,value=value)])
    monkeypatch.setattr(feedback,'ask',model)
    job,_=submit(c,p,target=dict(kind=kind,itemIds=[rid],fields=[field]),instruction='按要求修改这一项')
    result=wait(c,p,job);assert result['status']=='completed',result
    current=main.get(p['id']);record=current['workspace']['entities'][kind+':'+rid]
    assert record['draft'][field]==value
    assert not current['workspace'].get('media',{}).get('new_job')
    for key,before in old.items():
        if key==kind+':'+rid or kind=='character' and key=='material:main':continue
        assert current['workspace']['entities'][key]['draft']==before['draft'],key
        assert current['workspace']['entities'][key]['published']==before['published'],key
    assert c.post(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}/undo').status_code==200
    after=main.get(p['id'])['workspace']['entities'][kind+':'+rid]['draft']
    assert after.get(field)==old[kind+':'+rid]['draft'].get(field)


def test_locked_clue_cannot_be_rewritten_or_bypassed_via_units(merged_client,monkeypatch):
    c=merged_client;p,_=setup(c);p['workspace']['entities']['clue:c']['draft']['units'][0]['locked']=True
    p=main.save(p,p['version'],'studio:fixture_lock')
    for i,target in enumerate([dict(kind='clue',itemIds=['c']),dict(kind='clue',itemIds=['c'],unitIds=['u'])]):
        async def model(ctx):return dict(operations=[dict(op='update',section='clue',itemId='c',unitId='u',field='text' if ctx['context']['target']['unitIds'] else 'content',value='不能覆盖')])
        monkeypatch.setattr(feedback,'ask',model)
        job,_=submit(c,p,target=target,requestId='lock'+str(i))
        assert wait(c,p,job)['status']=='failed'
    assert main.get(p['id'])['workspace']['entities']['clue:c']['draft']['units'][0]['text']==p['workspace']['entities']['clue:c']['draft']['units'][0]['text']


@pytest.mark.parametrize('kind,field',[('persona','knowledgeTiming'),('clue','plotIds'),('plot','clueIds'),('storyboard','characterIds'),('character','id')])
def test_adapters_reject_permissions_ownership_and_id_changes(merged_client,monkeypatch,kind,field):
    c=merged_client;p,cid=setup(c);rid=cid if kind in ('persona','character') else 'p' if kind=='plot' else 'c'
    async def model(ctx):return dict(operations=[dict(op='update',section=kind,itemId=rid,field=field,value='越界')])
    monkeypatch.setattr(feedback,'ask',model)
    job,_=submit(c,p,target=dict(kind=kind,itemIds=[rid]))
    assert wait(c,p,job)['status']=='failed'
    assert main.get(p['id'])['version']==p['version']


def test_130_people_projection_retains_cast_and_hides_other_mentions(merged_client):
    p,cid=setup(merged_client);value=feedback.library(p)
    base=copy.deepcopy(value['people'][0]);value['people']=[base]
    for i in range(79):value['people'].append(dict(id=f'background-{i}',name=f'背景人物{i}',scope='background',contextRoles=['historical_background'],roleType='named',referenceIds=[]))
    for i in range(39):value['people'].append(dict(id=f'unknown-{i}',name=f'范围未定{i}',scope='unknown',roleType='named',referenceIds=[]))
    for i in range(11):value['people'].append(dict(id=f'candidate-{i}',name=f'画中提及{i}',scope='depicted',roleType='role',referenceIds=[value['evidence'][0]['id']]))
    assert len(value['people'])==130
    before=copy.deepcopy(p);policy=view(p,value)
    assert policy['mainIds']==[base['id']] and len(policy['candidateIds'])==11 and len(policy['otherIds'])==118
    assert p==before
    assert not character_allowed(dict(id='unproven',name='背景',namingOrigin='document',depictionScope='unknown'),p)


def test_bulk_classification_uses_no_model_and_undo_keeps_sources_instances(merged_client,monkeypatch):
    c=merged_client;p,cid=setup(c)
    async def forbidden(*args):raise AssertionError('bulk classification must not call model')
    monkeypatch.setattr(feedback,'ask',forbidden)
    before=copy.deepcopy(p['workspace']['entities']['material:main']['draft']['annotations'])
    job,_=submit(c,p,target=dict(section='people',itemIds=[cid]),instruction='',peopleAction='exclude')
    assert wait(c,p,job)['status']=='completed'
    current=main.get(p['id']);assert cid not in view(current)['eligibleCharacterIds']
    assert current['workspace']['entities']['material:main']['draft']['annotations']==before
    assert c.post(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}/undo').status_code==200
    assert cid in view(main.get(p['id']))['eligibleCharacterIds']


def test_creator_can_include_uncertain_person_without_upgrading_evidence(merged_client,monkeypatch):
    c=merged_client;p,_=setup(c);person=next(r for r in feedback.library(p)['people'] if r['id']=='alias');person['scope']='unknown'
    p=main.save(p,p['version'],'studio:uncertain_fixture')
    async def forbidden(*args):raise AssertionError('no model')
    monkeypatch.setattr(feedback,'ask',forbidden)
    job,_=submit(c,p,target=dict(section='people',itemIds=['alias']),instruction='',peopleAction='include')
    result=wait(c,p,job);assert result['status']=='completed',result
    current=main.get(p['id']);assert 'alias' in view(current)['eligibleCharacterIds']
    row=next(r for r in feedback.library(current)['people'] if r['id']=='alias')
    assert row['scope']=='unknown' and row['inclusionDecision']=='include'
    assert c.post(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}/undo').status_code==200
    assert 'character:alias' not in main.get(p['id'])['workspace']['entities']


def test_batch_merge_keeps_independent_groups_separate(merged_client,monkeypatch):
    c=merged_client;p,cid=setup(c);value=feedback.library(p)
    value['people'] += [dict(id='x',name='甲',scope='unknown',roleType='named',characterId='',annotationIds=[],referenceIds=[]),dict(id='y',name='甲别名',scope='unknown',roleType='named',characterId='',annotationIds=[],referenceIds=[])]
    p=main.save(p,p['version'],'studio:groups')
    async def forbidden(*args):raise AssertionError('explicit group choice must not call model')
    monkeypatch.setattr(feedback,'ask',forbidden)
    job,_=submit(c,p,target=dict(section='people',itemIds=[cid,'alias','x','y']),instruction='',peopleAction='merge_groups',groups=[dict(personIds=[cid,'alias'],survivorId=cid),dict(personIds=['x','y'],survivorId='x')])
    result=wait(c,p,job);assert result['status']=='completed',result
    value=feedback.library(main.get(p['id']))
    assert any(r['id']==cid for r in value['people']) and any(r['id']=='x' for r in value['people'])
    assert value['personRedirects']['alias']==cid and value['personRedirects']['y']=='x'


def test_similar_names_clothing_and_group_members_are_not_auto_merged():
    people=[dict(id='t',name='唐太宗',roleType='named',scope='depicted',characterId='t'),dict(id='s',name='宋太宗',roleType='named',scope='depicted'),dict(id='bare',name='太宗',roleType='named',scope='depicted'),dict(id='a',name='红衣侍女',roleType='role',scope='depicted'),dict(id='b',name='红衣侍女',roleType='role',scope='depicted'),dict(id='g',name='侍女',roleType='group',scope='depicted')]
    groups=duplicate_groups(dict(people=people,evidence=[]))
    assert not groups


def test_new_descriptions_are_deferred_but_explicit_decisions_persist(merged_client):
    p,cid=setup(merged_client)
    rows=[dict(id='new',name='红衣官员',scope='depicted',roleType='role',depictionReferences=[dict(quote='画中红衣官员')]),dict(id='bg',name='研究者',scope='background',roleType='named',referenceIds=['e'])]
    assert not intake_ids(p,rows)
    feedback.library(p)['people'][0]['inclusionDecision']='exclude'
    assert cid not in view(p)['eligibleCharacterIds'] or feedback.library(p)['people'][0]['id'] not in view(p)['mainIds']


def test_unit_context_only_advertises_selected_editable_fields(merged_client):
    from backend.smart_adapters import ADAPTERS
    p,_=setup(merged_client)
    target=feedback.FeedbackTarget(kind='clue',itemIds=['c'],unitIds=['u'],fields=['text'])
    context=ADAPTERS['clue'].context(p,target)
    assert context['allowedFields']==['text']


def test_bulk_classification_handles_all_118_filtered_people(merged_client,monkeypatch):
    c=merged_client;p,_=setup(c);value=feedback.library(p)
    ids=[f'background-{i}' for i in range(118)]
    value['people'] += [dict(id=rid,name=rid,scope='background',roleType='named',contextRoles=[],referenceIds=[],characterId='',annotationIds=[]) for rid in ids]
    p=main.save(p,p['version'],'studio:bulk_fixture')
    async def forbidden(*args):raise AssertionError('no model')
    monkeypatch.setattr(feedback,'ask',forbidden)
    job,_=submit(c,p,target=dict(section='people',itemIds=ids),instruction='',peopleAction='exclude')
    assert wait(c,p,job)['status']=='completed'
    assert len([r for r in feedback.library(main.get(p['id']))['people'] if r.get('inclusionDecision')=='exclude'])==118
    assert c.post(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}/undo').status_code==200
    assert not any(r.get('inclusionDecision')=='exclude' for r in feedback.library(main.get(p['id']))['people'])


def test_alias_list_in_same_quote_is_not_proof_of_identity():
    people=[dict(id='a',name='甲',scope='depicted',characterId='a',aliases=[dict(name='乙',referenceIds=['e'])]),dict(id='b',name='乙',scope='depicted')]
    assert not duplicate_groups(dict(people=people,evidence=[dict(id='e',quote='甲、乙同在画中。')]))
    groups=duplicate_groups(dict(people=people,evidence=[dict(id='e',quote='甲又名乙。')]))
    assert len(groups)==1 and groups[0]['safe']


def test_used_role_survives_background_reclassification_unless_creator_excludes():
    character=dict(id='used',name='角色',namingOrigin='document',depictionScope='background')
    p=dict(workspace=dict(entities={'plot:p':dict(kind='plot',state='draft',draft=dict(characterIds=['used']))}))
    assert character_allowed(character,p)
    character['inclusionDecision']='exclude'
    assert not character_allowed(character,p)


def test_profile_mirror_uses_structured_person_identity_not_only_character_id(merged_client):
    from backend.smart_adapters import ADAPTERS
    p,cid=setup(merged_client);value=feedback.library(p)
    person=next(r for r in value['people'] if r.get('characterId')==cid)
    person['id']='stable-material-person'
    value['statements'].append(dict(id='profile-mirror',personId=person['id'],profileField='biography',aspect='经历',text='旧经历',category='supported',referenceIds=[value['evidence'][0]['id']]))
    row=p['workspace']['entities']['character:'+cid];row['draft']['biography']='创作者改写的经历'
    context=ADAPTERS['character'].context(p,feedback.FeedbackTarget(kind='character',itemIds=[cid]))
    assert any(r['id']=='profile-mirror' for r in context['characterFacts'])
    ADAPTERS['character'].sync_character(p,row,'biography')
    statement=next(r for r in value['statements'] if r['id']=='profile-mirror')
    assert statement['text']=='创作者改写的经历' and statement['category']=='uncertain'
    assert not statement['referenceIds'] and statement['previousReferenceIds']
