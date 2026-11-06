"""Read confirmed workspace snapshots without consuming drafts or legacy mirrors."""
import copy
from . import workspace as ws
from .task_runtime import digest
from . import revisions

def character_id(p,rid):
    record=ws.ensure(p)['entities']['material:main']
    material=record.get('published') or record['draft']
    redirects=(material.get('structured') or {}).get('personRedirects',{})
    seen=set()
    while rid in redirects and rid not in seen:
        seen.add(rid);rid=redirects[rid]
    return rid


def confirmed(p, kind, rid, seen=None):
    if kind in ('character','knowledge','persona'):rid=character_id(p,rid)
    w = ws.ensure(p)
    r = w['entities'].get(ws.key(kind, rid))
    if not ws.valid(r):
        if r and r.get('basisError'):raise ValueError(r['basisError'])
        raise ValueError('请先确认有效的' + kind + ':' + rid)
    revisions.resolve(w,ws.key(kind,rid))
    if kind=='plot':
        for cid in r['published'].get('clueIds',[]):
            child=w['entities'].get('clue:'+cid)
            if not child or child['state']=='deleted':raise ValueError('剧情关联的线索已删除或不存在')
    if kind=='clue':
        errors=revisions.citation_issues(w,ws.key(kind,rid),r['published'])
        if errors:raise ValueError('；'.join(errors))
    return copy.deepcopy(r['published'])


def snapshot(p):
    """Draft-only edits, task status and project renaming do not change playback."""
    result = {}
    for key, r in ws.ensure(p)['entities'].items():
        if r['published'] is not None:
            result[key] = dict(data=r['published'], revision=r['revision'], deleted=r['state']=='deleted')
    return digest(result)


def dependencies(p,kind,rid):
    confirmed(p,kind,rid)
    return revisions.bases(ws.ensure(p),ws.key(kind,rid))

def material_context(p):
    from .structured import view,compact
    material=confirmed(p,'material','main')
    # Creative direction needs the story and field provenance, not duplicated raw
    # PDF pages or the whole historical archive. Extraction still reads originals.
    fields={k:material.get(k) for k in ('image','imageVersion','materialInputs','annotations','targetArtwork','visualGroups')}
    value=compact(view(p))
    fields['structured']={k:value[k] for k in ('artwork','events','relations')}
    from .library_review import active_conflicts
    fields['structured']['conflicts']=active_conflicts(value)
    return fields


def bound(p,owner_kind,owner_id,kind,rid):
    w=ws.ensure(p);owner=w['entities'][ws.key(owner_kind,owner_id)]
    ref=next((v for v in owner.get('refs',[]) if v['key']==ws.key(kind,rid)),None)
    revision=ref['revision'] if ref else None;item=revisions.resolve(w,ws.key(kind,rid),revision)
    if kind=='clue':
        errors=revisions.citation_issues(w,ws.key(kind,rid),item['data'],revision)
        if errors:raise ValueError('；'.join(errors))
    return copy.deepcopy(item['data'])


def evidence(p, clue,clue_id=None,clue_revision=None):
    w=ws.ensure(p)
    if clue_id is None:clue_id=next((r['id'] for r in w['entities'].values() if r['kind']=='clue' and r.get('published')==clue),None)
    materials = revisions.materials_for(w,ws.key('clue',clue_id),clue_revision) if clue_id else [confirmed(p, 'material', 'main')]
    from .structured import material_sources
    sources = {(s['id'],s['version']):s for mat in materials for s in material_sources(mat) if s.get('sourceType')!='creative_intent'}
    annotations={(a['id'],a.get('description')):a for mat in materials for a in mat.get('annotations',[]) if a.get('confirmed')}
    out = []
    for unit in clue.get('units', []):
        for ref in unit.get('references', []):
            source = sources.get((ref.get('sourceId'),ref.get('sourceVersion')))
            quote = ref.get('quote', '')
            if source and quote and source['version'] == ref.get('sourceVersion') and quote in source['text']:
                meta=next((e for mat in materials for e in (mat.get('structured') or {}).get('evidence',[]) if e.get('sourceId')==source['id'] and e.get('sourceVersion')==source['version'] and e.get('quote')==quote),{})
                out.append(dict(sourceId=source['id'], sourceVersion=source['version'],
                                quote=quote, title=source['title'], category=unit.get('category', 'fiction'),
                                level=meta.get('level','creator' if source.get('method')=='material_input' else 'research'),verification=meta.get('verification','unverified'),
                                edition=meta.get('edition',source.get('citation','')),locator=source.get('locator',''),documentId=source.get('documentId'),page=source.get('page')))
            elif (ref.get('annotationId'),quote) in annotations:
                out.append(dict(annotationId=ref['annotationId'],quote=quote,title='已确认画面观察',level='observation',category=unit.get('category','fiction')))
    return out


def freeze(p):
    w=ws.ensure(p);entities={}
    for key,r in w['entities'].items():
        if r.get('published') is None or r['state']=='deleted':continue
        item={k:copy.deepcopy(r[k]) for k in ('id','kind','published','revision','state','refs','reviewedRefs','basisError','linkedBasisRefs') if k in r};item['draft']=copy.deepcopy(item['published']);entities[key]=item
    return dict(id=p['id'],title=p['title'],version=p['version'],documents=[{k:d.get(k) for k in ('id','title','filename')} for d in p.get('documents',[])],
                workspace=dict(schemaVersion='2.0',revisionPolicy=1,entities=entities,revisionArchive=copy.deepcopy(w.get('revisionArchive',{})),media=copy.deepcopy(w.get('media',{})),folders=copy.deepcopy(w.get('folders',[])),jobs=[]))
