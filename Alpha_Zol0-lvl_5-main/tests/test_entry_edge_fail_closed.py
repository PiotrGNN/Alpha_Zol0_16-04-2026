import pytest

from core.BotCore import (
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
