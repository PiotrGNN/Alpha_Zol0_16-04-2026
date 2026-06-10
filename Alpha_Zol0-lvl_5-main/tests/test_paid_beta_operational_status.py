from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from scripts import paid_beta_operational_status as status


class _Query:
    def __init__(self, value):
        self.value = value

    def order_by(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.value

    def count(self):
        return int(self.value)


class _Session:
    def __init__(self, latest_period, unprocessed, failed):
        self.values = iter((latest_period, unprocessed, failed))

    def query(self, model):
        return _Query(next(self.values))

    def close(self):
        return None


def test_missing_economics_and_scorecard_are_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(status, "SessionLocal", lambda: _Session(None, 0, 0))
    monkeypatch.setattr(
        status,
        "settings",
        SimpleNamespace(trading_scorecard_path=str(tmp_path / "missing.json")),
    )

    report = status.collect_status(now=datetime(2026, 6, 10, tzinfo=timezone.utc))

    assert report["status"] == "BLOCKED"
    assert "WEEKLY_ECONOMICS_MISSING" in report["blockers"]
    assert "FRESH_SCORECARD_MISSING" in report["blockers"]
    assert report["public_live_trading"] is False
    assert report["profitability_claim_allowed"] is False


def test_current_economics_and_scorecard_pass(monkeypatch, tmp_path):
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    latest = SimpleNamespace(period_end=date(2026, 6, 8))
    monkeypatch.setattr(status, "SessionLocal", lambda: _Session(latest, 0, 0))
    scorecard = tmp_path / "scorecard.json"
    scorecard.write_text(
        '{"metadata":{"generated_at":"2026-06-09T00:00:00+00:00"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        status,
        "settings",
        SimpleNamespace(trading_scorecard_path=str(scorecard)),
    )

    report = status.collect_status(now=now)

    assert report["status"] == "PASS"
    assert report["blockers"] == []
    assert report["latest_economics_period_end"] == "2026-06-08"


def test_pending_webhooks_failed_payments_and_stale_data_are_reported(monkeypatch, tmp_path):
    now = datetime(2026, 6, 10, tzinfo=timezone.utc)
    latest = SimpleNamespace(period_end=date(2026, 5, 20))
    monkeypatch.setattr(status, "SessionLocal", lambda: _Session(latest, 3, 2))
    scorecard = tmp_path / "scorecard.json"
    scorecard.write_text(
        '{"metadata":{"generated_at":"2026-05-01T00:00:00+00:00"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        status,
        "settings",
        SimpleNamespace(trading_scorecard_path=str(scorecard)),
    )

    report = status.collect_status(now=now)

    assert report["status"] == "BLOCKED"
    assert set(report["blockers"]) >= {
        "WEEKLY_ECONOMICS_STALE",
        "UNPROCESSED_WEBHOOKS_PRESENT",
        "FAILED_PAYMENTS_PRESENT",
        "SCORECARD_STALE",
    }
