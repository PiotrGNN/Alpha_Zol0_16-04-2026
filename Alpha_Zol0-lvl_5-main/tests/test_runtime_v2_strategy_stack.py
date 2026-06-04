from core.runtime_v2.contracts import FeatureFrame
from core.runtime_v2.strategy_stack import MeanReversionV2, StrategyStack
import pytest


def _feature(*, ret_1: float, ret_3: float, vol: float) -> FeatureFrame:
    return FeatureFrame(
        symbol="BTCUSDTM",
        ts_ms=1,
        mid=100.0,
        ret_1=ret_1,
        ret_3=ret_3,
        volatility=vol,
        spread_bps=5.0,
        has_profile=True,
        sample_count=50,
    )


def test_strategy_stack_returns_complete_fields_for_all_strategies():
    stack = StrategyStack()
    signals = stack.evaluate(_feature(ret_1=0.0012, ret_3=0.0025, vol=0.0008))
    assert len(signals) == 4
    for signal in signals:
        assert signal.strategy
        assert signal.direction in {"buy", "sell", "hold"}
        assert isinstance(signal.score, float)
        assert 0.0 <= signal.confidence <= 1.0
        assert isinstance(signal.expected_move, float)
        assert signal.reason_code


def test_strategy_stack_no_signal_is_deterministic_hold():
    stack = StrategyStack()
    signals = stack.evaluate(_feature(ret_1=0.0, ret_3=0.0, vol=0.0005))
    assert len(signals) == 4
    assert all(signal.direction == "hold" for signal in signals)
    reason_codes = [signal.reason_code for signal in signals]
    assert reason_codes == [
        "trendfollowing_no_trend",
        "momentum_no_impulse",
        "meanrev_no_extreme",
        "universal_neutral",
    ]


def test_meanreversion_default_keeps_ret3_horizon3_calibration(monkeypatch):
    monkeypatch.delenv("V2_MEANREV_H10_CALIBRATION_ENABLE", raising=False)
    signal = MeanReversionV2().evaluate(_feature(ret_1=0.0, ret_3=0.0010, vol=0.0005))

    assert signal.direction == "sell"
    assert signal.expected_move == pytest.approx(0.00065)
    assert signal.metadata["signal_horizon_ticks"] == 3
    assert signal.metadata["expected_move_formula"] == "abs(ret_3) * 0.65"


def test_meanreversion_h10_calibration_is_explicit_env_gated(monkeypatch):
    monkeypatch.setenv("V2_MEANREV_H10_CALIBRATION_ENABLE", "1")
    signal = MeanReversionV2().evaluate(_feature(ret_1=0.0, ret_3=0.0010, vol=0.0005))

    assert signal.direction == "sell"
    assert signal.expected_move == pytest.approx(0.00125)
    assert signal.metadata["signal_horizon_ticks"] == 10
    assert signal.metadata["expected_move_formula"] == "abs(ret_3) * 1.25"
