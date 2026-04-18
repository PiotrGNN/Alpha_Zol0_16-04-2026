# Health endpoint should respond in offline mode
from fastapi.testclient import TestClient


def test_health_endpoint_ok_offline(monkeypatch):
    import api_status

    monkeypatch.setattr(api_status, "init_db", lambda: None)
    client = TestClient(api_status.app)
    resp = client.get("/")
    assert resp.status_code == 200
