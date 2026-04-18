import csv
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import time
from analysis.fl_impact_report import (
    FLDecisionSnapshot,
    create_report_json,
    create_report_markdown,
    evaluate_fl_impact,
)


DEFAULT_DECISION_LOG = Path("autopsy/decision_log.csv")
DEFAULT_REPORT_DIR = Path("reports/fl_impact")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


def _bool_from_decision(decision: Optional[str]) -> bool:
    if decision is None:
        return False
    decision = str(decision).lower()
    return decision in {"buy", "sell", "allow", "hold"} and decision != "hold"


def _extract_decision_pair(
    raw_decision: str,
    payload: Dict[str, Any],
) -> Tuple[str, str]:
    decision_before = (
        payload.get("entry_decision_before")
        or payload.get("entry_decision_raw")
        or payload.get("entry_decision")
        or raw_decision
    )
    decision_after = (
        payload.get("entry_decision_after")
        or payload.get("entry_decision_final")
        or payload.get("balanced_action")
        or payload.get("shadow_action")
        or payload.get("entry_decision")
        or raw_decision
    )
    return str(decision_before), str(decision_after)


def _extract_edge_pair(payload: Dict[str, Any]) -> Tuple[float, float]:
    # Legacy schema: explicit edge-over-fee pair
    edge_over_fee = payload.get("entry_edge_over_fee")
    if isinstance(edge_over_fee, dict):
        legacy_before = _safe_float(
            edge_over_fee.get("mean_edge_over_fee"),
            default=None,
        )
        legacy_after = _safe_float(
            edge_over_fee.get("shadow_edge_after_execution_cost"),
            default=None,
        )
        if legacy_before is not None:
            if legacy_after is None:
                legacy_after = legacy_before
            return float(legacy_before), float(legacy_after)

    live_edge = payload.get("entry_live_edge")
    threshold = None
    live_proxy = None
    if isinstance(live_edge, dict):
        threshold = _safe_float(live_edge.get("threshold"), default=None)
        live_proxy = _safe_float(live_edge.get("live_edge_proxy"), default=None)

    # Current runtime schema: reconstruct current/shadow edge from threshold+margins.
    current_margin = _safe_float(
        payload.get("current_margin_to_threshold"),
        default=None,
    )
    shadow_margin = _safe_float(payload.get("shadow_margin_to_threshold"), default=None)
    if (
        threshold is not None
        and current_margin is not None
        and shadow_margin is not None
    ):
        edge_before = float(threshold) + float(current_margin)
        edge_after = float(threshold) + float(shadow_margin)
        return edge_before, edge_after

    # Fallback: compare live edge proxy against threshold when no shadow margins.
    if threshold is not None and live_proxy is not None:
        return float(threshold), float(live_proxy)

    edge_after_execution = payload.get("entry_edge_after_execution")
    if isinstance(edge_after_execution, dict):
        reconstructed_after = _safe_float(
            edge_after_execution.get("edge_after_execution"),
            default=None,
        )
        if reconstructed_after is None:
            reconstructed_after = _safe_float(
                edge_after_execution.get("edge_after_realtime_cost"),
                default=None,
            )
        if reconstructed_after is not None:
            if live_proxy is not None:
                return float(live_proxy), float(reconstructed_after)
            return float(reconstructed_after), float(reconstructed_after)

    return 0.0, 0.0


def load_historical_decisions(
    source_path: Optional[Path] = None,
    limit: Optional[int] = None,
) -> Tuple[List[Tuple[str, str, Dict]], Dict[str, Any]]:
    source = Path(source_path) if source_path else DEFAULT_DECISION_LOG
    if not source.exists():
        raise FileNotFoundError(f"Decision source not found: {source}")

    decisions = []
    stats = Counter()
    bad_rows = []

    with source.open("r", encoding="utf-8", newline="") as f:
        for raw_line in f:
            stats["total_rows"] += 1
            if limit and len(decisions) >= limit:
                stats["skipped_limit"] += 1
                break

            line = raw_line.strip()
            if not line:
                stats["skipped_empty"] += 1
                continue

            ts = raw_decision = raw_payload = None
            try:
                csv_row = next(csv.reader([line]))
            except Exception:
                csv_row = []

            if len(csv_row) >= 3:
                ts = csv_row[0].strip()
                raw_decision = csv_row[1].strip()
                # if the entry is quoted and includes commas, csv.reader will keep it
                # as one field; unquoted comma-containing rows may be split into fields
                raw_payload = ",".join(csv_row[2:]).strip()
            else:
                parts = line.split(",", 2)
                if len(parts) < 3:
                    stats["skipped_malformed_line"] += 1
                    bad_rows.append({"line": line, "reason": "malformed_line"})
                    continue
                ts = parts[0].strip()
                raw_decision = parts[1].strip()
                raw_payload = parts[2].strip()

            if not raw_payload:
                stats["skipped_empty_payload"] += 1
                bad_rows.append({"line": line, "reason": "empty_payload"})
                continue

            raw_decision_norm = str(raw_decision or "").strip().lower()
            if (
                raw_decision_norm in {"strategy_switch", "risk_limit"}
                and not str(raw_payload).lstrip().startswith("{")
            ):
                # Legacy switch/risk events are plain text and not part of
                # decision impact corpus; track separately from malformed JSON.
                stats["skipped_non_decision_event"] += 1
                bad_rows.append({"line": line, "reason": "non_decision_event"})
                continue

            try:
                payload = json.loads(raw_payload)
                if isinstance(payload, str):
                    payload = json.loads(payload)
            except json.JSONDecodeError:
                # Skip non-json rows (e.g., risk_limit events) for this analysis
                stats["skipped_invalid_json"] += 1
                bad_rows.append({"line": line, "reason": "invalid_json"})
                continue

            if not isinstance(payload, dict):
                stats["skipped_non_dict_payload"] += 1
                bad_rows.append({"line": line, "reason": "non_dict_payload"})
                continue

            decisions.append((ts, raw_decision, payload))

    meta = {
        "total_rows": stats["total_rows"],
        "skipped_rows": (
            stats["skipped_empty"]
            + stats["skipped_malformed_line"]
            + stats["skipped_empty_payload"]
            + stats["skipped_invalid_json"]
            + stats["skipped_non_dict_payload"]
            + stats["skipped_non_decision_event"]
            + stats["skipped_limit"]
        ),
        "skipped_details": {k: v for k, v in stats.items() if k != "total_rows"},
        "bad_rows": bad_rows,
    }

    return decisions, meta


def build_fl_decision_snapshots(
    decision_rows: List[Tuple[str, str, Dict]]
) -> List[FLDecisionSnapshot]:
    snapshots: List[FLDecisionSnapshot] = []

    for idx, (ts, raw_decision, payload) in enumerate(
        sorted(decision_rows, key=lambda x: x[0])
    ):
        decision_before, decision_after = _extract_decision_pair(
            raw_decision,
            payload,
        )
        edge_before, edge_after = _extract_edge_pair(payload)

        admission_before = _bool_from_decision(decision_before)
        admission_after = _bool_from_decision(decision_after)

        snapshot_id = f"{ts}-{idx:06d}"

        snapshots.append(
            FLDecisionSnapshot(
                id=snapshot_id,
                decision_before=str(decision_before),
                decision_after=str(decision_after),
                edge_before=edge_before,
                edge_after=edge_after,
                admission_before=admission_before,
                admission_after=admission_after,
            )
        )

    return snapshots


def run_fl_impact_analysis(
    source_path: Optional[Path] = None,
    run_id: Optional[str] = None,
    limit: Optional[int] = None,
    profile: bool = False,
    report_dir: Optional[Path] = None,
    fail_if_exists: bool = False,
) -> Dict[str, Any]:
    """Run FL impact analysis.

    Args:
        source_path: path to historical decision CSV.
        run_id: identifier for this run (used for output JSON filename).
        limit: max number of rows to process from decision CSV.
        profile: if True, include perf timings in result.
        report_dir: path to directory where report files should be written.
        fail_if_exists: if True, raise FileExistsError when output files already exist.

    Behavior:
        - JSON report: {run_id}.json
        - Per-run markdown report: summary-{run_id}.md
        - Legacy report alias: summary.md (always overwritten with latest run output)

    Returns:
        result dict with metrics, paths, and stats.
    """
    perf = {}
    t_start = time.perf_counter()

    t0 = time.perf_counter()
    decision_rows, parse_meta = load_historical_decisions(
        source_path=source_path,
        limit=limit,
    )
    t1 = time.perf_counter()

    snapshots = build_fl_decision_snapshots(decision_rows)
    t2 = time.perf_counter()

    if not snapshots:
        raise ValueError("No FL decision snapshots could be built from source data")

    metrics = evaluate_fl_impact(snapshots)
    t3 = time.perf_counter()

    if profile:
        perf["load_time_seconds"] = t1 - t0
        perf["snapshot_build_time_seconds"] = t2 - t1
        perf["evaluation_time_seconds"] = t3 - t2

    total_time = time.perf_counter() - t_start

    if run_id is None:
        run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S")

    report_dir = Path(report_dir) if report_dir is not None else DEFAULT_REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)

    result_json_path = report_dir / f"{run_id}.json"
    summary_md_path = report_dir / f"summary-{run_id}.md"
    legacy_summary_md_path = report_dir / "summary.md"

    if fail_if_exists and (result_json_path.exists() or summary_md_path.exists()):
        raise FileExistsError(
            f"Output already exists: {result_json_path} or {summary_md_path}. "
            "Use a different run_id, report_dir, or set fail_if_exists=False"
        )

    json_content = create_report_json(snapshots)
    md_content = create_report_markdown(snapshots)

    t4 = time.perf_counter()
    result_json_path.write_text(json_content, encoding="utf-8")
    summary_md_path.write_text(md_content, encoding="utf-8")

    # backward-compatibility: update legacy summary pointer to latest run summary
    legacy_summary_md_path.write_text(md_content, encoding="utf-8")

    t5 = time.perf_counter()

    hash_value = hashlib.sha256(json_content.encode("utf-8")).hexdigest()

    result = {
        "run_id": run_id,
        "result_json_path": str(result_json_path),
        "summary_md_path": str(summary_md_path),
        "legacy_summary_md_path": str(legacy_summary_md_path),
        "metrics": metrics,
        "snapshot_count": len(snapshots),
        "json_sha256": hash_value,
        "total_decisions": len(decision_rows),
        "total_rows": parse_meta.get("total_rows", len(decision_rows)),
        "skipped_rows": parse_meta.get("skipped_rows", 0),
        "skipped_details": parse_meta.get("skipped_details", {}),
        "bad_rows": parse_meta.get("bad_rows", []),
        "fail_if_exists": fail_if_exists,
        "total_time_seconds": total_time,
        "write_time_seconds": t5 - t4,
    }

    if profile:
        result["perf"] = perf

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run FL impact evaluation from history corpus"
    )
    parser.add_argument(
        "--source",
        type=str,
        default=str(DEFAULT_DECISION_LOG),
        help="Source decision CSV path",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="ID for this run",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of rows to process",
    )
    args = parser.parse_args()

    result = run_fl_impact_analysis(
        source_path=Path(args.source),
        run_id=args.run_id,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2))
