import asyncio
import importlib.util
import json
from pathlib import Path
import httpx
import pytest
from backend import model_client,acceptance_media,main,consumption


def test_budget_is_durable_counts_failures_and_does_not_log_secrets(tmp_path,monkeypatch):
    monkeypatch.setenv('CREATION_LIVE_RUN_DIR',str(tmp_path));monkeypatch.setenv('CREATION_LIVE_REQUEST_LIMIT','2')
    async def run():
        request=httpx.Request('POST','https://example.test/v1/chat/completions',headers={'Authorization':'Bearer SECRET'},json={'model':'m','messages':[{'content':'PRIVATE'}]})
        await model_client.request_hook(request)
        response=httpx.Response(200,request=request,json={'model':'m','usage':{'total_tokens':5},'choices':[{'finish_reason':'stop'}]})
        await model_client.response_hook(response)
        await model_client.request_hook(httpx.Request('POST','https://example.test',json={'model':'m'}))
        with pytest.raises(ValueError,match='上限'):await model_client.request_hook(request)
    asyncio.run(run());raw=(tmp_path/'requests.json').read_text();data=json.loads(raw)
    assert len(data['requests'])==2 and data['requests'][1]['status']=='started'
    assert data['requests'][0]['usage']['total_tokens']==5 and 'SECRET' not in raw and 'PRIVATE' not in raw


def test_local_env_takes_priority_without_modifying_parent(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('control',Path(__file__).resolve().parents[1]/'scripts/server_control.py');control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)
    monkeypatch.setattr(control,'ROOT',tmp_path);monkeypatch.setenv('AIHUBMIX_API_KEY','inherited')
    (tmp_path/'.env').write_text('AIHUBMIX_API_KEY=local\nMODEL_PROVIDER=aihubmix\nUNRELATED=ignored\n')
    assert control.child_environment()['AIHUBMIX_API_KEY']=='local'
    import os
    assert os.environ['AIHUBMIX_API_KEY']=='inherited' and 'UNRELATED' not in control.child_environment()
    before=control.signature();(tmp_path/'.env').write_text('AIHUBMIX_API_KEY=changed\n');assert control.signature()!=before


def test_placeholder_requires_explicit_mode_and_current_dependencies(client,tmp_path,monkeypatch):
    p=client.post('/api/projects',json={'title':'test'}).json();folder=tmp_path/'acceptance-media';folder.mkdir();(folder/'fixture.mp4').write_bytes(b'fixture')
    (folder/'manifest.json').write_text(json.dumps({p['id']:{'shot':{'filename':'fixture.mp4','fingerprint':consumption.snapshot(p)}}}))
    monkeypatch.delenv('CREATION_ACCEPTANCE',raising=False)
    assert acceptance_media.fixture(p,tmp_path,'shot') is None
    assert client.get('/api/acceptance-media/fixture.mp4').status_code==404
    monkeypatch.setenv('CREATION_ACCEPTANCE','1');item=acceptance_media.fixture(p,tmp_path,'shot');assert item['kind']=='placeholder'
    assert client.get(item['videoUrl']).status_code==200
    (folder/'manifest.json').write_text(json.dumps({p['id']:{'shot':{'filename':'fixture.mp4','fingerprint':'outdated'}}}))
    assert acceptance_media.fixture(p,tmp_path,'shot') is None
    with main.db() as c:assert c.execute('SELECT COUNT(*) FROM video_jobs').fetchone()[0]==0
