# DB writes must be blocked without token
import core.db_utils as dbu


def test_db_write_blocked_without_token(monkeypatch):
    import security.zero_trust as zt

    events = []

    def fake_log_event(msg):
        events.append(msg)

    monkeypatch.setattr(zt, "log_event", fake_log_event)
    monkeypatch.delenv("ZOL0_TOKEN", raising=False)

    assert dbu.save_decision_to_db(1234567890, "test", details={"a": 1}) is False
    assert dbu.save_equity_to_db(1234567890, 1000.0, 0.0) is False
    assert dbu.save_log_to_db("event", details="details") is False
    assert events == [
        "DB_WRITE_BLOCKED:DECISION:UNAUTHORIZED",
        "DB_WRITE_BLOCKED:EQUITY:UNAUTHORIZED",
        "DB_WRITE_BLOCKED:LOG:UNAUTHORIZED",
    ]
