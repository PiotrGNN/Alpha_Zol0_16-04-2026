# flake8: noqa: E501  # long lines in tests
import importlib
import os
import sys
import json

from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class _ManagedTestClient:
    def __init__(self, app):
        self._client = TestClient(app)
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._client, name)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._client.close()
        finally:
            try:
                import core.db_models as db_models

                db_models.engine.dispose()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def _build_client(monkeypatch, overrides=None):
    db_path = Path("tmp") / "test_api.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    defaults = {
        "DATABASE_URL": f"sqlite:///{db_path.resolve().as_posix()}",
        "USE_MOCK": "1",
        "ZOL0_TOKEN": "testtoken",
        "LIVE": "0",
        "LIVE_ARMED": "0",
    }
    if overrides:
        defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setenv(k, v)
    # Ensure fresh modules with env applied
    import core.db_models

    importlib.reload(core.db_models)
    core.db_models.init_db()
    import api_status

    importlib.reload(api_status)
    return _ManagedTestClient(api_status.app), api_status


def _write_ready_snapshot(monkeypatch, tmp_path):
    path = tmp_path / "live_readiness_snapshot.json"
    path.write_text(
        json.dumps(
            {
                "runtime_state": {
                    "last_run": {
                        "process_returncode": 0,
                        "shutdown_classification": (
                            "close_flush_done_pending_positions_zero"
                        ),
                        "pending_positions": 0,
                        "close_request_backlog": 0,
                    },
                    "data_validity": {
                        "accepted_corpus_exists": True,
                        "no_rejected_runs_in_active_dataset": True,
                        "corpus_size_trades": 60,
                    },
                    "strategy_validation": {
                        "usable_strategy_economics": True,
                        "economic_go_no_go": "GO",
                        "profitability_metrics": {
                            "expectancy": 0.01,
                            "winrate": 0.55,
                            "profit_factor": 1.2,
                            "green_to_red_share": 0.2,
                        }
                    },
                    "critical_blockers": {
                        "CLOSE_FINALIZATION_BROKEN": False,
                        "LINKAGE_LAYER_NO_EFFECT": False,
                        "TERMINAL_TIMING_CUTOFF_CONFIRMED": False,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LIVE_READINESS_SNAPSHOT_PATH", str(path))
    return path


@pytest.fixture()
def api_client(monkeypatch):
    client, _ = _build_client(monkeypatch)
    try:
        yield client
    finally:
        client.close()


def test_api_market_mock(api_client):
    resp = api_client.get("/api/market")
    assert resp.status_code == 200
    data = resp.json()
    assert "ohlcv" in data
    assert isinstance(data["ohlcv"], list)
    assert "ticker" in data


def test_api_balance_mock(api_client):
    resp = api_client.get("/api/balance")
    assert resp.status_code == 200
    data = resp.json()
    assert "balances" in data
    assert isinstance(data["balances"], list)
    if data["balances"]:
        entry = data["balances"][0]
        for key in (
            "account_type",
            "currency",
            "available",
            "holds",
            "total",
            "timestamp",
        ):
            assert key in entry


def test_start_live_blocked_by_default(api_client, monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    resp = api_client.post("/start-live", headers={"X-API-Token": "testtoken"})
    assert resp.status_code in (403, 409)
    data = resp.json()
    assert "error" in data


def test_start_live_allowed_when_live_ready(monkeypatch, tmp_path):
    readiness_path = _write_ready_snapshot(monkeypatch, tmp_path)
    client, api_mod = _build_client(
        monkeypatch,
        {
            "LIVE": "1",
            "LIVE_ARMED": "1",
            "LIVE_READINESS_SNAPSHOT_PATH": str(readiness_path),
            "KUCOIN_API_KEY": "k",
            "KUCOIN_API_SECRET": "s",
            "KUCOIN_API_PASSPHRASE": "p",
        },
    )
    calls = []

    try:
        import core.BotCore as botcore

        def fake_run_bot(simulate=False):
            calls.append({"simulate": simulate})

        class DummyThread:
            def __init__(self, target=None, kwargs=None, daemon=None):
                self.target = target
                self.kwargs = kwargs or {}
                self.daemon = daemon

            def start(self):
                self.target(**self.kwargs)

        monkeypatch.setattr(botcore, "run_bot", fake_run_bot)
        monkeypatch.setattr(api_mod, "threading", SimpleNamespace(Thread=DummyThread))

        resp = client.post("/start-live", headers={"X-API-Token": "testtoken"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"
        assert calls == [{"simulate": False}]
    finally:
        client.close()


def test_control_routes_require_header_token(api_client):
    resp = api_client.post("/positions/BTCUSDTM/close")
    assert resp.status_code == 403


def test_auto_monitor_accepts_mode_and_persists_env(api_client, monkeypatch):
    # enable auto-monitor with 'hitrate' mode and verify env persistence
    headers = {"X-API-Token": "testtoken"}
    import api_status as api_mod

    class DummyThread:
        def __init__(self, *args, **kwargs):
            self._alive = False

        def start(self):
            self._alive = True

        def is_alive(self):
            return self._alive

    monkeypatch.setattr(api_mod.threading, "Thread", DummyThread)
    resp = api_client.post(
        "/auto-monitor?mode=hitrate&interval_sec=60", headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("mode") == "hitrate"
    # environment should reflect requested mode
    import os

    assert os.environ.get("AUTO_MONITOR_MODE") == "hitrate"
    # starting the monitor should create the background thread state
    import api_status as api_mod

    t = getattr(api_mod.app.state, "auto_monitor_thread", None)
    assert t is not None and t.is_alive() is True


def test_auto_monitor_writes_runtime_allocation_to_db(api_client):
    """POST /auto-monitor with allocation_pct must persist a runtime_allocation log row."""
    headers = {"X-API-Token": "testtoken"}
    resp = api_client.post("/auto-monitor?allocation_pct=0.30", headers=headers)
    assert resp.status_code == 200
    # verify the runtime_allocation row was written to the DB used by the API test client
    from core.db_models import SessionLocal, LogEntry
    import json

    db = SessionLocal()
    row = (
        db.query(LogEntry)
        .filter(LogEntry.event == "runtime_allocation")
        .order_by(LogEntry.timestamp.desc())
        .first()
    )
    assert row is not None, "runtime_allocation row missing"
    details = json.loads(row.details) if row.details else {}
    assert float(details.get("allocation_pct")) == pytest.approx(0.30, rel=1e-6)
    db.close()


def test_auto_monitor_end_to_end_bot_pickup(api_client):
    """End-to-end: POST /auto-monitor persists runtime_allocation and bot can pick it up (simulated)."""
    headers = {"X-API-Token": "testtoken"}
    resp = api_client.post("/auto-monitor?allocation_pct=0.42", headers=headers)
    assert resp.status_code == 200

    from core.db_models import SessionLocal, LogEntry
    import json

    db = SessionLocal()
    row = (
        db.query(LogEntry)
        .filter(LogEntry.event == "runtime_allocation")
        .order_by(LogEntry.timestamp.desc())
        .first()
    )
    assert row is not None, "runtime_allocation row missing (API persistence failed)"
    details = json.loads(row.details) if row.details else {}
    parsed = float(details.get("allocation_pct"))
    assert parsed == pytest.approx(0.42, rel=1e-6)

    # Simulate BotCore DB pickup: parsed value should be usable to update RiskManager
    from core.RiskManager import RiskManager

    rm = RiskManager()
    old_alloc = rm.allocation_pct
    rm.allocation_pct = parsed
    assert rm.allocation_pct == pytest.approx(parsed, rel=1e-6)
    assert old_alloc != rm.allocation_pct
    db.close()


def test_api_market_futures_uses_futures_client(monkeypatch):
    client, api_status = _build_client(
        monkeypatch,
        overrides={"USE_MOCK": "0", "MARKET_TYPE": "futures"},
    )

    class DummyFuturesClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_ticker(self, symbol):
            return {"price": "100", "bestBidPrice": "99", "bestAskPrice": "101"}

        def get_klines(self, symbol, interval, limit=200):
            return [
                {
                    "timestamp": 1,
                    "open": 1,
                    "close": 1,
                    "high": 1,
                    "low": 1,
                    "volume": 1,
                }
            ]

    class SpotClientBlocker:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("spot client should not be used in futures mode")

    monkeypatch.setattr(api_status, "KucoinFuturesClient", DummyFuturesClient)
    monkeypatch.setattr(api_status, "KucoinClient", SpotClientBlocker)

    resp = client.get("/api/market?symbol=BTCUSDTM")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "kucoin-futures"
    assert data["symbol"] == "BTCUSDTM"
    assert "ohlcv" in data


def test_api_balance_futures_does_not_use_spot(monkeypatch):
    client, api_status = _build_client(
        monkeypatch,
        overrides={"USE_MOCK": "0", "MARKET_TYPE": "futures"},
    )

    class DummyFuturesClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_account_overview(self, currency="USDT"):
            return {"availableBalance": "1", "frozenFunds": "0", "accountEquity": "1"}

    def spot_accounts_blocked(*args, **kwargs):
        raise RuntimeError("spot accounts should not be called in futures mode")

    monkeypatch.setattr(api_status, "KucoinFuturesClient", DummyFuturesClient)
    monkeypatch.setattr(api_status.KucoinClient, "get_accounts", spot_accounts_blocked)

    resp = client.get("/api/balance?symbol=BTCUSDTM")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "kucoin-futures"
    assert data["balances"][0]["account_type"] == "futures"


def test_api_market_futures_sanity_check_fails(monkeypatch):
    client, api_status = _build_client(
        monkeypatch,
        overrides={"USE_MOCK": "0", "MARKET_TYPE": "futures"},
    )

    class DummyFuturesClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_ticker(self, symbol):
            return {"price": "100", "bestBidPrice": "99", "bestAskPrice": "101"}

        def get_klines(self, symbol, interval, limit=200):
            # invalid: high < max(open, close)
            return [
                {
                    "timestamp": 1,
                    "open": 100,
                    "close": 101,
                    "high": 99,
                    "low": 98,
                    "volume": 1,
                }
            ]

    monkeypatch.setattr(api_status, "KucoinFuturesClient", DummyFuturesClient)

    resp = client.get("/api/market?symbol=BTCUSDTM")
    assert resp.status_code == 502
    data = resp.json()
    assert data["error"] == "invalid_ohlcv_sanity"


def test_api_market_futures_timestamps_in_ms(monkeypatch):
    client, api_status = _build_client(
        monkeypatch,
        overrides={"USE_MOCK": "0", "MARKET_TYPE": "futures"},
    )

    class DummyFuturesClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_ticker(self, symbol):
            return {"price": "100", "bestBidPrice": "99", "bestAskPrice": "101"}

        def get_klines(self, symbol, interval, limit=200):
            # timestamp in seconds
            return [
                {
                    "timestamp": 1700000000,
                    "open": 100,
                    "close": 100,
                    "high": 101,
                    "low": 99,
                    "volume": 1,
                }
            ]

    monkeypatch.setattr(api_status, "KucoinFuturesClient", DummyFuturesClient)

    resp = client.get("/api/market?symbol=BTCUSDTM")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ohlcv"][0]["timestamp"] == 1700000000000


def test_performance_net_pnl_15m(monkeypatch):
    client, api_status = _build_client(
        monkeypatch,
        overrides={"USE_MOCK": "1"},
    )
    # shortened debug output to satisfy the line-length limit
    print(
        "DEBUG test_performance_net_pnl_15m: api_status.__file__=%r"
        % getattr(api_status, "__file__", None)
    )
    print(
        "DEBUG test_performance_net_pnl_15m: SessionLocal=%r"
        % getattr(api_status, "SessionLocal", None)
    )
    import core.db_models as db_models

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db_models.engine = engine
    db_models.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    db_models.Base.metadata.bind = engine
    api_status.SessionLocal = db_models.SessionLocal
    api_status.init_db = db_models.init_db
    api_status.Equity = db_models.Equity

    SessionLocal = db_models.SessionLocal
    Equity = db_models.Equity
    init_db = db_models.init_db

    init_db()
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        e1 = Equity(timestamp=now - timedelta(minutes=10), equity=10000.0, pnl=0.0)
        e2 = Equity(timestamp=now - timedelta(minutes=2), equity=10000.4, pnl=0.4)
        db.add_all([e1, e2])
        db.commit()
    finally:
        db.close()

    resp = client.get("/performance")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("net_pnl_15m") == pytest.approx(0.4)
    assert data.get("net_pnl_15m_ok") is False

    db = SessionLocal()
    try:
        e3 = Equity(timestamp=now - timedelta(minutes=1), equity=10000.6, pnl=0.2)
        db.add(e3)
        db.commit()
    finally:
        db.close()

    resp = client.get("/performance")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("net_pnl_15m") == pytest.approx(0.6)
    assert data.get("net_pnl_15m_ok") is True


def test_performance_net_pnl_15m_respects_new_session_anchor(monkeypatch):
    client, api_status = _build_client(
        monkeypatch,
        overrides={"USE_MOCK": "1", "NEW_SESSION": "1"},
    )
    import core.db_models as db_models

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db_models.engine = engine
    db_models.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    db_models.Base.metadata.bind = engine
    api_status.SessionLocal = db_models.SessionLocal
    api_status.init_db = db_models.init_db
    api_status.Equity = db_models.Equity

    SessionLocal = db_models.SessionLocal
    Equity = db_models.Equity
    init_db = db_models.init_db

    init_db()
    now = datetime.now(timezone.utc)
    api_status.app.state.session_start = now - timedelta(minutes=5)

    db = SessionLocal()
    try:
        # Old point in last 15m but before NEW_SESSION anchor -> must be ignored.
        db.add(Equity(timestamp=now - timedelta(minutes=10), equity=9000.0, pnl=0.0))
        db.add(Equity(timestamp=now - timedelta(minutes=4), equity=10000.0, pnl=0.0))
        db.add(Equity(timestamp=now - timedelta(minutes=1), equity=10000.3, pnl=0.3))
        db.commit()
    finally:
        db.close()

    resp = client.get("/performance")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("net_pnl_15m") == pytest.approx(0.3)


def test_performance_net_pnl_15m_fallback_to_recent_history(monkeypatch):
    """When no equity samples exist inside the 15m window, fall back to the
    last two equity rows so monitoring can proceed when sampling is sparse.
    """
    client, api_status = _build_client(monkeypatch, overrides={"USE_MOCK": "1"})
    import core.db_models as db_models

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db_models.engine = engine
    db_models.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    db_models.Base.metadata.bind = engine
    api_status.SessionLocal = db_models.SessionLocal
    api_status.init_db = db_models.init_db
    api_status.Equity = db_models.Equity

    SessionLocal = db_models.SessionLocal
    Equity = db_models.Equity
    init_db = db_models.init_db

    init_db()
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        # Both points are older than 15 minutes -> eq_window will be empty.
        db.add(Equity(timestamp=now - timedelta(minutes=30), equity=10000.0, pnl=0.0))
        db.add(Equity(timestamp=now - timedelta(minutes=20), equity=10000.3, pnl=0.3))
        db.commit()
    finally:
        db.close()

    resp = client.get("/performance")
    assert resp.status_code == 200
    data = resp.json()
    # fallback should compute difference between last two equity values
    assert data.get("net_pnl_15m") == pytest.approx(0.3)
    assert data.get("net_pnl_15m_ok") is False


def test_performance_counts_order_entries(monkeypatch):
    client, api_status = _build_client(
        monkeypatch,
        overrides={"USE_MOCK": "1"},
    )
    import core.db_models as db_models

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db_models.engine = engine
    db_models.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    db_models.Base.metadata.bind = engine
    api_status.SessionLocal = db_models.SessionLocal
    api_status.init_db = db_models.init_db
    api_status.Equity = db_models.Equity
    api_status.LogEntry = db_models.LogEntry

    SessionLocal = db_models.SessionLocal
    Equity = db_models.Equity
    LogEntry = db_models.LogEntry
    init_db = db_models.init_db

    init_db()
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        db.add(Equity(timestamp=now - timedelta(minutes=1), equity=100.0, pnl=0.0))
        db.add(LogEntry(timestamp=now, event="order_simulated", details="{}"))
        db.commit()
    finally:
        db.close()

    resp = client.get("/performance")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("trades") == 1


def test_equity_endpoint_filters_outliers(monkeypatch):
    client, api_status = _build_client(
        monkeypatch,
        overrides={"USE_MOCK": "1", "EQUITY_MAX_USDT": "1000", "NEW_SESSION": "0"},
    )
    import core.db_models as db_models

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db_models.engine = engine
    db_models.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    db_models.Base.metadata.bind = engine
    api_status.SessionLocal = db_models.SessionLocal
    api_status.init_db = db_models.init_db
    api_status.Equity = db_models.Equity

    SessionLocal = db_models.SessionLocal
    Equity = db_models.Equity
    init_db = db_models.init_db

    init_db()
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        db.add(Equity(timestamp=now - timedelta(minutes=1), equity=50.0, pnl=0.0))
        db.add(Equity(timestamp=now, equity=2_000_000.0, pnl=0.0))
        db.commit()
    finally:
        db.close()

    resp = client.get("/equity")
    assert resp.status_code == 200
    data = resp.json()
    assert any(abs(row.get("equity", 0) - 50.0) < 1e-6 for row in data)
    assert all(abs(row.get("equity", 0)) <= 1000 for row in data)


def test_strategy_metrics_from_logs(monkeypatch):
    db_path = Path("tmp") / f"test_api_{uuid4().hex}.db"
    client, api_status = _build_client(
        monkeypatch,
        overrides={
            "USE_MOCK": "1",
            "DATABASE_URL": f"sqlite:///{db_path.resolve().as_posix()}",
        },
    )
    from core.db_models import LogEntry
    import core.db_models as db_models

    api_status.init_db()
    db_models.engine.dispose()

    db = api_status.SessionLocal()
    try:
        details = {
            "strategy": "Momentum",
            "realized_pnl": 1.5,
            "position": {"strategy": "Momentum", "realized_pnl": 1.5},
        }
        db.add(
            LogEntry(
                timestamp=datetime.now(timezone.utc),
                event="position_close",
                details=json.dumps(details),
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.get("/strategy")
    assert resp.status_code == 200
    data = resp.json()
    allocs = data.get("strategy_allocations") or []
    entry = next((e for e in allocs if e.get("name") == "Momentum"), None)
    assert entry is not None
    assert entry.get("pnl") == pytest.approx(1.5)
    assert entry.get("sharpe") == pytest.approx(1.5)


def test_closed_positions_prefers_fresh_db_events(monkeypatch):
    db_path = Path("tmp") / f"test_api_{uuid4().hex}.db"
    client, api_status = _build_client(
        monkeypatch,
        overrides={
            "USE_MOCK": "1",
            "DATABASE_URL": f"sqlite:///{db_path.resolve().as_posix()}",
        },
    )
    from core.db_models import LogEntry
    import core.db_models as db_models

    api_status.init_db()
    db_models.engine.dispose()

    # Simulate stale in-memory list loaded at API startup.
    api_status.position_manager.closed_positions.clear()
    api_status.position_manager.closed_positions.append(
        {
            "symbol": "BTCUSDTM",
            "side": "buy",
            "entry_price": 70000.0,
            "close_price": 69900.0,
            "close_timestamp": "2026-02-01T00:00:00+00:00",
            "realized_pnl": -0.1,
            "strategy": "Momentum",
        }
    )

    db = api_status.SessionLocal()
    try:
        fresh_details = {
            "symbol": "ETHUSDTM",
            "position": {
                "symbol": "ETHUSDTM",
                "side": "sell",
                "entry_price": 2000.0,
                "close_price": 1990.0,
                "close_timestamp": "2026-02-11T22:00:00+00:00",
                "realized_pnl": 0.23,
                "strategy": "Momentum",
            },
            "realized_pnl": 0.23,
            "close_price": 1990.0,
            "strategy": "Momentum",
        }
        db.add(
            LogEntry(
                timestamp=datetime.now(timezone.utc),
                event="position_close",
                details=json.dumps(fresh_details),
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.get("/positions/closed")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows
    # Fresh DB close should be visible even when memory is stale.
    assert rows[0]["symbol"] == "ETHUSDTM"
    assert rows[0].get("realized_pnl") == pytest.approx(0.23)

    # /api/paper_state should expose the same fresh closed list.
    state = client.get("/api/paper_state")
    assert state.status_code == 200
    closed = state.json().get("closed_positions", [])
    assert closed
    assert closed[0]["symbol"] == "ETHUSDTM"


def test_closed_positions_resolves_exit_reason_from_post_green_fallback(monkeypatch):
    db_path = Path("tmp") / f"test_api_{uuid4().hex}.db"
    client, api_status = _build_client(
        monkeypatch,
        overrides={
            "USE_MOCK": "1",
            "DATABASE_URL": f"sqlite:///{db_path.resolve().as_posix()}",
        },
    )
    from core.db_models import LogEntry
    import core.db_models as db_models

    api_status.init_db()
    db_models.engine.dispose()

    db = api_status.SessionLocal()
    try:
        details = {
            "symbol": "ETHUSDTM",
            "position": {
                "symbol": "ETHUSDTM",
                "side": "buy",
                "entry_price": 2000.0,
                "close_price": 1998.0,
                "strategy": "Momentum",
                "post_green_exit_reason": "post_green_protective_exit",
            },
            "close_price": 1998.0,
        }
        db.add(
            LogEntry(
                timestamp=datetime.now(timezone.utc),
                event="position_close",
                details=json.dumps(details),
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.get("/positions/closed")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows
    assert rows[0]["symbol"] == "ETHUSDTM"
    assert rows[0]["exit_reason"] == "post_green_protective_exit"
