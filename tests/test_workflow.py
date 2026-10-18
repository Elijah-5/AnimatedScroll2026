import copy
import json
import pytest
from fastapi.testclient import TestClient
from backend import main, agent
from backend.sample import sample
from backend.domain import reconcile, citation_errors, validate, units

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    return TestClient(main.app)


def test_persistence_version_and_history(client):
    p = client.post('/api/projects').json()
    p['title'] = '修改'
    saved = client.put('/api/projects/'+p['id'],json=p)
    assert saved.status_code == 200
    assert client.get('/api/projects/'+p['id']).json()['title']=='修改'
    assert client.put('/api/projects/'+p['id'],json=p).status_code == 409
    events=client.get('/api/projects/'+p['id']+'/events').json()
    assert events[-1]['before']['title'] != events[-1]['after']['title']


def test_citations_and_dialogue():
    p=sample(); u=units(p)[0]
    assert not citation_errors(u,p)
    u['kind']='dialogue';u['text']='一段未被记录的对白'
    assert citation_errors(u,p)
    u['category']='fiction';u['references']=[]
    assert not citation_errors(u,p)
    u['category']='inference'
    assert citation_errors(u,p)


def test_source_changes_invalidate_approvals():
    old=sample();units(old)[0]['status']='approved';new=copy.deepcopy(old)
    new['sources'][0]['text']+='新增信息'
    result=reconcile(old,new)
    assert result['sources'][0]['version']==2
    assert units(result)[0]['status']=='pending'
    assert citation_errors(units(result)[0],result)


def test_locked_edit_and_deletion():
    old=sample();units(old)[0]['locked']=True
    new=copy.deepcopy(old);units(new)[0]['text']='changed'
    with pytest.raises(ValueError):reconcile(old,new)
    new=copy.deepcopy(old);new['scenes'][0]['units']=[]
    with pytest.raises(ValueError):reconcile(old,new)


def test_edit_clears_checks():
    old=sample();old['checks']=[{'message':'ok','resolved':True}]
    new=copy.deepcopy(old);units(new)[0]['text']='changed'
    assert reconcile(old,new)['checks']==[]


def test_export_gate_and_formats(client):
    p=client.post('/api/sample').json();path='/api/projects/'+p['id']
    assert client.get(path+'/export?draft=false').status_code==422
    assert client.get(path+'/export').json()['state']=='draft'
    for c in p['characters']:c['confirmed']=True
    p=client.put(path,json=p).json()
    p['outlineConfirmed']=True
    p=client.put(path,json=p).json()
    for u in units(p):u['status']='approved'
    p['checks']=[{'id':'manual','message':'人工已核对','resolved':True}]
    assert client.put(path,json=p).status_code==200
    r=client.get(path+'/export?draft=false')
    assert r.status_code==200 and r.json()['state']=='approved'
    assert client.get(path+'/export?format=md&draft=false').status_code==200
    assert 'before' in client.get(path+'/export?format=csv').text
    assert json.loads(client.get(path+'/export?format=jsonl').text.splitlines()[0])['action']=='load_editorial_sample'


def test_invalid_reference_approval(client):
    p=client.post('/api/sample').json();path='/api/projects/'+p['id']
    units(p)[0]['references'][0]['quote']='伪造'
    p=client.put(path,json=p).json()
    units(p)[0]['status']='approved'
    assert client.put(path,json=p).status_code==422


def test_generation_failure_preserves_content(client,monkeypatch):
    p=client.post('/api/projects').json();path='/api/projects/'+p['id']
    async def fail(*args):raise ValueError('模拟失败')
    monkeypatch.setattr(agent,'generate',fail)
    assert client.post(path+'/generate',json={'version':p['version'],'task':'extract'}).status_code==502
    assert client.get(path).json()==p


def test_stale_generation(client,monkeypatch):
    p=client.post('/api/projects').json();path='/api/projects/'+p['id']
    async def changed(*args):
        current=main.get(p['id']);current['title']='new';main.save(current,current['version'],'concurrent')
        return {'characters':[]}
    monkeypatch.setattr(agent,'generate',changed)
    assert client.post(path+'/generate',json={'version':p['version'],'task':'extract'}).status_code==409
    assert client.get(path).json()['title']=='new'


def test_proposal_preserves_locked_units(client):
    p=client.post('/api/sample').json();path='/api/projects/'+p['id'];scene=p['scenes'][0]
    scene['units'][0]['locked']=True
    p=client.put(path,json=p).json();locked=copy.deepcopy(p['scenes'][0]['units'][0])
    proposal=dict(version=p['version'],sceneId=scene['id'],proposal={'units':[{'text':'新虚构动作','kind':'action','category':'fiction','references':[]}]})
    r=client.post(path+'/apply',json=proposal)
    assert r.status_code==200
    assert r.json()['scenes'][0]['units'][0]==locked
    assert client.post(path+'/apply',json=proposal).status_code==409


def test_mocked_full_generation(client,monkeypatch):
    p=client.post('/api/sample').json();path='/api/projects/'+p['id']
    for c in p['characters']:c['confirmed']=True
    for s in p['scenes']:s['units']=[]
    p=client.put(path,json=p).json();p['outlineConfirmed']=True;p=client.put(path,json=p).json()
    async def fake(task,*args):
        if task=='check':return {'checks':[{'id':'check','message':'复核','resolved':False}]}
        return {'units':[{'id':main.uid(),'text':'虚构动作','kind':'action','category':'fiction','speakerId':'','rationale':'','references':[],'status':'pending','locked':False}]}
    monkeypatch.setattr(agent,'generate',fake)
    for scene in p['scenes']:
        p=client.post(path+'/generate',json={'version':p['version'],'task':'scene','sceneId':scene['id']}).json()
    p=client.post(path+'/generate',json={'version':p['version'],'task':'check'}).json()
    for u in units(p):u['status']='approved'
    p['checks'][0]['resolved']=True
    assert client.put(path,json=p).status_code==200
    assert client.get(path+'/export?draft=false').status_code==200


def test_confirmed_observation():
    p=sample();u=units(p)[0]
    p['annotations']=[{'id':'a','description':'坐于床榻','confirmed':True}]
    u['references']=[{'annotationId':'a','quote':'坐于床榻'}]
    assert not citation_errors(u,p)
    p['annotations'][0]['confirmed']=False
    assert citation_errors(u,p)


def test_unchanged_save_keeps_approval(client):
    p=client.post('/api/sample').json();path='/api/projects/'+p['id']
    units(p)[0]['status']='approved'
    p=client.put(path,json=p).json()
    assert units(p)[0]['status']=='approved'
    p=client.put(path,json=p).json()
    assert units(p)[0]['status']=='approved'
