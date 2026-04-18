# Invalid DB payloads must be rejected and logged as security events
import core.db_utils as dbu
from datetime import datetime, timezone


def test_invalid_details_skipped(monkeypatch):
    import security.zero_trust as zt

    events = []

    def fake_log_event(message):
        events.append(message)

    monkeypatch.setattr(zt, "log_event", fake_log_event)
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")

    assert dbu.save_decision_to_db(1234567890, "test", details="not-json") is False
    assert events == ["DB_WRITE_BLOCKED:DECISION:INVALID_PAYLOAD"]


def test_validation_subsystem_unavailable_blocks_write(monkeypatch):
    import security.zero_trust as zt

    events = []

    def fake_log_event(message):
        events.append(message)

    def fake_validate_input(_payload):
        raise RuntimeError("validator offline")

    monkeypatch.setattr(zt, "log_event", fake_log_event)
    monkeypatch.setattr(zt, "validate_input", fake_validate_input)
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")

    assert dbu.save_decision_to_db(1234567890, "test", details={"a": 1}) is False
    assert events == ["DB_WRITE_BLOCKED:DECISION:VALIDATION_SUBSYSTEM_UNAVAILABLE"]


def test_ms_to_datetime_rejects_boolean_timestamp():
    assert dbu.ms_to_datetime(True) is None
    assert dbu.ms_to_datetime(False) is None


def test_coerce_finite_float_rejects_invalid_inputs():
    assert dbu._coerce_finite_float(True) is None
    assert dbu._coerce_finite_float("not-a-number") is None
    assert dbu._coerce_finite_float(float("inf")) is None
    assert dbu._coerce_finite_float("12.5") == 12.5


def test_ms_to_datetime_handles_datetime_and_numeric_inputs():
    naive_dt = datetime(2024, 1, 1, 12, 0, 0)
    aware_dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    assert dbu.ms_to_datetime(naive_dt) == naive_dt.replace(tzinfo=timezone.utc)
    assert dbu.ms_to_datetime(aware_dt) == aware_dt
    assert dbu.ms_to_datetime(1700000000) == datetime.fromtimestamp(
        1700000000, tz=timezone.utc
    )
    assert dbu.ms_to_datetime(1700000000000) == datetime.fromtimestamp(
        1700000000000 / 1000.0, tz=timezone.utc
    )


def test_ms_to_datetime_handles_iso_and_numeric_strings():
    assert dbu.ms_to_datetime("2024-01-01T12:00:00") == datetime(
        2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc
    )
    assert dbu.ms_to_datetime("1700000000") == datetime.fromtimestamp(
        1700000000, tz=timezone.utc
    )
    assert dbu.ms_to_datetime("1700000000000") == datetime.fromtimestamp(
        1700000000000 / 1000.0, tz=timezone.utc
    )
    assert dbu.ms_to_datetime("not-a-timestamp") is None


def test_save_decision_rejects_boolean_timestamp_before_db_write(monkeypatch):
    import security.zero_trust as zt

    events = []

    def fake_log_event(message):
        events.append(message)

    def fake_session():
        raise AssertionError("SessionLocal should not be called for invalid timestamp")

    monkeypatch.setattr(zt, "log_event", fake_log_event)
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setattr(dbu, "SessionLocal", fake_session)

    assert dbu.save_decision_to_db(True, "test", details={"a": 1}) is False
    assert events == []


def test_save_equity_rejects_non_finite_pnl_before_db_write(monkeypatch):
    import security.zero_trust as zt

    events = []

    def fake_log_event(message):
        events.append(message)

    def fake_session():
        raise AssertionError("SessionLocal should not be called for invalid pnl")

    monkeypatch.setattr(zt, "log_event", fake_log_event)
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setattr(dbu, "SessionLocal", fake_session)

    assert dbu.save_equity_to_db(1234567890, 1000.0, float("nan")) is False
    assert events == []
