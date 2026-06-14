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
from core.BotCore import run_bot, should_apply_universal_hold_passthrough


def test_universal_hold_passthrough_helper_respects_live_mode():
    assert (
        should_apply_universal_hold_passthrough(
            strategy_name="Universal",
            explicit_hold_side=True,
            universal_hold_passthrough_enabled=True,
            live_mode=False,
        )
        is True
    )
    assert (
        should_apply_universal_hold_passthrough(
            strategy_name="Universal",
            explicit_hold_side=True,
            universal_hold_passthrough_enabled=True,
            live_mode=True,
        )
        is False
    )


def _run_with_universal_hold(
    monkeypatch,
    passthrough_enabled: bool,
    router_strategy: str = "Universal",
    router_signal: dict | None = None,
    meta_strategy: str = "Universal",
    router_candidate_overrides: dict | None = None,
):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("ENTRY_IGNORE_HOLD_SIGNALS", "1")
    monkeypatch.setenv("ENTRY_ALLOW_BUY", "1")
    monkeypatch.setenv("ENTRY_ALLOW_SELL", "1")
    monkeypatch.setenv("ENTRY_REQUIRE_STRATEGY_NAME", "1")
    monkeypatch.setenv(
        "UNIVERSAL_HOLD_PASSTHROUGH_ENABLE",
        "1" if passthrough_enabled else "0",
    )

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
                    "signals": [{"type": "wait", "side": "hold"}],
                    "metrics": {"open": 1.0, "close": 1.0},
                    "analysis": {"trend": "flat"},
                    "type": "hold",
                }
            return {"signals": [], "metrics": {}, "analysis": {}}

    class FakeRouter:
        def __init__(self, *args, **kwargs):
            self._allocations = {router_strategy: 1.0}

        def route(self, state):
            candidate = {
                "strategy": router_strategy,
                "allocation": 1.0,
                "signal": router_signal or {
                    "signals": [{"type": "wait", "side": "hold"}],
                    "metrics": {"open": 1.0, "close": 1.0},
                    "analysis": {"trend": "flat"},
                    "type": "hold",
                },
            }
            if router_candidate_overrides:
                candidate.update(router_candidate_overrides)
            return [candidate]

        def get_last_allocations(self):
            return dict(self._allocations)

    class FakeMetaRouter:
        def __init__(self, *args, **kwargs):
            self.last_decision = meta_strategy

        def route(self, state):
            return types.SimpleNamespace(name=meta_strategy)

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
        paper_gate,
        "update_gate",
        lambda net_pnl, target=0.5: {"active": False},
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
        lambda self,
        signal,
        price,
        balance,
        position_status,
        pnl_history,
        symbol,
        global_pnl_history=None,
        open_positions=None: (True, None, None, 100.0),
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


def test_universal_explicit_hold_default_behavior_unchanged(monkeypatch):
    events = _run_with_universal_hold(monkeypatch, passthrough_enabled=False)
    rejection_traces = [
        payload
        for event, payload in events
        if event == "pre_entry_candidate_rejection_trace"
    ]
    assert any(
        payload.get("normalized_strategy_value") == "Universal"
        and payload.get("rejection_reason_code") == "hold_ignored"
        for payload in rejection_traces
        if isinstance(payload, dict)
    )
    assert not any(event == "universal_hold_passthrough" for event, _ in events)


def test_universal_explicit_hold_passthrough_applies_in_paper(monkeypatch):
    events = _run_with_universal_hold(monkeypatch, passthrough_enabled=True)
    passthrough = [
        payload
        for event, payload in events
        if event == "universal_hold_passthrough" and isinstance(payload, dict)
    ]
    assert passthrough
    assert any(
        payload.get("universal_hold_passthrough_applied") is True
        for payload in passthrough
    )

    rejection_traces = [
        payload
        for event, payload in events
        if event == "pre_entry_candidate_rejection_trace" and isinstance(payload, dict)
    ]
    assert not any(
        payload.get("normalized_strategy_value") == "Universal"
        and payload.get("rejection_reason_code") == "hold_ignored"
        for payload in rejection_traces
    )


def test_bias_vote_nested_side_is_not_trade_candidate_by_default(monkeypatch):
    monkeypatch.delenv("ROUTER_BIAS_SIGNALS_AS_ENTRY", raising=False)
    events = _run_with_universal_hold(
        monkeypatch,
        passthrough_enabled=False,
        router_strategy="Momentum",
        router_signal={
            "signals": [{"type": "bias", "side": "buy", "reason": "unit"}],
            "metrics": {"open": 1.0, "close": 1.0},
            "analysis": {},
        },
        meta_strategy="Momentum",
        router_candidate_overrides={
            "raw_side": "bias:buy",
            "raw_side_source": "signal.type:bias_non_entry",
        },
    )
    rejection_traces = [
        payload
        for event, payload in events
        if event == "pre_entry_candidate_rejection_trace" and isinstance(payload, dict)
    ]

    assert any(
        payload.get("normalized_strategy_value") == "Momentum"
        and payload.get("normalized_side_value") == "hold"
        and payload.get("rejection_reason_code") == "ambiguous_hold_side"
        for payload in rejection_traces
    )
    assert not [payload for event, payload in events if event == "position_open"]


def test_bias_vote_is_not_promoted_by_hold_side_fallback(monkeypatch):
    monkeypatch.delenv("ROUTER_BIAS_SIGNALS_AS_ENTRY", raising=False)
    monkeypatch.setenv("TRADE_UNBLOCK_ENABLE_HOLD_SIDE_FALLBACK", "1")
    events = _run_with_universal_hold(
        monkeypatch,
        passthrough_enabled=False,
        router_strategy="Momentum",
        router_signal={
            "signals": [{"type": "bias", "side": "buy", "reason": "unit"}],
            "metrics": {"open": 1.0, "close": 1.0},
            "analysis": {},
        },
        meta_strategy="Momentum",
        router_candidate_overrides={
            "raw_side": "bias:buy",
            "raw_side_source": "signal.type:bias_non_entry",
        },
    )
    rejection_traces = [
        payload
        for event, payload in events
        if event == "pre_entry_candidate_rejection_trace" and isinstance(payload, dict)
    ]

    assert any(
        payload.get("normalized_strategy_value") == "Momentum"
        and payload.get("normalized_side_value") == "hold"
        and payload.get("rejection_reason_code") == "ambiguous_hold_side"
        for payload in rejection_traces
    )
    assert not [payload for event, payload in events if event == "position_open"]
