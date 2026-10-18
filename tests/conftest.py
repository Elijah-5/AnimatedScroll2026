import pytest
from fastapi.testclient import TestClient
from backend import main

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    return TestClient(main.app)
