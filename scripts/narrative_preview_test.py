"""Explicit, bounded acceptance commands for the user's 步辇图(2) project.

prepare changes only three shot regions/prompts. quote never generates media.
submit creates one gated batch; accept/reject requires inspecting its result.
"""
import argparse
import gzip
import json
import sqlite3
import sys
import uuid
from pathlib import Path

import httpx

ROOT=Path(__file__).resolve().parents[1]
PID='85e0f870d8bc'
BASE=f'http://127.0.0.1:8000/api/projects/{PID}'
REPORT=ROOT/'.runtime/narrative-preview-test'
SHOTS=[
 ('3ed5b7fb0910','一前一后',dict(x=.05,y=.25,w=.35,h=.73),'聚焦画卷左段的三人队列：红衣官员在前，禄东赞居中作揖，白衣官员在后。保持原画三人的身份、服饰、位置和姿态。镜头固定或轻微推近，仅有极轻的衣纹变化，不新增人物。'),
 ('789873d1c098','九人抬辇',dict(x=.50,y=.22,w=.46,h=.75),'聚焦画卷右段的唐太宗、步辇与九位宫女。保持原画人物数量、衣冠、纨扇和抬杠的位置。太宗始终坐于辇上，人物不换位，仅作轻微衣袖变化与缓慢推近，不增加背景。'),
 ('0e757cf45d43','辞婚之答',dict(x=.14,y=.25,w=.65,h=.72),'保持画中太宗乘辇与使者作揖的静态姿态，以两端人物关系呈现进见气氛，轻微推近。辞婚只由外部讲解说明为文献所载，不新增婚礼、公主、对白、下辇动作或画外人物。'),
]


def request(client,method,path='',**kw):
    r=client.request(method,BASE+path,**kw)
    if r.status_code>=400:raise RuntimeError(str(r.status_code)+' '+r.text[:500])
    return r.json()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','quote','submit','status','accept','reject'])
    parser.add_argument('--kind',choices=['video','image','crop'],default='video');parser.add_argument('--job')
    args=parser.parse_args();REPORT.mkdir(parents=True,exist_ok=True)
    with httpx.Client(timeout=120) as client:
        if args.action=='prepare':
            backup=REPORT/'before-project.json.gz'
            if not backup.exists():
                with sqlite3.connect((ROOT/'data/projects.sqlite').as_uri()+'?mode=ro',uri=True) as c:body=c.execute('SELECT body FROM projects WHERE id=?',(PID,)).fetchone()[0]
                backup.write_bytes(gzip.compress(body.encode()))
            for sid,title,region,prompt in SHOTS:
                p=request(client,'GET','/studio/editor');assert p['title']=='步辇图(2)'
                d=p['workspace']['entities']['storyboard:'+sid]['draft']
                changes=[]
                for field,value in dict(region=region,prompt=prompt,camera='固定或缓慢推近',action='保持原画姿态，仅有轻微衣纹变化').items():
                    if d.get(field)!=value:changes.append(dict(path=f'/workspace/entities/storyboard:{sid}/draft/{field}',before=d.get(field),value=value))
                if changes:request(client,'PATCH','/studio/units/workspace',json=dict(version=p['version'],requestId=str(uuid.uuid4()),changes=changes))
                units=request(client,'GET','/studio/units');unit=units['units']['storyboard:'+sid]
                # These exact region/prompt changes are the user's authorized test setup.
                request(client,'POST','/studio/units/storyboard:'+sid+'/confirm',json=dict(requestId=str(uuid.uuid4()),contentHash=unit['contentHash'],dependencyHash=unit['dependencyHash']))
                print('prepared',title,region)
        elif args.action=='quote':
            p=request(client,'GET','/studio/editor')
            q=request(client,'POST','/media-previews/quote',json=dict(version=p['version'],scope='narrative',storyboardIds=[s[0] for s in SHOTS],kind=args.kind))
            (REPORT/(args.kind+'-quote.json')).write_text(json.dumps(q,ensure_ascii=False,indent=2))
            print(json.dumps({k:v for k,v in q.items() if k!='items'},ensure_ascii=False))
            print('items',[v['title'] for v in q['items']])
        elif args.action=='submit':
            q=json.loads((REPORT/(args.kind+'-quote.json')).read_text())
            result=request(client,'POST','/media-previews',json=dict(quoteId=q['quoteId'],requestId='bunian-narrative-preview-'+args.kind+'-'+q['quoteId']))
            (REPORT/(args.kind+'-submission.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
            print(json.dumps(dict(jobs=[{k:j.get(k) for k in ['id','title','status','kind','reservedCny']} for j in result['jobs']],budget=result['budget']),ensure_ascii=False))
        elif args.action in ('accept','reject'):
            if not args.job:parser.error('--job is required')
            j=request(client,'POST','/media-previews/'+args.job+'/review',json=dict(accepted=args.action=='accept'))
            print(j['title'],j['status'],j.get('review'))
        else:
            result=request(client,'GET','/media-previews')
            (REPORT/'latest-status.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            print(json.dumps(dict(jobs=[{k:j.get(k) for k in ['id','title','status','kind','model','reservedCny','message','remoteId','videoUrl','imageUrl','review']} for j in result['jobs']],budget=result['budget']),ensure_ascii=False))


if __name__=='__main__':main()
