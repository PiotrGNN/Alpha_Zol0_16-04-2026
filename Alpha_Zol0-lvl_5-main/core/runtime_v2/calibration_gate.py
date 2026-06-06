from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _norm_symbol(value: Any) -> str:
    return _norm_text(value).upper()


def _norm_side(value: Any) -> str:
    side = _norm_text(value).lower()
    if side in {"buy", "sell"}:
        return side
    return ""


def _horizon_bucket(
    signal_horizon_sec_estimate: Any,
    time_horizon_mismatch_ratio: Any,
) -> str:
    horizon = _safe_float(signal_horizon_sec_estimate)
    if horizon is None:
        return "missing_horizon"
    if horizon < 5.0:
        return "signal_lt_5s"
    if horizon < 15.0:
        return "signal_5_15s"
    return "signal_ge_15s"


def _bucket_key(
    symbol: Any,
    strategy: Any,
    side: Any,
    horizon_bucket: Any,
) -> Tuple[str, str, str, str]:
    return (
        _norm_symbol(symbol),
        _norm_text(strategy),
        _norm_side(side),
        _norm_text(horizon_bucket),
    )


def load_expected_move_calibration_profile(path: Optional[Path]) -> Dict[str, Any]:
    source_path = Path(path).resolve() if path else None
    if source_path is None:
        return {
            "enabled": False,
            "loaded": False,
            "source_path": None,
            "bucket_count": 0,
            "bucket_lookup": {},
        }
    if not source_path.exists():
        return {
            "enabled": True,
            "loaded": False,
            "source_path": str(source_path),
            "bucket_count": 0,
            "bucket_lookup": {},
        }
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    summary = payload.get("summary") or {}
    bucket_stats = payload.get("bucket_stats") or summary.get("bucket_stats") or {}
    buckets = bucket_stats.get("buckets") or []
    lookup: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    for row in buckets:
        if not isinstance(row, dict):
            continue
        key = _bucket_key(
            row.get("symbol"),
            row.get("strategy"),
            row.get("side"),
            row.get("horizon_bucket"),
        )
        lookup[key] = dict(row)
    return {
        "enabled": True,
        "loaded": bool(lookup),
        "source_path": str(source_path),
        "bucket_count": len(lookup),
        "bucket_lookup": lookup,
        "payload": payload,
    }


def evaluate_expected_move_calibration_gate(
    *,
    enabled: bool,
    fail_closed: bool,
    profile: Dict[str, Any],
    symbol: str,
    strategy: str,
    side: str,
    expected_gross_before_cost: Any,
    expected_cost_usdt: Any,
    signal_horizon_sec_estimate: Any,
    time_horizon_mismatch_ratio: Any,
    min_sample: int,
    min_positive_net_share: float,
    min_calibrated_expected_net: float,
    max_mismatch_ratio: float,
    expected_notional_usdt: Any = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "allow": True,
        "reason_code": "calibration_gate_disabled",
        "enabled": bool(enabled),
        "fail_closed": bool(fail_closed),
        "source_path": profile.get("source_path"),
        "bucket_count": int(profile.get("bucket_count") or 0),
        "calibration_bucket": None,
        "calibration_sample_size": None,
        "calibration_factor": None,
        "calibration_positive_net_share": None,
        "calibration_expected_over_realized_ratio": None,
        "calibrated_expected_gross": None,
        "calibrated_expected_net": None,
        "uncalibrated_expected_gross": None,
        "uncalibrated_expected_net": None,
        "effective_expected_net": None,
        "calibration_fallback_mode": None,
        "signal_horizon_bucket": _horizon_bucket(
            signal_horizon_sec_estimate,
            time_horizon_mismatch_ratio,
        ),
        "time_horizon_mismatch_ratio": _safe_float(time_horizon_mismatch_ratio),
        "signal_horizon_sec_estimate": _safe_float(signal_horizon_sec_estimate),
    }

    if not enabled:
        return result

    if not bool(profile.get("loaded")):
        result["reason_code"] = "missing_expected_move_calibration_profile"
        result["allow"] = not fail_closed
        return result

    bucket_key = _bucket_key(
        symbol,
        strategy,
        side,
        result["signal_horizon_bucket"],
    )
    bucket = (profile.get("bucket_lookup") or {}).get(bucket_key)
    if bucket is None:
        result["reason_code"] = "missing_expected_move_calibration_bucket"
        result["allow"] = not fail_closed
        return result

    sample_size = int(bucket.get("n") or 0)
    calibration_factor = _safe_float(bucket.get("calibration_factor"))
    positive_net_share = _safe_float(bucket.get("positive_net_share"))
    expected_over_realized_ratio = _safe_float(
        bucket.get("expected_over_realized_ratio")
    )
    median_mismatch_ratio = _safe_float(bucket.get("median_mismatch_ratio"))

    result.update(
        {
            "calibration_bucket": ":".join(bucket_key),
            "calibration_sample_size": sample_size,
            "calibration_factor": calibration_factor,
            "calibration_positive_net_share": positive_net_share,
            "calibration_expected_over_realized_ratio": expected_over_realized_ratio,
            "calibration_bucket_stats": dict(bucket),
        }
    )

    if sample_size < int(min_sample):
        result["reason_code"] = "calibration_sample_too_small"
        result["allow"] = not fail_closed
        return result

    if (
        positive_net_share is not None
        and positive_net_share < float(min_positive_net_share)
    ):
        result["reason_code"] = "calibration_negative_expected_realization"
        result["allow"] = not fail_closed
        return result

    expected_gross = _safe_float(expected_gross_before_cost)
    expected_cost = _safe_float(expected_cost_usdt)
    if expected_gross is None or expected_cost is None:
        result["reason_code"] = "missing_expected_edge_inputs"
        result["allow"] = not fail_closed
        return result

    expected_notional = _safe_float(expected_notional_usdt)
    if expected_notional is None or expected_notional <= 0.0:
        expected_notional = 1.0
    uncalibrated_expected_gross = float(expected_gross * expected_notional)
    uncalibrated_expected_net = float(uncalibrated_expected_gross - expected_cost)
    result["uncalibrated_expected_gross"] = uncalibrated_expected_gross
    result["uncalibrated_expected_net"] = uncalibrated_expected_net

    if calibration_factor is None or calibration_factor <= 0.0:
        result["calibration_fallback_mode"] = "uncalibrated_expected_net"
        result["effective_expected_net"] = uncalibrated_expected_net
        if uncalibrated_expected_net <= float(min_calibrated_expected_net):
            result["reason_code"] = "calibrated_expected_net_nonpositive"
            result["allow"] = False
            return result
        calibrated_expected_net = uncalibrated_expected_net
    else:
        calibrated_expected_gross = float(expected_gross * float(calibration_factor))
        calibrated_expected_net = float(calibrated_expected_gross - expected_cost)
        result["calibrated_expected_gross"] = calibrated_expected_gross
        result["calibrated_expected_net"] = calibrated_expected_net
        result["effective_expected_net"] = calibrated_expected_net

    if calibrated_expected_net <= float(min_calibrated_expected_net):
        result["reason_code"] = "calibrated_expected_net_nonpositive"
        result["allow"] = False
        return result

    mismatch_ratio = _safe_float(time_horizon_mismatch_ratio)
    if (
        mismatch_ratio is not None
        and mismatch_ratio >= float(max_mismatch_ratio)
        and positive_net_share is not None
        and positive_net_share < 0.5
    ):
        result["reason_code"] = "signal_horizon_execution_horizon_mismatch"
        result["allow"] = False
        return result

    result["reason_code"] = "allow"
    result["allow"] = True
    return result
