"""Explicit real-provider acceptance on raw-file copies. No video submissions."""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'data/acceptance/20261101-live'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--stage',choices=['import','analyze','review-roles','detect','vision','seed-history','history','review-history','curate-history','identities','creation','experience','media'],required=True)
    args=parser.parse_args()
    if not args.live:raise SystemExit('真实验收必须显式传 --live；只在独立数据目录运行')
    RUN.mkdir(parents=True,exist_ok=True)
    os.environ.update(CREATION_DATA_DIR=str(RUN/'data'),CREATION_SEED_LATEST='0',MODEL_PROVIDER='aihubmix',CREATION_LIVE_RUN_DIR=str(RUN),CREATION_LIVE_REQUEST_LIMIT='100',CREATION_ACCEPTANCE='1')
    sys.path.insert(0,str(ROOT))
    from backend import main as app_module,workspace as ws
    from fastapi.testclient import TestClient
    state_file=RUN/'state.json';state=json.loads(state_file.read_text()) if state_file.exists() else dict(stages={},sourceProjectId='85e0f870d8bc',purpose='技术验收；不代替史学审核',videoSubmissions=0)
    def persist():state_file.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    def announce(stage,value):print(json.dumps(dict(stage=stage,detail=value),ensure_ascii=False),flush=True)
    def request(method,path,**kw):
        response=getattr(client,method)('/api'+path,**kw)
        if not response.is_success:raise ValueError(str(response.status_code)+': '+str(response.json().get('detail','操作失败'))[:700])
        return response.json()
    def project():return request('get','/projects/'+state['projectId']+'/studio')
    def wait(family,jid=None):
        previous='';deadline=time.monotonic()+2400
        while time.monotonic()<deadline:
            if family=='analysis':jobs=request('get','/projects/'+state['projectId']+'/tasks');job=next((j for j in jobs if jid is None or j['id']==jid),None)
            else:jobs=project()['workspace']['jobs'];job=next((j for j in jobs if jid is None or j['id']==jid),None)
            if job:
                progress=job.get('progress','')
                if progress and progress!=previous:announce('progress',progress);previous=progress
                status=job.get('status',job.get('state'))
                if status not in ('queued','running'):
                    if status!='completed':raise ValueError('任务'+str(status)+'：'+str(job.get('error') or progress))
                    return project()
            time.sleep(1)
        raise ValueError('等待任务超时；未自动重试，已保存结果保留')
    def analysis(kind,**extra):
        p=project();job=request('post',f"/projects/{p['id']}/tasks",json=dict(version=p['version'],kind=kind,trigger='user_button',**extra));return wait('analysis',job['id'])
    def draft(p,kind,rid,data):return request('put',f"/projects/{p['id']}/studio/draft",json=dict(version=p['version'],kind=kind,id=rid,data=data))
    def confirm(p,kind,rid):return request('post',f"/projects/{p['id']}/studio/confirm",json=dict(version=p['version'],kind=kind,id=rid,generate=False,acceptRisk=True))
    def generate(task,target=''):
        p=project();value=request('post',f"/projects/{p['id']}/studio/jobs",json=dict(version=p['version'],task=task,target=target,trigger='user_button'))
        job=next(j for j in value['workspace']['jobs'] if j['task']==task and j['state'] in ('queued','running'))
        return wait('studio',job['id'])
    with TestClient(app_module.app) as client:
        if args.stage=='import':
            if state.get('projectId'):announce('reuse',state['projectId']);return
            with sqlite3.connect((ROOT/'data/projects.sqlite').as_uri()+'?mode=ro',uri=True) as c:source=json.loads(c.execute('SELECT body FROM projects WHERE id=?',(state['sourceProjectId'],)).fetchone()[0])
            state['sourceProjectHash']=hashlib.sha256(json.dumps(source,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            p=request('post','/projects',json=dict(title='步辇图真实API验收'))
            image=ROOT/'data'/Path(source['image']).name
            with image.open('rb') as f:p=request('post',f"/projects/{p['id']}/image?version={p['version']}",files=dict(file=(image.name,f,'image/jpeg')))
            state['projectId']=p['id'];persist()
            for doc in source['documents']:
                with (ROOT/'data'/doc['filename']).open('rb') as f:p=request('post',f"/projects/{p['id']}/documents?version={p['version']}",files=dict(file=(doc['title'],f,'application/pdf')))
                state['documentId']=p['documents'][-1]['id'];persist();p=wait('analysis')
            state['rawImageSha256']=hashlib.sha256(image.read_bytes()).hexdigest();state['stages']['import']=dict(pages=p['documents'][0]['pageCount'],characters=sum(len(s['text']) for s in p['sources']))
        elif args.stage=='analyze':
            p=analysis('document_analysis',documentId=state['documentId'],targetArtwork='步辇图')
            a=p['documentAnalysis'];state['stages']['analyze']=dict(claims=len(a['claims']),people=[dict(name=c['name'],scope=c['scope']) for c in a['people']],modelCalls=a.get('modelCalls'),warnings=len(a.get('validationWarnings',[])))
            ids=[c['id'] for c in a['people'] if c['scope']=='depicted']
            p=request('post',f"/projects/{p['id']}/documents/analysis/adopt",json=dict(version=p['version'],analysisId=a['id'],summaryKinds=['background','relationships','narrative'],characterIds=ids,updateIds=[]))
            state['adoptedCharacters']=[dict(id=c['id'],name=c['name']) for c in p['characters']]
        elif args.stage=='review-roles':
            # Explicit technical review of fresh PDF text. Never changes the original project.
            p=app_module.get(state['projectId']);reviewed=[]
            for name,page,quote in [('唐太宗',2,'《步辇图》画面中心情节是唐太宗坐在九位宫女抬着的步辇上来到会见使臣的场所，接见先期赶到、\n在场等候的吐蕃使者禄东赞'),('红衣官员',6,'《步辇图》中禄东赞由两位官员模样的人物一前一后陪同。前方著团领缺骻红袍官员戴着与太宗相同\n的幞头官帽'),('白衣官员',6,'禄东赞身后著白色唐服的官员')]:
                candidate=next(c for c in p['documentAnalysis']['people'] if c['name']==name)
                source=next(s for s in p['sources'] if s.get('page')==page and s.get('method')=='extracted');offset=source['text'].index(quote)
                ref=dict(sourceId=source['id'],sourceVersion=source['version'],documentId=state['documentId'],page=page,quote=quote,start=offset,end=offset+len(quote))
                candidate.update(scope='depicted',depictionReferences=[ref],manualScopeReview='验收中按原PDF画面描述人工技术核对；推测官职未升级为史实')
                reviewed.append(candidate['id'])
            p=app_module.save(p,p['version'],'studio:acceptance:scope_review',dict(candidateIds=reviewed))
            p=request('post',f"/projects/{p['id']}/documents/analysis/adopt",json=dict(version=p['version'],analysisId=p['documentAnalysis']['id'],summaryKinds=[],characterIds=reviewed,updateIds=[]))
            removed=[]
            for c in list(p['characters']):
                if c['name'] not in ('九位抬辇宫女','抬步辇的红裙侍女','引见的官员'):continue
                p=request('post',f"/projects/{p['id']}/studio/delete",json=dict(version=p['version'],kind='character',id=c['id'],acceptRisk=True));removed.append(c['name'])
            state['stages']['review-roles']=dict(reviewed=reviewed,removedDuplicateDescriptions=removed,characters=[dict(id=c['id'],name=c['name']) for c in p['characters']])
        elif args.stage=='detect':
            p=analysis('detect');state['stages']['detect']=dict(candidates=len(p['annotations']))
        elif args.stage=='vision':
            p=analysis('vision_match');state['stages']['vision']=dict(matches=[dict(annotationId=m['annotationId'],characterId=m.get('characterId'),confidence=m.get('confidence'),reason=m.get('reason','')) for m in p.get('matches',[])])
        elif args.stage=='seed-history':
            from backend import history
            p=project();h=request('get',f"/projects/{p['id']}/history")
            if h['draft'] is not None:raise ValueError('已有历史草稿，不覆盖')
            tables=history.empty();pid=p['id'];tables['works']=[dict(id=pid,title='步辇图')]
            folder=RUN/'editions';metadata=json.loads((folder/'jiutangshu-196a.json').read_text());text=(folder/'jiutangshu-196a.txt').read_text()
            tables['hist_sources']=[dict(id='jiutangshu-digital',**metadata,snapshot_text=text)]
            quotes=['因復請婚，太宗許之。','弄贊乃遣其相祿東贊致禮，獻金五千兩，自余寶玩數百事。','貞觀十五年，太宗以文成公主妻之，令禮部尚書、江夏郡王道宗主婚，持節送公主於吐蕃。','初，太宗既許降文成公主，贊普使祿東贊來迎，召見顧問，進對合旨，太宗禮之，有異諸蕃，乃拜祿東贊為右衛大將軍，又以瑯邪長公主外孫女段氏妻之。']
            for i,q in enumerate(quotes):
                offset=text.index(q);tables['quotations'].append(dict(id='jt-quote-'+str(i+1),source_id='jiutangshu-digital',work_id=pid,locator='卷一九六上·吐蕃上；数字转录节录'+str(i+1),original_text=q,source_start=offset,source_end=offset+len(q)))
            request('put',f'/projects/{pid}/history/draft',json=dict(version=h['version'],baseRevision=h['revision'],baseDraftHash=h['draftHash'],tables=tables))
            p=app_module.get(pid)
            for d in p['documents']:d['citation']='谢继胜、朱姝纯：《关于〈步辇图〉研究的几个问题》，《故宫博物院院刊》2018年第4期，总第198期，第30—54页；原PDF首页核对作者题名，正文观点仍为研究判断'
            app_module.save(p,p['version'],'studio:acceptance:document_citation')
            state['stages']['seed-history']=dict(quotations=len(quotes),edition=metadata['edition'],restriction=metadata['verification_note'])
        elif args.stage=='history':
            p=generate('history');h=request('get',f"/projects/{p['id']}/history")
            state['stages']['history']=dict(counts={t:len(v) for t,v in (h['draft'] or h['tables']).items()},issues=h['issues'],researchNotes=h['researchNotes'])
        elif args.stage=='review-history':
            p=project();h=request('get',f"/projects/{p['id']}/history")
            if h['issues']:raise ValueError('历史草稿仍有未解决校验问题：'+str(h['issues']))
            preview=request('post',f"/projects/{p['id']}/history/preview",json=dict(version=p['version']))
            h=request('post',f"/projects/{p['id']}/history/confirm",json=dict(version=p['version'],acceptRisk=True))
            p=request('post',f"/projects/{p['id']}/history/adopt",json=dict(version=h['version']))
            state['stages']['review-history']=dict(revision=h['revision'],counts={t:len(v) for t,v in h['tables'].items()},technicalReviewOnly=True)
        elif args.stage=='identities':
            p=project();confirmed=[]
            for a in list(p['annotations']):
                if not a.get('characterId'):continue
                match=next((m for m in p['matches'] if m['annotationId']==a['id']),{})
                if match.get('confidence')!='high' or match.get('conflicts'):continue
                p=request('post',f"/projects/{p['id']}/people/{a['id']}/confirm",json=dict(version=p['version'],characterId=a['characterId']))
                confirmed.append(dict(annotationId=a['id'],characterId=a['characterId']))
            if not confirmed:raise ValueError('无足够依据的高把握身份对应，未强行确认')
            state['stages']['identities']=confirmed
        elif args.stage=='curate-history':
            p=project();pid=p['id'];h=request('get',f'/projects/{pid}/history');tables=h['tables']
            for episode in tables['background_episodes']:
                if episode['phase']=='后续':episode['summary']='贞观十五年，太宗以文成公主妻吐蕃，命礼部尚书、江夏郡王道宗主婚并送公主入吐蕃。此为画中接见之后的历史背景，不把召见、授官等不同事项统称为后续。'
                if episode['phase']=='画中':episode['summary']='论文将画面解释为唐太宗坐步辇接见等候的吐蕃使者禄东赞，旁有官员陪同。史书记载太宗召见禄东赞；史文与画面人物的对应保留为研究判断。'
            for line in tables['person_lines']:
                if line['grounding']=='推断' and line['aspect']=='身份':line['line_text']='论文将画面坐辇者识别为唐太宗。'
                if line['line_text']=='进对合旨':line.update(aspect='史书刻画',line_text='史书称禄东赞进对合旨，保留为史书对奏对的评价。')
            h=request('put',f'/projects/{pid}/history/draft',json=dict(version=h['version'],baseRevision=h['revision'],baseDraftHash=h['draftHash'],tables=tables))
            h=request('post',f'/projects/{pid}/history/confirm',json=dict(version=h['version'],acceptRisk=True))
            request('post',f'/projects/{pid}/history/adopt',json=dict(version=h['version']))
            state['stages']['curate-history']=dict(revision=h['revision'],corrections=['后续只保留婚送公主，不把召见与授官拼入同一时点','画面与史文对应明确为论文判断','进对合旨调整为史书刻画，未伪作直接言语'])
        elif args.stage=='creation':
            # Technical confirmation only, on this isolated project. Invalid content is not bypassed.
            p=project()
            for r in list(p['workspace']['entities'].values()):
                if r['kind']=='knowledge' and r['state']!='deleted' and p['workspace']['entities'].get('character:'+r['id'],{}).get('state')=='deleted':
                    p=request('post',f"/projects/{p['id']}/studio/delete",json=dict(version=p['version'],kind='knowledge',id=r['id'],acceptRisk=True))
            if not state['stages'].get('charactersConfirmed'):
                p=confirm(p,'material','main')
                for c in p['characters']:p=confirm(p,'character',c['id'])
                state['stages']['charactersConfirmed']=True;persist()
            if not state['stages'].get('culture'):
                p=generate('culture');state['stages']['culture']=True;persist()
            if not state['stages'].get('relationship'):
                p=generate('relationship',p['characters'][0]['id']);state['stages']['relationship']=True;persist()
            if not state['stages'].get('plots'):
                d=p['workspace']['entities']['intent:main']['draft'];d.update(theme='史料与画面的相遇',goal='展示使者来访与宫廷接见，区分画中时刻及历史背景',plotCount=1)
                p=draft(p,'intent','main',d);p=confirm(p,'intent','main');p=generate('plots');state['stages']['plots']=True;persist()
            p=project()
            for r in list(p['workspace']['entities'].values()):
                if r['kind']=='plot' and not ws.valid(r):p=confirm(p,'plot',r['id'])
            for r in list(p['workspace']['entities'].values()):
                if r['kind']=='clue' and r['state']!='deleted' and not ws.valid(r):p=confirm(p,'clue',r['id'])
            if not state['stages'].get('knowledge'):
                p=generate('knowledge');state['stages']['knowledge']=True;persist()
            p=project()
            for r in list(p['workspace']['entities'].values()):
                if r['kind']=='knowledge' and r['state']!='deleted' and p['workspace']['entities'].get('character:'+r['id'],{}).get('state') not in ('deleted',None) and not ws.valid(r):
                    if r.get('suggestion'):p=draft(p,'knowledge',r['id'],r['suggestion'])
                    p=confirm(p,'knowledge',r['id'])
            for r in list(p['workspace']['entities'].values()):
                if r['kind']!='storyboard' or r['state']=='deleted' or ws.valid(r):continue
                d=r['draft'];d.update(region=dict(x=0,y=0,w=1,h=1),participantsConfirmed=True)
                p=draft(p,'storyboard',r['id'],d);p=generate('storyboard',r['id']);p=confirm(p,'storyboard',r['id'])
            p=generate('check');state['stages']['creation']=dict(storyboards=sum(r['kind']=='storyboard' and ws.valid(r) for r in p['workspace']['entities'].values()),consistency=p['workspace'].get('consistencyChecks',[]))
        elif args.stage=='media':
            import shutil
            from backend import consumption
            p=project();shots=[r for r in p['workspace']['entities'].values() if r['kind']=='storyboard' and ws.valid(r)]
            if not shots:raise ValueError('尚无有效已确认分镜')
            from backend import video
            previews=[]
            for shot in shots:
                sid=shot['id'];preview=request('get',f"/projects/{p['id']}/storyboards/{sid}/video-prompt")
                p=request('put',f"/projects/{p['id']}/storyboards/{sid}/video-prompt",json=dict(version=p['version'],baseFingerprint=preview['baseFingerprint'],text=preview['prompt']))
                p=request('post',f"/projects/{p['id']}/storyboards/{sid}/confirm-video",json=dict(version=p['version']))
                previews.append(dict(storyboardId=sid,promptSha256=hashlib.sha256(preview['prompt'].encode()).hexdigest(),parameters=video.VIDEO_PARAMETERS,submitted=False))
            folder=RUN/'data/acceptance-media';folder.mkdir(parents=True,exist_ok=True)
            shutil.copyfile('/tmp/animatedscroll-mock.mp4',folder/'local-placeholder.mp4')
            manifest={p['id']:{r['id']:dict(filename='local-placeholder.mp4',fingerprint=consumption.snapshot(p)) for r in shots}}
            (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
            result=client.get('/api/acceptance-media/local-placeholder.mp4');assert result.status_code==200 and len(result.content)>1000
            response=client.get(f"/api/projects/{p['id']}/narrative/export?draft=true&format=zip");assert response.status_code==200
            (RUN/'narrative-with-test-placeholder.zip').write_bytes(response.content)
            import io,zipfile
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                bundle=json.loads(z.read('manifest.json'));assert any(m['kind']=='placeholder' for m in bundle['media'])
                assert 'assets/test-media/local-placeholder.mp4' in z.namelist()
            with app_module.db() as c:count=c.execute('SELECT COUNT(*) FROM video_jobs').fetchone()[0]
            assert count==0;state['stages']['media']=dict(kind='placeholder',videoJobs=count,bytes=len(result.content),exported=True,prompts=previews)
        elif args.stage=='experience':
            p=project();before=p['version'];view=request('post',f"/projects/{p['id']}/experience/sessions")
            person=view['people'][0];sid=view['session']['id'];answers=[]
            dedup=True
            for i,text in enumerate(['你是谁？','你了解画中接见使者这件事吗？','你知道今天的股票价格吗？']):
                turn=request('post',f"/projects/{p['id']}/experience/sessions/{sid}/messages",json=dict(requestId='live-'+str(i),characterId=person['characterId'],text=text));answers.append(turn)
                budget_before=(RUN/'requests.json').read_bytes()
                replay=request('post',f"/projects/{p['id']}/experience/sessions/{sid}/messages",json=dict(requestId='live-'+str(i),characterId=person['characterId'],text=text))
                dedup=dedup and replay==turn and (RUN/'requests.json').read_bytes()==budget_before
                for clue_id in turn.get('clueIds',[]):view=request('post',f"/projects/{p['id']}/experience/sessions/{sid}/collect",json=dict(turnId=turn['id'],clueId=clue_id))
            assert dedup and all(t['status']=='completed' for t in answers)
            assert answers[-1]['basis']=='unknown' and not answers[-1]['clueIds']
            assert view['media'] and any(m.get('mediaKind')=='placeholder' for m in view['media'])
            state['stages']['experience']=dict(sessionId=sid,answers=answers,collected=view['session']['collectedClueIds'],unlocked=len(view['media']),creationVersionUnchanged=project()['version']==before,repeatedRequestsDeduplicated=dedup,restoredSession=request('get',f"/projects/{p['id']}/experience/sessions/{sid}")['session']['id']==sid)
        persist();announce('complete',dict(stage=args.stage,projectId=state.get('projectId'),summary=state['stages'].get(args.stage)))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        message=re.sub(r'sk-[A-Za-z0-9_-]{6,}','<credential-redacted>',str(exc))
        print(json.dumps(dict(error=type(exc).__name__,message=message[:1000]),ensure_ascii=False),flush=True)
        raise SystemExit(1)
