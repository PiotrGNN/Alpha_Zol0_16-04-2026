from __future__ import annotations

import math
from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def build_edge_after_execution_diagnostic(
    mean_gross_fill_model: float | None,
    execution_snapshot: dict[str, Any] | None,
    shadow_execution_cost_total: float | None = None,
    mean_fee_total: float | None = None,
) -> dict[str, Any] | None:
    if not isinstance(execution_snapshot, dict):
        return None
    realtime_cost = _safe_float(
        execution_snapshot.get("execution_cost_total_realtime")
    )
    gross_value = _safe_float(mean_gross_fill_model)
    if gross_value is None and realtime_cost is None:
        return None
    edge_after_execution = None
    if gross_value is not None and realtime_cost is not None:
        edge_after_execution = float(gross_value) - float(realtime_cost)
    shadow_cost = _safe_float(shadow_execution_cost_total)
    fee_only_cost = _safe_float(mean_fee_total)
    cost_model_error_vs_shadow = None
    cost_model_error_vs_fee_only = None
    if realtime_cost is not None and shadow_cost is not None:
        cost_model_error_vs_shadow = float(realtime_cost) - float(shadow_cost)
    if realtime_cost is not None and fee_only_cost is not None:
        cost_model_error_vs_fee_only = float(realtime_cost) - float(fee_only_cost)
    return {
        "edge_after_execution": _safe_float(edge_after_execution),
        "edge_after_realtime_cost": _safe_float(edge_after_execution),
        "cost_model_error_vs_shadow": _safe_float(cost_model_error_vs_shadow),
        "cost_model_error_vs_fee_only": _safe_float(cost_model_error_vs_fee_only),
        "diagnostic_only": True,
        "runtime_decision_unchanged": True,
    }
