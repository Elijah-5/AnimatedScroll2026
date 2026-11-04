"""Lossless, content-addressed audit snapshots. Business JSON remains unchanged."""
import base64,hashlib,zlib
PREFIX='@animatedscroll.snapshot/1:'

def schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS content_snapshots(id TEXT PRIMARY KEY,raw_bytes INTEGER NOT NULL,body TEXT NOT NULL)')

def is_reference(value):return isinstance(value,str) and value.startswith(PREFIX)
def decode(value,connection):
    if not is_reference(value):return value
    key=value[len(PREFIX):]
    if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('历史快照引用损坏')
    row=connection.execute('SELECT raw_bytes,body FROM content_snapshots WHERE id=?',(key,)).fetchone()
    if not row:raise ValueError('历史快照缺失：'+key)
    raw=zlib.decompress(base64.b64decode(row[1],validate=True))
    if len(raw)!=row[0] or hashlib.sha256(raw).hexdigest()!=key:raise ValueError('历史快照校验失败：'+key)
    return raw.decode('utf-8')

def pack(value,connection,level=3):
    if is_reference(value):decode(value,connection);return value
    raw=value.encode('utf-8')
    if len(raw)<4096:return value
    key=hashlib.sha256(raw).hexdigest()
    if not connection.execute('SELECT id FROM content_snapshots WHERE id=?',(key,)).fetchone():
        compressed=base64.b64encode(zlib.compress(raw,level)).decode('ascii')
        connection.execute('INSERT INTO content_snapshots VALUES (?,?,?)',(key,len(raw),compressed))
    return PREFIX+key

def sqlite_rows(cursor,row):
    return tuple(decode(value,cursor.connection) if cursor.description[i][0] in ('before','after') else value for i,value in enumerate(row))
