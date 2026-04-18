# Control endpoints must require token
from fastapi.testclient import TestClient


def test_control_routes_require_token(monkeypatch):
    import api_status

    # Avoid real DB init during startup
    monkeypatch.setattr(api_status, "init_db", lambda: None)
    monkeypatch.delenv("ZOL0_TOKEN", raising=False)

    client = TestClient(api_status.app)
    control_routes = []
    for route in api_status.app.routes:
        path = getattr(route, "path", "")
        if any(p in path for p in ("/start", "/stop", "/arm", "/config")):
            control_routes.append(route)

    assert control_routes, "No control routes found in api_status.py"

    for route in control_routes:
        methods = getattr(route, "methods", set())
        if "POST" in methods:
            resp = client.post(route.path)
        else:
            resp = client.get(route.path)
        assert resp.status_code in (401, 403)
