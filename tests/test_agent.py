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
