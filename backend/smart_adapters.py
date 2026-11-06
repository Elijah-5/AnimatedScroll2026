"""Typed adapters for scoped authoring edits; no model-controlled JSON paths."""
import copy
from . import workspace as ws, structured, task_runtime as tr

FIELDS={
 'intent':{'brief','theme','goal','audience','tone'},
 'plot':{'title','goal','body','connection'},
 'clue':{'name','summary','content'},
 'character':{'name','identity','summary','biography','relationships'},
 'persona':{'prompt','selfReference','temperament','speechStyle','addressStyle','reactions','situation'},
 'storyboard':{'prompt','action','camera','style','startFrame','endFrame'},
}


class EntityAdapter:
    def __init__(self,kind):self.kind=kind

    def rows(self,p,target):
        if not target.itemIds:raise ValueError('请先选择要智能修改的条目')
        rows=[]
        for rid in target.itemIds:
            row=p['workspace']['entities'].get(self.kind+':'+rid)
            if not row or row['state']=='deleted':raise ValueError('所选条目已变化，请重新选择')
            rows.append(row)
        if target.fields and not set(target.fields)<=FIELDS[self.kind]|({'text','rationale'} if self.kind=='clue' and target.unitIds else set()):raise ValueError('所选字段不支持智能修改')
        if target.unitIds and self.kind!='clue':raise ValueError('仅线索支持选择内容单元')
        if target.unitIds and not set(target.unitIds)<={u['id'] for row in rows for u in row['draft'].get('units',[])}:raise ValueError('所选内容单元不存在')
        return rows

    def context(self,p,target):
        rows=self.rows(p,target)
        material=p['workspace']['entities']['material:main']
        value=material['draft'].get('structured') or (material.get('published') or {}).get('structured') or {}
        refs=[]
        selected=[]
        for row in rows:
            data=copy.deepcopy(row['draft'])
            if self.kind=='clue' and data.get('type')=='narrative':data['content']=ws.narrative_text(data)
            selected.append(dict(id=row['id'],data=data))
            from .documents import evidence_refs
            refs+=evidence_refs(data)
        character_ids={cid for row in rows for cid in row['draft'].get('characterIds',[])}
        if self.kind in ('character','persona'):character_ids.update(target.itemIds)
        person_ids=character_ids|{r['id'] for r in value.get('people',[]) if r.get('characterId') in character_ids}
        facts=[r for r in value.get('statements',[]) if r.get('personId') in person_ids]
        ids={eid for row in facts for eid in row.get('referenceIds',[])}
        evidence=[e for e in value.get('evidence',[]) if e['id'] in ids or any(e.get('sourceId')==r.get('sourceId') and e.get('sourceVersion')==r.get('sourceVersion') and e.get('quote')==r.get('quote') for r in refs)]
        # The model receives the current boundary but cannot modify that boundary
        # or expand knowledge access through an ordinary prose rewrite.
        intent=p['workspace']['entities'].get('intent:main',{}).get('draft',{})
        allowed={'text','rationale'} if target.unitIds else FIELDS[self.kind]
        return dict(target=target.model_dump(),selected=selected,allowedFields=sorted(allowed & set(target.fields) if target.fields else allowed),
                    evidence=evidence,characterFacts=facts,historyFramework=intent.get('framework',[]),
                    forbidden=intent.get('forbidden',[]),
                    readHashes={row['id']:tr.digest(row['draft']) for row in rows})

    def apply(self,p,target,operations):
        rows={r['id']:r for r in self.rows(p,target)};changed=set()
        for raw in operations:
            op=raw.model_dump() if hasattr(raw,'model_dump') else raw
            if op['op']!='update' or op['section']!=self.kind or op['itemId'] not in rows:raise ValueError('智能修改超出所选内容范围')
            row=rows[op['itemId']];data=row['draft'];field=op['field']
            if data.get('locked'):raise ValueError('内容已锁定，请先解锁')
            if target.fields and field not in target.fields:raise ValueError('修改超出所选字段范围')
            if target.unitIds:
                if field not in ('text','rationale') or op.get('unitId') not in target.unitIds:raise ValueError('修改超出所选内容单元范围')
                unit=next((u for u in data.get('units',[]) if u['id']==op.get('unitId')),None)
                if not unit or unit.get('locked'):raise ValueError('所选内容单元已锁定或不存在')
                if field=='text' and unit.get('text')!=op['value']:
                    unit['previousReferences']=copy.deepcopy(unit.get('references',[]));unit['references']=[];unit['category']='fiction'
                unit[field]=op['value']
                if data.get('type')=='narrative':data['content']='\n'.join(u['text'] for u in data['units'])
            else:
                if field not in FIELDS[self.kind]:raise ValueError('此字段不允许智能修改')
                if self.kind=='clue' and field=='content':
                    if data.get('type')!='narrative':raise ValueError('只有叙事线索支持情节改写')
                    if any(u.get('locked') for u in data.get('units',[])):raise ValueError('叙事情节已锁定，请先解锁')
                    replacement=ws.narrative_draft(dict(data,content=op['value']),copy.deepcopy(data))
                    row['draft']=data=replacement
                else:data[field]=op['value']
            if field in ('name','title','prompt') and not op['value'].strip():raise ValueError('名称或提示词不能为空')
            if self.kind=='character':self.sync_character(p,row,field)
            changed.add(row['id'])
        # Existing schema/ownership validation runs before any transaction writes.
        for rid in changed:
            row=rows[rid]
            issues=ws.validate_entity(p,p['workspace'],row)
            if issues and row.get('published') is not None:raise ValueError('；'.join(issues))
        return f'已修改 {len(changed)} 项所选内容；关联内容保留，可按提醒更新'

    @staticmethod
    def sync_character(p,row,field):
        value=p['workspace']['entities']['material:main']['draft'].get('structured')
        if not value:return
        person_ids={row['id']}|{person['id'] for person in value['people'] if person.get('characterId')==row['id']}
        for person in value['people']:
            if person.get('characterId')==row['id'] and field in ('name','summary'):
                person[field]=row['draft'][field];person['origin']='feedback'
        for statement in value['statements']:
            if statement.get('personId') in person_ids and statement.get('profileField')==field:
                statement.update(text=row['draft'][field],origin='feedback',category='uncertain',previousReferenceIds=statement.get('referenceIds',[]),referenceIds=[])
        structured.finish(value)


ADAPTERS={kind:EntityAdapter(kind) for kind in FIELDS}
