"""Reusable scoped feedback jobs. Models propose typed operations; adapters write facts."""
import asyncio
import copy
import json
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from . import task_runtime as tr, structured, workspace as ws
from .library_review import SECTIONS, active_conflicts, refresh

Section = Literal['artwork', 'people', 'relations', 'events', 'research', 'sources', 'statements', 'conflicts']


class FeedbackTarget(BaseModel):
    kind: Literal['library','intent','plot','clue','character','persona','storyboard'] = 'library'
    section: str = 'content'
    itemIds: list[str] = Field(default_factory=list, max_length=2000)
    fields: list[str] = Field(default_factory=list,max_length=30)
    unitIds: list[str] = Field(default_factory=list,max_length=100)


class FeedbackRequest(BaseModel):
    version: int
    requestId: str = Field(min_length=1, max_length=100)
    target: FeedbackTarget
    instruction: str = Field(default='', max_length=8000)
    resolution: Literal['current', 'candidate', 'keep_both'] | None = None
    peopleAction: Literal['include','exclude','merge_groups'] | None = None
    groups: list[dict] = Field(default_factory=list,max_length=200)

    @model_validator(mode='after')
    def content(self):
        if not self.instruction.strip() and self.resolution is None and self.peopleAction is None:
            raise ValueError('请输入修改要求')
        if self.resolution and (self.target.section != 'conflicts' or not self.target.itemIds):
            raise ValueError('请选择要处理的争议')
        if self.peopleAction and (self.target.kind!='library' or self.target.section!='people' or not self.target.itemIds):raise ValueError('请选择要批量处理的资料人物')
        return self


class Operation(BaseModel):
    op: Literal['update', 'merge_people', 'resolve_conflict', 'summarize', 'set_inclusion']
    section: str = 'people'
    itemId: str = ''
    field: str = ''
    value: str = Field(default='', max_length=8000)
    referenceIds: list[str] = Field(default_factory=list, max_length=30)
    personIds: list[str] = Field(default_factory=list, max_length=2000)
    unitId: str = ''
    survivorId: str = ''
    resolution: Literal['current', 'candidate', 'keep_both'] = 'keep_both'


class FeedbackOutput(BaseModel):
    question: str = ''
    message: str = ''
    operations: list[Operation] = Field(default_factory=list, max_length=2000)


def library(p):
    return p['workspace']['entities']['material:main']['draft'].get('structured')


def selected(value, target):
    if target.section not in (*SECTIONS,'statements','conflicts'):raise ValueError('资料模块无效')
    rows = [dict(v, id=k) for k, v in value['artwork'].items()] if target.section == 'artwork' else value[target.section]
    if target.itemIds:
        rows = [r for r in rows if r['id'] in target.itemIds]
        if len({r['id'] for r in rows}) != len(set(target.itemIds)):
            raise ValueError('选中内容已变化，请重新选择')
    return rows


def context(p, target):
    if target.kind!='library':
        from .smart_adapters import ADAPTERS
        return ADAPTERS[target.kind].context(p,target)
    value = library(p)
    if not value: raise ValueError('请先整理资料')
    rows = selected(value, target)
    if target.section=='people' and not target.itemIds:
        from .people_policy import view
        visible=view(p,value);ids=set(visible['mainIds']+visible['candidateIds']+[rid for group in visible['duplicateGroups'] for rid in group['personIds']])
        rows=[r for r in rows if r['id'] in ids]
    people = {r['id'] for r in rows} if target.section == 'people' else set()
    related = [r for r in value['statements'] if r.get('personId') in people]
    related += [r for r in value['relations'] if r.get('fromId') in people or r.get('toId') in people]
    refs = {eid for r in rows + related for eid in r.get('referenceIds', [])}
    for r in rows:
        for alternative in r.get('alternatives', []): refs.update(alternative['referenceIds'])
    evidence = [e for e in value['evidence'] if e['id'] in refs]
    linked={r.get('characterId') for r in rows if r.get('characterId')}
    # Sources are editable only through explicit source tools, never a rewrite.
    if target.section == 'sources':
        rows = [{k: r.get(k) for k in ('id', 'title', 'version', 'citation', 'sourceType')} for r in rows]
    return dict(target=target.model_dump(), selected=rows, related=related, evidence=evidence,
                summary=value.get('summaryBlocks',{}).get(target.section),
                linkedRoleHashes={k:tr.digest(dict(draft=r['draft'],state=r['state'])) for k,r in p['workspace']['entities'].items()
                                  if r['kind'] in ('character','knowledge','persona') and r['id'] in linked},
                people=[{k: r.get(k) for k in ('id', 'name', 'scope', 'characterId')} for r in value['people']
                        if r['id'] in people or any(r['id'] in (v.get('fromId'), v.get('toId')) for v in related)],
                sourceLabels=[{k:s.get(k) for k in ('id','version','title','citation','documentId','page')}
                              for s in value['sources'] if any(e['sourceId']==s['id'] and e['sourceVersion']==s['version'] for e in evidence)])


async def ask(payload):
    from . import studio_agent
    return await studio_agent.run('feedback', payload)


def rebind(value, redirects):
    if isinstance(value, list):
        for item in value: rebind(item, redirects)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in ('characterId', 'personId', 'fromId', 'toId', 'speakerId') and isinstance(item, str):
                value[key] = redirects.get(item, item)
            elif key == 'characterIds':
                value[key] = list(dict.fromkeys(redirects.get(v, v) for v in item))
            elif key not in ('history', 'published', 'revisionArchive'):
                rebind(item, redirects)


def merge_people(p, value, ids, survivor=''):
    rows = [r for r in value['people'] if r['id'] in ids]
    if len(rows) != len(set(ids)) or len(rows) < 2:
        raise ValueError('合并至少需要两位当前人物')
    if survivor and survivor not in ids: raise ValueError('保留人物必须来自所选人物')
    keep = next((r for r in rows if r['id'] == survivor), None)
    keep = keep or sorted(rows, key=lambda r: (not bool(r.get('characterId')), r['id']))[0]
    others = [r for r in rows if r['id'] != keep['id']]
    redirects = {r['id']: keep['id'] for r in others}
    aliases = keep.setdefault('aliases', [])
    for r in others:
        if r.get('summary') and r['summary']!=keep.get('summary'):
            value['statements'].append(dict(id=structured.stable('merged-summary',[r['id'],r['summary']]),personId=keep['id'],aspect='合并前资料',text=r['summary'],referenceIds=r.get('referenceIds',[]),category='uncertain',origin='feedback'))
        for alias in [dict(name=r['name'], origin='creator')] + r.get('aliases', []):
            alias = dict(name=alias) if isinstance(alias, str) else copy.deepcopy(alias)
            if alias['name'] != keep['name'] and not any((a if isinstance(a,str) else a['name']) == alias['name'] for a in aliases): aliases.append(alias)
        for field in ('referenceIds', 'annotationIds', 'contextRoles'):
            keep[field] = list(dict.fromkeys(keep.get(field, []) + r.get(field, [])))
        if not keep.get('summary'): keep['summary'] = r.get('summary', '')
    if any(r.get('scope') == 'depicted' for r in rows): keep['scope'] = 'depicted'
    for row in value['statements']: row['personId'] = redirects.get(row.get('personId'), row.get('personId'))
    for row in value['relations']: rebind(row, redirects)
    removed_relations={r['id'] for r in value['relations'] if r['fromId']==r['toId']}
    value['relations'] = [r for r in value['relations'] if r['id'] not in removed_relations]
    for conflict in value['conflicts']:
        parts=conflict.get('field','').split('.')
        if len(parts)>1 and parts[0]=='people' and parts[1] in redirects:
            parts[1]=redirects[parts[1]];conflict['field']='.'.join(parts)
        elif len(parts)>1 and parts[0]=='relations' and parts[1] in removed_relations:
            conflict.update(status='retired',decision='identity_merge')
    value['people'] = [r for r in value['people'] if r['id'] not in redirects]
    mapping = value.setdefault('personRedirects', {})
    for key, dest in list(mapping.items()): mapping[key] = redirects.get(dest, dest)
    mapping.update(redirects)
    char_redirects = {r['characterId']: keep['characterId'] for r in others
                      if r.get('characterId') and keep.get('characterId') and r['characterId'] != keep['characterId']}
    entities = p['workspace']['entities']
    for old, new in char_redirects.items():
        old_record = entities.get('character:' + old)
        new_record = entities.get('character:' + new)
        if old_record and new_record:
            for key in ('identity', 'summary', 'biography', 'relationships'):
                text = old_record['draft'].get(key, '')
                if text and text not in new_record['draft'].get(key, ''):
                    new_record['draft'][key] = '；'.join(filter(None, [new_record['draft'].get(key), text]))
            new_record['draft']['aliases'] = copy.deepcopy(aliases)
            old_record['state'] = 'deleted'
            old_record['draft']['mergedInto'] = new
            for kind in ('knowledge','persona'):
                companion=entities.get(kind+':'+old)
                if companion:
                    companion['state']='deleted';companion['draft']['mergedInto']=new
    mat = entities['material:main']['draft']
    for key in ('annotations', 'matches', 'visualGroups'): rebind(mat.get(key, {}), char_redirects)
    # Current links follow redirects; generated plots, knowledge and historic
    # publications are not silently rewritten by a library operation.
    p['annotations'] = copy.deepcopy(mat.get('annotations', []))
    p['matches'] = copy.deepcopy(mat.get('matches', []))
    for old, new in char_redirects.items(): mapping[old] = new
    # Keep old candidate extraction immutable but suppress merged names when it
    # is next converted into a structured library.
    value.setdefault('mergedNames', {}).update({r['name']: keep['id'] for r in others})
    return f'已合并 {len(rows)} 位人物，保留 {len(keep.get("referenceIds", []))} 处依据'


def apply_operations(p, target, operations):
    if target.kind!='library':
        from .smart_adapters import ADAPTERS
        return ADAPTERS[target.kind].apply(p,target,operations)
    value = library(p)
    allowed = {r['id'] for r in context(p, target)['selected']}
    messages = []
    for raw in operations:
        op = Operation.model_validate(raw).model_dump()
        kind = op['op']
        if kind=='set_inclusion':
            if target.section!='people' or op['itemId'] not in allowed or op['value'] not in ('include','exclude'):raise ValueError('人物批量处理超出所选范围')
            person=next(r for r in value['people'] if r['id']==op['itemId'])
            person.update(inclusionDecision=op['value'],origin='creator')
            cid=person.get('characterId');entities=p['workspace']['entities']
            if op['value']=='include' and not cid:
                cid=person['id'];person['characterId']=cid
                body=dict(id=cid,name=person['name'],summary=person.get('summary',''),identity='',biography='',relationships='',knowledge='',evidence='创作者选择加入画中人物；原文范围与不确定性保留',namingOrigin='creator',depictionScope=person.get('scope','unknown'),roleType=person.get('roleType','role'),mentions=[],aliases=person.get('aliases',[]),inclusionDecision='include')
                entities['character:'+cid]=ws.record('character',cid,body)
                entities['knowledge:'+cid]=ws.record('knowledge',cid,dict(characterId=cid,clueIds=[],reasons={}))
            if cid and 'character:'+cid in entities:entities['character:'+cid]['draft']['inclusionDecision']=op['value']
            messages.append('已更新所选人物的画中范围；原文与实例保留')
        elif kind == 'merge_people':
            if target.section != 'people' or not set(op['personIds']) <= allowed:
                raise ValueError('合并超出选中的人物范围')
            messages.append(merge_people(p, value, op['personIds'], op['survivorId']))
        elif kind == 'resolve_conflict':
            if target.section != 'conflicts' or op['itemId'] not in allowed:
                raise ValueError('争议处理超出所选范围')
            c = next(c for c in value['conflicts'] if c['id'] == op['itemId'])
            if c.get('kind') != 'contradiction': raise ValueError('普通差异不是已判定的争议')
            if op['resolution'] != 'keep_both':
                parts = c['field'].split('.')
                row = value['artwork'][parts[1]] if parts[0] == 'artwork' else next(r for r in value[parts[0]] if r['id'] == parts[1])
                alternative = c['alternatives'][0 if op['resolution'] == 'current' else 1]
                row['value' if parts[0] == 'artwork' else parts[2]] = alternative['value']
                row['referenceIds'] = alternative['referenceIds']
                row['origin'] = 'feedback'
                if parts[0]=='people' and row.get('characterId'):
                    role=p['workspace']['entities'].get('character:'+row['characterId'])
                    if role:role['draft'][parts[2]]=alternative['value']
            c.update(resolution=op['resolution'], decision='creator')
            messages.append('已记录争议处理方式')
        elif kind == 'summarize':
            if op['section'] != target.section or target.itemIds or target.section not in SECTIONS or not op['value'].strip() or len(op['value'])>600:
                raise ValueError('模块摘要只能针对整个选中模块')
            refresh(value)
            # Artwork summaries use labeled cells in their fingerprint.
            fingerprint = value['summaryBlocks'][target.section]['inputHash']
            block = value['summaryBlocks'][target.section]
            block.update(text=op['value'], inputHash=fingerprint, origin='feedback')
            value.setdefault('summaryOverrides',{})[target.section]=copy.deepcopy(block)
            messages.append('已更新模块摘要')
        else:
            section = op['section']
            related_statement = target.section == 'people' and section == 'statements' and any(r['id'] == op['itemId'] and r['personId'] in allowed for r in value['statements'])
            if not related_statement and (section != target.section or op['itemId'] not in allowed):
                raise ValueError('修改超出所选内容范围')
            fields = {'artwork': {'value'}, 'people': {'name', 'summary'}, 'events': {'title', 'text', 'phase', 'time'},
                      'relations': {'label'}, 'research': {'text'}, 'statements': {'text', 'aspect'}}
            if op['field'] not in fields.get(section, set()): raise ValueError('不允许修改此字段')
            row = value['artwork'][op['itemId']] if section == 'artwork' else next(r for r in value[section] if r['id'] == op['itemId'])
            if row.get(op['field']) == op['value']: continue
            known = {e['id'] for e in value['evidence']}
            permitted = {e['id'] for e in context(p, target)['evidence']}
            if not set(op['referenceIds']) <= known & permitted: raise ValueError('修改引用了所选范围以外的依据')
            row['previousReferenceIds'] = copy.deepcopy(row.get('referenceIds', []))
            # Existing quotes are lineage, not automatic proof of newly written
            # text. A revision remains a creator interpretation pending review.
            row.update({op['field']: op['value'], 'referenceIds': op['referenceIds'], 'origin': 'feedback'})
            if section != 'artwork': row['category'] = 'uncertain'
            if section == 'people' and row.get('characterId'):
                character = p['workspace']['entities'].get('character:' + row['characterId'])
                if character: character['draft'][op['field']] = op['value']
            messages.append('已更新选中内容')
    structured.validate(value)
    structured.finish(value)
    p['structured'] = copy.deepcopy(value)
    return '；'.join(dict.fromkeys(messages)) or '内容无需修改'


def editable(p):
    """Only owned content, never history or unrelated generated material."""
    entities = p['workspace']['entities']
    result={'workspace': {'entities': {k: dict(draft=copy.deepcopy(r['draft']), state=r['state'])
            for k, r in entities.items() if r['kind'] in ('material', 'character', 'knowledge', 'persona','intent','plot','clue','storyboard')}}}
    # Derived summaries are rebuilt after undo. They must not make an unrelated
    # edit in the same module look like an overlapping fact modification.
    value=result['workspace']['entities']['material:main']['draft'].get('structured')
    if value:value.pop('summaryBlocks',None)
    return result


def changes(before, after, path=''):
    if before == after: return []
    if isinstance(before, dict) and isinstance(after, dict):
        out = []
        for key in sorted(set(before) | set(after)):
            child = path + '/' + key
            if key not in before or key not in after:
                out.append(dict(path=child, before=before.get(key), after=after.get(key), existed=key in before, exists=key in after))
            else: out += changes(before[key], after[key], child)
        return out
    keyed = lambda rows: isinstance(rows, list) and all(isinstance(r, dict) and 'id' in r for r in rows)
    if keyed(before) and keyed(after):
        return changes({'@' + r['id']: r for r in before}, {'@' + r['id']: r for r in after}, path)
    return [dict(path=path, before=before, after=after, existed=True, exists=True)]


def activate(p, touched):
    w = ws.ensure(p)
    w['_autoEnabling'] = True
    try:
        for key in sorted(touched, key=lambda k: k != 'material:main'):
            if key not in w['entities']:continue
            row = w['entities'][key]
            if row['state'] == 'deleted': continue
            # Preserve draft-only material as draft; otherwise feedback becomes
            # available through the same targeted commit used by the editor.
            if row.get('published') is not None or row['kind']=='character' and row['draft'].get('inclusionDecision')=='include':
                if row['kind'] in ('plot','clue','intent','persona','storyboard'):
                    issues=ws.validate_entity(p,w,row)
                    if issues:raise ValueError('；'.join(issues))
                    from .revisions import archive
                    archive(w,key,row)
                    if row.get('published') is not None:row['history'].append(dict(revision=row['revision'],data=copy.deepcopy(row['published']),refs=copy.deepcopy(row.get('refs',[]))))
                    row['revision']+=1;row['published']=copy.deepcopy(row['draft']);row['refs']=ws.refs_for(w,row)
                    row.update(state='confirmed',generationRefs=copy.deepcopy(row['refs']));row.pop('reviewedRefs',None)
                    archive(w,key,row)
                else:ws.commit(p, w, row, True)
                row['activation'] = dict(method='auto', revision=row['revision'])
    finally: w.pop('_autoEnabling', None)
    ws.mirror(p)


def install(app, get, save, db):
    runners = set()

    def schema(c): c.execute('CREATE TABLE IF NOT EXISTS feedback_jobs(id TEXT PRIMARY KEY, project TEXT, body TEXT)')
    def store(job):
        with db() as c:
            schema(c)
            c.execute('INSERT OR REPLACE INTO feedback_jobs VALUES (?,?,?)', (job['id'], job['projectId'], json.dumps(job, ensure_ascii=False)))
    def load(pid, jid):
        get(pid)
        with db() as c:
            schema(c)
            row = c.execute('SELECT body FROM feedback_jobs WHERE id=? AND project=?', (jid, pid)).fetchone()
        if not row: raise HTTPException(404, '反馈任务不存在')
        return json.loads(row[0])
    def public(job): return {k: v for k, v in job.items() if k not in ('changes', 'readContext')}
    def hook(job):
        def transaction(c, old, new):
            schema(c)
            c.execute('INSERT OR REPLACE INTO feedback_jobs VALUES (?,?,?)', (job['id'], job['projectId'], json.dumps(job, ensure_ascii=False)))
        return transaction

    async def run(job, req):
        job.update(status='running', progress='正在按所选范围整理修改')
        store(job)
        try:
            if req.peopleAction:
                if req.peopleAction=='merge_groups':
                    allowed=set(req.target.itemIds);used=set();ops=[]
                    for group in req.groups:
                        ids=group.get('personIds',[])
                        if len(set(ids))<2 or not set(ids)<=allowed or used&set(ids):raise ValueError('归并组必须相互独立，并来自所选人物')
                        used.update(ids);ops.append(dict(op='merge_people',personIds=ids,survivorId=group.get('survivorId','')))
                    if not ops:raise ValueError('请选择归并建议')
                    output=dict(operations=ops)
                else:output=dict(operations=[dict(op='set_inclusion',itemId=rid,value=req.peopleAction) for rid in req.target.itemIds])
            elif req.resolution:
                output = dict(operations=[dict(op='resolve_conflict', itemId=rid, resolution=req.resolution) for rid in req.target.itemIds])
            else:
                payload = dict(context=job['readContext'], instruction=req.instruction)
                output = await ask(payload)
            result = FeedbackOutput.model_validate(output)
            if result.question:
                job.update(status='needs_input', question=result.question, progress='请补充修改方向')
                store(job); return
            for attempt in range(4):
                p = get(job['projectId'])
                if tr.digest(context(p, req.target)) != job['inputHash']:
                    job.update(status='stale', progress='选中内容或依据已变化，结果已保留；请按最新内容重新发送', suggestion=result.model_dump())
                    store(job); return
                before = editable(p)
                message = apply_operations(p, req.target, result.operations)
                delta = changes(before, editable(p))
                touched = {d['path'].split('/')[3] for d in delta}
                affected={r['key']:r for key in touched for r in ws.impact(p['workspace'],key) if r['key'] not in touched}
                activate(p, touched)
                delta=changes(before,editable(p))
                # Main save's generation hook records affected review units only.
                job.update(status='completed', progress=message, message=message, changes=delta, affected=list(affected.values()),operationId=job['id'], finishedAt=tr.now())
                try:
                    save(p, p['version'], 'studio:generation:feedback', dict(instruction=req.instruction, target=req.target.model_dump(), taskId=job['id']), transaction_hook=hook(job))
                    return
                except HTTPException as exc:
                    if exc.status_code != 409 or attempt == 3: raise
        except Exception as exc:
            job.update(status='failed', progress=str(exc)[:600] if isinstance(exc, (ValueError, HTTPException)) else '反馈处理失败，原资料已保留，请重试')
            store(job)

    def recover():
        with db() as c:
            schema(c)
            for jid, body in c.execute('SELECT id,body FROM feedback_jobs'):
                job = json.loads(body)
                if job['status'] in ('queued', 'running'):
                    job.update(status='interrupted', progress='服务重启，原资料已保留，请重新发送')
                    c.execute('UPDATE feedback_jobs SET body=? WHERE id=?', (json.dumps(job, ensure_ascii=False), jid))

    app.router.add_event_handler('startup', recover)

    @app.post('/api/projects/{pid}/studio/feedback')
    async def submit(pid: str, req: FeedbackRequest):
        p = get(pid)
        jid = 'feedback-' + tr.digest([pid, req.requestId])[:24]
        with db() as c:
            schema(c)
            previous = c.execute('SELECT body FROM feedback_jobs WHERE id=? AND project=?', (jid, pid)).fetchone()
        if previous:
            job = json.loads(previous[0])
            if FeedbackRequest.model_validate(job['request']).model_dump() != req.model_dump(): raise HTTPException(409, '同一请求编号不能用于不同的反馈')
            return public(job)
        if p['version'] != req.version: raise HTTPException(409, '资料已变化，请重新加载后发送')
        try: ctx = context(p, req.target)
        except ValueError as exc: raise HTTPException(422, str(exc))
        job = dict(id=jid, projectId=pid, status='queued', progress='等待处理', request=req.model_dump(),
                   inputHash=tr.digest(ctx), readContext=ctx, time=tr.now())
        from .config import model_settings
        settings=model_settings(require_key=False)
        job.update(provider=settings.provider,model=None if req.resolution or req.peopleAction else settings.model,
                   promptVersion='scoped-feedback-2',trigger='user_choice' if req.resolution or req.peopleAction else 'user_message')
        try: tr.reserve(db, 'feedback_jobs', job)
        except ValueError as exc: raise HTTPException(409, str(exc))
        runner = asyncio.create_task(run(job, req));runners.add(runner);runner.add_done_callback(runners.discard)
        return public(job)

    @app.get('/api/projects/{pid}/studio/feedback/{jid}')
    def inspect(pid: str, jid: str): return public(load(pid, jid))

    @app.post('/api/projects/{pid}/studio/feedback/{jid}/undo')
    def undo(pid: str, jid: str):
        job = load(pid, jid)
        if job.get('undone'): return public(job)
        if job['status'] != 'completed': raise HTTPException(409, '该反馈尚未完成，不能撤销')
        for attempt in range(4):
            p = get(pid)
            delta = job.get('changes', [])
            if any(tr.value_at(editable(p), d['path']) != d['after'] for d in delta):
                raise HTTPException(409, '相关内容已有后续修改，不能覆盖；可选择最新内容再次反馈')
            from .review_units import assign
            for d in reversed(delta): assign(p, d['path'], d['before'], delete=not d['existed'])
            value = library(p)
            if value: structured.finish(value);structured.validate(value)
            activate(p, {d['path'].split('/')[3] for d in delta})
            undone = dict(job, undone=True)
            try:
                save(p, p['version'], 'studio:feedback_undo', dict(operationId=jid), transaction_hook=hook(undone))
                return public(undone)
            except HTTPException as exc:
                if exc.status_code != 409 or attempt == 3: raise
