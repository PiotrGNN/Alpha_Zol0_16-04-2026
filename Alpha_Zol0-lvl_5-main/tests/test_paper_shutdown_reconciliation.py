"""
P1-1  _paper_force_close_open_positions()  — force-close completeness
P1-2  _drain_close_requests()              — DB-queue → position close bridge
P2-1  close_lifecycle state machine        — attempt → failed → success
P2-6  Multi-position PAPER shutdown        — both positions closed
"""
import importlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path, rows: list[tuple]) -> Path:
    """Build a minimal SQLite DB with logs + decisions + equity tables."""
    db = tmp_path / "test_paper.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE logs "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT NOT NULL, event TEXT NOT NULL, details TEXT)"
    )
    conn.execute(
        "CREATE TABLE decisions "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT NOT NULL, decision TEXT NOT NULL, details TEXT)"
    )
    conn.execute(
        "CREATE TABLE equity "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT NOT NULL, equity REAL NOT NULL, pnl REAL NOT NULL)"
    )
    ts = datetime.now(timezone.utc).isoformat()
    for event, payload in rows:
        conn.execute(
            "INSERT INTO logs(timestamp, event, details) VALUES(?,?,?)",
            (ts, event, json.dumps(payload)),
        )
    conn.commit()
    conn.close()
    return db


def _count_event(db: Path, event_name: str) -> int:
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM logs WHERE event=?", (event_name,)
        ).fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


def _read_events(db: Path, event_name: str) -> list[dict]:
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT details FROM logs WHERE event=? ORDER BY id",
            (event_name,),
        ).fetchall()
        return [json.loads(r[0]) for r in rows if r[0]]
    finally:
        conn.close()


def _insert_raw_log_rows(db: Path, rows: list[tuple[str, str]]) -> None:
    conn = sqlite3.connect(str(db))
    try:
        ts = datetime.now(timezone.utc).isoformat()
        for event, raw_details in rows:
            conn.execute(
                "INSERT INTO logs(timestamp, event, details) VALUES(?,?,?)",
                (ts, event, raw_details),
            )
        conn.commit()
    finally:
        conn.close()


def _patch_botcore_symbols(monkeypatch, symbols: list[str]):
    """Patch BotCore load_config so test symbols are deterministic."""
    import core.BotCore as botcore
    from utils.config_loader import load_config as _real_load_config

    def _patched_load_config(path):
        cfg = _real_load_config(path)
        cfg = dict(cfg or {})
        cfg["market_type"] = "futures"
        cfg["symbols"] = list(symbols)
        if symbols:
            cfg["symbol"] = symbols[0]
        return cfg

    monkeypatch.setattr(botcore, "load_config", _patched_load_config)
    return botcore


def _capture_infinity_events(monkeypatch):
    """Capture InfinityLayerLogger.log events for deterministic assertions."""
    import core.InfinityLayerLogger as ill

    captured: list[tuple[str, dict]] = []
    original_log = ill.InfinityLayerLogger.log

    def _patched_log(self, event, details=None):
        payload = details if isinstance(details, dict) else {}
        captured.append((str(event), payload))
        return original_log(self, event, details)

    monkeypatch.setattr(ill.InfinityLayerLogger, "log", _patched_log)
    return captured


# ---------------------------------------------------------------------------
# P1-1  _paper_force_close_open_positions — single open position is force-closed
# ---------------------------------------------------------------------------

def test_paper_force_close_open_positions_closes_single_position(
    monkeypatch, tmp_path
):
    """
    Run bot (simulate=True, PAPER_RUN_ONCE=1) with one open position already in
    PositionManager before the force-close path fires.  Verify:
    - position is moved to closed list
    - position_close event is emitted to DB
    - _positions_map is empty after exit
    """
    db_path = _make_db(tmp_path, [])

    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("PAPER_FORCE_CLOSE_ON_EXIT", "1")

    # Track PM state via side-effect on PositionManager
    from core.PositionManager import PositionManager as _PM

    captured_pm: list[_PM] = []
    original_pm_init = _PM.__init__

    def patched_pm_init(self):
        original_pm_init(self)
        # Seed one open position
        self._positions_map["ETHUSDTM"] = {
            "symbol": "ETHUSDTM",
            "side": "buy",
            "amount": 0.001,
            "entry_price": 90000.0,
            "trade_id": "test-trade-001",
            "strategy": "TrendFollowing",
        }
        self.positions = list(self._positions_map.values())
        captured_pm.append(self)

    monkeypatch.setattr(_PM, "__init__", patched_pm_init)

    import requests

    def _block_net(*a, **k):
        raise AssertionError("no net")

    monkeypatch.setattr(requests, "get", _block_net)
    monkeypatch.setattr(requests, "post", _block_net)

    try:
        import utils.news_social_scheduler as nss
        monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    except Exception:
        pass

    import core.db_models as dbm
    importlib.reload(dbm)

    botcore = _patch_botcore_symbols(monkeypatch, ["ETHUSDTM"])
    botcore.run_bot(simulate=True)

    assert captured_pm, "PositionManager never instantiated"
    pm = captured_pm[-1]
    # Explicit shutdown reconciliation invariants
    assert pm.get_position("ETHUSDTM") is None, (
        "Target symbol must be closed by force-close on run-once exit"
    )
    assert any(
        p.get("symbol") == "ETHUSDTM" and p.get("trade_id") == "test-trade-001"
        for p in pm.closed
    ), "Closed ledger must contain the target forced-close position"
    assert _count_event(db_path, "position_close") >= 1
    close_events = _read_events(db_path, "position_close")
    target_events = [
        e
        for e in close_events
        if str(e.get("symbol") or "").upper() == "ETHUSDTM"
    ]
    assert target_events, "DB logs must contain position_close for target symbol"
    assert any(
        str(e.get("exit_reason") or "") == "paper_run_once_force_close"
        for e in target_events
    ), "Target close event must record paper_run_once_force_close exit reason"
    assert any(
        str(e.get("reason") or "") == "paper_run_once_force_close"
        and str(e.get("close_reason") or "") == "paper_run_once_force_close"
        and str(e.get("exit_owner") or "") == "run_end_cleanup_exit"
        and str(e.get("exit_reason_source") or "") == "position_payload_exit_reason"
        for e in target_events
    ), "Target close event must carry deterministic close reason and owner"


# ---------------------------------------------------------------------------
# P1-2  _drain_close_requests — DB position_close_request row drives close
# ---------------------------------------------------------------------------

def test_drain_close_requests_processes_db_request_and_closes_position(
    monkeypatch, tmp_path
):
    """
    Pre-seed DB with position_close_request for BTCUSDTM.
    Run bot with PAPER_RUN_ONCE=1.  Drain should pick up the request and
    close the position tracked in PositionManager.
    position_close event should appear in DB logs.
    """
    db_path = _make_db(
        tmp_path,
        [
            (
                "position_close_request",
                {
                    "symbol": "ETHUSDTM",
                    "reason": "controlled_kpi_window_end",
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        ],
    )

    monkeypatch.setenv("USE_MOCK", "0")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "0")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("PAPER_RUN_CYCLES", "0")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("PAPER_FORCE_CLOSE_ON_EXIT", "0")

    # Deterministic offline seams: no network, stable candles and ticker.
    from core.MarketDataFetcher import MarketDataFetcher
    from core.kucoin_futures_client import KucoinFuturesClient

    def _fake_ohlcv(self, symbol, interval, limit=120):
        ts = int(time.time())
        n = max(3, int(limit))
        return [
            {
                "timestamp": ts - (n - i) * 60,
                "open": 100.0 + i,
                "high": 100.5 + i,
                "low": 99.5 + i,
                "close": 100.2 + i,
                "volume": 1000.0,
            }
            for i in range(n)
        ]

    monkeypatch.setattr(MarketDataFetcher, "get_ohlcv", _fake_ohlcv)
    monkeypatch.setattr(
        KucoinFuturesClient,
        "get_ticker",
        lambda self, symbol: {"price": 123.45, "last": 123.45},
    )

    from core.PositionManager import PositionManager as _PM

    captured_pm: list[_PM] = []
    original_pm_init = _PM.__init__

    def patched_pm_init(self):
        original_pm_init(self)
        self._positions_map["ETHUSDTM"] = {
            "symbol": "ETHUSDTM",
            "side": "buy",
            "amount": 0.001,
            "entry_price": 90000.0,
            "trade_id": "drain-test-001",
            "strategy": "TrendFollowing",
        }
        self.positions = list(self._positions_map.values())
        captured_pm.append(self)

    monkeypatch.setattr(_PM, "__init__", patched_pm_init)

    events = _capture_infinity_events(monkeypatch)

    try:
        import utils.news_social_scheduler as nss
        monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    except Exception:
        pass

    import core.db_models as dbm
    importlib.reload(dbm)

    botcore = _patch_botcore_symbols(monkeypatch, ["ETHUSDTM"])
    botcore.run_bot(simulate=True)

    assert captured_pm, "PositionManager never instantiated"
    pm = captured_pm[-1]
    # Explicit drain invariants for the requested trade_id.
    # A new position may be reopened later on the same symbol during the run,
    # so we assert closure by trade identity rather than symbol emptiness.
    assert any(
        p.get("symbol") == "ETHUSDTM" and p.get("trade_id") == "drain-test-001"
        for p in pm.closed
    ), "Closed ledger must contain drained close-request position"
    assert all(
        str(p.get("trade_id") or "") != "drain-test-001"
        for p in pm._positions_map.values()
    ), "Requested trade_id must not remain in open positions after drain"
    assert _count_event(db_path, "position_close_request") == 1
    assert any(
        name == "close_drain_stage"
        and str(payload.get("trade_id") or "") == "drain-test-001"
        for name, payload in events
    ), "Drain diagnostics must be emitted for the requested trade"
    assert any(
        name == "position_close"
        and str(payload.get("symbol") or "").upper() == "ETHUSDTM"
        and str((payload.get("position") or {}).get("trade_id") or "")
        == "drain-test-001"
        and str(payload.get("exit_reason") or "").strip() != ""
        and str(payload.get("close_reason") or "").strip() != ""
        for name, payload in events
    ), "position_close from drain path must carry deterministic exit_reason/close_reason"


# ---------------------------------------------------------------------------
# P2-1  close_lifecycle state machine — _finalize_close_lifecycle_state helpers
# ---------------------------------------------------------------------------

def test_close_lifecycle_attempt_count_increments_correctly():
    """
    _finalize_close_lifecycle_state is already covered.
    This test validates the surrounding state-machine lifecycle:
    - state starts with close_attempt_count=0
    - after mark_attempt it becomes 1
    - after mark_failed the block_code is recorded and in_flight=False
    - after mark_success the key is removed from active_state
    """
    from core.BotCore import _finalize_close_lifecycle_state

    active = {
        "trade:sm-001": {
            "trade_id": "sm-001",
            "symbol": "ETHUSDTM",
            "close_requested_at": None,
            "close_in_flight": False,
            "close_last_attempt_ts": None,
            "close_attempt_count": 0,
            "last_selected_reason": None,
            "last_block_code": None,
        }
    }
    terminal = {}

    # Simulate mark_attempt (inline — closures not importable, replicate logic)
    now_ts = float(time.time())
    state = active["trade:sm-001"]
    state["close_in_flight"] = True
    state["close_requested_at"] = now_ts
    state["close_last_attempt_ts"] = now_ts
    state["close_attempt_count"] += 1
    state["last_selected_reason"] = "auto_close_time_economics"
    state["last_block_code"] = None

    assert state["close_attempt_count"] == 1
    assert state["close_in_flight"] is True

    # Simulate mark_failed
    snap = _finalize_close_lifecycle_state(
        active, terminal, "ETHUSDTM", {"trade_id": "sm-001"},
        success=False, block_code="POSITION_MANAGER_CLOSE_FAILED"
    )
    assert snap is not None
    assert snap["close_finalized"] is False
    assert snap["close_finalization_block_code"] == "POSITION_MANAGER_CLOSE_FAILED"
    assert active["trade:sm-001"]["close_in_flight"] is False
    assert active["trade:sm-001"]["last_block_code"] == "POSITION_MANAGER_CLOSE_FAILED"
    assert "trade:sm-001" in terminal

    # Re-attempt after failure — attempt_count must not reset
    state2 = active["trade:sm-001"]
    state2["close_in_flight"] = True
    state2["close_attempt_count"] += 1
    assert state2["close_attempt_count"] == 2

    # Simulate mark_success
    snap2 = _finalize_close_lifecycle_state(
        active, terminal, "ETHUSDTM", {"trade_id": "sm-001"},
        success=True
    )
    assert snap2 is not None
    assert snap2["close_finalized"] is True
    # Key must be removed from active state on success
    assert "trade:sm-001" not in active
    # Terminal state updated with success snapshot
    assert terminal["trade:sm-001"]["close_finalization_status"] == "success"
    assert terminal["trade:sm-001"]["close_attempt_count"] == 2


# ---------------------------------------------------------------------------
# P2-6  Multi-position PAPER shutdown — both positions force-closed
# ---------------------------------------------------------------------------

def test_paper_force_close_closes_multiple_positions(monkeypatch, tmp_path):
    """
    Two open positions (BTCUSDTM + ETHUSDTM).
    After run_bot(simulate=True, PAPER_RUN_ONCE=1) both must be in closed
    and _positions_map must be empty.
    """
    db_path = _make_db(tmp_path, [])

    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "0")
    monkeypatch.setenv("PAPER_RUN_CYCLES", "1")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("PAPER_FORCE_CLOSE_ON_EXIT", "1")

    from core.PositionManager import PositionManager as _PM

    captured_pm: list[_PM] = []
    original_pm_init = _PM.__init__

    def patched_pm_init(self):
        original_pm_init(self)
        for sym, side, price in [
            ("BTCUSDTM", "buy", 90000.0),
            ("ETHUSDTM", "buy", 3000.0),
        ]:
            self._positions_map[sym] = {
                "symbol": sym,
                "side": side,
                "amount": 0.001,
                "entry_price": price,
                "trade_id": f"multi-{sym}-001",
                "strategy": "TrendFollowing",
            }
        self.positions = list(self._positions_map.values())
        captured_pm.append(self)

    monkeypatch.setattr(_PM, "__init__", patched_pm_init)

    events = _capture_infinity_events(monkeypatch)

    import requests

    def _block_net(*a, **k):
        raise AssertionError("no net")

    monkeypatch.setattr(requests, "get", _block_net)
    monkeypatch.setattr(requests, "post", _block_net)

    try:
        import utils.news_social_scheduler as nss
        monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    except Exception:
        pass

    import core.db_models as dbm
    importlib.reload(dbm)

    botcore = _patch_botcore_symbols(monkeypatch, ["BTCUSDTM", "ETHUSDTM"])
    botcore.run_bot(simulate=True)

    assert captured_pm, "PositionManager never instantiated"
    pm = captured_pm[-1]
    # Explicit multi-position shutdown invariants
    assert pm.get_position("BTCUSDTM") is None
    assert pm.get_position("ETHUSDTM") is None
    closed_symbols = {str(p.get("symbol") or "") for p in pm.closed}
    assert "BTCUSDTM" in closed_symbols
    assert "ETHUSDTM" in closed_symbols
    force_close_events = [
        payload
        for name, payload in events
        if name == "position_close"
        and str(payload.get("symbol") or "") in {"BTCUSDTM", "ETHUSDTM"}
    ]
    assert len(force_close_events) >= 2


def test_drain_close_requests_handles_malformed_rows_invalid_qty_and_success_path(
    monkeypatch, tmp_path
):
    db_path = _make_db(tmp_path, [])
    _insert_raw_log_rows(
        db_path,
        [
            ("position_close_request", "{invalid-json"),
            ("position_close_request", json.dumps(["not-a-dict"])),
            ("position_close_request", json.dumps({"reason": "missing_symbol"})),
            (
                "position_close_request",
                json.dumps(
                    {
                        "symbol": "ETHUSDTM",
                        "reason": "invalid_qty",
                        "requested_at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
            ),
            (
                "position_close_request",
                json.dumps(
                    {
                        "symbol": "ETHUSDTM",
                        "reason": "valid_qty",
                        "requested_at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
            ),
        ],
    )

    monkeypatch.setenv("USE_MOCK", "0")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "0")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("PAPER_RUN_CYCLES", "0")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("PAPER_FORCE_CLOSE_ON_EXIT", "0")

    from core.MarketDataFetcher import MarketDataFetcher
    from core.kucoin_futures_client import KucoinFuturesClient
    from core.PositionManager import PositionManager as _PM

    def _fake_ohlcv(self, symbol, interval, limit=120):
        ts = int(time.time())
        n = max(3, int(limit))
        return [
            {
                "timestamp": ts - (n - i) * 60,
                "open": 100.0 + i,
                "high": 100.5 + i,
                "low": 99.5 + i,
                "close": 100.2 + i,
                "volume": 1000.0,
            }
            for i in range(n)
        ]

    monkeypatch.setattr(MarketDataFetcher, "get_ohlcv", _fake_ohlcv)
    monkeypatch.setattr(
        KucoinFuturesClient,
        "get_ticker",
        lambda self, symbol: {"price": 123.45, "last": 123.45},
    )

    captured_pm: list[_PM] = []
    original_pm_init = _PM.__init__

    def patched_pm_init(self):
        original_pm_init(self)
        self._positions_map["ETHUSDTM"] = {
            "symbol": "ETHUSDTM",
            "side": "buy",
            "amount": 0.001,
            "entry_price": 100.0,
            "trade_id": "drain-mixed-001",
            "strategy": "TrendFollowing",
            "entry_main_strategy": "TrendFollowing",
        }
        self.positions = list(self._positions_map.values())
        captured_pm.append(self)

    monkeypatch.setattr(_PM, "__init__", patched_pm_init)

    events = _capture_infinity_events(monkeypatch)

    try:
        import utils.news_social_scheduler as nss

        monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    except Exception:
        pass

    import core.db_models as dbm

    importlib.reload(dbm)
    botcore = _patch_botcore_symbols(monkeypatch, ["ETHUSDTM"])

    close_qty_calls = {"n": 0}

    def fake_resolve_simulated_close_quantity(_pos):
        close_qty_calls["n"] += 1
        if close_qty_calls["n"] == 1:
            return None, "forced_none", {"phase": "invalid"}
        return 0.001, "forced_ok", {"phase": "valid"}

    monkeypatch.setattr(
        botcore,
        "resolve_simulated_close_quantity",
        fake_resolve_simulated_close_quantity,
    )

    botcore.run_bot(simulate=True)

    assert captured_pm, "PositionManager never instantiated"
    pm = captured_pm[-1]
    assert any(
        p.get("symbol") == "ETHUSDTM" and p.get("trade_id") == "drain-mixed-001"
        for p in pm.closed
    ), "Requested position should be closed after valid simulated close payload"
    assert _count_event(db_path, "position_close_request") >= 5
    assert any(
        name == "position_close"
        and str(payload.get("symbol") or "").upper() == "ETHUSDTM"
        and str((payload.get("position") or {}).get("trade_id") or "")
        == "drain-mixed-001"
        and str(payload.get("exit_reason") or "").strip() != ""
        and str(payload.get("close_reason") or "").strip() != ""
        for name, payload in events
    )

    input_traces = [
        payload
        for name, payload in events
        if name == "close_pnl_decompose_input_trace"
        and str(payload.get("symbol") or "").upper() == "ETHUSDTM"
    ]
    assert any(
        str(p.get("raw_input_classification") or "") == "INVALID_SIMULATED_CLOSE_SIZE"
        for p in input_traces
    ), "Invalid simulated close size should emit deterministic classification trace"
    assert any(
        str(p.get("raw_input_classification") or "") == "RAW_INPUTS_PRESENT"
        for p in input_traces
    ), "Successful simulated close should emit RAW_INPUTS_PRESENT trace"


def test_post_close_summary_emit_failures_are_swallowed_during_run_bot(
    monkeypatch, tmp_path
):
    db_path = _make_db(tmp_path, [])

    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("PAPER_RUN_CYCLES", "0")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("PAPER_FORCE_CLOSE_ON_EXIT", "0")

    from core.MarketDataFetcher import MarketDataFetcher

    def _fake_ohlcv(self, symbol, interval, limit=120):
        ts = int(time.time())
        n = max(3, int(limit))
        return [
            {
                "timestamp": ts - (n - i) * 60,
                "open": 100.0 + i,
                "high": 100.5 + i,
                "low": 99.5 + i,
                "close": 100.2 + i,
                "volume": 1000.0,
            }
            for i in range(n)
        ]

    monkeypatch.setattr(MarketDataFetcher, "get_ohlcv", _fake_ohlcv)

    try:
        import utils.news_social_scheduler as nss

        monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    except Exception:
        pass

    import core.db_models as dbm
    import core.InfinityLayerLogger as ill

    importlib.reload(dbm)

    post_close_emit_attempted = []
    original_log = ill.InfinityLayerLogger.log

    def patched_log(self, event, details=None):
        event_name = str(event)
        if event_name in (
            "post_close_summary_pre_assembly",
            "post_close_summary_assembly_enter",
        ):
            post_close_emit_attempted.append(event_name)
            raise RuntimeError("forced-post-close-summary-log-error")
        return original_log(self, event, details)

    monkeypatch.setattr(ill.InfinityLayerLogger, "log", patched_log)

    botcore = _patch_botcore_symbols(monkeypatch, ["ETHUSDTM"])
    botcore.run_bot(simulate=True)

    assert "post_close_summary_pre_assembly" in post_close_emit_attempted
    assert "post_close_summary_assembly_enter" in post_close_emit_attempted
