"""Merge regression: all projects, models, remote jobs and media are isolated fakes."""
import asyncio
import copy
import io
import json
import sqlite3
import time
import zipfile
import pytest
import httpx
from PIL import Image
from fastapi.testclient import TestClient
from backend import main, workspace as ws, config, consumption, experience, video, narrative, storage
from test_studio import prepare, draft, confirm


@pytest.fixture
def merged_client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.delenv('DASHSCOPE_API_KEY',raising=False)
    from backend import video_generation
    from video_adapter_fake import FakeVideoAdapter
    monkeypatch.setitem(video_generation.ADAPTERS,'aihubmix',FakeVideoAdapter())
    with TestClient(main.app) as client:yield client


def ready(client):
    p,cid=prepare(client)
    Image.new('RGB',(800,400),'#b09b74').save(main.DATA/'merged-reference.png')
    w=p['workspace'];mat=w['entities']['material:main']
    annotation=dict(id='instance-1',kind='character',characterId=cid,x=.1,y=.1,w=.2,h=.6,description='已确认画中人物',identityConfirmed=True,confirmed=True)
    mat['draft'].update(image='/api/images/merged-reference.png',imageVersion=5,annotations=[annotation,dict(annotation,id='instance-2',x=.5)])
    mat['published']=copy.deepcopy(mat['draft'])
    p.update(image=mat['draft']['image'],imageVersion=5,annotations=copy.deepcopy(mat['draft']['annotations']))
    k=w['entities']['knowledge:'+cid];k['draft']=dict(characterId=cid,clueIds=['c'],reasons={});k['published']=copy.deepcopy(k['draft']);k.update(state='confirmed',revision=1);k['refs']=ws.refs_for(w,k)
    from backend.persona import empty
    role=empty(cid);role.update(prompt='你身处画中当时，依已确认资料自然交谈；不知未来。',knowledgeTiming=[dict(clueId='c',status='known',reason='测试已核对',topic='殿前见闻',question='方才殿前发生了什么？')])
    w['entities']['persona:'+cid]=ws.record('persona',cid,role,True)
    w['entities']['persona:'+cid]['refs']=ws.refs_for(w,w['entities']['persona:'+cid])
    shot=w['entities']['storyboard:c'];shot['draft'].update(characterIds=[cid],participantsConfirmed=True,region=dict(x=.1,y=.1,w=.2,h=.6),prompt='保留绘画风格，人物轻抬衣袖。',startFrame='人物静立',endFrame='人物放下衣袖',action='轻抬衣袖',camera='缓慢推近',style='保留古画笔触')
    shot['draft']['promptConfigHash']=ws.config_hash(shot['draft']);shot.update(published=copy.deepcopy(shot['draft']),state='confirmed',revision=1);shot['refs']=ws.refs_for(w,shot)
    secret=ws.record('clue','not-known',dict(name='未绑定秘密',type='culture',summary='不能透露的秘密',characterIds=[],plotIds=[],parentId='culture',units=[dict(id='secret-u',text='不能透露的秘密',kind='event',category='fiction',references=[])]),True)
    secret['refs']=ws.refs_for(w,secret);w['entities']['clue:not-known']=secret
    p=main.save(p,p['version'],'studio:test_fixture')
    return p,cid


def approve(client,p,sid='c',text='用户审核的最终完整文本'):
    path=f"/api/projects/{p['id']}/storyboards/{sid}"
    preview=client.get(path+'/video-prompt');assert preview.status_code==200,preview.text
    response=client.put(path+'/video-prompt',json=dict(version=p['version'],baseFingerprint=preview.json()['baseFingerprint'],text=text));assert response.status_code==200,response.text;p=response.json()
    response=client.post(path+'/confirm-video',json=dict(version=p['version']));assert response.status_code==200,response.text
    return response.json()


def session(client,p):
    r=client.post(f"/api/projects/{p['id']}/experience/sessions");assert r.status_code==200,r.text
    value=r.json()
    # These existing tests intentionally exercise the pre-segments protocol.
    # V2 sessions and every new guard are covered in test_persona_dialogue.py.
    with main.db() as c:
        body=json.loads(c.execute('SELECT body FROM experience_sessions WHERE id=?',(value['session']['id'],)).fetchone()[0]);body['dialogueVersion']=1
        c.execute('UPDATE experience_sessions SET body=? WHERE id=?',(json.dumps(body,ensure_ascii=False),body['id']))
    value['session']['dialogueVersion']=1
    return value


def send(client,p,s,cid,request_id='turn-1',text='你知道什么？'):
    return client.post(f"/api/projects/{p['id']}/experience/sessions/{s['session']['id']}/messages",json=dict(requestId=request_id,characterId=cid,text=text))


def test_video_key_does_not_switch_existing_text_provider(monkeypatch):
    monkeypatch.delenv('MODEL_PROVIDER',raising=False);monkeypatch.setenv('DASHSCOPE_API_KEY','fake-video-only')
    assert config.model_settings(require_key=False).provider=='aihubmix'
    monkeypatch.setenv('MODEL_PROVIDER','dashscope');monkeypatch.setenv('DASHSCOPE_MODEL','my-text');monkeypatch.setenv('DASHSCOPE_VISION_MODEL','my-vision')
    assert config.model_settings().model=='my-text' and config.model_settings('vision').model=='my-vision'
    assert 'fake-video-only' not in repr(config.model_settings())
    monkeypatch.delenv('DASHSCOPE_API_KEY')
    with pytest.raises(ValueError,match='DASHSCOPE_API_KEY'):config.model_settings()


def test_character_needs_at_least_one_valid_knowledge_binding(merged_client):
    p,cid=ready(merged_client);assert experience.available_people(p)
    w=p['workspace'];r=w['entities']['knowledge:'+cid];r['draft']['clueIds']=[];r['published']['clueIds']=[]
    assert experience.available_people(p)==[]


def test_video_preview_save_and_confirmation_do_not_submit_or_change_creation(merged_client,monkeypatch):
    p,cid=ready(merged_client);before=copy.deepcopy(p['workspace']['entities'])
    p=approve(merged_client,p)
    assert p['workspace']['entities']==before
    with main.db() as c:assert c.execute('SELECT COUNT(*) FROM video_jobs').fetchone()[0]==0
    preview=merged_client.get(f"/api/projects/{p['id']}/storyboards/c/video-prompt").json()
    assert preview['approved'] and not preview['stale']
    assert len(preview['references'])==2 and preview['references'][1]['characterId']==cid


def test_video_uses_confirmed_snapshot_and_unrelated_edits_do_not_invalidate(merged_client):
    p,cid=ready(merged_client);p=approve(merged_client,p)
    inputs,_=video.shot_inputs(p,'c',main.DATA);scope=inputs['scopeFingerprint']
    d=p['workspace']['entities']['storyboard:c']['draft'];d['prompt']='未确认的分镜改动'
    p=draft(merged_client,p,'storyboard','c',d)
    assert video.shot_inputs(p,'c',main.DATA)[0]['shot']['prompt']!='未确认的分镜改动'
    assert video.shot_inputs(p,'c',main.DATA)[0]['scopeFingerprint']==scope
    p=merged_client.patch(f"/api/projects/{p['id']}/metadata",json=dict(version=p['version'],title='改名不失效')).json()
    assert video.preview(p,'c',main.DATA)['approved']


def test_video_input_and_settings_changes_revoke_approval(merged_client,monkeypatch):
    p,cid=ready(merged_client);p=approve(merged_client,p)
    monkeypatch.setitem(video.VIDEO_PARAMETERS,'duration',6)
    assert video.preview(p,'c',main.DATA)['stale'] and not video.preview(p,'c',main.DATA)['approved']
    assert merged_client.post(f"/api/projects/{p['id']}/videos",json=dict(version=p['version'],storyboardId='c')).status_code==422


def test_old_prompt_version_and_unconfirmed_shot_are_rejected(merged_client):
    p,cid=ready(merged_client);path=f"/api/projects/{p['id']}"
    assert merged_client.post(path+'/videos',json=dict(version=p['version'],storyboardId='c')).status_code==422
    preview=merged_client.get(path+'/storyboards/c/video-prompt').json()
    assert merged_client.put(path+'/storyboards/c/video-prompt',json=dict(version=p['version']-1,text='内容',baseFingerprint=preview['baseFingerprint'])).status_code==409
    p['workspace']['entities']['storyboard:c']['state']='stale';p=main.save(p,p['version'],'studio:test_stale')
    assert merged_client.get(path+'/storyboards/c/video-prompt').status_code==200


def mock_video_provider(monkeypatch):
    from backend import video_generation
    from video_adapter_fake import FakeVideoAdapter
    monkeypatch.setitem(video_generation.ADAPTERS,'aihubmix',FakeVideoAdapter())
    calls=[];original=httpx.AsyncClient
    def handle(request):
        calls.append(request)
        if request.method=='POST':return httpx.Response(200,json={'output':{'task_id':'fake-remote'}})
        if '/tasks/' in str(request.url):return httpx.Response(200,json={'output':{'task_status':'SUCCEEDED','video_url':'https://test.aliyuncs.com/video.mp4'}})
        assert 'authorization' not in request.headers
        return httpx.Response(200,content=b'mock-mp4-content'*100)
    monkeypatch.setenv('DASHSCOPE_API_KEY','fake-video-key')
    monkeypatch.setattr(video.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    return calls


def wait_video(client,p,jid):
    for _ in range(150):
        job=next(j for j in client.get(f"/api/projects/{p['id']}/videos").json()['jobs'] if j['id']==jid)
        if job['status'] in ('succeeded','failed','submission_unknown','download_failed'):return job
        time.sleep(.01)
    raise AssertionError('mock job did not finish')


def test_mock_video_lifecycle_verbatim_prompt_dedup_and_selection(merged_client,monkeypatch):
    calls=mock_video_provider(monkeypatch);p,cid=ready(merged_client);p=approve(merged_client,p,text='精确审核文本\n不得隐藏拼接')
    path=f"/api/projects/{p['id']}";req=dict(version=p['version'],storyboardId='c')
    a=merged_client.post(path+'/videos',json=req);assert a.status_code==200,a.text
    b=merged_client.post(path+'/videos',json=req);assert b.json()['id']==a.json()['id']
    job=wait_video(merged_client,p,a.json()['id']);assert job['status']=='succeeded',job
    posts=[r for r in calls if r.method=='POST'];assert len(posts)==1
    payload=json.loads(posts[0].content);assert payload['input']['prompt']=='精确审核文本\n不得隐藏拼接'
    assert [v['type'] for v in payload['input']['media']]==['reference_image','reference_image']
    result=merged_client.post(path+'/storyboards/c/experience-video',json=dict(version=p['version'],jobId=job['id']));assert result.status_code==200,result.text
    assert merged_client.get(job['videoUrl']).status_code==200


def test_video_submit_timeout_never_reposts(merged_client,monkeypatch):
    original=httpx.AsyncClient;posts=[]
    def handle(request):posts.append(request);raise httpx.ReadTimeout('fake timeout',request=request)
    monkeypatch.setenv('DASHSCOPE_API_KEY','fake')
    monkeypatch.setattr(video.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    p,cid=ready(merged_client);p=approve(merged_client,p);path=f"/api/projects/{p['id']}";req=dict(version=p['version'],storyboardId='c')
    job=merged_client.post(path+'/videos',json=req).json();assert wait_video(merged_client,p,job['id'])['status']=='submission_unknown'
    merged_client.post(path+'/videos/'+job['id']+'/refresh');merged_client.post(path+'/videos',json=req)
    assert len(posts)==1


def test_historical_video_can_be_explicitly_selected(merged_client):
    p,cid=ready(merged_client);p=approve(merged_client,p)
    job=dict(id='old',projectId=p['id'],storyboardId='c',status='succeeded',time='1',requestFingerprint='old',videoUrl='/old.mp4')
    (main.DATA/'videos').mkdir();(main.DATA/'videos/old.mp4').write_bytes(b'old-video')
    with main.db() as c:c.execute('INSERT INTO video_jobs VALUES (?,?,?)',('old',p['id'],json.dumps(job)))
    assert merged_client.post(f"/api/projects/{p['id']}/storyboards/c/experience-video",json=dict(version=p['version'],jobId='old')).status_code==200


def test_reader_only_sees_confirmed_instances_and_groups_share_knowledge(merged_client):
    p,cid=ready(merged_client);before=main.get(p['id']);s=session(merged_client,p)
    assert len(s['people'])==2 and {v['characterId'] for v in s['people']}=={cid}
    assert main.get(p['id'])==before
    p['workspace']['entities']['knowledge:'+cid]['state']='stale';main.save(p,p['version'],'studio:test_stale')
    assert len(merged_client.get(f"/api/projects/{p['id']}/experience").json()['people'])==2


def test_dialogue_context_has_no_unbound_clues_drafts_or_other_char_history(merged_client,monkeypatch):
    p,cid=ready(merged_client);s=session(merged_client,p);seen=[]
    async def provider(ctx,message,history):
        seen.append((ctx,message,history));assert '不能透露的秘密' not in json.dumps(ctx,ensure_ascii=False)
        assert {c['id'] for c in ctx['clues']}=={'c'}
        return dict(answer='我当时略作停顿。',clueIds=['c'])
    monkeypatch.setattr(experience,'answer',provider)
    before=main.get(p['id']);r=send(merged_client,p,s,cid);assert r.status_code==200,r.text
    assert r.json()['status']=='completed' and r.json()['clueIds']==['c']
    assert main.get(p['id'])==before and len(seen)==1
    assert not merged_client.get(f"/api/projects/{p['id']}/experience/sessions/{s['session']['id']}").json()['media']


def test_dialogue_invalid_clue_ids_and_unknown_answers_do_not_unlock(merged_client,monkeypatch):
    p,cid=ready(merged_client);s=session(merged_client,p)
    async def bad(*args):return dict(answer='越界回答',clueIds=['not-known'])
    monkeypatch.setattr(experience,'answer',bad)
    assert send(merged_client,p,s,cid).json()['status']=='failed'
    async def unknown(*args):return dict(answer='模型可能擅自补全的信息',clueIds=[])
    monkeypatch.setattr(experience,'answer',unknown)
    r=send(merged_client,p,s,cid,'turn-2').json();assert r['answer']==experience.UNKNOWN and not r['clues']


def test_dialogue_dedup_and_explicit_collect_unlock_only_matching_board(merged_client,monkeypatch):
    p,cid=ready(merged_client);s=session(merged_client,p);calls=[]
    async def provider(*args):calls.append(True);return dict(answer='我略作停顿。',clueIds=['c'])
    monkeypatch.setattr(experience,'answer',provider)
    a=send(merged_client,p,s,cid).json();b=send(merged_client,p,s,cid).json();assert a==b and len(calls)==1
    base=f"/api/projects/{p['id']}/experience/sessions/{s['session']['id']}"
    assert merged_client.post(base+'/collect',json=dict(turnId=a['id'],clueId='not-known')).status_code==422
    r=merged_client.post(base+'/collect',json=dict(turnId=a['id'],clueId='c'));assert r.status_code==200,r.text
    assert r.json()['session']['collectedClueIds']==['c'] and [m['storyboardId'] for m in r.json()['media']]==['c']
    assert r.json()['collectedClues'][0]['id']=='c' and r.json()['collectedClues'][0]['name']=='折槛'
    assert not r.json()['media'][0]['videoUrl']
    assert merged_client.post(base+'/collect',json=dict(turnId=a['id'],clueId='c')).json()['session']['collectedClueIds']==['c']


def test_session_keeps_snapshot_across_drafts_and_revision_notices(merged_client):
    p,cid=ready(merged_client);s=session(merged_client,p);path=f"/api/projects/{p['id']}/experience/sessions/{s['session']['id']}"
    d=p['workspace']['entities']['character:'+cid]['draft'];d['name']='未发布姓名';p=draft(merged_client,p,'character',cid,d)
    assert merged_client.get(path).status_code==200
    p['workspace']['entities']['clue:c']['state']='stale';main.save(p,p['version'],'studio:test_stale')
    assert merged_client.get(path).status_code==200


def test_dialogue_failure_is_saved_and_retry_is_explicit(merged_client,monkeypatch):
    p,cid=ready(merged_client);s=session(merged_client,p);calls=[]
    async def fail(*args):calls.append(1);raise ValueError('模拟服务不可用')
    monkeypatch.setattr(experience,'answer',fail)
    r=send(merged_client,p,s,cid).json();assert r['status']=='failed' and r['text']=='你知道什么？'
    send(merged_client,p,s,cid);assert len(calls)==1
    send(merged_client,p,s,cid,'explicit-retry');assert len(calls)==2


def test_export_is_confirmed_only_and_excludes_reader_and_private_root(merged_client):
    p,cid=ready(merged_client);p['privateCredential']='DO-NOT-EXPORT';p=main.save(p,p['version'],'studio:test_private')
    d=p['workspace']['entities']['storyboard:c']['draft'];d['prompt']='未确认草稿不得导出';p=draft(merged_client,p,'storyboard','c',d)
    session(merged_client,p)
    path=f"/api/projects/{p['id']}/narrative/export"
    r=merged_client.get(path+'?format=json');assert r.status_code==200,r.text
    assert 'DO-NOT-EXPORT' not in r.text and '未确认草稿不得导出' not in r.text and 'experience_sessions' not in r.text
    assert r.json()['entities']['storyboard:c']['prompt']!='未确认草稿不得导出'
    z=zipfile.ZipFile(io.BytesIO(merged_client.get(path+'?format=zip').content))
    assert 'assets/painting/merged-reference.png' in z.namelist() and 'manifest.json' in z.namelist()
    assert merged_client.get(path+'?draft=false').status_code==422
    assert merged_client.get(path+f'?draft=false&reviewed=true&version={p["version"]-1}').status_code==409


def test_archive_restore_preserve_all_entities_and_data(merged_client):
    p,cid=ready(merged_client);before=p['workspace']['entities'];path=f"/api/projects/{p['id']}"
    r=merged_client.post(path+'/archive',json=dict(version=p['version']));assert r.status_code==200
    assert r.json()['workspace']['entities']==before
    assert p['id'] not in {r['id'] for r in merged_client.get('/api/projects').json()}
    assert p['id'] in {r['id'] for r in merged_client.get('/api/projects?archived=true').json()}
    restored=merged_client.post(path+'/restore',json=dict(version=r.json()['version']));assert restored.status_code==200
    assert restored.json()['workspace']['entities']==before and (main.DATA/'merged-reference.png').is_file()


def test_catalog_fields_use_material_draft_confirm_and_citation_validation(merged_client):
    p,cid=ready(merged_client);mat=p['workspace']['entities']['material:main']['draft'];mat['paintingInfo']=dict(name='通用画作',artist='作者未详')
    mat['historicalEvents']=[dict(id='event',title='有待核对的事件',evidence=dict(sourceId='missing',sourceVersion=1,quote='不存在'))]
    p=draft(merged_client,p,'material','main',mat)
    assert p['workspace']['entities']['material:main']['published'].get('paintingInfo') is None
    assert confirm(merged_client,p,'material','main',True).status_code==422
    catalog=merged_client.get(f"/api/projects/{p['id']}/catalog").json();assert catalog['painting']['name']=='通用画作'
    with main.db() as c:assert json.loads(c.execute('SELECT body FROM artwork_catalog WHERE project_id=?',(p['id'],)).fetchone()[0])['name']=='通用画作'


def test_directional_relations_reject_reversed_self_and_invalid_quotes(merged_client):
    p,cid=ready(merged_client);other=next(c['id'] for c in p['characters'] if c['id']!=cid)
    mat=p['workspace']['entities']['material:main']['published'];source=mat['sources'][0]
    relation=dict(fromId=cid,toId=cid,label='关系',sourceId=source['id'],sourceVersion=source['version'],quote=source['text'][:8])
    data=dict(name='方向关系',summary='关系',type='relationship',parentId='relationship',characterIds=[cid,other],plotIds=[],relations=[relation],units=[dict(id='ru',text='关系',kind='clue',category='fiction',references=[])])
    p=draft(merged_client,p,'clue','relation',data);assert confirm(merged_client,p,'clue','relation').status_code==422
    data['relations'][0]['toId']=other;data['relations'][0]['quote']='并不存在的原文'
    p=draft(merged_client,p,'clue','relation',data);assert confirm(merged_client,p,'clue','relation').status_code==422


def test_empty_project_has_honest_empty_experience_and_export(merged_client):
    p=merged_client.post('/api/projects',json=dict(title='空白画作')).json();path=f"/api/projects/{p['id']}"
    assert merged_client.get(path+'/experience').json()['people']==[]
    assert merged_client.post(path+'/experience/sessions').status_code==422
    assert merged_client.get(path+'/narrative/inspect').json()['issues']


def test_mysql_adapter_supports_all_new_tables_and_transaction_lock(monkeypatch):
    sql=[]
    class Cursor:
        description=None
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,q,args):sql.append((q,args))
        def fetchall(self):return []
    class Conn:
        def cursor(self):return Cursor()
        def begin(self):sql.append(('BEGIN',()))
    conn=object.__new__(storage.MySQLConnection);conn.conn=Conn();conn.write=False
    conn.execute('BEGIN IMMEDIATE');conn.execute('SELECT body FROM projects WHERE id=?',('p',))
    conn.execute('SELECT body FROM document_cache WHERE key=?',('hash',))
    assert sql[-1][0]=='SELECT body FROM document_cache WHERE `key`=%s'
    conn.execute('INSERT OR REPLACE INTO document_cache VALUES (?,?)',('hash','{}'))
    for table in ('tasks','studio_jobs','video_jobs','experience_sessions','experience_turns'):
        conn.execute('INSERT OR REPLACE INTO '+table+' VALUES (?,?,?)',('i','p','{}'))
    assert sql[1][0].endswith('FOR UPDATE')
    assert all('ON DUPLICATE KEY' in q for q,args in sql[3:])
    assert all('?' not in q for q,args in sql)


def test_migration_copies_every_persistent_table_and_rejects_nonempty_target(merged_client,tmp_path,monkeypatch):
    from scripts.migrate_sqlite_to_mysql import migrate,TABLES
    p,cid=ready(merged_client);session(merged_client,p)
    with main.db() as c:
        c.execute('INSERT INTO document_cache VALUES (?,?)',('cached-document',json.dumps(dict(text='文献缓存',pages=[1,2]))))
        c.execute('INSERT INTO video_jobs VALUES (?,?,?)',('historical-job',p['id'],json.dumps(dict(id='historical-job',projectId=p['id'],storyboardId='c',status='failed'))))
        schema=[row[0] for row in c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL")]
    target=tmp_path/'target.sqlite'
    with sqlite3.connect(target) as c:
        for statement in schema:c.execute(statement)
    monkeypatch.setattr(storage,'backend',lambda:'mysql')
    monkeypatch.setattr(storage,'connect',lambda data:sqlite3.connect(target))
    report=migrate(main.DATA/'projects.sqlite');assert set(report['counts'])==set(TABLES)
    assert report['counts']['video_jobs']==1 and report['counts']['experience_sessions']==1 and report['counts']['document_cache']==1
    assert migrate(main.DATA/'projects.sqlite',verify_only=True)['verified']
    with pytest.raises(ValueError,match='非空'):migrate(main.DATA/'projects.sqlite')
    with sqlite3.connect(target) as c:assert c.execute('SELECT COUNT(*) FROM video_jobs').fetchone()[0]==1


def test_restart_recovers_remote_ids_and_interrupts_chat_without_resubmission(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    with main.db() as c:
        for jid,status,remote in [('unknown','submitting',''),('known','running','old-remote')]:
            job=dict(id=jid,projectId='p',storyboardId='c',status=status,remoteId=remote,time='1')
            c.execute('INSERT INTO video_jobs VALUES (?,?,?)',(jid,'p',json.dumps(job)))
        turn=dict(id='pending-turn',projectId='p',sessionId='session',status='pending')
        c.execute('INSERT INTO experience_turns VALUES (?,?,?)',('pending-turn','p',json.dumps(turn)))
    calls=[];original=httpx.AsyncClient
    def handle(request):
        calls.append(request);assert request.method=='GET' and str(request.url).endswith('/tasks/old-remote')
        return httpx.Response(200,json={'output':{'task_status':'FAILED','message':'mock failure'}})
    monkeypatch.setenv('DASHSCOPE_API_KEY','fake')
    monkeypatch.setattr(video.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    with TestClient(main.app) as client:
        for _ in range(100):
            with main.db() as c:job=json.loads(c.execute('SELECT body FROM video_jobs WHERE id=?',('known',)).fetchone()[0])
            if job['status']=='failed':break
            time.sleep(.01)
        with main.db() as c:
            assert json.loads(c.execute('SELECT body FROM video_jobs WHERE id=?',('unknown',)).fetchone()[0])['status']=='submission_unknown'
            assert json.loads(c.execute('SELECT body FROM experience_turns WHERE id=?',('pending-turn',)).fetchone()[0])['status']=='interrupted'
    assert len(calls)==1 and job['remoteId']=='old-remote'


def test_complete_mock_video_dialogue_collect_play_export_flow(merged_client,monkeypatch):
    calls=mock_video_provider(monkeypatch);p,cid=ready(merged_client);p=approve(merged_client,p)
    path=f"/api/projects/{p['id']}"
    job=merged_client.post(path+'/videos',json=dict(version=p['version'],storyboardId='c')).json();job=wait_video(merged_client,p,job['id']);assert job['status']=='succeeded'
    p=merged_client.post(path+'/storyboards/c/experience-video',json=dict(version=p['version'],jobId=job['id'])).json()
    before=copy.deepcopy(main.get(p['id']));s=session(merged_client,p)
    async def provider(ctx,*args):return dict(answer='我在这一刻略作停顿。',clueIds=['c'])
    monkeypatch.setattr(experience,'answer',provider)
    turn=send(merged_client,p,s,cid).json()
    result=merged_client.post(path+f"/experience/sessions/{s['session']['id']}/collect",json=dict(turnId=turn['id'],clueId='c')).json()
    assert result['media'][0]['videoUrl']==job['videoUrl']
    assert merged_client.get(result['media'][0]['videoUrl']).status_code==200
    bundle=zipfile.ZipFile(io.BytesIO(merged_client.get(path+'/narrative/export?format=zip').content))
    assert 'assets/videos/'+job['id']+'.mp4' in bundle.namelist()
    assert main.get(p['id'])==before


def test_known_video_failure_has_explicit_idempotent_retry(merged_client,monkeypatch):
    original=httpx.AsyncClient;posts=[]
    def handle(request):
        if request.method=='POST':posts.append(request);return httpx.Response(400,json={'code':'InvalidParameter','message':'mock rejection'})
        raise AssertionError('rejected submissions do not poll')
    monkeypatch.setenv('DASHSCOPE_API_KEY','fake')
    monkeypatch.setattr(video.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    p,cid=ready(merged_client);p=approve(merged_client,p);path=f"/api/projects/{p['id']}/videos"
    old=merged_client.post(path,json=dict(version=p['version'],storyboardId='c')).json();old=wait_video(merged_client,p,old['id'])
    assert old['status']=='failed' and old['submissionKnownRejected']
    req=dict(version=p['version'],storyboardId='c',retryOf=old['id'],requestId='explicit-retry')
    new=merged_client.post(path,json=req).json();assert new['id']!=old['id']
    wait_video(merged_client,p,new['id']);assert merged_client.post(path,json=req).json()['id']==new['id']
    assert len(posts)==2


def test_unknown_video_submission_cannot_be_explicitly_retried(merged_client):
    p,cid=ready(merged_client);p=approve(merged_client,p)
    job=dict(id='uncertain',projectId=p['id'],storyboardId='c',status='submission_unknown',requestFingerprint=video.approval_hash(video.shot_inputs(p,'c',main.DATA)[0],p['workspace']['media']['c']['prompt']))
    with main.db() as c:c.execute('INSERT INTO video_jobs VALUES (?,?,?)',(job['id'],p['id'],json.dumps(job)))
    r=merged_client.post(f"/api/projects/{p['id']}/videos",json=dict(version=p['version'],storyboardId='c',retryOf='uncertain',requestId='try-again'))
    assert r.status_code==422


def test_download_retry_uses_existing_result_without_new_generation(merged_client,monkeypatch):
    original=httpx.AsyncClient;counts=dict(post=0,download=0)
    def handle(request):
        if request.method=='POST':counts['post']+=1;return httpx.Response(200,json={'output':{'task_id':'one-task'}})
        if '/tasks/' in str(request.url):return httpx.Response(200,json={'output':{'task_status':'SUCCEEDED','video_url':'https://mock.aliyuncs.com/result.mp4'}})
        counts['download']+=1
        return httpx.Response(503 if counts['download']==1 else 200,content=b'mock-media'*100)
    monkeypatch.setenv('DASHSCOPE_API_KEY','fake')
    monkeypatch.setattr(video.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    p,cid=ready(merged_client);p=approve(merged_client,p)
    job=merged_client.post(f"/api/projects/{p['id']}/videos",json=dict(version=p['version'],storyboardId='c')).json()
    assert wait_video(merged_client,p,job['id'])['status']=='download_failed'
    merged_client.post(f"/api/projects/{p['id']}/videos/{job['id']}/refresh")
    for _ in range(100):
        job=wait_video(merged_client,p,job['id'])
        if job['status']=='succeeded':break
        time.sleep(.01)
    assert job['status']=='succeeded' and counts==dict(post=1,download=2)


def test_knowledge_metadata_does_not_change_actual_video_request(merged_client):
    p,cid=ready(merged_client);before=video.shot_inputs(p,'c',main.DATA)[0]['scopeFingerprint']
    clue=p['workspace']['entities']['clue:c'];clue['published']['summary']='已确认的新版情节内容';clue['draft']=copy.deepcopy(clue['published'])
    # Emulate a completed re-review with the same wording in the final video prompt.
    p=main.save(p,p['version'],'studio:test_rereview')
    assert video.shot_inputs(p,'c',main.DATA)[0]['scopeFingerprint']==before


def test_late_dialogue_answer_finishes_on_its_pinned_session(merged_client,monkeypatch):
    p,cid=ready(merged_client);s=session(merged_client,p)
    async def provider(*args):
        latest=main.get(p['id']);latest['workspace']['entities']['clue:c']['state']='stale';main.save(latest,latest['version'],'studio:test_changed_during_chat')
        return dict(answer='过期回答',clueIds=['c'])
    monkeypatch.setattr(experience,'answer',provider)
    turn=send(merged_client,p,s,cid).json();assert turn['status']=='completed' and turn['answer']=='过期回答'


def test_explicit_sample_import_does_not_seed_identity_or_replace_existing_project(merged_client):
    p,cid=ready(merged_client);before=main.get(p['id'])
    assert {r['id'] for r in merged_client.get('/api/samples/artworks').json()}=={'zhekan','bunian','chongping'}
    new=merged_client.post('/api/samples/artworks/bunian');assert new.status_code==200,new.text
    assert new.json()['title']=='步辇图' and not new.json()['characters'] and not new.json()['annotations']
    assert new.json()['workspace']['entities']['material:main']['published'] is None
    assert main.get(p['id'])==before


def test_profile_answer_uses_confirmed_fields_and_cannot_unlock_any_clue(merged_client,monkeypatch):
    p,cid=ready(merged_client);s=session(merged_client,p)
    async def provider(*args):return dict(answer='模型不应添加的身份经历',clueIds=[],basis='profile')
    monkeypatch.setattr(experience,'answer',provider)
    turn=send(merged_client,p,s,cid,text='你是谁？').json()
    assert turn['status']=='completed' and turn['basis']=='profile' and not turn['clueIds']
    assert p['workspace']['entities']['character:'+cid]['published']['name'] in turn['answer']
    assert '模型不应添加' not in turn['answer']
