"""Explicit backend-only rollout; snapshot all current data and preserve the Vite PID."""
import argparse,hashlib,json,os,shutil,signal,sqlite3,time
from datetime import datetime,timezone
from pathlib import Path
import server_control as service
ROOT=service.ROOT

def file_hash(path):
    value=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()

def logical(path):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as c:
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        result={}
        for table in tables:
            value=hashlib.sha256()
            for row in c.execute('SELECT * FROM "'+table+'" ORDER BY 1,2'):
                value.update(json.dumps(row,ensure_ascii=False).encode());value.update(b'\n')
            result[table]=value.hexdigest()
        return result

def pending_turns():
    with sqlite3.connect((ROOT/'data/projects.sqlite').as_uri()+'?mode=ro',uri=True) as c:
        return sum(json.loads(b).get('status')=='pending' for b, in c.execute('SELECT body FROM experience_turns'))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--reload',action='store_true');ap.add_argument('--review-receipts',action='store_true');args=ap.parse_args()
    if not args.reload:raise SystemExit('--reload required')
    deadline=time.monotonic()+120
    while service.active_tasks() or pending_turns():
        if time.monotonic()>deadline:raise SystemExit('Still active tasks/turns; no process was stopped')
        print('Waiting for active generation/dialogue to finish',flush=True);time.sleep(2)
    backend=service.listeners(8000);frontend=service.listeners(5173)
    assert len(backend)==len(frontend)==1 and service.ours(backend[0],'backend') and service.ours(frontend[0],'frontend')
    folder=ROOT.parent/'merge-backups'/(('review-rollout-' if args.review_receipts else 'one-click-rollout-')+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));folder.mkdir()
    shutil.copytree(ROOT/'data',folder/'data',ignore=lambda path,names:[n for n in names if Path(path)==ROOT/'data' and n in ('projects.sqlite','projects.sqlite-shm','projects.sqlite-wal')])
    if service.active_tasks() or pending_turns():raise SystemExit('New task arrived; snapshot kept, reload not performed')
    with sqlite3.connect((ROOT/'data/projects.sqlite').as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(folder/'data/projects.sqlite') as b:a.backup(b)
    before=logical(ROOT/'data/projects.sqlite')
    assert before==logical(folder/'data/projects.sqlite'), 'Data changed during snapshot; no reload'
    manifest=[]
    for p in sorted((folder/'data').rglob('*')):
        if p.is_file():
            checksum=file_hash(p)
            if p.relative_to(folder)!=Path('data/projects.sqlite'):assert checksum==file_hash(ROOT/p.relative_to(folder)), 'File changed during snapshot'
            manifest.append(dict(path=str(p.relative_to(folder)),sha256=checksum,size=p.stat().st_size))
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    if args.review_receipts:
        source=folder/'source';source.mkdir()
        excluded={'.git','.venv','node_modules','data','models','dist','.runtime','.pytest_cache','__pycache__'}
        for path in ROOT.iterdir():
            if path.name in excluded:continue
            if path.is_dir():shutil.copytree(path,source/path.name,ignore=shutil.ignore_patterns('__pycache__','.DS_Store'))
            elif path.is_file():shutil.copy2(path,source/path.name)
        source_manifest=[]
        for path in sorted(source.rglob('*')):
            if path.is_file():
                checksum=file_hash(path);assert checksum==file_hash(ROOT/path.relative_to(source))
                source_manifest.append(dict(path=str(path.relative_to(source)),sha256=checksum,size=path.stat().st_size))
        (folder/'source-manifest.json').write_text(json.dumps(source_manifest,ensure_ascii=False,indent=2))
    print('Full current-data backup verified:',folder,flush=True)
    service.record('frontend',frontend[0])
    os.kill(backend[0],signal.SIGTERM)
    deadline=time.monotonic()+12
    while service.listeners(8000):
        if time.monotonic()>deadline:raise SystemExit('Backend did not stop normally; no force kill')
        time.sleep(.2)
    migrated=[]
    if args.review_receipts:
        import sys
        sys.path.insert(0,str(ROOT))
        from backend import main as project_app,review_units as review,workspace
        with project_app.db() as c:ids=[v[0] for v in c.execute('SELECT id FROM projects')]
        for pid in ids:
            project=project_app.get(pid);workspace.ensure(project)
            if project['workspace'].get('reviewUnits',{}).get('legacyAuditRecovered'):
                prior=json.dumps(project['workspace']['reviewUnits'],sort_keys=True)
                with project_app.db() as c:edits=c.execute("SELECT `before` FROM events WHERE project=? AND action='studio:unit_autosave' ORDER BY rowid DESC LIMIT 10",(pid,)).fetchall()
                for old_body, in edits:review.preserve_origins(json.loads(old_body),project)
                if json.dumps(project['workspace']['reviewUnits'],sort_keys=True)!=prior:
                    project_app.save(project,project['version'],'studio:recover_review_origin');migrated.append(pid)
                continue
            with project_app.db() as c:events=c.execute("SELECT action,`after`,meta FROM events WHERE project=? AND (action LIKE 'studio:confirm:%' OR action='studio:batch_confirm' OR action='confirm_person') ORDER BY rowid",(pid,)).fetchall()
            review.recover_reviews(project,events)
            project_app.save(project,project['version'],'studio:recover_review_units');migrated.append(pid)
        adapted=logical(ROOT/'data/projects.sqlite')
        assert all(adapted[k]==v for k,v in before.items() if k.startswith('experience_') or k in ('video_jobs','tasks','studio_jobs')), 'Reader/task records changed during audit adaptation'
        before=adapted
    service.start(False)
    assert service.listeners(5173)==frontend
    after=logical(ROOT/'data/projects.sqlite')
    report=dict(reviewReceiptProjects=migrated,backup=str(folder),frontendPid=frontend[0],backendPid=service.listeners(8000)[0],dataTablesUnchanged=before==after,before=before,after=after)
    (ROOT/('.runtime/review-rollout.json' if args.review_receipts else '.runtime/oneclick-rollout.json')).write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ('before','after')},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
