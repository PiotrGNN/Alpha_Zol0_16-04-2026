import types

import core.BotCore as botcore
import core.DynamicStrategyRouter as dr_mod
import core.InfinityLayerLogger as ill
import core.MetaStrategyRouter as mr_mod
import strategies.arbitrage as arbitrage_mod
import strategies.breakout as breakout_mod
import strategies.grid_trading as grid_mod
import strategies.market_making as market_making_mod
import strategies.mean_reversion as mean_reversion_mod
import strategies.momentum as momentum_mod
import strategies.rl_omega as rl_omega_mod
import strategies.sentiment as sentiment_mod
import strategies.trend_following as trend_following_mod
import strategies.UniversalStrategy as universal_mod
from core.BotCore import (
    apply_paper_gate_entry_guard,
    run_bot,
    should_bypass_symbol_strategy_guard_for_hold,
)


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


def test_hold_candidates_bypass_symbol_strategy_guard_when_ignored():
    assert should_bypass_symbol_strategy_guard_for_hold("hold", True) is True
    assert should_bypass_symbol_strategy_guard_for_hold("buy", True) is False
    assert should_bypass_symbol_strategy_guard_for_hold("hold", False) is False


def test_run_bot_resolves_structured_empty_signals_to_hold(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("ENTRY_IGNORE_HOLD_SIGNALS", "1")
    monkeypatch.setenv("ENTRY_ALLOW_BUY", "1")
    monkeypatch.setenv("ENTRY_ALLOW_SELL", "1")
    monkeypatch.setenv("ENTRY_REQUIRE_STRATEGY_NAME", "1")

    calls = {
        "update_position": 0,
        "execute_order": 0,
        "apply_risk": 0,
        "update_gate": 0,
    }
    events = []

    class CaptureLogger:
        def log(self, event, payload=None):
            events.append((event, payload))

    class DummyStrategy:
        def __init__(self, *args, **kwargs):
            self.name = str(kwargs.get("name") or self.__class__.__name__)

        def analyze(self, *args, **kwargs):
            if self.name == "Universal":
                return {
                    "signals": [{"type": "entry", "side": "sell"}],
                    "metrics": {},
                    "analysis": {"trend": "down"},
                }
            if self.name == "TrendFollowing":
                return {
                    "signals": [],
                    "metrics": {
                        "trend_strength": {
                            "direction": 1,
                            "momentum": 1,
                            "strength": "strong",
                            "score": 3,
                        }
                    },
                    "analysis": {"trend": {"direction": 1}},
                }
            return {"signals": [], "metrics": {}, "analysis": {}}

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            self._allocations = {"Universal": 0.6, "MeanReversion": 0.4}

        def route(self, state):
            return [
                {
                    "strategy": "MeanReversion",
                    "allocation": 0.4,
                    "signal": {
                        "signals": [],
                        "metrics": {"rsi": 51.0},
                        "analysis": {"mean": 1.0, "current_price": 1.0},
                    },
                },
                {
                    "strategy": "Universal",
                    "allocation": 0.6,
                    "signal": {
                        "signals": [{"type": "entry", "side": "sell"}],
                        "metrics": {},
                        "analysis": {"trend": "down"},
                    },
                },
            ]

        def get_last_allocations(self):
            return dict(self._allocations)

    class FakeMetaRouter:
        def __init__(self, *args, **kwargs):
            self.last_decision = "Universal"

        def route(self, state):
            return types.SimpleNamespace(name="Universal")

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
    monkeypatch.setattr(ill, "InfinityLayerLogger", lambda: CaptureLogger())
    monkeypatch.setattr(momentum_mod, "MomentumStrategy", DummyStrategy)
    monkeypatch.setattr(mean_reversion_mod, "MeanReversionStrategy", DummyStrategy)
    monkeypatch.setattr(breakout_mod, "BreakoutStrategy", DummyStrategy)
    monkeypatch.setattr(trend_following_mod, "TrendFollowingStrategy", DummyStrategy)
    monkeypatch.setattr(universal_mod, "UniversalStrategy", DummyStrategy)
    monkeypatch.setattr(grid_mod, "GridTradingStrategy", DummyStrategy)
    monkeypatch.setattr(market_making_mod, "MarketMakingStrategy", DummyStrategy)
    monkeypatch.setattr(arbitrage_mod, "ArbitrageStrategy", DummyStrategy)
    monkeypatch.setattr(sentiment_mod, "SentimentStrategy", DummyStrategy)
    monkeypatch.setattr(rl_omega_mod, "RLOmegaStrategy", DummyStrategy)
    monkeypatch.setattr(dr_mod, "DynamicStrategyRouter", FakeRouter)
    monkeypatch.setattr(mr_mod, "MetaStrategyRouter", FakeMetaRouter)

    run_bot(simulate=True)

    rejection_traces = [
        payload
        for event, payload in events
        if event == "pre_entry_candidate_rejection_trace"
    ]
    mean_reversion_traces = [
        payload
        for payload in rejection_traces
        if payload.get("normalized_strategy_value") == "MeanReversion"
    ]
    assert mean_reversion_traces, "expected MeanReversion rejection trace"
    assert any(
        trace.get("normalized_side_value") == "hold"
        and trace.get("rejection_reason_code") == "ambiguous_hold_side"
        for trace in mean_reversion_traces
    )
    assert all(
        trace.get("rejection_reason_code") != "invalid_side"
        for trace in mean_reversion_traces
    )
