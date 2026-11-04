"""Back up local DB, preserve latest Zhekan project, migrate without model calls."""
import sys,json,sqlite3
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import main,workspace

def migrate():
    folder=main.DATA/'backups';folder.mkdir(exist_ok=True)
    name=datetime.now().strftime('%Y%m%d-%H%M%S')+'-before-studio.sqlite'
    conn=main.db();backup=sqlite3.connect(folder/name);conn.backup(backup);backup.close()
    rows=[json.loads(r[0]) for r in conn.execute('SELECT body FROM projects ORDER BY rowid')]
    matching=[p for p in rows if p['title']=='折槛图 · 图片与资料创作示例']
    if not matching:raise RuntimeError('未找到指定折槛图项目；已备份，未清理其他项目')
    original=max(matching,key=lambda p:p['version']);p=main.get(original['id']);workspace.ensure(p)
    p=main.save(p,p['version'],'studio:migrate')
    for table,column in [('projects','id'),('events','project'),('tasks','project')]:conn.execute(f'DELETE FROM {table} WHERE {column}<>?',(p['id'],))
    conn.commit();conn.close()
    print('backup:',folder/name);print('retained:',p['id'],p['title']);print('entities:',len(p['workspace']['entities']))
if __name__=='__main__':migrate()
