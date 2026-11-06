import asyncio
import copy
import time
import pytest
from backend import main, feedback, structured, workspace as ws
from backend.library_review import active_conflicts, install_contradictions
from test_merged_features import merged_client, ready


def setup(client):
    p, cid = ready(client)
    value = structured.seed(p)
    value['people'][0].update(name='唐太宗', summary='唐代皇帝。')
    value['people'].append(dict(id='alias', name='太宗', summary='资料中的皇帝称谓。',
                                characterId='', scope='depicted', roleType='named', referenceIds=[]))
    value['relations'].append(dict(id='relation', fromId='alias', toId=cid, label='另一称谓', referenceIds=[]))
    structured.install_draft(p, value)
    p['workspace']['entities']['material:main']['published']['structured'] = copy.deepcopy(value)
    p = main.save(p, p['version'], 'studio:feedback_fixture')
    return p, cid


def submit(client, p, target=None, **kw):
    body = dict(version=p['version'], requestId='feedback-1', target=target or dict(section='people'), instruction='合并唐太宗和太宗')
    body.update(kw)
    r = client.post(f'/api/projects/{p["id"]}/studio/feedback', json=body)
    assert r.status_code == 200, r.text
    return r.json(), body


def wait(client, p, job):
    for _ in range(300):
        r = client.get(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}')
        assert r.status_code == 200, r.text
        job = r.json()
        if job['status'] not in ('queued', 'running'): return job
        time.sleep(.01)
    raise AssertionError('feedback did not finish')


def test_merge_is_structural_and_undo_preserves_unrelated_edits(merged_client, monkeypatch):
    c = merged_client
    p, cid = setup(c)
    archive = copy.deepcopy(p['workspace']['revisionArchive'])
    unrelated = {k:copy.deepcopy(v) for k,v in p['workspace']['entities'].items() if v['kind'] in ('plot','clue','storyboard')}
    async def model(ctx):
        return dict(operations=[dict(op='merge_people', personIds=[cid, 'alias'])])
    monkeypatch.setattr(feedback, 'ask', model)
    job, body = submit(c, p)
    result = wait(c, p, job)
    assert result['status'] == 'completed', result
    current = main.get(p['id'])
    value = feedback.library(current)
    assert len(value['people']) == len(feedback.library(p)['people']) - 1
    assert value['people'][0]['id'] == cid
    assert value['people'][0]['aliases'][0]['name'] == '太宗'
    assert value['personRedirects']['alias'] == cid and not value['relations']
    assert current['annotations'] == p['annotations']
    assert all(all(current['workspace']['entities'][k].get(field)==v.get(field) for field in ('draft','published','refs','revision','history')) for k,v in unrelated.items())
    assert current['workspace']['revisionArchive']['material:main']['1'] == archive['material:main']['1']
    replay = c.post(f'/api/projects/{p["id"]}/studio/feedback', json=body)
    assert replay.json()['id'] == job['id']
    current['title'] = '无关改名'
    current = main.save(current, current['version'], 'studio:rename')
    undo = c.post(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}/undo')
    assert undo.status_code == 200, undo.text
    restored = main.get(p['id'])
    assert restored['title'] == '无关改名'
    assert len(feedback.library(restored)['people']) == len(feedback.library(p)['people'])
    assert feedback.library(restored)['relations'][0]['fromId'] == 'alias'
    assert c.post(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}/undo').status_code == 200


def test_selected_scope_and_atomic_failure(merged_client, monkeypatch):
    c = merged_client;p, cid = setup(c);before = feedback.library(p)
    async def model(ctx):
        return dict(operations=[dict(op='update', section='people', itemId=cid, field='summary', value='允许的修改'),
                                dict(op='update', section='people', itemId='alias', field='summary', value='越界修改')])
    monkeypatch.setattr(feedback, 'ask', model)
    job, _ = submit(c, p, target=dict(section='people', itemIds=[cid]))
    assert wait(c, p, job)['status'] == 'failed'
    assert feedback.library(main.get(p['id'])) == before


def test_stale_result_cannot_overwrite_latest_content(merged_client, monkeypatch):
    c = merged_client;p, cid = setup(c)
    async def model(ctx):
        current = main.get(p['id'])
        feedback.library(current)['people'][0]['summary'] = '并行修改'
        main.save(current, current['version'], 'studio:parallel_edit')
        return dict(operations=[dict(op='update', section='people', itemId=cid, field='summary', value='旧结果')])
    monkeypatch.setattr(feedback, 'ask', model)
    job, _ = submit(c, p, target=dict(section='people', itemIds=[cid]))
    assert wait(c, p, job)['status'] == 'stale'
    assert feedback.library(main.get(p['id']))['people'][0]['summary'] == '并行修改'


def test_undo_rejects_overlapping_edit(merged_client, monkeypatch):
    c = merged_client;p, cid = setup(c)
    async def model(ctx): return dict(operations=[dict(op='update', section='people', itemId=cid, field='summary', value='修改后')])
    monkeypatch.setattr(feedback, 'ask', model)
    job, _ = submit(c, p, target=dict(section='people', itemIds=[cid]))
    assert wait(c, p, job)['status'] == 'completed'
    current = main.get(p['id']);feedback.library(current)['people'][0]['summary'] = '后续编辑'
    main.save(current, current['version'], 'studio:later_edit')
    assert c.post(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}/undo').status_code == 409


def test_ambiguous_request_asks_without_writing(merged_client, monkeypatch):
    c = merged_client;p, _ = setup(c)
    async def model(ctx): return dict(question='要保留哪个姓名？')
    monkeypatch.setattr(feedback, 'ask', model)
    job, _ = submit(c, p)
    result = wait(c, p, job)
    assert result['status'] == 'needs_input' and result['question']
    assert main.get(p['id'])['version'] == p['version']


def test_invalid_evidence_is_rejected_and_creator_changes_stay_uncertain(merged_client, monkeypatch):
    c = merged_client;p, cid = setup(c)
    async def invalid(ctx):return dict(operations=[dict(op='update', section='people', itemId=cid, field='summary', value='新描述', referenceIds=['invented'])])
    monkeypatch.setattr(feedback, 'ask', invalid)
    job, _ = submit(c, p)
    assert wait(c, p, job)['status'] == 'failed'
    async def valid(ctx):return dict(operations=[dict(op='update', section='people', itemId=cid, field='summary', value='用户补充判断')])
    monkeypatch.setattr(feedback, 'ask', valid)
    job, _ = submit(c, p, requestId='valid')
    assert wait(c, p, job)['status'] == 'completed'
    person = feedback.library(main.get(p['id']))['people'][0]
    assert person['category'] == 'uncertain' and not person['referenceIds']


def test_two_linked_roles_merge_annotations_and_undo(merged_client, monkeypatch):
    c = merged_client;p, cid = setup(c)
    char = copy.deepcopy(p['workspace']['entities']['character:' + cid])
    char['id'] = 'alias';char['draft']['id'] = 'alias';char['draft']['name'] = '太宗'
    char['published'] = copy.deepcopy(char['draft'])
    p['workspace']['entities']['character:alias'] = char
    next(r for r in feedback.library(p)['people'] if r['id']=='alias')['characterId'] = 'alias'
    p['workspace']['entities']['material:main']['draft']['annotations'][0]['characterId'] = 'alias'
    p = main.save(p, p['version'], 'studio:fixture_link')
    async def model(ctx):return dict(operations=[dict(op='merge_people', personIds=[cid,'alias'], survivorId=cid)])
    monkeypatch.setattr(feedback, 'ask', model)
    job, _ = submit(c, p)
    assert wait(c, p, job)['status'] == 'completed'
    current = main.get(p['id'])
    assert current['workspace']['entities']['material:main']['draft']['annotations'][0]['characterId'] == cid
    assert current['workspace']['entities']['character:alias']['state'] == 'deleted'
    r = c.post(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}/undo')
    assert r.status_code == 200, r.text
    current = main.get(p['id'])
    assert current['workspace']['entities']['material:main']['draft']['annotations'][0]['characterId'] == 'alias'
    assert current['workspace']['entities']['character:alias']['state'] != 'deleted'


def test_only_evidenced_contradictions_are_promoted_and_decisions_need_no_model(merged_client, monkeypatch):
    c = merged_client;p, _ = setup(c);value = feedback.library(p)
    source = dict(id='opinion-b',version=1,title='来源乙',text='作者是乙。',citation='乙文')
    value['sources'].append(source)
    value['evidence'].append(dict(id='b',sourceId='opinion-b',sourceVersion=1,quote=source['text'],start=0,end=len(source['text']),level='research',verification='unverified'))
    a = value['evidence'][0]['id']
    value['conflicts'].append(dict(id='legacy',field='artwork.artist',current='甲',candidate='甲某',reason='值不同'))
    assert not active_conflicts(value)
    install_contradictions(value,[dict(field='artwork.artist',context='同一幅作品的作者归属',reason='两来源将同一作者位置排他地归于不同人',alternatives=[dict(value='甲',referenceIds=[a]),dict(value='乙',referenceIds=['b'])])])
    assert len(active_conflicts(value)) == 1
    p = main.save(p, p['version'], 'studio:fixture_conflict')
    async def forbidden(*a):raise AssertionError('choice should not call model')
    monkeypatch.setattr(feedback,'ask',forbidden)
    conflict = active_conflicts(value)[0]
    job, _ = submit(c,p,target=dict(section='conflicts',itemIds=[conflict['id']]),instruction='',resolution='keep_both')
    assert wait(c,p,job)['status']=='completed'
    assert active_conflicts(feedback.library(main.get(p['id'])))[0]['resolution']=='keep_both'


def test_incremental_merge_does_not_recreate_merged_person(merged_client,monkeypatch):
    p,cid=setup(merged_client);before=copy.deepcopy(feedback.library(p))
    feedback.merge_people(p,feedback.library(p),[cid,'alias'],cid)
    after=structured.merge(feedback.library(p),before)
    assert len(after['people'])==len(before['people'])-1 and any(r['id']==cid for r in after['people'])


def test_feedback_reads_and_wrong_project_access_are_safe(merged_client,monkeypatch):
    c=merged_client;p,_=setup(c)
    async def model(ctx):return dict(question='请补充方向')
    monkeypatch.setattr(feedback,'ask',model)
    job,_=submit(c,p);wait(c,p,job)
    other=c.post('/api/projects').json()
    assert c.get(f'/api/projects/{other["id"]}/studio/feedback/{job["id"]}').status_code==404
    before=main.get(p['id'])
    for _ in range(3):c.get(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}')
    assert main.get(p['id'])==before


def test_undo_keeps_other_person_edit_in_same_module(merged_client,monkeypatch):
    c=merged_client;p,cid=setup(c)
    async def model(ctx):return dict(operations=[dict(op='update',section='people',itemId=cid,field='summary',value='新简介')])
    monkeypatch.setattr(feedback,'ask',model)
    job,_=submit(c,p,target=dict(section='people',itemIds=[cid]));assert wait(c,p,job)['status']=='completed'
    current=main.get(p['id']);other=next(r for r in feedback.library(current)['people'] if r['id']!=cid)
    other['summary']='另一个人物的修改'
    main.save(current,current['version'],'studio:other_person')
    response=c.post(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}/undo')
    assert response.status_code==200,response.text
    value=feedback.library(main.get(p['id']))
    assert next(r for r in value['people'] if r['id']==other['id'])['summary']=='另一个人物的修改'
    assert next(r for r in value['people'] if r['id']==cid)['summary']=='唐代皇帝。'


def test_module_summary_feedback_is_version_bound_and_undoable(merged_client,monkeypatch):
    c=merged_client;p,_=setup(c)
    async def model(ctx):return dict(operations=[dict(op='summarize',section='people',value='整理后的简短人物概括。')])
    monkeypatch.setattr(feedback,'ask',model)
    job,_=submit(c,p);assert wait(c,p,job)['status']=='completed'
    assert feedback.library(main.get(p['id']))['summaryBlocks']['people']['text']=='整理后的简短人物概括。'
    response=c.post(f'/api/projects/{p["id"]}/studio/feedback/{job["id"]}/undo')
    assert response.status_code==200,response.text
    assert feedback.library(main.get(p['id']))['summaryBlocks']['people']['text']!='整理后的简短人物概括。'


def test_running_feedback_remains_visible_when_switching_pages(merged_client,monkeypatch):
    c=merged_client;p,_=setup(c);release=[False]
    async def model(ctx):
        while not release[0]:await asyncio.sleep(.01)
        return dict(question='请补充处理方向')
    monkeypatch.setattr(feedback,'ask',model)
    job,_=submit(c,p)
    try:
        editor=c.get(f'/api/projects/{p["id"]}/studio/editor').json()
        visible=next(j for j in editor['workspace']['jobs'] if j['id']==job['id'])
        assert visible['family']=='feedback' and 'readContext' not in visible
    finally:release[0]=True
    assert wait(c,p,job)['status']=='needs_input'
    editor=c.get(f'/api/projects/{p["id"]}/studio/editor').json()
    assert not any(j['id']==job['id'] for j in editor['workspace']['jobs'])
