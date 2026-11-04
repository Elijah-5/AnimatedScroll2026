import asyncio
from types import SimpleNamespace as NS
import pytest
from backend.llm_response import options,json_text,ModelResponseError
from backend import materials
from backend.domain import blank


def response(text=None,finish='stop',reasoning=None):
    return NS(model='deepseek',choices=[NS(message=NS(content=text,reasoning_content=reasoning),finish_reason=finish)],usage=NS(completion_tokens=6000,completion_tokens_details=NS(reasoning_tokens=6000)))


def test_deepseek_structured_options_disable_thinking(monkeypatch):
    monkeypatch.delenv('AIHUBMIX_THINKING',raising=False)
    o=options('deepseek-v4.1-flash-1017')
    assert o['extra_body']=={'thinking':{'type':'disabled'}}
    assert o['response_format']=={'type':'json_object'} and o['max_tokens']>=12000
    assert 'extra_body' not in options('gpt-4o')


def test_reasoning_only_is_not_parsed_as_script():
    with pytest.raises(ModelResponseError) as e:json_text(response('',reasoning='private reasoning'))
    assert e.value.code=='empty_response'
    assert 'private reasoning' not in str(e.value)


def test_truncated_and_empty_responses_have_distinct_errors():
    with pytest.raises(ModelResponseError) as e:json_text(response('',finish='length'))
    assert e.value.code=='truncated_response' and e.value.diagnostics['reasoningTokens']==6000
    with pytest.raises(ModelResponseError):json_text(NS(choices=[]))


def test_valid_fenced_json():assert json_text(response('```json\n{"ok": true}\n```'))=='{"ok": true}'


def test_empty_material_response_does_not_waste_repair_request(monkeypatch):
    calls=[]
    class Client:
        def __init__(self,**kw):self.chat=NS(completions=self)
        async def create(self,**kw):calls.append(kw);return response('')
        async def close(self):pass
    monkeypatch.setenv('AIHUBMIX_API_KEY','test-key');monkeypatch.setattr(materials,'AsyncOpenAI',Client)
    with pytest.raises(ModelResponseError,match='空内容'):asyncio.run(materials.organize(blank()))
    assert len(calls)==1
