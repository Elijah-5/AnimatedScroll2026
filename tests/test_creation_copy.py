import copy,io,json,zipfile
from pathlib import Path
import pytest
from backend import main,creation_copy,experience
from test_review_units import merged_client,ready,edit
from test_persona_dialogue import new_session,send

def download(c,p):
    r=c.get(f"/api/projects/{p['id']}/creation-copy?version={p['version']}");assert r.status_code==200,r.text
    return r.content
def upload(c,raw):return c.post('/api/creation-copies/restore',files={'file':('working-copy.zip',raw,'application/zip')})
def database():
    with main.db() as c:return {t:c.execute('SELECT * FROM '+t).fetchall() for t in ('projects','events','experience_sessions','experience_turns')}

def test_download_contains_current_drafts_assets_and_no_reader_records_or_new_backups(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);new_session(c,p)
    p=edit(c,p,'/workspace/entities/character:'+cid+'/draft/summary','未单独人工确认的工作内容').json()
    original=database();paths=set(main.DATA.rglob('*'));created=[];build=creation_copy.build
    def tracked(*args):
        path=build(*args);created.append(path);return path
    monkeypatch.setattr(creation_copy,'build',tracked);raw=download(c,p)
    assert database()==original and set(main.DATA.rglob('*'))==paths and all(not v.exists() for v in created)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        manifest=json.loads(z.read('manifest.json'));project=json.loads(z.read('project.json'))
        assert manifest['includesAudienceRecords'] is False and not any('experience' in n for n in z.namelist())
        assert project['workspace']['entities']['character:'+cid]['draft']['summary']=='未单独人工确认的工作内容'
        assert manifest['files'] and all(not n.startswith('.') for n in z.namelist())

def test_restore_independent_project_keeps_original_and_experience_progress(merged_client):
    c=merged_client;p,cid=ready(c);new_session(c,p);raw=download(c,p);old=database()
    r=upload(c,raw);assert r.status_code==200,r.text
    pid=r.json()['projectId'];assert pid!=p['id'];q=main.get(pid,decorate=False)
    assert q['workspace']['entities']['character:'+cid]['draft']==main.get(p['id'],decorate=False)['workspace']['entities']['character:'+cid]['draft']
    assert q['image']!=p['image'] and c.get(q['image']).status_code==200
    fresh=database();assert fresh['experience_sessions']==old['experience_sessions'] and fresh['experience_turns']==old['experience_turns']
    assert dict(fresh['projects'])[p['id']]==dict(old['projects'])[p['id']]
    assert main.get(p['id'])['version']==p['version']

def test_download_stale_version_rejected_without_writes(merged_client):
    c=merged_client;p,_=ready(c);before=database()
    assert c.get(f"/api/projects/{p['id']}/creation-copy?version=0").status_code==409
    assert database()==before

def test_missing_optional_file_is_reported_and_does_not_block_copy(merged_client):
    c=merged_client;p,_=ready(c);p['documents']=[dict(id='missing',filename='missing.pdf',title='缺失资料')]
    p=main.save(p,p['version'],'studio:fixture');raw=download(c,p)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:assert json.loads(z.read('manifest.json'))['missingAssets']==[dict(name='missing.pdf',reason='原文件缺失')]
    assert upload(c,raw).json()['missingAssets']

@pytest.mark.parametrize('mode',['corrupt','traversal','duplicate'])
def test_invalid_bundle_never_writes_project_or_assets(merged_client,mode):
    c=merged_client;p,_=ready(c);raw=download(c,p);out=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source,zipfile.ZipFile(out,'w') as target:
        for name in source.namelist():target.writestr(name,b'broken' if name=='project.json' and mode=='corrupt' else source.read(name))
        if mode=='traversal':target.writestr('../outside.txt','bad')
        if mode=='duplicate':
            with pytest.warns(UserWarning):target.writestr('project.json','duplicate')
    before=database();paths=set(main.DATA.rglob('*'));r=upload(c,out.getvalue());assert r.status_code==422,r.text
    assert database()==before and paths==set(main.DATA.rglob('*'))

def test_failed_restore_rolls_back_files_and_project(merged_client,monkeypatch):
    c=merged_client;p,_=ready(c);raw=download(c,p);before=database();paths=set(main.DATA.rglob('*'))
    from backend import structured
    def fail(*args):raise RuntimeError('transaction fixture')
    monkeypatch.setattr(structured,'synchronize',fail)
    with pytest.raises(RuntimeError,match='transaction fixture'):upload(c,raw)
    assert database()==before and set(main.DATA.rglob('*'))==paths

def test_reader_log_is_lightweight_timed_and_idempotent(merged_client,monkeypatch):
    c=merged_client;p,cid=ready(c);_,base=new_session(c,p)
    async def answer(ctx,*_):
        b=next(v for v in ctx['basis'] if v['clueId']=='c');return dict(segments=[dict(text=b['text'],basisIds=[b['id']],clueIds=['c'])])
    monkeypatch.setattr(experience,'answer',answer);before=main.get(p['id']);turn=send(c,base,cid)
    assert turn['finishedAt']>=turn['time'] and send(c,base,cid)==turn
    for _ in range(2):assert c.post(base+'/collect',json=dict(turnId=turn['id'],clueId='c')).status_code==200
    def forbidden(*args):raise AssertionError('record reading must not rebuild creation')
    monkeypatch.setattr(experience.consume,'snapshot',forbidden)
    records=c.get(base+'/records');assert records.status_code==200,records.text
    value=records.json();assert len(value['messages'])==1 and [e['type'] for e in value['clueEvents']]==['triggered','collected']
    assert all(e['time'] for e in value['clueEvents']) and 'contentSnapshot' not in value and 'presentation' not in value
    assert main.get(p['id'])==before

def test_old_collection_time_is_not_fabricated(merged_client):
    c=merged_client;p,_=ready(c);v,base=new_session(c,p);sid=v['session']['id']
    with main.db() as db:
        row=json.loads(db.execute('SELECT body FROM experience_sessions WHERE id=?',(sid,)).fetchone()[0]);row['collectedClueIds']=['c'];db.execute('UPDATE experience_sessions SET body=? WHERE id=?',(json.dumps(row),sid))
    event=c.get(base+'/records').json()['clueEvents'][0];assert event['time'] is None and event['timePrecision']=='unknown-legacy'

def test_backup_pruning_only_touches_manifested_backups_and_requires_verified_recovery(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    import retain_recovery_backup as retention
    root=tmp_path/'backups';root.mkdir();old=root/'old';(old/'project/data').mkdir(parents=True);(old/'manifest.json').write_text('{}')
    other=root/'unrecognised';other.mkdir();(other/'important.txt').write_text('keep')
    linked=root/'linked';linked.symlink_to(old,target_is_directory=True)
    keep=root/'latest';(keep/'data').mkdir(parents=True);(keep/'manifest.json').write_text('{"verified":false}')
    plan=retention.candidates(root,keep);assert [v['name'] for v in plan]==['old']
    with pytest.raises(RuntimeError,match='拒绝清理'):retention.prune(root,keep,plan)
    assert old.exists()
    (keep/'manifest.json').write_text('{"verified":true}')
    assert len(retention.prune(root,keep,plan))==1 and not old.exists() and other.exists() and keep.exists()
