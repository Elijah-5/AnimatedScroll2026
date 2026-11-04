"""Explicit temporary browser fixture. No real provider requests or creator writes."""
import os
import sys
import tempfile
import json
import shutil
from pathlib import Path
if os.getenv('CREATION_NOTICE_UI_TEST')!='1':raise SystemExit('Explicit CREATION_NOTICE_UI_TEST=1 required')
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
os.environ.update(CREATION_DATA_DIR=tempfile.mkdtemp(prefix='animatedscroll-notices-'),CREATION_SEED_LATEST='0',CREATION_DB_BACKEND='sqlite',MODEL_PROVIDER='aihubmix',AIHUBMIX_API_KEY='',DASHSCOPE_API_KEY='')
from backend import main,experience,studio_agent,video,workspace as ws
from fastapi.testclient import TestClient
from test_merged_features import ready,approve
from PIL import Image,ImageDraw
import uvicorn

with TestClient(main.app) as client:
    p,cid=ready(client)
    p=main.rename_project(p['id'],main.RenameProject(version=p['version'],title='版本提醒与批量确认 · 隔离验收'))
    image=Image.new('RGB',(800,400),'#d7c5a2');draw=ImageDraw.Draw(image)
    for x in (80,400):
        draw.ellipse((x+30,45,x+90,110),fill='#564c3a');draw.polygon([(x+30,110),(x,320),(x+130,320),(x+90,110)],fill='#6c7e66')
    image.save(main.DATA/'merged-reference.png')
    if os.getenv('CREATION_READER_REAL_ART')=='1':
        # Copy only the image and published geometry into this disposable fixture.
        # The creator database is opened strictly read-only; no real API keys are used.
        import sqlite3,copy
        with sqlite3.connect('file:'+str(ROOT/'data/projects.sqlite')+'?mode=ro',uri=True) as connection:
            original=json.loads(connection.execute('SELECT body FROM projects WHERE id=?',('f417cabb0972',)).fetchone()[0])
        material=original['workspace']['entities']['material:main']['published']
        source_people={r['id']:r['published']['name'] for r in original['workspace']['entities'].values() if r['kind']=='character' and r.get('published')}
        targets={r['published']['name']:r['id'] for r in p['workspace']['entities'].values() if r['kind']=='character' and r.get('published')}
        maid=ws.record('character','gallery-maids',dict(name='仕女',identity='画中群体角色',roleType='group',depictionScope='depicted'),True)
        p['workspace']['entities']['character:gallery-maids']=maid
        targets.update(仕女='gallery-maids',仕女2='gallery-maids')
        figures=[]
        for a in material['annotations']:
            name=source_people.get(a['characterId'])
            if name not in targets:continue
            row=copy.deepcopy(a);row.update(characterId=targets[name],identityConfirmed=True,needsReview=False,confirmed=True);figures.append(row)
        shutil.copyfile(ROOT/'data'/Path(material['image']).name,main.DATA/'merged-reference.png')
        mat=p['workspace']['entities']['material:main'];mat['draft']['annotations']=figures;mat['published']=copy.deepcopy(mat['draft'])
        p['annotations']=copy.deepcopy(figures)
        p=main.save(p,p['version'],'studio:reader_art_fixture')
    p=approve(client,p);inputs,_=video.shot_inputs(p,'c',main.DATA)
    folder=main.DATA/'videos';folder.mkdir(exist_ok=True);shutil.copyfile('/tmp/animatedscroll-mock.mp4',folder/'notice-fixture.mp4')
    job=dict(id='notice-fixture',projectId=p['id'],storyboardId='c',status='succeeded',time='1',sourceVersion=p['version'],storyboardSnapshot=p['workspace']['entities']['storyboard:c']['published'],videoUrl=f"/api/projects/{p['id']}/videos/notice-fixture/file",requestFingerprint=video.approval_hash(inputs,p['workspace']['media']['c']['prompt']),message='本地测试视频 · 模拟结果，无远端任务',fixture=True)
    with main.db() as c:c.execute('INSERT INTO video_jobs VALUES (?,?,?)',(job['id'],p['id'],json.dumps(job)))
    p['workspace']['media']['c']['selectedJobId']=job['id'];main.save(p,p['version'],'studio:browser_fixture')

async def answer(context,*args):return dict(answer='【模型替身】我只知道已确认的这一条情节，记录线索后可查看对应镜头。',clueIds=[v['id'] for v in context['clues']][:1])
async def generation(kind,context):
    if kind!='storyboard':raise ValueError('此隔离验收只提供分镜模型替身')
    return dict(prompt='【模型替身】原画中人物衣袖轻动，镜头固定。',startFrame='人物静立',endFrame='恢复静立',action='衣袖轻动',camera='固定',style='保留古画笔触')
experience.answer=answer;studio_agent.run=generation
print(json.dumps(dict(data=str(main.DATA),projectId=p['id'],characterId=cid,providers='local_fakes_only')),flush=True)
uvicorn.run(main.app,host='127.0.0.1',port=8017,log_level='warning')
