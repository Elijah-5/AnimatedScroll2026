"""Losslessly compact an isolated SQLite copy; never overwrite the input database."""
import argparse,hashlib,json,sqlite3,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import snapshot_store,read_models

def checksum(raw):return hashlib.sha256(raw.encode() if isinstance(raw,str) else raw).hexdigest()
def rows_hash(c,table):
    h=hashlib.sha256()
    for row in c.execute('SELECT * FROM "'+table+'" ORDER BY 1,2' if table not in ('document_cache',) else 'SELECT * FROM document_cache ORDER BY 1'):
        h.update(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode());h.update(b'\n')
    return h.hexdigest()

def compact(source,output,report_path=None,progress=print):
    source=Path(source).resolve();output=Path(output).resolve()
    if not source.is_file() or output.exists() or source==output:raise ValueError('源库必须存在，输出库必须为空，禁止覆盖源库')
    output.parent.mkdir(parents=True,exist_ok=True);start=time.monotonic()
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(output) as out:src.backup(out)
    before_bytes=output.stat().st_size
    with sqlite3.connect(output) as c:
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        preserved={table:rows_hash(c,table) for table in tables if table not in ('events','projects','content_snapshots','studio_read_models')}
        snapshot_store.schema(c);read_models.schema(c);c.commit();c.execute('BEGIN IMMEDIATE')
        total=c.execute('SELECT COUNT(*) FROM events').fetchone()[0];event_hash=hashlib.sha256();heads={}
        for index,row in enumerate(c.execute('SELECT rowid,id,project,time,action,before,after,meta FROM events ORDER BY rowid')):
            rid,eid,pid,stamp,action,before,after,meta=row
            decoded=[snapshot_store.decode(value,c) for value in (before,after)]
            packed=[snapshot_store.pack(value,c,level=6) for value in decoded]
            for original,stored in zip(decoded,packed):
                if checksum(snapshot_store.decode(stored,c))!=checksum(original):raise ValueError('历史快照不一致，未切换数据库')
            event_hash.update(json.dumps([eid,pid,stamp,action,checksum(decoded[0]),checksum(decoded[1]),meta],ensure_ascii=False).encode())
            if [before,after]!=packed:c.execute('UPDATE events SET before=?,after=? WHERE rowid=?',(*packed,rid))
            if (index+1)%20==0:progress(f'历史快照 {index+1}/{total} 已逐条校验')
        for pid,body in c.execute('SELECT id,body FROM projects').fetchall():
            p=json.loads(body);cleaned=read_models.clean_project(p)
            reference=snapshot_store.pack(body,c,level=6)
            heads[pid]=dict(version=p['version'],original=reference,originalSha256=checksum(body))
            # Only derived display warnings are removed from the current head.
            # The exact old head remains a verified immutable snapshot above.
            encoded=json.dumps(cleaned,ensure_ascii=False)
            if read_models.clean_project(json.loads(snapshot_store.decode(reference,c)))!=json.loads(encoded):raise ValueError('制作内容校验失败')
            c.execute('UPDATE projects SET body=? WHERE id=?',(encoded,pid));read_models.write(c,cleaned)
            heads[pid]['optimizedSha256']=checksum(encoded)
        c.commit()
        if any(rows_hash(c,table)!=digest for table,digest in preserved.items()):raise ValueError('聊天、体验或其他持久表校验失败')
        if c.execute('SELECT COUNT(*) FROM events').fetchone()[0]!=total:raise ValueError('历史记录数量变化')
        check=hashlib.sha256()
        for eid,pid,stamp,action,before,after,meta in c.execute('SELECT id,project,time,action,before,after,meta FROM events ORDER BY rowid'):
            check.update(json.dumps([eid,pid,stamp,action,checksum(snapshot_store.decode(before,c)),checksum(snapshot_store.decode(after,c)),meta],ensure_ascii=False).encode())
        if check.digest()!=event_hash.digest():raise ValueError('全量历史复核失败')
        snapshots=c.execute('SELECT COUNT(*) FROM content_snapshots').fetchone()[0]
        progress('全部内容校验通过，正在回收 SQLite 空闲页')
        c.execute('VACUUM')
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite完整性检查失败')
        c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    c.close()
    result=dict(source=str(source),output=str(output),beforeBytes=before_bytes,afterBytes=output.stat().st_size,eventCount=total,snapshots=snapshots,eventsLogicalSha256=event_hash.hexdigest(),preservedTables=preserved,projectHeads=heads,seconds=round(time.monotonic()-start,2),integrity='ok',losslessAudit=True)
    destination=Path(report_path) if report_path else output.with_suffix('.report.json');destination.write_text(json.dumps(result,ensure_ascii=False,indent=2));progress(json.dumps({k:v for k,v in result.items() if k not in ('preservedTables','projectHeads')},ensure_ascii=False));return result

def inflate(source,output):
    source=Path(source).resolve();output=Path(output).resolve()
    if not source.is_file() or output.exists() or source==output:raise ValueError('必须输出到新的数据库副本')
    output.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(output) as c:src.backup(c)
    src.close()
    with c:
        for rid,before,after in c.execute('SELECT rowid,before,after FROM events ORDER BY rowid'):
            c.execute('UPDATE events SET before=?,after=? WHERE rowid=?',(snapshot_store.decode(before,c),snapshot_store.decode(after,c),rid))
    if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('还原副本完整性检查失败')
    c.execute('PRAGMA wal_checkpoint(TRUNCATE)');c.close()
    return dict(output=str(output),format='plain-json-audit',sourcePreserved=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--report',type=Path);parser.add_argument('--inflate',action='store_true');args=parser.parse_args()
    if args.inflate:print(json.dumps(inflate(args.source,args.output),ensure_ascii=False))
    else:compact(args.source,args.output,args.report)
