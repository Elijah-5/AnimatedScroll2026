from . import config
import copy
import json
import os
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from typing import Literal
from .domain import uid

MODEL = os.getenv('AIHUBMIX_MODEL', 'deepseek-v4.1-flash-1017')
PROMPT_VERSION = 'creation-v1'

class Reference(BaseModel):
    sourceId: str = ''
    sourceVersion: int = 1
    annotationId: str = ''
    quote: str

class Unit(BaseModel):
    text: str
    kind: Literal['event', 'action', 'dialogue', 'clue']
    category: Literal['supported', 'inference', 'fiction']
    speakerId: str = ''
    rationale: str = ''
    references: list[Reference] = Field(default_factory=list)

class Scene(BaseModel):
    title: str
    goal: str
    characterIds: list[str]
    connection: str

class Character(BaseModel):
    biography: str = ''
    summary: str = ''
    mentions: list[dict] = Field(default_factory=list)
    namingOrigin: str = 'legacy'
    name: str
    identity: str
    relationships: str
    knowledge: str = ''
    evidence: str

class Characters(BaseModel):
    characters: list[Character]

class Outline(BaseModel):
    scenes: list[Scene] = Field(min_length=1, max_length=12)

class Content(BaseModel):
    units: list[Unit] = Field(min_length=1)

class Finding(BaseModel):
    message: str

class Findings(BaseModel):
    checks: list[Finding]

SCHEMAS = {'extract': Characters, 'outline': Outline, 'scene': Content, 'classify': Content, 'rewrite': Content, 'check': Findings}

async def generate(task, project, scene_id='', unit_id='', instruction=''):
    if not os.getenv('AIHUBMIX_API_KEY'):
        raise ValueError('未配置 AIHUBMIX_API_KEY。请在本地后端环境配置后重启。')
    schema = SCHEMAS[task]
    system = '''你是古画创作助手。仅以用户提供的资料和已确认画面观察为依据，资料本身不代表真相。不得编造来源、引文或ID。输出严格JSON。区分supported有依据、inference解释推测、fiction虚构；事实和虚构拆成独立单元。dialogue单元text只放说话原句，不混入说话人称谓或动作；动作另列action单元。具体对白、心理、动机默认fiction，除非原文直接记录。inference必须说明推导。引用须带sourceId、sourceVersion及逐字quote，或annotationId及对应description。遵守历史边界；人物知识只使用已确认设定；按project.sceneCount生成连续故事。不要修改锁定内容。'''
    context=copy.deepcopy(project)
    inputs=project.get('materialInputs',{})
    if any(inputs.get(k,'').strip() for k in ('background','relationships','narrative')):
        context['storyMode']='已有历史叙事框架' if inputs.get('narrative','').strip() else '基于历史背景共创虚构叙事'
        messages_mode='已有叙事时保留输入的事件框架；未填写narrative时，生成的故事事件必须标为fiction，不能伪称为已有史料叙事。背景与人物身份仍可关联依据。'
        system += messages_mode
        context['sources']=[s for s in context['sources'] if s.get('method')=='material_input']
        if project.get('materialAnalysis',{}).get('stale') or project.get('materialAnalysis',{}).get('inputVersion') != inputs.get('version'):
            context['materialAnalysis']={}
            context['materialSegments']=[]
    if task != 'extract':
        context['sources']=[s for s in context['sources'] if s.get('confirmed',True) and s.get('sourceType')!='creative_intent']
        context['annotations']=[a for a in context['annotations'] if a.get('confirmed')]
        context['observations']=[o for o in context.get('observations',[]) if o.get('confirmed') and not o.get('stale')]
        context['matches']=[m for m in context.get('matches',[]) if m.get('confirmed')]
    prompt = json.dumps(dict(task=task, project=context, sceneId=scene_id, unitId=unit_id, instruction=instruction, outputSchema=schema.model_json_schema()), ensure_ascii=False)
    client = AsyncOpenAI(api_key=os.environ['AIHUBMIX_API_KEY'], base_url=os.getenv('AIHUBMIX_BASE_URL', 'https://aihubmix.com/v1'), timeout=90, max_retries=0)
    messages = [{'role':'system','content':system}, {'role':'user','content':prompt}]
    try:
        for attempt in range(2):
            result = await client.chat.completions.create(model=MODEL, messages=messages, max_tokens=6500, stream=False)
            raw = result.choices[0].message.content or ''
            try:
                value = schema.model_validate_json(raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()).model_dump()
                if task == 'outline' and len(value['scenes']) != project.get('sceneCount', 3):
                    raise ValueError('场景数量与sceneCount不一致')
                for key, rows in value.items():
                    for row in rows:
                        row['id'] = uid()
                        if key == 'units': row.update(status='pending', locked=False)
                        if key == 'characters': row['confirmed'] = False
                        if key == 'scenes': row['units'] = []
                        if key == 'checks': row['resolved'] = False
                if task == 'check' and not value['checks']:
                    value['checks'] = [dict(id=uid(), message='AI 未发现明显冲突；请人工确认历史边界和连贯性。', resolved=False)]
                return value
            except (ValueError, TypeError) as exc:
                if attempt: raise ValueError('模型输出格式校验失败，原稿未改变') from exc
                messages += [{'role':'assistant','content':raw}, {'role':'user','content':'输出未通过校验，请按原JSON schema修复。错误：' + str(exc)[:1500]}]
    finally:
        await client.close()
