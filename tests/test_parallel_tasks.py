import asyncio,copy,json,threading,time
import pytest
from fastapi.testclient import TestClient
from backend import main,vision,workspace as ws,studio_agent,materials,task_runtime as tr
from test_studio import prepare,draft,confirm,setup
from test_import import wait


def finish_studio(client,pid):
    for _ in range(300):
        p=client.get(f'/api/projects/{pid}/studio').json();job=p['workspace']['jobs'][0]
        if job['state'] not in ('queued','running'):return p,job
        time.sleep(.01)
    raise AssertionError('task timeout')


def test_rename_only_changes_metadata_and_checks_version(client):
    p,c=prepare(client);before=copy.deepcopy(p['workspace']['entities']);path=f"/api/projects/{p['id']}"
    renamed=client.patch(path+'/metadata',json=dict(version=p['version'],title='  新项目标题  '))
    assert renamed.status_code==200 and renamed.json()['title']=='新项目标题'
    assert renamed.json()['workspace']['entities']==before
    assert client.patch(path+'/metadata',json=dict(version=p['version'],title='过期')).status_code==409
    v=renamed.json()['version']
    assert client.patch(path+'/metadata',json=dict(version=v,title='  ')).status_code==422
    assert client.patch(path+'/metadata',json=dict(version=v,title='字'*121)).status_code==422
    assert client.post('/api/projects',json=dict(title='  步辇图  ')).json()['title']=='步辇图'


def test_analysis_merges_with_unrelated_saved_drafts_and_rename(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path);started=threading.Event();release=threading.Event()
    def detect(path,progress):
        started.set();assert release.wait(3)
        return [dict(id='detected',x=.1,y=.1,w=.2,h=.3,description='',kind='character',characterId='',confirmed=False,origin='detector')]
    monkeypatch.setattr(vision,'detect',detect)
    with TestClient(main.app) as client:
        p=setup(client);pid=p['id'];path='/api/projects/'+pid
        assert client.post(path+'/tasks',json=dict(version=p['version'],kind='detect')).status_code==200
        assert started.wait(2)
        p=draft(client,p,'plot','independent',dict(title='并行编辑',body='不会丢失',goal='',characterIds=[],clueIds=[],connection='',region=None))
        renamed=client.patch(path+'/metadata',json=dict(version=p['version'],title='检测期间改名'));assert renamed.status_code==200
        release.set();task=wait(client,pid);assert task['status']=='completed',task
        current=client.get(path+'/studio').json()
        assert current['title']=='检测期间改名'
        assert current['workspace']['entities']['plot:independent']['draft']['body']=='不会丢失'
        assert current['annotations'][0]['id']=='detected'


def test_studio_task_merges_unrelated_clue_edit(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path);started=threading.Event();release=threading.Event()
    async def provider(task,ctx):
        started.set()
        while not release.is_set():await asyncio.sleep(.005)
        return dict(clues=[dict(name='重写结果',content='生成的短情节。')])
    monkeypatch.setattr(studio_agent,'run',provider)
    with TestClient(main.app) as client:
        p,c=prepare(client);p=draft(client,p,'clue','other',dict(name='背景',summary='旧内容',type='culture',parentId='culture',characterIds=[],plotIds=[],units=[]))
        path=f"/api/projects/{p['id']}/studio"
        response=client.post(path+'/jobs',json=dict(version=p['version'],task='clue',target='c',trigger='user_button'));assert response.status_code==200
        assert started.wait(2)
        body=p['workspace']['entities']['clue:other']['draft'];body['summary']='并行修改';p=draft(client,p,'clue','other',body);release.set()
        current,job=finish_studio(client,p['id']);assert job['state']=='completed',job
        assert current['workspace']['entities']['clue:other']['draft']['summary']=='并行修改'
        assert current['workspace']['entities']['clue:c']['draft']['content']=='生成的短情节。'


def test_two_task_families_cannot_run_for_same_project(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path);started=threading.Event();release=threading.Event()
    def detect(*args):started.set();release.wait(3);return []
    monkeypatch.setattr(vision,'detect',detect)
    with TestClient(main.app) as client:
        p=setup(client);path=f"/api/projects/{p['id']}"
        client.post(path+'/tasks',json=dict(version=p['version'],kind='detect'));assert started.wait(2)
        second=client.post(path+'/studio/jobs',json=dict(version=p['version'],task='check',trigger='user_button'))
        assert second.status_code in (409,422) and '运行' in second.text
        legacy=client.post(path+'/generate',json=dict(version=p['version'],task='outline'))
        assert legacy.status_code==409 and '运行' in legacy.text
        release.set();assert wait(client,p['id'])['status']=='completed'


def test_changed_image_preserves_result_as_old_input_suggestion(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path);calls=[]
    async def analyze(path,annotations,progress):
        p=main.get(pid);p['imageVersion']+=1;main.save(p,p['version'],'test_new_image')
        progress('下一阶段不应继续')
        return dict(overview={},observations=[])
    async def match(*args):calls.append(True);return []
    monkeypatch.setattr(vision,'analyze',analyze);monkeypatch.setattr(vision,'match_people',match)
    with TestClient(main.app) as client:
        p=setup(client);pid=p['id'];path=f'/api/projects/{pid}'
        client.post(path+'/tasks',json=dict(version=p['version'],kind='vision_match'))
        task=wait(client,pid);assert task['status']=='completed' and task['savedAsSuggestion'] and calls==[True]
        current=client.get(path+'/studio').json();assert current['workspace']['generationSuggestions']


def test_supplement_review_adoption_keeps_originals_and_never_matches(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path);calls=[]
    async def supplement(*args):return [dict(id='candidate',x=.55,y=.15,w=.2,h=.3,description='候选人物')]
    async def forbidden(*args):calls.append(True);raise AssertionError('implicit match')
    monkeypatch.setattr(vision,'supplement',supplement);monkeypatch.setattr(vision,'match_people',forbidden)
    with TestClient(main.app) as client:
        p=setup(client);path=f"/api/projects/{p['id']}";p['annotations']=[dict(id='manual',x=.1,y=.1,w=.15,h=.3,description='手工框',kind='character',characterId=p['characters'][0]['id'],confirmed=True,identityConfirmed=True)]
        p=client.put(path,json=p).json();original=copy.deepcopy(p['annotations'][0])
        client.post(path+'/tasks',json=dict(version=p['version'],kind='supplement'));assert wait(client,p['id'])['status']=='completed'
        p=client.get(path).json();assert p['annotations']==[original]
        proposal=p['visualDetectionProposal'];candidate=proposal['candidates'][0];candidate['x']=.6
        adopted=client.post(path+'/detections/adopt',json=dict(version=p['version'],taskId=proposal['taskId'],candidates=[candidate]))
        assert adopted.status_code==200,adopted.text
        result=adopted.json();assert result['annotations'][0]==original
        assert result['annotations'][1]['x']==.6 and result['annotations'][1]['characterId']==''
        assert calls==[]
        assert client.post(path+'/detections/adopt',json=dict(version=result['version'],taskId=proposal['taskId'],candidates=[candidate])).status_code==422


def test_supplement_cannot_be_adopted_after_image_changes(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    async def supplement(*args):return [dict(id='candidate',x=.1,y=.1,w=.1,h=.1,description='候选')]
    monkeypatch.setattr(vision,'supplement',supplement)
    with TestClient(main.app) as client:
        p=setup(client);path=f"/api/projects/{p['id']}";client.post(path+'/tasks',json=dict(version=p['version'],kind='supplement'));wait(client,p['id'])
        p=client.get(path).json();proposal=p['visualDetectionProposal'];p['imageVersion']+=1;p=client.put(path,json=p).json()
        assert client.post(path+'/detections/adopt',json=dict(version=p['version'],taskId=proposal['taskId'],candidates=proposal['candidates'])).status_code==409


def test_dense_detection_dedupe_keeps_distinct_overlapping_instances():
    a=dict(x=.2,y=.1,w=.2,h=.6);b=dict(x=.28,y=.1,w=.2,h=.6)
    assert vision.same_person(a,dict(x=.201,y=.101,w=.2,h=.6))
    assert not vision.same_person(a,b)
    tiles=vision.detection_tiles(2013,800)
    assert tiles[0]==(0,0,2013,800) and len(tiles)>3


def test_exclusive_source_hint_blocks_wrong_identity_and_background():
    chars=[dict(id='official',depictionScope='depicted'),dict(id='envoy',depictionScope='depicted')]
    hints={'red-hint':dict(id='red-hint',characterId='official',exclusive=True,quote='只有典礼官一个人是红袍在身')}
    sources=[dict(id='s',version=1,text='禄东赞在左侧三人之中。')]
    raw=dict(characterId='envoy',confidence='high',supports=[dict(sourceId='s',sourceVersion=1,quote='禄东赞')],constraintChecks=[dict(hintId='red-hint',result='supports')])
    result=vision.normalize_match(raw,dict(id='a'),chars,sources,hints)
    assert result['characterId']=='' and result['conflicts']
    raw['characterId']='author';result=vision.normalize_match(raw,dict(id='a'),chars,sources,hints)
    assert result['characterId']==''


def test_material_role_titles_and_visual_hints_preserve_exact_source_spans():
    from test_materials import inputs
    p=inputs();text='只有典礼官一个人是红袍在身，宫女在皇帝身旁。';p['materialInputs']['relationships']=text
    old=copy.deepcopy(p);p=__import__('backend.domain',fromlist=['reconcile']).reconcile(old,p)
    result=materials.bind(p,dict(segments=[],characters=[dict(name='典礼官',identity='',biography='',summary='',relationships='',evidence='',roleType='role',depictionScope='depicted',visualHints=[dict(kind='relationships',quote='只有典礼官一个人是红袍在身',text='红袍',attribute='clothing',value='红袍',strength='required',exclusive=True)])],eventFramework=[],summary=''))
    role=result['characters'][0];hint=role['visualHints'][0]
    assert role['roleType']=='role' and role['depictionScope']=='depicted'
    assert text[hint['start']:hint['end']]==hint['quote'] and hint['sourceId']


def test_manual_identity_without_old_match_is_preserved(tmp_path,monkeypatch):
    from PIL import Image
    path=tmp_path/'painting.png';Image.new('RGB',(300,200),'white').save(path)
    async def provider(*args):
        return dict(matches=[dict(annotationId='a',characterId='other',confidence='low',reason='模型不确定')])
    monkeypatch.setattr(vision,'ask',provider)
    p=dict(annotations=[dict(id='a',kind='character',x=.1,y=.1,w=.3,h=.6,characterId='manual',identityManual=True)],characters=[dict(id='manual'),dict(id='other')],sources=[],matches=[],observations=[])
    matches=asyncio.run(vision.match_people(path,p))
    assert matches[0]['characterId']=='manual' and matches[0]['manual']
