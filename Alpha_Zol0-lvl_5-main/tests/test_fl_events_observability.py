from fastapi.testclient import TestClient
from api_status import app


def test_fl_events_endpoint():
    client = TestClient(app)
    resp = client.get("/fl_events?limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        ev = data[0]
        assert "timestamp" in ev
        assert ev["event"] == "fl_round"
        assert "details" in ev
        # details should be JSON-parseable
        import json

        try:
            d = json.loads(ev["details"])
            assert "symbol" in d or "model" in d or "global_model" in d
        except Exception:
            assert False, "details not JSON-parseable"
