import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from backend import main, video, video_budget as budget, video_generation as generation, video_prompt, media_previews
from test_merged_features import merged_client, ready, approve, wait_video
from test_media_previews import clone_shot


class LocalAdapter:
    def __init__(self,outcome='succeeded'):self.calls=0;self.outcome=outcome
    def profile(self):return dict(model='fixture-video-model',resolution='1080P',duration=5,audio=False,estimatedCny=4.8)
    def validate_configuration(self):pass
    def build_request(self,job,image_path):return dict(prompt=job['prompt'],settings=job['requestConfig'],image=hashlib.sha256(image_path.read_bytes()).hexdigest())
    async def submit(self,job,body):self.calls+=1;return 'remote-'+job['id']
    async def inspect(self,job):return dict(status=self.outcome,message='fixture result')
    async def download(self,job,result):return b'\x00\x00\x00\x18ftypmp42'+b'0'*200


@pytest.fixture
def production(merged_client,monkeypatch):
    adapter=LocalAdapter();monkeypatch.setitem(generation.ADAPTERS,'aihubmix',adapter)
    monkeypatch.setattr(budget,'_attempts',{})
    p,_=ready(merged_client)
    return merged_client,p,adapter


def insert_jobs(pid,count,status='succeeded',legacy=False,**extra):
    with main.db() as c:
        for i in range(count):
            j=dict(id=f'old-{i}',projectId=pid,storyboardId='past-'+str(i),title='fixture',kind='video',status=status,time='2026-01-01',budgetReservationCny=5,**extra)
            c.execute('INSERT INTO '+('media_preview_jobs' if legacy else 'video_jobs')+' VALUES (?,?,?)',(j['id'],pid,json.dumps(j)))


def test_default_wan_configuration_is_empty_and_never_reserves(production,monkeypatch):
    c,p,adapter=production;monkeypatch.setattr(generation,'ADAPTERS',{})
    info=c.get(f"/api/projects/{p['id']}/video-budget").json()
    assert info['model']['provider']=='aihubmix' and info['model']['model'] is None and not info['model']['ready']
    assert (info['limitCny'],info['limitCount'],info['remainingCny'],info['remainingCount'])==(100,20,100,20)
    preview=c.get(f"/api/projects/{p['id']}/storyboards/c/video-prompt").json()
    assert preview['audit']['checks'] and '图1' in preview['compiledPrompt']
    p=approve(c,p,text=preview['compiledPrompt'])
    response=c.post(f"/api/projects/{p['id']}/videos",json=dict(version=p['version'],storyboardId='c'))
    assert response.status_code==503 and adapter.calls==0
    assert c.get(f"/api/projects/{p['id']}/videos").json()['jobs']==[]
    old=c.post(f"/api/projects/{p['id']}/media-previews/quote",json=dict(version=p['version'],storyboardIds=['c'],kind='video'))
    assert old.status_code==503
    assert c.get(f"/api/projects/{p['id']}/video-budget").json()['remainingCount']==20


def test_atomic_last_slot_is_shared_by_distinct_shots(production):
    c,p,adapter=production;clone_shot(p,'second');p=main.save(p,p['version'],'studio:test_fixture')
    p=approve(c,p);p=approve(c,p,'second');insert_jobs(p['id'],19)
    def submit(sid):return c.post(f"/api/projects/{p['id']}/videos",json=dict(version=p['version'],storyboardId=sid))
    with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(submit,['c','second']))
    assert sorted(r.status_code for r in responses)==[200,422]
    successful=next(r.json() for r in responses if r.status_code==200);wait_video(c,p,successful['id'])
    info=c.get(f"/api/projects/{p['id']}/video-budget").json()
    assert info['usedCount']==20 and info['usedCny']==100 and info['remainingCount']==0 and adapter.calls==1
    replay=submit(successful['storyboardId']);assert replay.status_code==200 and replay.json()['id']==successful['id']
    assert adapter.calls==1


def test_legacy_and_new_video_endpoints_share_the_project_allowance(production):
    c,p,adapter=production;insert_jobs(p['id'],20,legacy=True);p=approve(c,p)
    result=c.post(f"/api/projects/{p['id']}/videos",json=dict(version=p['version'],storyboardId='c'))
    assert result.status_code==422 and adapter.calls==0
    q,_=ready(c)
    assert c.get(f"/api/projects/{q['id']}/video-budget").json()['remainingCount']==20


def test_known_failure_releases_and_unknown_submission_retains_allowance(production):
    c,p,adapter=production
    insert_jobs(p['id'],1,status='failed',submissionKnownRejected=True)
    info=c.get(f"/api/projects/{p['id']}/video-budget").json();assert info['remainingCny']==100
    with main.db() as db:db.execute('DELETE FROM video_jobs WHERE project=?',(p['id'],))
    insert_jobs(p['id'],1,status='submission_unknown')
    info=c.get(f"/api/projects/{p['id']}/video-budget").json()
    assert info['remainingCny']==95 and info['reservedCny']==5 and info['blocked']
    p=approve(c,p)
    assert c.post(f"/api/projects/{p['id']}/videos",json=dict(version=p['version'],storyboardId='c')).status_code==409
    assert adapter.calls==0
    with main.db() as db:db.execute('DELETE FROM video_jobs WHERE project=?',(p['id'],))
    adapter.outcome='failed'
    r=c.post(f"/api/projects/{p['id']}/videos",json=dict(version=p['version'],storyboardId='c'));wait_video(c,p,r.json()['id'])
    assert c.get(f"/api/projects/{p['id']}/video-budget").json()['remainingCny']==100


def test_download_failure_is_spent_without_recreating_generation(production,monkeypatch):
    c,p,adapter=production;p=approve(c,p)
    async def fail(*args):raise ValueError('fixture download failed')
    monkeypatch.setattr(adapter,'download',fail)
    r=c.post(f"/api/projects/{p['id']}/videos",json=dict(version=p['version'],storyboardId='c'));job=wait_video(c,p,r.json()['id'])
    assert job['status']=='download_failed'
    info=c.get(f"/api/projects/{p['id']}/video-budget").json();assert info['usedCny']==5 and info['reservedCny']==0
    async def content(*args):return b'0'*200
    monkeypatch.setattr(adapter,'download',content)
    c.post(f"/api/projects/{p['id']}/videos/{job['id']}/refresh")
    assert wait_video(c,p,job['id'])['status']=='succeeded' and adapter.calls==1


def test_researcher_grants_are_authenticated_scoped_and_idempotent(production,monkeypatch):
    c,p,_=production;monkeypatch.setenv('CREATION_RESEARCHER_PASSWORD_HASH',budget.password_hash('fixture-password'))
    path=f"/api/projects/{p['id']}/video-budget/grants"
    body=dict(password='incorrect',requestId='grant-1',additionalCount=3)
    assert c.post(path,json=body).status_code==403
    assert c.get(f"/api/projects/{p['id']}/video-budget").json()['limitCny']==100
    body['password']='fixture-password';a=c.post(path,json=body);assert a.status_code==200
    assert (a.json()['limitCny'],a.json()['limitCount'])==(115,23)
    assert c.post(path,json=body).json()['limitCny']==115
    assert c.post(path,json=dict(body,additionalCount=4)).status_code==409
    with main.db() as db:
        stored=db.execute('SELECT body FROM video_budget_accounts WHERE id=?',(p['id'],)).fetchone()[0]
        assert 'fixture-password' not in stored
    q,_=ready(c);assert c.get(f"/api/projects/{q['id']}/video-budget").json()['limitCny']==100


def test_researcher_attempts_are_throttled_and_negative_grants_rejected(production,monkeypatch):
    c,p,_=production;monkeypatch.setenv('CREATION_RESEARCHER_PASSWORD_HASH',budget.password_hash('fixture-password'))
    path=f"/api/projects/{p['id']}/video-budget/grants"
    assert c.post(path,json=dict(password='x',requestId='bad',additionalCount=-20)).status_code==422
    for i in range(5):assert c.post(path,json=dict(password='incorrect',requestId=str(i),additionalCount=1)).status_code==403
    assert c.post(path,json=dict(password='fixture-password',requestId='after-limit',additionalCount=1)).status_code==429


def test_director_brief_anchors_people_group_instances_style_and_motion(production):
    c,p,_=production;inputs,_=video.shot_inputs(p,'c',main.DATA)
    inputs['people'][0]['profile']['roleType']='group'
    text=video.compile_prompt(inputs)
    assert '图1' in text and '图2' in text and '共 2 个身影' in text
    assert '生成单镜头' in text and '无台词' in text and '无背景音乐' in text and '0–1秒' in text
    result=video_prompt.audit(inputs,text,5);assert not result['errors'] and not result['warnings']
    inputs['shot']['prompt']='请生成真人实拍的20秒视频'
    warnings=video_prompt.audit(inputs,video.compile_prompt(inputs),5)['warnings']
    assert any('时长' in v for v in warnings) and any('原画风格' in v for v in warnings)


def test_director_update_is_a_notice_and_does_not_overwrite_reviewed_text(production):
    c,p,_=production;p=approve(c,p,text='已保存并审核的导演稿')
    p['workspace']['entities']['storyboard:c']['published']['action']='缓慢颔首'
    p=main.save(p,p['version'],'studio:test_fixture')
    result=c.get(f"/api/projects/{p['id']}/storyboards/c/video-prompt").json()
    assert result['directorChanged'] and result['approved'] and result['prompt']=='已保存并审核的导演稿'


def test_unverified_or_overpriced_adapter_does_not_reserve(production,monkeypatch):
    c,p,adapter=production;p=approve(c,p)
    old=adapter.profile
    monkeypatch.setattr(adapter,'profile',lambda:dict(old(),estimatedCny=6))
    result=c.post(f"/api/projects/{p['id']}/videos",json=dict(version=p['version'],storyboardId='c'))
    assert result.status_code==422 and adapter.calls==0
    assert c.get(f"/api/projects/{p['id']}/video-budget").json()['remainingCny']==100


def test_audit_detects_real_framing_and_static_motion_conflicts(production):
    _,p,_=production;inputs,_=video.shot_inputs(p,'c',main.DATA)
    inputs['shot'].update(region=dict(x=.8,y=.1,w=.15,h=.6),prompt='人物不换位',action='保持原画姿态，仅有轻微衣纹变化',camera='固定或缓慢推近',endFrame='人物前行一小步')
    warnings=video_prompt.audit(inputs,video.compile_prompt(inputs),5)['warnings']
    assert any('取景框外' in w for w in warnings)
    assert any('备选方案' in w for w in warnings)
    assert any('起止动作' in w for w in warnings)
    assert any('外部讲解' in w for w in warnings)
