"""Validated artwork catalog and SQL read models, committed with each project revision."""
import json
from . import storage

TABLES = {
    'artwork_catalog': 'project_id TEXT PRIMARY KEY, name TEXT NOT NULL, body TEXT NOT NULL',
    'artwork_people': 'project_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(project_id,id)',
    'artwork_sources': 'project_id TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL, version INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(project_id,id)',
    'artwork_relations': 'project_id TEXT NOT NULL, id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, label TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(project_id,id)',
    'artwork_events': 'project_id TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL, time_label TEXT NOT NULL, position INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(project_id,id)',
}

def schema(conn):
    for table, columns in TABLES.items():
        conn.execute(f'CREATE TABLE IF NOT EXISTS {table} ({columns})')
    conn.execute('CREATE INDEX IF NOT EXISTS artwork_people_name ON artwork_people(name)')
    conn.execute('CREATE INDEX IF NOT EXISTS artwork_relations_from ON artwork_relations(project_id,from_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS artwork_relations_to ON artwork_relations(project_id,to_id)')


def rows(p):
    from . import workspace as ws
    w=ws.ensure(p);mat=w['entities']['material:main']['draft']
    people=[dict(r['draft'],id=r['id'],state=r['state']) for r in w['entities'].values() if r['kind']=='character' and r['state']!='deleted']
    relations=[]
    for r in w['entities'].values():
        if r['kind']!='clue' or r['state']=='deleted' or r['draft'].get('type')!='relationship':continue
        for i,edge in enumerate(r['draft'].get('relations',[])):
            relations.append(dict(edge,id=r['id']+':'+str(i),clueId=r['id'],state=r['state']))
    structured=mat.get('structured')
    return dict(painting={k:v['value'] for k,v in structured['artwork'].items()} if structured else mat.get('paintingInfo',{}),characters=people,sources=structured['sources'] if structured else mat.get('sources',[]),relations=structured['relations'] if structured else relations,
                events=structured['events'] if structured else mat.get('historicalEvents',[]),materialState=w['entities']['material:main']['state'])


def validate_material(d):
    if d.get('structured'):
        from .structured import validate
        validate(d['structured']);return
    from .models import PaintingInfo, HistoricalEvent
    PaintingInfo.model_validate(d.get('paintingInfo',{}))
    seen=set();sources={s['id']:s for s in d.get('sources',[])}
    for item in d.get('historicalEvents',[]):
        event=HistoricalEvent.model_validate(item)
        if event.id in seen:raise ValueError('历史事件编号重复')
        seen.add(event.id)
        e=event.evidence
        if e.sourceId or e.quote:
            source=sources.get(e.sourceId)
            if not source or source['version']!=e.sourceVersion or not e.quote or e.quote not in source['text'] or source.get('sourceType')=='creative_intent':raise ValueError('历史事件须引用当前来源的逐字原文')


def validate_relations(d,w):
    from .models import DirectionalRelation
    from .structured import material_sources
    sources={s['id']:s for s in material_sources(w['entities']['material:main']['published'] or {})}
    seen=set()
    for raw in d.get('relations',[]):
        r=DirectionalRelation.model_validate(raw)
        if r.fromId==r.toId:raise ValueError('关系两端必须是不同人物')
        if (r.fromId,r.toId,r.label) in seen:raise ValueError('关系重复')
        seen.add((r.fromId,r.toId,r.label))
        for cid in (r.fromId,r.toId):
            if cid not in d.get('characterIds',[]):raise ValueError('请将关系两端加入关联人物')
        source=sources.get(r.sourceId)
        if not source or source['version']!=r.sourceVersion or r.quote not in source['text'] or source.get('sourceType')=='creative_intent':raise ValueError('人物关系须引用当前来源的逐字原文')


def synchronize(conn,p):
    value=rows(p);pid=p['id'];dump=lambda v:json.dumps(v,ensure_ascii=False)
    for table in TABLES:conn.execute(f'DELETE FROM {table} WHERE project_id=?',(pid,))
    conn.execute('INSERT INTO artwork_catalog VALUES (?,?,?)',(pid,value['painting'].get('name') or p['title'],dump(value['painting'])))
    for r in value['characters']:conn.execute('INSERT INTO artwork_people VALUES (?,?,?,?)',(pid,r['id'],r['name'],dump(r)))
    # This legacy lookup has one row per source ID. Full immutable versions live
    # in material.structured and its published revision archive.
    latest={}
    for r in value['sources']:
        if r['id'] not in latest or r['version']>latest[r['id']]['version']:latest[r['id']]=r
    for r in latest.values():conn.execute('INSERT INTO artwork_sources VALUES (?,?,?,?,?)',(pid,r['id'],r['title'],r['version'],dump(r)))
    for r in value['relations']:conn.execute('INSERT INTO artwork_relations VALUES (?,?,?,?,?,?)',(pid,r['id'],r['fromId'],r['toId'],r['label'],dump(r)))
    for i,r in enumerate(value['events']):conn.execute('INSERT INTO artwork_events VALUES (?,?,?,?,?,?)',(pid,r['id'],r['title'],r.get('time',''),i,dump(r)))


def install(app,get,db):
    @app.get('/api/projects/{pid}/catalog')
    def read_catalog(pid:str):return dict(rows(get(pid)),storage=storage.backend())

    @app.get('/api/database/status')
    def status():
        with db() as c:c.execute('SELECT COUNT(*) FROM projects').fetchone()
        return dict(backend=storage.backend(),connected=True)

    def backfill():
        with db() as c:
            for body, in c.execute('SELECT body FROM projects').fetchall():synchronize(c,json.loads(body))
    app.router.add_event_handler('startup',backfill)
