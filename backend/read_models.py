"""Transactional editor projections; cold starts and idle polls never replay audit history."""
import hashlib,json,threading
from pathlib import Path
from fastapi import HTTPException
from . import storage
POLICY=hashlib.sha256(b''.join((Path(__file__).parent/name).read_bytes() for name in ('read_models.py','review_units.py','workspace.py','persona.py','revisions.py','experience.py'))).hexdigest()[:20]
_lock=threading.RLock()

def schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS studio_read_models(project TEXT PRIMARY KEY,version INTEGER NOT NULL,title TEXT NOT NULL,archived INTEGER NOT NULL,policy TEXT NOT NULL,editor TEXT NOT NULL,checks TEXT NOT NULL,assets TEXT NOT NULL)')
    c.execute('CREATE INDEX IF NOT EXISTS events_project_lookup ON events(project)')
    if getattr(c,'dialect','sqlite')=='sqlite':
        for operation in ('INSERT','UPDATE','DELETE'):
            column='OLD' if operation=='DELETE' else 'NEW'
            c.execute(f'CREATE TRIGGER IF NOT EXISTS invalidate_studio_{operation.lower()} AFTER {operation} ON projects BEGIN DELETE FROM studio_read_models WHERE project={column}.id; END')

def dump(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
def clean_project(p):
    w=p.get('workspace')
    if not w:return p
    return dict(p,workspace=dict(w,entities={key:{field:value for field,value in r.items() if field!='basisWarnings'} for key,r in w['entities'].items()}))

def write(c,p):
    from .review_units import compact_project
    editor=compact_project(clean_project(p));editor['workspace']['jobs']=[]
    c.execute('INSERT OR REPLACE INTO studio_read_models VALUES (?,?,?,?,?,?,?,?)',(p['id'],p['version'],p['title'],int(bool(p.get('archived'))),POLICY,dump(editor),'',''))

def metadata(c,pid=None):
    # Canonical JSON is only inspected for heads missing a projection. SQLite's
    # JSON engine returns scalar metadata without materializing Python history.
    expr="JSON_UNQUOTE(JSON_EXTRACT(p.body,'$.title'))" if getattr(c,'dialect','sqlite')=='mysql' else "json_extract(p.body,'$.title')"
    version="CAST(JSON_UNQUOTE(JSON_EXTRACT(p.body,'$.version')) AS UNSIGNED)" if getattr(c,'dialect','sqlite')=='mysql' else "json_extract(p.body,'$.version')"
    archived="COALESCE(JSON_UNQUOTE(JSON_EXTRACT(p.body,'$.archived')),'false')='true'" if getattr(c,'dialect','sqlite')=='mysql' else "COALESCE(json_extract(p.body,'$.archived'),0)"
    params=(pid,) if pid else ()
    sql=f'SELECT p.id,COALESCE(r.title,{expr}),COALESCE(r.version,{version}),COALESCE(r.archived,{archived}) FROM projects p LEFT JOIN studio_read_models r ON r.project=p.id'+(' WHERE p.id=?' if pid else '')
    return [dict(id=a,title=b,version=int(v),archived=bool(ar)) for a,b,v,ar in c.execute(sql,params)]

def asset_signature(editor,data):
    names={Path(editor.get('image','')).name} if editor.get('image') else set()
    root=Path(data);items=[]
    for name in sorted(names):
        path=root/name
        try:s=path.stat();items.append((name,s.st_size,s.st_mtime_ns))
        except OSError:items.append((name,None,None))
    videos=root/'videos'
    if videos.exists():
        for path in sorted(videos.glob('*.mp4')):
            s=path.stat();items.append((str(path.relative_to(root)),s.st_size,s.st_mtime_ns))
    return dump(items)

def install(app,get,db,data):
    def row(pid):
        with db() as c:value=c.execute('SELECT version,policy,editor,checks,assets FROM studio_read_models WHERE project=?',(pid,)).fetchone()
        if value and value[1]==POLICY:return value
        with _lock:
            for attempt in range(3):
                p=get(pid)
                with db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    heads=metadata(c,pid)
                    if not heads:raise HTTPException(404,'项目不存在')
                    if heads[0]['version']!=p['version']:continue
                    write(c,p)
                with db() as c:return c.execute('SELECT version,policy,editor,checks,assets FROM studio_read_models WHERE project=?',(pid,)).fetchone()
        raise HTTPException(409,'项目正在更新，请重新读取')
    def editor(pid):
        value=row(pid);p=json.loads(value[2])
        p['workspace']['jobs']=app.state.studio_jobs(pid) if hasattr(app.state,'studio_jobs') else []
        return p
    def checks(pid):
        for attempt in range(3):
            value=row(pid);view=json.loads(value[2])
            with db() as c:jobs=[(key,hashlib.sha256(body.encode()).hexdigest()) for key,body in c.execute('SELECT id,body FROM video_jobs WHERE project=?',(pid,))]
            assets=dump([asset_signature(view,data()),jobs])
            if value[3] and value[4]==assets:return json.loads(value[3])
            p=get(pid)
            if p['version']!=value[0]:continue
            report=app.state.review_report(p)
            with db() as c:c.execute('UPDATE studio_read_models SET checks=?,assets=? WHERE project=? AND version=? AND policy=?',(dump(report),assets,pid,p['version'],POLICY))
            return report
        raise HTTPException(409,'项目正在更新，请重新读取')
    @app.get('/api/studio/bootstrap')
    def bootstrap(projectId:str=''):
        for attempt in range(3):
            with db() as c:projects=[{k:v for k,v in p.items() if k!='archived'} for p in metadata(c) if not p['archived']]
            chosen=next((p for p in projects if p['id']==projectId),projects[0] if projects else None)
            if not chosen:return dict(projects=[],project=None,checks={})
            p=editor(chosen['id']);report=checks(chosen['id'])
            with db() as c:head=metadata(c,p['id'])
            if head and p['version']==head[0]['version']:return dict(projects=projects,project=p,checks=report)
        raise HTTPException(409,'项目正在更新，请重新加载')
    app.state.studio_editor=editor;app.state.studio_checks=checks
