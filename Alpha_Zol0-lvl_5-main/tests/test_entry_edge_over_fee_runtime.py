import pytest

from core.BotCore import (
    _build_entry_edge_over_fee_no_history_status,
    _paper_known_entry_execution_cost_context,
    _resolve_entry_edge_profit_metric_fields,
    _resolve_entry_edge_status_fields,
    _select_entry_edge_status_source,
    _should_fail_closed_known_entry_execution_cost,
)


def test_known_entry_execution_cost_context_includes_nonzero_spread_from_bid_ask():
    payload = _paper_known_entry_execution_cost_context(
        price_value=1.2355,
        bid_value=1.235,
        ask_value=1.236,
        fee_rate_value=0.0004,
        edge_metric_value=0.0,
    )

    assert payload["available"] is True
    assert payload["spread_slippage_proxy_metric"] > 0.0
    assert payload["shadow_execution_cost_total"] > 0.0


def test_known_entry_execution_cost_context_includes_round_trip_fee():
    payload = _paper_known_entry_execution_cost_context(
        price_value=1.2355,
        bid_value=1.235,
        ask_value=1.236,
        fee_rate_value=0.0004,
        edge_metric_value=0.0,
    )

    assert payload["available"] is True
    assert payload["fee_metric"] == 0.0008


def test_should_fail_closed_known_execution_cost_for_zero_edge():
    payload = _paper_known_entry_execution_cost_context(
        price_value=1.2355,
        bid_value=1.235,
        ask_value=1.236,
        fee_rate_value=0.0004,
        edge_metric_value=0.0,
    )

    assert (
        _should_fail_closed_known_entry_execution_cost(
            expected_edge_after_fee=0.0,
            known_cost_context=payload,
        )
        is True
    )


def test_should_fail_closed_known_execution_cost_prevents_history_fail_open_override():
    payload = _paper_known_entry_execution_cost_context(
        price_value=1.2355,
        bid_value=1.235,
        ask_value=1.236,
        fee_rate_value=0.0004,
        edge_metric_value=0.0,
    )

    assert payload["available"] is True
    assert payload["shadow_execution_cost_total"] > 0.0
    assert (
        _should_fail_closed_known_entry_execution_cost(
            expected_edge_after_fee=0.0,
            known_cost_context=payload,
        )
        is True
    )


def test_build_entry_edge_over_fee_no_history_status_is_deterministic():
    status = _build_entry_edge_over_fee_no_history_status(
        symbol_name="XRPUSDTM",
        strategy_name="Momentum",
        side_name="sell",
        window=16,
        min_trades=4,
        threshold=0.0008,
        trade_count=0,
        selected_snapshot={"trade_count": 0, "mean_gross_fill_model": None},
        snapshot_primary={"trade_count": 0},
        snapshot_fallback=None,
        trade_count_primary=0,
        trade_count_fallback=0,
        bucket_key_primary="XRPUSDTM|MOMENTUM|sell",
        bucket_key_fallback="XRPUSDTM|__ALL__|sell",
        bucket_used_final="primary",
        canonical_shadow={
            "canonical_shadow_trade_count": 0,
            "canonical_shadow_history_ready": False,
            "canonical_shadow_last_update_ts": None,
        },
        mean_gross=0.0,
        mean_fee=0.0,
        mean_spread_slippage_proxy=0.0,
        edge_over_fee=0.0,
        shadow_execution_cost_total=0.0,
        shadow_edge_after_execution_cost=None,
    )

    assert status["enabled"] is True
    assert status["history_ready"] is False
    assert status["reason"] == "insufficient_history"
    assert status["edge_build_status"] == "history_unavailable_no_snapshot"
    assert status["edge_zero_reason"] == "HISTORY_UNAVAILABLE_ZERO_DEFAULT"
    assert status["expected_edge_after_fee_effective"] == 0.0
    assert status["entry_expected_edge_after_fee"] == 0.0
    assert status["fee_estimate"] == 0.0
    assert status["gross_edge_before_fee_effective"] is None
    assert status["mean_edge_over_fee"] == 0.0
    assert status["shadow_edge_after_execution_cost"] == 0.0
    assert status["canonical_shadow_trade_count"] == 0


def test_build_entry_edge_over_fee_no_history_status_emits_edge_fields_from_fallback():
    status = _build_entry_edge_over_fee_no_history_status(
        symbol_name="BTCUSDTM",
        strategy_name="TrendFollowing",
        side_name="buy",
        window=16,
        min_trades=4,
        threshold=0.0008,
        trade_count=0,
        selected_snapshot={"trade_count": 0, "mean_gross_fill_model": None},
        snapshot_primary={"trade_count": 0},
        snapshot_fallback=None,
        trade_count_primary=0,
        trade_count_fallback=0,
        bucket_key_primary="BTCUSDTM|TRENDFOLLOWING|buy",
        bucket_key_fallback="BTCUSDTM|__ALL__|buy",
        bucket_used_final="primary",
        canonical_shadow={
            "canonical_shadow_trade_count": 0,
            "canonical_shadow_history_ready": False,
            "canonical_shadow_last_update_ts": None,
        },
        mean_gross=0.0,
        mean_fee=0.0,
        mean_spread_slippage_proxy=0.0,
        edge_over_fee=-0.0012,
        shadow_execution_cost_total=0.0008,
        shadow_edge_after_execution_cost=-0.0012,
    )

    assert status["entry_expected_edge_after_fee"] == pytest.approx(-0.0012)
    assert status["expected_edge_after_fee_effective"] == pytest.approx(-0.0012)
    assert status["fee_estimate"] == pytest.approx(0.0008)


def test_select_entry_edge_status_source_uses_canonical_on_exact_primary_match():
    result = _select_entry_edge_status_source(
        bucket_key_primary="BTCUSDTM|MOMENTUM|sell",
        bucket_used_final="primary",
        production_trade_count=0,
        canonical_key_read="BTCUSDTM|MOMENTUM|sell",
        canonical_shadow_trade_count=3,
        min_trades=20,
    )

    assert result["selected_snapshot_source"] == "canonical_shadow"
    assert result["status_trade_count"] == 3
    assert result["status_history_ready"] is False
    assert result["canonical_status_takeover"] is True
    assert result["exact_primary_key_match"] is True


def test_select_entry_edge_status_source_preserves_no_history_when_canonical_missing():
    result = _select_entry_edge_status_source(
        bucket_key_primary="XRPUSDTM|UNIVERSAL|sell",
        bucket_used_final="primary",
        production_trade_count=0,
        canonical_key_read="XRPUSDTM|UNIVERSAL|sell",
        canonical_shadow_trade_count=0,
        min_trades=20,
    )

    assert result["selected_snapshot_source"] == "production_snapshot_primary"
    assert result["status_trade_count"] == 0
    assert result["status_history_ready"] is False
    assert result["canonical_status_takeover"] is False
    assert result["exact_primary_key_match"] is True


def test_select_entry_edge_status_source_requires_exact_key_match_for_takeover():
    result = _select_entry_edge_status_source(
        bucket_key_primary="BTCUSDTM|MOMENTUM|sell",
        bucket_used_final="primary",
        production_trade_count=0,
        canonical_key_read="BTCUSDTM|MOMENTUM|buy",
        canonical_shadow_trade_count=3,
        min_trades=20,
    )

    assert result["selected_snapshot_source"] == "production_snapshot_primary"
    assert result["status_trade_count"] == 0
    assert result["status_history_ready"] is False
    assert result["canonical_status_takeover"] is False
    assert result["exact_primary_key_match"] is False


def test_resolve_entry_edge_status_fields_uses_canonical_shadow_for_btc_family():
    result = _resolve_entry_edge_status_fields(
        bucket_key_primary="BTCUSDTM|MOMENTUM|sell",
        bucket_used_final="primary",
        production_trade_count=0,
        canonical_key_read="BTCUSDTM|MOMENTUM|sell",
        canonical_shadow_trade_count=3,
        min_trades=20,
        mean_gross=0.0,
        shadow_edge_after_execution_cost=0.0,
    )

    assert result["selected_snapshot_source"] == "canonical_shadow"
    assert result["history_count_used"] == 3
    assert result["history_ready"] is False
    assert result["edge_build_status"] == "history_materialized"
    assert result["edge_zero_reason"] == "TRUE_ZERO_GROSS_EDGE"
    assert result["canonical_status_takeover"] is True
    assert result["exact_primary_key_match"] is True
    assert result["canonical_key_read"] == "BTCUSDTM|MOMENTUM|sell"


def test_resolve_entry_edge_status_fields_keeps_universal_absence_noncanonical():
    result = _resolve_entry_edge_status_fields(
        bucket_key_primary="XRPUSDTM|UNIVERSAL|sell",
        bucket_used_final="primary",
        production_trade_count=0,
        canonical_key_read="XRPUSDTM|UNIVERSAL|sell",
        canonical_shadow_trade_count=0,
        min_trades=20,
        mean_gross=0.0,
        shadow_edge_after_execution_cost=0.0,
    )

    assert result["selected_snapshot_source"] == "production_snapshot_primary"
    assert result["history_count_used"] == 0
    assert result["history_ready"] is False
    assert result["edge_build_status"] == "history_unavailable_no_snapshot"
    assert result["edge_zero_reason"] == "HISTORY_UNAVAILABLE_ZERO_DEFAULT"
    assert result["canonical_status_takeover"] is False
    assert result["exact_primary_key_match"] is True
    assert result["canonical_key_read"] == "XRPUSDTM|UNIVERSAL|sell"


def test_resolve_entry_edge_profit_metric_fields_uses_canonical_shadow_for_btc():
    canonical_shadow = {
        "canonical_key_read": "BTCUSDTM|MOMENTUM|sell",
        "canonical_shadow_trade_count": 3,
        "shadow_bucket": {
            "gross_hist": [
                -0.10327149603535532,
                0.034947757678444845,
                -0.14522662082146323,
            ],
            "fee_hist": [0.0, 0.0, 0.0],
            "slippage_hist": [0.0, 0.0, 0.0],
        },
    }

    result = _resolve_entry_edge_profit_metric_fields(
        bucket_key_primary="BTCUSDTM|MOMENTUM|sell",
        bucket_used_final="primary",
        production_snapshot={"trade_count": 0, "mean_gross_fill_model": 0.0},
        canonical_shadow=canonical_shadow,
        min_trades=20,
    )

    assert result["selected_profit_metric_source"] == "canonical_shadow"
    assert result["profit_metric_takeover"] is True
    assert result["profit_metric_exact_primary_key_match"] is True
    assert result["profit_metric_canonical_key_read"] == "BTCUSDTM|MOMENTUM|sell"
    assert result["trade_count"] == 3
    assert result["history_ready"] is False
    assert result["mean_gross"] == -0.0711834530594579
    assert result["mean_fee"] == 0.0
    assert result["mean_spread_slippage_proxy"] == 0.0
    assert result["edge_over_fee"] == -0.0711834530594579
    assert result["expected_edge_after_fee"] == -0.0711834530594579
    assert result["shadow_edge_after_execution_cost"] == -0.0711834530594579
    assert result["shadow_execution_cost_total"] == 0.0
    assert (
        _should_fail_closed_known_entry_execution_cost(
            expected_edge_after_fee=result["expected_edge_after_fee"],
            known_cost_context={
                "available": True,
                "shadow_edge_after_execution_cost": result[
                    "shadow_edge_after_execution_cost"
                ],
            },
        )
        is True
    )


def test_resolve_entry_edge_profit_metric_fields_keeps_universal_absence_noncanonical():
    result = _resolve_entry_edge_profit_metric_fields(
        bucket_key_primary="XRPUSDTM|UNIVERSAL|sell",
        bucket_used_final="primary",
        production_snapshot={"trade_count": 0, "mean_gross_fill_model": 0.0},
        canonical_shadow={
            "canonical_key_read": "XRPUSDTM|UNIVERSAL|sell",
            "canonical_shadow_trade_count": 0,
            "shadow_bucket": None,
        },
        min_trades=20,
    )

    assert result["selected_profit_metric_source"] == "production_snapshot_primary"
    assert result["profit_metric_takeover"] is False
    assert result["profit_metric_exact_primary_key_match"] is True
    assert result["profit_metric_canonical_key_read"] == "XRPUSDTM|UNIVERSAL|sell"
    assert result["trade_count"] == 0
    assert result["history_ready"] is False
    assert result["edge_over_fee"] == 0.0
    assert result["expected_edge_after_fee"] == 0.0
    assert result["shadow_edge_after_execution_cost"] == 0.0
