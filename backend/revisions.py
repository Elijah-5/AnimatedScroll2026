"""Immutable published bases, independent of non-blocking revision notices."""
import copy


def archive(w,key,record):
    if record.get('published') is None:return
    versions=w.setdefault('revisionArchive',{}).setdefault(key,{})
    version=str(record['revision']);saved=versions.get(version)
    if saved is None:
        saved=dict(data=copy.deepcopy(record['published']),refs=copy.deepcopy(record.get('refs',[])));versions[version]=saved
    for linked,revision in record.get('linkedBasisRefs',{}).items():
        if revision and not saved.setdefault('linkedRefs',{}).get(linked):saved['linkedRefs'][linked]=revision


def upgrade(p,events=None):
    w=p.get('workspace')
    if not w:return
    if w.get('revisionPolicy')!=1:
        # Old history entries saved content but not dependency references. Recover
        # those references from the earliest recorded publication, never guess them.
        if events:
            for snapshot in events():
                for key,r in snapshot.get('workspace',{}).get('entities',{}).items():archive(w,key,r)
        for key,r in w['entities'].items():
            for h in r.get('history',[]):
                if 'refs' in h:w.setdefault('revisionArchive',{}).setdefault(key,{}).setdefault(str(h['revision']),dict(data=copy.deepcopy(h['data']),refs=copy.deepcopy(h['refs'])))
            archive(w,key,r)
        w['revisionPolicy']=1
    for key,r in w['entities'].items():
        archive(w,key,r)
        if r.get('published') is not None and r.get('state')!='deleted':
            try:
                resolve(w,key)
                if r.get('state') in ('stale','review'):r['state']='confirmed'
                r.pop('basisError',None)
            except ValueError as exc:r['basisError']=str(exc)


def node(w,key,revision=None):
    r=w['entities'].get(key)
    if not r or r.get('state')=='deleted':raise ValueError('引用对象已删除或不存在：'+key)
    if revision is None:revision=r['revision']
    if revision==r['revision'] and r.get('published') is not None:return dict(data=r['published'],refs=r.get('refs',[]),linkedRefs=r.get('linkedBasisRefs',{}),revision=revision)
    old=w.get('revisionArchive',{}).get(key,{}).get(str(revision))
    if not old:raise ValueError('无法恢复历史依据：'+key+' r'+str(revision))
    return dict(old,revision=revision)


def resolve(w,key,revision=None,seen=None):
    item=node(w,key,revision);seen=set() if seen is None else seen;token=(key,item['revision'])
    if token in seen:return item
    seen.add(token)
    for ref in item['refs']:resolve(w,ref['key'],ref['revision'],seen)
    return item


def bases(w,key,revision=None,copy_data=True):
    result={};seen=set()
    def visit(k,revision=None):
        item=node(w,k,revision);token=(k,item['revision'])
        if token in seen:return
        snapshot=copy.deepcopy if copy_data else lambda value:value
        seen.add(token);result[k+'@'+str(item['revision'])]=dict(key=k,revision=item['revision'],data=snapshot(item['data']),refs=snapshot(item['refs']),linkedRefs=snapshot(item.get('linkedRefs',{})))
        for ref in item['refs']:visit(ref['key'],ref['revision'])
        for linked,version in item.get('linkedRefs',{}).items():
            if version:visit(linked,version)
    visit(key,revision);return result


def material_for(w,key,revision=None):
    items=[v for v in bases(w,key,revision).values() if v['key']=='material:main']
    return items[0]['data'] if items else node(w,'material:main')['data']


def materials_for(w,key,revision=None):
    return [v['data'] for v in bases(w,key,revision).values() if v['key']=='material:main']


def citation_issues(w,key,clue,revision=None,editing=False):
    from .domain import citation_errors
    from .structured import material_sources
    try:materials=materials_for(w,key,revision)
    except ValueError:
        if not editing:raise
        materials=[]
    record=w['entities'].get(key,{})
    if editing and (record.get('draftRefs') or record.get('published') is None and record.get('refs')):
        projected=dict(w,entities=dict(w['entities']))
        refs=copy.deepcopy(record.get('draftRefs') or record['refs'])
        for ref in refs:
            if ref['revision']==0:ref['revision']=w['entities'].get(ref['key'],{}).get('revision',0)
        projected['entities'][key]=dict(record,published=clue,refs=refs)
        materials.extend(materials_for(projected,key))
    current=w['entities'].get('material:main',{}).get('published')
    if editing and current:materials.append(current)
    if not materials:raise ValueError('没有可恢复的已确认原文依据')
    errors=[]
    for original in clue.get('units',[]):
        unit=copy.deepcopy(original);sources=[];annotations=[]
        for i,ref in enumerate(unit.get('references',[])):
            source=next((s for m in materials for s in material_sources(m) if s['id']==ref.get('sourceId') and s['version']==ref.get('sourceVersion') and ref.get('quote') and ref['quote'] in s['text']),None)
            if source:
                token='source-'+str(i);sources.append(dict(source,id=token));ref['sourceId']=token
            annotation=next((a for m in materials for a in m.get('annotations',[]) if a['id']==ref.get('annotationId') and a.get('description')==ref.get('quote') and a.get('confirmed')),None)
            if annotation:
                token='annotation-'+str(i);annotations.append(dict(annotation,id=token));ref['annotationId']=token
        errors.extend(citation_errors(unit,dict(sources=sources,annotations=annotations,materialInputs=materials[0].get('materialInputs',{}))))
    return list(dict.fromkeys(errors))


def warnings(w,r):
    if r.get('published') is None or r.get('state')=='deleted':return []
    key=r['kind']+':'+r['id'];result=[];seen=set();reviewed=r.get('reviewedRefs',{})
    try:
        items=list(bases(w,key,copy_data=False).values())
        for k,revision in r.get('linkedBasisRefs',{}).items():
            if revision:items.append(dict(node(w,k,revision),key=k))
    except ValueError:return []
    for item in items:
        k=item['key'];current=w['entities'].get(k)
        if k==key or not current or current['revision']==item['revision'] or k in seen:continue
        seen.add(k);before=item['data'];after=current.get('published') or {}
        def display(field,value):
            if field=='structured' and value:
                from .structured import compact
                return compact(value)
            return copy.deepcopy(value)
        changes=[dict(field=f,before=display(f,before.get(f)),after=display(f,after.get(f))) for f in sorted(set(before)|set(after)) if before.get(f)!=after.get(f)]
        result.append(dict(key=k,name=after.get('name') or after.get('title') or k,fromRevision=item['revision'],toRevision=current['revision'],changes=changes,reviewed=reviewed.get(k)==current['revision']))
    return result


def acknowledge(w,r):
    resolve(w,r['kind']+':'+r['id'])
    r['reviewedRefs']={v['key']:v['toRevision'] for v in warnings(w,r)}


def pin_citations(w,r):
    """Bind generated quotes to confirmed material revisions actually containing them."""
    from .structured import material_sources
    from .documents import evidence_refs
    refs=evidence_refs(r['draft'])
    if not refs:return
    current=w['entities']['material:main'];versions=[dict(revision=current['revision'],data=current.get('published') or {})]
    versions += [dict(revision=int(revision),data=item['data']) for revision,item in w.get('revisionArchive',{}).get('material:main',{}).items()]
    for ref in refs:
        for material in versions:
            if any(s['id']==ref.get('sourceId') and s['version']==ref.get('sourceVersion') and s.get('confirmed') is not False and ref.get('quote') and ref['quote'] in s['text'] for s in material_sources(material['data'])):
                basis=dict(key='material:main',revision=material['revision'])
                if basis not in r['draftRefs']:r['draftRefs'].append(basis)
                break


def decorate(w):
    for r in w['entities'].values():r['basisWarnings']=warnings(w,r)
    return w
