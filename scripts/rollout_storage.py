"""Verified offline compaction of the latest production DB, never an older test copy."""
import hashlib,json,os,shutil,signal,sqlite3,time
from datetime import datetime,timezone
from pathlib import Path
import server_control as service
from compact_storage import compact
from rollout_oneclick import pending_turns
ROOT=service.ROOT

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def copy_file(source,target):
 source=Path(source);target=Path(target)
 if not target.exists() or source.stat().st_size!=target.stat().st_size or source.stat().st_mtime_ns!=target.stat().st_mtime_ns:shutil.copy2(source,target)
 return str(target)
def assets(destination):
 shutil.copytree(ROOT/'data',destination,dirs_exist_ok=True,copy_function=copy_file,ignore=lambda path,names:[n for n in names if Path(path)==ROOT/'data' and n in ('projects.sqlite','projects.sqlite-shm','projects.sqlite-wal')])
def quiet():
 deadline=time.monotonic()+120
 while service.active_tasks() or pending_turns():
  if time.monotonic()>deadline:raise RuntimeError('仍有运行任务，未停止服务')
  print('等待现有生成、对话和资源准备完成',flush=True);time.sleep(2)
def rollout():
 quiet();back=service.listeners(8000);front=service.listeners(5173)
 if len(back)!=1 or len(front)!=1 or not service.ours(back[0],'backend') or not service.ours(front[0],'frontend'):raise RuntimeError('服务进程不匹配，未操作')
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');folder=ROOT.parent/'merge-backups'/('storage-rollout-'+stamp);folder.mkdir()
 assets(folder/'data');quiet();service.record('frontend',front[0]);os.kill(back[0],signal.SIGTERM)
 deadline=time.monotonic()+20
 while service.listeners(8000):
  if time.monotonic()>deadline:raise RuntimeError('后端未正常退出，没有强制停止')
  time.sleep(.2)
 replaced=False
 try:
  assets(folder/'data')
  with sqlite3.connect(ROOT/'data/projects.sqlite') as c:c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
  c.close()
  with sqlite3.connect((ROOT/'data/projects.sqlite').as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(folder/'data/projects.sqlite') as target:source.backup(target)
  source.close();target.close()
  manifest=[dict(path=str(p.relative_to(folder)),size=p.stat().st_size,sha256=sha(p)) for p in sorted((folder/'data').rglob('*')) if p.is_file()]
  (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));print('最新完整数据备份完成：'+str(folder),flush=True)
  staging=ROOT/'.runtime'/('storage-'+stamp);staging.mkdir();report=compact(folder/'data/projects.sqlite',staging/'projects.sqlite',staging/'verification.json',progress=lambda text:print(text,flush=True))
  # All model/reader/audit rows are verified before exposing this DB to clients.
  for suffix in ('-wal','-shm'):
   path=ROOT/'data'/('projects.sqlite'+suffix)
   if path.exists():
    if suffix=='-wal' and path.stat().st_size:raise RuntimeError('WAL仍有内容，未替换数据库')
    path.unlink()
  os.replace(staging/'projects.sqlite',ROOT/'data/projects.sqlite');replaced=True
  import sys
  sys.path.insert(0,str(ROOT))
  from backend import main
  with main.db() as c:ids=[r[0] for r in c.execute('SELECT id FROM projects')]
  for pid in ids:main.app.state.studio_checks(pid)
  print('启动读取缓存已预热',flush=True);service.start(False)
  if service.listeners(5173)!=front:raise RuntimeError('前端进程意外变化')
  result=dict(backup=str(folder),frontendPid=front[0],backendPid=service.listeners(8000)[0],auditLossless=report['losslessAudit'],preservedTables=report['preservedTables'],beforeBytes=report['beforeBytes'],afterBytes=(ROOT/'data/projects.sqlite').stat().st_size,eventCount=report['eventCount'],snapshots=report['snapshots'],verification=str(staging/'verification.json'))
  (ROOT/'.runtime/storage-rollout.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='preservedTables'},ensure_ascii=False),flush=True)
 except Exception:
  if not service.listeners(8000):service.start(False)
  if replaced:print('优化库已通过完整校验并替换；请检查启动错误。最新原库备份位于 '+str(folder),flush=True)
  raise
if __name__=='__main__':rollout()
