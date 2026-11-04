import copy,json,sqlite3
from pathlib import Path
import pytest
from backend import main,snapshot_store as snapshots,read_models
from test_review_units import merged_client,ready,edit

def test_bootstrap_and_idle_poll_never_read_canonical_project_after_warmup(merged_client,monkeypatch):
 c=merged_client;p,_=ready(c);url='/api/studio/bootstrap?projectId='+p['id'];initial=c.get(url);assert initial.status_code==200,initial.text
 def forbidden(*a,**kw):raise AssertionError('warm startup read a full project/history')
 with monkeypatch.context() as patch:
  patch.setattr(main,'get',forbidden)
  for endpoint in (url,'/api/projects',f"/api/projects/{p['id']}/studio/editor",f"/api/projects/{p['id']}/studio/units",f"/api/projects/{p['id']}/studio/poll?version={p['version']}&compact=true"):
   r=c.get(endpoint);assert r.status_code==200,r.text
 result=initial.json();assert result['project']['version']==p['version'] and result['checks']['pages']
 assert 'revisionArchive' not in result['project']['workspace'] and all('basisWarnings' not in v for v in result['project']['workspace']['entities'].values())

def test_save_updates_projection_in_the_same_transaction_without_storing_display_warnings(merged_client):
 c=merged_client;p,cid=ready(c);r=edit(c,p,'/workspace/entities/character:'+cid+'/draft/summary','新的手写内容');assert r.status_code==200,r.text
 boot=c.get('/api/studio/bootstrap?projectId='+p['id']).json();assert boot['project']['version']==r.json()['version']
 assert boot['project']['workspace']['entities']['character:'+cid]['draft']['summary']=='新的手写内容'
 with main.db() as db:stored=json.loads(db.execute('SELECT body FROM projects WHERE id=?',(p['id'],)).fetchone()[0])
 assert all('basisWarnings' not in v for v in stored['workspace']['entities'].values())
 assert main.get(p['id'])['workspace']['revisionArchive']

def test_external_same_version_repair_invalidates_cached_projection(merged_client):
 c=merged_client;p,_=ready(c);assert c.get('/api/studio/bootstrap?projectId='+p['id']).status_code==200
 p['title']='外部修复画名'
 with main.db() as db:db.execute('UPDATE projects SET body=? WHERE id=?',(json.dumps(p,ensure_ascii=False),p['id']))
 assert c.get('/api/studio/bootstrap?projectId='+p['id']).json()['project']['title']=='外部修复画名'

def test_check_cache_invalidates_when_an_actual_image_changes(merged_client,monkeypatch):
 c=merged_client;p,_=ready(c);url=f"/api/projects/{p['id']}/studio/units";assert c.get(url).status_code==200
 original=main.app.state.review_report;calls=[]
 def counted(value):calls.append(value['id']);return original(value)
 monkeypatch.setattr(main.app.state,'review_report',counted)
 assert c.get(url).status_code==200 and not calls
 image=main.DATA/Path(p['image']).name;image.write_bytes(image.read_bytes()+b'changed')
 assert c.get(url).status_code==200 and calls==[p['id']]

def test_snapshots_are_exact_deduplicated_and_read_through_existing_event_queries(merged_client):
 c=merged_client;p,cid=ready(c)
 with main.db() as db:
  raw=json.dumps(dict(text='逐字原文'*10000),ensure_ascii=False);a=snapshots.pack(raw,db);b=snapshots.pack(raw,db)
  assert a==b and snapshots.decode(a,db)==raw
  db.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)',('codec-check',p['id'],'2000','test',a,b,'{}'))
  assert db.execute('SELECT before,after FROM events WHERE id=?',('codec-check',)).fetchone()==(raw,raw)
  # Scalar user input matching the reserved prefix is not an audit field.
  assert db.execute('SELECT ? AS title',(a,)).fetchone()[0]==a
 with sqlite3.connect(main.DATA/'projects.sqlite') as db:
  assert db.execute('SELECT before FROM events WHERE id=?',('codec-check',)).fetchone()[0]==a
  assert db.execute('SELECT COUNT(*) FROM content_snapshots WHERE id=?',(a[len(snapshots.PREFIX):],)).fetchone()[0]==1
 assert snapshots.decode('{}',None)=='{}'

def test_corrupt_or_missing_snapshot_fails_closed(merged_client):
 c=merged_client;p,_=ready(c)
 with main.db() as db:
  with pytest.raises(ValueError):snapshots.decode(snapshots.PREFIX+'0'*64,db)
  token=snapshots.pack('A'*10000,db);db.execute('UPDATE content_snapshots SET body=? WHERE id=?',('broken',token[len(snapshots.PREFIX):]))
  with pytest.raises(Exception):snapshots.decode(token,db)

def test_compaction_preserves_all_history_sessions_chats_and_progress(merged_client,tmp_path):
 from scripts.compact_storage import compact
 c=merged_client;p,cid=ready(c)
 session=c.post(f"/api/projects/{p['id']}/experience/sessions").json()['session']
 with main.db() as db:
  row=json.loads(db.execute('SELECT body FROM experience_sessions WHERE id=?',(session['id'],)).fetchone()[0]);row['collectedClueIds']=['c'];db.execute('UPDATE experience_sessions SET body=? WHERE id=?',(json.dumps(row),session['id']))
 source=main.DATA/'projects.sqlite';dest=tmp_path/'optimized.sqlite';report=compact(source,dest,progress=lambda *a:None)
 assert report['losslessAudit'] and report['integrity']=='ok'
 with sqlite3.connect(source) as a,sqlite3.connect(dest) as b:
  assert a.execute('SELECT * FROM experience_sessions').fetchall()==b.execute('SELECT * FROM experience_sessions').fetchall()
  assert a.execute('SELECT COUNT(*) FROM events').fetchone()==b.execute('SELECT COUNT(*) FROM events').fetchone()
  for eid,before,after in a.execute('SELECT id,before,after FROM events'):
   new=b.execute('SELECT before,after FROM events WHERE id=?',(eid,)).fetchone()
   assert snapshots.decode(before,a)==snapshots.decode(new[0],b) and snapshots.decode(after,a)==snapshots.decode(new[1],b)
  old=json.loads(a.execute('SELECT body FROM projects WHERE id=?',(p['id'],)).fetchone()[0]);new=json.loads(b.execute('SELECT body FROM projects WHERE id=?',(p['id'],)).fetchone()[0]);assert read_models.clean_project(old)==new
 with pytest.raises(ValueError):compact(source,source)
 with pytest.raises(ValueError):compact(source,dest)

def test_plain_json_rollback_copy_preserves_new_progress(merged_client,tmp_path):
 from scripts.compact_storage import inflate
 c=merged_client;p,_=ready(c);before=main.get(p['id']);target=tmp_path/'plain.sqlite';inflate(main.DATA/'projects.sqlite',target)
 with sqlite3.connect(target) as db:
  for a,b in db.execute('SELECT before,after FROM events'):assert not snapshots.is_reference(a) and not snapshots.is_reference(b);json.loads(a);json.loads(b)
  assert json.loads(db.execute('SELECT body FROM projects WHERE id=?',(p['id'],)).fetchone()[0])==read_models.clean_project(before)
 with pytest.raises(ValueError):inflate(target,target)
