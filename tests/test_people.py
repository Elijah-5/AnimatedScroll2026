import copy
import pytest
from backend import agent,materials
from backend.domain import reconcile
from test_materials import inputs


def person_project(client):
    p=client.post('/api/sample?example=zhekan').json();cid=p['characters'][0]['id']
    p['annotations']=[dict(id='a'+str(i),x=.1*i,y=.1,w=.1,h=.2,kind='character',description='',confirmed=False,characterId=cid,identityConfirmed=False) for i in range(2)]
    return client.put('/api/projects/'+p['id'],json=p).json()


def test_unified_confirmation_atomic_and_instance_specific(client):
    p=person_project(client);path='/api/projects/'+p['id'];cid=p['characters'][0]['id']
    p=client.post(path+'/people/a0/confirm',json=dict(version=p['version'],characterId=cid)).json()
    assert p['characters'][0]['confirmed'] and p['annotations'][0]['identityConfirmed']
    assert not p['annotations'][1]['identityConfirmed']
    loaded=client.get(path).json();assert loaded['characters'][0]['confirmed']
    assert client.post(path+'/people/a0/confirm',json=dict(version=1,characterId=cid)).status_code==409


def test_missing_role_message_and_confirmed_generation(client,monkeypatch):
    p=person_project(client);path='/api/projects/'+p['id']
    response=client.post(path+'/generate',json=dict(version=p['version'],task='outline'))
    assert response.status_code==422
    assert response.json()['detail']['code']=='characters_unconfirmed'
    assert {c['name'] for c in response.json()['detail']['characters']}=={c['name'] for c in p['characters']}
    for c in p['characters']:
        p=client.post(path+'/characters/'+c['id']+'/confirm',json=dict(version=p['version'],characterId=c['id'])).json()
    # Unnamed/unconfirmed instances do not prevent outline generation.
    async def fake(*args):return dict(scenes=[])
    monkeypatch.setattr(agent,'generate',fake)
    assert client.post(path+'/generate',json=dict(version=p['version'],task='outline')).status_code==200


def test_direct_name_duplicate_and_no_llm(client,monkeypatch):
    async def forbidden(*args):raise AssertionError('unexpected model')
    monkeypatch.setattr(agent,'generate',forbidden);monkeypatch.setattr(materials,'organize',forbidden)
    p=person_project(client);path='/api/projects/'+p['id']
    p=client.post(path+'/people/a0/name',json=dict(version=p['version'],name='殿前侍卫')).json()
    c=next(c for c in p['characters'] if c['name']=='殿前侍卫')
    assert c['namingOrigin']=='creator' and not c['identity'] and not c['biography']
    assert not c['confirmed'] and p['annotations'][0]['characterId']==c['id']
    r=client.post(path+'/people/a1/name',json=dict(version=p['version'],name='殿前侍卫'))
    assert r.status_code==409 and r.json()['detail']['code']=='name_exists'
    p=client.post(path+'/people/a1/name',json=dict(version=p['version'],name='殿前侍卫',useExisting=True)).json()
    assert len([c for c in p['characters'] if c['name']=='殿前侍卫'])==1
    assert p['annotations'][1]['characterId']==c['id']


def test_profile_and_geometry_changes_invalidate(client):
    p=person_project(client);path='/api/projects/'+p['id'];cid=p['characters'][0]['id']
    p=client.post(path+'/people/a0/confirm',json=dict(version=p['version'],characterId=cid)).json()
    p['annotations'][0]['x']=.2
    p=client.put(path,json=p).json()
    assert not p['annotations'][0]['identityConfirmed'] and p['characters'][0]['confirmed']
    assert p['annotations'][0]['characterId']==cid
    p=client.post(path+'/people/a0/confirm',json=dict(version=p['version'],characterId=cid)).json()
    p['characters'][0]['identity']='已修改身份'
    p=client.put(path,json=p).json()
    assert not p['characters'][0]['confirmed'] and not p['annotations'][0]['identityConfirmed']


def test_deleted_instance_can_be_restored_without_deleting_role(client):
    p=person_project(client);path='/api/projects/'+p['id'];before=copy.deepcopy(p)
    p['annotations']=p['annotations'][1:]
    p=client.put(path,json=p).json()
    assert len(p['characters'])==len(before['characters'])
    p['annotations'].insert(0,before['annotations'][0])
    p=client.put(path,json=p).json()
    assert [a['id'] for a in p['annotations']]==['a0','a1']


def test_missing_biography_uses_exact_mention_and_does_not_invent():
    p=inputs()
    parsed=dict(segments=[],characters=[dict(name='朱云',identity='',biography='',relationships='',summary='不应保留的编造描述',knowledge='',evidence='')],eventFramework=[],summary='')
    c=materials.bind(p,parsed)['characters'][0]
    assert '未提供具体身份／经历' in c['summary']
    m=c['mentions'][0];assert p['materialInputs'][m['kind']][m['start']:m['end']]==m['quote']=='朱云'


def test_candidate_update_preserves_id_and_manual_content_until_adopt(client):
    p=person_project(client);path='/api/projects/'+p['id'];c=p['characters'][0]
    candidate={**c,'id':'candidate','summary':'更新候选简介','confirmed':False}
    p['materialAnalysis']=dict(inputVersion=p['materialInputs']['version'],stale=False,characters=[candidate])
    p=client.put(path,json=p).json()
    assert p['characters'][0]['summary']!='更新候选简介'
    p=client.post(path+'/materials/adopt',json=dict(version=p['version'],updateIds=[c['id']])).json()
    assert p['characters'][0]['id']==c['id'] and p['characters'][0]['summary']=='更新候选简介'
