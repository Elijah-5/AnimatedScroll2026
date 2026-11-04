import asyncio
import copy
import json
from types import SimpleNamespace as N
from backend import studio_agent


def test_history_inference_id_cannot_masquerade_as_annotation(monkeypatch):
    good=dict(clues=[dict(name='线索',summary='论文描述',characterIds=[],units=[dict(text='原文',kind='clue',category='supported',references=[dict(sourceId='source',sourceVersion=1,quote='原文')])])])
    bad=copy.deepcopy(good);bad['clues'][0]['units'][0]['references'].append(dict(annotationId='invented',quote='history-inference-id'))
    replies=[bad,good];calls=[]
    class Fake:
        def __init__(self,**kwargs):self.chat=N(completions=N(create=self.create))
        async def create(self,**kwargs):
            calls.append(kwargs);value=replies.pop(0)
            return N(choices=[N(message=N(content=json.dumps(value,ensure_ascii=False)),finish_reason='stop')],model='test')
        async def close(self):pass
    monkeypatch.setenv('AIHUBMIX_API_KEY','test-only');monkeypatch.setattr(studio_agent,'AsyncOpenAI',Fake)
    context=dict(characters=[],sources=[dict(id='source',version=1,text='原文')],material=dict(annotations=[]))
    result=asyncio.run(studio_agent.run('culture',context))
    assert len(calls)==2 and len(result['clues'][0]['units'][0]['references'])==1


def test_knowledge_short_aliases_resolve_only_to_supplied_ids(monkeypatch):
    class Fake:
        def __init__(self,**kwargs):self.chat=N(completions=N(create=self.create))
        async def create(self,**kwargs):return N(choices=[N(message=N(content=json.dumps(dict(assignments=[dict(characterId='P1',clueIds=['L1'],reason='参与此事')]))),finish_reason='stop')],model='test')
        async def close(self):pass
    monkeypatch.setenv('AIHUBMIX_API_KEY','test-only');monkeypatch.setattr(studio_agent,'AsyncOpenAI',Fake)
    context=dict(characters=[dict(id='person-stable',name='甲')],clues=[dict(id='clue-stable',name='线索')])
    result=asyncio.run(studio_agent.run('knowledge',context))
    assert result['assignments'][0]['characterId']=='person-stable' and result['assignments'][0]['clueIds']==['clue-stable']
