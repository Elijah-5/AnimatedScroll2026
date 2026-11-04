import asyncio
import copy
import json
import time
import pytest
from fastapi.testclient import TestClient
from backend import main,structured,history,consumption,studio,materials,experience
from test_merged_features import ready,session
from test_studio import draft,confirm
from test_history import dataset


def install(client,p,value):return draft(client,p,'material','main',dict(p['workspace']['entities']['material:main']['draft'],structured=value))

def test_preview_never_writes_or_calls_models_and_legacy_writes_are_retired(client,monkeypatch):
    p=client.post('/api/projects',json=dict(title='空项目')).json();before=main.get(p['id'])
    async def forbidden(*args):raise AssertionError('implicit model')
    monkeypatch.setattr(structured,'ask',forbidden)
    r=client.get(f"/api/projects/{p['id']}/structured");assert r.status_code==200
    value=r.json();assert value['derivedPreview'] and set(value['draft']['artwork'])==set(structured.FIELDS)
    assert len(value['draft']['missing'])>=10 and main.get(p['id'])==before
    for suffix in ('draft','legacy-candidates','preview','confirm','discard','adopt'):
        method=client.put if suffix=='draft' else client.post
        assert method(f"/api/projects/{p['id']}/history/{suffix}",json=dict(version=p['version'])).status_code==410


def test_group_and_background_people_reuse_existing_ids_without_inventing_actors(client):
    p,cid=ready(client);p['workspace']['entities']['character:'+cid]['draft']['roleType']='group'
    p['documentAnalysis']=dict(people=[dict(id='scholar',name='研究者甲',roleType='named',scope='background',contextRoles=['scholar'],references=[])])
    value=structured.seed(p);group=next(r for r in value['people'] if r['id']==cid)
    assert group['annotationIds']==['instance-1','instance-2'] and group['characterId']==cid
    scholar=next(r for r in value['people'] if r['name']=='研究者甲');assert not scholar['characterId'] and scholar['scope']=='background'
    structured.validate(value)


def test_bounded_aggregation_cache_exact_evidence_and_manual_precedence(client,monkeypatch):
    p,_=ready(client);source=p['workspace']['entities']['material:main']['draft']['sources'][0]
    calls=[];cache={}
    async def fake(ctx):
        calls.append(ctx)
        return dict(artwork=[dict(field='artist',value='候选作者',referenceIds=[ctx['evidence'][0]['id']])])
    monkeypatch.setattr(structured,'ask',fake)
    first=asyncio.run(structured.organize(p,cache.get,cache.__setitem__));count=len(calls)
    assert first['artwork']['artist']['value']=='候选作者' and count>0
    assert all(len(json.dumps(c['evidence'],ensure_ascii=False))<16000 for c in calls)
    asyncio.run(structured.organize(p,cache.get,cache.__setitem__));assert len(calls)==count
    first['artwork']['artist']['value']='人工作者';structured.install_draft(p,first)
    final=asyncio.run(structured.organize(p,cache.get,cache.__setitem__))
    assert final['artwork']['artist']['value']=='人工作者' and any(c['candidate']=='候选作者' for c in final['conflicts'])
    assert not any(e['verification']=='edition_verified' for e in final['evidence'])


def test_unverified_secondary_quote_never_becomes_primary_and_bad_references_fail(client):
    p,_=ready(client);s=p['workspace']['entities']['material:main']['draft']['sources'][0];quote=s['text'][:8]
    p['documentAnalysis']=dict(claims=[dict(id='secondary',text='论文转引史书',topic='story',assertion='historical_account',indirectSource='经论文转引',references=[dict(sourceId=s['id'],sourceVersion=s['version'],quote=quote)])])
    value=structured.seed(p);ref=next(e for e in value['evidence'] if e['quote']==quote)
    assert ref['level']=='indirect' and ref['verification']=='unverified'
    assert any(v['label']=='转引史书版本' for v in value['missing'])
    with pytest.raises(ValueError,match='不存在'):structured.apply_suggestion(value,dict(artwork=[dict(field='artist',value='编造',referenceIds=['missing'])]))
    ref['verification']='edition_verified'
    with pytest.raises(ValueError,match='升级'):structured.validate(value)


def test_publication_uses_one_material_version_and_downstream_reads_confirmed_only(client,monkeypatch):
    p,cid=ready(client);value=structured.seed(p);value['artwork']['artist']=structured.cell('已确认作者',origin='creator')
    before=copy.deepcopy(p['workspace']['revisionArchive']['material:main']['1']['data']);p=install(client,p,value)
    assert 'structured' not in consumption.confirmed(p,'material','main')
    async def forbidden(*args):raise AssertionError('publish called a model')
    monkeypatch.setattr(structured,'ask',forbidden)
    r=confirm(client,p,'material','main');assert r.status_code==200,r.text;p=r.json()
    assert structured.view(p)['artwork']['artist']['value']=='已确认作者'
    assert studio.context(p,'plots')['structuredMaterial']['artwork']['artist']['value']=='已确认作者'
    assert p['workspace']['entities']['storyboard:c']['state']=='confirmed'
    with main.db() as c:assert c.execute('SELECT artist FROM works WHERE project_id=?',(p['id'],)).fetchone()[0]=='已确认作者'
    assert p['workspace']['revisionArchive']['material:main']['1']['data']==before
    changed=copy.deepcopy(value);changed['artwork']['artist']['value']='草稿秘密';p=install(client,p,changed)
    assert '草稿秘密' not in json.dumps(studio.context(p,'plots'),ensure_ascii=False)


def test_new_canonical_source_can_ground_clues_and_evidence(client):
    p,_=ready(client);value=structured.seed(p)
    value['sources'].append(dict(id='canonical-only',version=1,title='研究资料',text='只存在于统一资料的原文。',citation='测试论文'))
    value['evidence'].append(dict(id='canonical-e',sourceId='canonical-only',sourceVersion=1,start=0,end=13,quote='只存在于统一资料的原文。',level='research',verification='unverified',edition='测试论文'))
    value['evidence'][-1]['end']=len(value['evidence'][-1]['quote'])
    p=install(client,p,value);p=confirm(client,p,'material','main').json()
    d=dict(name='统一依据',type='culture',parentId='culture',summary='说明',characterIds=[],plotIds=[],units=[dict(id='cu',text='只存在于统一资料的原文。',kind='clue',category='supported',references=[dict(sourceId='canonical-only',sourceVersion=1,quote='只存在于统一资料的原文。')])])
    p=draft(client,p,'clue','canonical',d);r=confirm(client,p,'clue','canonical');assert r.status_code==200,r.text;p=r.json()
    evidence=consumption.evidence(p,consumption.confirmed(p,'clue','canonical'),'canonical');assert evidence[0]['sourceId']=='canonical-only'


def test_legacy_history_import_preserves_ids_review_and_both_draft_versions(client):
    p,_=ready(client);tables=dataset(p['id'])
    with main.db() as c:history.publish(c,p['id'],history.empty(),tables)
    p['workspace']['historyLibrary']=dict(revision=1,draft=copy.deepcopy(tables));p['workspace']['historyLibrary']['draft']['works'][0]['artist']='不同旧草稿'
    value=structured.preview(p,main.db);assert len(value['legacyVersions'])==2
    assert any(e.get('legacyId')=='quote' and e['verification']=='edition_verified' for e in value['evidence'])
    assert any(r['id']=='person' for r in value['people'])
    assert any(r['candidate']=='不同旧草稿' for r in value['conflicts'])
    assert value['legacyVersions'][0]['tables']['hist_sources'][0]['snapshot_text']==tables['hist_sources'][0]['snapshot_text']
    structured.validate(value)


def test_shared_confirmation_rolls_back_sql_projections_on_failure(client,monkeypatch):
    p,_=ready(client);p=install(client,p,structured.seed(p));before=main.get(p['id'])
    actual=history.publish
    def fail(conn,*args):actual(conn,*args);raise ValueError('投影事务失败')
    monkeypatch.setattr(history,'publish',fail)
    result=confirm(client,p,'material','main');assert result.status_code==422 and '投影事务失败' in result.text
    assert main.get(p['id'])==before
    with main.db() as c:assert not history.read_tables(c,p['id'])['works']


def test_role_context_filters_other_people_and_old_sessions_keep_own_snapshot(client):
    p,cid=ready(client);old=session(client,p);value=structured.seed(p)
    value['statements'] += [dict(id='own-fact',personId=cid,text='本角色的统一资料',aspect='行事',category='uncertain',referenceIds=[],origin='creator'),dict(id='other-secret',personId=next(r['id'] for r in value['people'] if r['id']!=cid),text='其他角色的秘密XYZ',aspect='行事',category='uncertain',referenceIds=[],origin='creator')]
    p=install(client,p,value);p=confirm(client,p,'material','main').json()
    context=experience.dialogue_context(p,cid)
    assert '本角色的统一资料' in json.dumps(context,ensure_ascii=False) and '其他角色的秘密XYZ' not in json.dumps(context,ensure_ascii=False)
    restored=client.get(f"/api/projects/{p['id']}/experience/sessions/{old['session']['id']}").json();assert restored['oldVersion']


def test_structure_job_generates_only_draft_and_invalid_model_output_preserves_manual_data(client,monkeypatch):
    with TestClient(main.app) as c:
        p,_=ready(c);published=copy.deepcopy(p['workspace']['entities']['material:main']['published'])
        async def invalid(ctx):return dict(artwork=[dict(field='artist',value='坏结果',referenceIds=['fabricated'])])
        monkeypatch.setattr(structured,'ask',invalid)
        r=c.post(f"/api/projects/{p['id']}/studio/jobs",json=dict(version=p['version'],task='structure_materials'));assert r.status_code==200,r.text
        for _ in range(120):
            jobs=c.get(f"/api/projects/{p['id']}/studio").json()['workspace']['jobs']
            if jobs and jobs[0]['state'] not in ('queued','running'):break
            time.sleep(.02)
        assert jobs[0]['state']=='failed' and '不存在' in jobs[0]['error']
        assert main.get(p['id'])['workspace']['entities']['material:main']['published']==published


def test_materials_analysis_also_builds_unified_draft(client,monkeypatch):
    async def fake(p,legacy=False):return dict(segments=[],characters=[],eventFramework=[],summary='测试替身')
    monkeypatch.setattr(materials,'organize',fake)
    with TestClient(main.app) as c:
        p,_=ready(c);r=c.post(f"/api/projects/{p['id']}/tasks",json=dict(version=p['version'],kind='materials'));assert r.status_code==200,r.text
        for _ in range(120):
            rows=c.get(f"/api/projects/{p['id']}/tasks").json()
            if rows[0]['status'] not in ('queued','running'):break
            time.sleep(.02)
        assert rows[0]['status']=='completed',rows[0]
        result=main.get(p['id'])['workspace']['entities']['material:main']
        assert result['draft']['structured']['people'] and 'structured' not in result['published']


def test_migration_dry_run_then_stages_only_once_without_publication(client):
    from scripts.migrate_unified_library import run
    p,_=ready(client);old=main.get(p['id']);report=run(project_id=p['id']);assert report and not report[0]['applied'] and main.get(p['id'])==old
    assert run(True,p['id'])[0]['publishedContentUnchanged'] and run(True,p['id'])==[]
    current=main.get(p['id'])
    assert current['workspace']['entities']['material:main']['published']==old['workspace']['entities']['material:main']['published']


def test_failed_generated_references_are_not_cached_forever(client,monkeypatch):
    p,_=ready(client);cache={};calls=[]
    async def fake(ctx):
        calls.append(1)
        return dict(artwork=[dict(field='artist',value='测试',referenceIds=['bad'])]) if len(calls)==1 else {}
    monkeypatch.setattr(structured,'ask',fake)
    with pytest.raises(ValueError,match='不存在'):asyncio.run(structured.organize(p,cache.get,cache.__setitem__))
    assert not cache
    asyncio.run(structured.organize(p,cache.get,cache.__setitem__));assert len(calls)>=2


def test_confirming_first_material_never_calls_models_even_from_legacy_client(client,monkeypatch):
    from test_studio import setup
    p=setup(client)
    async def forbidden(*args):raise AssertionError('implicit call')
    monkeypatch.setattr(materials,'organize',forbidden)
    response=client.post(f"/api/projects/{p['id']}/studio/confirm",json=dict(version=p['version'],kind='material',id='main',generate=True))
    assert response.status_code==200 and not response.json()['workspace']['jobs']


def test_export_and_model_context_exclude_legacy_unconfirmed_archives(client):
    from backend import narrative
    p,_=ready(client);value=structured.seed(p);value['legacyVersions']=[dict(state='draft',tables=dict(secret='旧未确认记录XYZ'))]
    p=install(client,p,value);p=confirm(client,p,'material','main').json()
    bundle=narrative.package(p,main.DATA,[])
    assert bundle['schemaVersion']=='3.4' and 'structuredMaterial' in bundle
    assert bool('旧未确认记录XYZ' not in json.dumps(bundle,ensure_ascii=False)), 'export contains an unconfirmed legacy archive'
    assert bool('旧未确认记录XYZ' not in json.dumps(studio.context(p,'plots'),ensure_ascii=False)), 'model context contains an unconfirmed legacy archive'


def test_new_source_added_in_unified_editor_is_used_by_next_organization(client,monkeypatch):
    p,_=ready(client);value=structured.seed(p)
    value['sources'].append(dict(id='added',version=1,title='补充',text='补充作者原文',citation=''))
    value['evidence'].append(dict(id='added-e',sourceId='added',sourceVersion=1,quote='补充作者原文',start=0,end=6,level='creator',verification='unverified',edition=''))
    structured.install_draft(p,value);seen=[]
    async def fake(ctx):seen.extend(e['sourceId'] for e in ctx['evidence']);return {}
    monkeypatch.setattr(structured,'ask',fake)
    result=asyncio.run(structured.organize(p));assert 'added' in seen;structured.validate(result)


def test_explicitly_verified_primary_span_projects_without_promoting_secondary_sources(client):
    p,_=ready(client);value=structured.seed(p);text='人工测试原文，不是真实史料。'
    value['sources'].append(dict(id='primary-test',version=1,title='测试史书',text=text,citation='测试版本',sourceType='historical_primary',genre='正史',resource_uri='document:test-primary'))
    value['evidence'].append(dict(id='primary-e',sourceId='primary-test',sourceVersion=1,quote=text,start=0,end=len(text),level='direct',verification='edition_verified',edition='测试版本',locator='测试卷'))
    p=install(client,p,value);result=confirm(client,p,'material','main');assert result.status_code==200,result.text
    with main.db() as c:tables=history.read_tables(c,p['id'])
    assert [q['id'] for q in tables['quotations']]==['primary-e']
    assert tables['hist_sources'][0]['snapshot_text']==text


def test_structure_result_from_changed_input_preserves_manual_edit_as_old_input_suggestion(client,monkeypatch):
    from test_parallel_tasks import finish_studio
    p,_=ready(client);pid=p['id']
    async def fake(ctx):
        current=main.get(pid);manual=structured.seed(current);manual['artwork']['artist']=structured.cell('运行中人工填写',origin='creator');structured.install_draft(current,manual)
        main.save(current,current['version'],'studio:test_parallel_edit')
        return dict(artwork=[dict(field='artist',value='旧输入建议',referenceIds=[ctx['evidence'][0]['id']])])
    monkeypatch.setattr(structured,'ask',fake)
    with TestClient(main.app) as c:
        response=c.post(f'/api/projects/{pid}/studio/jobs',json=dict(version=p['version'],task='structure_materials'));assert response.status_code==200,response.text
        current,job=finish_studio(c,pid)
        assert job['state']=='completed' and job['savedAsSuggestion']
        assert current['workspace']['entities']['material:main']['draft']['structured']['artwork']['artist']['value']=='运行中人工填写'
        assert current['workspace']['generationSuggestions'][-1]['status']=='pending'


def test_canonical_old_source_is_retained_when_editing_clue_after_new_material_publication(client):
    p,_=ready(client);value=structured.seed(p);text='统一原文甲版本。'
    value['sources'].append(dict(id='canonical-history',version=1,title='旧来源',text=text,citation=''))
    value['evidence'].append(dict(id='old-quote',sourceId='canonical-history',sourceVersion=1,quote=text,start=0,end=len(text),level='research',verification='unverified',edition=''))
    p=install(client,p,value);p=confirm(client,p,'material','main').json()
    body=dict(name='历史依据线索',summary='旧摘要',type='culture',parentId='culture',plotIds=[],characterIds=[],units=[dict(id='history-unit',text=text,kind='clue',category='supported',references=[dict(sourceId='canonical-history',sourceVersion=1,quote=text)])])
    p=draft(client,p,'clue','old-canonical',body);p=confirm(client,p,'clue','old-canonical').json()
    changed=copy.deepcopy(value);changed['sources']=[s for s in changed['sources'] if s['id']!='canonical-history'];changed['evidence']=[e for e in changed['evidence'] if e['sourceId']!='canonical-history']
    p=install(client,p,changed);p=confirm(client,p,'material','main').json()
    body['summary']='仅编辑线索摘要';p=draft(client,p,'clue','old-canonical',body);result=confirm(client,p,'clue','old-canonical')
    assert result.status_code==200,result.text;p=result.json()
    assert consumption.evidence(p,consumption.confirmed(p,'clue','old-canonical'),'old-canonical')[0]['sourceVersion']==1


def test_source_versions_coexist_in_canonical_data_and_catalog_exposes_latest(client):
    p,_=ready(client);value=structured.seed(p)
    for version,text in [(1,'旧原文。'),(2,'新原文。')]:
        value['sources'].append(dict(id='versioned',version=version,title='版本来源',text=text,citation=''))
        value['evidence'].append(dict(id='version-e-'+str(version),sourceId='versioned',sourceVersion=version,quote=text,start=0,end=len(text),level='research',verification='unverified',edition=''))
    p=install(client,p,value);result=confirm(client,p,'material','main');assert result.status_code==200,result.text
    assert len([s for s in structured.view(result.json())['sources'] if s['id']=='versioned'])==2
    with main.db() as c:assert c.execute('SELECT version FROM artwork_sources WHERE project_id=? AND id=?',(p['id'],'versioned')).fetchone()[0]==2


def test_confirmed_visual_observation_keeps_instance_and_never_becomes_historical_quote(client):
    p,cid=ready(client);annotations=p['workspace']['entities']['material:main']['draft']['annotations'];annotations[0].update(confirmed=True,description='仅为测试的画面衣服观察')
    annotations[1].update(confirmed=False,description='尚未确认的观察')
    value=structured.seed(p);lines=[r for r in value['statements'] if r.get('annotationId')==annotations[0]['id']]
    assert len(lines)==1 and lines[0]['personId']==cid
    e=next(e for e in value['evidence'] if e['id']==lines[0]['referenceIds'][0]);assert e['level']=='observation' and e['verification']=='unverified'
    assert not any(r.get('annotationId')==annotations[1]['id'] for r in value['statements'])
    structured.validate(value)


@pytest.mark.parametrize('mutation',[
    lambda value:value['sources'].append(copy.deepcopy(value['sources'][0])),
    lambda value:value['sources'][0].update(version=0),
])
def test_ambiguous_source_versions_fail_without_partial_save(client,mutation):
    p,_=ready(client);value=structured.seed(p);mutation(value);before=main.get(p['id'])
    result=client.put(f"/api/projects/{p['id']}/studio/drafts",json=dict(version=p['version'],entries=[dict(kind='material',id='main',data=dict(p['workspace']['entities']['material:main']['draft'],structured=value))]))
    assert result.status_code==422 and main.get(p['id'])==before
