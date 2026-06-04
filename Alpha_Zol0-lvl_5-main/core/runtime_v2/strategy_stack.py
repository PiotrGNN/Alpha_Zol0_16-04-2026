from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Protocol

from core.runtime_v2.contracts import FeatureFrame, StrategySignal


def _clamp01(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return float(value)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return float(default)


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _confidence_with_scaling(
    feature: FeatureFrame,
    magnitude: float,
) -> tuple[float, dict]:
    vol = max(1e-8, float(feature.volatility))
    baseline_ratio = abs(float(magnitude)) / vol
    raw_confidence = 0.15 + baseline_ratio * 0.25
    confidence = _clamp01(min(1.0, raw_confidence))
    return confidence, {
        "volatility": vol,
        "signal_magnitude": float(abs(float(magnitude))),
        "baseline_ratio": float(baseline_ratio),
        "raw_confidence": float(raw_confidence),
        "clamped_confidence": float(confidence),
        "scaling_rule": "0.15 + abs(magnitude)/vol * 0.25 (clamped 0..1)",
    }


def _hold_signal(strategy: str, reason_code: str) -> StrategySignal:
    return StrategySignal(
        strategy=strategy,
        direction="hold",
        score=0.0,
        confidence=0.0,
        expected_move=0.0,
        reason_code=reason_code,
        metadata={},
    )


class StrategyV2(Protocol):
    name: str

    def evaluate(self, feature: FeatureFrame) -> StrategySignal:
        ...


@dataclass
class TrendFollowingV2:
    name: str = "TrendFollowingV2"
    min_trend: float = 0.00015

    def evaluate(self, feature: FeatureFrame) -> StrategySignal:
        trend = float(feature.ret_3)
        min_trend = max(
            0.0,
            _env_float("V2_TRENDFOLLOWING_MIN_TREND", self.min_trend),
        )
        if abs(trend) < min_trend:
            return _hold_signal(self.name, "trendfollowing_no_trend")
        direction = "buy" if trend > 0 else "sell"
        expected_move = abs(trend) * 0.95
        confidence, scaling = _confidence_with_scaling(feature, trend)
        return StrategySignal(
            strategy=self.name,
            direction=direction,
            score=trend,
            confidence=confidence,
            expected_move=expected_move,
            reason_code="trendfollowing_signal",
            metadata={
                "trend": trend,
                "signal_horizon_ticks": 3,
                "expected_move_formula": "abs(ret_3) * 0.95",
                "expected_move_raw": abs(trend),
                "expected_move_scaled": expected_move,
                "confidence_scaling": scaling,
            },
        )


@dataclass
class MomentumV2:
    name: str = "MomentumV2"
    min_impulse: float = 0.00010

    def evaluate(self, feature: FeatureFrame) -> StrategySignal:
        impulse = float(feature.ret_1)
        min_impulse = max(
            0.0,
            _env_float("V2_MOMENTUM_MIN_IMPULSE", self.min_impulse),
        )
        if abs(impulse) < min_impulse:
            return _hold_signal(self.name, "momentum_no_impulse")
        direction = "buy" if impulse > 0 else "sell"
        expected_move = abs(impulse) * 1.20
        confidence, scaling = _confidence_with_scaling(feature, impulse)
        return StrategySignal(
            strategy=self.name,
            direction=direction,
            score=impulse,
            confidence=confidence,
            expected_move=expected_move,
            reason_code="momentum_signal",
            metadata={
                "impulse": impulse,
                "signal_horizon_ticks": 1,
                "expected_move_formula": "abs(ret_1) * 1.20",
                "expected_move_raw": abs(impulse),
                "expected_move_scaled": expected_move,
                "confidence_scaling": scaling,
            },
        )


@dataclass
class MeanReversionV2:
    name: str = "MeanReversionV2"
    min_extreme: float = 0.00025

    def evaluate(self, feature: FeatureFrame) -> StrategySignal:
        trend = float(feature.ret_3)
        min_extreme = max(
            0.0,
            _env_float("V2_MEANREV_MIN_EXTREME", self.min_extreme),
        )
        if abs(trend) < min_extreme:
            return _hold_signal(self.name, "meanrev_no_extreme")
        direction = "sell" if trend > 0 else "buy"
        h10_calibration = _env_flag("V2_MEANREV_H10_CALIBRATION_ENABLE", "0")
        expected_move_multiplier = (
            max(0.0, _env_float("V2_MEANREV_H10_EXPECTED_MOVE_MULT", 1.25))
            if h10_calibration
            else 0.65
        )
        signal_horizon_ticks = 10 if h10_calibration else 3
        expected_move = abs(trend) * expected_move_multiplier
        confidence, scaling = _confidence_with_scaling(feature, trend)
        return StrategySignal(
            strategy=self.name,
            direction=direction,
            score=-trend,
            confidence=confidence,
            expected_move=expected_move,
            reason_code="meanrev_signal",
            metadata={
                "trend_extreme": trend,
                "signal_horizon_ticks": signal_horizon_ticks,
                "expected_move_formula": f"abs(ret_3) * {expected_move_multiplier:g}",
                "expected_move_raw": abs(trend),
                "expected_move_scaled": expected_move,
                "h10_calibration_enabled": h10_calibration,
                "confidence_scaling": scaling,
            },
        )


@dataclass
class UniversalV2:
    name: str = "UniversalV2"

    def evaluate(self, feature: FeatureFrame) -> StrategySignal:
        blend = (float(feature.ret_1) * 0.65) + (float(feature.ret_3) * 0.35)
        min_blend = max(0.0, _env_float("V2_UNIVERSAL_MIN_BLEND", 0.00008))
        if abs(blend) < min_blend:
            return _hold_signal(self.name, "universal_neutral")
        direction = "buy" if blend > 0 else "sell"
        expected_move = abs(blend) * 0.90
        confidence, scaling = _confidence_with_scaling(feature, blend)
        return StrategySignal(
            strategy=self.name,
            direction=direction,
            score=blend,
            confidence=confidence,
            expected_move=expected_move,
            reason_code="universal_signal",
            metadata={
                "blend": blend,
                "signal_horizon_ticks": 2,
                "expected_move_formula": "abs(0.65*ret_1 + 0.35*ret_3) * 0.90",
                "expected_move_raw": abs(blend),
                "expected_move_scaled": expected_move,
                "confidence_scaling": scaling,
            },
        )


class StrategyStack:
    def __init__(self):
        self._strategies: List[StrategyV2] = [
            TrendFollowingV2(),
            MomentumV2(),
            MeanReversionV2(),
            UniversalV2(),
        ]

    def evaluate(self, feature: FeatureFrame) -> List[StrategySignal]:
        return [strategy.evaluate(feature) for strategy in self._strategies]
