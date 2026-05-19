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


def test_controlled_run_entry_cutoff_helper_blocks_terminal_window():
    assert botcore._controlled_run_entry_cutoff_active(
        controlled_run_end_ts=1_060.0,
        entry_cutoff_before_end_sec=60,
        now_ts=1_000.0,
    )
    assert not botcore._controlled_run_entry_cutoff_active(
        controlled_run_end_ts=1_060.0,
        entry_cutoff_before_end_sec=60,
        now_ts=999.99,
    )
    assert not botcore._controlled_run_entry_cutoff_active(
        controlled_run_end_ts=1_060.0,
        entry_cutoff_before_end_sec=0,
        now_ts=1_059.0,
    )
    assert not botcore._controlled_run_entry_cutoff_active(
        controlled_run_end_ts=0,
        entry_cutoff_before_end_sec=60,
        now_ts=1_059.0,
    )


def test_paper_auto_open_respects_controlled_run_entry_cutoff(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("PAPER_AUTO_OPEN", "1")
    monkeypatch.setenv("PAPER_AUTO_OPEN_STARTUP_ENABLE", "1")
    monkeypatch.setenv("PAPER_AUTO_OPEN_FALLBACK_ENABLE", "1")
    monkeypatch.setenv("PAPER_AUTO_OPEN_REPEAT", "1")
    monkeypatch.setenv("CONTROLLED_RUN_END_TS", "1000")
    monkeypatch.setenv("ENTRY_CUTOFF_BEFORE_END_SEC", "60")

    calls = {"update_position": 0, "execute_order": 0}
    events = []

    class CaptureLogger:
        def log(self, event, payload=None):
            events.append((event, payload))

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

    def fake_update_position(self, symbol, order):
        calls["update_position"] += 1

    def fake_execute_order(self, order, use_rest=True):
        calls["execute_order"] += 1

    import core.db_models as db_models
    import core.OrderExecutor as order_exec
    import core.PositionManager as position_mgr
    import utils.news_social_scheduler as nss
    import utils.paper_gate as paper_gate

    monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    monkeypatch.setattr(paper_gate, "update_gate", lambda *a, **k: {"active": False})
    monkeypatch.setattr(db_models, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(order_exec.OrderExecutor, "execute_order", fake_execute_order)
    monkeypatch.setattr(
        position_mgr.PositionManager, "update_position", fake_update_position
    )
    monkeypatch.setattr(botcore, "load_config", fake_config)
    monkeypatch.setattr(botcore, "save_decision_to_db", lambda *a, **k: None)
    monkeypatch.setattr(botcore, "save_equity_to_db", lambda *a, **k: None)
    monkeypatch.setattr(botcore.time, "time", lambda: 950.0)
    monkeypatch.setattr(ill, "InfinityLayerLogger", lambda: CaptureLogger())

    run_bot(simulate=True)

    assert calls["update_position"] == 0
    assert calls["execute_order"] == 0
    skipped = [
        payload
        for event, payload in events
        if event == "paper_auto_open_skipped" and isinstance(payload, dict)
    ]
    assert any(payload.get("reason") == "run_end_cutoff" for payload in skipped)


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


def test_run_bot_skips_zero_allocation_simulated_open(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("PAPER_AUTO_OPEN", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN_STARTUP_ENABLE", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN_FALLBACK_ENABLE", "0")
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
                    "signals": [{"type": "entry", "side": "buy"}],
                    "metrics": {},
                    "analysis": {"trend": "up"},
                }
            return {"signals": [], "metrics": {}, "analysis": {}}

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            self._allocations = {"Universal": 1.0}

        def route(self, state):
            return [
                {
                    "strategy": "Universal",
                    "allocation": 1.0,
                    "signal": {
                        "signals": [{"type": "entry", "side": "buy"}],
                        "metrics": {},
                        "analysis": {"trend": "up"},
                    },
                }
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
        return True, None, None, 0.0

    def fake_update_gate(net_pnl, target=0.5):
        calls["update_gate"] += 1
        return {"active": False}

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

    assert calls["apply_risk"] >= 1
    assert calls["update_gate"] >= 1
    assert calls["update_position"] == 0
    assert calls["execute_order"] == 0
    assert not any(event == "order_simulated" for event, _ in events)
    skipped = [
        payload for event, payload in events if event == "position_open_skipped"
    ]
    assert skipped
    assert any(
        payload.get("missing") == ["allocation_usdt_nonpositive", "amount_nonpositive"]
        for payload in skipped
        if isinstance(payload, dict)
    )


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


def test_run_bot_side_allowlist_blocks_foreign_symbol_strategy_side_in_paper(
    monkeypatch,
):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("ENTRY_ALLOW_BUY", "1")
    monkeypatch.setenv("ENTRY_ALLOW_SELL", "1")
    monkeypatch.setenv("ENTRY_REQUIRE_STRATEGY_NAME", "1")
    monkeypatch.setenv("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST", "ETHUSDTM:MOMENTUM:buy")
    monkeypatch.setenv("ENTRY_IGNORE_HOLD_SIGNALS", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN_STARTUP_ENABLE", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN_FALLBACK_ENABLE", "0")

    events = []

    class CaptureLogger:
        def log(self, event, payload=None):
            events.append((event, payload))

    class DummyStrategy:
        def __init__(self, *args, **kwargs):
            self.name = str(kwargs.get("name") or self.__class__.__name__)

        def analyze(self, *args, **kwargs):
            return {
                "signals": [{"type": "entry", "side": "buy"}],
                "metrics": {},
                "analysis": {"trend": "up"},
            }

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            self._allocations = {"Momentum": 1.0}

        def route(self, state):
            return [
                {
                    "strategy": "Momentum",
                    "allocation": 1.0,
                    "signal": {
                        "signals": [{"type": "entry", "side": "buy"}],
                        "metrics": {},
                        "analysis": {"trend": "up"},
                    },
                }
            ]

        def get_last_allocations(self):
            return dict(self._allocations)

    class FakeMetaRouter:
        def __init__(self, *args, **kwargs):
            self.last_decision = "Momentum"

        def route(self, state):
            return types.SimpleNamespace(name="Momentum")

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
    monkeypatch.setattr(paper_gate, "update_gate", lambda net_pnl, target=0.5: {"active": False})
    monkeypatch.setattr(db_models, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(order_exec.OrderExecutor, "execute_order", lambda self, order, use_rest=True: None)
    monkeypatch.setattr(position_mgr.PositionManager, "update_position", lambda self, symbol, order: None)
    monkeypatch.setattr(
        risk_mgr.RiskManager,
        "apply_risk",
        lambda self, signal, price, balance, position_status, pnl_history, symbol, global_pnl_history=None, open_positions=None: (True, None, None, 100.0),
    )
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
    _allowlist_reason_codes = {
        "symbol_strategy_side_allowlist",
        "symbol_strategy_side_allowlist_resolved_not_allowed",
        "symbol_strategy_side_allowlist_unresolved_identity",
    }
    assert any(
        payload.get("normalized_strategy_value") == "Momentum"
        and payload.get("normalized_side_value") == "buy"
        and payload.get("rejection_reason_code") in _allowlist_reason_codes
        for payload in rejection_traces
    )
    assert not [payload for event, payload in events if event == "position_open"]


def test_run_bot_exact_symbol_strategy_side_allowlist_overrides_broader_strategy_side_allowlist(
    monkeypatch,
):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("ENTRY_ALLOW_BUY", "1")
    monkeypatch.setenv("ENTRY_ALLOW_SELL", "1")
    monkeypatch.setenv("ENTRY_REQUIRE_STRATEGY_NAME", "1")
    monkeypatch.setenv(
        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST",
        "BTCUSDTM:TRENDFOLLOWING:buy",
    )
    monkeypatch.setenv("ENTRY_STRATEGY_SIDE_ALLOWLIST", "TRENDFOLLOWING:sell")
    monkeypatch.setenv("ENTRY_IGNORE_HOLD_SIGNALS", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN_STARTUP_ENABLE", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN_FALLBACK_ENABLE", "0")

    events = []

    class CaptureLogger:
        def log(self, event, payload=None):
            events.append((event, payload))

    class DummyStrategy:
        def __init__(self, *args, **kwargs):
            self.name = str(kwargs.get("name") or self.__class__.__name__)

        def analyze(self, *args, **kwargs):
            return {
                "signals": [{"type": "entry", "side": "buy"}],
                "metrics": {},
                "analysis": {"trend": "up"},
            }

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            self._allocations = {"TrendFollowing": 1.0}

        def route(self, state):
            return [
                {
                    "strategy": "TrendFollowing",
                    "allocation": 1.0,
                    "signal": {
                        "signals": [{"type": "entry", "side": "buy"}],
                        "metrics": {},
                        "analysis": {"trend": "up"},
                    },
                }
            ]

        def get_last_allocations(self):
            return dict(self._allocations)

    class FakeMetaRouter:
        def __init__(self, *args, **kwargs):
            self.last_decision = "TrendFollowing"

        def route(self, state):
            return types.SimpleNamespace(name="TrendFollowing")

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
    monkeypatch.setattr(
        paper_gate, "update_gate", lambda net_pnl, target=0.5: {"active": False}
    )
    monkeypatch.setattr(db_models, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(
        order_exec.OrderExecutor,
        "execute_order",
        lambda self, order, use_rest=True: None,
    )
    monkeypatch.setattr(
        position_mgr.PositionManager,
        "update_position",
        lambda self, symbol, order: None,
    )
    monkeypatch.setattr(
        risk_mgr.RiskManager,
        "apply_risk",
        lambda self, signal, price, balance, position_status, pnl_history, symbol, global_pnl_history=None, open_positions=None: (True, None, None, 100.0),
    )
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
    assert not any(
        payload.get("normalized_strategy_value") == "TrendFollowing"
        and payload.get("normalized_side_value") == "buy"
        and payload.get("rejection_reason_code") == "strategy_side_allowlist"
        for payload in rejection_traces
    )


def test_paper_auto_open_position_payload_carries_exact_allowlist_telemetry(
    monkeypatch,
):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("PAPER_AUTO_OPEN", "1")
    monkeypatch.setenv("PAPER_AUTO_OPEN_STARTUP_ENABLE", "1")
    monkeypatch.setenv("PAPER_AUTO_OPEN_FALLBACK_ENABLE", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN_REPEAT", "0")
    monkeypatch.setenv(
        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST",
        "XRPUSDTM:MOMENTUM:sell",
    )
    monkeypatch.setenv(
        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST_SOURCE",
        "strict_positive_side_allowlist",
    )
    monkeypatch.setenv(
        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST_CONTRACT_HASH",
        "A" * 64,
    )

    events = []

    class CaptureLogger:
        def log(self, event, payload=None):
            events.append((event, payload))

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
            "symbol": "XRPUSDTM",
            "timeframe": 1,
            "market_type": "futures",
        }

    import core.db_models as db_models
    import core.OrderExecutor as order_exec
    import core.PositionManager as position_mgr
    import utils.news_social_scheduler as nss
    import utils.paper_gate as paper_gate

    monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    monkeypatch.setattr(paper_gate, "update_gate", lambda *a, **k: {"active": False})
    monkeypatch.setattr(db_models, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(order_exec.OrderExecutor, "execute_order", lambda *a, **k: None)
    monkeypatch.setattr(position_mgr.PositionManager, "update_position", lambda *a, **k: None)
    monkeypatch.setattr(botcore, "load_config", fake_config)
    monkeypatch.setattr(botcore, "save_decision_to_db", lambda *a, **k: None)
    monkeypatch.setattr(botcore, "save_equity_to_db", lambda *a, **k: None)
    monkeypatch.setattr(ill, "InfinityLayerLogger", lambda: CaptureLogger())

    run_bot(simulate=True)

    position_opens = [
        payload for event, payload in events if event == "position_open"
    ]
    assert position_opens, "expected allowlisted paper auto-open"
    opened = position_opens[-1]
    assert opened.get("symbol") == "XRPUSDTM"
    assert opened.get("side") == "sell"
    assert opened.get("symbol_strategy_side_allowlist") == [
        "XRPUSDTM:MOMENTUM:sell"
    ]
    assert opened.get("strategy_allowlist") == []
    assert opened.get("strategy_side_allowlist") == []
    assert opened.get("allowlist_source") == "strict_positive_side_allowlist"
    assert opened.get("allowlist_contract_hash") == "A" * 64
    assert opened.get("allowlist_gate_decision") == "allowed"


def test_run_bot_side_allowlist_still_blocks_same_symbol_strategy_wrong_side(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("ENTRY_ALLOW_BUY", "1")
    monkeypatch.setenv("ENTRY_ALLOW_SELL", "1")
    monkeypatch.setenv("ENTRY_REQUIRE_STRATEGY_NAME", "1")
    monkeypatch.setenv("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST", "BTCUSDTM:MOMENTUM:buy")
    monkeypatch.setenv("ENTRY_IGNORE_HOLD_SIGNALS", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN_STARTUP_ENABLE", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN_FALLBACK_ENABLE", "0")

    events = []

    class CaptureLogger:
        def log(self, event, payload=None):
            events.append((event, payload))

    class DummyStrategy:
        def __init__(self, *args, **kwargs):
            self.name = str(kwargs.get("name") or self.__class__.__name__)

        def analyze(self, *args, **kwargs):
            return {
                "signals": [{"type": "entry", "side": "sell"}],
                "metrics": {},
                "analysis": {"trend": "down"},
            }

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            self._allocations = {"Momentum": 1.0}

        def route(self, state):
            return [
                {
                    "strategy": "Momentum",
                    "allocation": 1.0,
                    "signal": {
                        "signals": [{"type": "entry", "side": "sell"}],
                        "metrics": {},
                        "analysis": {"trend": "down"},
                    },
                }
            ]

        def get_last_allocations(self):
            return dict(self._allocations)

    class FakeMetaRouter:
        def __init__(self, *args, **kwargs):
            self.last_decision = "Momentum"

        def route(self, state):
            return types.SimpleNamespace(name="Momentum")

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
    monkeypatch.setattr(paper_gate, "update_gate", lambda net_pnl, target=0.5: {"active": False})
    monkeypatch.setattr(db_models, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(order_exec.OrderExecutor, "execute_order", lambda self, order, use_rest=True: None)
    monkeypatch.setattr(position_mgr.PositionManager, "update_position", lambda self, symbol, order: None)
    monkeypatch.setattr(
        risk_mgr.RiskManager,
        "apply_risk",
        lambda self, signal, price, balance, position_status, pnl_history, symbol, global_pnl_history=None, open_positions=None: (True, None, None, 100.0),
    )
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
    _allowlist_reason_codes = {
        "symbol_strategy_side_allowlist",
        "symbol_strategy_side_allowlist_resolved_not_allowed",
        "symbol_strategy_side_allowlist_unresolved_identity",
    }
    assert any(
        payload.get("normalized_strategy_value") == "Momentum"
        and payload.get("normalized_side_value") == "sell"
        and payload.get("rejection_reason_code") in _allowlist_reason_codes
        for payload in rejection_traces
    )
