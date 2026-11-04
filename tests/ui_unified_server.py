"""Disposable real-project UI fixture. Explicit opt-in; all remote models replaced."""
import os
import sys
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
if os.getenv('CREATION_UNIFIED_UI_TEST')!='1':raise SystemExit('CREATION_UNIFIED_UI_TEST=1 required')
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
data=Path(os.environ['CREATION_UNIFIED_FIXTURE_DIR']) if os.getenv('CREATION_UNIFIED_FIXTURE_DIR') else Path(tempfile.mkdtemp(prefix='scroll-unified-ui-'))
if not any(data.resolve().is_relative_to(folder.resolve()) for folder in (Path(tempfile.gettempdir()),Path('/tmp'))):raise SystemExit('Fixture data must be inside a temporary directory')
if not (data/'projects.sqlite').exists():
    with sqlite3.connect((ROOT/'data/projects.sqlite').as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(data/'projects.sqlite') as target:source.backup(target)
    for path in (ROOT/'data').iterdir():
        if path.is_file() and path.suffix in ('.png','.jpg','.jpeg','.webp','.pdf','.txt'):shutil.copy2(path,data/path.name)
    for name in ('videos','video-inputs','experience-cutouts'):
        if (ROOT/'data'/name).exists():shutil.copytree(ROOT/'data'/name,data/name)
os.environ.update(CREATION_DATA_DIR=str(data),CREATION_DB_BACKEND='sqlite',CREATION_SEED_LATEST='0',MODEL_PROVIDER='aihubmix',AIHUBMIX_API_KEY='',DASHSCOPE_API_KEY='')
from backend import main,structured,experience,studio_agent,materials,config,documents
from fastapi.testclient import TestClient
import uvicorn

if os.getenv('CREATION_NAVIGATION_LATENCY'):
    import asyncio
    traffic={}
    @main.app.middleware('http')
    async def slow_full_reads(request,call_next):
        key=request.method+' '+request.url.path;traffic[key]=traffic.get(key,0)+1
        (data/'navigation-traffic.json').write_text(json.dumps(traffic,ensure_ascii=False))
        if request.method=='GET' and request.url.path.endswith('/studio'):await asyncio.sleep(float(os.environ['CREATION_NAVIGATION_LATENCY']))
        return await call_next(request)

async def aggregate(ctx):
    result=structured.Suggestion().model_dump()
    author=next((e for e in ctx['evidence'] if '阎立本' in e['quote']),None)
    if author:result['artwork'].append(dict(field='artist',value='【模型替身】文献提及阎立本，作者归属待核对',referenceIds=[author['id']]))
    story=next((e for e in ctx['evidence'] if '唐太宗' in e['quote'] and '禄东赞' in e['quote']),None)
    if story:result['artwork'].append(dict(field='storyOneLiner',value='【模型替身】唐太宗接见禄东赞，具体解释以资料为准',referenceIds=[story['id']]))
    return result
async def answer(context,message,*args):
    if not context.get('persona'):return dict(answer='【模型替身】仅依照本角色的确认资料和所绑定线索回答。',clueIds=[c['id'] for c in context['clues']][:1],basis='clues')
    if '闲聊' in message or '你好' in message:return dict(disposition='smalltalk',segments=[dict(text='【模型替身】且在此歇一歇，你想聊些什么？')])
    if '未来' in message:return dict(disposition='unknown',segments=[dict(text='【模型替身】此刻尚未发生的事，我怎能预知？')])
    rows=[]
    for category in ('supported','inference'):
        b=next((b for b in context['basis'] if b['category']==category and b['clueId']),None)
        if b:rows.append(dict(text=b['text'],basisIds=[b['id']],clueIds=[b['clueId']]))
    b=next((b for b in context['basis'] if b['clueId']),context['basis'][0])
    rows.append(dict(text='【模型替身】我稍一停顿，且与你说说眼前之事。',basisIds=[b['id']],clueIds=[b['clueId']] if b['clueId'] else []))
    return dict(segments=rows)

async def organize_materials(project,legacy=False):return dict(segments=[],characters=[],eventFramework=[],summary='【模型替身】保留原资料',inputVersion=project['materialInputs']['version'],stale=False)
async def document_model(schema,payload,stats,validator=None):
    if schema is documents.Extracted:
        passage=payload['passages'][0];quote=passage['text'][:120]
        result=dict(claims=[dict(kind='background',text='【模型替身】仅归纳所选文献中提供的文字。',assertion='description',references=[dict(sourceId=passage['sourceId'],quote=quote)],indirectSource='')],people=[])
    elif schema is documents.Topics:result=dict(assignments=[dict(claimId='C'+str(i+1),topic='culture') for i,_ in enumerate(payload['claims'])])
    else:result=dict(paragraphs=[dict(text='【模型替身】'+payload['claims'][0]['text'],claimIds=['C1'])])
    return validator(result) if validator else result
async def generate(kind,ctx):
    if kind=='persona':
        from backend.persona import empty
        values=[]
        for role in ctx['roles']:
            row=empty(role['characterId']);row.update(prompt='【模型替身】你身处画中事件当时，依确认身份自然交谈，不预知后来，不编造生平。',knowledgeTiming=[dict(clueId=c['id'],status='after' if '后续' in c['phases'] else 'known',reason='【模型替身】时间候选，须人工核对',topic='当时见闻',question='方才眼前发生了什么？') for c in role['clues']]);values.append(row)
        return dict(personas=values)

    if kind=='storyboard':return dict(prompt='【模型替身】人物衣袖轻动，延续古画构图。',startFrame='人物静立',endFrame='恢复静立',action='衣袖轻动',camera='固定镜头',style='延续古画')
    if kind=='check':return dict(checks=[])
    if kind=='culture':
        s=next(s for s in ctx['sources'] if s['text'].strip());quote=s['text'][:30]
        return dict(clues=[dict(name='【模型替身】统一资料依据',summary=quote,characterIds=[],units=[dict(text=quote,kind='clue',category='supported',references=[dict(sourceId=s['id'],sourceVersion=s['version'],quote=quote)])])])
    raise ValueError('本隔离预览未为此操作提供模型替身')
structured.ask=aggregate;experience.answer=answer;studio_agent.run=generate
materials.organize=organize_materials
documents.ask=document_model
assert not config.model_settings(require_key=False).api_key
with TestClient(main.app) as client:
    p=main.get('85e0f870d8bc')
    print(json.dumps(dict(projectId=p['id'],version=p['version'],data=str(data),providers='local_fakes_only')),flush=True)
uvicorn.run(main.app,host='127.0.0.1',port=int(os.getenv('CREATION_UNIFIED_FIXTURE_PORT','8018')),log_level='warning')
