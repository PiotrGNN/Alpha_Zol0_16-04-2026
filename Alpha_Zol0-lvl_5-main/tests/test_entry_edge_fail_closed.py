import pytest

from core.BotCore import (
    _evaluate_entry_edge_fail_closed_gate,
    _entry_profitability_fee_gate_enabled,
    _evaluate_entry_profitability_fee_gate,
    _paper_known_entry_execution_cost_context,
    _should_fail_closed_known_entry_execution_cost,
)


def test_known_cost_context_with_bid_ask_and_fee_rate():
    ctx = _paper_known_entry_execution_cost_context(
        price_value=1.2355,
        bid_value=1.2350,
        ask_value=1.2360,
        fee_rate_value=0.0004,
        edge_metric_value=0.0,
    )

    assert ctx["available"] is True
    assert ctx["fee_metric"] == pytest.approx(0.0008)
    assert ctx["spread_slippage_proxy_metric"] > 0.0
    assert ctx["shadow_execution_cost_total"] > 0.0
    assert ctx["shadow_edge_after_execution_cost"] < 0.0


def test_known_cost_context_fee_only_is_available():
    ctx = _paper_known_entry_execution_cost_context(
        price_value=1.2355,
        bid_value=None,
        ask_value=None,
        fee_rate_value=0.0004,
        edge_metric_value=0.0,
    )

    assert ctx["available"] is True
    assert ctx["fee_metric"] == pytest.approx(0.0008)
    assert ctx["spread_slippage_proxy_metric"] == pytest.approx(0.0)
    assert ctx["shadow_execution_cost_total"] == pytest.approx(0.0008)


def test_known_cost_context_without_fee_or_spread_is_unavailable():
    ctx = _paper_known_entry_execution_cost_context(
        price_value=1.2355,
        bid_value=None,
        ask_value=None,
        fee_rate_value=None,
        edge_metric_value=0.0,
    )

    assert ctx["available"] is False
    assert ctx["fee_metric"] == pytest.approx(0.0)
    assert ctx["spread_slippage_proxy_metric"] == pytest.approx(0.0)
    assert ctx["shadow_execution_cost_total"] == pytest.approx(0.0)


def test_fail_closed_when_known_cost_available_and_zero_expected_edge():
    known_ctx = _paper_known_entry_execution_cost_context(
        price_value=1.2355,
        bid_value=1.2350,
        ask_value=1.2360,
        fee_rate_value=0.0004,
        edge_metric_value=0.0,
    )

    should_block = _should_fail_closed_known_entry_execution_cost(
        expected_edge_after_fee=0.0,
        known_cost_context=known_ctx,
    )

    assert should_block is True


def test_fail_closed_when_known_cost_available_and_negative_expected_edge():
    known_ctx = _paper_known_entry_execution_cost_context(
        price_value=1.2355,
        bid_value=1.2350,
        ask_value=1.2360,
        fee_rate_value=0.0004,
        edge_metric_value=0.0,
    )

    should_block = _should_fail_closed_known_entry_execution_cost(
        expected_edge_after_fee=-0.0001,
        known_cost_context=known_ctx,
    )

    assert should_block is True


def test_fail_closed_does_not_block_positive_expected_edge():
    known_ctx = _paper_known_entry_execution_cost_context(
        price_value=1.2355,
        bid_value=1.2350,
        ask_value=1.2360,
        fee_rate_value=0.0004,
        edge_metric_value=0.001,
    )

    should_block = _should_fail_closed_known_entry_execution_cost(
        expected_edge_after_fee=0.0001,
        known_cost_context=known_ctx,
    )

    assert should_block is False


def test_fail_closed_does_not_block_when_known_cost_unavailable():
    known_ctx = {
        "available": False,
        "fee_metric": 0.0,
        "spread_slippage_proxy_metric": 0.0,
        "shadow_execution_cost_total": 0.0,
    }

    should_block = _should_fail_closed_known_entry_execution_cost(
        expected_edge_after_fee=0.0,
        known_cost_context=known_ctx,
    )

    assert should_block is False


def test_fail_closed_does_not_block_when_context_missing():
    should_block = _should_fail_closed_known_entry_execution_cost(
        expected_edge_after_fee=0.0,
        known_cost_context=None,
    )

    assert should_block is False


def test_fail_closed_uses_shadow_edge_when_expected_edge_missing():
    known_ctx = {
        "available": True,
        "fee_metric": 0.0008,
        "spread_slippage_proxy_metric": 0.00001,
        "shadow_execution_cost_total": 0.00081,
        "shadow_edge_after_execution_cost": -0.00081,
    }

    should_block = _should_fail_closed_known_entry_execution_cost(
        expected_edge_after_fee=None,
        known_cost_context=known_ctx,
    )

    assert should_block is True


def test_missing_expected_edge_does_not_block_when_shadow_edge_positive():
    known_ctx = {
        "available": True,
        "fee_metric": 0.0008,
        "spread_slippage_proxy_metric": 0.00001,
        "shadow_execution_cost_total": 0.00081,
        "shadow_edge_after_execution_cost": 0.00029,
    }

    should_block = _should_fail_closed_known_entry_execution_cost(
        expected_edge_after_fee=None,
        known_cost_context=known_ctx,
    )

    assert should_block is False


def test_profitability_fee_gate_rejects_when_edge_below_fee_ratio():
    result = _evaluate_entry_profitability_fee_gate(
        entry_decision="buy",
        expected_edge_after_fee=0.0005,
        fee_estimate=0.0004,
        known_cost_context={"available": True},
        fee_ratio_min=1.5,
    )

    assert result["blocked"] is True
    assert result["reason"] == "edge_below_fee_ratio_min"
    assert result["entry_edge_vs_fee_ratio"] == pytest.approx(1.25)


def test_profitability_fee_gate_accepts_when_edge_above_fee_ratio():
    result = _evaluate_entry_profitability_fee_gate(
        entry_decision="buy",
        expected_edge_after_fee=0.0010,
        fee_estimate=0.0004,
        known_cost_context={"available": True},
        fee_ratio_min=1.5,
    )

    assert result["blocked"] is False
    assert result["reason"] == "allow"
    assert result["entry_edge_vs_fee_ratio"] == pytest.approx(2.5)


def test_profitability_fee_gate_fails_closed_when_expected_edge_missing():
    result = _evaluate_entry_profitability_fee_gate(
        entry_decision="buy",
        expected_edge_after_fee=None,
        fee_estimate=None,
        known_cost_context={
            "available": True,
            "shadow_edge_after_execution_cost": -0.0009,
            "shadow_execution_cost_total": 0.0009,
        },
        fee_ratio_min=1.5,
    )

    assert result["blocked"] is True
    assert result["reason"] in {
        "missing_expected_edge_after_fee",
        "nonpositive_expected_edge_after_fee",
    }


def test_profitability_fee_gate_disable_is_paper_only():
    assert (
        _entry_profitability_fee_gate_enabled(
            live_mode=False,
            raw_value="0",
        )
        is False
    )
    assert (
        _entry_profitability_fee_gate_enabled(
            live_mode=True,
            raw_value="0",
        )
        is True
    )


def test_admission_fail_closed_blocks_negative_effective_edge() -> None:
    result = _evaluate_entry_edge_fail_closed_gate(
        entry_decision="buy",
        expected_edge_after_fee_effective=-0.001,
        entry_expected_edge_after_fee=-0.001,
        edge_zero_reason=None,
        history_ready=True,
        trade_count=10,
        min_trades_required=5,
        live_mode=False,
    )
    assert result["blocked"] is True
    assert result["reason"] == "entry_edge_nonpositive_after_fee"


def test_admission_fail_closed_blocks_zero_effective_edge() -> None:
    result = _evaluate_entry_edge_fail_closed_gate(
        entry_decision="sell",
        expected_edge_after_fee_effective=0.0,
        entry_expected_edge_after_fee=0.0,
        edge_zero_reason=None,
        history_ready=True,
        trade_count=10,
        min_trades_required=5,
        live_mode=False,
    )
    assert result["blocked"] is True
    assert result["reason"] == "entry_edge_nonpositive_after_fee"


def test_admission_fail_closed_blocks_cost_overdominance() -> None:
    result = _evaluate_entry_edge_fail_closed_gate(
        entry_decision="buy",
        expected_edge_after_fee_effective=-0.0002,
        entry_expected_edge_after_fee=-0.0002,
        edge_zero_reason="COST_MODEL_OVERDOMINANCE",
        history_ready=False,
        trade_count=2,
        min_trades_required=20,
        live_mode=False,
    )
    assert result["blocked"] is True
    assert result["reason"] == "entry_edge_cost_overdominance"


def test_admission_fail_closed_blocks_history_unready_zero_default() -> None:
    result = _evaluate_entry_edge_fail_closed_gate(
        entry_decision="buy",
        expected_edge_after_fee_effective=0.0,
        entry_expected_edge_after_fee=0.0,
        edge_zero_reason="HISTORY_UNAVAILABLE_ZERO_DEFAULT",
        history_ready=False,
        trade_count=0,
        min_trades_required=5,
        live_mode=False,
    )
    assert result["blocked"] is True
    assert result["reason"] == "entry_edge_history_unready"


def test_admission_fail_closed_blocks_history_unready_below_min_trades() -> None:
    result = _evaluate_entry_edge_fail_closed_gate(
        entry_decision="buy",
        expected_edge_after_fee_effective=0.003,
        entry_expected_edge_after_fee=0.003,
        edge_zero_reason=None,
        history_ready=False,
        trade_count=2,
        min_trades_required=20,
        live_mode=False,
    )
    assert result["blocked"] is True
    assert result["reason"] == "entry_edge_history_unready"


def test_admission_fail_closed_allows_positive_with_sufficient_history() -> None:
    result = _evaluate_entry_edge_fail_closed_gate(
        entry_decision="buy",
        expected_edge_after_fee_effective=0.004,
        entry_expected_edge_after_fee=0.004,
        edge_zero_reason=None,
        history_ready=True,
        trade_count=32,
        min_trades_required=20,
        live_mode=False,
    )
    assert result["blocked"] is False
    assert result["reason"] == "allow"


def test_admission_fail_closed_live_mode_keeps_behavior_unaffected() -> None:
    result = _evaluate_entry_edge_fail_closed_gate(
        entry_decision="buy",
        expected_edge_after_fee_effective=-0.01,
        entry_expected_edge_after_fee=-0.01,
        edge_zero_reason="COST_MODEL_OVERDOMINANCE",
        history_ready=False,
        trade_count=0,
        min_trades_required=20,
        live_mode=True,
    )
    assert result["blocked"] is False
    assert result["reason"] == "live_unaffected_noop"
