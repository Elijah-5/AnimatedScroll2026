"""One cast policy. A mention in a document is not a depicted character."""
import re
from .task_runtime import digest


def decision(person):
    return person.get('inclusionDecision') or person.get('creatorDecision')


def character_allowed(character, project=None):
    if decision(character) == 'exclude' or character.get('mergedInto'): return False
    if decision(character) == 'include': return True
    if project:
        cid=character.get('id')
        entities=project.get('workspace',{}).get('entities',{})
        material=entities.get('material:main',{}).get('draft',{})
        choices=[decision(r) for r in (material.get('structured') or {}).get('people',[]) if r.get('characterId')==cid or r.get('id')==cid]
        if 'exclude' in choices:return False
        if 'include' in choices:return True
        record=entities.get('character:'+str(cid),{})
        receipt=project.get('workspace',{}).get('reviewUnits',{}).get('members',{}).get('character:'+str(cid),{})
        if record.get('activation',{}).get('method') in ('human','manual') or receipt.get('origin')=='human':return True
        annotations=material.get('annotations',project.get('annotations',[]))
        if any(a.get('characterId')==cid and (a.get('identityManual') or a.get('identityConfirmed') or a.get('confirmed')) for a in annotations): return True
        for row in entities.values():
            if row.get('state')=='deleted' or row.get('kind') not in ('plot','clue','storyboard'): continue
            data=row.get('draft',{})
            if cid in data.get('characterIds',[]) or any(u.get('speakerId')==cid for u in data.get('units',[])): return True
    if character.get('namingOrigin') == 'creator': return True
    if character.get('depictionScope') == 'background': return False
    if character.get('depictionScope')=='depicted':
        return bool(character.get('depictionReferences')) or character.get('namingOrigin')!='document'
    # Older manually created projects did not have a namingOrigin field. Keep
    # those operational roles, without treating an imported role ID as evidence.
    return not character.get('namingOrigin') and character.get('depictionScope','unknown')=='unknown'


def names(row):
    return {n for n in [row.get('name'),row.get('sourceName'),(row.get('creativeNaming') or {}).get('name')]+
            [a.get('name') if isinstance(a,dict) else a for a in row.get('aliases',[])] if n}


def eligible_mention(row):
    if decision(row)=='exclude': return False
    return decision(row)=='include' or row.get('scope')=='depicted' and bool(row.get('depictionReferences') or row.get('referenceIds'))


def duplicate_groups(value, analysis=None):
    people=value.get('people',[]);evidence={e['id']:e for e in value.get('evidence',[])}
    groups=[];seen=set()
    for i,a in enumerate(people):
        for b in people[i+1:]:
            if decision(a)=='exclude' or decision(b)=='exclude': continue
            if a.get('roleType')=='group' or b.get('roleType')=='group':
                if a.get('roleType')!=b.get('roleType'): continue
            shared=set(a.get('annotationIds',[]))&set(b.get('annotationIds',[]))
            alias_match=bool(names(a)&names(b)) and a.get('name')!=b.get('name')
            # Bare titles may refer to different rulers. Such a pair is an
            # optional suggestion, never an automatic historical alias.
            short=min((a.get('name',''),b.get('name','')),key=len)
            long=max((a.get('name',''),b.get('name','')),key=len)
            possible=bool(len(short)>=2 and long!=short and long.endswith(short) and a.get('roleType')!='group' and b.get('roleType')!='group')
            if possible and sum(1 for row in people if row.get('name')!=short and row.get('name','').endswith(short))>1:possible=False
            explicit=False
            if alias_match:
                for row,other in ((a,b),(b,a)):
                    for alias in row.get('aliases',[]):
                        if not isinstance(alias,dict) or alias.get('name')!=other.get('name'): continue
                        quotes=[r.get('quote','') for r in alias.get('references',[])]
                        quotes += [evidence[e].get('quote','') for e in alias.get('referenceIds',[]) if e in evidence]
                        name=re.escape(row['name']);other_name=re.escape(other['name'])
                        pattern=name+r'(?:[（(，、\s]*(?:即|又名|亦称|又称|本名|字|号)[为：:]?\s*'+other_name+r'|[（(]\s*'+other_name+r'\s*[）)])'
                        explicit=explicit or any(re.search(pattern,q) for q in quotes)
            if not(shared or explicit or possible): continue
            # Unrelated background names are not a cast-review queue.
            if not(a.get('characterId') or b.get('characterId') or a.get('scope')=='depicted' and b.get('scope')=='depicted'): continue
            ids=sorted([a['id'],b['id']]);key=digest(ids)[:20]
            if key in seen:continue
            seen.add(key)
            survivor=sorted((a,b),key=lambda r:(not bool(r.get('characterId')),r['id']))[0]
            groups.append(dict(id=key,personIds=ids,survivorId=survivor['id'],name=survivor['name'],
                               names=[a['name'],b['name']],safe=bool(shared or explicit),
                               reason='关联同一画中实例' if shared else '原文明确关联两种称呼' if explicit else '称谓可能指向同一人物，需结合原文判断'))
    # Connected proven/unique suggestions form one independent group. A batch
    # can adopt several groups without ever merging all selected IDs together.
    components=[]
    for group in groups:
        touching=[c for c in components if set(c['personIds'])&set(group['personIds'])]
        ids=set(group['personIds']);safe=group['safe']
        for item in touching:ids.update(item['personIds']);safe=safe and item['safe'];components.remove(item)
        rows=[r for r in people if r['id'] in ids]
        survivor=sorted(rows,key=lambda r:(not bool(r.get('characterId')),r['id']))[0]
        components.append(dict(id=digest(sorted(ids))[:20],personIds=sorted(ids),survivorId=survivor['id'],name=survivor['name'],names=[r['name'] for r in rows],safe=safe,reason='原文别名或同一画中实例提供归并依据' if safe else '称谓可能指向同一人物，需结合原文判断'))
    return components


def view(project,value=None):
    entities=project.get('workspace',{}).get('entities',{})
    material=entities.get('material:main',{}).get('draft',{})
    value=value if value is not None else material.get('structured') or {}
    roles=[dict(r['draft'],id=r['id']) for r in entities.values() if r.get('kind')=='character' and r.get('state')!='deleted']
    if not roles:roles=project.get('characters',[])
    allowed={r['id'] for r in roles if character_allowed(r,project)}
    people=value.get('people') or [dict(r,characterId=r['id'],scope=r.get('depictionScope','unknown')) for r in roles]
    main=[];candidates=[];other=[]
    for row in people:
        if decision(row)=='exclude':other.append(row['id'])
        elif row.get('characterId') in allowed or row['id'] in allowed:main.append(row['id'])
        elif eligible_mention(row):candidates.append(row['id'])
        else:other.append(row['id'])
    groups=duplicate_groups(dict(value,people=people),project.get('documentAnalysis'))
    return dict(eligibleCharacterIds=sorted(allowed),mainIds=main,candidateIds=candidates,otherIds=other,duplicateGroups=groups)


def intake_ids(project,people):
    """Keep new unbound descriptions as optional material, not extra actors."""
    entities=project.get('workspace',{}).get('entities',{})
    existing=[dict(r['draft'],id=r['id']) for r in entities.values() if r.get('kind')=='character' and r.get('state')!='deleted'] or project.get('characters',[])
    decisions=(entities.get('material:main',{}).get('draft',{}).get('structured') or {}).get('people',[])
    excluded={n for r in decisions if decision(r)=='exclude' for n in names(r)}
    out=[]
    for row in people:
        if not eligible_mention(row) or names(row)&excluded:continue
        matched=any(names(row)&names(c) for c in existing)
        if existing and not matched and row.get('roleType') in ('role','group'):continue
        if row.get('roleType')=='named' and len(row['name'])>=2 and any(other.get('name')!=row['name'] and other.get('name','').endswith(row['name']) for other in people if other.get('scope')=='depicted'):continue
        out.append(row['id'])
    return out
