"""SQLite compatibility and pooled MySQL transactions for the existing storage API."""
import os
import sqlite3
from functools import lru_cache
from . import config


def backend():
    kind = os.getenv('CREATION_DB_BACKEND', 'sqlite').lower()
    if kind not in ('sqlite', 'mysql'):
        raise ValueError('CREATION_DB_BACKEND must be sqlite or mysql')
    return kind


@lru_cache(maxsize=4)
def mysql_engine(host, port, database, user, password):
    from sqlalchemy import create_engine, URL, MetaData, Table, Column, String, Integer, Index
    from sqlalchemy.dialects.mysql import LONGTEXT
    url = URL.create('mysql+pymysql', username=user, password=password,
                     host=host, port=int(port), database=database, query={'charset':'utf8mb4'})
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800,
                           connect_args={'connect_timeout':10}, hide_parameters=True)
    meta = MetaData()
    def table(name, *columns):
        return Table(name, meta, *columns, mysql_engine='InnoDB', mysql_charset='utf8mb4')
    def text(name): return Column(name, LONGTEXT, nullable=False)
    def key(name='id'): return Column(name, String(128), primary_key=True)
    table('projects', key(), text('body'))
    table('content_snapshots',key(),Column('raw_bytes',Integer,nullable=False),text('body'))
    table('studio_read_models',key('project'),Column('version',Integer,nullable=False),text('title'),Column('archived',Integer,nullable=False),text('policy'),text('editor'),text('checks'),text('assets'))
    table('events', key(), Column('project',String(128),index=True), Column('time',String(64)),
          Column('action',String(128)), text('before'),text('after'),text('meta'))
    table('tasks', key(), Column('project',String(128),index=True), text('body'))
    table('document_cache',key('key'),text('body'))
    table('studio_jobs', key(), Column('project',String(128),index=True), text('body'))
    table('experience_sessions', key(), Column('project',String(128),index=True), text('body'))
    table('experience_turns', key(), Column('project',String(128),index=True), text('body'))
    table('video_jobs', key(), Column('project',String(128),index=True), text('body'))
    table('media_preview_jobs', key(), Column('project',String(128),index=True), text('body'))
    table('media_preview_quotes', key(), Column('project',String(128),index=True), text('body'))
    table('artwork_catalog',key('project_id'),text('name'),text('body'))
    table('artwork_people',key('project_id'),key(),text('name'),text('body'))
    table('artwork_sources',key('project_id'),key(),text('title'),Column('version',Integer),text('body'))
    table('artwork_relations',key('project_id'),key(),Column('from_id',String(128)),Column('to_id',String(128)),Column('label',String(100)),text('body'))
    table('artwork_events',key('project_id'),key(),Column('title',String(200)),Column('time_label',String(512)),Column('position',Integer),text('body'))
    Index('artwork_relations_from',meta.tables['artwork_relations'].c.project_id,meta.tables['artwork_relations'].c.from_id)
    Index('artwork_relations_to',meta.tables['artwork_relations'].c.project_id,meta.tables['artwork_relations'].c.to_id)
    from .history_schema import mysql_tables
    mysql_tables(meta,table,key,text)
    meta.create_all(engine)
    return engine


def engine():
    required = ('MYSQL_DATABASE','MYSQL_USER','MYSQL_PASSWORD')
    if not all(os.getenv(k) for k in required):
        raise RuntimeError('MySQL 配置不完整，请填写 .env.mysql。不会回退到 SQLite。')
    return mysql_engine(os.getenv('MYSQL_HOST','127.0.0.1'),os.getenv('MYSQL_PORT','3307'),
                        os.environ['MYSQL_DATABASE'],os.environ['MYSQL_USER'],os.environ['MYSQL_PASSWORD'])


class Rows:
    def __init__(self, rows,connection=None,columns=()):self.rows=rows;self.connection=connection;self.columns=columns
    def decode(self,row):
        from .snapshot_store import decode
        return tuple(decode(v,self.connection) if self.columns[i] in ('before','after') else v for i,v in enumerate(row)) if self.connection else row
    def fetchone(self):return self.decode(self.rows[0]) if self.rows else None
    def fetchall(self):return [self.decode(row) for row in self.rows]
    def __iter__(self):return (self.decode(row) for row in self.rows)


class MySQLConnection:
    dialect = 'mysql'
    def __init__(self): self.conn=engine().raw_connection();self.write=False
    def __enter__(self): return self
    def __exit__(self,kind,value,traceback):
        try:
            if kind: self.conn.rollback()
            else: self.conn.commit()
        finally: self.conn.close()
    def execute(self,sql,params=()):
        if sql.startswith(('INSERT OR REPLACE INTO projects','UPDATE projects','DELETE FROM projects')):
            with self.conn.cursor() as cur:cur.execute('DELETE FROM studio_read_models')
        if sql.startswith(('CREATE TABLE IF NOT EXISTS', 'CREATE INDEX IF NOT EXISTS')):return Rows([])
        if sql=='BEGIN IMMEDIATE':
            self.conn.begin();self.write=True;return Rows([])
        if sql.startswith('INSERT OR REPLACE INTO projects'):
            sql='INSERT INTO projects (id,body) VALUES (?,?) ON DUPLICATE KEY UPDATE body=VALUES(body)'
        elif sql.startswith('INSERT OR REPLACE INTO studio_read_models'):
            sql='INSERT INTO studio_read_models VALUES (?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE version=VALUES(version),title=VALUES(title),archived=VALUES(archived),policy=VALUES(policy),editor=VALUES(editor),checks=VALUES(checks),assets=VALUES(assets)'
        elif sql.startswith('INSERT OR REPLACE INTO document_cache'):
            sql='INSERT INTO document_cache (`key`,body) VALUES (?,?) ON DUPLICATE KEY UPDATE body=VALUES(body)'
        else:
            for name in ('tasks','studio_jobs','video_jobs','experience_sessions','experience_turns'):
                if sql.startswith('INSERT OR REPLACE INTO '+name+' '):
                    sql=f'INSERT INTO {name} (id,project,body) VALUES (?,?,?) ON DUPLICATE KEY UPDATE project=VALUES(project),body=VALUES(body)'
                    break
        if 'ORDER BY rowid DESC' in sql:
            sql=sql.replace('ORDER BY rowid DESC',"ORDER BY JSON_UNQUOTE(JSON_EXTRACT(body,'$.time')) DESC,id DESC")
        elif 'ORDER BY rowid' in sql:
            sql=sql.replace('ORDER BY rowid','ORDER BY time,id' if 'FROM events ' in sql else "ORDER BY JSON_UNQUOTE(JSON_EXTRACT(body,'$.time')),id")
        if self.write and sql in ('SELECT body FROM projects WHERE id=?','SELECT body FROM experience_sessions WHERE id=?'): sql+=' FOR UPDATE'
        sql=sql.replace('action,before,after,meta','action,`before`,`after`,meta')
        if 'document_cache' in sql:sql=sql.replace('WHERE key=','WHERE `key`=').replace('ORDER BY key','ORDER BY `key`')
        # SQL is internal, with ? placeholders; values remain bound separately.
        sql=sql.replace('?', '%s')
        with self.conn.cursor() as cur:
            cur.execute(sql,params)
            return Rows(list(cur.fetchall()) if cur.description else [],self,[d[0] for d in cur.description] if cur.description else [])


def connect(data):
    if backend()=='mysql':return MySQLConnection()
    conn=sqlite3.connect(data/'projects.sqlite')
    from .snapshot_store import sqlite_rows
    conn.row_factory=sqlite_rows
    conn.execute('PRAGMA foreign_keys=ON')
    return conn
