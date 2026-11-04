"""Explicit maintenance only: verify one latest recovery copy, then prune old backups."""
import argparse,hashlib,json,os,shutil,signal,sqlite3,time,urllib.request
from datetime import datetime,timezone
from pathlib import Path
import server_control as service
from rollout_storage import quiet
from rollout_oneclick import logical

ROOT=service.ROOT
EXCLUDED={'.git','.venv','node_modules','dist','models','data','.runtime','__pycache__','.pytest_cache','.DS_Store'}

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def size(path):return sum(p.stat().st_size for p in path.rglob('*') if p.is_file() and not p.is_symlink())
def candidates(root,keep=None):
    # Only known, manifested implementation backups. Never touch sibling projects or unrecognised folders.
    names=[]
    if not Path(root).is_dir():return names
    for path in sorted(Path(root).iterdir()):
        if path==keep or path.is_symlink() or not path.is_dir() or not (path/'manifest.json').is_file():continue
        if not any((path/part).is_dir() for part in ('data','creation-agent-demo/data','project/data')):continue
        names.append(dict(name=path.name,bytes=size(path),manifest=sha(path/'manifest.json')))
    return names
def copy_assets(destination):
    def ignore(path,names):
        if Path(path)==ROOT/'data':return [n for n in names if n in ('projects.sqlite','projects.sqlite-wal','projects.sqlite-shm','backups')]
        return []
    shutil.copytree(ROOT/'data',destination,ignore=ignore)
def create_recovery(folder):
    folder.mkdir(mode=0o700)
    shutil.copytree(ROOT,folder/'source',ignore=lambda path,names:[n for n in names if n in EXCLUDED])
    copy_assets(folder/'data')
    with sqlite3.connect((ROOT/'data/projects.sqlite').as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(folder/'data/projects.sqlite') as target:source.backup(target)
    source.close();target.close()
    expected=logical(ROOT/'data/projects.sqlite');actual=logical(folder/'data/projects.sqlite')
    if expected!=actual:raise RuntimeError('恢复副本逐表校验失败，未删除任何旧备份')
    with sqlite3.connect(folder/'data/projects.sqlite') as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('恢复副本完整性检查失败')
    c.close();files=[]
    for path in sorted(folder.rglob('*')):
        if not path.is_file():continue
        rel=path.relative_to(folder);value=sha(path)
        original=ROOT/Path(*rel.parts[1:]) if rel.parts[0]=='source' else ROOT/rel
        if rel.as_posix()!='data/projects.sqlite' and sha(original)!=value:raise RuntimeError('源码或素材副本校验失败：'+str(rel))
        files.append(dict(path=str(rel),bytes=path.stat().st_size,sha256=value))
    report=dict(createdAt=datetime.now(timezone.utc).isoformat(),files=files,tables=actual,verified=True,policy='one-latest-recovery-copy; manual-download-for-creation')
    (folder/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));return report
def prune(root,keep,planned):
    verification=json.loads((keep/'manifest.json').read_text())
    if not verification.get('verified'):raise RuntimeError('必要备份未通过校验，拒绝清理')
    removed=[]
    for item in planned:
        path=root/item['name']
        if path==keep or path.is_symlink() or path.resolve().parent!=root.resolve() or sha(path/'manifest.json')!=item['manifest']:raise RuntimeError('备份路径或清单已变化，停止清理')
        shutil.rmtree(path);removed.append(item);print('已清理旧备份：'+item['name'],flush=True)
    return removed
def apply():
    root=ROOT.parent/'merge-backups';planned=candidates(root);quiet()
    back=service.listeners(8000);front=service.listeners(5173)
    if len(back)!=1 or len(front)!=1 or not service.ours(back[0],'backend') or not service.ours(front[0],'frontend'):raise RuntimeError('服务不匹配，未停止或删除任何内容')
    folder=root/('recovery-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    service.record('frontend',front[0]);os.kill(back[0],signal.SIGTERM)
    deadline=time.monotonic()+25
    while service.listeners(8000):
        if time.monotonic()>deadline:raise RuntimeError('后端未正常退出，没有强制停止')
        time.sleep(.2)
    try:
        create_recovery(folder);print('最新源码、制作、聊天和进度备份逐表校验通过：'+str(folder),flush=True)
    finally:
        if not service.listeners(8000):service.start(False)
    with urllib.request.urlopen('http://127.0.0.1:8000/openapi.json',timeout=20) as response:routes=json.load(response)['paths']
    if '/api/projects/{pid}/creation-copy' not in routes or '/api/projects/{pid}/experience/sessions/{sid}/records' not in routes:raise RuntimeError('新服务未通过接口检查，旧备份未清理')
    removed=prune(root,folder,planned)
    # Old standalone pre-migration SQLite copies are superseded by the verified complete recovery copy.
    small=ROOT/'data/backups';small_bytes=size(small) if small.is_dir() else 0
    if small.is_dir():shutil.rmtree(small)
    # This exact temporary performance fixture was created by the previous acceptance run, never production.
    fixture=Path('/tmp/startup-storage-copy');fixture_bytes=0;proof=fixture/'projects.report.json'
    if proof.is_file() and json.loads(proof.read_text()).get('losslessAudit') is True:
        fixture_bytes=size(fixture);shutil.rmtree(fixture)
    result=dict(kept=str(folder),keptBytes=size(folder),removed=removed,reclaimedBytes=sum(r['bytes'] for r in removed)+small_bytes+fixture_bytes,temporaryFixtureBytes=fixture_bytes,legacyBackupBytes=small_bytes,allPersistentTablesVerified=True)
    (ROOT/'.runtime/backup-retention.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='removed'},ensure_ascii=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if args.apply:apply()
    else:print(json.dumps(dict(mode='preview',candidates=candidates(ROOT.parent/'merge-backups'),deletesNothing=True),ensure_ascii=False,indent=2))
