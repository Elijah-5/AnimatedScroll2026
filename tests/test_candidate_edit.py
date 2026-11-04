import copy
from backend import main,documents as docs
from backend.models import Project
from test_documents import literature_project,analysis

def setup_candidate():
    p=literature_project()
    p['characters']=[dict(id='stable-character',name='画家甲',identity='原身份',summary='原简介',biography='',relationships='',knowledge='',evidence='',confirmed=True)]
    p=Project.model_validate(p).model_dump()
    p['documentAnalysis']=analysis(p)
    return main.save(p,0,'test_setup')

def edit_request(p,**changes):
    profile=dict(name='创作者改名',identity='手动身份',summary='手动简介',biography='手动经历',relationships='手动关系')
    profile.update(changes)
    return dict(version=p['version'],analysisId=p['documentAnalysis']['id'],profile=profile)

def path(p):return f"/api/projects/{p['id']}/documents/analysis/people/{p['documentAnalysis']['people'][0]['id']}"

def test_manual_candidate_save_preserves_evidence_and_existing_profile_until_adoption(client,monkeypatch):
    async def forbidden(*args,**kwargs):raise AssertionError('manual edit must not call LLM')
    monkeypatch.setattr(docs,'ask',forbidden)
    p=setup_candidate();candidate=copy.deepcopy(p['documentAnalysis']['people'][0]);characters=copy.deepcopy(p['characters'])
    response=client.patch(path(p),json=edit_request(p));assert response.status_code==200,response.text
    saved=response.json();edited=saved['documentAnalysis']['people'][0]
    assert saved['characters']==characters and saved['workspace']['entities']==p['workspace']['entities']
    assert edited['id']==candidate['id'] and edited['references']==candidate['references']
    assert {k:v for k,v in edited.items() if k not in ('manualProfile','manualEditedAt')}==candidate
    assert client.get('/api/projects/'+p['id']).json()['documentAnalysis']['people'][0]['manualProfile']==edit_request(p)['profile']

def test_adopting_a_renamed_candidate_keeps_stable_character_and_instance_ids(client):
    p=setup_candidate();p['annotations']=[dict(id='box',x=.1,y=.1,w=.2,h=.3,kind='character',characterId='stable-character',description='',confirmed=False)]
    p=client.put('/api/projects/'+p['id'],json=p).json()
    p=client.patch(path(p),json=edit_request(p)).json();cid=p['documentAnalysis']['people'][0]['id']
    payload=dict(version=p['version'],analysisId='analysis',summaryKinds=[],characterIds=[cid],updateIds=['stable-character'])
    adopted=client.post('/api/projects/'+p['id']+'/documents/analysis/adopt',json=payload)
    assert adopted.status_code==200,adopted.text
    p=adopted.json();assert len(p['characters'])==1
    c=p['characters'][0]
    assert c['id']=='stable-character' and c['name']=='创作者改名' and c['sourceName']=='画家甲'
    assert c['profileEdit']['origin']=='creator' and not c['confirmed']
    assert p['annotations'][0]['characterId']=='stable-character'
    p=client.patch(path(p),json=edit_request(p,name='再次改名')).json()
    payload['version']=p['version']
    p=client.post('/api/projects/'+p['id']+'/documents/analysis/adopt',json=payload).json()
    assert len(p['characters'])==1 and p['characters'][0]['id']=='stable-character' and p['characters'][0]['name']=='再次改名'

def test_candidate_edit_rejects_empty_names_unknown_fields_and_stale_versions(client):
    p=setup_candidate()
    assert client.patch(path(p),json=edit_request(p,name='  ')).status_code==422
    request=edit_request(p);request['profile']['references']=[]
    assert client.patch(path(p),json=request).status_code==422
    saved=client.patch(path(p),json=edit_request(p)).json()
    assert client.patch(path(p),json=edit_request(p,name='过期编辑')).status_code==409
    assert client.get('/api/projects/'+p['id']).json()==saved

def test_candidate_edit_does_not_bypass_changed_source_or_analysis_guards(client):
    p=setup_candidate();request=edit_request(p);request['analysisId']='other'
    assert client.patch(path(p),json=request).status_code==422
    p['sources'][0]['text']+='原文已补充'
    p=client.put('/api/projects/'+p['id'],json=p).json()
    assert client.patch(path(p),json=edit_request(p)).status_code==422
