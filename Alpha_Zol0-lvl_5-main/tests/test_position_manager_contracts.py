import pytest

import core.PositionManager as position_manager_module
from core.PositionManager import PositionManager


def _contract_position(symbol, side="buy", **overrides):
    position = {
        "symbol": symbol,
        "side": side,
        "amount": 1.5,
        "entry_price": 100.0,
        "timestamp": "2026-04-13T00:00:00Z",
        "strategy": "Unknown",
        "sl": 95.0,
        "tp": 120.0,
        "alpha_micro_exploration": True,
        "ai_vote": "vote-1",
        "ai_weight": 0.8,
        "trade_id": "trade-1",
        "anchor_id": "anchor-1",
        "ab_arm_id": "arm-a",
        "ab_forced_on_anchor": True,
        "open_snapshot": {"phase": "entry", "score": 0.73},
        "fee_cost_open": 0.01,
        "fee_rate_open": 0.0005,
        "execution_model_open": "maker",
        "maker_filled_open": True,
        "order_id": "order-1",
        "allocation_usdt": 150.0,
        "leverage": 2,
        "entry_main_strategy": "TrendFollowing",
        "selection_source": "entry_symbol_strategy_side_allowlist",
        "canonical_bucket": {
            "canonical_bucket_key": f"{symbol}|TREND|{side}"
        },
        "canonical_bucket_key": f"{symbol}|TREND|{side}",
        "decision_quote_open": "quote-open",
        "fill_quote_open": "quote-fill",
        "runtime_isolation_status": "none",
        "runtime_isolation_reason": "none",
        "runtime_isolation_key": "isol-key",
        "runtime_isolation_disabled_until": "2026-04-13T00:00:00Z",
    }
    position.update(overrides)
    return position


def test_position_manager_helpers_and_status_variants(monkeypatch):
    manager = PositionManager()

    assert manager.get_status() == "none"
    assert manager._snapshot_position({"symbol": "BTCUSDTM", "amount": 1}) == {
        "symbol": "BTCUSDTM",
        "amount": 1,
    }
    assert manager._snapshot_position("not-a-position") is None
    assert manager._is_zero_shaped({"amount": 0, "qty": 0, "size": 0}) is True
    assert manager._is_zero_shaped({"amount": 1, "qty": 0, "size": 0}) is False

    monkeypatch.delenv("LIVE", raising=False)
    assert manager._is_paper_trace_enabled() is True
    monkeypatch.setenv("LIVE", "1")
    assert manager._is_paper_trace_enabled() is False
    monkeypatch.delenv("LIVE", raising=False)

    with pytest.raises(ValueError, match="Position must include a symbol"):
        manager.open_position({"side": "buy", "amount": 1, "entry_price": 100.0})

    manager.update_position("MISSING", {"side": "close", "timestamp": "noop"})
    assert manager.get_position("MISSING") is None

    manager.close_position("MISSING", timestamp="noop", price=1.0)
    assert manager.get_status() == "none"

    manager.open_position(_contract_position("BTCUSDTM", side="buy"))
    manager.open_position(_contract_position("ETHUSDTM", side="sell", strategy="TrendFollowing"))

    assert manager.get_status() == {
        "BTCUSDTM": "buy",
        "ETHUSDTM": "sell",
    }


def test_position_manager_open_position_normalizes_and_copies_snapshot():
    manager = PositionManager()
    payload = _contract_position("BTCUSDTM", side="buy")

    manager.open_position(payload)
    stored = manager.get_position("BTCUSDTM")

    assert stored["strategy"] == "Universal"
    assert stored["open_snapshot"] == {"phase": "entry", "score": 0.73}
    assert stored["sl"] == 95.0
    assert stored["tp"] == 120.0
    assert stored["alpha_micro_exploration"] is True
    assert stored["ai_vote"] == "vote-1"
    assert stored["ai_weight"] == 0.8
    assert stored["trade_id"] == "trade-1"
    assert stored["anchor_id"] == "anchor-1"
    assert stored["ab_arm_id"] == "arm-a"
    assert stored["ab_forced_on_anchor"] is True

    payload["open_snapshot"]["phase"] = "mutated"
    assert stored["open_snapshot"]["phase"] == "entry"
    assert manager.get_status() == "buy"


def test_position_manager_update_position_lifecycle_recomputes_short_pnl():
    manager = PositionManager()

    manager.update_position(
        "BTCUSDTM",
        _contract_position(
            "BTCUSDTM",
            side="short",
            amount=2.0,
            price=100.0,
            timestamp="2026-04-13T00:01:00Z",
            fill_price=101.0,
            strategy="Unknown",
            decision_quote_open="quote-open-1",
            selection_source="entry_symbol_strategy_side_allowlist",
            entry_reason="initial-entry",
        ),
    )
    opened = manager.get_position("BTCUSDTM")

    assert opened["strategy"] == "Universal"
    assert opened["entry_price"] == 101.0
    assert opened["fill_price"] == 101.0
    assert opened["fee_cost_open"] == 0.01
    assert opened["fee_rate_open"] == 0.0005
    assert opened["execution_model_open"] == "maker"
    assert opened["maker_filled_open"] is True
    assert opened["entry_order_id"] == "order-1"
    assert opened["allocation_usdt"] == 150.0
    assert opened["leverage"] == 2
    assert opened["sl"] == 95.0
    assert opened["tp"] == 120.0
    assert opened["alpha_micro_exploration"] is True
    assert opened["ai_vote"] == "vote-1"
    assert opened["ai_weight"] == 0.8
    assert opened["trade_id"] == "trade-1"
    assert opened["anchor_id"] == "anchor-1"
    assert opened["ab_arm_id"] == "arm-a"
    assert opened["ab_forced_on_anchor"] is True
    assert opened["open_snapshot"] == {"phase": "entry", "score": 0.73}
    assert opened["entry_main_strategy"] == "TrendFollowing"
    assert opened["selection_source"] == "entry_symbol_strategy_side_allowlist"
    assert opened["canonical_bucket_key"] == "BTCUSDTM|TREND|short"
    assert opened["canonical_bucket"]["canonical_bucket_key"] == "BTCUSDTM|TREND|short"
    assert opened["decision_quote_open"] == "quote-open-1"
    assert opened["entry_reason"] == "initial-entry"

    manager.update_position(
        "BTCUSDTM",
        {
            "side": "short",
            "amount": 3.0,
            "fill_price": 102.5,
            "timestamp": "2026-04-13T00:02:00Z",
            "strategy": "TrendFollowing",
            "alpha_micro_exploration": False,
            "ab_forced_on_anchor": False,
            "decision_quote_close": "quote-close-1",
            "fill_quote_close": "quote-fill-close-1",
            "router_top1": "momentum",
            "router_top2": "mean_reversion",
            "router_weight_top1": 0.65,
            "router_weight_top2": 0.35,
            "router_lead_margin": 0.3,
            "runtime_isolation_status": "isolated",
        },
    )
    mutated = manager.get_position("BTCUSDTM")

    assert mutated["amount"] == 3.0
    assert mutated["entry_price"] == 102.5
    assert mutated["fill_price"] == 102.5
    assert mutated["strategy"] == "TrendFollowing"
    assert mutated["fee_cost_open"] == 0.01
    assert mutated["fee_rate_open"] == 0.0005
    assert mutated["execution_model_open"] == "maker"
    assert mutated["maker_filled_open"] is True
    assert mutated["entry_order_id"] == "order-1"
    assert mutated["allocation_usdt"] == 150.0
    assert mutated["leverage"] == 2
    assert mutated["sl"] == 95.0
    assert mutated["tp"] == 120.0
    assert mutated["alpha_micro_exploration"] is False
    assert mutated["ab_forced_on_anchor"] is False
    assert mutated["ai_vote"] == "vote-1"
    assert mutated["ai_weight"] == 0.8
    assert mutated["trade_id"] == "trade-1"
    assert mutated["anchor_id"] == "anchor-1"
    assert mutated["ab_arm_id"] == "arm-a"
    assert mutated["open_snapshot"] == {"phase": "entry", "score": 0.73}
    assert mutated["decision_quote_close"] == "quote-close-1"
    assert mutated["fill_quote_close"] == "quote-fill-close-1"
    assert mutated["router_top1"] == "momentum"
    assert mutated["router_top2"] == "mean_reversion"
    assert mutated["router_weight_top1"] == 0.65
    assert mutated["router_weight_top2"] == 0.35
    assert mutated["router_lead_margin"] == 0.3
    assert mutated["runtime_isolation_status"] == "isolated"
    assert mutated["selection_source"] == "entry_symbol_strategy_side_allowlist"
    assert mutated["canonical_bucket_key"] == "BTCUSDTM|TREND|short"
    assert mutated["canonical_bucket"]["canonical_bucket_key"] == "BTCUSDTM|TREND|short"

    manager.update_position(
        "BTCUSDTM",
        {
            "side": "close",
            "price": 95.0,
            "timestamp": "2026-04-13T00:03:00Z",
        },
    )

    assert manager.get_position("BTCUSDTM") is None
    assert len(manager.closed) == 1
    closed = manager.closed[0]
    assert closed["close_price"] == 95.0
    assert closed["close_timestamp"] == "2026-04-13T00:03:00Z"
    assert closed["realized_pnl"] == pytest.approx((102.5 - 95.0) * 3.0)
    assert closed["side"] == "short"


def test_position_manager_close_position_survives_logging_and_caller_failures(
    monkeypatch,
):
    manager = PositionManager()
    manager.open_position(
        _contract_position(
            "ETHUSDTM",
            side="buy",
            strategy="TrendFollowing",
            amount=1.0,
            entry_price=100.0,
            timestamp="2026-04-13T00:04:00Z",
        )
    )

    def boom_stack(*args, **kwargs):
        raise RuntimeError("inspect-stack-boom")

    def boom_info(*args, **kwargs):
        raise RuntimeError("logging-info-boom")

    monkeypatch.setattr(position_manager_module.inspect, "stack", boom_stack)
    monkeypatch.setattr(position_manager_module.logging, "info", boom_info)

    manager.close_position(
        {"symbol": "ETHUSDTM"},
        timestamp="2026-04-13T00:05:00Z",
        price=110.0,
        realized_pnl=7.5,
        fee_cost=0.2,
        funding_cost=0.3,
    )

    assert manager.get_position("ETHUSDTM") is None
    assert len(manager.closed) == 1
    closed = manager.closed[0]
    assert closed["close_price"] == 110.0
    assert closed["close_timestamp"] == "2026-04-13T00:05:00Z"
    assert closed["realized_pnl"] == 7.5
    assert closed["fee_cost"] == 0.2
    assert closed["funding_cost"] == 0.3


def test_position_manager_close_position_computes_short_realized_pnl():
    manager = PositionManager()

    manager.open_position(
        _contract_position(
            "BTCUSDTM",
            side="short",
            strategy="TrendFollowing",
            amount=2.0,
            entry_price=100.0,
            timestamp="2026-04-13T00:06:00Z",
        )
    )

    manager.close_position(
        "BTCUSDTM",
        timestamp="2026-04-13T00:07:00Z",
        price=95.0,
    )

    assert manager.get_position("BTCUSDTM") is None
    assert len(manager.closed) == 1
    closed = manager.closed[0]
    assert closed["close_price"] == 95.0
    assert closed["close_timestamp"] == "2026-04-13T00:07:00Z"
    assert closed["realized_pnl"] == pytest.approx((100.0 - 95.0) * 2.0)
