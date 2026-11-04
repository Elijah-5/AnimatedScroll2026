import copy,time
from fastapi.testclient import TestClient
from backend import main,workspace as ws,studio_agent,materials


def setup(client):
    p=client.post('/api/sample?example=zhekan').json();p=client.put('/api/projects/'+p['id'],json=p).json()
    return client.get('/api/projects/'+p['id']+'/studio').json()

def draft(client,p,kind,rid,data):
    r=client.put(f"/api/projects/{p['id']}/studio/draft",json=dict(version=p['version'],kind=kind,id=rid,data=data));assert r.status_code==200,r.text;return r.json()

def confirm(client,p,kind,rid,risk=False):
    return client.post(f"/api/projects/{p['id']}/studio/confirm",json=dict(version=p['version'],kind=kind,id=rid,generate=False,acceptRisk=risk))

def prepare(client):
    p=setup(client)
    for kind,rid in [('material','main')]+[('character',c['id']) for c in p['characters']]+[('intent','main')]:
        r=confirm(client,p,kind,rid);assert r.status_code==200,r.text;p=r.json()
    c=p['characters'][0]['id']
    p=draft(client,p,'clue','c',dict(name='折槛',summary='虚构过渡',type='narrative',parentId='narrative',plotIds=['p'],characterIds=[c],units=[dict(id='u',text='朱云略作停顿。',kind='action',category='fiction',rationale='虚构过渡',references=[])]))
    p=draft(client,p,'plot','p',dict(title='进谏',goal='呈现冲突',body='剧情',connection='',characterIds=[c],clueIds=['c'],region=None))
    p=confirm(client,p,'plot','p').json();p=confirm(client,p,'clue','c').json()
    return p,c


def test_deleting_character_retains_knowledge_as_deleted_history(client):
    p=setup(client);cid=p['characters'][0]['id']
    before=copy.deepcopy(p['workspace']['entities']['knowledge:'+cid]['draft'])
    response=client.post(f"/api/projects/{p['id']}/studio/delete",json=dict(version=p['version'],kind='character',id=cid,acceptRisk=True))
    assert response.status_code==200,response.text
    knowledge=response.json()['workspace']['entities']['knowledge:'+cid]
    assert knowledge['state']=='deleted' and knowledge['draft']==before

def test_migration_keeps_legacy_ids_and_units(client):
    old=client.post('/api/sample').json();p=client.get('/api/projects/'+old['id']+'/studio').json();w=p['workspace']
    assert w['schemaVersion']=='2.0'
    assert all('character:'+c['id'] in w['entities'] for c in old['characters'])
    for s in old['scenes']:
        assert w['entities']['clue:legacy-'+s['id']]['draft']['units']==s['units']
    assert not [r for r in w['entities'].values() if r['kind']=='knowledge' and ws.valid(r)]

def test_drafts_do_not_invalidate_and_discard_restores(client):
    p,c=prepare(client);old=copy.deepcopy(p);profile=p['workspace']['entities']['character:'+c]['draft'];profile['name']='新名字'
    p=draft(client,p,'character',c,profile)
    assert p['workspace']['entities']['plot:p']['state']=='confirmed'
    assert p['workspace']['entities']['character:'+c]['published']['name']==old['workspace']['entities']['character:'+c]['published']['name']
    p=client.post(f"/api/projects/{p['id']}/studio/discard",json=dict(version=p['version'],kind='character',id=c)).json()
    assert not ws.dirty(p['workspace']['entities']['character:'+c])

def test_publish_change_keeps_dependents_and_reports_exact_versions(client):
    p,c=prepare(client);profile=p['workspace']['entities']['character:'+c]['draft'];profile['name']='新名字';p=draft(client,p,'character',c,profile)
    plan=client.post(f"/api/projects/{p['id']}/studio/preview",json=dict(version=p['version'],kind='character',id=c)).json()
    assert not plan['requiresRisk'] and 'plot:p' in {a['key'] for a in plan['affected']}
    p=confirm(client,p,'character',c).json()
    assert p['workspace']['entities']['plot:p']['state']=='confirmed'
    assert p['workspace']['entities']['plot:p']['basisWarnings']
    assert p['workspace']['entities']['material:main']['state']=='confirmed'


def test_child_clue_review_does_not_invalidate_other_plots_or_cycle(client):
    p,c=prepare(client)
    p=draft(client,p,'clue','c2',dict(name='其他情节',type='narrative',parentId='narrative',content='另一段情节。',plotIds=['p2'],characterIds=[c],units=[]))
    p=draft(client,p,'plot','p2',dict(title='后续剧情',goal='另一个剧情',body='',connection='',characterIds=[c],clueIds=['c2'],region=None));p=confirm(client,p,'plot','p2').json()
    clue=p['workspace']['entities']['clue:c']['draft'];clue['summary']='改写';p=draft(client,p,'clue','c',clue)
    p=confirm(client,p,'clue','c',True).json()
    assert p['workspace']['entities']['plot:p']['state']=='confirmed'
    assert p['workspace']['entities']['plot:p2']['state']=='confirmed'
    assert p['workspace']['entities']['storyboard:c']['state']=='draft'
    p=confirm(client,p,'plot','p').json()
    assert p['workspace']['entities']['clue:c']['state']=='confirmed'


def test_one_shot_per_clue_and_no_final_publish(client):
    p,c=prepare(client)
    p=confirm(client,p,'clue','c').json()
    assert len([r for r in p['workspace']['entities'].values() if r['kind']=='storyboard'])==1
    check=client.get(f"/api/projects/{p['id']}/studio/checklist").json()
    assert check['ready'] is False and check['videoGenerated'] is False
    assert any(r['page']=='storyboards' for r in check['items'])

def test_folder_cycle_and_root_protection(client):
    p=setup(client);path=f"/api/projects/{p['id']}/studio/folders";fs=p['workspace']['folders']
    assert client.put(path,json=dict(version=p['version'],folders=fs[1:])).status_code==422
    fs+=[dict(id='a',name='a',type='culture',parentId='b'),dict(id='b',name='b',type='culture',parentId='a')]
    assert client.put(path,json=dict(version=p['version'],folders=fs)).status_code==422

def test_model_failure_keeps_confirmation(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    async def fail(*a,**k):raise ValueError('模拟模型失败')
    monkeypatch.setattr(materials,'organize',fail)
    with TestClient(main.app) as client:
        p=setup(client)
        r=client.post(f"/api/projects/{p['id']}/studio/confirm",json=dict(version=p['version'],kind='material',id='main',generate=True));assert r.status_code==200
        r=client.post(f"/api/projects/{p['id']}/studio/jobs",json=dict(version=r.json()['version'],task='culture'));assert r.status_code==200,r.text
        for _ in range(100):
            current=client.get(f"/api/projects/{p['id']}/studio").json()
            if current['workspace']['jobs'] and current['workspace']['jobs'][0]['state']=='failed':break
            time.sleep(.01)
        assert current['workspace']['entities']['material:main']['state']=='confirmed'
        assert current['workspace']['jobs'][0]['state']=='failed'

def test_version_conflict(client):
    p=setup(client);v=p['version'];p=draft(client,p,'intent','main',p['workspace']['entities']['intent:main']['draft'])
    r=client.post(f"/api/projects/{p['id']}/studio/confirm",json=dict(version=v,kind='material',id='main'))
    assert r.status_code==409


def test_ready_state_and_style_change_invalidates_prompt(client):
    p,c=prepare(client)
    for cid in [x['id'] for x in p['characters']]:
        p=confirm(client,p,'knowledge',cid).json()
    shot=p['workspace']['entities']['storyboard:c']['draft'];shot.update(region=dict(x=.1,y=.1,w=.3,h=.4),characterIds=[],participantsConfirmed=True,prompt='保留古画构图，衣袖轻动。',startFrame='静止原画',endFrame='回复静止',action='轻动',camera='固定',style='古画笔触')
    shot['promptConfigHash']=ws.config_hash(shot);p=draft(client,p,'storyboard','c',shot);r=confirm(client,p,'storyboard','c');assert r.status_code==200,r.text;p=r.json()
    report=client.get(f"/api/projects/{p['id']}/studio/checklist").json()
    assert report['ready'] is True,report
    shot=p['workspace']['entities']['storyboard:c']['draft'];shot['style']='改变风格';p=draft(client,p,'storyboard','c',shot)
    assert confirm(client,p,'storyboard','c').status_code==422
    assert not client.get(f"/api/projects/{p['id']}/studio/checklist").json()['ready']


def test_blank_clue_cannot_be_confirmed(client):
    p,c=prepare(client);d=p['workspace']['entities']['clue:c']['draft'];d['units'][0]['text']='';p=draft(client,p,'clue','c',d)
    assert confirm(client,p,'clue','c',True).status_code==422


def test_same_root_layout_does_not_invalidate_content(client):
    p,c=prepare(client);w=p['workspace'];w['folders'].append(dict(id='folder',name='分类',type='narrative',parentId='narrative',root=False))
    r=client.put(f"/api/projects/{p['id']}/studio/folders",json=dict(version=p['version'],folders=w['folders']));p=r.json()
    clue=p['workspace']['entities']['clue:c']['draft'];clue['parentId']='folder';p=draft(client,p,'clue','c',clue)
    plan=client.post(f"/api/projects/{p['id']}/studio/preview",json=dict(version=p['version'],kind='clue',id='c')).json()
    assert plan['affected']==[] and not plan['requiresRisk']


def test_full_button_driven_workflow_with_provider_fixture(tmp_path,monkeypatch):
    from backend import studio
    monkeypatch.setattr(main,'DATA',tmp_path)
    calls=[]
    async def organize(*args,**kwargs):return dict(segments=[],characters=[],eventFramework=[],summary='整理')
    async def provider(task,ctx):
        calls.append(task)
        u=dict(text='演示虚构动作',kind='action',category='fiction',speakerId='',rationale='测试',references=[])
        if task=='culture':return dict(clues=[dict(name='文化背景',summary='背景',characterIds=[],units=[u])])
        if task in ('plots','plot'):return dict(plots=[dict(title='剧情一',goal='目标',body='内容',connection='',characterIds=[],clues=[dict(name='剧情线索',summary='叙事',characterIds=[],units=[u])])])
        if task=='knowledge':return dict(assignments=[dict(characterId=c['id'],clueIds=[v['id'] for v in ctx['clues']],reason='依据身份与参与情况') for c in ctx['characters']])
        if task=='storyboard':return dict(prompt='衣袖轻动，固定镜头',startFrame='原画静止',endFrame='恢复静止',action='衣袖轻动',camera='固定',style='保留古画笔触')
        return dict(clues=[])
    monkeypatch.setattr(materials,'organize',organize);monkeypatch.setattr(studio_agent,'run',provider)
    with TestClient(main.app) as client:
        p=setup(client);path='/api/projects/'+p['id']
        def load():return client.get(path+'/studio').json()
        def wait_done():
            for _ in range(200):
                value=load();jobs=value['workspace']['jobs']
                if jobs and jobs[0]['state'] not in ('running','queued'):
                    assert jobs[0]['state']=='completed',jobs[0];return value
                time.sleep(.01)
            raise AssertionError('job did not complete')
        # Reads, drafts, and navigation checks do not invoke the provider.
        client.get(path+'/studio/checklist');assert calls==[]
        r=client.post(path+'/studio/confirm',json=dict(version=p['version'],kind='material',id='main',generate=True));assert r.status_code==200
        r=client.post(path+'/studio/jobs',json=dict(version=r.json()['version'],task='culture'));assert r.status_code==200;p=wait_done()
        for c in p['characters']:p=confirm(client,p,'character',c['id']).json()
        intent=p['workspace']['entities']['intent:main']['draft'];intent['plotCount']=1;p=draft(client,p,'intent','main',intent)
        r=client.post(path+'/studio/confirm',json=dict(version=p['version'],kind='intent',id='main',generate=True));assert r.status_code==200;p=wait_done()
        for r in list(p['workspace']['entities'].values()):
            if r['kind']=='plot':p=confirm(client,p,'plot',r['id']).json()
        for r in list(p['workspace']['entities'].values()):
            if r['kind']=='clue':
                result=confirm(client,p,'clue',r['id']);assert result.status_code==200,result.text;p=result.json()
        client.post(path+'/studio/jobs',json=dict(version=p['version'],task='knowledge',trigger='user_button'));p=wait_done()
        for r in list(p['workspace']['entities'].values()):
            if r['kind']=='knowledge':
                p=draft(client,p,'knowledge',r['id'],r.get('suggestion',r['draft']));p=confirm(client,p,'knowledge',r['id']).json()
        for shot in list(p['workspace']['entities'].values()):
            if shot['kind']=='storyboard':
                body=shot['draft'];body.update(characterIds=[],participantsConfirmed=True,region=dict(x=.1,y=.1,w=.4,h=.4))
                p=draft(client,p,'storyboard',shot['id'],body)
                client.post(path+'/studio/jobs',json=dict(version=p['version'],task='storyboard',target=shot['id'],trigger='user_button'));p=wait_done();p=confirm(client,p,'storyboard',shot['id']).json()
        ready=client.get(path+'/studio/checklist').json();assert ready['ready'],ready
        assert calls==['culture','plots','knowledge','storyboard','storyboard']
        assert ready['videoGenerated'] is False


def test_locked_clue_unit_requires_separate_unlock(client):
    p,c=prepare(client);body=p['workspace']['entities']['clue:c']['draft'];body['units'][0]['locked']=True;p=draft(client,p,'clue','c',body)
    body['units'][0]['text']='不能直接改'
    r=client.put(f"/api/projects/{p['id']}/studio/draft",json=dict(version=p['version'],kind='clue',id='c',data=body));assert r.status_code==422


def test_edit_during_clue_generation_rejects_old_result(tmp_path,monkeypatch):
    import asyncio,threading
    monkeypatch.setattr(main,'DATA',tmp_path)
    started=threading.Event();release=threading.Event()
    async def provider(task,ctx):
        started.set()
        while not release.is_set():await asyncio.sleep(.005)
        return dict(clues=[dict(name='过期生成',summary='',characterIds=[],units=[])])
    monkeypatch.setattr(studio_agent,'run',provider)
    with TestClient(main.app) as client:
        p,c=prepare(client);path=f"/api/projects/{p['id']}/studio"
        r=client.post(path+'/jobs',json=dict(version=p['version'],task='clue',target='c',trigger='user_button'))
        assert r.status_code==200 and started.wait(2)
        body=p['workspace']['entities']['clue:c']['draft'];body['name']='新人工编辑'
        p=draft(client,p,'clue','c',body);release.set()
        for _ in range(200):
            current=client.get(path).json()
            if current['workspace']['jobs'][0]['state'] not in ('queued','running'):break
            time.sleep(.01)
        assert current['workspace']['jobs'][0]['state']=='completed'
        assert current['workspace']['generationSuggestions']
        assert current['workspace']['entities']['clue:c']['draft']['name']=='新人工编辑'


def test_old_empty_response_has_readable_error(client):
    import json
    p=setup(client)
    # Simulate the persisted provider failure seen in the reported screenshot.
    client.get(f"/api/projects/{p['id']}/studio")
    job=dict(id='empty',projectId=p['id'],task='culture',target='main',state='failed',error="Invalid JSON: EOF while parsing a value input_value=''",label='文化背景线索')
    with main.db() as c:c.execute('INSERT INTO studio_jobs VALUES (?,?,?)',('empty',p['id'],json.dumps(job)))
    result=client.get(f"/api/projects/{p['id']}/studio").json()['workspace']['jobs'][0]
    assert result['errorCode']=='empty_response' and '空内容' in result['error']
    assert result['target']==''


def test_checklist_stable_ids_names_and_task_locations(client):
    p,c=prepare(client);w=p['workspace']
    w['jobs']=[dict(id='task-1',task='relationship',target=c,page='characters',label='关系线索',state='failed',error='provider failed')]
    w['consistencyChecks']=[dict(id='suggestion-1',message='请核对',resolved=False)]
    report=ws.checklist(p);rows=report['items']
    assert len({r['id'] for r in rows})==len(rows)
    knowledge=next(r for r in rows if r['id']=='knowledge:'+c)
    assert knowledge['name']==w['entities']['character:'+c]['draft']['name']+'的知识库'
    shot=next(r for r in rows if r['id']=='storyboard:c')
    assert shot['name']=='折槛分镜'
    task=next(r for r in rows if r['kind']=='job')
    assert task['jobId']=='task-1' and task['target']=='character:'+c
    assert any(r['id']=='suggestion:suggestion-1' for r in rows)
    assert ws.checklist(p)==report


def test_checklist_reads_preserve_version_and_do_not_call_model(client,monkeypatch):
    p=prepare(client)[0]
    async def forbidden(*args,**kwargs):raise AssertionError('implicit model call')
    monkeypatch.setattr(studio_agent,'run',forbidden);monkeypatch.setattr(materials,'organize',forbidden)
    before=client.get(f"/api/projects/{p['id']}/studio").json()
    for _ in range(3):
        report=client.get(f"/api/projects/{p['id']}/studio/checklist")
        assert report.status_code==200
    after=client.get(f"/api/projects/{p['id']}/studio").json()
    assert before['version']==after['version'] and before['workspace']['jobs']==after['workspace']['jobs']


def test_analysis_failures_are_visible_and_success_supersedes_old_failure(client):
    import json
    p=setup(client);pid=p['id']
    request=dict(documentId='doc',pages=[1,2],trigger='user_button')
    def store(tid,state):
        row=dict(id=tid,projectId=pid,kind='ocr',status=state,progress='测试诊断',request=request)
        with main.db() as c:c.execute('INSERT INTO tasks VALUES (?,?,?)',(tid,pid,json.dumps(row)))
    store('old','failed');store('new','interrupted')
    current=client.get(f'/api/projects/{pid}/studio').json()
    failures=[j for j in current['workspace']['jobs'] if j.get('family')=='analysis']
    assert len(failures)==1 and failures[0]['id']=='analysis-new'
    assert failures[0]['request']==request
    rows=client.get(f'/api/projects/{pid}/studio/checklist').json()['items']
    assert any(r['jobId']=='analysis-new' and r['target']=='material:main' for r in rows)
    store('success','completed')
    assert not [j for j in client.get(f'/api/projects/{pid}/studio').json()['workspace']['jobs'] if j.get('family')=='analysis']


def test_unavailable_initial_knowledge_waits_for_clues_without_revoking_profiles(client):
    p=setup(client)
    for kind,rid in [('material','main')]+[('character',c['id']) for c in p['characters']]:
        result=confirm(client,p,kind,rid);assert result.status_code==200,result.text;p=result.json()
    path=f"/api/projects/{p['id']}/studio"
    report=client.get(path+'/checklist').json()
    profiles=[r for r in report['items'] if r['target'].startswith('character:')]
    knowledge=[r for r in report['items'] if r['target'].startswith('knowledge:')]
    assert profiles and all(r['state']=='confirmed' for r in profiles)
    assert knowledge and all(r['state']=='waiting' and r['dependency']['page']=='clues' for r in knowledge)
    assert report['ready'] is False
    assert confirm(client,p,'knowledge',p['characters'][0]['id']).status_code==422
    clue=dict(name='背景线索',summary='待人工核对',type='culture',parentId='culture',plotIds=[],characterIds=[],units=[dict(id='knowledge-test-u',text='虚构环境描写',kind='action',category='fiction',rationale='测试',references=[])])
    p=draft(client,p,'clue','knowledge-test-c',clue);result=confirm(client,p,'clue','knowledge-test-c');assert result.status_code==200,result.text;p=result.json()
    report=client.get(path+'/checklist').json()
    knowledge=[r for r in report['items'] if r['target'].startswith('knowledge:')]
    assert all(r['state']=='draft' for r in knowledge)
    assert not p['workspace']['jobs']  # Unlocking does not generate or confirm knowledge.


def test_stale_knowledge_remains_actionable_when_clues_become_invalid(client):
    p,c=prepare(client);p=confirm(client,p,'knowledge',c).json()
    w=p['workspace'];w['entities']['clue:c']['state']='stale';w['entities']['knowledge:'+c]['state']='stale'
    item=next(r for r in ws.checklist(p)['items'] if r['target']=='knowledge:'+c)
    assert item['state']=='confirmed' and item['dependency'] is None


def test_narrative_clue_has_one_owner_and_cannot_be_shared(client):
    p,c=prepare(client);body=copy.deepcopy(p['workspace']['entities']['clue:c']['draft']);body['plotIds']=['p','p2']
    path=f"/api/projects/{p['id']}/studio"
    r=client.put(path+'/draft',json=dict(version=p['version'],kind='clue',id='c',data=body))
    assert r.status_code==422 and '只能属于一个剧情' in r.text
    p=draft(client,p,'plot','p2',dict(title='另一剧情',goal='不能共享',body='',connection='',characterIds=[c],clueIds=['c'],region=None))
    r=confirm(client,p,'plot','p2');assert r.status_code==422 and '不能跨剧情共享' in r.text


def test_paragraph_edit_preserves_old_evidence_and_respects_locks(client):
    p,c=prepare(client);original=copy.deepcopy(p['workspace']['entities']['clue:c']['draft'])
    assert ws.narrative_text(original)=='朱云略作停顿。'
    assert 'content' not in original
    body=copy.deepcopy(original);body['content']='朱云向前一步，继续陈述。';p=draft(client,p,'clue','c',body)
    result=p['workspace']['entities']['clue:c']['draft']
    assert result['content']==result['units'][0]['text']
    assert len(result['units'])==1 and result['units'][0]['category']=='fiction'
    assert result['legacyUnits']==original['units']
    assert p['workspace']['entities']['clue:c']['published']==original
    result['units'][0]['locked']=True;p=draft(client,p,'clue','c',result)
    result['content']='不允许覆盖锁定情节'
    r=client.put(f"/api/projects/{p['id']}/studio/draft",json=dict(version=p['version'],kind='clue',id='c',data=result))
    assert r.status_code==422


def test_plot_check_action_appends_paragraph_children_without_rewriting(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path);calls=[]
    async def provider(task,ctx):
        calls.append((task,ctx['targetPlot']['id']))
        return dict(clues=[dict(name='第一段情节',content='朱云走到殿前，准备陈述。'),dict(name='第二段情节',content='殿中众人转向朱云。')])
    monkeypatch.setattr(studio_agent,'run',provider)
    with TestClient(main.app) as client:
        p,c=prepare(client);p=draft(client,p,'plot','empty-plot',dict(title='准备进谏',goal='铺垫',body='原剧情正文保持不变',connection='承接前段',characterIds=[c],clueIds=['c'],region=None))
        path=f"/api/projects/{p['id']}/studio"
        row=next(i for i in client.get(path+'/checklist').json()['items'] if i['target']=='plot:empty-plot')
        assert row['action']==dict(task='plot_clues',target='empty-plot',label='一键生成子叙事线索')
        assert calls==[]
        old=copy.deepcopy(p['workspace']['entities']['clue:c'])
        r=client.post(path+'/jobs',json=dict(version=p['version'],task='plot_clues',target='empty-plot',trigger='user_button'));assert r.status_code==200,r.text
        for _ in range(200):
            p=client.get(path).json()
            if p['workspace']['jobs'][0]['state'] not in ('queued','running'):break
            time.sleep(.01)
        assert p['workspace']['jobs'][0]['state']=='completed',p['workspace']['jobs'][0]
        plot=p['workspace']['entities']['plot:empty-plot']
        assert plot['published'] is None and plot['draft']['body']=='原剧情正文保持不变'
        assert len(plot['draft']['clueIds'])==2
        for cid in plot['draft']['clueIds']:
            child=p['workspace']['entities']['clue:'+cid]
            assert child['draft']['plotIds']==['empty-plot'] and child['published'] is None
            assert len(child['draft']['units'])==1 and child['draft']['content']==child['draft']['units'][0]['text']
            assert child['draft']['characterIds']==[c]
        assert p['workspace']['entities']['clue:c']==old and calls==[('plot_clues','empty-plot')]


def test_plot_children_failure_keeps_plot_and_existing_clues(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    async def fail(*args,**kwargs):raise ValueError('模拟生成失败')
    monkeypatch.setattr(studio_agent,'run',fail)
    with TestClient(main.app) as client:
        p,c=prepare(client);before=copy.deepcopy(p['workspace']['entities']);path=f"/api/projects/{p['id']}/studio"
        r=client.post(path+'/jobs',json=dict(version=p['version'],task='plot_clues',target='p',trigger='user_button'));assert r.status_code==200
        for _ in range(200):
            current=client.get(path).json()
            if current['workspace']['jobs'][0]['state'] not in ('queued','running'):break
            time.sleep(.01)
        assert current['workspace']['jobs'][0]['state']=='failed'
        assert current['workspace']['entities']==before and current['version']==p['version']


def test_plot_children_result_cannot_overwrite_newer_plot_edits(tmp_path,monkeypatch):
    import asyncio,threading
    monkeypatch.setattr(main,'DATA',tmp_path);started=threading.Event();release=threading.Event()
    async def provider(*args):
        started.set()
        while not release.is_set():await asyncio.sleep(.005)
        return dict(clues=[dict(name='旧输入生成的情节',content='不应应用。')])
    monkeypatch.setattr(studio_agent,'run',provider)
    with TestClient(main.app) as client:
        p,c=prepare(client);path=f"/api/projects/{p['id']}/studio"
        client.post(path+'/jobs',json=dict(version=p['version'],task='plot_clues',target='p',trigger='user_button'))
        assert started.wait(2)
        body=p['workspace']['entities']['plot:p']['draft'];body['body']='新的人工修改';p=draft(client,p,'plot','p',body);release.set()
        for _ in range(200):
            value=client.get(path).json()
            if value['workspace']['jobs'][0]['state'] not in ('queued','running'):break
            time.sleep(.01)
        assert value['workspace']['jobs'][0]['state']=='completed'
        assert value['workspace']['generationSuggestions']
        assert value['workspace']['entities']['plot:p']['draft']['body']=='新的人工修改'
        assert len([r for r in value['workspace']['entities'].values() if r['kind']=='clue'])==1
