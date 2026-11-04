"""UI validation on a real-project copy. All model calls use deterministic fakes."""
import os,sys,sqlite3,json,shutil,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
data=Path(os.environ['CREATION_ONECLICK_UI_DATA']) if os.getenv('CREATION_ONECLICK_UI_DATA') else Path(tempfile.mkdtemp(prefix='scroll-oneclick-ui-'))
if not (data/'projects.sqlite').exists():
    with sqlite3.connect((ROOT/'data/projects.sqlite').as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(data/'projects.sqlite') as b:a.backup(b)
    for p in (ROOT/'data').iterdir():
        if p.is_file() and p.suffix in ('.png','.jpg','.jpeg','.webp','.pdf','.txt'):shutil.copy2(p,data/p.name)
    for name in ('videos','video-inputs','experience-cutouts'):
        if (ROOT/'data'/name).exists():shutil.copytree(ROOT/'data'/name,data/name)
os.environ.update(CREATION_DATA_DIR=str(data),CREATION_DB_BACKEND='sqlite',CREATION_SEED_LATEST='0',AIHUBMIX_API_KEY='',DASHSCOPE_API_KEY='')
from backend import main,studio_agent,authoring_defaults,experience
from test_completions import provider,defaults
studio_agent.run=provider;authoring_defaults.intent=defaults
async def answer(ctx,message,history):
    if '你好' in message:return dict(disposition='smalltalk',segments=[dict(text='【本地替身】来，且与你说说眼前之事。')])
    b=next((v for v in ctx['basis'] if v['clueId']),ctx['basis'][0]);return dict(disposition='grounded',segments=[dict(text=b['text'],basisIds=[b['id']],clueIds=[b['clueId']] if b['clueId'] else [])])
experience.answer=answer
print(json.dumps(dict(data=str(data),remoteModels=False)),flush=True)
import uvicorn
uvicorn.run(main.app,host='127.0.0.1',port=8018,log_level='warning')
