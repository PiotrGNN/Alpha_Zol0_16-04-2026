import json
import sys
import types
from datetime import datetime, timezone

import utils.health_check as health_module


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"bad status: {self.status_code}")

    def json(self):
        return self._payload


def test_check_api_validates_payload(monkeypatch):
    fake_requests = types.SimpleNamespace(
        get=lambda *args, **kwargs: _FakeResponse({"code": "200000", "data": 123})
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    assert health_module.check_api() is True


def test_check_api_rejects_empty_payload(monkeypatch):
    fake_requests = types.SimpleNamespace(
        get=lambda *args, **kwargs: _FakeResponse({"code": "200000", "data": None})
    )
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    assert health_module.check_api() is False


def test_check_ticks_uses_recent_decision_log(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    log_dir = tmp_path / "autopsy"
    log_dir.mkdir()
    (log_dir / "decision_log.csv").write_text(
        f"{datetime.now(timezone.utc).isoformat()},decision\n",
        encoding="utf-8",
    )

    assert health_module.check_ticks() is True


def test_check_bot_status_uses_pid_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bot.pid").write_text("4321\n", encoding="utf-8")
    monkeypatch.setattr(health_module, "_pid_is_running", lambda pid: pid == 4321)

    assert health_module.check_bot_status() is True


def test_health_check_aggregates_checks_and_writes_log(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(health_module, "check_api", lambda *args, **kwargs: True)
    monkeypatch.setattr(health_module, "check_ticks", lambda *args, **kwargs: False)
    monkeypatch.setattr(health_module, "check_bot_status", lambda *args, **kwargs: True)

    payload = health_module.health_check()

    assert payload["status"] == "degraded"
    assert payload["api"] is True
    assert payload["ticks"] is False
    assert payload["bot"] is True
    logged = (tmp_path / "logs" / "health.log").read_text(encoding="utf-8")
    record = json.loads(logged.splitlines()[-1])
    assert record["checks"]["ticks"] is False
