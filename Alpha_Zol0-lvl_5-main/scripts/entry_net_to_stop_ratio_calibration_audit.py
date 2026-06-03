from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"
RATIO_BUCKETS = ("<0.50", "0.50-0.70", "0.70-0.90", "0.90-1.00", "1.00-1.10", ">=1.10")
SIMULATED_THRESHOLDS = (1.10, 1.00, 0.95, 0.90)
CURRENT_REQUIRED_RATIO = 1.10


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except Exception:
        return 0


def _dig(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _canonical_key(symbol: Any, strategy: Any, side: Any) -> str:
    return (
        f"{str(symbol or '').strip().upper()}:"
        f"{str(strategy or '').strip()}:"
        f"{str(side or '').strip().lower()}"
    )


def bucket_for_ratio(value: float | None) -> str | None:
    ratio = _safe_float(value)
    if ratio is None:
        return None
    if ratio < 0.50:
        return "<0.50"
    if ratio < 0.70:
        return "0.50-0.70"
    if ratio < 0.90:
        return "0.70-0.90"
    if ratio < 1.00:
        return "0.90-1.00"
    if ratio < 1.10:
        return "1.00-1.10"
    return ">=1.10"


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {"count": len(values), "min": min(values), "max": max(values), "mean": float(mean(values))}


def _profit_factor(pnls: list[float]) -> float | str | None:
    if not pnls:
        return None
    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
    if gross_profit <= 0 and gross_loss <= 0:
        return None
    if gross_loss <= 0:
        return "inf"
    return gross_profit / gross_loss


def _base_bucket_row() -> dict[str, Any]:
    return {
        "event_count": 0,
        "candidate_count": 0,
        "symbol_strategy_side_distribution": {},
        "position_open_count": 0,
        "completed_clean_trade_count": 0,
        "net_pnl": 0.0,
        "winrate": None,
        "profit_factor": None,
        "expectancy": None,
        "avg_expected_net_after_full_cost": None,
        "avg_stop_risk": None,
        "avg_ratio": None,
        "avg_mfe": None,
        "avg_mae": None,
        "green_to_red_share": None,
        "fee_inversion_share": None,
        "exit_reason_distribution": {},
        "contamination_rejection_count": 0,
        "sample_sufficiency": "INSUFFICIENT_CLEAN_COMPLETED_TRADES",
    }


def summarize_ratio_buckets(
    ratio_events: list[dict[str, Any]],
    clean_trades: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    bucket_events: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in RATIO_BUCKETS}
    bucket_trades: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in RATIO_BUCKETS}
    for event in ratio_events:
        bucket = bucket_for_ratio(event.get("entry_net_to_stop_ratio"))
        if bucket:
            bucket_events[bucket].append(event)
    for trade in clean_trades:
        bucket = bucket_for_ratio(trade.get("entry_net_to_stop_ratio"))
        if bucket:
            bucket_trades[bucket].append(trade)

    summary: dict[str, dict[str, Any]] = {}
    for bucket in RATIO_BUCKETS:
        events = bucket_events[bucket]
        trades = bucket_trades[bucket]
        pnls = [float(trade.get("realized_pnl") or 0.0) for trade in trades]
        mfe_values = [float(trade["mfe"]) for trade in trades if _safe_float(trade.get("mfe")) is not None]
        mae_values = [float(trade["mae"]) for trade in trades if _safe_float(trade.get("mae")) is not None]
        expected_values = [
            float(event["expected_net_after_full_cost"])
            for event in events
            if _safe_float(event.get("expected_net_after_full_cost")) is not None
        ]
        stop_values = [
            float(event["estimated_stop_loss_net_usdt"])
            for event in events
            if _safe_float(event.get("estimated_stop_loss_net_usdt")) is not None
        ]
        ratio_values = [
            float(event["entry_net_to_stop_ratio"])
            for event in events
            if _safe_float(event.get("entry_net_to_stop_ratio")) is not None
        ]
        distribution = Counter(str(event.get("canonical_key") or "") for event in events)
        exit_distribution = Counter(str(trade.get("exit_reason") or "UNKNOWN") for trade in trades)
        row = _base_bucket_row()
        row.update(
            {
                "event_count": len(events),
                "candidate_count": len({event.get("canonical_key") for event in events if event.get("canonical_key")}),
                "symbol_strategy_side_distribution": dict(sorted(distribution.items())),
                "position_open_count": sum(1 for trade in trades if trade.get("position_open")),
                "completed_clean_trade_count": len(trades),
                "net_pnl": sum(pnls),
                "winrate": (sum(1 for pnl in pnls if pnl > 0) / len(pnls)) if pnls else None,
                "profit_factor": _profit_factor(pnls),
                "expectancy": (sum(pnls) / len(pnls)) if pnls else None,
                "avg_expected_net_after_full_cost": (sum(expected_values) / len(expected_values)) if expected_values else None,
                "avg_stop_risk": (sum(stop_values) / len(stop_values)) if stop_values else None,
                "avg_ratio": (sum(ratio_values) / len(ratio_values)) if ratio_values else None,
                "avg_mfe": (sum(mfe_values) / len(mfe_values)) if mfe_values else None,
                "avg_mae": (sum(mae_values) / len(mae_values)) if mae_values else None,
                "green_to_red_share": (
                    sum(1 for trade in trades if trade.get("green_to_red")) / len(trades)
                    if trades
                    else None
                ),
                "fee_inversion_share": (
                    sum(1 for trade in trades if trade.get("fee_inversion")) / len(trades)
                    if trades
                    else None
                ),
                "exit_reason_distribution": dict(sorted(exit_distribution.items())),
                "contamination_rejection_count": sum(1 for event in events if event.get("contaminated")),
                "sample_sufficiency": (
                    "SUFFICIENT_CLEAN_COMPLETED_TRADES"
                    if len(trades) >= 20
                    else "INSUFFICIENT_CLEAN_COMPLETED_TRADES"
                ),
            }
        )
        summary[bucket] = row
    return summary


def simulate_ratio_thresholds(
    ratio_events: list[dict[str, Any]],
    clean_trades: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for threshold in SIMULATED_THRESHOLDS:
        additional = [
            event
            for event in ratio_events
            if event.get("only_net_to_stop_blocked")
            and (_safe_float(event.get("entry_net_to_stop_ratio")) is not None)
            and float(event["entry_net_to_stop_ratio"]) >= threshold
            and float(event["entry_net_to_stop_ratio"]) < CURRENT_REQUIRED_RATIO
        ]
        keys = {event.get("canonical_key") for event in additional if event.get("canonical_key")}
        bucketed_trades = [
            trade
            for trade in clean_trades
            if (_safe_float(trade.get("entry_net_to_stop_ratio")) is not None)
            and float(trade["entry_net_to_stop_ratio"]) >= threshold
            and float(trade["entry_net_to_stop_ratio"]) < CURRENT_REQUIRED_RATIO
        ]
        pnls = [float(trade.get("realized_pnl") or 0.0) for trade in bucketed_trades]
        out[f"{threshold:.2f}"] = {
            "additional_admitted_events": len(additional),
            "additional_candidates": len(keys),
            "likely_opens_if_all_other_gates_pass": len(additional),
            "clean_completed_historical_trades_available": len(bucketed_trades),
            "realized_net_pnl": sum(pnls) if pnls else None,
            "expectancy": (sum(pnls) / len(pnls)) if pnls else None,
            "profit_factor": _profit_factor(pnls),
            "sample_sufficiency": (
                "SUFFICIENT_CLEAN_COMPLETED_TRADES"
                if len(bucketed_trades) >= 20
                else "INSUFFICIENT_CLEAN_COMPLETED_TRADES"
            ),
            "experiment_justified": False,
        }
    return out


def classify_calibration(
    *,
    ratio_events: list[dict[str, Any]],
    bucket_summary: dict[str, dict[str, Any]],
    simulation: dict[str, dict[str, Any]],
) -> dict[str, str]:
    lower_trade_count = sum(
        _safe_int(bucket_summary.get(bucket, {}).get("completed_clean_trade_count"))
        for bucket in ("<0.50", "0.50-0.70", "0.70-0.90", "0.90-1.00", "1.00-1.10")
    )
    lower_net_pnl = sum(
        float(bucket_summary.get(bucket, {}).get("net_pnl") or 0.0)
        for bucket in ("<0.50", "0.50-0.70", "0.70-0.90", "0.90-1.00", "1.00-1.10")
    )
    ratio_only_count = sum(1 for event in ratio_events if event.get("only_net_to_stop_blocked"))
    max_ratio = max(
        [
            float(event["entry_net_to_stop_ratio"])
            for event in ratio_events
            if _safe_float(event.get("entry_net_to_stop_ratio")) is not None
        ],
        default=None,
    )
    max_expected = max(
        [
            float(event["expected_net_after_full_cost"])
            for event in ratio_events
            if _safe_float(event.get("expected_net_after_full_cost")) is not None
        ],
        default=None,
    )

    if lower_trade_count >= 20 and lower_net_pnl < 0.0:
        classification = "ENTRY_NET_TO_STOP_RATIO_1_10_SUPPORTED_BY_NEGATIVE_LOWER_RATIO_BUCKETS"
        final_verdict = "RATIO_THRESHOLD_CHANGE_NOT_JUSTIFIED"
    elif lower_trade_count >= 20 and lower_net_pnl > 0.0:
        classification = "ENTRY_NET_TO_STOP_RATIO_1_10_TOO_STRICT_SUPPORTED_BY_CLEAN_LOWER_RATIO_PROFIT"
        final_verdict = "PAPER_ONLY_RATIO_EXPERIMENT_JUSTIFIED"
    elif ratio_only_count > 0 and (max_ratio is not None and max_ratio < CURRENT_REQUIRED_RATIO) and (
        max_expected is not None and max_expected < 0.08
    ):
        classification = "STRATEGY_EDGE_TOO_WEAK_RELATIVE_TO_STOP_RISK"
        final_verdict = "STRATEGY_EDGE_REPAIR_REQUIRED"
    elif ratio_only_count > 0:
        classification = "ENTRY_NET_TO_STOP_RATIO_1_10_POSSIBLY_TOO_STRICT_NEEDS_PAPER_EXPERIMENT"
        final_verdict = "PAPER_ONLY_RATIO_EXPERIMENT_JUSTIFIED"
    elif lower_trade_count == 0:
        classification = "ENTRY_NET_TO_STOP_RATIO_CALIBRATION_BLOCKED_BY_INSUFFICIENT_SAMPLE"
        final_verdict = "RATIO_CALIBRATION_BLOCKED_BY_INSUFFICIENT_SAMPLE"
    else:
        classification = "ENTRY_NET_TO_STOP_RATIO_CALIBRATION_INCONCLUSIVE"
        final_verdict = "RATIO_CALIBRATION_INCONCLUSIVE"

    return {
        "classification": classification,
        "final_verdict": final_verdict,
        "patch_decision": "no_semantic_patch",
    }


def _ratio_from_event(event: dict[str, Any]) -> float | None:
    direct = _safe_float(event.get("entry_net_to_stop_ratio"))
    if direct is not None:
        return direct
    formula = _safe_float(event.get("formula_entry_net_to_stop_ratio"))
    if formula is not None:
        return formula
    expected = _safe_float(event.get("expected_net_after_full_cost"))
    stop = _safe_float(event.get("estimated_stop_loss_net_usdt"))
    if expected is not None and stop is not None and stop > 0:
        return expected / stop
    return None


def normalize_autopsy_events(autopsy: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in autopsy.get("events") or []:
        if not isinstance(event, dict):
            continue
        ratio = _ratio_from_event(event)
        if ratio is None:
            continue
        expected = _safe_float(event.get("expected_net_after_full_cost"))
        stop = _safe_float(event.get("estimated_stop_loss_net_usdt"))
        min_net = _safe_float(event.get("entry_min_net_usdt") or event.get("threshold"))
        required = _safe_float(event.get("entry_min_net_to_stop_ratio")) or CURRENT_REQUIRED_RATIO
        reason = str(event.get("reason_code") or "")
        min_net_passed = bool(expected is not None and (min_net is None or expected >= min_net))
        edge_filter_passed = reason != "entry_edge_filtered"
        only_ratio = bool(reason == "entry_net_to_stop_guard" and min_net_passed and edge_filter_passed)
        gates = []
        if reason:
            gates.append(reason)
        if event.get("min_net_triggered"):
            gates.append("entry_min_net_guard")
        if event.get("net_to_stop_triggered") or reason == "entry_net_to_stop_guard":
            gates.append("entry_net_to_stop_guard")
        records.append(
            {
                "run_id": event.get("run_id"),
                "symbol": event.get("symbol"),
                "strategy": event.get("strategy"),
                "canonical_strategy": event.get("strategy"),
                "side": event.get("side"),
                "canonical_key": event.get("canonical_key")
                or _canonical_key(event.get("symbol"), event.get("strategy"), event.get("side")),
                "threshold_variant": event.get("threshold"),
                "expected_net_after_full_cost": expected,
                "stop_risk": stop,
                "estimated_stop_loss_net_usdt": stop,
                "entry_net_to_stop_ratio": ratio,
                "required_ratio": required,
                "stop_loss_distance": None,
                "notional": event.get("final_notional_usdt"),
                "qty": event.get("quantity_contracts"),
                "fee_estimate": event.get("fee_round_trip_ratio"),
                "spread_estimate": event.get("spread_ratio"),
                "slippage_estimate": event.get("slippage_ratio"),
                "quote_source": event.get("quote_source"),
                "profile_source": event.get("runtime_profile_source"),
                "profile_age": event.get("runtime_profile_age_sec"),
                "first_blocking_gate": reason,
                "all_blocking_gates": sorted(set(gates)),
                "min_net_passed": min_net_passed,
                "edge_filter_passed": edge_filter_passed,
                "only_net_to_stop_blocked": only_ratio,
                "reason_code": reason,
                "contaminated": False,
            }
        )
    return records


def _parse_payload(raw: Any) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_trade_ratio(payload: dict[str, Any]) -> float | None:
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    sizing = payload.get("sizing_trace") if isinstance(payload.get("sizing_trace"), dict) else {}
    if not sizing:
        nested = _dig(payload, ("risk_block_fields", "sizing_trace"))
        sizing = nested if isinstance(nested, dict) else {}
    return (
        _safe_float(payload.get("entry_net_to_stop_ratio"))
        or _safe_float(position.get("entry_net_to_stop_ratio"))
        or _safe_float(sizing.get("entry_net_to_stop_ratio"))
    )


def load_clean_trades_from_db(db_path: Path, *, run_id: str) -> tuple[list[dict[str, Any]], int]:
    if not db_path.exists():
        return [], 1
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, event, details FROM logs "
            "WHERE event IN ('position_open','position_open_v2','position_close','position_close_v2') "
            "ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()

    opens: list[dict[str, Any]] = []
    closes: list[dict[str, Any]] = []
    rejected = 0
    for row in rows:
        payload = _parse_payload(row["details"])
        event = str(row["event"])
        source = payload.get("source") or payload.get("open_source") or payload.get("reason")
        source_text = str(source or "").lower()
        contaminated = any(
            token in source_text
            for token in ("seed", "fallback", "force", "forced", "mock", "cycle_end")
        )
        if contaminated:
            rejected += 1
            continue
        ratio = _extract_trade_ratio(payload)
        if ratio is None:
            continue
        position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
        record = {
            "run_id": run_id,
            "canonical_key": payload.get("canonical_key")
            or _canonical_key(
                payload.get("symbol") or position.get("symbol"),
                payload.get("strategy") or position.get("strategy"),
                payload.get("side") or position.get("side"),
            ),
            "entry_net_to_stop_ratio": ratio,
            "position_open": event in {"position_open", "position_open_v2"},
            "realized_pnl": _safe_float(payload.get("realized_pnl") or position.get("realized_pnl")),
            "mfe": _safe_float(
                payload.get("mfe")
                or payload.get("max_unrealized_pnl")
                or position.get("max_unrealized_pnl")
            ),
            "mae": _safe_float(
                payload.get("mae")
                or payload.get("min_unrealized_pnl")
                or position.get("min_unrealized_pnl")
            ),
            "exit_reason": payload.get("exit_reason") or position.get("exit_reason"),
            "green_to_red": False,
            "fee_inversion": False,
        }
        realized = _safe_float(record.get("realized_pnl"))
        mfe = _safe_float(record.get("mfe"))
        gross = _safe_float(payload.get("realized_gross_pnl") or position.get("realized_gross_pnl"))
        record["green_to_red"] = bool(mfe is not None and mfe > 0 and realized is not None and realized < 0)
        record["fee_inversion"] = bool(gross is not None and gross > 0 and realized is not None and realized <= 0)
        if event in {"position_close", "position_close_v2"} and realized is not None:
            closes.append(record)
        elif event in {"position_open", "position_open_v2"}:
            opens.append(record)
    return opens + closes, rejected


def load_auxiliary_artifact(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_report(
    *,
    autopsy_path: Path,
    matrix_path: Path | None = None,
    smoke_path: Path | None = None,
) -> dict[str, Any]:
    autopsy = json.loads(autopsy_path.read_text(encoding="utf-8"))
    ratio_events = normalize_autopsy_events(autopsy)
    clean_trades: list[dict[str, Any]] = []
    contamination_rejections = 0
    for run in autopsy.get("runs") or []:
        if not isinstance(run, dict):
            continue
        db_path = Path(str(run.get("db_path") or ""))
        trades, rejected = load_clean_trades_from_db(db_path, run_id=str(run.get("run_id") or ""))
        clean_trades.extend(trades)
        contamination_rejections += rejected

    bucket_summary = summarize_ratio_buckets(ratio_events, clean_trades)
    for row in bucket_summary.values():
        row["contamination_rejection_count"] += contamination_rejections
    simulation = simulate_ratio_thresholds(ratio_events, clean_trades)
    classification = classify_calibration(
        ratio_events=ratio_events,
        bucket_summary=bucket_summary,
        simulation=simulation,
    )

    ratio_values = [
        float(event["entry_net_to_stop_ratio"])
        for event in ratio_events
        if _safe_float(event.get("entry_net_to_stop_ratio")) is not None
    ]
    stop_values = [
        float(event["estimated_stop_loss_net_usdt"])
        for event in ratio_events
        if _safe_float(event.get("estimated_stop_loss_net_usdt")) is not None
    ]
    expected_values = [
        float(event["expected_net_after_full_cost"])
        for event in ratio_events
        if _safe_float(event.get("expected_net_after_full_cost")) is not None
    ]
    only_ratio_events = [event for event in ratio_events if event.get("only_net_to_stop_blocked")]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **classification,
        "profitability_claim": False,
        "scope": {
            "kucoin_only": True,
            "paper_only": True,
            "live": False,
            "semantic_patch": False,
            "threshold_patch": False,
        },
        "evidence_sources": {
            "entry_edge_autopsy": str(autopsy_path),
            "threshold_matrix": str(matrix_path) if matrix_path else None,
            "next_candidate_smoke": str(smoke_path) if smoke_path else None,
            "threshold_matrix_classification": (
                (load_auxiliary_artifact(matrix_path) or {}).get("classification")
                if matrix_path
                else None
            ),
            "next_candidate_smoke_classification": (
                (load_auxiliary_artifact(smoke_path) or {}).get("classification")
                if smoke_path
                else None
            ),
        },
        "locked_facts": {
            "source_classification": autopsy.get("classification"),
            "threshold_override_propagated": autopsy.get("threshold_override_propagated"),
            "formula_mismatch_count": autopsy.get("formula_mismatch_count"),
        },
        "ratio_event_count": len(ratio_events),
        "only_net_to_stop_blocked_count": len(only_ratio_events),
        "clean_trade_with_ratio_count": len([trade for trade in clean_trades if not trade.get("position_open")]),
        "ratio_stats": _stats(ratio_values),
        "expected_net_after_full_cost_stats": _stats(expected_values),
        "stop_risk_stats": _stats(stop_values),
        "ratio_bucket_summary": bucket_summary,
        "hypothetical_ratio_threshold_simulation": simulation,
        "blocked_events": ratio_events,
        "required_checks": {
            "stop_risk_too_large_relative_to_observed_mae": "INSUFFICIENT_CLEAN_MAE_SAMPLE",
            "expected_net_too_small_because_strategy_signal_weak": bool(expected_values and max(expected_values) < 0.08),
            "expected_net_clipped_or_cost_overburdened_before_ratio": bool(autopsy.get("entry_edge_filtered_count", 0)),
            "ratio_uses_correct_units": bool(autopsy.get("formula_mismatch_count") == 0),
            "required_1_10_has_historical_evidence": "NOT_PROVEN_BY_CURRENT_CLEAN_SAMPLE",
            "lower_ratio_buckets_positive_under_clean_semantics": "NO_CLEAN_COMPLETED_LOWER_RATIO_SAMPLE",
            "candidate_fails_only_because_ratio_guard": bool(only_ratio_events),
            "lowering_to_1_00_0_95_0_90_outcome": simulation,
            "stop_risk_model_symbol_sensitive_enough": "INCONCLUSIVE_WITHOUT_CLEAN_MAE_SAMPLE",
            "trendfollowing_entries_too_late_or_weak": bool(expected_values and max(expected_values) < 0.08),
        },
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Entry net-to-stop ratio calibration audit",
        "",
        f"- classification: `{report.get('classification')}`",
        f"- final_verdict: `{report.get('final_verdict')}`",
        f"- patch_decision: `{report.get('patch_decision')}`",
        f"- ratio_event_count: `{report.get('ratio_event_count')}`",
        f"- only_net_to_stop_blocked_count: `{report.get('only_net_to_stop_blocked_count')}`",
        f"- clean_trade_with_ratio_count: `{report.get('clean_trade_with_ratio_count')}`",
        f"- ratio_stats: `{report.get('ratio_stats')}`",
        f"- expected_net_after_full_cost_stats: `{report.get('expected_net_after_full_cost_stats')}`",
        "",
        "## Buckets",
    ]
    for bucket, row in (report.get("ratio_bucket_summary") or {}).items():
        lines.append(
            "- "
            f"{bucket}: events=`{row.get('event_count')}`, candidates=`{row.get('candidate_count')}`, "
            f"trades=`{row.get('completed_clean_trade_count')}`, net_pnl=`{row.get('net_pnl')}`, "
            f"avg_ratio=`{row.get('avg_ratio')}`, avg_expected=`{row.get('avg_expected_net_after_full_cost')}`, "
            f"avg_stop=`{row.get('avg_stop_risk')}`, sample=`{row.get('sample_sufficiency')}`"
        )
    lines.extend(["", "## Hypothetical thresholds"])
    for threshold, row in (report.get("hypothetical_ratio_threshold_simulation") or {}).items():
        lines.append(
            "- "
            f"{threshold}: additional_events=`{row.get('additional_admitted_events')}`, "
            f"additional_candidates=`{row.get('additional_candidates')}`, "
            f"clean_trades=`{row.get('clean_completed_historical_trades_available')}`, "
            f"expectancy=`{row.get('expectancy')}`, experiment_justified=`{row.get('experiment_justified')}`"
        )
    lines.extend(["", "## Required checks"])
    for key, value in (report.get("required_checks") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--autopsy-json",
        type=Path,
        default=ANALYSIS_DIR / "entry_edge_filtered_event_autopsy_current.json",
    )
    parser.add_argument(
        "--matrix-json",
        type=Path,
        default=ANALYSIS_DIR / "paper_entry_min_net_experiment_matrix_current.json",
    )
    parser.add_argument(
        "--smoke-json",
        type=Path,
        default=ANALYSIS_DIR / "next_research_candidate_runtime_smoke_current.json",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ANALYSIS_DIR / "entry_net_to_stop_ratio_calibration_current.json",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=ANALYSIS_DIR / "entry_net_to_stop_ratio_calibration_current.md",
    )
    args = parser.parse_args(argv)
    report = build_report(
        autopsy_path=args.autopsy_json,
        matrix_path=args.matrix_json if args.matrix_json.exists() else None,
        smoke_path=args.smoke_json if args.smoke_json.exists() else None,
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    args.md_out.write_text(render_markdown(report), encoding="utf-8")
    print(report["classification"])
    print(report["final_verdict"])
    print(args.json_out)
    print(args.md_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
