import copy
import uuid


def uid():
    return uuid.uuid4().hex[:12]


def blank():
    return dict(id=uid(), version=1, title='未命名项目', materialInputs=dict(background='',relationships='',narrative='',version=1), materialSegments=[], materialAnalysis={}, sceneCount=3, imageVersion=0, documents=[], observations=[], matches=[], sources=[], characters=[], annotations=[], image='', intent=dict(theme='', audience='博物馆普通观众', tone='克制、生动', goal='', fixed='', allowed='对白、过渡动作', forbidden='无依据的真实人物经历'), scenes=[], outlineConfirmed=False, checks=[])


def citation_errors(unit, project):
    errors = []
    inputs=project.get('materialInputs',{})
    if any(inputs.get(k,'').strip() for k in ('background','relationships','narrative')) and not inputs.get('narrative','').strip() and unit['kind']=='event' and unit['category']=='supported':
        errors.append('未提供已有历史叙事，新增故事事件须标为虚构；背景事实请单独表达')
    refs = unit.get('references', [])
    for ref in refs:
        source = next((s for s in project['sources'] if s['id'] == ref.get('sourceId')), None)
        annotation = next((a for a in project['annotations'] if a['id'] == ref.get('annotationId')), None)
        if source:
            if source.get('sourceType') == 'creative_intent':
                errors.append('创作设想不能作为历史依据')
            if source.get('confirmed') is False:
                errors.append('资料提取结果尚未人工确认')
            if not ref.get('quote') or ref['quote'] not in source['text'] or ref.get('sourceVersion') != source['version']:
                errors.append('引用原文不存在或资料版本已变化')
        elif not (annotation and annotation.get('confirmed') and ref.get('quote') == annotation.get('description')):
            errors.append('引用不存在或画面观察未确认')
    if unit['category'] in ('supported', 'inference') and not refs:
        errors.append('有依据／推测内容必须关联依据')
    if unit['category'] == 'inference' and not unit.get('rationale'):
        errors.append('推测需要解释推导过程')
    if unit['kind'] == 'dialogue' and unit['category'] == 'supported' and not any(unit['text'] in r.get('quote', '') for r in refs):
        errors.append('对白不能仅凭人物背景标为有依据；需要逐字记录依据')
    return errors


def units(project):
    return [u for s in project['scenes'] for u in s.get('units', [])]


def reconcile(old, new):
    new = copy.deepcopy(new)
    from .materials import synchronize
    material_changed=synchronize(old,new)
    if material_changed:
        for match in new.get('matches',[]):match['confirmed']=False;match['stale']=True
        for a in new['annotations']:a['identityConfirmed']=False;a['needsReview']=True
    from .people import invalidate
    invalidate(old,new)
    prior_annotations={a['id']:a for a in old['annotations']}
    moved={a['id'] for a in new['annotations'] if a['id'] in prior_annotations and any(a.get(k)!=prior_annotations[a['id']].get(k) for k in ('x','y','w','h'))}
    present={a['id'] for a in new['annotations']}
    new['observations']=[o for o in new.get('observations',[]) if o.get('annotationId') in present]
    new['matches']=[m for m in new.get('matches',[]) if m.get('annotationId') in present]
    for a in new['annotations']:
        if a['id'] in moved:a['confirmed']=False;a['identityConfirmed']=False;a['needsReview']=True
    for obs in new.get('observations',[]):
        if obs.get('annotationId') in moved:obs['confirmed']=False;obs['stale']=True
    for match in new.get('matches',[]):
        if match.get('annotationId') in moved:match['confirmed']=False;match['stale']=True
    old_sources = {s['id']: s for s in old['sources']}
    for source in new['sources']:
        previous = old_sources.get(source['id'])
        source['version'] = previous.get('version', 1) + (source != previous) if previous else 1
    before = {u['id']: u for u in units(old)}
    after_ids = {u['id'] for u in units(new)}
    if any(u.get('locked') and u['id'] not in after_ids for u in units(old)):
        raise ValueError('不能删除锁定单元，请先解锁')
    changed = False
    scene_changed = [{k:v for k,v in s.items() if k != 'units'} for s in old['scenes']] != [{k:v for k,v in s.items() if k != 'units'} for s in new['scenes']]
    context_changed = material_changed or any(old.get(k) != new.get(k) for k in ('intent', 'characters', 'annotations', 'sceneCount', 'observations', 'matches')) or old['sources'] != new['sources'] or scene_changed
    for unit in units(new):
        previous = before.get(unit['id'])
        if previous:
            content_changed = any(previous.get(k) != unit.get(k) for k in ('text', 'category', 'references', 'rationale', 'kind', 'speakerId'))
            if previous.get('locked') and content_changed:
                raise ValueError('请先单独解锁，再修改内容')
            if content_changed or context_changed:
                unit['status'] = 'pending'
                changed = True
        else:
            unit['status'] = 'pending'
            changed = True
        if unit.get('status') == 'approved':
            errors = citation_errors(unit, new)
            if errors:
                raise ValueError('；'.join(errors))
    if changed or context_changed or set(before) != after_ids:
        new['checks'] = []
        new['reviewNotice'] = '内容或上下文已变化，请复核相关单元及跨场景连贯性。'
    if scene_changed or any(old.get(k) != new.get(k) for k in ('intent', 'characters', 'sources', 'annotations', 'sceneCount', 'observations', 'matches')):
        new['outlineConfirmed'] = False
    return new


def validate(project):
    issues = []
    ids = set()
    characters = {c['id'] for c in project['characters']}
    for collection in (project['sources'], project['characters'], project['annotations'], project['scenes'], units(project)):
        for item in collection:
            if item['id'] in ids:
                issues.append('重复 ID: ' + item['id'])
            ids.add(item['id'])
    for scene in project['scenes']:
        if any(c not in characters for c in scene.get('characterIds', [])):
            issues.append('场景存在无效人物引用')
    for unit in units(project):
        issues += [unit['id'] + ': ' + e for e in citation_errors(unit, project)]
        if unit.get('speakerId') and unit['speakerId'] not in characters:
            issues.append('无效说话人物')
        if unit.get('status') != 'approved':
            issues.append(unit['id'] + ': 尚未批准')
    if len(project['scenes']) != project.get('sceneCount', 3) or any(not s.get('units') for s in project['scenes']):
        issues.append('需要完成设定数量的场景正文')
    if not project['characters']:
        issues.append('缺少人物')
    if not project['scenes'] or not units(project):
        issues.append('故事尚未生成')
    if any(not c.get('confirmed') for c in project['characters']):
        issues.append('人物尚未确认')
    if not project.get('outlineConfirmed'):
        issues.append('大纲尚未确认')
    if not project.get('checks'):
        issues.append('请运行一致性检查并确认结果')
    for issue in project.get('checks', []):
        if not issue.get('resolved'):
            issues.append('检查建议尚未处理: ' + issue['message'])
    return issues
