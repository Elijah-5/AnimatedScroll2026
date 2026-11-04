import copy
import json
import asyncio
import threading
from fastapi.testclient import TestClient
from backend import main,revisions,studio_agent
from test_merged_features import ready
from test_parallel_tasks import finish_studio


def test_idle_poll_skips_workspace_decoration_and_never_writes(client,monkeypatch):
    p,_=ready(client);before=main.get(p['id'])
    def forbidden(*a,**kw):raise AssertionError('idle poll rebuilt a workspace')
    with monkeypatch.context() as patch:
        patch.setattr(revisions,'decorate',forbidden)
        response=client.get(f"/api/projects/{p['id']}/studio/poll?version={p['version']}")
        assert response.status_code==200,response.text
        value=response.json();assert value['changed'] is False and 'project' not in value and len(response.content)<5000
    assert main.get(p['id'])==before


def test_poll_delivers_current_project_only_after_version_changes(client):
    p,_=ready(client);old=p['version'];current=main.get(p['id']);current['title']='并行改名';main.save(current,old,'studio:test_external_edit')
    response=client.get(f"/api/projects/{p['id']}/studio/poll?version={old}")
    assert response.status_code==200;value=response.json()
    assert value['changed'] and value['version']==old+1 and value['project']['title']=='并行改名'
    assert value['project']['workspace']['revisionArchive']
    assert not client.get(f"/api/projects/{p['id']}/studio/poll?version={value['version']}").json()['changed']
    assert client.get('/api/projects/no-such-project/studio/poll?version=1').status_code==404


def test_poll_updates_running_jobs_without_forcing_a_project_reload(client,monkeypatch):
    started=threading.Event();release=threading.Event()
    async def fake(*args):
        started.set()
        while not release.is_set():await asyncio.sleep(.005)
        return dict(checks=[])
    monkeypatch.setattr(studio_agent,'run',fake)
    with TestClient(main.app) as c:
        p,_=ready(c);response=c.post(f"/api/projects/{p['id']}/studio/jobs",json=dict(version=p['version'],task='check'));assert response.status_code==200,response.text
        assert started.wait(2)
        try:
            value=c.get(f"/api/projects/{p['id']}/studio/poll?version={p['version']}").json()
            assert not value['changed'] and 'project' not in value and value['jobs'][0]['state']=='running'
        finally:release.set()
        current,job=finish_studio(c,p['id']);assert job['state']=='completed'
        assert c.get(f"/api/projects/{p['id']}/studio/poll?version={p['version']}").json()['changed']


def test_existing_revision_and_readonly_warning_walk_do_not_clone_whole_content(client,monkeypatch):
    p,_=ready(client);w=p['workspace'];r=w['entities']['material:main'];revisions.archive(w,'material:main',r)
    original=copy.deepcopy(w['revisionArchive'])
    def forbidden(*a,**kw):raise AssertionError('unnecessary published-content copy')
    with monkeypatch.context() as patch:
        patch.setattr(revisions.copy,'deepcopy',forbidden)
        revisions.archive(w,'material:main',r)
        assert revisions.warnings(w,r)==[]
    assert w['revisionArchive']==original
    exported=revisions.bases(w,'material:main');exported['material:main@'+str(r['revision'])]['data']['image']='caller mutation'
    assert r['published']['image']!='caller mutation'
