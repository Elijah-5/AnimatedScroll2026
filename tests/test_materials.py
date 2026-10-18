import copy
from backend import materials,agent,vision,main
from backend.domain import blank,reconcile,citation_errors
from fastapi.testclient import TestClient
from test_import import wait,png
import pytest


def inputs():
    p=blank();p['materialInputs'].update(background='宋代画作表现汉代故事。',relationships='朱云向成帝进谏，辛庆忌求情。',narrative='朱云攀栏，栏杆折断。')
    return reconcile(blank(),p)


def organized(p):
    return dict(segments=[dict(kind='background',quote='宋代画作',summary='画作时代')],characters=[],eventFramework=['朱云攀栏'],summary='整理摘要')


def test_exact_span_and_versions():
    p=inputs();result=materials.bind(p,organized(p));seg=result['segments'][0]
    assert p['materialInputs'][seg['kind']][seg['start']:seg['end']]==seg['quote']
    assert seg['sourceId'] in {s['id'] for s in p['sources']}
    bad=organized(p);bad['segments'][0]['quote']='编造内容'
    with pytest.raises(ValueError):materials.bind(p,bad)


def test_empty_narrative_never_invents_framework():
    p=inputs();p['materialInputs']['narrative']=''
    with pytest.raises(ValueError):materials.bind(p,organized(p))
    u=dict(kind='event',category='supported',references=[],text='新的事件')
    assert any('新增故事事件' in e for e in citation_errors(u,p))


def test_input_change_stales_analysis_and_sources():
    old=inputs();old['materialAnalysis']=dict(inputVersion=old['materialInputs']['version'],stale=False)
    new=copy.deepcopy(old);new['materialInputs']['background']='不同背景'
    result=reconcile(old,new)
    assert result['materialAnalysis']['stale']
    assert result['materialInputs']['version']==old['materialInputs']['version']+1
    before=next(s for s in old['sources'] if s.get('materialKind')=='background')
    after=next(s for s in result['sources'] if s.get('materialKind')=='background')
    assert after['id']==before['id'] and after['version']==before['version']+1
    same=reconcile(result,copy.deepcopy(result))
    assert same['materialInputs']['version']==result['materialInputs']['version']


def test_non_model_actions_make_zero_llm_calls(client,monkeypatch):
    calls=[]
    async def forbidden(*args,**kwargs):calls.append(True);raise AssertionError('unexpected model call')
    monkeypatch.setattr(materials,'organize',forbidden);monkeypatch.setattr(vision,'ask',forbidden);monkeypatch.setattr(agent,'generate',forbidden)
    p=client.post('/api/projects').json();path='/api/projects/'+p['id']
    p=client.post(path+'/image?version=1',files={'file':('painting.png',png(),'image/png')}).json()
    p['materialInputs']['background']='背景';p['annotations']=[dict(id='a',x=.1,y=.1,w=.4,h=.4,kind='character',description='',confirmed=False,characterId='')]
    p=client.put(path,json=p).json()
    for endpoint in ('','/tasks','/events'):assert client.get(path+endpoint).status_code==200
    assert client.get('/api/status').status_code==200
    assert client.get(path+'/portraits/a').status_code==200
    assert client.get(path+'/portraits/a?x=.2&y=.1&w=.4&h=.4').status_code==200
    p['annotations'][0]['x']=.2;p['annotations'][0]['characterId']=''
    assert client.put(path,json=p).status_code==200
    assert calls==[]


def test_material_button_organizes_without_overwrite(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path);calls=[]
    async def fake(p,legacy=False):
        calls.append(legacy)
        return materials.bind(p,organized(p))
    monkeypatch.setattr(materials,'organize',fake)
    with TestClient(main.app) as client:
        p=client.post('/api/projects').json();path='/api/projects/'+p['id']
        p['materialInputs'].update(background='宋代画作表现汉代故事。',narrative='朱云攀栏，栏杆折断。')
        p=client.put(path,json=p).json()
        assert not calls
        assert client.post(path+'/tasks',json=dict(version=p['version'],kind='materials',trigger='page_enter')).status_code==422
        assert client.post(path+'/tasks',json=dict(version=p['version'],kind='materials',trigger='user_button')).status_code==200
        assert wait(client,p['id'])['status']=='completed'
        result=client.get(path).json()
        assert result['materialInputs']==p['materialInputs']
        assert result['materialSegments'][0]['quote']=='宋代画作'
        assert calls==[False]


def test_legacy_adoption_preserves_original_sources(client):
    p=client.post('/api/sample').json();path='/api/projects/'+p['id'];source=copy.deepcopy(p['sources'][0])
    p['legacyMaterialProposal']=dict(background='旧资料摘要',relationships='人物关系',narrative='')
    p=client.put(path,json=p).json()
    result=client.post(path+'/materials/adopt',json=dict(version=p['version'],legacy=True)).json()
    assert next(s for s in result['sources'] if s['id']==source['id'])==source
    assert result['materialInputs']['background']=='旧资料摘要'


def test_same_identity_multiple_instances(client):
    p=client.post('/api/sample?example=zhekan').json();path='/api/projects/'+p['id']
    cid=p['characters'][0]['id']
    p['annotations']=[dict(id='a'+str(i),x=.1*i,y=.1,w=.1,h=.1,kind='character',description='',confirmed=False,characterId=cid,identityConfirmed=True) for i in range(2)]
    result=client.put(path,json=p).json()
    assert [a['characterId'] for a in result['annotations']]==[cid,cid]


def test_restart_recovery_requires_startup(tmp_path,monkeypatch):
    import json
    monkeypatch.setattr(main,'DATA',tmp_path)
    with main.db() as c:
        c.execute('INSERT INTO tasks VALUES (?,?,?)',('live','p',json.dumps(dict(id='live',status='running'))))
    with TestClient(main.app):pass
    with main.db() as c:assert json.loads(c.execute('SELECT body FROM tasks').fetchone()[0])['status']=='interrupted'


def test_combined_button_is_one_explicit_task_and_keeps_confirmed_mapping(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path);calls=[]
    async def analyze(path,annotations,progress):
        calls.append('analyze');return dict(overview=dict(summary='全图'),observations=[])
    async def match(path,p):
        calls.append('match');return [dict(id='m',annotationId='a',characterId=p['characters'][1]['id'],confirmed=False,reason='候选')]
    monkeypatch.setattr(vision,'analyze',analyze);monkeypatch.setattr(vision,'match_people',match)
    with TestClient(main.app) as client:
        p=client.post('/api/sample?example=zhekan').json();path='/api/projects/'+p['id'];cid=p['characters'][0]['id']
        p['annotations']=[dict(id='a',x=.1,y=.1,w=.2,h=.2,kind='character',description='',confirmed=False,characterId=cid,identityConfirmed=True)]
        p=client.put(path,json=p).json()
        assert client.post(path+'/tasks',json=dict(version=p['version'],kind='vision_match',trigger='user_button')).status_code==200
        assert wait(client,p['id'])['status']=='completed'
        result=client.get(path).json()
        assert calls==['analyze','match']
        assert result['annotations'][0]['characterId']==cid
        assert result['matches'][0]['confirmed'] is False
