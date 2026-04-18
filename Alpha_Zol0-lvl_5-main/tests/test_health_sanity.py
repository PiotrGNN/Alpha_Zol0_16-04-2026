# Health endpoint should respond in offline mode
from fastapi.testclient import TestClient


def test_health_endpoint_ok_offline(monkeypatch):
    import api_status

    monkeypatch.setattr(api_status, "init_db", lambda: None)
    client = TestClient(api_status.app)
    resp = client.get("/")
    assert resp.status_code == 200


def test_api_health_uses_aggregated_runtime_wrapper(monkeypatch):
    import api_status

    monkeypatch.setattr(api_status, "init_db", lambda: None)
    monkeypatch.setattr(
        api_status,
        "health_check",
        lambda: {
            "status": "degraded",
            "api": True,
            "ticks": False,
            "bot": True,
        },
    )

    client = TestClient(api_status.app)
    resp = client.get("/api/health")

    assert resp.status_code == 200
    assert resp.json()["ticks"] is False
