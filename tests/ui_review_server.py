"""Read-only source copy, deterministic models, no remote service access."""
import os,sys,json,sqlite3,shutil,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
data=Path(os.environ['CREATION_REVIEW_FIXTURE_DIR']) if os.getenv('CREATION_REVIEW_FIXTURE_DIR') else Path(tempfile.mkdtemp(prefix='scroll-review-ui-'))
if not (data/'projects.sqlite').exists():
 with sqlite3.connect((ROOT/'data/projects.sqlite').as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(data/'projects.sqlite') as b:a.backup(b)
 for path in (ROOT/'data').iterdir():
  if path.is_file() and path.suffix in ('.png','.jpg','.jpeg','.webp','.pdf','.txt'):shutil.copy2(path,data/path.name)
 for name in ('videos','video-inputs','experience-cutouts','experience-presentations','experience-preparations','experience-preparation-requests','experience-asset-owners'):
  if (ROOT/'data'/name).exists():shutil.copytree(ROOT/'data'/name,data/name)
os.environ.update(CREATION_DATA_DIR=str(data),CREATION_DB_BACKEND='sqlite',CREATION_SEED_LATEST='0',AIHUBMIX_API_KEY='',DASHSCOPE_API_KEY='')
from backend import main,studio_agent,authoring_defaults,experience,structured,materials,documents,vision,review_units as ru,workspace as ws
from test_completions import provider,defaults
studio_agent.run=provider;authoring_defaults.intent=defaults
async def aggregate(ctx):return structured.Suggestion().model_dump()
structured.ask=aggregate
async def answer(ctx,message,*args):
 if '你好' in message:return dict(disposition='smalltalk',segments=[dict(text='【本地替身】来，且与你说说眼前之事。')])
 b=next((v for v in ctx['basis'] if v['clueId']),ctx['basis'][0]);return dict(disposition='grounded',segments=[dict(text=b['text'],basisIds=[b['id']],clueIds=[b['clueId']] if b['clueId'] else [])])
experience.answer=answer
# No other model path is permitted in this fixture.
async def forbidden(*args,**kwargs):raise ValueError('隔离验收：此操作未配置模型替身，未发送远程请求')
vision.ask=forbidden;vision.analyze=forbidden;vision.match_people=forbidden;materials.organize=forbidden;documents.ask=forbidden
if not os.getenv('CREATION_REVIEW_FIXTURE_DIR'):
 with main.db() as c:ids=[r[0] for r in c.execute('SELECT id FROM projects')]
 for pid in ids:
  p=main.get(pid);ws.ensure(p)
  with main.db() as c:events=c.execute("SELECT action,`after`,meta FROM events WHERE project=? AND (action LIKE 'studio:confirm:%' OR action='studio:batch_confirm' OR action='confirm_person') ORDER BY rowid",(pid,)).fetchall()
  ru.recover_reviews(p,events);ru.make_available(p);main.save(p,p['version'],'studio:fixture_review')
if os.getenv('CREATION_EXPERIENCE_FAKE_CUTOUTS'):
 from backend import cutouts
 from PIL import Image,ImageDraw
 import time
 def local_cutout(image,box,prompts=None):
  calls=data/'segment-calls.json';items=json.loads(calls.read_text()) if calls.exists() else [];items.append(box);calls.write_text(json.dumps(items))
  fail=data/'fail-next-cutout'
  if fail.exists():fail.unlink();raise ValueError('副本验收：模拟单个人物分割失败')
  time.sleep(float(os.getenv('CREATION_CUTOUT_LATENCY','.05')))
  result=Image.new('RGBA',(80,140),(0,0,0,0));ImageDraw.Draw(result).ellipse((8,2,72,138),fill='#8e7954');return result
 cutouts.segment=local_cutout
if os.getenv('CREATION_REQUEST_COUNTS'):
 @main.app.middleware('http')
 async def count_requests(request,call_next):
  dest=data/'request-counts.json'
  value=json.loads(dest.read_text()) if dest.exists() else {}
  key=request.method+' '+request.url.path;value[key]=value.get(key,0)+1;dest.write_text(json.dumps(value))
  return await call_next(request)
if os.getenv('CREATION_STARTUP_LATENCY') or os.getenv('CREATION_STARTUP_FAIL_ONCE'):
 import asyncio
 from fastapi.responses import JSONResponse
 startup_failed=False
 @main.app.middleware('http')
 async def startup_preview(request,call_next):
  global startup_failed
  if request.method=='GET' and request.url.path=='/api/projects' and os.getenv('CREATION_STARTUP_FAIL_ONCE')=='1' and not startup_failed:
   startup_failed=True;return JSONResponse(dict(detail='验收：模拟首次连接失败，重新加载即可恢复'),status_code=503)
  if request.method=='GET' and request.url.path.endswith('/studio/editor'):await asyncio.sleep(float(os.getenv('CREATION_STARTUP_LATENCY','0')))
  return await call_next(request)
print(json.dumps(dict(data=str(data),remoteModels=False)),flush=True)
import uvicorn
uvicorn.run(main.app,host='127.0.0.1',port=int(os.getenv('CREATION_UI_REVIEW_PORT','8018')),log_level='warning')
