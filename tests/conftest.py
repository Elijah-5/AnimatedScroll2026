import pytest
from fastapi.testclient import TestClient
from backend import main

@pytest.fixture(autouse=True)
def isolate_config(monkeypatch):
    monkeypatch.setenv('CREATION_DB_BACKEND','sqlite')
    monkeypatch.setenv('MODEL_PROVIDER','aihubmix')
    monkeypatch.setenv('CREATION_SEED_LATEST','0')
    from backend import structured
    async def local_structured(context):return structured.Suggestion().model_dump()
    monkeypatch.setattr(structured,'ask',local_structured)

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    return TestClient(main.app)
