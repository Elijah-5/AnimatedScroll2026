from . import config
import csv
import io
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel
from typing import Literal
from . import agent
from .models import Project
from .domain import blank, reconcile, validate, uid, units, citation_errors

DATA = Path(os.getenv('CREATION_DATA_DIR', str(Path(__file__).parent.parent / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
app = FastAPI(title='Creation Agent')

def db():
    conn = sqlite3.connect(DATA / 'projects.sqlite')
    conn.execute('CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, project TEXT, body TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, body TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, project TEXT, time TEXT, action TEXT, before TEXT, after TEXT, meta TEXT)')
    return conn

def get(pid):
    with db() as conn:
        row = conn.execute('SELECT body FROM projects WHERE id=?', (pid,)).fetchone()
    if not row: raise HTTPException(404, '项目不存在')
    project=Project.model_validate_json(row[0]).model_dump()
    for source in project['sources']:
        if source['title']=='互动创作意图 · 非史料':source.setdefault('sourceType','creative_intent')
    return project

def save(project, expected, action, meta=None):
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT body FROM projects WHERE id=?', (project['id'],)).fetchone()
        old = json.loads(row[0]) if row else None
        if (old and old['version'] != expected) or (not old and expected != 0):
            raise HTTPException(409, '项目已变化，请重新加载；生成结果不会覆盖新版本。')
        project['version'] = expected + 1
        body = json.dumps(project, ensure_ascii=False)
        conn.execute('INSERT OR REPLACE INTO projects VALUES (?,?)', (project['id'], body))
        conn.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)', (uid(), project['id'], datetime.now(timezone.utc).isoformat(), action, row[0] if row else '{}', body, json.dumps(meta or {}, ensure_ascii=False)))
    return project

@app.get('/api/projects')
def projects():
    with db() as conn:
        return [dict(id=p['id'],title=p['title'],version=p['version']) for (body,) in conn.execute('SELECT body FROM projects') for p in [json.loads(body)]]

@app.post('/api/projects')
def create():
    return save(blank(), 0, 'create')

@app.get('/api/projects/{pid}')
def read(pid: str): return get(pid)

@app.put('/api/projects/{pid}')
def update(pid: str, project: Project):
    project = project.model_dump()
    old = Project.model_validate(get(pid)).model_dump()
    if project.get('id') != pid: raise HTTPException(400, '项目ID不匹配')
    try: updated = reconcile(old, project)
    except (ValueError, KeyError, TypeError) as exc: raise HTTPException(422, str(exc))
    return save(updated, project['version'], 'edit')

@app.post('/api/projects/{pid}/image')
async def image(pid: str, version: int, file: UploadFile):
    p = get(pid)
    data = await file.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024: raise HTTPException(413, '图片限20MB')
    ext = '.png' if data.startswith(b'\x89PNG\r\n\x1a\n') else '.jpg' if data.startswith(b'\xff\xd8\xff') else '.webp' if data[:4] == b'RIFF' and data[8:12] == b'WEBP' else ''
    if not ext: raise HTTPException(422, '仅支持 PNG、JPEG、WebP')
    name = uid() + ext
    (DATA / name).write_bytes(data)
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as img: img.verify()
    except Exception: raise HTTPException(422, '图片无法解码')
    p['image'] = '/api/images/' + name
    p['imageVersion'] = p.get('imageVersion', 0) + 1
    p['observations'] = []
    p['matches'] = []
    if p['title'] == '未命名项目': p['title'] = Path(file.filename or '未命名画作').stem
    p['annotations'] = []
    for u in units(p): u['status'] = 'pending'
    p['checks'] = []
    p['outlineConfirmed'] = False
    return save(p, version, 'upload_image')

@app.get('/api/images/{name}')
def read_image(name: str):
    if Path(name).name != name or Path(name).suffix not in ('.png','.jpg','.webp'): raise HTTPException(404)
    return FileResponse(DATA / name)

class GenerateRequest(BaseModel):
    version: int
    task: Literal['extract','outline','scene','classify','rewrite','check']
    sceneId: str = ''
    unitId: str = ''
    instruction: str = ''
    trigger: Literal['user_button'] = 'user_button'

@app.post('/api/projects/{pid}/generate')
async def generate(pid: str, req: GenerateRequest):
    p = get(pid)
    if p['version'] != req.version: raise HTTPException(409, '版本已变化')
    if req.task != 'extract' and (not p['characters'] or any(not c.get('confirmed') for c in p['characters'])):
        raise HTTPException(422, dict(code='characters_unconfirmed',message='请核对并确认以下人物资料',characters=[dict(id=c['id'],name=c['name']) for c in p['characters'] if not c.get('confirmed')],missingCharacters=not bool(p['characters'])))
    if req.task in ('scene','rewrite','classify') and not p['outlineConfirmed']: raise HTTPException(422, '请先确认大纲')
    if req.task in ('scene','rewrite','classify') and not any(s['id'] == req.sceneId for s in p['scenes']): raise HTTPException(422, '场景不存在')
    if req.task == 'extract' and p['characters']: raise HTTPException(422, '已有角色，不自动覆盖')
    if req.task == 'outline' and p['scenes']: raise HTTPException(422, '已有大纲，不自动覆盖')
    try: result = await agent.generate(req.task, p, req.sceneId, req.unitId, req.instruction)
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else '模型请求失败或超时，请检查后端配置与网络后重试。'
        raise HTTPException(502, message)
    if get(pid)['version'] != req.version: raise HTTPException(409, '生成期间项目已变化，原稿未被覆盖')
    if req.task in ('rewrite','classify'):
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT body FROM projects WHERE id=?', (pid,)).fetchone()
            if json.loads(row[0])['version'] != req.version: raise HTTPException(409, '提案生成期间版本已变化')
            conn.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)', (uid(), pid, datetime.now(timezone.utc).isoformat(), 'proposal:' + req.task, row[0], row[0], json.dumps(dict(model=agent.MODEL,promptVersion=agent.PROMPT_VERSION,trigger=req.trigger,instruction=req.instruction,proposal=result),ensure_ascii=False)))
        return dict(version=req.version, proposal=result, sceneId=req.sceneId, unitId=req.unitId, instruction=req.instruction)
    if req.task == 'extract': p['characters'] = result['characters']; p['outlineConfirmed'] = False
    if req.task == 'outline': p['scenes'] = result['scenes']; p['outlineConfirmed'] = False
    if req.task == 'check':
        p['checks'] = [dict(id=uid(),message='引用校验：'+error,resolved=False) for unit in units(p) for error in citation_errors(unit,p)] + result['checks']
    if req.task == 'scene':
        scene = next(s for s in p['scenes'] if s['id'] == req.sceneId)
        if scene['units']: raise HTTPException(422, '已有内容请使用局部重写')
        scene['units'] = result['units']
    if req.task != 'check': p['checks'] = []
    return save(p, req.version, 'generate:' + req.task, dict(model=agent.MODEL,promptVersion=agent.PROMPT_VERSION,trigger=req.trigger,instruction=req.instruction))

@app.post('/api/projects/{pid}/apply')
def apply(pid: str, payload: dict):
    p = get(pid)
    if p['version'] != payload['version']: raise HTTPException(409, '提案已过期，请重新生成')
    scene = next((s for s in p['scenes'] if s['id'] == payload['sceneId']), None)
    if not scene: raise HTTPException(422, '场景不存在')
    try:
        incoming = [agent.Unit.model_validate(u).model_dump() for u in payload['proposal']['units']]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, '提案格式无效') from exc
    if not incoming: raise HTTPException(422, '提案不能为空')
    old = scene['units']
    target = payload.get('unitId')
    if target and not any(u['id'] == target for u in old): raise HTTPException(422, '单元不存在')
    if target and next(u for u in old if u['id'] == target).get('locked'): raise HTTPException(422, '单元已锁定')
    fresh = [dict(u,id=uid(),status='pending',locked=False) for u in incoming]
    if target:
        scene['units'] = [v for u in old for v in (fresh if u['id'] == target else [u])]
    else:
        locked_texts = {u['text'] for u in old if u.get('locked')}
        fresh = [u for u in fresh if u['text'] not in locked_texts]
        merged = []
        for u in old:
            if u.get('locked'): merged.append(u)
            elif fresh: merged.append(fresh.pop(0))
        scene['units'] = merged + fresh
    p['checks'] = []
    p['reviewNotice'] = '局部修改已应用，请复核相邻场景。'
    return save(p, payload['version'], 'apply_proposal', dict(model=agent.MODEL,promptVersion=agent.PROMPT_VERSION,instruction=payload.get('instruction','')))

@app.get('/api/projects/{pid}/events')
def events(pid: str):
    get(pid)
    with db() as conn:
        return [dict(id=r[0],time=r[1],action=r[2],before=json.loads(r[3]),after=json.loads(r[4]),meta=json.loads(r[5])) for r in conn.execute('SELECT id,time,action,before,after,meta FROM events WHERE project=? ORDER BY rowid', (pid,))]

@app.get('/api/projects/{pid}/export')
def export(pid: str, format: Literal['json','md','jsonl','csv']='json', draft: bool=True):
    p = get(pid)
    issues = validate(p)
    if not draft and issues: raise HTTPException(422, '；'.join(issues))
    package = dict(schemaVersion='1.1',state='draft' if draft else 'approved',issues=issues,project=p)
    if format == 'json': body = json.dumps(package, ensure_ascii=False, indent=2)
    elif format == 'md':
        body = '# ' + p['title'] + ('（草稿）' if draft else '（已确认）') + '\n\n'
        for s in p['scenes']:
            body += '## ' + s['title'] + '\n\n' + s['goal'] + '\n\n'
            for u in s['units']:
                body += f"- [{u['category']} / {u['status']}] {u['text']}\n"
                for r in u.get('references', []): body += f"  - 依据 {r.get('sourceId') or r.get('annotationId')}: {r['quote']}\n"
        body += '\n## 资料\n' + '\n'.join(f"- {s['id']} · v{s['version']} · {s['title']} · {s['citation']}\n{s['text']}" for s in p['sources'])
    elif format == 'jsonl': body = '\n'.join(json.dumps(e,ensure_ascii=False) for e in events(pid))
    else:
        stream = io.StringIO(); writer = csv.writer(stream)
        writer.writerow(['id','time','action','before','after','meta'])
        for e in events(pid): writer.writerow([json.dumps(e[k],ensure_ascii=False) if isinstance(e[k],dict) else e[k] for k in ('id','time','action','before','after','meta')])
        body = '\ufeff' + stream.getvalue()
    return Response(body, media_type='text/plain; charset=utf-8', headers={'Content-Disposition': f'attachment; filename="story-{pid}.{format}"'})

@app.post('/api/sample')
def create_sample(example: str = 'hanxizai'):
    if example == 'zhekan':
        import shutil
        from .zhekan import sample
        name = 'example-zhekan.png'
        shutil.copyfile(config.ROOT / 'examples/assets/zhekan-user-reference.png', DATA / name)
        return save(sample('/api/images/' + name), 0, 'load_zhekan_sample')
    from .sample import sample
    return save(sample(), 0, 'load_editorial_sample')

from .pipeline import install
install(app, get, save, db, lambda: DATA)

from .people import install as install_people
install_people(app,get,save)

# A fresh clone opens the creator's latest saved project, without model calls.
def seed_latest_project():
    snapshot=config.ROOT/'examples/latest-project.json'
    if not snapshot.exists() or projects():return
    import shutil
    p=Project.model_validate_json(snapshot.read_text()).model_dump()
    shutil.copyfile(config.ROOT/'examples/assets/latest-project.png',DATA/'latest-project.png')
    p['image']='/api/images/latest-project.png'
    save(p,0,'restore_latest_snapshot')
app.router.add_event_handler('startup',seed_latest_project)
