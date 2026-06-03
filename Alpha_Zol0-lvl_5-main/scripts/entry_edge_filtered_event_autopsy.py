from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"
TARGET_EVENTS = {"entry_eval_v2", "entry_reject_v2", "entry_gate_decision_summary"}
TARGET_REASONS = {
    "entry_edge_filtered",
    "entry_min_net_guard",
    "entry_net_to_stop_guard",
}
EPSILON = 1e-9


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _dig(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _canonical_strategy(value: Any) -> str:
    return str(value or "").strip()


def _canonical_key(symbol: Any, strategy: Any, side: Any) -> str:
    return (
        f"{str(symbol or '').strip().upper()}:"
        f"{_canonical_strategy(strategy)}:"
        f"{str(side or '').strip().lower()}"
    )


def _close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return True
    return abs(float(left) - float(right)) <= EPSILON


def _extract_sizing_trace(payload: dict[str, Any]) -> dict[str, Any]:
    direct = payload.get("sizing_trace")
    if isinstance(direct, dict):
        return direct
    nested = _dig(payload, ("risk_block_fields", "sizing_trace"))
    if isinstance(nested, dict):
        return nested
    meta = _dig(payload, ("meta", "sizing_trace"))
    return meta if isinstance(meta, dict) else {}


def _extract_cost_breakdown(payload: dict[str, Any]) -> dict[str, Any]:
    cost = payload.get("cost_breakdown")
    if isinstance(cost, dict):
        return cost
    meta_cost = _dig(payload, ("meta", "cost_breakdown"))
    return meta_cost if isinstance(meta_cost, dict) else {}


def _reason(payload: dict[str, Any]) -> str:
    return str(
        payload.get("reason_code")
        or payload.get("local_gate_reason")
        or payload.get("effective_gate_reason")
        or payload.get("gate_reason")
        or ""
    )


def _extract_expected_net_after_cost(payload: dict[str, Any]) -> float | None:
    return (
        _safe_float(payload.get("expected_net_after_cost"))
        or _safe_float(_dig(payload, ("entry_edge_after_execution", "expected_net_after_cost")))
        or _safe_float(_dig(payload, ("meta", "expected_net_after_cost")))
    )


def _extract_expected_edge_after_fee(payload: dict[str, Any]) -> float | None:
    return (
        _safe_float(payload.get("expected_edge_after_fee"))
        or _safe_float(_dig(payload, ("entry_edge_over_fee", "expected_edge_after_fee")))
        or _safe_float(_dig(payload, ("meta", "expected_edge_after_fee")))
    )


def extract_runtime_events(
    db_path: Path,
    *,
    run_id: str,
    threshold: float | None,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, timestamp, event, details FROM logs "
            "WHERE event IN ('entry_eval_v2','entry_reject_v2','entry_gate_decision_summary') "
            "ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()

    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["details"] or "{}")
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        reason = _reason(payload)
        if reason not in TARGET_REASONS:
            continue

        cost = _extract_cost_breakdown(payload)
        sizing = _extract_sizing_trace(payload)
        expected_move = _safe_float(payload.get("expected_move"))
        expected_move_scaled = (
            _safe_float(payload.get("expected_move_scaled"))
            or _safe_float(cost.get("expected_move_scaled"))
            or _safe_float(_dig(payload, ("signal_metadata", "expected_move_scaled")))
            or expected_move
        )
        fee_round_trip_ratio = _safe_float(cost.get("fee_round_trip_ratio"))
        total_cost_ratio = _safe_float(cost.get("total_cost_ratio"))
        expected_edge_after_fee = _extract_expected_edge_after_fee(payload)
        expected_net_after_cost = _extract_expected_net_after_cost(payload)
        formula_expected_edge_after_fee = (
            expected_move_scaled - fee_round_trip_ratio
            if expected_move_scaled is not None and fee_round_trip_ratio is not None
            else None
        )
        formula_expected_net_after_cost = (
            expected_move_scaled - total_cost_ratio
            if expected_move_scaled is not None and total_cost_ratio is not None
            else None
        )
        expected_full = _safe_float(sizing.get("expected_net_after_full_cost"))
        final_notional = _safe_float(sizing.get("final_notional_usdt"))
        formula_expected_full = (
            expected_net_after_cost * final_notional
            if expected_net_after_cost is not None and final_notional is not None
            else None
        )
        stop_loss = _safe_float(sizing.get("estimated_stop_loss_net_usdt"))
        entry_ratio = _safe_float(sizing.get("entry_net_to_stop_ratio"))
        formula_entry_ratio = (
            expected_full / stop_loss
            if expected_full is not None and stop_loss is not None and stop_loss > 0.0
            else None
        )
        entry_min_net = _safe_float(sizing.get("entry_min_net_usdt"))
        entry_min_ratio = _safe_float(sizing.get("entry_min_net_to_stop_ratio"))
        formula_match = all(
            (
                _close(expected_edge_after_fee, formula_expected_edge_after_fee),
                _close(expected_net_after_cost, formula_expected_net_after_cost),
                _close(expected_full, formula_expected_full),
                _close(entry_ratio, formula_entry_ratio),
            )
        )
        dominant_blocker = reason
        records.append(
            {
                "run_id": run_id,
                "db_path": str(db_path),
                "threshold": threshold,
                "id": int(row["id"]),
                "timestamp": str(row["timestamp"]),
                "event": str(row["event"]),
                "reason_code": reason,
                "symbol": payload.get("symbol"),
                "strategy": payload.get("strategy"),
                "side": payload.get("side"),
                "canonical_key": _canonical_key(
                    payload.get("symbol"),
                    payload.get("strategy"),
                    payload.get("side"),
                ),
                "expected_move": expected_move,
                "expected_move_raw": _safe_float(payload.get("expected_move_raw")),
                "expected_move_scaled": expected_move_scaled,
                "expected_gross_before_cost": (
                    _safe_float(payload.get("expected_gross_before_cost"))
                    or _safe_float(cost.get("expected_gross_before_cost"))
                    or expected_move_scaled
                ),
                "fee_round_trip_ratio": fee_round_trip_ratio,
                "spread_ratio": _safe_float(cost.get("spread_ratio")),
                "slippage_ratio": _safe_float(cost.get("slippage_ratio")),
                "total_cost_ratio": total_cost_ratio,
                "expected_edge_after_fee": expected_edge_after_fee,
                "expected_net_after_cost": expected_net_after_cost,
                "formula_expected_edge_after_fee": formula_expected_edge_after_fee,
                "formula_expected_net_after_cost": formula_expected_net_after_cost,
                "final_notional_usdt": final_notional,
                "expected_net_after_full_cost": expected_full,
                "formula_expected_net_after_full_cost": formula_expected_full,
                "entry_min_net_usdt": entry_min_net,
                "estimated_stop_loss_net_usdt": stop_loss,
                "entry_net_to_stop_ratio": entry_ratio,
                "formula_entry_net_to_stop_ratio": formula_entry_ratio,
                "entry_min_net_to_stop_ratio": entry_min_ratio,
                "edge_filter_triggered": reason == "entry_edge_filtered",
                "min_net_triggered": (
                    entry_min_net is not None
                    and expected_full is not None
                    and expected_full < entry_min_net
                ),
                "net_to_stop_triggered": (
                    entry_min_ratio is not None
                    and (entry_ratio or formula_entry_ratio) is not None
                    and float(entry_ratio if entry_ratio is not None else formula_entry_ratio)
                    < entry_min_ratio
                ),
                "dominant_blocker": dominant_blocker,
                "formula_match": formula_match,
            }
        )
    return records


def _numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": float(mean(values)),
    }


def classify_autopsy(records: list[dict[str, Any]]) -> dict[str, Any]:
    formula_mismatch_count = sum(1 for row in records if not row.get("formula_match"))
    threshold_rows = [
        row
        for row in records
        if _safe_float(row.get("threshold")) is not None
        and _safe_float(row.get("entry_min_net_usdt")) is not None
    ]
    threshold_override_propagated = bool(
        threshold_rows
        and all(
            _close(_safe_float(row.get("threshold")), _safe_float(row.get("entry_min_net_usdt")))
            for row in threshold_rows
        )
    )
    threshold_override_missing = bool(records and not threshold_rows)
    ratio_block_count = sum(
        1
        for row in records
        if row.get("net_to_stop_triggered")
        or (
            _safe_float(row.get("entry_net_to_stop_ratio")) is not None
            and _safe_float(row.get("entry_min_net_to_stop_ratio")) is not None
            and float(row["entry_net_to_stop_ratio"])
            < float(row["entry_min_net_to_stop_ratio"])
        )
    )
    min_net_count = sum(1 for row in records if row.get("min_net_triggered"))
    edge_count = sum(1 for row in records if row.get("reason_code") == "entry_edge_filtered")

    if formula_mismatch_count:
        classification = "ENTRY_EDGE_FILTER_FORMULA_MISMATCH"
    elif threshold_override_missing:
        classification = "THRESHOLD_OVERRIDE_NOT_PROPAGATED"
    elif threshold_override_propagated and ratio_block_count:
        classification = "THRESHOLD_OVERRIDE_PROPAGATED_RISK_RATIO_BLOCKS"
    elif records and (min_net_count or edge_count):
        classification = "ENTRY_EDGE_FILTER_CORRECT_WEAK_EDGE"
    else:
        classification = "ENTRY_EDGE_AUTOPSY_INCONCLUSIVE"

    return {
        "classification": classification,
        "threshold_override_propagated": threshold_override_propagated,
        "threshold_override_missing": threshold_override_missing,
        "formula_mismatch_count": formula_mismatch_count,
        "entry_edge_filtered_count": edge_count,
        "entry_min_net_guard_count": min_net_count,
        "entry_net_to_stop_guard_count": ratio_block_count,
    }


def _extract_threshold(result: dict[str, Any]) -> float | None:
    after_env = result.get("after_env_overrides")
    after_env = after_env if isinstance(after_env, dict) else {}
    params = result.get("params")
    params = params if isinstance(params, dict) else {}
    params_after_env = params.get("after_env_overrides")
    params_after_env = params_after_env if isinstance(params_after_env, dict) else {}
    params_after_env_cli = params.get("after_env_overrides_cli")
    params_after_env_cli = (
        params_after_env_cli if isinstance(params_after_env_cli, dict) else {}
    )
    after = result.get("after")
    after = after if isinstance(after, dict) else {}
    effective = after.get("effective_env_values")
    effective = effective if isinstance(effective, dict) else {}
    return _safe_float(
        after_env.get("ENTRY_MIN_NET_USDT")
        or params_after_env.get("ENTRY_MIN_NET_USDT")
        or params_after_env_cli.get("ENTRY_MIN_NET_USDT")
        or effective.get("ENTRY_MIN_NET_USDT")
    )


def _result_run_id(path: Path, result: dict[str, Any]) -> str:
    after = result.get("after")
    after = after if isinstance(after, dict) else {}
    db_path = str(after.get("db_path") or "")
    if "controlled_kpi_" in db_path:
        return Path(db_path).stem.replace("zol0_paper_", "")
    return path.stem


def build_report(result_paths: list[Path]) -> dict[str, Any]:
    all_records: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for result_path in result_paths:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        after = result.get("after")
        after = after if isinstance(after, dict) else {}
        db_path = Path(str(after.get("db_path") or ""))
        threshold = _extract_threshold(result)
        run_id = _result_run_id(result_path, result)
        records = extract_runtime_events(db_path, run_id=run_id, threshold=threshold)
        runs.append(
            {
                "run_id": run_id,
                "result_path": str(result_path),
                "db_path": str(db_path),
                "threshold": threshold,
                "record_count": len(records),
                "effective_env_values_has_entry_min_net": (
                    "ENTRY_MIN_NET_USDT"
                    in (
                        after.get("effective_env_values")
                        if isinstance(after.get("effective_env_values"), dict)
                        else {}
                    )
                ),
            }
        )
        all_records.extend(records)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in all_records:
        grouped[f"{record['canonical_key']}|{record.get('threshold')}"].append(record)

    candidate_summary: dict[str, dict[str, Any]] = {}
    for key, rows in sorted(grouped.items()):
        candidate_summary[key] = {
            "record_count": len(rows),
            "entry_edge_filtered_count": sum(
                1 for row in rows if row.get("reason_code") == "entry_edge_filtered"
            ),
            "entry_min_net_guard_count": sum(
                1 for row in rows if row.get("reason_code") == "entry_min_net_guard"
            ),
            "entry_net_to_stop_guard_count": sum(
                1 for row in rows if row.get("reason_code") == "entry_net_to_stop_guard"
            ),
            "expected_net_after_cost_stats": _numeric_summary(
                [
                    float(row["expected_net_after_cost"])
                    for row in rows
                    if _safe_float(row.get("expected_net_after_cost")) is not None
                ]
            ),
            "expected_net_after_full_cost_stats": _numeric_summary(
                [
                    float(row["expected_net_after_full_cost"])
                    for row in rows
                    if _safe_float(row.get("expected_net_after_full_cost")) is not None
                ]
            ),
            "entry_net_to_stop_ratio_stats": _numeric_summary(
                [
                    float(row["entry_net_to_stop_ratio"])
                    for row in rows
                    if _safe_float(row.get("entry_net_to_stop_ratio")) is not None
                ]
            ),
        }

    classification = classify_autopsy(all_records)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        **classification,
        "run_count": len(runs),
        "event_count": len(all_records),
        "runs": runs,
        "candidate_threshold_summary": candidate_summary,
        "events": all_records,
        "formula": {
            "expected_edge_after_fee": "expected_move_scaled - fee_round_trip_ratio",
            "expected_net_after_cost": "expected_move_scaled - total_cost_ratio",
            "expected_net_after_full_cost": "expected_net_after_cost * final_notional_usdt",
            "entry_net_to_stop_ratio": "expected_net_after_full_cost / estimated_stop_loss_net_usdt",
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Entry edge filtered event autopsy",
        "",
        f"- classification: `{report.get('classification')}`",
        f"- threshold_override_propagated: `{report.get('threshold_override_propagated')}`",
        f"- formula_mismatch_count: `{report.get('formula_mismatch_count')}`",
        f"- event_count: `{report.get('event_count')}`",
        "",
        "## Formula contract",
    ]
    for key, value in (report.get("formula") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Candidate threshold summary"])
    for key, row in (report.get("candidate_threshold_summary") or {}).items():
        lines.append(
            "- "
            f"{key}: records=`{row.get('record_count')}`, "
            f"edge=`{row.get('entry_edge_filtered_count')}`, "
            f"min_net=`{row.get('entry_min_net_guard_count')}`, "
            f"net_to_stop=`{row.get('entry_net_to_stop_guard_count')}`, "
            f"full_cost_max=`{(row.get('expected_net_after_full_cost_stats') or {}).get('max')}`, "
            f"ratio_max=`{(row.get('entry_net_to_stop_ratio_stats') or {}).get('max')}`"
        )
    lines.extend(["", "## Runs"])
    for row in report.get("runs") or []:
        lines.append(
            "- "
            f"{row.get('run_id')}: threshold=`{row.get('threshold')}`, "
            f"records=`{row.get('record_count')}`, "
            f"effective_env_has_entry_min_net=`{row.get('effective_env_values_has_entry_min_net')}`"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-json", action="append", type=Path, required=True)
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ANALYSIS_DIR / "entry_edge_filtered_event_autopsy_current.json",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=ANALYSIS_DIR / "entry_edge_filtered_event_autopsy_current.md",
    )
    args = parser.parse_args(argv)

    report = build_report(args.result_json)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    args.md_out.write_text(render_markdown(report), encoding="utf-8")
    print(report["classification"])
    print(args.json_out)
    print(args.md_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
