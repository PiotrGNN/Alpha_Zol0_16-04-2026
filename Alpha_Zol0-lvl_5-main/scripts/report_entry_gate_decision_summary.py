import argparse
import json
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ENTRY_GATE_EVENT = "entry_gate_decision_summary"
RISK_EVENT = "risk_decision"
ENTRY_GATE_REQUIRED_KEYS = (
    "ts",
    "symbol",
    "side",
    "final_allow",
    "entry_gate_bucket",
    "global_block_reason",
    "local_gate_reason",
    "effective_gate_reason",
    "effective_gate_reason_origin",
    "paper_gate_active",
    "paper_gate_reason",
    "paper_gate_mode",
    "risk_allow_before_paper_gate",
    "paper_gate_override",
    "entry_decision_raw",
    "entry_decision_final",
    "entry_reason",
    "entry_reason_classification",
    "entry_live_edge",
    "entry_edge_over_fee",
    "entry_edge_after_execution",
    "spread",
    "liquidity_ok",
    "confidence",
    "fee_estimate",
    "current_edge",
    "realtime_edge",
    "max_positions_blocked",
)
ENTRY_GATE_SPREAD_KEYS = ("abs", "pct", "bps")


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _build_anchor(cur: sqlite3.Cursor, hours: int | None):
    if hours is None:
        return None
    max_ts = cur.execute("select max(timestamp) from logs").fetchone()[0]
    if not max_ts:
        return None
    return (
        datetime.fromisoformat(str(max_ts).replace("Z", "+00:00"))
        - timedelta(hours=hours)
    ).isoformat(sep=" ")


def _load_rows(db_path: Path, hours: int | None, event: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        params = [event]
        query = (
            "select rowid, timestamp, event, details from logs "
            "where event = ?"
        )
        if hours is not None:
            anchor = _build_anchor(cur, hours)
            if anchor is not None:
                query += " and timestamp >= ?"
                params.append(anchor)
        query += " order by rowid asc"
        rows = cur.execute(query, params).fetchall()
        return rows
    finally:
        conn.close()


def _load_sequence_rows(db_path: Path, hours: int | None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        params = [ENTRY_GATE_EVENT, RISK_EVENT]
        query = (
            "select rowid, timestamp, event, details from logs "
            "where event in (?, ?)"
        )
        if hours is not None:
            anchor = _build_anchor(cur, hours)
            if anchor is not None:
                query += " and timestamp >= ?"
                params.append(anchor)
        query += " order by rowid asc"
        return cur.execute(query, params).fetchall()
    finally:
        conn.close()


def _mean_median(values):
    numbers = [value for value in values if value is not None]
    if not numbers:
        return {"count": 0, "mean": None, "median": None}
    return {
        "count": len(numbers),
        "mean": statistics.fmean(numbers),
        "median": statistics.median(numbers),
    }


def _safe_json_loads(raw):
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _payload_health(payload):
    if not isinstance(payload, dict):
        return {
            "complete": False,
            "missing_keys": list(ENTRY_GATE_REQUIRED_KEYS),
            "missing_spread_keys": list(ENTRY_GATE_SPREAD_KEYS),
        }
    missing_keys = [key for key in ENTRY_GATE_REQUIRED_KEYS if key not in payload]
    spread_obj = payload.get("spread")
    if isinstance(spread_obj, dict):
        missing_spread_keys = [
            key for key in ENTRY_GATE_SPREAD_KEYS if key not in spread_obj
        ]
    else:
        missing_spread_keys = list(ENTRY_GATE_SPREAD_KEYS)
    return {
        "complete": not missing_keys and not missing_spread_keys,
        "missing_keys": missing_keys,
        "missing_spread_keys": missing_spread_keys,
    }


def _classify_position_open_truth(payload: dict):
    if not isinstance(payload, dict):
        return "UNKNOWN_REQUIRES_REVIEW"
    existing = str(payload.get("entry_open_truth_classification") or "").strip()
    if existing:
        return existing
    selection_source = str(payload.get("selection_source") or "").strip().lower()
    entry_reason = str(payload.get("entry_reason") or "").strip().lower()
    decision_router_path = str(payload.get("decision_router_path") or "").strip().lower()
    override_reason = str(payload.get("override_reason") or "").strip().lower()
    if (
        selection_source == "paper_auto_open_fallback"
        or decision_router_path == "paper_auto_open_fallback"
        or override_reason == "paper_auto_open_fallback"
    ):
        return "PAPER_AUTO_OPEN_FALLBACK"
    if (
        selection_source == "entry_symbol_strategy_side_allowlist"
        or decision_router_path == "paper_auto_open_allowlisted"
        or override_reason == "paper_auto_open_allowlisted"
        or entry_reason == "paper_auto_open_allowlisted"
    ):
        return "BOOTSTRAP_ALLOWLIST_ASSISTED"
    if entry_reason in {
        "edge_discovered_dynamic",
        "entry_live_edge",
        "live_edge_discovered",
        "dynamic_edge_discovered",
    }:
        return "EDGE_DISCOVERED_DYNAMIC"
    return "UNKNOWN_REQUIRES_REVIEW"


def _position_open_identity(payload: dict):
    payload = payload if isinstance(payload, dict) else {}
    nested_position = payload.get("position")
    if not isinstance(nested_position, dict):
        nested_position = {}
    canonical_bucket = payload.get("canonical_bucket")
    if not isinstance(canonical_bucket, dict):
        canonical_bucket = nested_position.get("canonical_bucket")
    canonical_bucket_key = payload.get("canonical_bucket_key")
    if canonical_bucket_key in (None, "") and isinstance(canonical_bucket, dict):
        canonical_bucket_key = canonical_bucket.get("canonical_bucket_key")
    strategy = payload.get("strategy")
    if strategy in (None, ""):
        strategy = nested_position.get("entry_main_strategy") or nested_position.get("strategy")
    side = payload.get("side")
    if side in (None, ""):
        side = nested_position.get("side")
    selection_source = payload.get("selection_source")
    if selection_source in (None, ""):
        selection_source = nested_position.get("selection_source")
    entry_main_strategy = payload.get("entry_main_strategy")
    if entry_main_strategy in (None, ""):
        entry_main_strategy = nested_position.get("entry_main_strategy") or strategy
    return {
        "symbol": payload.get("symbol") or nested_position.get("symbol"),
        "strategy": strategy,
        "entry_main_strategy": entry_main_strategy,
        "side": side,
        "selection_source": selection_source,
        "decision_router_path": payload.get("decision_router_path")
        or nested_position.get("decision_router_path"),
        "override_reason": payload.get("override_reason")
        or nested_position.get("override_reason"),
        "canonical_bucket": canonical_bucket,
        "canonical_bucket_key": canonical_bucket_key,
    }


def build_report(db_path: Path, hours: int | None):
    db_path = db_path.resolve()
    rows = _load_rows(db_path, hours, ENTRY_GATE_EVENT)
    risk_rows = _load_rows(db_path, hours, RISK_EVENT)
    open_rows = _load_rows(db_path, hours, "position_open")
    sequence_rows = _load_sequence_rows(db_path, hours)
    admitted = 0
    blocked = 0
    global_reasons = Counter()
    local_reasons = Counter()
    open_truth_reasons = Counter()
    paper_gate_overrides = 0
    complete_payloads = 0
    incomplete_samples = []
    last_payload = {}
    last_risk_payload = {}
    last_open_payload = {}
    pair_count = 0
    symbol_mismatch_pairs = 0
    pending_summary = None
    metrics = {
        "admitted": {
            "current_edge": [],
            "realtime_edge": [],
            "spread_bps": [],
            "confidence": [],
        },
        "blocked": {
            "current_edge": [],
            "realtime_edge": [],
            "spread_bps": [],
            "confidence": [],
        },
    }
    for row in rows:
        payload = _safe_json_loads(row["details"])
        if not isinstance(payload, dict):
            continue
        last_payload = payload
        health = _payload_health(payload)
        if health["complete"]:
            complete_payloads += 1
        elif len(incomplete_samples) < 10:
            incomplete_samples.append(
                {
                    "rowid": row["rowid"],
                    "timestamp": row["timestamp"],
                    "symbol": payload.get("symbol"),
                    "missing_keys": health["missing_keys"],
                    "missing_spread_keys": health["missing_spread_keys"],
                }
            )
        is_admitted = bool(payload.get("final_allow"))
        bucket = "admitted" if is_admitted else "blocked"
        if is_admitted:
            admitted += 1
        else:
            blocked += 1
        global_reason = payload.get("global_block_reason")
        local_reason = payload.get("local_gate_reason")
        if global_reason:
            global_reasons[str(global_reason)] += 1
        if local_reason:
            local_reasons[str(local_reason)] += 1
        if payload.get("paper_gate_override"):
            paper_gate_overrides += 1
        spread = (
            payload.get("spread")
            if isinstance(payload.get("spread"), dict)
            else {}
        )
        metrics[bucket]["current_edge"].append(_safe_float(payload.get("current_edge")))
        metrics[bucket]["realtime_edge"].append(
            _safe_float(payload.get("realtime_edge"))
        )
        metrics[bucket]["spread_bps"].append(_safe_float(spread.get("bps")))
        metrics[bucket]["confidence"].append(_safe_float(payload.get("confidence")))
    for row in risk_rows:
        last_risk_payload = _safe_json_loads(row["details"])
    for row in open_rows:
        payload = _safe_json_loads(row["details"])
        if not isinstance(payload, dict):
            continue
        last_open_payload = payload
        open_truth = _classify_position_open_truth(payload)
        if open_truth:
            open_truth_reasons[str(open_truth)] += 1
    for row in sequence_rows:
        payload = _safe_json_loads(row["details"])
        if row["event"] == ENTRY_GATE_EVENT:
            pending_summary = payload
        elif row["event"] == RISK_EVENT:
            if pending_summary is not None:
                pair_count += 1
                if pending_summary.get("symbol") != payload.get("symbol"):
                    symbol_mismatch_pairs += 1
            pending_summary = None
    trailing_summary_rows = 1 if pending_summary is not None else 0
    relaxed_count_matches = (
        len(rows) == len(risk_rows)
        or (
            len(rows) == len(risk_rows) + 1
            and trailing_summary_rows == 1
            and symbol_mismatch_pairs == 0
        )
    )
    last_health = _payload_health(last_payload)
    return {
        "db_path": str(db_path),
        "hours": hours,
        "event": ENTRY_GATE_EVENT,
        "rows": len(rows),
        "risk_decision_rows": len(risk_rows),
        "count_alignment": {
            "entry_gate_decision_summary": len(rows),
            "risk_decision": len(risk_rows),
            "delta": len(rows) - len(risk_rows),
            "count_matches": relaxed_count_matches,
        },
        "ordering": {
            "summary_before_risk_pairs": pair_count,
            "risk_without_summary": max(0, len(risk_rows) - pair_count),
            "summary_without_risk": max(0, len(rows) - pair_count),
            "trailing_summary_rows": trailing_summary_rows,
            "symbol_mismatch_pairs": symbol_mismatch_pairs,
            "all_pairs_in_order": (
                symbol_mismatch_pairs == 0
                and max(0, len(risk_rows) - pair_count) == 0
                and max(0, len(rows) - pair_count) <= 1
            ),
        },
        "payload_completeness": {
            "required_keys": list(ENTRY_GATE_REQUIRED_KEYS),
            "required_spread_keys": list(ENTRY_GATE_SPREAD_KEYS),
            "complete_rows": complete_payloads,
            "incomplete_rows": len(rows) - complete_payloads,
            "all_complete": len(rows) > 0 and complete_payloads == len(rows),
            "sample_incomplete_rows": incomplete_samples,
        },
        "admitted_vs_blocked": {"admitted": admitted, "blocked": blocked},
        "top_global_block_reason": global_reasons.most_common(10),
        "top_local_gate_reason": local_reasons.most_common(10),
        "paper_gate_overrides": paper_gate_overrides,
        "last_entry_gate_decision_summary": {
            "symbol": last_payload.get("symbol"),
            "side": last_payload.get("side"),
            "final_allow": last_payload.get("final_allow"),
            "paper_gate_active": last_payload.get("paper_gate_active"),
            "missing_keys": last_health["missing_keys"],
            "missing_spread_keys": last_health["missing_spread_keys"],
        },
        "last_risk_decision": {
            "symbol": last_risk_payload.get("symbol"),
            "entry_decision": last_risk_payload.get("entry_decision"),
            "allow": last_risk_payload.get("allow"),
        },
        "position_open_rows": len(open_rows),
        "position_open_truth_classification_counts": open_truth_reasons.most_common(10),
        "last_position_open": {
            **_position_open_identity(last_open_payload),
            "entry_reason": last_open_payload.get("entry_reason"),
            "entry_open_truth_classification": _classify_position_open_truth(
                last_open_payload
            ),
        },
        "metrics": {
            bucket: {
                "current_edge": _mean_median(values["current_edge"]),
                "realtime_edge": _mean_median(values["realtime_edge"]),
                "spread_bps": _mean_median(values["spread_bps"]),
                "confidence": _mean_median(values["confidence"]),
            }
            for bucket, values in metrics.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Report PAPER entry gate decision summary metrics from zol0.db"
    )
    parser.add_argument(
        "--db-path",
        default="zol0.db",
        help="Path to sqlite database. Default: zol0.db",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help=(
            "Lookback window in hours based on max log timestamp. "
            "Use 0 to disable filtering."
        ),
    )
    args = parser.parse_args()
    hours = args.hours if args.hours and args.hours > 0 else None
    report = build_report(Path(args.db_path), hours)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
