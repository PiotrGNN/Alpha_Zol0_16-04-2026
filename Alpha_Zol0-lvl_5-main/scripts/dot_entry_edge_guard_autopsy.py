from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _canonical_strategy(value: Any) -> str:
    text = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if text.endswith("V2"):
        text = text[:-2]
    return text


def _canonical_key(symbol: Any, strategy: Any, side: Any) -> str:
    symbol_key = str(symbol or "").strip().upper()
    strategy_key = _canonical_strategy(strategy)
    side_key = str(side or "").strip().lower()
    if not symbol_key or not strategy_key or side_key not in {"buy", "sell"}:
        return ""
    return f"{symbol_key}:{strategy_key}:{side_key}"


def _dig(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_runtime_event(row: sqlite3.Row) -> dict[str, Any]:
    payload = json.loads(row["details"] or "{}")
    cost_breakdown = payload.get("cost_breakdown")
    cost_breakdown = cost_breakdown if isinstance(cost_breakdown, dict) else {}
    risk_fields = payload.get("risk_block_fields")
    risk_fields = risk_fields if isinstance(risk_fields, dict) else {}
    sizing_trace = risk_fields.get("sizing_trace")
    sizing_trace = sizing_trace if isinstance(sizing_trace, dict) else {}
    spread = payload.get("spread")
    spread = spread if isinstance(spread, dict) else {}
    reason = str(
        payload.get("reason_code")
        or payload.get("local_gate_reason")
        or payload.get("effective_gate_reason")
        or ""
    )
    expected_net_after_cost = (
        _safe_float(payload.get("expected_net_after_cost"))
        or _safe_float(_dig(payload, ("entry_edge_after_execution", "expected_net_after_cost")))
    )
    expected_edge_after_fee = (
        _safe_float(payload.get("expected_edge_after_fee"))
        or _safe_float(_dig(payload, ("entry_edge_over_fee", "expected_edge_after_fee")))
    )
    expected_net_after_full_cost = _safe_float(
        sizing_trace.get("expected_net_after_full_cost")
    )
    entry_min_net_usdt = _safe_float(sizing_trace.get("entry_min_net_usdt"))
    total_cost_ratio = _safe_float(cost_breakdown.get("total_cost_ratio"))
    return {
        "id": int(row["id"]),
        "timestamp": str(row["timestamp"]),
        "event": str(row["event"]),
        "reason_code": reason,
        "symbol": payload.get("symbol"),
        "strategy": payload.get("strategy"),
        "canonical_strategy": _canonical_strategy(payload.get("strategy")),
        "side": payload.get("side"),
        "canonical_key": _canonical_key(
            payload.get("symbol"),
            payload.get("strategy"),
            payload.get("side"),
        ),
        "expected_net_after_cost": expected_net_after_cost,
        "expected_edge_after_fee": expected_edge_after_fee,
        "expected_net_after_full_cost": expected_net_after_full_cost,
        "entry_min_net_usdt": entry_min_net_usdt,
        "expected_move": _safe_float(payload.get("expected_move")),
        "expected_move_raw": _safe_float(payload.get("expected_move_raw")),
        "expected_move_scaled": _safe_float(payload.get("expected_move_scaled")),
        "fee_estimate": _safe_float(payload.get("fee_estimate")),
        "fee_round_trip_ratio": _safe_float(cost_breakdown.get("fee_round_trip_ratio")),
        "spread_bps": _safe_float(spread.get("bps")),
        "spread_ratio": _safe_float(cost_breakdown.get("spread_ratio")),
        "slippage_ratio": _safe_float(cost_breakdown.get("slippage_ratio")),
        "total_cost_ratio": total_cost_ratio,
        "final_notional_usdt": _safe_float(sizing_trace.get("final_notional_usdt")),
        "requested_notional_usdt": _safe_float(
            sizing_trace.get("requested_notional_usdt")
        ),
        "quantity_contracts": _safe_float(sizing_trace.get("quantity_contracts")),
        "runtime_profile_source": payload.get("runtime_profile_source"),
        "runtime_profile_key": payload.get("runtime_profile_key"),
        "runtime_profile_sample_size": payload.get("runtime_profile_sample_size"),
        "runtime_profile_span_sec": payload.get("runtime_profile_span_sec"),
        "missing_fields": [
            key
            for key, value in {
                "expected_net_after_cost": expected_net_after_cost,
                "expected_net_after_full_cost": expected_net_after_full_cost,
                "entry_min_net_usdt": entry_min_net_usdt,
                "total_cost_ratio": total_cost_ratio,
            }.items()
            if value is None
        ],
    }


def _summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": float(mean(values)),
    }


def classify_edge_guard(
    *,
    research_expected_net_after_full_cost: float | None,
    runtime_min_net_guard_events: list[dict[str, Any]],
    runtime_edge_filtered_events: list[dict[str, Any]],
    required_fields_missing: list[str],
    strategy_alias_mismatch: bool,
    unit_mismatch: bool,
) -> dict[str, Any]:
    min_guard_full_cost_values = [
        float(row["expected_net_after_full_cost"])
        for row in runtime_min_net_guard_events
        if _safe_float(row.get("expected_net_after_full_cost")) is not None
    ]
    edge_ratio_values = [
        float(row["expected_net_after_cost"])
        for row in runtime_edge_filtered_events
        if _safe_float(row.get("expected_net_after_cost")) is not None
    ]
    runtime_max_full_cost = max(min_guard_full_cost_values) if min_guard_full_cost_values else None
    runtime_max_edge_ratio = max(edge_ratio_values) if edge_ratio_values else None

    if required_fields_missing and not min_guard_full_cost_values and not edge_ratio_values:
        classification = "DOT_EDGE_GUARD_TELEMETRY_INSUFFICIENT"
        patch_decision = "telemetry_only"
    elif strategy_alias_mismatch:
        classification = "DOT_STRATEGY_ALIAS_COLLAPSE_CAUSES_EDGE_MISMATCH"
        patch_decision = "key_report_only"
    elif unit_mismatch:
        classification = "DOT_RESEARCH_RUNTIME_UNIT_MISMATCH"
        patch_decision = "not_justified"
    elif min_guard_full_cost_values:
        classification = "DOT_RUNTIME_EXPECTED_NET_BELOW_MIN_NET"
        patch_decision = "not_justified"
    elif edge_ratio_values and max(edge_ratio_values) <= 0.0:
        classification = "DOT_RUNTIME_EXPECTED_NET_MISSING_OR_ZERO"
        patch_decision = "not_justified"
    elif edge_ratio_values:
        classification = "DOT_RUNTIME_EXPECTED_NET_BELOW_MIN_NET"
        patch_decision = "not_justified"
    else:
        classification = "DOT_EDGE_GUARD_AUTOPSY_INCONCLUSIVE"
        patch_decision = "not_justified"

    return {
        "classification": classification,
        "patch_decision": patch_decision,
        "runtime_max_expected_net_after_full_cost": runtime_max_full_cost,
        "runtime_max_expected_net_after_cost_ratio": runtime_max_edge_ratio,
        "research_expected_net_after_full_cost": research_expected_net_after_full_cost,
    }


def load_runtime_events(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, timestamp, event, details FROM logs "
            "WHERE event IN ('entry_eval_v2','entry_reject_v2','entry_gate_decision_summary') "
            "ORDER BY id ASC"
        ).fetchall()
        return [_extract_runtime_event(row) for row in rows]
    finally:
        conn.close()


def build_report(
    *,
    research_artifact: Path,
    result_artifact: Path,
    profile_autopsy_artifact: Path,
) -> dict[str, Any]:
    research = json.loads(research_artifact.read_text(encoding="utf-8"))
    result = json.loads(result_artifact.read_text(encoding="utf-8"))
    profile_autopsy = json.loads(profile_autopsy_artifact.read_text(encoding="utf-8"))
    selected = research.get("selected_hypothesis") or {}
    after = result.get("after") or {}
    db_path = Path(after.get("db_path") or "")
    events = load_runtime_events(db_path)
    target_key = _canonical_key("DOTUSDTM", "TrendFollowingV2", "sell")
    target_events = [row for row in events if row.get("canonical_key") == target_key]
    edge_filtered = [row for row in target_events if row.get("reason_code") == "entry_edge_filtered"]
    min_net_guard = [row for row in target_events if row.get("reason_code") == "entry_min_net_guard"]
    nearby_no_runtime_profile = [
        row
        for row in events
        if row.get("symbol") == "DOTUSDTM" and row.get("reason_code") == "no_runtime_profile"
    ][:25]
    missing_fields = sorted(
        {
            field
            for row in min_net_guard + edge_filtered
            for field in row.get("missing_fields", [])
            if field != "expected_net_after_full_cost" or row.get("reason_code") == "entry_min_net_guard"
        }
    )
    research_expected_full = _safe_float(selected.get("expected_net_after_full_cost"))
    research_expected_ratio = _safe_float(selected.get("expected_net_after_cost"))
    runtime_full_values = [
        float(row["expected_net_after_full_cost"])
        for row in min_net_guard
        if _safe_float(row.get("expected_net_after_full_cost")) is not None
    ]
    runtime_ratio_values = [
        float(row["expected_net_after_cost"])
        for row in target_events
        if _safe_float(row.get("expected_net_after_cost")) is not None
    ]
    min_thresholds = sorted(
        {
            float(row["entry_min_net_usdt"])
            for row in min_net_guard
            if _safe_float(row.get("entry_min_net_usdt")) is not None
        }
    )
    cost_values = [
        float(row["total_cost_ratio"])
        for row in target_events
        if _safe_float(row.get("total_cost_ratio")) is not None
    ]
    unit_mismatch = bool(
        research_expected_full is not None
        and runtime_ratio_values
        and research_expected_full > 0.01
        and max(runtime_ratio_values) < 0.01
        and not runtime_full_values
    )
    strategy_alias_mismatch = any(
        row.get("canonical_strategy") != "TRENDFOLLOWING" for row in target_events
    )
    classified = classify_edge_guard(
        research_expected_net_after_full_cost=research_expected_full,
        runtime_min_net_guard_events=min_net_guard,
        runtime_edge_filtered_events=edge_filtered,
        required_fields_missing=missing_fields,
        strategy_alias_mismatch=strategy_alias_mismatch,
        unit_mismatch=False,
    )
    gate_distribution = Counter(row.get("reason_code") or "" for row in events)
    threshold_higher_than_research = bool(
        min_thresholds
        and research_expected_full is not None
        and max(min_thresholds) > research_expected_full
    )
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": "DOTUSDTM:TrendFollowingV2:sell",
        "source_artifacts": {
            "research_artifact": str(research_artifact),
            "result_artifact": str(result_artifact),
            "profile_autopsy_artifact": str(profile_autopsy_artifact),
            "runtime_db": str(db_path),
        },
        "research_candidate": {
            "symbol": selected.get("symbol"),
            "strategy": selected.get("strategy"),
            "canonical_strategy": _canonical_strategy(selected.get("strategy")),
            "side": selected.get("side"),
            "expected_net_after_full_cost": research_expected_full,
            "expected_net_after_cost": research_expected_ratio,
            "expected_move": selected.get("expected_move"),
            "final_notional_usdt": selected.get("final_notional_usdt"),
            "source": selected.get("source"),
            "profile_span_sec": selected.get("profile_span_sec"),
            "sample_count": selected.get("sample_count"),
        },
        "runtime_profile_summary": {
            "profile_autopsy_classification": profile_autopsy.get("classification"),
            "profile_source_values": (profile_autopsy.get("runtime_profile_sources") or {}).get("runtime_profile_source_values"),
            "matching_profile_row_count": (profile_autopsy.get("gate_path") or {}).get("matching_profile_row_count"),
        },
        "runtime_blocked_events": {
            "entry_edge_filtered_count": len(edge_filtered),
            "entry_min_net_guard_count": len(min_net_guard),
            "nearby_no_runtime_profile_count_sampled": len(nearby_no_runtime_profile),
            "entry_edge_filtered_events": edge_filtered,
            "entry_min_net_guard_events": min_net_guard,
            "nearby_no_runtime_profile_events_sample": nearby_no_runtime_profile,
        },
        "formula_and_unit_consistency": {
            "research_full_cost_usdt": research_expected_full,
            "research_expected_net_ratio": research_expected_ratio,
            "runtime_expected_net_after_full_cost_stats": _summarize(runtime_full_values),
            "runtime_expected_net_after_cost_ratio_stats": _summarize(runtime_ratio_values),
            "runtime_total_cost_ratio_stats": _summarize(cost_values),
            "effective_entry_min_net_usdt_values": min_thresholds,
            "threshold_higher_than_research_expected_full_cost": threshold_higher_than_research,
            "runtime_uses_notional_dependent_full_cost": bool(runtime_full_values),
            "unit_mismatch_suspected": unit_mismatch,
            "runtime_applies_cost_components": bool(cost_values),
            "missing_fields": missing_fields,
        },
        "gate_reason_distribution": dict(gate_distribution),
        "classification": classified["classification"],
        "patch_decision": classified["patch_decision"],
        "next_recommended_action": (
            "Reject DOT for current runtime economics and test next research candidate "
            "unless a later market window produces expected_net_after_full_cost above 0.12."
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DOT Entry Edge / Min-Net Guard Autopsy",
        "",
        f"- generated_at_utc: `{report.get('generated_at_utc')}`",
        f"- target: `{report.get('target')}`",
        f"- classification: `{report.get('classification')}`",
        f"- patch_decision: `{report.get('patch_decision')}`",
        "",
        "## Research Candidate",
    ]
    for key, value in (report.get("research_candidate") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Runtime Blocked Counts"])
    blocked = report.get("runtime_blocked_events") or {}
    for key in (
        "entry_edge_filtered_count",
        "entry_min_net_guard_count",
        "nearby_no_runtime_profile_count_sampled",
    ):
        lines.append(f"- {key}: `{blocked.get(key)}`")
    lines.extend(["", "## Formula And Unit Consistency"])
    for key, value in (report.get("formula_and_unit_consistency") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Gate Reason Distribution"])
    for key, value in (report.get("gate_reason_distribution") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Next Recommended Action", report.get("next_recommended_action", "")])
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only DOT edge/min-net guard autopsy")
    parser.add_argument(
        "--research-artifact",
        default=str(ANALYSIS_DIR / "new_alpha_research_validation_current.json"),
    )
    parser.add_argument(
        "--result-artifact",
        default=str(WORKDIR / "results" / "controlled_kpi_20260603_142706.json"),
    )
    parser.add_argument(
        "--profile-autopsy-artifact",
        default=str(ANALYSIS_DIR / "dot_no_runtime_profile_autopsy_current.json"),
    )
    parser.add_argument(
        "--output-json",
        default=str(ANALYSIS_DIR / "dot_entry_edge_guard_autopsy_current.json"),
    )
    parser.add_argument(
        "--output-md",
        default=str(ANALYSIS_DIR / "dot_entry_edge_guard_autopsy_current.md"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        research_artifact=Path(args.research_artifact),
        result_artifact=Path(args.result_artifact),
        profile_autopsy_artifact=Path(args.profile_autopsy_artifact),
    )
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "classification": report["classification"],
                "patch_decision": report["patch_decision"],
                "output_json": str(output_json),
                "output_md": str(output_md),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
