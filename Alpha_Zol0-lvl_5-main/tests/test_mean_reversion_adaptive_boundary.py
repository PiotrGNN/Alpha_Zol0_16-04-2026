import pytest

from strategies.mean_reversion import MeanReversionStrategy


def test_adaptive_boundary_metrics_use_bb_width_and_ignore_static_overrides(
    monkeypatch,
):
    monkeypatch.setenv("MR_BOUNDARY_BB_PCT_OVERRIDE", "0.0001")
    monkeypatch.setenv("MR_BOUNDARY_RSI_BUFFER_OVERRIDE", "11.5")
    strategy = MeanReversionStrategy()

    result = strategy.analyze(
        symbol="XRPUSDTM",
        klines={
            "last_row": {"close": 98.3},
            "last_indicators": {
                "bb_mid": 100.0,
                "bb_std": 1.0,
                "rsi": 35.1,
                "ema_fast": 100.0,
                "ema_slow": 100.0,
            },
        },
        indicators={},
        timeframe="1m",
    )

    metrics = result["metrics"]
    expected_vol_ratio = (102.0 - 98.0) / 98.3

    assert metrics["vol_ratio"] == pytest.approx(expected_vol_ratio)
    assert metrics["bb_boundary_pct"] == pytest.approx(0.004)
    assert metrics["rsi_buffer"] == pytest.approx(5.0 + 5.0 * expected_vol_ratio)
    assert metrics["rsi_boundary_buffer"] == pytest.approx(metrics["rsi_buffer"])
    assert result["signals"]
    assert result["signals"][0]["side"] == "buy"


def test_adaptive_boundary_keeps_and_condition_for_entry():
    strategy = MeanReversionStrategy()

    result = strategy.analyze(
        symbol="XRPUSDTM",
        klines={
            "last_row": {"close": 98.3},
            "last_indicators": {
                "bb_mid": 100.0,
                "bb_std": 1.0,
                "rsi": 35.3,
                "ema_fast": 100.0,
                "ema_slow": 100.0,
            },
        },
        indicators={},
        timeframe="1m",
    )

    metrics = result["metrics"]

    assert metrics["bb_boundary_pct"] == pytest.approx(0.004)
    assert metrics["rsi_buffer"] < 5.3
    assert result["signals"] == []


def test_adaptive_boundary_clamps_low_volatility_floor():
    strategy = MeanReversionStrategy()

    boundary = strategy._adaptive_boundary_context(
        close=100.0,
        bb_upper=100.1,
        bb_lower=100.0,
    )

    assert boundary["vol_ratio"] == pytest.approx(0.001)
    assert boundary["bb_boundary_pct"] == pytest.approx(0.001)
    assert boundary["rsi_buffer"] == pytest.approx(5.005)


def test_trigger_helpers_match_runtime_boundary_snapshot():
    strategy = MeanReversionStrategy()

    snapshot = strategy._boundary_snapshot(
        close=98.3,
        bb_upper=102.0,
        bb_lower=98.0,
    )

    assert strategy._buy_trigger(
        close=98.3,
        bb_lower=98.0,
        rsi=snapshot["buy_rsi_threshold"],
        bb_upper=102.0,
    )
    assert not strategy._buy_trigger(
        close=98.3,
        bb_lower=98.0,
        rsi=snapshot["buy_rsi_threshold"] + 0.01,
        bb_upper=102.0,
    )
    assert not strategy._sell_trigger(
        close=98.3,
        bb_upper=102.0,
        rsi=snapshot["sell_rsi_threshold"] - 0.01,
        bb_lower=98.0,
    )
