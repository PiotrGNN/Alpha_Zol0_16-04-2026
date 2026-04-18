from core.execution_snapshot import _safe_float, build_execution_snapshot


def test_build_execution_snapshot_rejects_invalid_side():
    assert build_execution_snapshot("hold", 100.0, {}) is None


def test_safe_float_rejects_bad_and_non_finite_values():
    assert _safe_float("not-a-number") is None
    assert _safe_float(float("inf")) is None


def test_build_execution_snapshot_buy_uses_quote_values_and_top_of_book_quality():
    snapshot = build_execution_snapshot(
        "buy",
        100.0,
        decision_quote={
            "bid": 99.0,
            "ask": 101.0,
            "bid_size": 1.2,
            "ask_size": 1.4,
            "bid_size_source": "book_size_measured",
        },
        fallback_price=88.0,
        maker_fee_rate=0.001,
        taker_fee_rate=0.01,
        mean_gross_fill_model=5.0,
    )

    assert snapshot is not None
    assert snapshot["mid"] == 100.0
    assert snapshot["spread_abs"] == 2.0
    assert snapshot["spread_pct"] == 0.02
    assert snapshot["top_of_book_size"] == 1.4
    assert snapshot["expected_open_price"] == 101.0
    assert snapshot["expected_close_price"] == 99.0
    assert snapshot["expected_fee_total"] == 2.0
    assert snapshot["slippage_proxy_total"] == 2.0
    assert snapshot["execution_cost_total_realtime"] == 4.0
    assert snapshot["edge_after_realtime_cost"] == 1.0
    assert snapshot["source_quality"] == "top_of_book"
    assert snapshot["snapshot_method"] == "decision_quote_round_trip_taker_touch"
    assert snapshot["diagnostic_only"] is True


def test_build_execution_snapshot_sell_uses_fallback_mid_and_full_depth_quality():
    snapshot = build_execution_snapshot(
        "sell",
        50.0,
        decision_quote={
            "depth_top5": 9.5,
            "bid_size": 0.7,
        },
        fallback_price=200.0,
        taker_fee_rate=0.02,
        mean_gross_fill_model=10.0,
    )

    assert snapshot is not None
    assert snapshot["mid"] == 200.0
    assert snapshot["spread_abs"] is None
    assert snapshot["spread_pct"] is None
    assert snapshot["depth_top5"] == 9.5
    assert snapshot["top_of_book_size"] == 0.7
    assert snapshot["expected_open_price"] == 200.0
    assert snapshot["expected_close_price"] == 200.0
    assert snapshot["expected_fee_total"] == 2.0
    assert snapshot["slippage_proxy_total"] == 0.0
    assert snapshot["execution_cost_total_realtime"] == 2.0
    assert snapshot["edge_after_realtime_cost"] == 8.0
    assert snapshot["source_quality"] == "full_depth"


def test_build_execution_snapshot_uses_proxy_quality_when_size_source_is_missing():
    snapshot = build_execution_snapshot(
        "buy",
        25.0,
        decision_quote={
            "bid": 9.0,
            "ask": 11.0,
            "bid_size": 2.0,
            "ask_size": 3.0,
        },
        fallback_price=10.0,
        taker_fee_rate=0.01,
    )

    assert snapshot is not None
    assert snapshot["source_quality"] == "proxy"
