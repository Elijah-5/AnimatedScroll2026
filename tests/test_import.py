import io
import time
from PIL import Image
from pypdf import PdfWriter
from fastapi.testclient import TestClient
from backend import main,vision

def png():
    b=io.BytesIO();Image.new('RGB',(200,100),'white').save(b,format='PNG');return b.getvalue()

def wait(client,pid):
    for _ in range(100):
        rows=client.get(f'/api/projects/{pid}/tasks').json()
        if rows and rows[0]['status'] not in ('queued','running'):return rows[0]
        time.sleep(.01)
    raise AssertionError('task did not finish')

def test_generic_empty_project(client):
    p=client.post('/api/projects').json()
    assert p['title']=='未命名项目'
    assert not p['characters'] and not p['sources'] and not p['image']

def test_text_import_and_page(client):
    p=client.post('/api/projects').json();path='/api/projects/'+p['id']
    r=client.post(path+f"/documents?version={p['version']}",files={'file':('资料.txt','资料原文'.encode(),'text/plain')})
    assert r.status_code==200
    p=r.json();assert p['sources'][0]['confirmed'] is False
    assert p['sources'][0]['text']=='资料原文'
    d=p['documents'][0]
    assert '资料原文' in client.get(path+f"/documents/{d['id']}/pages/1").text

def test_pdf_import_scan_page(client):
    p=client.post('/api/projects').json();writer=PdfWriter();writer.add_blank_page(width=100,height=100);b=io.BytesIO();writer.write(b)
    r=client.post(f"/api/projects/{p['id']}/documents?version=1",files={'file':('scan.pdf',b.getvalue(),'application/pdf')})
    assert r.status_code==200
    assert r.json()['documents'][0]['pageCount']==1
    assert not r.json()['sources']

def test_image_name_and_version(client):
    p=client.post('/api/projects').json();path='/api/projects/'+p['id']
    r=client.post(path+'/image?version=1',files={'file':('新画.png',png(),'image/png')})
    assert r.status_code==200
    assert r.json()['title']=='新画' and r.json()['imageVersion']==1

def test_zhekan(client):
    p=client.post('/api/sample?example=zhekan').json()
    assert len(p['characters'])==4 and not p['annotations']
    assert p['painting']['paintingPeriod']=='宋代'
    assert all(not s['confirmed'] for s in p['sources'])
    assert '未成功劝服' in p['sources'][-1]['text']

def test_task_detect_and_match(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.setattr(vision,'detect',lambda path,progress:[dict(id='instance1',x=.1,y=.1,w=.2,h=.3,kind='character',description='',characterId='',confirmed=False)])
    with TestClient(main.app) as client:
        p=client.post('/api/sample?example=zhekan').json();path='/api/projects/'+p['id']
        r=client.post(path+'/tasks',json={'version':p['version'],'kind':'detect'})
        assert r.status_code==200
        assert wait(client,p['id'])['status']=='completed'
        p=client.get(path).json();assert p['annotations'][0]['id']=='instance1'
        async def match(*args):return {'matches':[dict(annotationId='instance1',characterId=p['characters'][0]['id'],reason='候选') ]}
        monkeypatch.setattr(vision,'ask',match)
        assert client.post(path+'/tasks',json={'version':p['version'],'kind':'match'}).status_code==200
        assert wait(client,p['id'])['status']=='completed'
        result=client.get(path).json();assert result['matches'][0]['confirmed'] is False

def test_variable_scene_count(client):
    p=client.post('/api/projects').json();p['sceneCount']=5
    assert client.put('/api/projects/'+p['id'],json=p).json()['sceneCount']==5
    p['sceneCount']=13
    assert client.put('/api/projects/'+p['id'],json=p).status_code==422


def test_ocr_partial_result(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    async def ocr(*args):return {'text':'使其言是，不可诛；其言非，固当容之。'}
    monkeypatch.setattr(vision,'ask',ocr)
    with TestClient(main.app) as client:
        p=client.post('/api/projects').json();path='/api/projects/'+p['id']
        p=client.post(path+'/documents?version=1',files={'file':('scan.png',png(),'image/png')}).json()
        task=client.post(path+'/tasks',json=dict(version=p['version'],kind='ocr',documentId=p['documents'][0]['id'],pages=[1]))
        assert task.status_code==200
        assert wait(client,p['id'])['status']=='completed'
        p=client.get(path).json();assert p['sources'][0]['method']=='ocr'
        assert p['sources'][0]['confirmed'] is False


def test_task_stale_input(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    def detect(*args):
        p=main.get(pid);p['title']='concurrent';main.save(p,p['version'],'test_edit')
        return []
    monkeypatch.setattr(vision,'detect',detect)
    with TestClient(main.app) as client:
        p=client.post('/api/sample?example=zhekan').json();pid=p['id'];path='/api/projects/'+pid
        client.post(path+'/tasks',json=dict(version=p['version'],kind='detect'))
        assert wait(client,pid)['status']=='stale'
        assert client.get(path).json()['title']=='concurrent'


def test_moved_box_invalidates_visual_identity():
    import copy
    from backend.domain import reconcile
    from backend.zhekan import sample
    old=sample('image');old['annotations']=[dict(id='a',x=.1,y=.1,w=.2,h=.2)]
    old['observations']=[dict(annotationId='a',confirmed=True)]
    old['matches']=[dict(annotationId='a',confirmed=True)]
    new=copy.deepcopy(old);new['annotations'][0]['x']=.2
    result=reconcile(old,new)
    assert not result['observations'][0]['confirmed'] and result['observations'][0]['stale']
    assert not result['matches'][0]['confirmed']


def test_creative_brief_is_not_historical_evidence():
    from backend.domain import citation_errors
    from backend.zhekan import sample
    p=sample('image');s=p['sources'][-1];s['confirmed']=True
    unit=dict(text='互动失败',kind='event',category='supported',references=[dict(sourceId=s['id'],sourceVersion=1,quote=s['text'])])
    assert '创作设想不能作为历史依据' in citation_errors(unit,p)
