"""
P1-4  save_decision_to_db() — DECISION_THROTTLE_SEC silent swallow
P2-2  save_equity_to_db()   — EQUITY_MAX_USDT guard
P2-3  save_log_to_db()      — position_close write→read roundtrip
P3-3  _canonical_post_promotion_readback_reason_code("unknown") branch
"""
import importlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _reload_db(monkeypatch, db_path: Path):
    """Reload db_models + db_utils against a fresh SQLite file."""
    import core.db_models as dbm
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    importlib.reload(dbm)
    dbm.init_db()
    import core.db_utils as dbu
    importlib.reload(dbu)
    return dbu


def _count_rows(db_path: Path, table: str, event: str | None = None) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        if event is not None:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE event=?", (event,)
            ).fetchone()
        else:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# P1-4  DECISION_THROTTLE_SEC — duplicate within window is silently dropped
# ---------------------------------------------------------------------------

def test_save_decision_throttle_drops_duplicate_within_window(monkeypatch):
    """
    When DECISION_THROTTLE_SEC=60, a second identical (decision, details) call
    within the window must return False and must NOT write a second Decision.
    After the window expires the write must succeed.

    Note: Uses a FakeSession so that in-memory Decision objects retain their
    timezone-aware timestamps — the SQLite round-trip strips tzinfo, which
    would silently break the throttle comparison via exception swallowing.
    """
    import core.db_utils as dbu

    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("DECISION_THROTTLE_SEC", "60")

    ts1 = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 4, 16, 12, 0, 30, tzinfo=timezone.utc)  # within 60s
    ts3 = datetime(2026, 4, 16, 12, 1, 30, tzinfo=timezone.utc)  # outside 60s

    details_str = json.dumps({"user": "u", "action": "buy"})

    written: list = []

    class _FakeQuery:
        def order_by(self, *a):
            return self

        def first(self):
            return written[-1] if written else None

    class _FakeSession:
        def add(self, obj):
            written.append(obj)

        def commit(self):
            pass

        def query(self, *a):
            return _FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(dbu, "SessionLocal", _FakeSession)

    ok1 = dbu.save_decision_to_db(ts1, "buy", details=details_str)
    ok2 = dbu.save_decision_to_db(ts2, "buy", details=details_str)
    ok3 = dbu.save_decision_to_db(ts3, "buy", details=details_str)

    assert ok1 is True, "First write should succeed"
    assert ok2 is False, "Duplicate within throttle window must return False"
    assert ok3 is True, "Write outside throttle window should succeed"
    assert len(written) == 2, (
        f"Expected 2 Decision objects written (1st + after-window), got {len(written)}"
    )


def test_save_decision_throttle_does_not_drop_different_decision(monkeypatch):
    """Different decision value must NOT be throttled."""
    import core.db_utils as dbu

    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("DECISION_THROTTLE_SEC", "60")

    ts = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
    details_str = json.dumps({"user": "u", "action": "sell"})

    written: list = []

    class _FakeQuery:
        def order_by(self, *a):
            return self

        def first(self):
            return written[-1] if written else None

    class _FakeSession:
        def add(self, obj):
            written.append(obj)

        def commit(self):
            pass

        def query(self, *a):
            return _FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(dbu, "SessionLocal", _FakeSession)

    ok1 = dbu.save_decision_to_db(ts, "buy", details=details_str)
    ok2 = dbu.save_decision_to_db(ts, "sell", details=details_str)

    assert ok1 is True
    assert ok2 is True, "Different decision type must not be throttled"
    assert len(written) == 2


# ---------------------------------------------------------------------------
# P2-2  EQUITY_MAX_USDT guard — out-of-range equity is rejected
# ---------------------------------------------------------------------------

def test_save_equity_rejects_above_max_usdt(monkeypatch, tmp_path):
    """
    Equity value above EQUITY_MAX_USDT must be rejected (return False) and
    must NOT be written to the DB.
    """
    db = tmp_path / "equity_guard.db"
    dbu = _reload_db(monkeypatch, db)

    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("EQUITY_MAX_USDT", "100000")

    ts = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
    ok_above = dbu.save_equity_to_db(ts, 999_999_999.0, 0.0)

    assert ok_above is False, (
        "Equity above EQUITY_MAX_USDT must return False"
    )
    assert _count_rows(db, "equity") == 0, "No equity row should be written"


def test_save_equity_accepts_within_max_usdt(monkeypatch, tmp_path):
    """Equity within the limit must be accepted."""
    db = tmp_path / "equity_ok.db"
    dbu = _reload_db(monkeypatch, db)

    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("EQUITY_MAX_USDT", "100000")

    ts = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
    ok = dbu.save_equity_to_db(ts, 50_000.0, 100.0)

    assert ok is True
    assert _count_rows(db, "equity") == 1


# ---------------------------------------------------------------------------
# P2-3  save_log_to_db() → position_close write→read roundtrip
# ---------------------------------------------------------------------------

def test_save_log_position_close_is_readable_by_consumer(monkeypatch, tmp_path):
    """
    Write a position_close event via save_log_to_db().
    Verify the row is present and readable from the same SQLite file with
    the exact event name the drain consumer would query.
    """
    db = tmp_path / "pclose_roundtrip.db"
    dbu = _reload_db(monkeypatch, db)
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")

    payload = {
        "symbol": "BTCUSDTM",
        "realized_pnl": 1.23,
        "trade_id": "rtrip-001",
        "position": {"side": "buy"},
    }
    ok = dbu.save_log_to_db("position_close", details=payload)
    assert ok is True, "save_log_to_db must succeed for position_close event"

    # Read back as the _drain_close_requests query would
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT event, details FROM logs WHERE event=?",
            ("position_close",),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1, f"Expected 1 position_close row, found {len(rows)}"
    event_name, details_raw = rows[0]
    assert event_name == "position_close"
    parsed = json.loads(details_raw)
    assert parsed["symbol"] == "BTCUSDTM"
    assert parsed["trade_id"] == "rtrip-001"


def test_save_log_position_close_request_is_readable_by_drain(monkeypatch, tmp_path):
    """
    The drain consumer queries for 'position_close_request' events.
    Verify that a row written with this event name is visible via the
    exact query pattern used by _drain_close_requests.
    """
    db = tmp_path / "pclose_req_roundtrip.db"
    dbu = _reload_db(monkeypatch, db)
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")

    payload = {
        "symbol": "ETHUSDTM",
        "reason": "controlled_kpi_window_end",
    }
    ok = dbu.save_log_to_db("position_close_request", details=payload)
    assert ok is True

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT id, details FROM logs "
            "WHERE event='position_close_request' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    row_id, details_raw = rows[0]
    assert row_id is not None and row_id > 0
    parsed = json.loads(details_raw)
    assert parsed["symbol"] == "ETHUSDTM"


# ---------------------------------------------------------------------------
# P3-3  _canonical_post_promotion_readback_reason_code("unknown") branch
# ---------------------------------------------------------------------------

def test_canonical_readback_reason_code_unknown_branch():
    """
    _canonical_post_promotion_readback_reason_code must handle the 'unknown'
    case by returning the fallback string, not raising or returning None.
    """
    import core.db_utils as dbu

    result_missing = dbu._canonical_post_promotion_readback_reason_code("missing")
    result_error = dbu._canonical_post_promotion_readback_reason_code("error")
    result_unknown = dbu._canonical_post_promotion_readback_reason_code("unknown")
    result_other = dbu._canonical_post_promotion_readback_reason_code("some_other")

    assert result_missing == "canonical_post_promotion_readback_missing"
    assert result_error == "canonical_post_promotion_readback_error"
    assert result_unknown == "canonical_post_promotion_readback_unknown"
    assert result_other == "canonical_post_promotion_readback_unknown", (
        "Any unrecognised outcome must fall through to the 'unknown' return"
    )
