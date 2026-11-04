"""Explicit, verified migration into an empty MySQL database; never run on startup."""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from backend import config, storage, catalog
from backend.history_schema import INSERT_ORDER as HISTORY_TABLES

TABLES=('projects','events','tasks','studio_jobs','document_cache','video_jobs','experience_sessions','experience_turns','media_preview_jobs','media_preview_quotes','content_snapshots','studio_read_models')+HISTORY_TABLES


def migrate(source,verify_only=False):
    if storage.backend()!='mysql':raise ValueError('请显式选择 mysql 作为目标数据库')
    source=Path(source).resolve()
    if not source.is_file():raise ValueError('源数据库不存在')
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    folder=source.parent/'backups';folder.mkdir(parents=True,exist_ok=True)
    backup=folder/f'before-mysql-{stamp}.sqlite'
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(backup) as out:src.backup(out)
    with sqlite3.connect(backup) as src:
        present={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        unexpected=present-set(TABLES)-set(catalog.TABLES)-{'sqlite_sequence'}
        if unexpected:raise ValueError('发现未支持的持久化表，停止迁移以免遗漏：'+','.join(sorted(unexpected)))
        rows={name:src.execute('SELECT * FROM '+name+' ORDER BY '+('key' if name=='document_cache' else 'project_id,work_id,person_id' if name=='work_persons' else 'project_id,id' if name in HISTORY_TABLES else 'project' if name=='studio_read_models' else 'id')).fetchall() if name in present else [] for name in TABLES}
    with storage.connect(source.parent) as target:
        target.execute('BEGIN IMMEDIATE')
        if not verify_only:
            if any(target.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in TABLES+tuple(catalog.TABLES)):raise ValueError('目标数据库非空，未覆盖任何资料')
            for name,items in rows.items():
                for item in items:target.execute('INSERT INTO '+name+' VALUES ('+','.join('?' for _ in item)+')',item)
            for pid,body in rows['projects']:catalog.synchronize(target,json.loads(body))
        for name,items in rows.items():
            actual_result=target.execute('SELECT * FROM '+name+' ORDER BY '+('key' if name=='document_cache' else 'project_id,work_id,person_id' if name=='work_persons' else 'project_id,id' if name in HISTORY_TABLES else 'project' if name=='studio_read_models' else 'id'))
            actual=actual_result.rows if hasattr(actual_result,'rows') else actual_result.fetchall()
            if [tuple(r) for r in actual]!=[tuple(r) for r in items]:raise ValueError(name+' 内容不一致，迁移事务已回滚')
        # Compare full searchable projection contents, not only record counts.
        with sqlite3.connect(':memory:') as expected:
            catalog.schema(expected)
            for pid,body in rows['projects']:catalog.synchronize(expected,json.loads(body))
            for name in catalog.TABLES:
                order='project_id'+(',id' if name!='artwork_catalog' else '')
                wanted=expected.execute('SELECT * FROM '+name+' ORDER BY '+order).fetchall()
                actual=target.execute('SELECT * FROM '+name+' ORDER BY '+order).fetchall()
                if [tuple(r) for r in actual]!=wanted:raise ValueError(name+' 查询投影不一致，事务已回滚')
    report=dict(sourceBackup=str(backup),target='mysql',verified=True,counts={k:len(v) for k,v in rows.items()},assets='图片与文献继续使用源data目录；本工具不删除源文件')
    path=source.parent/f'mysql-migration-{stamp}.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=config.ROOT/'data/projects.sqlite');parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    try:print(json.dumps(migrate(args.source,args.verify_only),ensure_ascii=False,indent=2))
    except Exception as exc:
        print(str(exc) if isinstance(exc,ValueError) else 'MySQL连接或迁移失败，未完成提交。请检查本机配置。')
        raise SystemExit(1)
