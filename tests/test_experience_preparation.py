import copy,json,time,threading
from pathlib import Path
from PIL import Image,ImageDraw
import pytest
from backend import main,cutouts,experience_preparation as prep
from test_review_units import merged_client,ready,edit
from test_merged_features import session

@pytest.fixture
def local_model(monkeypatch):
 calls=[]
 def segment(image,box,prompts=None):
  calls.append(copy.deepcopy(box));out=Image.new('RGBA',(40,80),(0,0,0,0));ImageDraw.Draw(out).ellipse((4,1,36,78),fill='#705f43');return out
 monkeypatch.setattr(cutouts,'segment',segment);return calls

def begin(c,p,sid=None,mode='refresh',rid='prepare'):
 r=c.post(f"/api/projects/{p['id']}/experience/preparations",json=dict(requestId=rid,sessionId=sid,mode=mode));assert r.status_code==200,r.text;return r.json()
def wait(c,p,job):
 for _ in range(200):
  value=c.get(f"/api/projects/{p['id']}/experience/preparations/{job['id']}").json()
  if value['state'] not in ('queued','running'):return value
  time.sleep(.01)
 raise AssertionError('local preparation did not finish')
def getview(c,p,job):return c.get(f"/api/projects/{p['id']}/experience/sessions/{job['sessionId']}").json()

def test_prepare_is_complete_persistent_and_never_changes_creation(merged_client,local_model):
 c=merged_client;p,_=ready(c);before=main.get(p['id']);job=wait(c,p,begin(c,p));assert job['state']=='ready',job
 value=getview(c,p,job);m=value['presentation'];assert len(m['cutouts'])==len(m['figures'])==2 and len(local_model)==2
 assert m['image']!=p['image'] and c.get(m['cutouts'][0]['url']).status_code==200
 assert main.get(p['id'])==before
 assert begin(c,p,rid='prepare')['sessionId']==job['sessionId']

def test_same_content_refresh_reuses_session_progress_and_successful_masks(merged_client,local_model):
 c=merged_client;p,_=ready(c);a=wait(c,p,begin(c,p));sid=a['sessionId']
 with main.db() as db:
  row=json.loads(db.execute('SELECT body FROM experience_sessions WHERE id=?',(sid,)).fetchone()[0]);row['collectedClueIds']=['c'];db.execute('UPDATE experience_sessions SET body=? WHERE id=?',(json.dumps(row),sid))
 b=wait(c,p,begin(c,p,sid,rid='refresh-again'));assert b['state']=='ready' and b['sessionId']==sid and len(local_model)==2
 assert getview(c,p,b)['session']['collectedClueIds']==['c']

def test_refresh_new_content_keeps_old_snapshot_and_does_not_repeat_segmentation(merged_client,local_model):
 c=merged_client;p,cid=ready(c);a=wait(c,p,begin(c,p));old=getview(c,p,a)
 r=edit(c,p,'/workspace/entities/character:'+cid+'/draft/summary','新的人工小传');assert r.status_code==200,r.text
 p=r.json();b=wait(c,p,begin(c,p,a['sessionId'],rid='changed'))
 assert b['sessionId']!=a['sessionId'] and len(local_model)==2
 assert getview(c,p,a)['people']==old['people'] and getview(c,p,a)['oldVersion']
 assert getview(c,p,b)['session']['collectedClueIds']==[]

def test_legacy_restore_uses_original_snapshot_not_latest_creation(merged_client,local_model):
 c=merged_client;p,cid=ready(c);old=session(c,p);sid=old['session']['id']
 r=edit(c,p,'/workspace/entities/character:'+cid+'/draft/name','新版人物称谓');assert r.status_code==200;r=r.json()
 job=wait(c,r,begin(c,r,sid,'resume'));v=getview(c,r,job)
 assert v['people']==old['people'] and v['session'].get('dialogueVersion',1)==1
 assert job['sessionId']==sid and v['oldVersion']

def test_partial_failure_stops_entry_and_retry_only_computes_missing(merged_client,local_model,monkeypatch):
 c=merged_client;p,_=ready(c);original=cutouts.segment;failed=True
 def model(image,box,prompts=None):
  if box['x']>.4 and failed:raise ValueError('第二个人物需要重试')
  return original(image,box,prompts)
 monkeypatch.setattr(cutouts,'segment',model)
 a=wait(c,p,begin(c,p));assert a['state']=='failed' and a['errors'][0]['message']=='第二个人物需要重试'
 assert getview(c,p,a)['presentation'] is None and len(local_model)==1
 failed=False;r=c.post(f"/api/projects/{p['id']}/experience/preparations/{a['id']}/retry");assert r.status_code==200
 b=wait(c,p,r.json());assert b['state']=='ready' and len(local_model)==2

def test_dedup_inflight_and_not_ready_dialogue_does_not_call_model(merged_client,local_model,monkeypatch):
 c=merged_client;p,cid=ready(c);entered=threading.Event();release=threading.Event();original=cutouts.segment
 def held(*args):entered.set();assert release.wait(5);return original(*args)
 monkeypatch.setattr(cutouts,'segment',held)
 try:
  a=begin(c,p);assert entered.wait(3);b=begin(c,p,rid='prepare');assert a['id']==b['id'] and a['sessionId']==b['sessionId']
  r=c.post(f"/api/projects/{p['id']}/experience/sessions/{a['sessionId']}/messages",json=dict(requestId='not-yet',characterId=cid,text='你好'));assert r.status_code==409
 finally:release.set()
 assert wait(c,p,a)['state']=='ready' and len(local_model)==2

def test_cancel_preserves_cache_and_explicit_retry_finishes(merged_client,local_model,monkeypatch):
 c=merged_client;p,_=ready(c);entered=threading.Event();release=threading.Event();original=cutouts.segment
 def held(*args):entered.set();assert release.wait(5);return original(*args)
 monkeypatch.setattr(cutouts,'segment',held)
 a=begin(c,p);assert entered.wait(3)
 r=c.post(f"/api/projects/{p['id']}/experience/preparations/{a['id']}/cancel");assert r.json()['state']=='cancelled';release.set()
 for _ in range(100):
  if not prep.active_count(main.DATA):break
  time.sleep(.01)
 assert prep.manifest(main.DATA,p['id'],a['sessionId']) is None
 r=c.post(f"/api/projects/{p['id']}/experience/preparations/{a['id']}/retry");assert wait(c,p,r.json())['state']=='ready'
 assert len(local_model)==2

def test_source_is_pinned_even_if_original_file_is_replaced(merged_client,local_model):
 c=merged_client;p,_=ready(c);a=wait(c,p,begin(c,p));v=getview(c,p,a);frozen=main.DATA/Path(v['image']).name;before=frozen.read_bytes()
 Image.new('RGB',(800,400),'red').save(main.DATA/Path(p['image']).name)
 assert getview(c,p,a)['image']==v['image'] and frozen.read_bytes()==before
 assert begin(c,p,a['sessionId'],'resume',rid='restore')['state']=='ready' and len(local_model)==2

def test_asset_get_uses_manifest_without_rebuilding_scene(merged_client,local_model,monkeypatch):
 c=merged_client;p,_=ready(c);a=wait(c,p,begin(c,p));row=getview(c,p,a)['presentation']['cutouts'][0]
 monkeypatch.setattr(cutouts,'source',lambda *args:(_ for _ in ()).throw(AssertionError('must not reread source')))
 r=c.get(row['url']);assert r.status_code==200 and 'immutable' in r.headers['cache-control']
 other=c.post('/api/projects',json=dict(title='其他项目')).json()
 assert c.get(row['url'].replace(p['id'],other['id'])).status_code==404

def test_restart_requires_explicit_resume_and_request_ids_are_checked(merged_client,local_model):
 c=merged_client;p,_=ready(c);a=wait(c,p,begin(c,p));path=main.DATA/'experience-preparations'/(a['id']+'.json');job=json.loads(path.read_text());job.update(state='running');prep.atomic(path,job)
 r=c.get(f"/api/projects/{p['id']}/experience/preparations/{a['id']}");assert r.json()['state']=='interrupted' and len(local_model)==2
 conflict=c.post(f"/api/projects/{p['id']}/experience/preparations",json=dict(requestId='prepare',mode='resume',sessionId=a['sessionId']));assert conflict.status_code==409
 r=c.post(f"/api/projects/{p['id']}/experience/preparations/{a['id']}/retry");assert wait(c,p,r.json())['state']=='ready' and len(local_model)==2

def test_prepared_media_does_not_pick_new_video_until_manual_refresh(merged_client,local_model,monkeypatch):
 from backend import video
 c=merged_client;p,_=ready(c);a=wait(c,p,begin(c,p));sid=a['sessionId']
 with main.db() as db:
  body=json.loads(db.execute('SELECT body FROM experience_sessions WHERE id=?',(sid,)).fetchone()[0]);body['collectedClueIds']=['c'];db.execute('UPDATE experience_sessions SET body=? WHERE id=?',(json.dumps(body),sid))
  job=dict(id='later-video',storyboardId='c',time='2030-01-01',videoUrl='/api/projects/'+p['id']+'/videos/later-video/file',storyboardSnapshot=p['workspace']['entities']['storyboard:c']['published']);db.execute('INSERT INTO video_jobs VALUES (?,?,?)',(job['id'],p['id'],json.dumps(job)))
 monkeypatch.setattr(video,'job_usable',lambda *args:True);monkeypatch.setattr(video,'job_current',lambda *args:True)
 assert not getview(c,p,a)['media'][0]['videoUrl']
 b=wait(c,p,begin(c,p,sid,rid='video-refresh'));assert b['sessionId']!=sid
 assert getview(c,p,b)['presentation']['mediaCatalog'][0]['videoUrl']==job['videoUrl']

def test_empty_project_does_not_start_preparation_or_create_a_session(merged_client,local_model):
 c=merged_client;p=c.post('/api/projects',json=dict(title='空体验验收')).json()
 r=c.post(f"/api/projects/{p['id']}/experience/preparations",json=dict(requestId='empty',mode='refresh'));assert r.status_code==422 and '人物档案' in r.text
 with main.db() as db:assert db.execute('SELECT COUNT(*) FROM experience_sessions WHERE project=?',(p['id'],)).fetchone()[0]==0
 assert not local_model

def test_one_ready_role_is_enough_while_all_visible_figures_are_prepared(merged_client,local_model):
 from backend import workspace as ws
 c=merged_client;p,_=ready(c);other=ws.record('character','unprepared',dict(name='旁观者',identity='画中人物',depictionScope='depicted'),True);p['workspace']['entities']['character:unprepared']=other
 mat=p['workspace']['entities']['material:main']
 for field in ('draft','published'):mat[field]['annotations'][1]['characterId']='unprepared'
 p['annotations'][1]['characterId']='unprepared';p=main.save(p,p['version'],'studio:fixture')
 a=wait(c,p,begin(c,p));v=getview(c,p,a)
 assert a['state']=='ready' and len(v['people'])==1 and len(v['figures'])==2 and len(v['presentation']['cutouts'])==2
 assert v['figures'][1]['canChat'] is False and len(local_model)==2


def test_independent_visitors_do_not_share_sessions_but_do_share_assets(merged_client,local_model):
 c=merged_client;p,_=ready(c);a=wait(c,p,begin(c,p,rid='viewer-a'));b=wait(c,p,begin(c,p,rid='viewer-b'))
 assert a['sessionId']!=b['sessionId'] and len(local_model)==2
 assert getview(c,p,a)['presentation']['cutouts']==getview(c,p,b)['presentation']['cutouts']
