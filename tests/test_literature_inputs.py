import copy
import json
import hashlib
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from backend import main,documents,structured,consumption
from test_import import png,wait
from test_merged_features import ready

TEXT='🖼《测试图》画中甲与乙相对。\n原文保留全角标点。'

def create(client):return client.post('/api/projects',json=dict(title='测试图')).json()
def text(client,p,**extra):return client.post(f"/api/projects/{p['id']}/documents/text",json=dict(version=p['version'],title='测试文献',citation='手工提供的出处，未独立核对',text=TEXT,**extra))

def test_text_import_is_exact_unconfirmed_and_never_calls_a_model(client,monkeypatch):
    async def forbidden(*a,**kw):raise AssertionError('implicit model')
    monkeypatch.setattr(documents,'ask',forbidden);monkeypatch.setattr(structured,'ask',forbidden)
    p=create(client);response=text(client,p);assert response.status_code==200,response.text
    result=response.json();p=result['project'];source=p['sources'][0];doc=p['documents'][0]
    assert source['text']==TEXT and source['confirmed'] is False and source['citation']==doc['citation']
    assert doc['format']=='text' and doc['parseStatus']=='ready' and doc['inputMode']=='text'
    assert doc['contentHash']==hashlib.sha256(TEXT.encode()).hexdigest()
    assert client.get(f"/api/projects/{p['id']}/documents/{doc['id']}/pages/1").text==TEXT
    selected=documents.selected_sources(p,dict(documents=[dict(documentId=doc['id'],pages=[])]))
    assert selected[0]['source']['text']==TEXT


def test_identical_text_reuses_document_and_version_conflicts_do_not_duplicate(client):
    p=create(client);result=text(client,p).json();saved=result['project']
    assert text(client,p).status_code==409
    repeated=text(client,saved);assert repeated.status_code==200 and repeated.json()['reused']
    assert repeated.json()['project']['version']==saved['version'] and len(repeated.json()['project']['documents'])==1


def test_editing_text_keeps_source_id_and_preserves_old_published_evidence(client):
    p,_=ready(client);old=copy.deepcopy(consumption.confirmed(p,'material','main'));result=text(client,p).json();p=result['project'];doc=p['documents'][-1];source=next(s for s in p['sources'] if s.get('documentId')==doc['id']);filename=doc['filename']
    body=dict(version=p['version'],documentId=doc['id'],sourceVersion=source['version'],title=doc['title'],citation=doc['citation'],text=TEXT+'新补充。')
    response=client.post(f"/api/projects/{p['id']}/documents/text",json=body);assert response.status_code==200,response.text
    updated=response.json()['project'];new=next(s for s in updated['sources'] if s['id']==source['id'])
    assert new['version']==source['version']+1 and len(updated['documents'])==1
    assert (main.DATA/filename).read_text()==TEXT and consumption.confirmed(updated,'material','main')==old
    body['version']=updated['version'];assert client.post(f"/api/projects/{p['id']}/documents/text",json=body).status_code==409


@pytest.mark.parametrize('value',['',' \n\t'])
def test_empty_text_is_rejected_without_saving(client,value):
    p=create(client);response=client.post(f"/api/projects/{p['id']}/documents/text",json=dict(version=p['version'],text=value));assert response.status_code==422
    assert main.get(p['id'])['version']==p['version'] and not main.get(p['id'])['documents']


def test_failed_text_transaction_removes_only_new_file_and_keeps_original(client,monkeypatch):
    p=create(client);before={path.name for path in main.DATA.iterdir()};version=p['version']
    # Force a real optimistic conflict after the endpoint has prepared its file.
    from backend import pipeline
    original=pipeline.reconcile
    def concurrent(old,new):
        current=main.get(p['id']);main.save(current,current['version'],'studio:concurrent_test')
        return original(old,new)
    monkeypatch.setattr(pipeline,'reconcile',concurrent)
    response=text(client,p);assert response.status_code==409,response.text
    current=main.get(p['id']);assert current['version']==version+1 and not current['documents']
    assert not any(path.suffix=='.txt' and path.name not in before for path in main.DATA.iterdir())


def test_text_editor_buffer_is_saved_as_draft_but_not_sent_or_exported_as_evidence(client):
    from backend import studio,narrative
    from test_studio import draft,confirm
    p,_=ready(client);d=copy.deepcopy(p['workspace']['entities']['material:main']['draft']);d['literatureInput']=dict(title='尚未导入',text='未保存为文献的编辑区XYZ',citation='',documentId='',sourceVersion=0)
    p=draft(client,p,'material','main',d);assert p['workspace']['entities']['material:main']['draft']['literatureInput']['text']=='未保存为文献的编辑区XYZ'
    assert not p['documents'];p=confirm(client,p,'material','main').json()
    assert bool('未保存为文献的编辑区XYZ' not in json.dumps(studio.context(p,'plots'),ensure_ascii=False))
    assert bool('未保存为文献的编辑区XYZ' not in json.dumps(narrative.package(p,main.DATA,[]),ensure_ascii=False))


def test_export_keeps_confirmed_text_file_instead_of_newer_unpublished_edit(client):
    from backend import narrative
    from test_studio import draft,confirm
    p,_=ready(client);result=text(client,p).json();p=result['project'];doc=p['documents'][-1];source=next(s for s in p['sources'] if s.get('documentId')==doc['id'])
    value=copy.deepcopy(p['workspace']['entities']['material:main']['draft']);next(s for s in value['sources'] if s['id']==source['id'])['confirmed']=True
    p=draft(client,p,'material','main',value);p=confirm(client,p,'material','main').json()
    response=client.post(f"/api/projects/{p['id']}/documents/text",json=dict(version=p['version'],documentId=doc['id'],sourceVersion=source['version'],title=doc['title'],citation=doc['citation'],text='未发布的新原文XYZ'))
    assert response.status_code==200,response.text;p=response.json()['project']
    bundle=narrative.package(p,main.DATA,[]);files=[d['filename'] for d in bundle['documents'] if d['id']==doc['id']]
    assert files==[doc['filename']] and (main.DATA/files[0]).read_text()==TEXT
    assert bool('未发布的新原文XYZ' not in json.dumps(bundle,ensure_ascii=False))


@pytest.mark.parametrize('mode',['file','text'])
def test_file_and_text_use_identical_analysis_schema_and_structured_stage(tmp_path,monkeypatch,mode):
    monkeypatch.setattr(main,'DATA',tmp_path)
    async def fake(schema,payload,stats,validator=None):
        if schema is documents.Extracted:
            passage=payload['passages'][0]
            value=dict(claims=[dict(kind='background',text='资料描述画中人物相对。',assertion='description',references=[dict(sourceId=passage['sourceId'],quote=passage['text'])],indirectSource='')],people=[])
        elif schema is documents.Topics:value=dict(assignments=[dict(claimId='C1',topic='culture')])
        else:value=dict(paragraphs=[dict(text='资料描述画中人物相对。',claimIds=['C1'])])
        return validator(value) if validator else value
    monkeypatch.setattr(documents,'ask',fake)
    with TestClient(main.app) as c:
        p=create(c);p=c.post(f"/api/projects/{p['id']}/image?version={p['version']}",files=dict(file=('测试图.png',png(),'image/png'))).json()
        if mode=='file':p=c.post(f"/api/projects/{p['id']}/documents?version={p['version']}",files=dict(file=('测试文献.txt',TEXT.encode(),'text/plain'))).json()
        else:p=text(c,p).json()['project']
        doc=p['documents'][0];response=c.post(f"/api/projects/{p['id']}/tasks",json=dict(version=p['version'],kind='document_analysis',targetArtwork='测试图',documents=[dict(documentId=doc['id'],pages=[])]));assert response.status_code==200,response.text
        task=wait(c,p['id']);assert task['status']=='completed',task
        p=main.get(p['id']);a=p['documentAnalysis'];assert set(('claims','people','summaries','selectedPages','coverage'))<=a.keys()
        ref=a['summaries']['background'][0]['references'][0];source=next(s for s in p['sources'] if s['id']==ref['sourceId'])
        assert source['text'][ref['start']:ref['end']]==ref['quote']==TEXT
        assert p['workspace']['entities']['material:main']['draft']['structured']['evidence']
        assert p['workspace']['entities']['material:main']['published'] is None and not p['characters']
