"""Revision notices and atomic confirmation; all providers are local substitutes."""
import copy
import io
import json
import sqlite3
import zipfile
import pytest
from backend import main,workspace as ws,consumption as consume,revisions,experience,video,catalog
from test_merged_features import ready,approve,session,send
from test_studio import setup,prepare,draft,confirm


def publish_name(client,p,cid,name):
    d=copy.deepcopy(p['workspace']['entities']['character:'+cid]['draft']);d['name']=name
    p=draft(client,p,'character',cid,d);r=confirm(client,p,'character',cid);assert r.status_code==200,r.text
    return r.json()


def test_legacy_read_cache_isolated_and_invalidated_by_body_or_audit(client,monkeypatch):
    p,_=ready(client);pid=p['id'];main._revision_reads.clear()
    with main.db() as c:
        raw=json.loads(c.execute('SELECT body FROM projects WHERE id=?',(pid,)).fetchone()[0]);raw['workspace'].pop('revisionPolicy',None)
        c.execute('UPDATE projects SET body=? WHERE id=?',(json.dumps(raw),pid))
    actual=revisions.upgrade;replays=[]
    def counted(project,events=None):
        if events:replays.append(project['id'])
        return actual(project,events)
    monkeypatch.setattr(revisions,'upgrade',counted)
    first=main.get(pid);first['workspace']['entities']['material:main']['draft']['image']='caller-only'
    assert main.get(pid)['workspace']['entities']['material:main']['draft']['image']!='caller-only'
    assert len(replays)==1
    with main.db() as c:
        raw['title']='changed without version bump';c.execute('UPDATE projects SET body=? WHERE id=?',(json.dumps(raw),pid))
    assert main.get(pid)['title']=='changed without version bump' and len(replays)==2
    with main.db() as c:
        c.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)',('cache-audit',pid,'now','test','{}','{}','{}'))
    main.get(pid);assert len(replays)==3


def preview(client,p,**kw):
    req=dict(version=p['version'],scope='project',page='library');req.update(kw)
    response=client.post(f"/api/projects/{p['id']}/studio/batch-confirm/preview",json=req);assert response.status_code==200,response.text
    return req,response.json()


def commit_batch(client,p,req,plan,request_id='batch-one'):
    return client.post(f"/api/projects/{p['id']}/studio/batch-confirm",json=dict(req,previewHash=plan['previewHash'],requestId=request_id))


def test_published_change_is_notice_not_cascade_and_ack_keeps_lineage(client):
    p,cid=ready(client);p=approve(client,p);old=copy.deepcopy(p);r=old['workspace']['entities']['storyboard:c']
    p=publish_name(client,p,cid,'修订后的姓名')
    shot=p['workspace']['entities']['storyboard:c'];assert shot['state']=='confirmed' and shot['published']==r['published']
    assert shot['refs']==r['refs'] and shot['revision']==r['revision']
    assert any(v['key']=='character:'+cid and not v['reviewed'] for v in shot['basisWarnings'])
    assert video.preview(p,'c',main.DATA)['approved']
    report=client.get(f"/api/projects/{p['id']}/studio/checklist").json();assert report['versionWarnings']
    result=client.post(f"/api/projects/{p['id']}/studio/acknowledge",json=dict(version=p['version'],kind='storyboard',id='c'));assert result.status_code==200
    p=result.json();shot=p['workspace']['entities']['storyboard:c']
    assert shot['revision']==r['revision'] and shot['refs']==r['refs'] and all(v['reviewed'] for v in shot['basisWarnings'])
    assert p['workspace']['entities']['clue:c']['revision']==old['workspace']['entities']['clue:c']['revision']
    p=publish_name(client,p,cid,'再次修订');assert any(not v['reviewed'] for v in p['workspace']['entities']['storyboard:c']['basisWarnings'])


def test_draft_edits_do_not_notice_or_remove_identity(client):
    p,cid=ready(client);old=copy.deepcopy(p)
    d=p['workspace']['entities']['character:'+cid]['draft'];d['biography']='暂未发布的补充'
    p=draft(client,p,'character',cid,d)
    assert not p['workspace']['entities']['storyboard:c']['basisWarnings']
    assert experience.available_people(p)==experience.available_people(old)
    p['annotations'][0]['x']+=.01;p=client.put('/api/projects/'+p['id'],json=p).json()
    assert p['annotations'][0]['identityConfirmed'] and p['annotations'][0]['basisChanged']
    assert consume.confirmed(p,'material','main')['annotations']==old['workspace']['entities']['material:main']['published']['annotations']


def test_old_source_evidence_survives_new_material_and_clue_edit(client):
    p,cid=ready(client);mat=copy.deepcopy(p['workspace']['entities']['material:main']['draft']);mat['sources'][0]['confirmed']=True
    p=draft(client,p,'material','main',mat);p=confirm(client,p,'material','main').json()
    source=p['workspace']['entities']['material:main']['published']['sources'][0];quote=source['text'][:10]
    d=dict(name='旧版原文',summary='依据',type='culture',parentId='culture',characterIds=[],plotIds=[],units=[dict(id='quote-u',text=quote,kind='clue',category='supported',references=[dict(sourceId=source['id'],sourceVersion=source['version'],quote=quote)])])
    p=draft(client,p,'clue','evidence',d);response=confirm(client,p,'clue','evidence');assert response.status_code==200,response.text;p=response.json()
    mat=copy.deepcopy(p['workspace']['entities']['material:main']['draft']);changed=next(s for s in mat['sources'] if s['id']==source['id']);changed.update(text='新版原文已完全替换',version=source['version']+1)
    p=draft(client,p,'material','main',mat);p=confirm(client,p,'material','main').json()
    old_clue=consume.confirmed(p,'clue','evidence');assert consume.evidence(p,old_clue)[0]['quote']==quote
    d=copy.deepcopy(old_clue);d['name']='只修订线索标题';p=draft(client,p,'clue','evidence',d)
    response=confirm(client,p,'clue','evidence');assert response.status_code==200,response.text
    p=response.json();assert consume.evidence(p,consume.confirmed(p,'clue','evidence'))[0]['sourceVersion']==source['version']
    d=copy.deepcopy(p['workspace']['entities']['clue:evidence']['draft']);d['units'][0]['references'][0]['quote']='从未出现过的伪造引用';p=draft(client,p,'clue','evidence',d)
    assert confirm(client,p,'clue','evidence').status_code==422


def test_deleted_reference_blocks_only_affected_content(client):
    p,cid=ready(client)
    p=draft(client,p,'clue','independent',dict(name='独立背景',summary='背景',type='culture',parentId='culture',characterIds=[],plotIds=[],units=[dict(id='free',text='虚构说明',kind='clue',category='fiction',references=[])]));p=confirm(client,p,'clue','independent').json()
    response=client.post(f"/api/projects/{p['id']}/studio/delete",json=dict(version=p['version'],kind='character',id=cid,acceptRisk=True));assert response.status_code==200
    p=response.json()
    with pytest.raises(ValueError,match='删除'):consume.confirmed(p,'clue','c')
    assert consume.confirmed(p,'clue','independent')['name']=='独立背景'


def test_batch_confirms_same_transaction_and_replays_without_side_effect(client,monkeypatch):
    p,cid=ready(client);d=copy.deepcopy(p['workspace']['entities']['character:'+cid]['draft']);d['name']='批量新姓名';p=draft(client,p,'character',cid,d)
    mat=copy.deepcopy(p['workspace']['entities']['material:main']['draft'])
    for a in mat['annotations']:a['identityConfirmed']=False
    p=draft(client,p,'material','main',mat)
    async def forbidden(*a,**kw):raise AssertionError('batch cannot call a provider')
    monkeypatch.setattr(experience,'answer',forbidden)
    from backend import studio_agent
    monkeypatch.setattr(studio_agent,'run',forbidden)
    req,plan=preview(client,p)
    assert len([i for i in plan['eligible'] if i['action']=='identity'])==2
    assert any(i['key']=='character:'+cid for i in plan['eligible'])
    assert any('至少一条' in i['reason'] for i in plan['skipped'])
    with main.db() as c:count=c.execute('SELECT COUNT(*) FROM events WHERE project=?',(p['id'],)).fetchone()[0]
    response=commit_batch(client,p,req,plan);assert response.status_code==200,response.text;updated=response.json()['project']
    assert updated['version']==p['version']+1
    assert all(a['identityConfirmed'] for a in updated['workspace']['entities']['material:main']['published']['annotations'])
    with main.db() as c:assert c.execute('SELECT COUNT(*) FROM events WHERE project=?',(p['id'],)).fetchone()[0]==count+1
    replay=commit_batch(client,p,req,plan).json();assert replay['replayed'] and replay['project']['version']==updated['version']
    assert commit_batch(client,p,dict(req,scope='page'),plan).status_code==409


def test_batch_confirms_prerequisites_in_order_without_generation(client):
    p=setup(client);cid=p['characters'][0]['id']
    clue=dict(name='批量情节',content='人物稍作停顿。',type='narrative',parentId='narrative',plotIds=['batch-plot'],characterIds=[cid],units=[])
    p=draft(client,p,'clue','batch-clue',clue)
    p=draft(client,p,'plot','batch-plot',dict(title='剧情',body='剧情内容',goal='',characterIds=[cid],clueIds=['batch-clue']))
    p=draft(client,p,'knowledge',cid,dict(characterId=cid,clueIds=['batch-clue'],reasons={}))
    shot=dict(clueId='batch-clue',characterIds=[cid],region=dict(x=0,y=0,w=1,h=1),participantsConfirmed=True,prompt='静止构图，衣袖微动',startFrame='静立',endFrame='静立',action='微动',camera='固定',style='古画')
    shot['promptConfigHash']=ws.config_hash(shot);p=draft(client,p,'storyboard','batch-clue',shot)
    req,plan=preview(client,p);result=commit_batch(client,p,req,plan);assert result.status_code==200,result.text
    updated=result.json()['project']
    for key in ['material:main','character:'+cid,'intent:main','plot:batch-plot','clue:batch-clue','knowledge:'+cid,'storyboard:batch-clue']:assert ws.valid(updated['workspace']['entities'][key]),(key,plan)
    assert updated['version']==p['version']+1 and not updated['workspace']['jobs']


def test_batch_page_scope_conflicts_skip_and_preview_version(client):
    p,cid=ready(client);mat=copy.deepcopy(p['workspace']['entities']['material:main']['draft']);mat['annotations'][0]['identityConfirmed']=False;mat['matches']=[dict(annotationId='instance-1',conflicts=['明确冲突'])]
    p=draft(client,p,'material','main',mat)
    req,plan=preview(client,p,scope='page',page='library')
    assert any(i['key']=='identity:instance-1' and '冲突' in i['reason'] for i in plan['skipped'])
    assert not any(i['key'].startswith(('character:','knowledge:','clue:')) for i in plan['eligible'])
    p=draft(client,p,'intent','main',p['workspace']['entities']['intent:main']['draft'])
    assert commit_batch(client,p,req,plan).status_code==409


def test_batch_transaction_rolls_back_on_storage_failure(client,monkeypatch):
    p,cid=ready(client);d=copy.deepcopy(p['workspace']['entities']['character:'+cid]['draft']);d['name']='不能写入';p=draft(client,p,'character',cid,d);req,plan=preview(client,p)
    before=main.get(p['id'])
    def fail(*a):raise RuntimeError('storage failure')
    monkeypatch.setattr(catalog,'synchronize',fail)
    with pytest.raises(RuntimeError,match='storage failure'):commit_batch(client,p,req,plan)
    assert main.get(p['id'])==before


def test_batch_does_not_adopt_suggestions_or_resolve_history_and_checks(client):
    p,cid=ready(client);other=next(r for r in p['workspace']['entities'].values() if r['kind']=='knowledge' and r['id']!=cid)
    other['suggestion']=dict(characterId=other['id'],clueIds=['c'],reasons={})
    p['workspace']['historyLibrary']=dict(revision=0,draft={'works':[{'title':'未审史料'}]})
    p['workspace']['consistencyChecks']=[dict(id='review',message='待人工核对',resolved=False)]
    p=main.save(p,p['version'],'studio:test_pending_suggestions');before=copy.deepcopy(p['workspace']['historyLibrary'])
    req,plan=preview(client,p);assert any(i['key']=='knowledge:'+other['id'] for i in plan['skipped'])
    response=commit_batch(client,p,req,plan);assert response.status_code==200
    updated=response.json()['project'];assert updated['workspace']['historyLibrary']==before
    assert updated['workspace']['entities']['knowledge:'+other['id']]['suggestion']
    assert not updated['workspace']['consistencyChecks'][0]['resolved']


def test_batch_respects_running_output_locks(client):
    p,cid=ready(client);d=copy.deepcopy(p['workspace']['entities']['character:'+cid]['draft']);d['name']='生成期间编辑';p=draft(client,p,'character',cid,d)
    with main.db() as c:c.execute('INSERT INTO studio_jobs VALUES (?,?,?)',('lock',p['id'],json.dumps(dict(id='lock',projectId=p['id'],task='relationship',target=cid,state='running',label='测试任务',writeSet=['/workspace/entities/character:'+cid],time='1'))))
    req,plan=preview(client,p);assert any(v['key']=='character:'+cid and '生成' in v['reason'] for v in plan['skipped'])
    assert not any(v['key']=='character:'+cid for v in plan['eligible'])


def test_batch_preview_is_bound_to_project_even_for_identical_content(client):
    a=client.post('/api/projects',json=dict(title='相同内容')).json();b=client.post('/api/projects',json=dict(title='相同内容')).json()
    req,plan=preview(client,a)
    response=client.post(f"/api/projects/{b['id']}/studio/batch-confirm",json=dict(req,previewHash=plan['previewHash'],requestId='wrong-project'))
    assert response.status_code==409


def test_legacy_revision_recovery_uses_audit_and_missing_basis_is_explicit(client):
    p,cid=ready(client);p=publish_name(client,p,cid,'新版姓名')
    raw=copy.deepcopy(p);w=raw['workspace'];w.pop('revisionArchive');w.pop('revisionPolicy')
    w['entities']['clue:c']['state']='stale'
    for r in w['entities'].values():
        for h in r.get('history',[]):h.pop('refs',None)
    with main.db() as c:c.execute('UPDATE projects SET body=? WHERE id=?',(json.dumps(raw),p['id']))
    restored=main.get(p['id']);assert consume.confirmed(restored,'clue','c')
    assert restored['workspace']['entities']['clue:c']['state']=='confirmed'
    with main.db() as c:
        c.execute('DELETE FROM events WHERE project=?',(p['id'],));c.execute('UPDATE projects SET body=? WHERE id=?',(json.dumps(raw),p['id']))
    broken=main.get(p['id']);assert '无法恢复' in broken['workspace']['entities']['clue:c']['basisError']


def test_old_session_is_pinned_and_new_session_uses_new_profile(client,monkeypatch):
    p,cid=ready(client);s=session(client,p);path=f"/api/projects/{p['id']}/experience/sessions/{s['session']['id']}"
    old_name=next(v['name'] for v in s['people'] if v['characterId']==cid)
    p=publish_name(client,p,cid,'新版本角色')
    old=client.get(path).json();assert old['oldVersion'] and old['people'][0]['name']==old_name
    assert session(client,p)['people'][0]['name']=='新版本角色'
    async def provider(context,*args):
        assert context['character']['name']==old_name
        assert [c['id'] for c in context['clues']]==['c']
        return dict(answer='沿用旧会话中的线索',clueIds=['c'])
    monkeypatch.setattr(experience,'answer',provider)
    turn=send(client,p,s,cid).json();assert turn['status']=='completed'
    collected=client.post(path+'/collect',json=dict(turnId=turn['id'],clueId='c')).json();assert collected['session']['collectedClueIds']==['c']
    assert main.get(p['id'])['version']==p['version']
    assert client.get(path).json()['session']['collectedClueIds']==['c']


def test_version_warnings_are_exported_as_nonblocking_with_pinned_bases(client):
    p,cid=ready(client)
    for c in p['characters']:
        if not ws.valid(p['workspace']['entities']['knowledge:'+c['id']]):p=confirm(client,p,'knowledge',c['id']).json()
    p=publish_name(client,p,cid,'修改姓名')
    path=f"/api/projects/{p['id']}/narrative/export?format=zip&draft=false&reviewed=true&version={p['version']}"
    result=client.get(path);assert result.status_code==200,result.text
    with zipfile.ZipFile(io.BytesIO(result.content)) as z:
        bundle=json.loads(z.read('manifest.json'));assert bundle['basisWarnings'] and bundle['basisVersions']
        assert not bundle['issues'] and bundle['state']=='approved' and not bundle['interaction']['readerProgressIncluded']


def test_legacy_video_hash_does_not_duplicate_the_same_provider_body(client,monkeypatch):
    from test_merged_features import mock_video_provider,wait_video
    calls=mock_video_provider(monkeypatch);p,cid=ready(client);p=approve(client,p);path=f"/api/projects/{p['id']}/videos"
    response=client.post(path,json=dict(version=p['version'],storyboardId='c'));assert response.status_code==200,response.text
    job=wait_video(client,p,response.json()['id']);assert job['status']=='succeeded'
    original_id=job['id'];job['id']='legacy-job';job['requestFingerprint']='legacy-version-hash';job.pop('providerRequestHash',None)
    (main.DATA/'video-inputs'/(original_id+'.png')).rename(main.DATA/'video-inputs/legacy-job.png')
    with main.db() as c:
        c.execute('DELETE FROM video_jobs WHERE id=?',(original_id,));c.execute('INSERT INTO video_jobs VALUES (?,?,?)',(job['id'],p['id'],json.dumps(job)))
    result=client.post(path,json=dict(version=p['version'],storyboardId='c'));assert result.status_code==200,result.text
    assert result.json()['id']=='legacy-job' and len([c for c in calls if c.method=='POST'])==1
