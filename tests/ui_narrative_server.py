"""Disposable local UI acceptance. Copies data; every model call is a fake.

No simulated dialogue or collection is written to the user's production data.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import signal
import subprocess

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if '--stop' in sys.argv:
    found=subprocess.run(['/usr/sbin/lsof','-nP','-iTCP:8021','-sTCP:LISTEN','-t'],capture_output=True,text=True)
    for pid in found.stdout.split():
        command=subprocess.run(['/bin/ps','-p',pid,'-o','command='],capture_output=True,text=True).stdout
        if 'tests/ui_narrative_server.py' not in command:raise SystemExit('拒绝停止其他服务')
        os.kill(int(pid),signal.SIGINT)
    raise SystemExit(0)
data=Path(tempfile.mkdtemp(prefix='scroll-narrative-ui-'))
with sqlite3.connect((ROOT/'data/projects.sqlite').as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(data/'projects.sqlite') as dst:src.backup(dst)
for source in (ROOT/'data').iterdir():
    if source.is_file() and source.suffix in ('.png','.jpg','.jpeg','.webp'):shutil.copy2(source,data/source.name)
for name in ('media-previews','experience-cutouts'):
    if (ROOT/'data'/name).exists():shutil.copytree(ROOT/'data'/name,data/name)
os.environ.update(CREATION_DATA_DIR=str(data),CREATION_DB_BACKEND='sqlite',CREATION_SEED_LATEST='0',AIHUBMIX_API_KEY='',DASHSCOPE_API_KEY='')
from backend import main,experience,cutouts,media_previews,studio_agent,structured,workspace as ws
import copy
from fastapi.staticfiles import StaticFiles
from PIL import Image
import uvicorn

async def forbidden(*args,**kwargs):raise ValueError('隔离界面验收不调用远端模型')
studio_agent.run=forbidden;structured.ask=forbidden
original_price=media_previews.pricing
async def price(kind):
    if kind!='crop':raise ValueError('隔离验收仅允许零费用局部预览')
    return await original_price(kind)
media_previews.pricing=price
targets={'3ed5b7fb0910','789873d1c098','0e757cf45d43'}
async def answer(ctx,message,history):
    candidates=[b for b in ctx['basis'] if b.get('clueId') in targets and b['clueId'] in ctx['unrecordedClueIds']]
    if not candidates:candidates=[b for b in ctx['basis'] if b.get('clueId') in targets]
    if not candidates:return dict(disposition='unknown',segments=[dict(text='【隔离验收替身】此角色没有绑定测试线索。')])
    b=candidates[0]
    return dict(disposition='grounded',segments=[dict(text='【隔离验收替身】'+b['text'],basisIds=[b['id']],clueIds=[b['clueId']])])
experience.answer=answer
def segment(image,box,prompts=None):
    # Only the disposable fixture uses an approximate mask. It does not test SAM.
    w,h=image.size
    return image.crop((round(box['x']*w),round(box['y']*h),round((box['x']+box['w'])*w),round((box['y']+box['h'])*h))).convert('RGBA')
cutouts.segment=segment
pid='85e0f870d8bc';p=main.get(pid)
# Supply the two visually grounded test clues only in this disposable fixture.
# The production knowledge configuration is a separate user decision.
cid='f99c25ddc2f5';w=p['workspace'];knowledge=w['entities']['knowledge:'+cid]
visual_targets=['3ed5b7fb0910','789873d1c098']
knowledge['draft']['clueIds']=list(dict.fromkeys(knowledge['draft']['clueIds']+visual_targets))
ws.commit(p,w,knowledge)
role=w['entities']['persona:'+cid]
for clue_id in visual_targets:
    if not any(t['clueId']==clue_id for t in role['draft']['knowledgeTiming']):role['draft']['knowledgeTiming'].append(dict(clueId=clue_id,status='known',reason='隔离验收的画面可见内容',topic='眼前画面',question='使者与前后人物有何位置关系？'))
ws.commit(p,w,role)
p['title']='步辇图(2) · 隔离验收';p['artworkName']=p['title'];main.save(p,p['version'],'studio:fixture_title')
main.app.mount('/',StaticFiles(directory=ROOT/'dist',html=True),name='fixture-ui')
print(json.dumps(dict(data=str(data),url='http://127.0.0.1:8021',remoteModels=False),ensure_ascii=False),flush=True)
uvicorn.run(main.app,host='127.0.0.1',port=8021,log_level='warning')
