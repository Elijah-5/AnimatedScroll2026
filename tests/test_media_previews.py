import copy
import io
import json
import time

import httpx
import pytest
from PIL import Image

from backend import main, media_previews as previews
from test_merged_features import ready, merged_client


@pytest.fixture
def media(merged_client,monkeypatch):
    monkeypatch.setenv('AIHUBMIX_API_KEY','fake-not-a-real-key')
    async def price(kind):
        return dict(model='wan3.0-video' if kind=='video' else 'verified-image' if kind=='image' else 'local-crop',
                    unitUsd=.04 if kind=='video' else .01 if kind=='image' else 0,fx=8,
                    endpoint='/ai/v1/videos' if kind=='video' else '/ai/v1/images',referenceField='input_references',
                    parameters=dict(duration=5,resolution='480p',generate_audio=False) if kind=='video' else {})
    monkeypatch.setattr(previews,'pricing',price)
    calls=[];png=io.BytesIO();Image.new('RGB',(320,240),'#a09060').save(png,format='PNG')
    def provider(request):
        calls.append(request)
        if request.method=='POST':return httpx.Response(200,json={'id':'remote-'+str(len(calls))})
        if request.url.path.endswith('/content'):
            return httpx.Response(200,content=png.getvalue() if '/images/' in request.url.path else b'\x00\x00\x00\x18ftypmp42'+b'0'*200)
        return httpx.Response(200,json={'status':'completed','output':[]})
    original=httpx.AsyncClient
    monkeypatch.setattr(previews.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(provider),**kw))
    p,_=ready(merged_client)
    return merged_client,p,calls


def quote(c,p,kind='video',ids=None,scope='narrative'):
    r=c.post(f"/api/projects/{p['id']}/media-previews/quote",json=dict(version=p['version'],scope=scope,storyboardIds=ids or ['c'],kind=kind))
    assert r.status_code==200,r.text
    return r.json()


def submit(c,p,q,rid='preview-request'):
    return c.post(f"/api/projects/{p['id']}/media-previews",json=dict(quoteId=q['quoteId'],requestId=rid))


def wait(c,p,jid):
    for _ in range(150):
        result=c.get(f"/api/projects/{p['id']}/media-previews").json()
        job=next(j for j in result['jobs'] if j['id']==jid)
        if job['status'] not in previews.ACTIVE:return job
        time.sleep(.01)
    raise AssertionError('preview worker did not finish')


def clone_shot(p,sid):
    es=p['workspace']['entities']
    clue=copy.deepcopy(es['clue:c']);clue['id']=sid;clue['draft']['name']=sid;clue['published']['name']=sid;es['clue:'+sid]=clue
    shot=copy.deepcopy(es['storyboard:c']);shot['id']=sid;shot['draft']['clueId']=sid;shot['published']['clueId']=sid
    for ref in shot.get('refs',[]):
        if ref['key']=='clue:c':ref['key']='clue:'+sid
    es['storyboard:'+sid]=shot


def test_quote_is_read_only_and_scope_is_enforced(media):
    c,p,calls=media;before=main.get(p['id']);q=quote(c,p)
    assert q['model']=='wan3.0-video' and q['duration']==5 and q['reservedCny']==2
    assert calls==[] and main.get(p['id'])==before
    assert c.get(f"/api/projects/{p['id']}/media-previews").json()['jobs']==[]
    assert c.post(f"/api/projects/{p['id']}/media-previews/quote",json=dict(version=p['version'],storyboardIds=['not-known'])).status_code==422


def test_submit_uses_reviewed_native_body_and_deduplicates(media):
    c,p,calls=media;q=quote(c,p);response=submit(c,p,q);assert response.status_code==200,response.text
    job=wait(c,p,response.json()['jobs'][0]['id']);assert job['status']=='succeeded'
    body=json.loads(next(r.content for r in calls if r.method=='POST'))
    assert body['resolution']=='480p' and body['duration']==5 and body['generate_audio'] is False
    assert body['input_references'][0]['url'].startswith('data:image/png;base64,')
    assert c.get(job['videoUrl']).status_code==200
    assert submit(c,p,q).json()['jobs'][0]['id']==job['id']
    other=quote(c,p)
    assert submit(c,p,other,'new-request').status_code==409
    assert len([r for r in calls if r.method=='POST'])==1
    assert 'providerBody' not in job


def test_batch_waits_for_review_and_reject_stops_unsubmitted(media):
    c,p,calls=media;clone_shot(p,'second');clone_shot(p,'third');p=main.save(p,p['version'],'studio:test_fixture')
    q=quote(c,p,ids=['c','second','third']);r=submit(c,p,q).json();first=r['jobs'][0];wait(c,p,first['id'])
    assert len([r for r in calls if r.method=='POST'])==1
    assert all(j['status']=='waiting_review' for j in r['jobs'][1:])
    endpoint=f"/api/projects/{p['id']}/media-previews/{first['id']}/review"
    assert c.post(endpoint,json={'accepted':True}).status_code==200
    second=wait(c,p,r['jobs'][1]['id']);assert second['status']=='succeeded'
    assert c.post(endpoint,json={'accepted':True}).status_code==200
    assert len([r for r in calls if r.method=='POST'])==2
    assert c.post(f"/api/projects/{p['id']}/media-previews/{second['id']}/review",json={'accepted':False}).status_code==200
    result=c.get(f"/api/projects/{p['id']}/media-previews").json()
    assert next(j for j in result['jobs'] if j['id']==r['jobs'][2]['id'])['status']=='skipped'
    assert result['budget']['reservedCny']==4


def test_budget_reserves_inflight_and_is_shared_across_projects(media):
    c,p,calls=media
    with main.db() as db:db.execute('INSERT INTO media_preview_jobs VALUES (?,?,?)',('existing','another-project',json.dumps(dict(status='pending',reservedCny=9))))
    q=quote(c,p)
    assert q['budget']['remainingCny']==1
    assert submit(c,p,q).status_code==422
    assert calls==[]


def test_unknown_submission_blocks_new_paid_work_but_allows_free_crop(media,monkeypatch):
    c,p,_=media;original=httpx.AsyncClient
    # The fixture already captured the real class; instantiate a replacement transport directly.
    def fail(request):raise httpx.ReadTimeout('response lost',request=request)
    from httpx import _client
    monkeypatch.setattr(previews.httpx,'AsyncClient',lambda **kw:_client.AsyncClient(transport=httpx.MockTransport(fail),**kw))
    q=quote(c,p);r=submit(c,p,q);job=wait(c,p,r.json()['jobs'][0]['id'])
    assert job['status']=='submission_unknown' and job['reservedCny']==2
    assert submit(c,p,quote(c,p,'image'),'another-paid-request').status_code==409
    free=submit(c,p,quote(c,p,'crop'),'free-request');assert free.status_code==200,free.text
    crop=wait(c,p,free.json()['jobs'][0]['id']);assert crop['status']=='succeeded'
    assert c.get(crop['imageUrl']).headers['content-type']=='image/png'


def test_stale_quote_cannot_generate_and_old_content_never_matches_new_media(media):
    c,p,calls=media;q=quote(c,p,'crop');r=submit(c,p,q);job=wait(c,p,r.json()['jobs'][0]['id'])
    c.post(f"/api/projects/{p['id']}/media-previews/{job['id']}/review",json={'accepted':True})
    old=copy.deepcopy(p)
    assert previews.media_for(old,'c',main.db,main.DATA)['narrationText']
    stale=quote(c,p)
    p['workspace']['entities']['storyboard:c']['published']['region']['x']+=.01
    p=main.save(p,p['version'],'studio:test_fixture')
    assert submit(c,p,stale,'stale-request').status_code==409 and calls==[]
    assert previews.media_for(p,'c',main.db,main.DATA) is None
    assert previews.media_for(old,'c',main.db,main.DATA)['previewJobId']==job['id']


def test_image_download_and_resume_never_resubmit(media):
    c,p,calls=media;q=quote(c,p,'image');r=submit(c,p,q);job=wait(c,p,r.json()['jobs'][0]['id'])
    assert job['kind']=='image' and job['status']=='succeeded'
    Image.open(io.BytesIO(c.get(job['imageUrl']).content)).verify()
    assert c.post(f"/api/projects/{p['id']}/media-previews/{job['id']}/resume",json={}).status_code==422
    assert len([r for r in calls if r.method=='POST'])==1


def test_price_parser_never_uses_token_defaults():
    assert previews.unit_price({'pricing':{'input':2,'output':2}},'video') is None
    row={'pricing_lines':[dict(billable='generate',unit='second',cost_usd=.04,variant={'size':'480p'}),dict(billable='generate',unit='second',cost_usd=.02,variant={'size':'1080p'})]}
    assert previews.unit_price(row,'video')[0]==.04


def test_sync_image_inline_result_needs_no_async_task_permission(media,monkeypatch):
    c,p,calls=media
    import base64
    out=io.BytesIO();Image.new('RGB',(300,200),'green').save(out,format='PNG')
    def sync(request):
        calls.append(request)
        assert request.method=='POST','inline image must never poll the async interface'
        return httpx.Response(200,json={'id':'sync-image','status':'completed','output':[{'b64_json':base64.b64encode(out.getvalue()).decode()}]})
    from httpx import _client
    monkeypatch.setattr(previews.httpx,'AsyncClient',lambda **kw:_client.AsyncClient(transport=httpx.MockTransport(sync),**kw))
    r=submit(c,p,quote(c,p,'image'));j=wait(c,p,r.json()['jobs'][0]['id'])
    assert j['status']=='succeeded' and len(calls)==1
    assert c.get(j['imageUrl']).status_code==200


def test_download_failure_only_downloads_again(media,monkeypatch):
    c,p,calls=media;attempts=[]
    def provider(request):
        attempts.append(request.method+' '+request.url.path)
        if request.method=='POST':return httpx.Response(200,json={'id':'one-remote'})
        if request.url.path.endswith('/content'):
            if sum(s.endswith('/content') for s in attempts)==1:return httpx.Response(502)
            return httpx.Response(200,content=b'\x00\x00\x00\x18ftypmp42'+b'0'*200)
        return httpx.Response(200,json={'status':'completed','output':[]})
    from httpx import _client
    monkeypatch.setattr(previews.httpx,'AsyncClient',lambda **kw:_client.AsyncClient(transport=httpx.MockTransport(provider),**kw))
    r=submit(c,p,quote(c,p));j=wait(c,p,r.json()['jobs'][0]['id']);assert j['status']=='download_failed'
    assert c.post(f"/api/projects/{p['id']}/media-previews/{j['id']}/resume",json={}).status_code==200
    assert wait(c,p,j['id'])['status']=='succeeded'
    assert sum(s.startswith('POST') for s in attempts)==1


def test_prompt_batch_default_scope_and_all_scope_are_enforced(media,monkeypatch):
    c,p,_=media
    from backend import studio_agent
    from test_completions import provider
    monkeypatch.setattr(studio_agent,'run',provider)
    base=f"/api/projects/{p['id']}/studio/generation-batches"
    invalid=c.post(base,json=dict(version=p['version'],requestId='bad-scope',page='storyboards',targets=['not-known']))
    assert invalid.status_code==422
    r=c.post(base,json=dict(version=p['version'],requestId='narrative-default',page='storyboards'))
    assert r.status_code==200,r.text
    assert r.json()['targets']==['c'] and r.json()['clueScope']=='narrative'
    for _ in range(100):
        job=c.get(base+'/'+r.json()['id']).json()
        if job['state'] not in ('running','queued'):break
        time.sleep(.01)
    p=main.get(p['id'])
    r=c.post(base,json=dict(version=p['version'],requestId='all-scope',page='storyboards',clueScope='all',targets=['not-known']))
    assert r.status_code==200,r.text
    assert r.json()['targets']==['not-known'] and r.json()['clueScope']=='all'


def test_compat_image_after_known_permission_rejection_is_explicit_and_single_reference(media,monkeypatch):
    c,p,calls=media
    with main.db() as db:db.execute('INSERT INTO media_preview_jobs VALUES (?,?,?)',('permission-rejected','other',json.dumps(dict(status='failed',reservedCny=0,errorCode='async_not_enabled'))))
    async def price(kind):return dict(model='fixed-price-image',unitUsd=.01,inputUnitUsd=.003,fx=8,endpoint='/ai/v1/images/generations',compatEndpoint='/v1/images/edits',referenceField='images',parameters={'size':'1K','async':False,'response_format':'b64_json'})
    monkeypatch.setattr(previews,'pricing',price)
    import base64
    out=io.BytesIO();Image.new('RGB',(300,200),'green').save(out,format='PNG')
    def compat(request):
        calls.append(request)
        assert request.url.path=='/v1/images/edits'
        assert request.headers['content-type'].startswith('multipart/form-data')
        assert b'name="image"' in request.content and b'name="async"' not in request.content
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(out.getvalue()).decode()}]})
    from httpx import _client
    monkeypatch.setattr(previews.httpx,'AsyncClient',lambda **kw:_client.AsyncClient(transport=httpx.MockTransport(compat),**kw))
    q=quote(c,p,'image');assert q['items'][0]['referenceCount']==1
    assert q['reservedCny']==.13
    r=submit(c,p,q);assert r.status_code==200,r.text
    assert wait(c,p,r.json()['jobs'][0]['id'])['status']=='succeeded' and len(calls)==1
