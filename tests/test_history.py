import copy
import hashlib
import json
import sqlite3
import pytest
from backend import main,history,history_schema,studio_agent


@pytest.fixture
def client(client):
    """Pre-upgrade server fixture: retain relational/audit tests for legacy data.

    Production retires these writes with middleware. This isolated old-router
    app constructs historical datasets for migration; new APIs are tested in
    test_structured.py, including the production 410 response.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    legacy=FastAPI();legacy.router.routes=list(main.app.router.routes)
    return TestClient(legacy)


def dataset(pid):
    data=history.empty();text='以下为人工测试文本，不是历史原文。甲来到殿前。乙作出回应。';quote='甲来到殿前。'
    data['works']=[dict(id=pid,title='测试画作',artist='著录作者',circulation='画作流传',story_one_liner='测试故事')]
    data['background_episodes']=[dict(id='episode',work_id=pid,phase='画中',summary='甲来到殿前',sort_order=0)]
    data['persons']=[dict(id='person',canonical_name='甲')]
    data['work_persons']=[dict(work_id=pid,person_id='person',presence='画中',character_id='')]
    data['hist_sources']=[dict(id='source',title='人工测试书',genre='正史',edition='人工测试电子版',resource_uri='https://example.org/test',snapshot_text=text,verification_note='仅供单元测试，不宣称为史料')]
    start=text.index(quote)
    data['quotations']=[dict(id='quote',source_id='source',work_id=pid,episode_id='episode',locator='测试卷一',original_text=quote,source_start=start,source_end=start+len(quote))]
    data['inferences']=[dict(id='inference',work_id=pid,author='测试作者',publication='测试论文',claim='人工测试判断',quotation_id='quote')]
    data['person_lines']=[dict(id='line',work_id=pid,person_id='person',aspect='行事',line_text='甲来到殿前',grounding='原话',quotation_id='quote',inference_id=None,sort_order=0)]
    return history.normalize(pid,data)


def create(client):return client.post('/api/projects',json=dict(title='历史库测试')).json()
def read(client,p):return client.get(f"/api/projects/{p['id']}/history").json()
def save(client,p,tables):
    view=read(client,p)
    return client.put(f"/api/projects/{p['id']}/history/draft",json=dict(version=view['version'],baseRevision=view['revision'],baseDraftHash=view['draftHash'],tables=tables))
def confirm(client,p,version,**extra):return client.post(f"/api/projects/{p['id']}/history/confirm",json=dict(version=version,**extra))


def test_history_schema_and_drafts_do_not_publish_or_call_model(client,monkeypatch):
    async def forbidden(*a,**k):raise AssertionError('implicit model call')
    monkeypatch.setattr(studio_agent,'run',forbidden)
    p=create(client);view=read(client,p)
    assert set(view['tables'])==set(history_schema.TABLES) and not view['tables']['works']
    saved=save(client,p,dataset(p['id']));assert saved.status_code==200,saved.text
    assert not saved.json()['tables']['works'] and saved.json()['draft']['works']
    assert not saved.json()['issues']


def test_publish_eight_tables_and_immutable_audit(client):
    p=create(client);saved=save(client,p,dataset(p['id'])).json();result=confirm(client,p,saved['version'])
    assert result.status_code==200,result.text
    value=result.json();assert value['revision']==1 and value['draft'] is None
    with main.db() as c:
        for table in history_schema.TABLES:assert c.execute('SELECT COUNT(*) FROM '+table+' WHERE project_id=?',(p['id'],)).fetchone()[0]==1
        logs=[json.loads(r[0]) for r in c.execute('SELECT meta FROM events WHERE project=?',(p['id'],))]
    record=next(r for r in logs if 'historyAfter' in r)
    assert record['historyAfter']['quotations'][0]['original_text']=='甲来到殿前。'
    assert value['tables']['person_lines'][0]['grounding']=='原话'


@pytest.mark.parametrize('mutation',[
 lambda d:d['hist_sources'][0].update(genre='论文'),
 lambda d:d['hist_sources'][0].update(edition=''),
 lambda d:d['quotations'][0].update(original_text='甲来到殿上。'),
 lambda d:d['quotations'][0].update(episode_id='other-project-episode'),
 lambda d:d['inferences'][0].update(quotation_id=None),
 lambda d:d['inferences'][0].update(author=''),
 lambda d:d['person_lines'][0].update(inference_id='inference'),
 lambda d:d['person_lines'][0].update(grounding='推断',quotation_id=None,inference_id=None),
 lambda d:d['work_persons'][0].update(presence='未知'),
 lambda d:d['background_episodes'][0].update(phase='流传'),
])
def test_invalid_evidence_and_structure_remain_drafts(client,mutation):
    p=create(client);d=dataset(p['id']);mutation(d);saved=save(client,p,d)
    assert saved.status_code==200,saved.text
    assert confirm(client,p,saved.json()['version']).status_code==422
    assert not read(client,p)['tables']['works']


def test_same_ids_and_names_are_isolated_by_project(client):
    a=create(client);b=create(client)
    for p in (a,b):
        value=save(client,p,dataset(p['id'])).json();assert confirm(client,p,value['version']).status_code==200
    assert read(client,a)['tables']['persons'][0]['id']==read(client,b)['tables']['persons'][0]['id']
    with main.db() as c:assert c.execute('SELECT COUNT(*) FROM persons WHERE id=?',('person',)).fetchone()[0]==2
    bad=dataset(a['id']);bad['quotations'][0]['project_id']=b['id']
    assert save(client,a,bad).status_code==422


def test_stale_draft_and_project_versions_are_rejected(client):
    p=create(client);old=read(client,p);value=save(client,p,dataset(p['id'])).json()
    assert confirm(client,p,old['version']).status_code==409
    result=client.put(f"/api/projects/{p['id']}/history/draft",json=dict(version=value['version'],baseRevision=0,baseDraftHash=old['draftHash'],tables=dataset(p['id'])))
    assert result.status_code==409


def test_adoption_changes_drafts_only_and_pins_history_snapshot(client):
    p=create(client);before=main.get(p['id'])['workspace']['entities'];value=save(client,p,dataset(p['id'])).json();value=confirm(client,p,value['version']).json()
    assert main.get(p['id'])['workspace']['entities']==before
    adopted=client.post(f"/api/projects/{p['id']}/history/adopt",json=dict(version=value['version']));assert adopted.status_code==200
    mat=adopted.json()['workspace']['entities']['material:main']
    assert mat['published'] is None and mat['draft']['historySnapshot']['revision']==1
    assert mat['draft']['sources'][-1]['sourceType']=='historical_primary'
    assert 'snapshot_text' not in mat['draft']['historySnapshot']['tables']['hist_sources'][0]


def test_publish_rollback_keeps_original_tables_project_and_audit(client,monkeypatch):
    p=create(client);v=save(client,p,dataset(p['id'])).json();v=confirm(client,p,v['version']).json()
    d=copy.deepcopy(v['tables']);d['works'][0]['title']='新版';v=save(client,p,d).json();before=main.get(p['id'])
    real=history.publish
    def fail(conn,*args):real(conn,*args);raise ValueError('模拟事务中断')
    monkeypatch.setattr(history,'publish',fail)
    with pytest.raises(ValueError,match='事务中断'):confirm(client,p,v['version'])
    assert main.get(p['id'])==before and read(client,p)['tables']['works'][0]['title']=='测试画作'


def test_sql_foreign_keys_and_grounding_constraint_are_enforced(client):
    p=create(client);v=save(client,p,dataset(p['id'])).json();confirm(client,p,v['version'])
    with pytest.raises(sqlite3.IntegrityError):
        with main.db() as c:c.execute('UPDATE person_lines SET inference_id=? WHERE project_id=?',('inference',p['id']))
    with pytest.raises(sqlite3.IntegrityError):
        with main.db() as c:c.execute('UPDATE inferences SET quotation_id=? WHERE project_id=?',('missing',p['id']))


def test_legacy_migration_only_creates_unconfirmed_candidates(client):
    p=create(client);r=client.post(f"/api/projects/{p['id']}/history/legacy-candidates",json=dict(version=p['version']));assert r.status_code==200
    assert r.json()['draft']['works'] and not r.json()['tables']['works']
    assert not r.json()['draft']['hist_sources'] and not r.json()['draft']['quotations']


@pytest.mark.parametrize('field,value',[('snapshot_text',17),('resource_uri',[]),('revision',True)])
def test_malformed_types_rejected_without_server_error(client,field,value):
    p=create(client);d=dataset(p['id']);d['hist_sources'][0][field]=value
    assert save(client,p,d).status_code==422


def test_migration_preserves_all_eight_history_tables_with_foreign_keys(client,tmp_path,monkeypatch):
    from backend import storage
    from scripts.migrate_sqlite_to_mysql import migrate
    p=create(client);v=save(client,p,dataset(p['id'])).json();assert confirm(client,p,v['version']).status_code==200
    source=main.DATA/'projects.sqlite'
    with main.db() as c:ddl=[r[0] for r in c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL")]
    target=tmp_path/'target.sqlite'
    with sqlite3.connect(target) as c:
        for statement in ddl:c.execute(statement)
    def connection(data):
        c=sqlite3.connect(target);c.execute('PRAGMA foreign_keys=ON');return c
    monkeypatch.setattr(storage,'backend',lambda:'mysql');monkeypatch.setattr(storage,'connect',connection)
    report=migrate(source)
    assert all(report['counts'][name]==1 for name in history_schema.TABLES)
    assert migrate(source,verify_only=True)['verified']
    with pytest.raises(ValueError,match='非空'):migrate(source)


def test_mysql_history_ddl_compiles_without_connecting():
    sqlalchemy=pytest.importorskip('sqlalchemy')
    from sqlalchemy.dialects.mysql import LONGTEXT,dialect
    from sqlalchemy.schema import CreateTable
    meta=sqlalchemy.MetaData();sqlalchemy.Table('projects',meta,sqlalchemy.Column('id',sqlalchemy.String(128),primary_key=True))
    history_schema.mysql_tables(meta,lambda name,*c:sqlalchemy.Table(name,meta,*c),None,lambda name:sqlalchemy.Column(name,LONGTEXT))
    for name in history_schema.TABLES:
        text=str(CreateTable(meta.tables[name]).compile(dialect=dialect()))
        assert 'FOREIGN KEY' in text and 'project_id' in text
