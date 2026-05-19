import types

import pandas as pd

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
from core.BotCore import run_bot
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.trend_following import TrendFollowingStrategy


def test_momentum_empty_signals_emits_no_entry_reason_code():
    strategy = MomentumStrategy()
    rows = 30
    klines = pd.DataFrame(
        {
            "open": [100.0] * rows,
            "high": [100.0] * rows,
            "low": [100.0] * rows,
            "close": [100.0] * rows,
            "volume": [1000.0] * rows,
        }
    )

    out = strategy.analyze("BTCUSDTM", klines, indicators={}, timeframe="1m")

    assert out.get("signals") == []
    analysis = out.get("analysis") or {}
    assert analysis.get("no_entry_reason_code") is not None
    assert analysis.get("strategy_condition_snapshot") is not None
    assert (analysis.get("telemetry_completeness") or {}).get("status") == "complete"


def test_trendfollowing_empty_signals_emits_no_entry_reason_code(monkeypatch):
    monkeypatch.setenv("STRATEGY_BIAS_VOTES", "0")

    strategy = TrendFollowingStrategy()
    klines = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [101.0, 101.0],
            "low": [99.0, 99.0],
            "close": [100.0, 100.0],
        }
    )
    indicators = {
        "ema_fast": pd.Series([110.0, 110.0]),
        "ema_slow": pd.Series([100.0, 100.0]),
        "rsi": pd.Series([55.0, 55.0]),
        "adx": pd.Series([10.0, 10.0]),
        "atr": pd.Series([1.0, 1.0]),
    }

    out = strategy.analyze("BTCUSDTM", klines, indicators, timeframe="1h")

    assert out.get("signals") == []
    analysis = out.get("analysis") or {}
    assert analysis.get("no_entry_reason_code") == "trendfollowing_no_entry_conditions_not_met"
    assert analysis.get("strategy_condition_snapshot") is not None
    assert (analysis.get("telemetry_completeness") or {}).get("status") == "complete"


def test_meanreversion_empty_signals_emits_no_entry_reason_code():
    strategy = MeanReversionStrategy()
    rows = 40
    klines = pd.DataFrame(
        {
            "open": [100.0] * rows,
            "high": [100.0] * rows,
            "low": [100.0] * rows,
            "close": [100.0] * rows,
            "volume": [1000.0] * rows,
        }
    )

    out = strategy.analyze("BTCUSDTM", klines, indicators={}, timeframe="1h")

    assert out.get("signals") == []
    analysis = out.get("analysis") or {}
    assert analysis.get("no_entry_reason_code") == "mean_reversion_no_entry_conditions_not_met"
    assert analysis.get("strategy_condition_snapshot") is not None
    assert (analysis.get("telemetry_completeness") or {}).get("status") == "complete"


def test_botcore_preserves_no_entry_fields_for_signals_empty_hold_ignored(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("ENTRY_ALLOW_BUY", "1")
    monkeypatch.setenv("ENTRY_ALLOW_SELL", "1")
    monkeypatch.setenv("ENTRY_REQUIRE_STRATEGY_NAME", "1")
    monkeypatch.setenv("ENTRY_IGNORE_HOLD_SIGNALS", "1")
    monkeypatch.setenv("PAPER_AUTO_OPEN", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN_STARTUP_ENABLE", "0")
    monkeypatch.setenv("PAPER_AUTO_OPEN_FALLBACK_ENABLE", "0")

    events = []

    class CaptureLogger:
        def log(self, event, payload=None):
            events.append((event, payload))

    signal_payload = {
        "signals": [],
        "metrics": {
            "signal_score": 0.3,
            "score_threshold": 0.1,
            "score_margin": 0.2,
        },
        "analysis": {
            "no_entry_reason_code": "trendfollowing_no_entry_conditions_not_met",
            "no_entry_reason_detail": "crossover_not_confirmed",
            "strategy_condition_snapshot": {
                "trend_score": 2,
                "risk_gate_ok": True,
            },
            "trend_condition_result": {"direction": 1, "momentum": 1},
            "volatility_risk_filter_result": {
                "risk_gate_ok": True,
            },
            "quality_filter_reason": None,
            "insufficient_data_reason": None,
            "model_neutrality_reason": "no_actionable_entry_or_exit",
            "regime_condition_result": "unknown",
            "trigger_condition_result": "crossover_not_confirmed",
            "telemetry_completeness": {
                "status": "complete",
                "missing_fields": [],
            },
        },
    }

    class DummyStrategy:
        def __init__(self, *args, **kwargs):
            self.name = str(kwargs.get("name") or self.__class__.__name__)

        def analyze(self, *args, **kwargs):
            return signal_payload

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            self._allocations = {"TrendFollowing": 1.0}

        def route(self, state):
            return [
                {
                    "strategy": "TrendFollowing",
                    "allocation": 1.0,
                    "signal": signal_payload,
                    "side": "hold",
                    "raw_side": "signals:empty",
                    "raw_side_source": "signal.signals",
                    "raw_action": "signals:empty",
                    "normalized_action": "hold",
                    "router_assignment_reason": "signal.signals",
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

    import core.db_models as db_models
    import core.OrderExecutor as order_exec
    import core.PositionManager as position_mgr
    import core.RiskManager as risk_mgr
    import utils.news_social_scheduler as nss
    import utils.paper_gate as paper_gate

    monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    monkeypatch.setattr(paper_gate, "update_gate", lambda *a, **k: {"active": False})
    monkeypatch.setattr(db_models, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(order_exec.OrderExecutor, "execute_order", lambda *a, **k: None)
    monkeypatch.setattr(position_mgr.PositionManager, "update_position", lambda *a, **k: None)
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

    traces = [
        payload
        for event, payload in events
        if event == "pre_entry_candidate_rejection_trace"
        and isinstance(payload, dict)
        and payload.get("rejection_reason_code") == "hold_ignored"
        and payload.get("router_assignment_reason") == "signal.signals"
    ]
    assert traces
    payload = traces[0]

    assert payload.get("no_entry_reason_code") == "trendfollowing_no_entry_conditions_not_met"
    assert payload.get("strategy_condition_snapshot") is not None
    assert payload.get("trigger_condition_result") == "crossover_not_confirmed"
    assert payload.get("raw_action") == "signals:empty"
    assert payload.get("normalized_action") == "hold"


def test_botcore_synthesizes_empty_signals_no_entry_fields_when_missing(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("ENTRY_ALLOW_BUY", "1")
    monkeypatch.setenv("ENTRY_ALLOW_SELL", "1")
    monkeypatch.setenv("ENTRY_REQUIRE_STRATEGY_NAME", "1")
    monkeypatch.setenv("ENTRY_IGNORE_HOLD_SIGNALS", "1")
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
                "signals": [],
                "metrics": {},
                "analysis": {},
            }

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            self._allocations = {"Momentum": 1.0}

        def route(self, state):
            return [
                {
                    "strategy": "Momentum",
                    "allocation": 1.0,
                    "signal": {"signals": [], "metrics": {}, "analysis": {}},
                    "side": "hold",
                    "raw_side": "signals:empty",
                    "raw_side_source": "signal.signals",
                    "raw_action": "signals:empty",
                    "normalized_action": "hold",
                    "router_assignment_reason": "signal.signals",
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

    import core.db_models as db_models
    import core.OrderExecutor as order_exec
    import core.PositionManager as position_mgr
    import core.RiskManager as risk_mgr
    import utils.news_social_scheduler as nss
    import utils.paper_gate as paper_gate

    monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    monkeypatch.setattr(paper_gate, "update_gate", lambda *a, **k: {"active": False})
    monkeypatch.setattr(db_models, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(order_exec.OrderExecutor, "execute_order", lambda *a, **k: None)
    monkeypatch.setattr(position_mgr.PositionManager, "update_position", lambda *a, **k: None)
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

    traces = [
        payload
        for event, payload in events
        if event == "pre_entry_candidate_rejection_trace"
        and isinstance(payload, dict)
        and payload.get("rejection_reason_code") == "hold_ignored"
        and payload.get("router_assignment_reason") == "signal.signals"
        and payload.get("raw_action") == "signals:empty"
    ]
    assert traces
    payload = traces[0]

    assert payload.get("no_entry_reason_code") == "momentum_empty_signals_no_entry"
    assert payload.get("strategy_condition_snapshot") is not None
    assert payload.get("telemetry_completeness", {}).get("status") == "incomplete"
    assert payload.get("telemetry_completeness", {}).get("missing_fields")
    assert payload.get("normalized_action") == "hold"
    assert not [p for e, p in events if e == "position_open"]

    # Admission semantics unchanged: no opens from hold-ignored path.
    assert not [p for e, p in events if e == "position_open"]
