# Test DB write does not crash when SessionLocal is unavailable
import core.db_utils as dbu


def test_db_disabled_does_not_crash(monkeypatch):
    # Simulate SessionLocal raising on instantiation
    def fake_session():
        raise Exception("DB unavailable")

    monkeypatch.setattr(dbu, "SessionLocal", fake_session)
    ok = dbu.save_decision_to_db(
        1234567890,
        "test",
        details={"user": "u", "action": "test"},
    )
    assert ok is False
    ok2 = dbu.save_equity_to_db(1234567890, 1000.0, 0.0)
    assert ok2 is False
    ok3 = dbu.save_log_to_db("event", details="details")
    assert ok3 is False
