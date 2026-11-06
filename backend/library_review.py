"""Evidence-linked reading projections and narrowly defined source contradictions."""
import copy
import re
from pydantic import BaseModel, Field
from .task_runtime import digest

SECTIONS = {'artwork': '作品档案', 'people': '人物候选', 'relations': '人物关系',
            'events': '历史背景与事件', 'research': '研究判断', 'sources': '来源概况'}


def brief(text, limit=180):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    sentences = re.split(r'(?<=[。！？])', text)
    out = ''
    for sentence in sentences:
        if out and len(out + sentence) > limit:
            break
        out += sentence
        if len(out) >= limit:
            break
    return out if len(out) <= limit else out[:limit] + '…'


def active_conflicts(value):
    return [c for c in value.get('conflicts', []) if c.get('kind') == 'contradiction'
            and c.get('status')!='retired' and c.get('resolution') not in ('current', 'candidate')]


def summaries(value):
    """Derived excerpts, not another independently editable version of the facts."""
    blocks = {}
    artwork = value['artwork']
    for section, label in SECTIONS.items():
        if section == 'artwork':
            rows = [dict(id=k, text=v['value'], referenceIds=v.get('referenceIds', []))
                    for k, v in artwork.items() if v.get('value')]
            text = '；'.join(f'{name}：{artwork[key]["value"]}' for key, name in
                            [('artist', '作者'), ('period', '绘画年代'), ('storyPeriod', '故事时代')]
                            if artwork.get(key, {}).get('value'))
            story = artwork.get('storyOneLiner', {}).get('value') or artwork.get('description', {}).get('value')
            text = '。'.join(filter(None, [text, brief(story)]))
        else:
            rows = value.get(section, [])
            if section == 'people':
                main = [r for r in rows if r.get('scope') == 'depicted' or r.get('characterId')]
                text = f'{len(rows)} 位资料人物，{len(main)} 位画中人物候选。'
                text += '、'.join(r['name'] for r in (main or rows)[:6])
            elif section == 'relations':
                names = {r['id']: r['name'] for r in value['people']}
                text = '；'.join(f'{names.get(r["fromId"], "未知")} → {r["label"]} → {names.get(r["toId"], "未知")}' for r in rows[:3])
            elif section == 'sources':
                documents = {s.get('documentId') or s['id'] for s in rows}
                text = f'{len(documents)} 个来源，{len(value["evidence"])} 处逐字依据。'
            else:
                text = '；'.join(brief(r.get('text', ''), 90) for r in rows[:2])
        fingerprint = digest(rows)
        cached = value.get('summaryOverrides', {}).get(section, {})
        # A model may compress a module during explicit feedback. Never keep it
        # after the underlying rows change.
        if cached.get('inputHash') == fingerprint and cached.get('origin') == 'feedback':
            blocks[section] = copy.deepcopy(cached)
        else:
            blocks[section] = dict(label=label, text=brief(text, 260) or '现有资料尚未提供。',
                                   itemIds=[r['id'] for r in rows],
                                   referenceIds=list(dict.fromkeys(ref for r in rows for ref in r.get('referenceIds', []))),
                                   inputHash=fingerprint, origin='projection')
    return blocks


def refresh(value):
    value['summaryBlocks'] = summaries(value)
    value.setdefault('personRedirects', {})
    return value


class Alternative(BaseModel):
    value: str = Field(min_length=1, max_length=4000)
    referenceIds: list[str] = Field(min_length=1, max_length=20)


class Contradiction(BaseModel):
    field: str
    context: str = Field(min_length=1, max_length=800)
    reason: str = Field(min_length=1, max_length=1000)
    alternatives: list[Alternative] = Field(min_length=2, max_length=2)


def install_contradictions(value, rows):
    from .structured import stable
    known = {e['id']: e for e in value['evidence']}
    targets = {'artwork.' + k for k in value['artwork']}
    for section in ('people', 'events', 'relations', 'statements', 'research'):
        for row in value[section]:
            targets.update(section + '.' + row['id'] + '.' + field for field in
                           ('name', 'summary') if section == 'people')
            if section!='people':targets.add(section + '.' + row['id'] + ('.label' if section == 'relations' else '.text'))
    decisions = {c['id']: c for c in value.get('conflicts', [])}
    for item in rows:
        c = Contradiction.model_validate(item).model_dump()
        a, b = c['alternatives']
        if c['field'] not in targets or a['value'].strip() == b['value'].strip():
            continue
        refs = set(a['referenceIds'] + b['referenceIds'])
        if not refs <= known.keys():
            raise ValueError('争议引用了不存在的依据')
        # Distinct assertions need distinct evidence. A single ambiguous passage
        # is uncertainty, not two irreconcilable source accounts.
        if set(a['referenceIds']) == set(b['referenceIds']):
            continue
        key = stable('contradiction', [c['field'], c['context'], sorted([a['value'], b['value']])])
        row = dict(c, id=key, kind='contradiction', current=a['value'], candidate=b['value'],
                   referenceIds=b['referenceIds'], currentReferenceIds=a['referenceIds'])
        old = decisions.get(key)
        if old and old.get('alternatives') == row['alternatives']:
            for field in ('resolution', 'decision'):
                if field in old: row[field] = old[field]
        decisions[key] = row
    value['conflicts'] = list(decisions.values())
    return refresh(value)


def conflict_context(value):
    """Compact cross-source claims including both old and newly extracted values."""
    rows = []
    for k, cell in value['artwork'].items():
        if cell.get('value'):
            rows.append(dict(field='artwork.' + k, text=cell['value'], referenceIds=cell.get('referenceIds', [])))
    for kind in ('people', 'events', 'statements', 'relations', 'research'):
        for row in value[kind]:
            field = 'name' if kind == 'people' else 'label' if kind == 'relations' else 'text'
            rows.append(dict(field=kind + '.' + row['id'] + '.' + field,
                             text=row.get(field, ''), referenceIds=row.get('referenceIds', [])))
    for c in value.get('conflicts', []):
        if c.get('kind') != 'contradiction':
            rows.append(dict(field=c['field'], text=c.get('candidate', ''), referenceIds=c.get('referenceIds', [])))
    return rows
