import copy,json,time,asyncio
import pytest
from backend import main,workspace as ws,review_units as ru,studio_agent,authoring_defaults
from test_merged_features import merged_client,ready
from test_completions import provider,defaults

def units(c,p):return c.get(f"/api/projects/{p['id']}/studio/units").json()
def confirm(c,p,uid,rid='confirm'):
    u=units(c,p)['units'][uid]
    return c.post(f"/api/projects/{p['id']}/studio/units/{uid}/confirm",json=dict(contentHash=u['contentHash'],dependencyHash=u['dependencyHash'],requestId=rid))
def edit(c,p,path,value,before=None,rid='save'):
    if before is None:
        from backend.task_runtime import value_at
        before=value_at(p,path)
    return c.patch(f"/api/projects/{p['id']}/studio/units/workspace",json=dict(version=p['version'],requestId=rid,changes=[dict(path=path,before=before,value=value)]))

def test_group_confirmation_covers_profile_knowledge_and_persona(merged_client):
 c=merged_client;p,cid=ready(c);uid='character:'+cid
 r=confirm(c,p,uid);assert r.status_code==200,r.text
 p=r.json();assert units(c,p)['units'][uid]['status']=='human'
 receipt=p['workspace']['reviewUnits']['members']
 assert all(k+':'+cid in receipt for k in ('character','knowledge','persona'))
 assert confirm(c,p,uid).status_code==200
 assert p['workspace']['entities']['persona:'+cid]['refs']==main.get(p['id'])['workspace']['entities']['persona:'+cid]['refs']

def test_ai_content_is_available_without_human_review(merged_client):
 c=merged_client;p,cid=ready(c);r=p['workspace']['entities']['persona:'+cid];r['activation']=dict(method='auto');p=main.save(p,p['version'],'studio:fixture')
 response=c.post(f"/api/projects/{p['id']}/experience/sessions");assert response.status_code==200,response.text
 assert units(c,p)['units']['character:'+cid]['status']!='human'

def test_manual_edit_preserves_human_but_ai_partial_edit_does_not_promote(merged_client):
 c=merged_client;p,cid=ready(c);p=confirm(c,p,'character:'+cid).json()
 path='/workspace/entities/character:'+cid+'/draft/summary'
 r=edit(c,p,path,'人工修改小传');assert r.status_code==200,r.text
 p=r.json();assert units(c,p)['units']['character:'+cid]['status']=='human'
 row=main.get(p['id']);old=copy.deepcopy(row);row['workspace']['entities']['persona:'+cid]['draft']['prompt']='新AI人设'
 ru.make_available(row);row=main.save(row,row['version'],'studio:generation:persona')
 assert units(c,row)['units']['character:'+cid]['status']=='AI'
 r=edit(c,row,path,'手动局部改字',rid='next');assert r.status_code==200,r.text
 assert units(c,r.json())['units']['character:'+cid]['status']=='AI'

def test_autosave_merges_different_fields_and_rejects_same_field_conflicts(merged_client):
 c=merged_client;p,cid=ready(c);base=p
 path='/workspace/entities/character:'+cid+'/draft/summary'
 r=edit(c,p,path,'先保存');assert r.status_code==200,r.text
 other=edit(c,base,'/workspace/entities/character:'+cid+'/draft/biography','另一处编辑',rid='other');assert other.status_code==200,other.text
 conflict=edit(c,base,path,'冲突编辑',rid='conflict');assert conflict.status_code==409
 assert main.get(p['id'])['workspace']['entities']['character:'+cid]['draft']['summary']=='先保存'
 replay=edit(c,base,path,'先保存');assert replay.status_code==200

def test_invalid_input_is_saved_and_only_marks_its_own_unit_incomplete(merged_client):
 c=merged_client;p,cid=ready(c);path='/workspace/entities/character:'+cid+'/draft/name'
 r=edit(c,p,path,'');assert r.status_code==200,r.text
 p=r.json();assert p['workspace']['entities']['character:'+cid]['draft']['name']==''
 assert units(c,p)['units']['character:'+cid]['status']=='incomplete'
 assert units(c,p)['units']['storyboard:c']['ready']


def test_confirm_changed_content_is_rejected_without_partial_receipts(merged_client):
 c=merged_client;p,cid=ready(c);uid='character:'+cid;u=units(c,p)['units'][uid]
 r=edit(c,p,'/workspace/entities/character:'+cid+'/draft/summary','改动');assert r.status_code==200,r.text
 res=c.post(f"/api/projects/{p['id']}/studio/units/{uid}/confirm",json=dict(contentHash=u['contentHash'],dependencyHash=u['dependencyHash'],requestId='old'))
 assert res.status_code==409 and 'old' not in main.get(p['id'])['workspace']['reviewUnits']['receipts']


def test_unrelated_edits_and_identical_ai_outputs_do_not_clear_review(merged_client):
 c=merged_client;p,cid=ready(c);p=confirm(c,p,'storyboard:c').json();before=main.get(p['id'])
 p=main.get(p['id']);p['title']='项目改名';p=main.save(p,p['version'],'studio:rename')
 u=units(c,p)['units']['storyboard:c'];assert u['status']=='human' and not u['outdated']
 p=main.save(main.get(p['id']),p['version'],'studio:generation:storyboard')
 assert units(c,p)['units']['storyboard:c']['status']=='human'
 assert main.get(p['id'])['workspace']['entities']['storyboard:c']['refs']==before['workspace']['entities']['storyboard:c']['refs']


def test_outdated_tracks_related_content_and_confirmation_keeps_original_bases(merged_client):
 c=merged_client;p,cid=ready(c);p=confirm(c,p,'storyboard:c').json();refs=copy.deepcopy(p['workspace']['entities']['storyboard:c']['refs'])
 path='/workspace/entities/clue:c/draft/summary';r=edit(c,p,path,'新的相关线索内容');assert r.status_code==200,r.text
 p=r.json();assert units(c,p)['units']['storyboard:c']['outdated']
 p=confirm(c,p,'storyboard:c',rid='checked').json();assert not units(c,p)['units']['storyboard:c']['outdated']
 assert main.get(p['id'])['workspace']['entities']['storyboard:c']['refs']==refs


def test_editor_read_is_compact_readonly_and_workflow_order_has_no_confirm_gate(merged_client,monkeypatch):
 c=merged_client;p,cid=ready(c);before=main.get(p['id']);r=c.get(f"/api/projects/{p['id']}/studio/editor");assert r.status_code==200
 assert 'revisionArchive' not in r.json()['workspace'] and all('history' not in v for v in r.json()['workspace']['entities'].values())
 report=units(c,p);assert [v['id'] for v in report['pages']]==ru.ORDER
 assert main.get(p['id'])==before


def test_step_batch_does_not_generate_upstream_and_replays_request(merged_client,monkeypatch):
 c=merged_client;p,cid=ready(c);calls=[]
 async def model(task,ctx):calls.append(task);return await provider(task,ctx)
 monkeypatch.setattr(studio_agent,'run',model);monkeypatch.setattr(authoring_defaults,'intent',defaults)
 body=dict(version=p['version'],requestId='batch',page='storyboards')
 r=c.post(f"/api/projects/{p['id']}/studio/generation-batches",json=body);assert r.status_code==200,r.text
 j=r.json()
 for _ in range(500):
  j=c.get(f"/api/projects/{p['id']}/studio/generation-batches/{j['id']}").json()
  if j['state'] not in ('queued','running'):break
  time.sleep(.01)
 assert j['state']=='completed',j
 assert not set(calls)&{'plots','culture','relationship','persona','knowledge'}
 replay=c.post(f"/api/projects/{p['id']}/studio/generation-batches",json=body);assert replay.status_code==200 and replay.json()['id']==j['id']

def test_legacy_recovery_only_credits_the_clicked_person(merged_client):
 c=merged_client;p,cid=ready(c);a=copy.deepcopy(p['annotations'][0]);b=copy.deepcopy(a);b['id']='other';a.update(identityConfirmed=True,needsReview=False);b.update(identityConfirmed=True,needsReview=False)
 p['annotations']=[a,b];p['workspace']['entities']['material:main']['draft']['annotations']=[a,b]
 ru.recover_reviews(p,[('confirm_person',dict(annotations=[a,b]),dict(annotationId=a['id']))])
 assert ru.meta(p)['members']['visual:'+a['id']]['origin']=='human'
 assert 'visual:other' not in ru.meta(p)['members']

def test_no_clues_is_not_a_character_review_or_chat_gate(merged_client):
 c=merged_client;p,cid=ready(c);k=p['workspace']['entities']['knowledge:'+cid];k['draft']=dict(characterId=cid,clueIds=[],reasons={},profileOnly=True)
 persona=p['workspace']['entities']['persona:'+cid];persona['draft']['knowledgeTiming']=[]
 ru.make_available(p);p=main.save(p,p['version'],'studio:generation:fixture')
 assert units(c,p)['units']['character:'+cid]['ready']
 assert c.post(f"/api/projects/{p['id']}/experience/sessions").status_code==200

def test_busy_generation_rejection_does_not_save_operational_inputs(merged_client):
 c=merged_client;p,cid=ready(c);old=main.get(p['id'])
 with main.db() as db:db.execute('INSERT INTO studio_jobs VALUES (?,?,?)',('busy',p['id'],json.dumps(dict(id='busy',state='running',family='generation'))))
 r=c.post(f"/api/projects/{p['id']}/studio/generation-batches",json=dict(version=p['version'],requestId='different',page='characters'))
 assert r.status_code==409 and main.get(p['id'])==old

def test_shared_clue_review_and_unrelated_renaming(merged_client):
 c=merged_client;p,cid=ready(c);p=confirm(c,p,'clues:main').json()
 receipts=p['workspace']['reviewUnits']['members'];assert any(k.startswith('clue:') and v.get('reviewedHash') for k,v in receipts.items())
 p=confirm(c,p,'storyboard:c',rid='shot').json()
 r=edit(c,p,'/workspace/entities/clue:c/draft/name','只改线索名称');assert r.status_code==200,r.text
 assert not units(c,r.json())['units']['storyboard:c']['outdated']

def test_compact_poll_keeps_history_on_server(merged_client):
 c=merged_client;p,cid=ready(c)
 r=c.get(f"/api/projects/{p['id']}/studio/poll?version=0&compact=true")
 assert r.status_code==200 and 'revisionArchive' not in r.json()['project']['workspace']
 assert main.get(p['id'])['workspace']['revisionArchive']

def test_visual_confirmation_covers_observation_with_no_second_receipt(merged_client):
 c=merged_client;p,cid=ready(c);aid=p['annotations'][0]['id'];r=confirm(c,p,'visual:'+aid)
 assert r.status_code==200,r.text
 p=r.json();assert units(c,p)['units']['visual:'+aid]['status']=='human'
 observations=p['workspace']['entities']['material:main']['draft'].get('observations',[])
 if observations:assert p['workspace']['reviewUnits']['members']['observation:'+aid]['reviewedHash']

def test_review_change_tracking_does_not_run_validators(merged_client,monkeypatch):
 c=merged_client;p,cid=ready(c);other=copy.deepcopy(p)
 def forbidden(*args):raise AssertionError('Tracking hashes must not revalidate every group')
 monkeypatch.setattr(ru,'problems',forbidden);ru.changed_members(p,other,'AI')
 assert not ru.meta(other)['members']

def test_next_action_uses_available_dependency_even_with_optional_review(merged_client):
 c=merged_client;p,cid=ready(c);report=units(c,p)
 chars=next(v for v in report['pages'] if v['id']=='characters')
 assert chars['nextAction']['page']=='storyboards'
 assert all(v['canGenerate'] for v in report['pages'][1:5])

def test_member_human_receipt_protects_a_partial_outline_from_rewrite(merged_client,monkeypatch):
 from backend import completions
 c=merged_client;p,cid=ready(c)
 key=next(k for k,r in p['workspace']['entities'].items() if r['kind']=='plot');row=p['workspace']['entities'][key]
 original=copy.deepcopy(row['draft']);ru.meta(p)['members'][key]=dict(origin='human',hash=ru.fingerprint(original),reviewedHash=ru.fingerprint(original))
 async def replacement(task,ctx):return dict(plots=[dict(title='AI替代标题',goal='新的目标',body='新的内容',connection='',characterIds=[cid],clues=[dict(name='AI新线索',content='演绎情节')])])
 monkeypatch.setattr(studio_agent,'run',replacement)
 result,notes=asyncio.run(completions.stage_result(p,'rewrite',dict(id='replacement',family='generation',mode='regenerate',currentUnit=key),lambda:main.DATA,lambda key:None,lambda *args:None))
 assert result['workspace']['entities'][key]['draft']==original
 assert result['workspace']['generationSuggestions'][-1]['status']=='pending'

def test_observation_edits_autosave_after_group_confirmation(merged_client):
 c=merged_client;p,cid=ready(c);aid=p['annotations'][0]['id']
 p=confirm(c,p,'visual:'+aid).json();rows=p['workspace']['entities']['material:main']['draft'].get('observations',[])
 if not rows:return
 r=edit(c,p,'/workspace/entities/material:main/draft/observations/@'+rows[0]['id']+'/description','人工观察调整')
 assert r.status_code==200,r.text
 assert units(c,r.json())['units']['visual:'+aid]['status']=='human'

def test_incomplete_creation_form_is_preserved_without_changing_review_status(merged_client):
 c=merged_client;p,cid=ready(c);p=confirm(c,p,'character:'+cid).json()
 r=edit(c,p,'/authoringDrafts',dict(sourceForm=dict(title='未写完的来源',text='')),rid='buffer');assert r.status_code==200,r.text
 assert main.get(p['id'])['authoringDrafts']['sourceForm']['title']=='未写完的来源'
 assert units(c,r.json())['units']['character:'+cid]['status']=='human'

def test_incomplete_geometry_does_not_corrupt_saved_project_and_can_be_corrected(merged_client):
 c=merged_client;p,cid=ready(c);a=p['annotations'][0];path='/annotations/@'+a['id']+'/w'
 r=edit(c,p,path,0);assert r.status_code==422
 assert c.get(f"/api/projects/{p['id']}/studio/editor").status_code==200
 r=edit(c,p,path,.2,rid='corrected');assert r.status_code==200,r.text
 assert main.get(p['id'])['annotations'][0]['w']==.2

def test_first_library_generation_uses_raw_inputs_not_prior_publication(merged_client):
 c=merged_client;p=c.post('/api/projects',json=dict(title='首次整理')).json();p['image']='/api/images/picture.jpg';p['documents']=[dict(id='doc',filename='paper.pdf',format='pdf')]
 ws.ensure(p);p['workspace']['entities']['material:main']['draft']['image']=p['image']
 page=next(v for v in ru.workflow(p)['pages'] if v['id']=='library');assert page['canGenerate']
 p=c.post('/api/projects',json=dict(title='空资料')).json()
 r=c.post(f"/api/projects/{p['id']}/studio/generation-batches",json=dict(version=p['version'],requestId='missing',page='library'))
 assert r.status_code==422 and '请上传' in r.text
 with main.db() as db:assert not db.execute('SELECT id FROM studio_jobs WHERE project=?',(p['id'],)).fetchall()

def test_manual_source_change_marks_library_for_explicit_restructure(merged_client):
 c=merged_client;p,cid=ready(c);source=p['sources'][0]
 r=edit(c,p,'/sources/@'+source['id']+'/text',source['text']+' 新补充资料');assert r.status_code==200,r.text
 assert main.get(p['id'])['workspace']['entities']['material:main']['needsStructuredRefresh']

def test_persona_queue_locks_only_the_current_role_result(merged_client,monkeypatch):
 import threading
 c=merged_client;p,cid=ready(c);r=p['workspace']['entities']['persona:'+cid];r.update(published=None,state='draft');r['draft']['prompt']='';p=main.save(p,p['version'],'studio:fixture')
 started=threading.Event();release=threading.Event()
 async def slow(task,ctx):
  if task=='persona':
   started.set()
   while not release.is_set():await asyncio.sleep(.005)
  return await provider(task,ctx)
 monkeypatch.setattr(studio_agent,'run',slow)
 j=c.post(f"/api/projects/{p['id']}/studio/generation-batches",json=dict(version=p['version'],requestId='role-queue',page='characters')).json()
 try:
  assert started.wait(3)
  live=c.get(f"/api/projects/{p['id']}/studio/generation-batches/{j['id']}").json()
  assert live['writeSet']==['/workspace/entities/persona:'+cid+'/draft']
 finally:release.set()
 for _ in range(400):
  live=c.get(f"/api/projects/{p['id']}/studio/generation-batches/{j['id']}").json()
  if live['state'] not in ('running','queued'):break
  time.sleep(.01)
 assert live['state']=='completed',live

def test_legacy_apply_is_not_proof_of_human_review(merged_client):
 c=merged_client;p,cid=ready(c);r=p['workspace']['entities']['persona:'+cid];r['activation']=dict(method='manual');r['generationRefs']=[dict(key='character:'+cid,revision=1)]
 assert ru.inferred_origin(p,'persona:'+cid,r['draft'])=='AI'
 r.pop('generationRefs');r.pop('regenerated',None);r.pop('autoValues',None)
 assert ru.inferred_origin(p,'persona:'+cid,r['draft'])=='unknown'

def test_editing_one_unknown_legacy_field_does_not_fabricate_human_receipts(merged_client):
 c=merged_client;p,cid=ready(c);key='character:'+cid;r=p['workspace']['entities'][key]
 for field in ('activation','generationRefs','autoValues','regenerated','suggestion'):r.pop(field,None)
 ru.meta(p)['legacyAuditRecovered']=True;p=main.save(p,p['version'],'studio:fixture')
 response=edit(c,p,'/workspace/entities/'+key+'/draft/summary','只改了一句旧内容');assert response.status_code==200,response.text
 stored=main.get(p['id'])['workspace']['reviewUnits']['members'][key]
 assert stored['origin']=='unknown' and not stored.get('reviewedHash')

def test_availability_only_autosave_keeps_existing_ai_library_origin(merged_client):
 from backend import structured
 c=merged_client;p,cid=ready(c);mat=p['workspace']['entities']['material:main'];mat['draft']['structured']=structured.preview(p,main.db);ru.make_available(p)
 mat=p['workspace']['entities']['material:main'];mat['activation']=dict(method='auto');mat['draft']['sources'][0]['confirmed']=False;mat['published']['sources'][0]['confirmed']=False
 p=main.save(p,p['version'],'studio:fixture');before=units(c,p)['units']['library:main'];assert before['status']=='AI'
 response=c.patch(f"/api/projects/{p['id']}/studio/units/workspace",json=dict(version=p['version'],requestId='availability-only',changes=[]));assert response.status_code==200,response.text
 current=units(c,response.json())['units']['library:main']
 assert current['status']=='AI' and current['contentHash']==before['contentHash'] and not current['outdated']
