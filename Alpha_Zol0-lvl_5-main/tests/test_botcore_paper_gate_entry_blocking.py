import core.BotCore as botcore
from core.BotCore import apply_paper_gate_entry_guard, run_bot


def test_botcore_gate_blocks_entry_attempts(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")

    calls = {
        "update_position": 0,
        "execute_order": 0,
        "apply_risk": 0,
        "update_gate": 0,
    }

    def fake_update_position(self, symbol, order):
        calls["update_position"] += 1

    def fake_execute_order(self, order, use_rest=True):
        calls["execute_order"] += 1

    def fake_apply_risk(
        self,
        signal,
        price,
        balance,
        position_status,
        pnl_history,
        symbol,
        global_pnl_history=None,
        open_positions=None,
    ):
        calls["apply_risk"] += 1
        return True, None, None, 100.0

    def fake_update_gate(net_pnl, target=0.5):
        calls["update_gate"] += 1
        return {"active": True}

    class DummyQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return []

    class DummySession:
        def query(self, *args, **kwargs):
            return DummyQuery()

        def close(self):
            return None

    def fake_config(_path):
        return {
            "api_key": None,
            "api_secret": None,
            "balance": 10000.0,
            "retrain_interval": 10000000,
            "sl_pct": 0.5,
            "tp_pct": 1.0,
            "symbol": "BTCUSDTM",
            "timeframe": 1,
            "market_type": "futures",
        }

    import utils.news_social_scheduler as nss
    import utils.paper_gate as paper_gate
    import core.db_models as db_models
    import core.OrderExecutor as order_exec
    import core.PositionManager as position_mgr
    import core.RiskManager as risk_mgr

    monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    monkeypatch.setattr(paper_gate, "update_gate", fake_update_gate)
    monkeypatch.setattr(db_models, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(order_exec.OrderExecutor, "execute_order", fake_execute_order)
    monkeypatch.setattr(
        position_mgr.PositionManager, "update_position", fake_update_position
    )
    monkeypatch.setattr(risk_mgr.RiskManager, "apply_risk", fake_apply_risk)
    monkeypatch.setattr(botcore, "load_config", fake_config)
    monkeypatch.setattr(botcore, "save_decision_to_db", lambda *a, **k: None)
    monkeypatch.setattr(botcore, "save_equity_to_db", lambda *a, **k: None)

    run_bot(simulate=True)
    assert calls["apply_risk"] >= 1
    assert calls["update_gate"] >= 1
    assert calls["update_position"] == 0
    assert calls["execute_order"] == 0


def test_run_bot_loads_repo_config_independent_of_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")

    calls = {
        "update_position": 0,
        "execute_order": 0,
        "apply_risk": 0,
        "update_gate": 0,
    }

    def fake_update_position(self, symbol, order):
        calls["update_position"] += 1

    def fake_execute_order(self, order, use_rest=True):
        calls["execute_order"] += 1

    def fake_apply_risk(
        self,
        signal,
        price,
        balance,
        position_status,
        pnl_history,
        symbol,
        global_pnl_history=None,
        open_positions=None,
    ):
        calls["apply_risk"] += 1
        return True, None, None, 100.0

    def fake_update_gate(net_pnl, target=0.5):
        calls["update_gate"] += 1
        return {"active": True}

    class DummyQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return []

    class DummySession:
        def query(self, *args, **kwargs):
            return DummyQuery()

        def close(self):
            return None

    import utils.news_social_scheduler as nss
    import utils.paper_gate as paper_gate
    import core.db_models as db_models
    import core.OrderExecutor as order_exec
    import core.PositionManager as position_mgr
    import core.RiskManager as risk_mgr

    monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    monkeypatch.setattr(paper_gate, "update_gate", fake_update_gate)
    monkeypatch.setattr(db_models, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(order_exec.OrderExecutor, "execute_order", fake_execute_order)
    monkeypatch.setattr(
        position_mgr.PositionManager, "update_position", fake_update_position
    )
    monkeypatch.setattr(risk_mgr.RiskManager, "apply_risk", fake_apply_risk)
    monkeypatch.setattr(botcore, "save_decision_to_db", lambda *a, **k: None)
    monkeypatch.setattr(botcore, "save_equity_to_db", lambda *a, **k: None)

    run_bot(simulate=True)

    assert calls["apply_risk"] >= 1
    assert calls["update_gate"] >= 1
    assert calls["update_position"] == 0
    assert calls["execute_order"] == 0


def test_gate_guard_allows_zero_allocation():
    allow = apply_paper_gate_entry_guard(True, 0.0, True)
    assert allow is True
