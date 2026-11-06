import base64
import copy
import io
import json
import zipfile
from PIL import Image
import pytest
from backend import main, experiments as exp
from test_merged_features import merged_client, ready


def start(c,p,request_id='start',client='researcher-tab'):
    r=c.post('/api/experiments/start',json=dict(requestId=request_id,clientId=client,name='P01',projectId=p['id'],page='library'))
    assert r.status_code==200,r.text
    return r.json()


def event(run,kind,page='library',elapsed=1000,data=None,**extra):
    return dict(id=extra.pop('id',exp.new_id()),kind=kind,page=page,projectId=run['projectId'],clientId=extra.pop('clientId','researcher-tab'),sequence=extra.pop('sequence',0),elapsedMs=elapsed,data=data or {},**extra)


def batch(c,run,rows):return c.post(f"/api/experiments/{run['id']}/events",json=dict(events=rows))

def end(c,run,elapsed=10000):return c.post(f"/api/experiments/{run['id']}/end",json=dict(requestId='end',elapsedMs=elapsed))


@pytest.fixture
def research(merged_client,monkeypatch):
    c=merged_client;p,_=ready(c);clock=[1_000_000];monkeypatch.setattr(exp,'now',lambda:clock[0])
    return c,p,clock


def test_start_is_explicit_idempotent_and_does_not_change_project(research):
    c,p,clock=research;before=main.get(p['id']);r=start(c,p)
    assert start(c,p)['id']==r['id'] and main.get(p['id'])==before
    assert c.post('/api/experiments/start',json=dict(requestId='different',clientId='researcher-tab',projectId=p['id'])).status_code==409
    clock[0]+=10000;assert end(c,r).status_code==200
    report=c.get('/api/experiments/'+r['id']).json()
    assert report['durationMs']==10000 and report['foregroundMs']==0 and report['outputs']==[]


def test_time_frequency_order_and_overlapping_tabs_are_aggregated_without_double_count(research):
    c,p,clock=research;r=start(c,p);clock[0]+=20000
    rows=[event(r,'navigation',elapsed=0),event(r,'dwell',elapsed=5000,data=dict(fromMs=0,toMs=5000)),event(r,'dwell',elapsed=7000,data=dict(fromMs=3000,toMs=7000),clientId='other-tab'),event(r,'click',elapsed=6000,data=dict(label='整理资料')),event(r,'input_change',elapsed=6500,data=dict(before='甲',value='乙')),event(r,'agent_submit',elapsed=6800,data=dict(instruction='合并两位人物')),event(r,'navigation',page='outline',elapsed=10000),event(r,'dwell',page='outline',elapsed=14000,data=dict(fromMs=10000,toMs=14000))]
    assert batch(c,r,rows).status_code==200
    assert batch(c,r,rows).status_code==200
    assert end(c,r,20000).status_code==200
    report=c.get('/api/experiments/'+r['id']).json();assert report['foregroundMs']==11000 and report['durationMs']==20000
    modules={m['page']:m for m in report['modules']};assert modules['library']['foregroundMs']==7000
    assert (modules['library']['clicks'],modules['library']['inputs'],modules['library']['agentMessages'])==(1,1,1)
    assert [row['page'] for row in report['order']]==['library','outline'] and report['eventCount']==len(rows)


def test_full_input_contents_and_sensitive_fields_are_handled_separately(research):
    c,p,clock=research;r=start(c,p);clock[0]+=1000
    text='用户输入的完整修改方向。'*2000
    row=event(r,'input_change',data=dict(value=text,password='hidden-password',nested=dict(api_key='hidden-key')))
    assert batch(c,r,[row]).status_code==200
    result=c.get(f"/api/experiments/{r['id']}/events").json()['events'][0]
    assert result['data']['value']==text
    dump=json.dumps(result);assert 'hidden-password' not in dump and 'hidden-key' not in dump
    conflict=dict(row,data=dict(value='不同内容'));assert batch(c,r,[conflict]).status_code==409


def test_server_saves_track_final_and_overwritten_versions_only_during_run(research):
    c,p,clock=research;r=start(c,p);path=f"/api/projects/{p['id']}/studio/draft";old=copy.deepcopy(p['workspace']['entities']['plot:p']['draft'])
    headers={'X-Experiment-Id':r['id'],'X-Experiment-Client':'researcher-tab','X-Experiment-Request':'save-1','X-Experiment-Page':'outline'}
    clock[0]+=1000
    response=c.put(path,headers=headers,json=dict(version=p['version'],kind='plot',id='p',data=dict(old,body='实验中新写的剧情')))
    assert response.status_code==200,response.text;p=response.json()
    clock[0]+=1000
    response=c.put(path,headers=dict(headers,**{'X-Experiment-Request':'save-2'}),json=dict(version=p['version'],kind='plot',id='p',data=old));assert response.status_code==200
    p=response.json();clock[0]+=1000;assert end(c,r,3000).status_code==200
    report=c.get('/api/experiments/'+r['id']).json();assert report['versionCount']==2
    versions=c.get(f"/api/experiments/{r['id']}/versions").json()
    assert versions[0]['content']['entities']['plot:p']['draft']['body']=='实验中新写的剧情'
    assert versions[1]['content']['entities']['plot:p']['draft']['body']==old['body']
    before=report['eventCount'];clock[0]+=1000
    response=c.put(path,headers=headers,json=dict(version=p['version'],kind='plot',id='p',data=dict(old,body='实验结束后的修改')));assert response.status_code==200
    assert c.get('/api/experiments/'+r['id']).json()['eventCount']==before
    assert all('实验结束后的修改' not in json.dumps(v,ensure_ascii=False) for v in c.get(f"/api/experiments/{r['id']}/versions").json())


def test_end_freezes_outputs_and_new_events_but_accepts_exact_retries(research):
    c,p,clock=research;r=start(c,p);clock[0]+=1000;row=event(r,'click',data=dict(label='展开详情'));assert batch(c,r,[row]).status_code==200
    assert end(c,r,1000).status_code==200
    assert end(c,r,1000).status_code==200
    assert batch(c,r,[row]).status_code==200
    assert batch(c,r,[event(r,'click',elapsed=1100)]).status_code==409
    output=c.get(f"/api/experiments/{r['id']}/outputs").json()
    p['workspace']['entities']['plot:p']['draft']['body']='结束后改写';main.save(p,p['version'],'studio:outside-experiment')
    assert c.get(f"/api/experiments/{r['id']}/outputs").json()==output


def test_session_can_span_projects_and_tracks_a_new_project_creation(research):
    c,p,clock=research;r=start(c,p);clock[0]+=1000
    headers={'X-Experiment-Id':r['id'],'X-Experiment-Client':'researcher-tab','X-Experiment-Request':'create','X-Experiment-Page':'overview'}
    response=c.post('/api/projects',headers=headers,json=dict(title='实验中新建'));assert response.status_code==200
    new=response.json();clock[0]+=1000;assert end(c,r,2000).status_code==200
    outputs=c.get(f"/api/experiments/{r['id']}/outputs").json();assert any(o['projectId']==new['id'] and o['change']=='created' for o in outputs)


def test_bad_dwell_intervals_are_rejected_and_end_clamps_to_real_time(research):
    c,p,clock=research;r=start(c,p);clock[0]+=5000
    bad=event(r,'dwell',elapsed=5000,data=dict(fromMs=100,toMs=40000));assert batch(c,r,[bad]).status_code==422
    assert end(c,r,100_000_000).status_code==200
    report=c.get('/api/experiments/'+r['id']).json();assert report['durationMs']==5000 and report['foregroundMs']==0


def test_selected_screenshot_and_notes_export_with_timeline(research):
    c,p,clock=research;r=start(c,p);image=io.BytesIO();Image.new('RGB',(160,90),'#ddcc99').save(image,format='PNG')
    payload=dict(id='note-'+exp.new_id(),projectId=p['id'],runId=r['id'],page='library',text='这里不知道应该先点哪个按钮',category='discomfort',image='data:image/png;base64,'+base64.b64encode(image.getvalue()).decode(),region=dict(x=.2,y=.3,w=.4,h=.2),elapsedMs=500)
    response=c.post('/api/experiment-notes',json=payload);assert response.status_code==200,response.text
    assert c.post('/api/experiment-notes',json=payload).json()['id']==response.json()['id']
    assert c.post('/api/experiment-notes',json=dict(payload,text='不同便笺')).status_code==409
    original=c.get(response.json()['imageUrl']);assert Image.open(io.BytesIO(original.content)).size==(160,90)
    clock[0]+=1000;end(c,r,1000)
    exported=c.get(f"/api/experiments/{r['id']}/export?format=zip");assert exported.status_code==200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as z:
        data=json.loads(z.read('experiment.json'));assert data['notes'][0]['text']==payload['text']
        assert 'notes/'+payload['id']+'.png' in z.namelist() and 'events.csv' in z.namelist()
    assert c.get(f"/api/experiments/{r['id']}/export?format=csv").content.startswith(b'\xef\xbb\xbf')


def test_standalone_notes_work_without_starting_an_experiment(research):
    c,p,_=research;payload=dict(id='standalone-'+exp.new_id(),projectId=p['id'],page='experience',text='原画进入分镜时的反馈')
    response=c.post('/api/experiment-notes',json=payload);assert response.status_code==200
    assert c.get('/api/experiments').json()==[]
    assert c.get('/api/experiment-notes',params=dict(projectId=p['id'])).json()[0]['text']==payload['text']
    assert c.get(response.json().get('imageUrl') or '/api/experiment-notes/'+payload['id']+'/image').status_code==404


def test_timeline_filters_apply_before_pagination(research):
    c,p,clock=research;r=start(c,p);clock[0]+=10000
    rows=[event(r,'click',elapsed=i*20) for i in range(100)];assert batch(c,r,rows).status_code==200
    rows=[event(r,'input_change',elapsed=4000+i,data=dict(value=str(i))) for i in range(3)];assert batch(c,r,rows).status_code==200
    result=c.get(f"/api/experiments/{r['id']}/events?kind=input_change&limit=2").json()
    assert result['total']==3 and len(result['events'])==2 and all(e['kind']=='input_change' for e in result['events'])


def test_read_projection_refresh_is_not_a_new_content_output():
    before=dict(entities={'material:main':dict(kind='material',id='main',state='confirmed',draft=dict(structured=dict(people=[])),published=None)})
    after=copy.deepcopy(before);after['entities']['material:main']['draft']['structured'].update(summaryBlocks=dict(people=dict(text='阅读摘要')),personRedirects={})
    assert exp.output_diff(before,after,'project')==[]
    after['entities']['material:main']['draft']['structured']['summaryOverrides']={'people':'用户明确修改的摘要'}
    assert len(exp.output_diff(before,after,'project'))==1
