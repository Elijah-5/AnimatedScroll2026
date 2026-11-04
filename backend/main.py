from . import config
import csv
import io
import json
import os
import sqlite3
import copy
import hashlib
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field
from typing import Literal
from . import agent
from .models import Project
from .domain import blank, reconcile, validate, uid, units, citation_errors

DATA = Path(os.getenv('CREATION_DATA_DIR', str(Path(__file__).parent.parent / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
app = FastAPI(title='Creation Agent')
_revision_reads=OrderedDict()
_revision_read_lock=threading.Lock()

def db():
    from . import storage
    conn = storage.connect(DATA)
    conn.execute('CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, project TEXT, body TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, body TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, project TEXT, time TEXT, action TEXT, before TEXT, after TEXT, meta TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS document_cache(key TEXT PRIMARY KEY,body TEXT)')
    for table in ('video_jobs','studio_jobs','experience_sessions','experience_turns'):
        conn.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY, project TEXT, body TEXT)')
    from .media_previews import schema as preview_schema
    preview_schema(conn)
    from . import catalog
    catalog.schema(conn)
    from .history_schema import schema as history_schema
    history_schema(conn)
    from . import read_models,snapshot_store
    read_models.schema(conn);snapshot_store.schema(conn)
    return conn

def get(pid,decorate=True):
    with db() as conn:
        row = conn.execute('SELECT body FROM projects WHERE id=?', (pid,)).fetchone()
    if not row: raise HTTPException(404, '项目不存在')
    project=Project.model_validate_json(row[0]).model_dump()
    from .revisions import upgrade
    if project.get('workspace',{}).get('revisionPolicy')!=1:
        # Legacy audit replay can be large. Cache only immutable read snapshots,
        # never the mutable project handed to a caller. Either body or audit
        # changes or appended audit rows invalidate the entry, even when the
        # project body was repaired without a version bump.
        with db() as conn:
            audit=tuple(conn.execute('SELECT COUNT(*),MAX(time),MAX(id) FROM events WHERE project=?',(pid,)).fetchone())
        from .storage import backend as storage_backend
        token=(storage_backend(),str(DATA.resolve()),pid,hashlib.sha256(row[0].encode()).hexdigest(),audit)
        with _revision_read_lock:
            cached=_revision_reads.get(token)
            if cached is not None:
                project=copy.deepcopy(cached);_revision_reads.move_to_end(token)
            else:
                def old_versions():
                    with db() as conn:
                        for before,after in conn.execute('SELECT `before`,`after` FROM events WHERE project=? ORDER BY rowid',(pid,)):
                            for body in (before,after):yield json.loads(body)
                upgrade(project,old_versions)
                _revision_reads[token]=copy.deepcopy(project)
                while len(_revision_reads)>8:_revision_reads.popitem(last=False)
    from .revisions import decorate as decorate_project
    if project.get('workspace') and decorate:decorate_project(project['workspace'])
    for source in project['sources']:
        if source['title']=='互动创作意图 · 非史料':source.setdefault('sourceType','creative_intent')
    return project

def save(project, expected, action, meta=None, transaction_hook=None):
    with db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT body FROM projects WHERE id=?', (project['id'],)).fetchone()
        old = json.loads(row[0]) if row else None
        if (old and old['version'] != expected) or (not old and expected != 0):
            raise HTTPException(409, '项目已变化，请重新加载；生成结果不会覆盖新版本。')
        from .project_names import artwork_name,unique_title
        if 'artworkName' in project or old is None or (old and project['title']!=old['title']):
            name=project.get('artworkName') or project['title']
            if old and project['title']!=old['title'] and project.get('artworkName')==old.get('artworkName'):
                name=project['title']
            project['artworkName']=artwork_name(name)
            from .read_models import metadata
            occupied={p['title'] for p in metadata(conn) if p['id']!=project['id']}
            project['title']=unique_title(project['artworkName'],occupied,project['title'])
        from .workspace import ingest,ensure
        if old and 'workspace' in old and not action.startswith('studio:'):
            ingest(old,project)
        ensure(project)
        unified=project['workspace']['entities']['material:main']['draft'].get('structured')
        if unified:
            from .structured import validate as validate_structured,finish
            try:validate_structured(unified);finish(unified)
            except (ValueError,KeyError,TypeError,AttributeError) as exc:raise HTTPException(422,'作品资料库草稿格式无效：'+str(exc))
        from .revisions import decorate
        decorate(project['workspace'])
        if action.startswith(('studio:generation:','studio:adopt_','studio:generated:','analysis:')):
            from .review_units import changed_members,make_available
            if action.startswith('analysis:') and (meta or {}).get('autoEnable'):make_available(project)
            if old:changed_members(old,project,'AI')
        if transaction_hook:transaction_hook(conn,old,project)
        project['version'] = expected + 1
        from . import read_models,snapshot_store
        body = json.dumps(read_models.clean_project(project), ensure_ascii=False)
        conn.execute('INSERT OR REPLACE INTO projects VALUES (?,?)', (project['id'], body))
        conn.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)', (uid(), project['id'], datetime.now(timezone.utc).isoformat(), action, snapshot_store.pack(row[0],conn) if row else '{}', snapshot_store.pack(body,conn), json.dumps(meta or {}, ensure_ascii=False)))
        from .catalog import synchronize
        synchronize(conn,project)
        from .structured import synchronize as sync_structured
        sync_structured(conn,old,project)
        read_models.write(conn,project)
    return project

@app.get('/api/projects')
def projects(archived:bool=False):
    with db() as conn:
        from .read_models import metadata
        return [{k:v for k,v in p.items() if k!='archived'} for p in metadata(conn) if p['archived']==archived]

class ProjectName(BaseModel):
    model_config={'str_strip_whitespace':True}
    title: str = Field(default='未命名项目',min_length=1,max_length=120)
class RenameProject(ProjectName):
    version: int

@app.post('/api/projects')
def create(payload: ProjectName|None=None):
    p=blank()
    if payload:
        p['title']=payload.title.strip()
        if not p['title']:raise HTTPException(422,'项目名称不能为空')
    p['artworkName']=p['title']
    return save(p, 0, 'create')

@app.patch('/api/projects/{pid}/metadata')
def rename_project(pid:str,payload:RenameProject):
    p=get(pid)
    if p['version']!=payload.version:raise HTTPException(409,'项目已变化，请重新加载后改名')
    title=payload.title.strip()
    if not title:raise HTTPException(422,'项目名称不能为空')
    from .project_names import artwork_name
    if artwork_name(title)==p.get('artworkName',p['title']):return p
    p['artworkName']=artwork_name(title);p['title']=p['artworkName']
    return save(p,payload.version,'studio:rename_project')

@app.get('/api/projects/{pid}')
def read(pid: str): return get(pid)

@app.put('/api/projects/{pid}')
def update(pid: str, project: Project):
    project = project.model_dump()
    old = Project.model_validate(get(pid)).model_dump()
    if old.get('workspace') and project.get('workspace'):
        for key in ('revisionArchive','historyLibrary','reviewUnits','batchReceipts'):
            if key not in project['workspace'] and key in old['workspace']:project['workspace'][key]=copy.deepcopy(old['workspace'][key])
        for key,r in project['workspace']['entities'].items():
            previous=old['workspace']['entities'].get(key,{})
            if 'history' not in r:r['history']=copy.deepcopy(previous.get('history',[]))
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
    if p.get('artworkName',p['title']) in ('未命名项目','未命名画作'):
        p['artworkName']=Path(file.filename or '未命名画作').stem;p['title']=p['artworkName']
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
    # The archived synchronous endpoint shares the same project-level gate.
    from . import task_runtime as tr
    p=get(pid)
    if p['version']!=req.version:raise HTTPException(409,'版本已变化')
    task=dict(id=uid(),projectId=pid,kind='legacy_'+req.task,request=req.model_dump(),status='running',progress='旧版生成任务',time=tr.now(),startedAt=tr.now())
    try:tr.reserve(db,'tasks',task)
    except ValueError as exc:raise HTTPException(409,str(exc))
    try:
        result=await legacy_generate(pid,req)
        task.update(status='completed',progress='旧版生成完成')
        return result
    except Exception:
        task.update(status='failed',progress='旧版生成未完成，原稿保留')
        raise
    finally:
        with db() as conn:conn.execute('UPDATE tasks SET body=? WHERE id=?',(json.dumps(task,ensure_ascii=False),task['id']))

async def legacy_generate(pid: str, req: GenerateRequest):
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
            from .snapshot_store import pack
            snapshot=pack(row[0],conn)
            conn.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?)', (uid(), pid, datetime.now(timezone.utc).isoformat(), 'proposal:' + req.task, snapshot, snapshot, json.dumps(dict(model=agent.MODEL,promptVersion=agent.PROMPT_VERSION,trigger=req.trigger,instruction=req.instruction,proposal=result),ensure_ascii=False)))
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
        body += '\n## 资料\n' + '\n'.join(f"- {s['id']} | v{s['version']} | {s['title']} | {s['citation']}\n{s['text']}" for s in p['sources'])
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
    if os.getenv('CREATION_SEED_LATEST','1')!='1':return
    snapshot=config.ROOT/'examples/latest-project.json'
    if not snapshot.exists():return
    with db() as c:
        if c.execute('SELECT COUNT(*) FROM projects').fetchone()[0]:return
    import shutil
    p=Project.model_validate_json(snapshot.read_text()).model_dump()
    shutil.copyfile(config.ROOT/'examples/assets/latest-project.png',DATA/'latest-project.png')
    p['image']='/api/images/latest-project.png'
    save(p,0,'restore_latest_snapshot')
app.router.add_event_handler('startup',seed_latest_project)

from .studio import install as install_studio
install_studio(app,lambda pid:get(pid,decorate=False),save,db)
from .review_units import install as install_review_units
install_review_units(app,lambda pid:get(pid,decorate=False),save,db,lambda:DATA)
from .completions import install as install_completions
install_completions(app,get,save,db,lambda:DATA)

from . import catalog,video,experience,narrative
catalog.install(app,get,db)
video.install(app,get,save,db,lambda:DATA)
from . import media_previews
media_previews.install(app,get,db,lambda:DATA)
experience.install(app,get,db,lambda:DATA)
from . import structured
structured.install(app,get,save,db)
narrative.install(app,get,save,db,lambda:DATA)
from .history import install as install_history
install_history(app,get,save,db)
from .acceptance_media import install as install_acceptance_media
install_acceptance_media(app,lambda:DATA)
from .read_models import install as install_read_models
install_read_models(app,lambda pid:get(pid,decorate=False),db,lambda:DATA)
from .creation_copy import install as install_creation_copy
install_creation_copy(app,lambda pid:get(pid,decorate=False),save,db,lambda:DATA)

class ArchiveProject(BaseModel):version:int

@app.post('/api/projects/{pid}/archive')
def archive(pid:str,req:ArchiveProject):
    p=get(pid);p['archived']=True
    return save(p,req.version,'studio:archive')

@app.post('/api/projects/{pid}/restore')
def restore(pid:str,req:ArchiveProject):
    p=get(pid);p['archived']=False
    return save(p,req.version,'studio:restore')

ARTWORK_SAMPLES={
    'zhekan':('折槛图','宋人折槛图_部分.jpg'),
    'bunian':('步辇图','步辇图.jpg'),
    'chongping':('重屏会棋图','重屏会棋图.jpg'),
}

@app.get('/api/samples/artworks')
def artwork_samples():return [dict(id=key,title=value[0]) for key,value in ARTWORK_SAMPLES.items()]

@app.post('/api/samples/artworks/{sample_id}')
def import_artwork_sample(sample_id:str):
    import shutil
    if sample_id not in ARTWORK_SAMPLES:raise HTTPException(404,'示例不存在')
    title,filename=ARTWORK_SAMPLES[sample_id];source=config.ROOT/'examples/assets'/filename
    if not source.is_file():raise HTTPException(404,'示例画作文件不存在')
    p=blank();p['title']=title;p['artworkName']=title;p['imageVersion']=1
    target=uid()+'.jpg';shutil.copyfile(source,DATA/target);p['image']='/api/images/'+target
    return save(p,0,'import_artwork_sample',dict(sample=sample_id,note='只导入画作，不预设身份或确认资料'))
