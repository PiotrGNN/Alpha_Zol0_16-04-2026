from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from core.db_utils import save_decision_to_db, save_equity_to_db, save_log_to_db
from core.runtime_v2.contracts import EntryCandidate, OrderPlan


def _ts_iso_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _spread_payload(candidate: Optional[EntryCandidate]) -> Dict[str, float]:
    if candidate is None:
        return {"abs": 0.0, "pct": 0.0, "bps": 0.0}
    spread_abs = float(candidate.quote.spread_abs)
    mid = max(1e-12, float(candidate.quote.mid))
    spread_pct = spread_abs / mid
    return {"abs": spread_abs, "pct": spread_pct, "bps": spread_pct * 10_000.0}


def _profile_payload(candidate: Optional[EntryCandidate]) -> Dict[str, Any]:
    if candidate is None:
        return {
            "runtime_profile_source": None,
            "runtime_profile_key": None,
            "runtime_profile_age_sec": None,
            "runtime_profile_span_sec": None,
            "runtime_profile_sample_size": None,
        }
    cost_breakdown = dict(candidate.cost_breakdown or {})
    runtime_profile_key = cost_breakdown.get("runtime_profile_key")
    if runtime_profile_key is None:
        runtime_profile_key = (
            f"{candidate.symbol}|{candidate.feature.profile_source}|"
            f"n={int(candidate.feature.sample_count)}|span={int(candidate.feature.profile_span_sec)}"
        )
    return {
        "runtime_profile_source": str(candidate.feature.profile_source),
        "runtime_profile_key": str(runtime_profile_key),
        "runtime_profile_age_sec": float(candidate.feature.profile_age_sec),
        "runtime_profile_span_sec": float(candidate.feature.profile_span_sec),
        "runtime_profile_sample_size": int(candidate.feature.sample_count),
    }


def _signal_provenance(candidate: Optional[EntryCandidate]) -> Dict[str, Any]:
    if candidate is None:
        return {
            "signal_confidence_scaling": {},
            "signal_horizon_ticks": None,
            "signal_expected_move_formula": None,
            "expected_move_raw": None,
            "expected_move_scaled": None,
            "expected_gross_before_cost": None,
        }
    metadata = dict(candidate.signal_metadata or {})
    expected_move_scaled = metadata.get("expected_move_scaled")
    if expected_move_scaled is None:
        expected_move_scaled = float(candidate.expected_move)
    expected_move_raw = metadata.get("expected_move_raw")
    if expected_move_raw is None:
        expected_move_raw = float(expected_move_scaled)
    expected_gross_before_cost = metadata.get("expected_gross_before_cost")
    if expected_gross_before_cost is None:
        expected_gross_before_cost = float(expected_move_scaled)
    return {
        "signal_confidence_scaling": dict(metadata.get("confidence_scaling") or {}),
        "signal_horizon_ticks": metadata.get("signal_horizon_ticks"),
        "signal_expected_move_formula": metadata.get("expected_move_formula"),
        "expected_move_raw": float(expected_move_raw),
        "expected_move_scaled": float(expected_move_scaled),
        "expected_gross_before_cost": float(expected_gross_before_cost),
    }


class TelemetryV2:
    def __init__(self, engine_version: str = "v2"):
        self.engine_version = str(engine_version)

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        body = dict(payload or {})
        body.setdefault("engine_version", self.engine_version)
        body.setdefault("ts", _ts_iso_utc())
        save_log_to_db(event, body)

    def emit_decision(self, decision: str, details: Optional[Dict[str, Any]] = None) -> None:
        payload = dict(details or {})
        payload.setdefault("engine_version", self.engine_version)
        save_decision_to_db(time.time(), decision, json.dumps(payload, ensure_ascii=True))

    def emit_equity(self, equity: float, pnl: float) -> None:
        save_equity_to_db(time.time(), equity, pnl)

    def emit_entry_eval(
        self,
        *,
        symbol: str,
        candidate: Optional[EntryCandidate],
        final_allow: bool,
        reason_code: str,
    ) -> None:
        profile_payload = _profile_payload(candidate)
        signal_payload = _signal_provenance(candidate)
        payload = {
            "symbol": symbol,
            "final_allow": bool(final_allow),
            "reason_code": str(reason_code),
            "strategy": candidate.strategy if candidate else None,
            "side": candidate.side if candidate else None,
            "expected_move": (float(candidate.expected_move) if candidate else None),
            "expected_net_after_cost": (
                float(candidate.expected_net_after_cost) if candidate else None
            ),
            "expected_edge_after_fee": (
                float(candidate.expected_edge_after_fee) if candidate else None
            ),
            "probability_of_profit": (
                float(candidate.probability_of_profit) if candidate else None
            ),
            "confidence": float(candidate.confidence) if candidate else None,
            "cost_breakdown": dict(candidate.cost_breakdown) if candidate else {},
            "runtime_profile_source": profile_payload["runtime_profile_source"],
            "runtime_profile_key": profile_payload["runtime_profile_key"],
            "runtime_profile_age_sec": profile_payload["runtime_profile_age_sec"],
            "runtime_profile_span_sec": profile_payload["runtime_profile_span_sec"],
            "runtime_profile_sample_size": profile_payload["runtime_profile_sample_size"],
            "signal_confidence_scaling": signal_payload["signal_confidence_scaling"],
            "signal_horizon_ticks": signal_payload["signal_horizon_ticks"],
            "signal_expected_move_formula": signal_payload["signal_expected_move_formula"],
            "expected_move_raw": signal_payload["expected_move_raw"],
            "expected_move_scaled": signal_payload["expected_move_scaled"],
            "expected_gross_before_cost": signal_payload["expected_gross_before_cost"],
            "tuple_concentration": (
                float(candidate.cost_breakdown.get("tuple_concentration", 0.0))
                if candidate
                else None
            ),
            "trendfollowing_tuple_concentration": (
                candidate.cost_breakdown.get("trendfollowing_tuple_concentration")
                if candidate
                else None
            ),
        }
        self._emit("entry_eval_v2", payload)

    def emit_entry_reject(
        self,
        *,
        symbol: str,
        reason_code: str,
        candidate: Optional[EntryCandidate],
        risk_fields: Optional[Dict[str, Any]] = None,
    ) -> None:
        profile_payload = _profile_payload(candidate)
        signal_payload = _signal_provenance(candidate)
        payload = {
            "symbol": symbol,
            "reason_code": str(reason_code),
            "strategy": candidate.strategy if candidate else None,
            "side": candidate.side if candidate else None,
            "expected_move": (float(candidate.expected_move) if candidate else None),
            "expected_net_after_cost": (
                float(candidate.expected_net_after_cost) if candidate else None
            ),
            "expected_edge_after_fee": (
                float(candidate.expected_edge_after_fee) if candidate else None
            ),
            "probability_of_profit": (
                float(candidate.probability_of_profit) if candidate else None
            ),
            "confidence": float(candidate.confidence) if candidate else None,
            "cost_breakdown": dict(candidate.cost_breakdown) if candidate else {},
            "risk_block_fields": dict(risk_fields or {}),
            "runtime_profile_source": profile_payload["runtime_profile_source"],
            "runtime_profile_key": profile_payload["runtime_profile_key"],
            "runtime_profile_age_sec": profile_payload["runtime_profile_age_sec"],
            "runtime_profile_span_sec": profile_payload["runtime_profile_span_sec"],
            "runtime_profile_sample_size": profile_payload["runtime_profile_sample_size"],
            "signal_confidence_scaling": signal_payload["signal_confidence_scaling"],
            "signal_horizon_ticks": signal_payload["signal_horizon_ticks"],
            "signal_expected_move_formula": signal_payload["signal_expected_move_formula"],
            "expected_move_raw": signal_payload["expected_move_raw"],
            "expected_move_scaled": signal_payload["expected_move_scaled"],
            "expected_gross_before_cost": signal_payload["expected_gross_before_cost"],
            "tuple_concentration": (
                float(candidate.cost_breakdown.get("tuple_concentration", 0.0))
                if candidate
                else None
            ),
            "trendfollowing_tuple_concentration": (
                candidate.cost_breakdown.get("trendfollowing_tuple_concentration")
                if candidate
                else None
            ),
        }
        self._emit("entry_reject_v2", payload)

    def emit_gate_summary(
        self,
        *,
        symbol: str,
        reason_code: str,
        final_allow: bool,
        candidate: Optional[EntryCandidate],
    ) -> None:
        spread = _spread_payload(candidate)
        profile_payload = _profile_payload(candidate)
        signal_payload = _signal_provenance(candidate)
        payload = {
            "ts": _ts_iso_utc(),
            "symbol": symbol,
            "side": candidate.side if candidate else None,
            "strategy": candidate.strategy if candidate else None,
            "main_strategy": candidate.strategy if candidate else None,
            "final_allow": bool(final_allow),
            "entry_gate_bucket": "admitted" if final_allow else "blocked",
            "global_block_reason": None,
            "local_gate_reason": str(reason_code),
            "effective_gate_reason": str(reason_code),
            "effective_gate_reason_origin": "local",
            "paper_gate_active": False,
            "paper_gate_reason": None,
            "paper_gate_mode": "inactive",
            "risk_allow_before_paper_gate": bool(final_allow),
            "paper_gate_override": False,
            "entry_decision_raw": candidate.side if candidate else "hold",
            "entry_decision_final": candidate.side if final_allow and candidate else "hold",
            "entry_reason": "decision_passed" if final_allow else str(reason_code),
            "entry_reason_classification": (
                "passed"
                if final_allow
                else ("no_edge" if str(reason_code) in {"no_edge", "no_runtime_profile"} else "blocked")
            ),
            "entry_live_edge": {},
            "entry_edge_over_fee": {
                "expected_edge_after_fee": (
                    float(candidate.expected_edge_after_fee) if candidate else None
                ),
            },
            "entry_edge_after_execution": {
                "expected_net_after_cost": (
                    float(candidate.expected_net_after_cost) if candidate else None
                )
            },
            "expected_move": (float(candidate.expected_move) if candidate else None),
            "spread": spread,
            "liquidity_ok": True,
            "confidence": float(candidate.confidence) if candidate else 0.0,
            "fee_estimate": (
                float(candidate.cost_breakdown.get("fee_round_trip_ratio"))
                if candidate
                else 0.0
            ),
            "current_edge": (
                float(candidate.expected_edge_after_fee) if candidate else None
            ),
            "realtime_edge": (
                float(candidate.expected_net_after_cost) if candidate else None
            ),
            "runtime_profile_source": profile_payload["runtime_profile_source"],
            "runtime_profile_key": profile_payload["runtime_profile_key"],
            "runtime_profile_age_sec": profile_payload["runtime_profile_age_sec"],
            "runtime_profile_span_sec": profile_payload["runtime_profile_span_sec"],
            "runtime_profile_sample_size": profile_payload["runtime_profile_sample_size"],
            "signal_confidence_scaling": signal_payload["signal_confidence_scaling"],
            "signal_horizon_ticks": signal_payload["signal_horizon_ticks"],
            "signal_expected_move_formula": signal_payload["signal_expected_move_formula"],
            "expected_move_raw": signal_payload["expected_move_raw"],
            "expected_move_scaled": signal_payload["expected_move_scaled"],
            "expected_gross_before_cost": signal_payload["expected_gross_before_cost"],
            "tuple_concentration": (
                float(candidate.cost_breakdown.get("tuple_concentration", 0.0))
                if candidate
                else None
            ),
            "trendfollowing_tuple_concentration": (
                candidate.cost_breakdown.get("trendfollowing_tuple_concentration")
                if candidate
                else None
            ),
            "max_positions_blocked": str(reason_code) == "current_side",
            "natural_path_trace": {
                "pre_entry_candidate_exists": candidate is not None,
                "strategy_assignment_stage": "selected" if candidate else "no_candidate",
                "strategy": candidate.strategy if candidate else None,
                "main_strategy": candidate.strategy if candidate else None,
                "side": candidate.side if candidate else None,
            },
        }
        self._emit("entry_gate_decision_summary", payload)
        self._emit(
            "risk_decision",
            {
                "symbol": symbol,
                "entry_decision": candidate.side if final_allow and candidate else "hold",
                "allow": bool(final_allow),
                "local_gate_reason": str(reason_code),
            },
        )

    def emit_pre_entry_rejection_trace(
        self,
        *,
        symbol: str,
        reason_code: str,
        candidate: Optional[EntryCandidate],
    ) -> None:
        payload = {
            "symbol": symbol,
            "rejection_reason_code": str(reason_code),
            "normalized_strategy_value": candidate.strategy if candidate else None,
            "normalized_side_value": candidate.side if candidate else None,
            "candidate_payload_preview": {
                "strategy": candidate.strategy if candidate else None,
                "side": candidate.side if candidate else None,
                "raw_side": candidate.side if candidate else None,
            },
        }
        self._emit("pre_entry_candidate_rejection_trace", payload)

    def emit_position_open(self, *, plan: OrderPlan, position_payload: Dict[str, Any]) -> None:
        signal_metadata = dict(plan.signal_metadata or {})
        position_meta = (
            position_payload.get("meta")
            if isinstance(position_payload.get("meta"), dict)
            else {}
        )
        expected_move_scaled = signal_metadata.get("expected_move_scaled", plan.expected_move)
        expected_move_raw = signal_metadata.get("expected_move_raw", expected_move_scaled)
        expected_gross_before_cost = signal_metadata.get(
            "expected_gross_before_cost",
            expected_move_scaled,
        )
        body = {
            "symbol": plan.symbol,
            "side": plan.side,
            "strategy": plan.strategy,
            "entry_reason": "decision_passed",
            "entry_open_truth_classification": "NATURAL_STRATEGY_ENTRY",
            "selection_source": "runtime_v2",
            "decision_router_path": "runtime_v2",
            "override_reason": None,
            "position": position_payload,
            "leverage": plan.leverage,
            "notional_usdt": plan.final_notional_usdt,
            "requested_notional_usdt": plan.requested_notional_usdt,
            "capped_notional_usdt": plan.capped_notional_usdt,
            "sizing_trace": dict(plan.sizing_trace),
            "cost_breakdown": dict(plan.cost_breakdown),
            "expected_net_after_full_cost": plan.expected_net_after_full_cost,
            "expected_move": plan.expected_move,
            "probability_of_profit": plan.probability_of_profit,
            "confidence": plan.confidence,
            "runtime_profile_source": plan.cost_breakdown.get("runtime_profile_source"),
            "runtime_profile_key": plan.cost_breakdown.get("runtime_profile_key"),
            "runtime_profile_age_sec": plan.cost_breakdown.get("runtime_profile_age_sec"),
            "runtime_profile_span_sec": plan.cost_breakdown.get("runtime_profile_span_sec"),
            "runtime_profile_sample_size": plan.cost_breakdown.get("runtime_profile_sample_size"),
            "signal_confidence_scaling": dict(signal_metadata.get("confidence_scaling") or {}),
            "signal_horizon_ticks": signal_metadata.get("signal_horizon_ticks"),
            "signal_expected_move_formula": signal_metadata.get("expected_move_formula"),
            "expected_move_raw": expected_move_raw,
            "expected_move_scaled": expected_move_scaled,
            "expected_gross_before_cost": expected_gross_before_cost,
            "time_decay_exit_sec": position_meta.get("time_decay_exit_sec"),
            "tuple_concentration": plan.cost_breakdown.get("tuple_concentration"),
            "trendfollowing_tuple_concentration": plan.cost_breakdown.get(
                "trendfollowing_tuple_concentration"
            ),
        }
        self._emit("position_open_v2", body)
        self._emit("position_open", body)

    def emit_exit_eval(self, payload: Dict[str, Any]) -> None:
        self._emit("exit_eval_v2", payload)

    def emit_position_close(self, payload: Dict[str, Any]) -> None:
        body = dict(payload or {})
        meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
        if "runtime_profile_key" in meta:
            body["runtime_profile_key"] = meta.get("runtime_profile_key")
        if "expected_move_scaled" in meta:
            body["expected_move_scaled"] = meta.get("expected_move_scaled")
        if "expected_gross_before_cost" in meta:
            body["expected_gross_before_cost"] = meta.get("expected_gross_before_cost")
        if "time_decay_exit_sec" in meta:
            body["time_decay_exit_sec"] = meta.get("time_decay_exit_sec")
        body["realized_pnl"] = float(payload.get("realized_pnl", 0.0))
        body["position"] = dict(payload or {})
        self._emit("position_close_v2", body)
        self._emit("position_close", body)
