import types

import pytest

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


def _run_with_single_signal_router(monkeypatch, strategy_name, signal_payload):
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
            return signal_payload

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            self._allocations = {strategy_name: 1.0}

        def route(self, state):
            return [
                {
                    "strategy": strategy_name,
                    "allocation": 1.0,
                    "signal": signal_payload,
                    "side": "hold",
                    "raw_side": "hold",
                    "raw_side_source": "signal.side",
                    "raw_action": "hold",
                    "normalized_action": "hold",
                    "router_assignment_reason": "signal.side",
                }
            ]

        def get_last_allocations(self):
            return dict(self._allocations)

    class FakeMetaRouter:
        def __init__(self, *args, **kwargs):
            self.last_decision = strategy_name

        def route(self, state):
            return types.SimpleNamespace(name=strategy_name)

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
    return events


def _find_hold_trace(events, strategy_name):
    traces = [
        payload
        for event, payload in events
        if event == "pre_entry_candidate_rejection_trace"
        and isinstance(payload, dict)
        and payload.get("normalized_strategy_value") == strategy_name
        and payload.get("rejection_reason_code") == "hold_ignored"
    ]
    assert traces, f"expected hold_ignored trace for {strategy_name}"
    return traces[0]


def test_momentum_hold_emits_decision_surface_telemetry(monkeypatch):
    signal_payload = {
        "signals": [
            {
                "type": "hold",
                "side": "hold",
                "reason": "momentum_buy_paper_quality_filter",
                "signal_score": 0.32,
            }
        ],
        "metrics": {
            "signal_score": 0.32,
            "paper_buy_min_signal_score": 0.55,
        },
        "analysis": {"trend": "up", "regime": "mixed"},
    }
    events = _run_with_single_signal_router(monkeypatch, "Momentum", signal_payload)
    payload = _find_hold_trace(events, "Momentum")

    assert payload.get("hold_source") in {
        "HOLD_FROM_SCORE_BELOW_THRESHOLD",
        "HOLD_FROM_STRATEGY_SIGNAL",
    }
    assert payload.get("hold_reason_detail") == "momentum_buy_paper_quality_filter"
    assert payload.get("raw_action") == "hold"
    assert payload.get("normalized_action") == "hold"
    assert payload.get("raw_side") == "hold"
    assert payload.get("normalized_side") == "hold"
    assert payload.get("signal_score") == 0.32
    assert payload.get("score_threshold") == 0.55
    assert payload.get("score_margin") == pytest.approx(-0.23, abs=1e-9)
    assert payload.get("confidence") is not None
    assert payload.get("model_vote") == "hold"
    assert payload.get("strategy_vote") == "hold"
    assert payload.get("trend_state") == "up"
    assert payload.get("regime_state") == "mixed"
    assert payload.get("prefilter_reason") == "hold_ignored"
    assert payload.get("telemetry_completeness", {}).get("status") in {
        "complete",
        "incomplete",
    }

    # Semantic guard: hold remains blocked in PAPER pre-entry path.
    assert not [p for e, p in events if e == "position_open"]


def test_trendfollowing_hold_marks_incomplete_telemetry(monkeypatch):
    signal_payload = {
        "signals": [{"type": "hold", "side": "hold", "reason": "no_actionable_entry"}],
        "metrics": {},
        "analysis": {"trend": {"direction": "down", "strength": "weak"}},
    }
    events = _run_with_single_signal_router(
        monkeypatch,
        "TrendFollowing",
        signal_payload,
    )
    payload = _find_hold_trace(events, "TrendFollowing")

    assert payload.get("raw_action") == "hold"
    assert payload.get("normalized_action") == "hold"
    assert payload.get("normalized_side") == "hold"
    completeness = payload.get("telemetry_completeness") or {}
    assert completeness.get("status") == "incomplete"
    missing = set(completeness.get("missing_fields") or [])
    assert "signal_score" in missing
    assert payload.get("score_threshold") == 2.0
    assert payload.get("regime_state") == "unknown"
    assert payload.get("model_vote") == "hold"
    assert payload.get("strategy_vote") == "hold"


def test_meanreversion_hold_empty_router_path_emits_diagnostic_fields(monkeypatch):
    signal_payload = {
        "signals": [],
        "metrics": {
            "price_dist_to_bb_lower_std": 0.42,
            "price": 100.0,
        },
        "analysis": {
            "mean": 99.5,
            "std": 1.0,
            "current_price": 100.0,
        },
    }
    events = _run_with_single_signal_router(
        monkeypatch,
        "MeanReversion",
        signal_payload,
    )
    payload = _find_hold_trace(events, "MeanReversion")

    assert payload.get("raw_action") in {"hold", "signals:empty"}
    assert payload.get("normalized_action") == "hold"
    assert payload.get("raw_side") in {"hold", "signals:empty"}
    assert payload.get("normalized_side") == "hold"
    assert payload.get("signal_score") == pytest.approx(0.42, abs=1e-9)
    assert payload.get("score_threshold") == pytest.approx(0.0, abs=1e-9)
    assert payload.get("score_margin") == pytest.approx(0.42, abs=1e-9)
    assert payload.get("trend_state") in {"above_mean", "below_mean", "at_mean"}
