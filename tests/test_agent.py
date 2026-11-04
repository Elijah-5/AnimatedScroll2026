from types import SimpleNamespace
import asyncio
import pytest
from backend import agent
from backend.sample import sample

class FakeClient:
    replies = []
    calls = 0
    def __init__(self,**kwargs):
        self.chat=SimpleNamespace(completions=self)
    async def create(self,**kwargs):
        FakeClient.calls+=1
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.replies.pop(0)))])
    async def close(self): pass


def test_format_repair_once(monkeypatch):
    monkeypatch.setenv('AIHUBMIX_API_KEY','test-key')
    monkeypatch.setattr(agent,'AsyncOpenAI',FakeClient)
    FakeClient.calls=0;FakeClient.replies=['invalid','{"characters":[]}']
    assert asyncio.run(agent.generate('extract',sample()))=={'characters':[]}
    assert FakeClient.calls==2


def test_format_failure_limited(monkeypatch):
    monkeypatch.setenv('AIHUBMIX_API_KEY','test-key')
    monkeypatch.setattr(agent,'AsyncOpenAI',FakeClient)
    FakeClient.calls=0;FakeClient.replies=['invalid','invalid']
    with pytest.raises(ValueError):asyncio.run(agent.generate('extract',sample()))
    assert FakeClient.calls==2


def test_missing_key(monkeypatch):
    monkeypatch.delenv('AIHUBMIX_API_KEY',raising=False)
    with pytest.raises(ValueError,match='AIHUBMIX_API_KEY'):asyncio.run(agent.generate('extract',sample()))


@pytest.mark.parametrize('kind', ['plot_clues','plots'])
def test_narrative_generation_accepts_one_paragraph_without_units(monkeypatch,kind):
    import json
    from backend import studio_agent
    monkeypatch.setenv('AIHUBMIX_API_KEY','test-key');monkeypatch.setattr(studio_agent,'AsyncOpenAI',FakeClient)
    clue=dict(name='进谏前',content='朱云走到殿前，准备向皇帝陈述。')
    payload=dict(clues=[clue]) if kind=='plot_clues' else dict(plots=[dict(title='进谏',goal='呈现冲突',body='剧情内容',characterIds=[],clues=[clue])])
    FakeClient.calls=0;FakeClient.replies=[json.dumps(payload,ensure_ascii=False)]
    result=asyncio.run(studio_agent.run(kind,dict(intent=dict(plotCount=1),characters=[],targetPlot=dict(id='p',title='进谏'))))
    actual=result['clues'][0] if kind=='plot_clues' else result['plots'][0]['clues'][0]
    assert actual==clue and FakeClient.calls==1
