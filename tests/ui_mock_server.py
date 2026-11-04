"""Explicit isolated browser fixture. Never connect this harness to creator data."""
import os
import sys
import tempfile
from pathlib import Path

if os.getenv('CREATION_MERGE_UI_TEST')!='1':raise SystemExit('Set CREATION_MERGE_UI_TEST=1 to run the isolated mock server')
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'tests')]
os.environ.update(CREATION_DATA_DIR=tempfile.mkdtemp(prefix='animatedscroll-merge-ui-'),CREATION_SEED_LATEST='0',CREATION_DB_BACKEND='sqlite',MODEL_PROVIDER='aihubmix',AIHUBMIX_API_KEY='',DASHSCOPE_API_KEY='fake-ui-only-key')
from fastapi.testclient import TestClient
from backend import main,experience,video
from test_merged_features import ready
from PIL import Image,ImageDraw
import httpx
import uvicorn

with TestClient(main.app) as client:
    p,cid=ready(client)
    main.rename_project(p['id'],main.RenameProject(version=p['version'],title='隔离模拟验收 · 通用古画'))
    # This drawing is a test fixture, not a model-generated painting or real result.
    image=Image.new('RGB',(800,400),'#d7c5a2');draw=ImageDraw.Draw(image)
    for x in (80,400):
        draw.ellipse((x+30,45,x+90,110),fill='#564c3a');draw.polygon([(x+30,110),(x,320),(x+130,320),(x+90,110)],fill='#6c7e66')
    image.save(main.DATA/'merged-reference.png')

async def fake_answer(context,message,history):
    return dict(answer='【模拟回答】我在这一刻略作停顿。这是一段经过创作者确认的叙事创作。',clueIds=[c['id'] for c in context['clues']][:1])
experience.answer=fake_answer
original=httpx.AsyncClient
def handle(request):
    if request.method=='POST':return httpx.Response(200,json={'output':{'task_id':'ui-mock-remote'}})
    if '/tasks/' in str(request.url):return httpx.Response(200,json={'output':{'task_status':'SUCCEEDED','video_url':'https://mock.aliyuncs.com/fixture.mp4'}})
    media=Path('/tmp/animatedscroll-mock.mp4')
    return httpx.Response(200,content=media.read_bytes() if media.is_file() else b'isolated-placeholder-video'*100)
video.httpx.AsyncClient=lambda **kw:original(transport=httpx.MockTransport(handle),**kw)
print('Isolated mock database:',main.DATA,flush=True)
uvicorn.run(main.app,host='127.0.0.1',port=8017,log_level='warning')
