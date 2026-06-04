from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
CLASS_ENTRY_EDGE_FILTER_DOMINANT = "STRONGER_ALPHA_OBSERVATION_BLOCKED_BY_ENTRY_EDGE_FILTER"
CLASS_ALLOWLIST_DOMINANT = "STRONGER_ALPHA_OBSERVATION_BLOCKED_BY_ALLOWLIST"
CLASS_NO_RUNTIME_PROFILE_DOMINANT = "STRONGER_ALPHA_OBSERVATION_BLOCKED_BY_NO_RUNTIME_PROFILE"
CLASS_MIN_NET_DOMINANT = "STRONGER_ALPHA_OBSERVATION_BLOCKED_BY_MIN_NET"
CLASS_NO_POSITION_OPEN = "STRONGER_ALPHA_OBSERVATION_NO_POSITION_OPEN"
CLASS_HAS_POSITION_OPEN = "STRONGER_ALPHA_OBSERVATION_POSITION_OPENED"
CLASS_CONTAMINATED = "STRONGER_ALPHA_OBSERVATION_EVIDENCE_CONTAMINATED"

CONTAMINATION_KEYS = ("seed", "fallback", "mock", "force_open", "forced_cycle")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _canonical_strategy(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "")
    aliases = {
        "microbreakoutv2": "MICROBREAKOUT",
        "microbreakout": "MICROBREAKOUT",
        "momentumv2": "MOMENTUM",
        "momentum": "MOMENTUM",
        "meanreversionv2": "MEANREVERSION",
        "meanreversion": "MEANREVERSION",
        "mean_reversion": "MEANREVERSION",
        "trendfollowingv2": "TRENDFOLLOWING",
        "trendfollowing": "TRENDFOLLOWING",
    }
    return aliases.get(normalized, str(value or "").strip().upper())


def _candidate_key(payload: dict[str, Any]) -> str | None:
    symbol = str(payload.get("symbol") or "").upper()
    side = str(payload.get("side") or "").lower()
    strategy = _canonical_strategy(payload.get("canonical_strategy") or payload.get("strategy"))
    if not symbol or not strategy or side not in {"buy", "sell"}:
        return None
    return f"{symbol}:{strategy}:{side}"


def _is_contaminated(payload: dict[str, Any]) -> bool:
    flags = payload.get("contamination_flags")
    if not isinstance(flags, dict):
        return False
    for key in CONTAMINATION_KEYS:
        value = flags.get(key, 0)
        if value is True:
            return True
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value != 0:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _load_log_payloads(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "logs" not in tables:
            return []
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(logs)")}
        event_col = "event" if "event" in columns else "event_type" if "event_type" in columns else None
        details_col = "details" if "details" in columns else "payload" if "payload" in columns else None
        ts_col = "timestamp" if "timestamp" in columns else "ts" if "ts" in columns else None
        if event_col is None or details_col is None:
            return []
        selected = [event_col, details_col]
        if ts_col:
            selected.append(ts_col)
        payloads = []
        for row in conn.execute(f"SELECT {', '.join(selected)} FROM logs ORDER BY rowid ASC"):
            values = dict(row)
            try:
                payload = json.loads(str(values.get(details_col) or "{}"))
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            payload["event"] = values.get(event_col)
            if ts_col:
                payload["db_timestamp"] = values.get(ts_col)
            payloads.append(payload)
        return payloads
    finally:
        conn.close()


def _load_decision_payloads(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "decisions" not in tables:
            return []
        payloads = []
        for row in conn.execute("SELECT decision, details FROM decisions ORDER BY rowid ASC"):
            try:
                payload = json.loads(str(row["details"] or "{}"))
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            payload["decision"] = row["decision"]
            payloads.append(payload)
        return payloads
    finally:
        conn.close()


def _target_keys(targets_artifact: dict[str, Any]) -> set[str]:
    keys = set()
    for row in targets_artifact.get("selected_targets") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("candidate_key") or "").strip().upper()
        if key:
            keys.add(key)
    return keys


def _reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        reason = str(row.get("reason_code") or row.get("local_gate_reason") or row.get("effective_gate_reason") or "unknown")
        counts[reason] += 1
    return dict(counts.most_common())


def _classify(position_open_count: int, contaminated_count: int, target_reason_counts: dict[str, int]) -> str:
    if contaminated_count:
        return CLASS_CONTAMINATED
    if position_open_count:
        return CLASS_HAS_POSITION_OPEN
    if not target_reason_counts:
        return CLASS_NO_POSITION_OPEN
    top_reason = max(target_reason_counts.items(), key=lambda item: item[1])[0]
    if top_reason == "entry_edge_filtered":
        return CLASS_ENTRY_EDGE_FILTER_DOMINANT
    if top_reason == "symbol_strategy_side_allowlist":
        return CLASS_ALLOWLIST_DOMINANT
    if top_reason == "no_runtime_profile":
        return CLASS_NO_RUNTIME_PROFILE_DOMINANT
    if top_reason in {"entry_min_net_guard", "net_target_guard", "min_size"}:
        return CLASS_MIN_NET_DOMINANT
    return CLASS_NO_POSITION_OPEN


def audit_observation_blockers(db_path: Path | str, targets_artifact: Path | str) -> dict[str, Any]:
    db = Path(db_path)
    targets_path = Path(targets_artifact)
    targets = _read_json(targets_path)
    target_keys = _target_keys(targets)
    log_rows = _load_log_payloads(db)
    decision_rows = _load_decision_payloads(db)
    relevant_events = {"entry_eval_v2", "entry_reject_v2", "post_signal_trajectory_v2"}
    blocker_rows = [row for row in log_rows if row.get("event") in relevant_events]
    target_rows = [
        row
        for row in blocker_rows
        if (_candidate_key(row) or "").upper() in target_keys
    ]
    contaminated_count = sum(1 for row in log_rows if _is_contaminated(row))
    position_open_count = sum(1 for row in log_rows if row.get("event") == "position_open")
    target_reason_counts = _reason_counts(target_rows)
    global_reason_counts = _reason_counts(blocker_rows if blocker_rows else decision_rows)
    classification = _classify(position_open_count, contaminated_count, target_reason_counts)
    return {
        "classification": classification,
        "inputs": {
            "db_path": str(db),
            "targets_artifact": str(targets_path),
            "target_keys": sorted(target_keys),
        },
        "summary": {
            "log_event_count": len(log_rows),
            "decision_count": len(decision_rows),
            "position_open_count": position_open_count,
            "target_blocker_event_count": len(target_rows),
            "contaminated_event_count": contaminated_count,
        },
        "target_reason_counts": target_reason_counts,
        "global_reason_counts": global_reason_counts,
        "target_blocker_samples": target_rows[:20],
        "decision": _decision(classification),
    }


def _decision(classification: str) -> dict[str, Any]:
    if classification == CLASS_ENTRY_EDGE_FILTER_DOMINANT:
        return {
            "next_step": "stronger_alpha_design_required",
            "patch_runtime": False,
            "patch_threshold": False,
            "reason": "selected clean candidates exist but current entry edge filter rejects them before position open",
        }
    if classification == CLASS_HAS_POSITION_OPEN:
        return {
            "next_step": "analyze_clean_paper_trade_outcomes",
            "patch_runtime": False,
            "patch_threshold": False,
            "reason": "paper position opened; evaluate realized outcomes without profitability claim until evidence supports it",
        }
    if classification == CLASS_CONTAMINATED:
        return {
            "next_step": "discard_observation_evidence",
            "patch_runtime": False,
            "patch_threshold": False,
            "reason": "seed/fallback/mock/force-open contamination present",
        }
    return {
        "next_step": "adjust_paper_observation_scope_only",
        "patch_runtime": False,
        "patch_threshold": False,
        "reason": "no clean target-position path reached",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Stronger Alpha Observation Blocker Audit",
        "",
        f"- classification: `{report['classification']}`",
        f"- position_open_count: `{report['summary']['position_open_count']}`",
        f"- target_blocker_event_count: `{report['summary']['target_blocker_event_count']}`",
        f"- contaminated_event_count: `{report['summary']['contaminated_event_count']}`",
        f"- next_step: `{report['decision']['next_step']}`",
        "",
        "## Target Reason Counts",
    ]
    if not report["target_reason_counts"]:
        lines.append("- none")
    for reason, count in report["target_reason_counts"].items():
        lines.append(f"- {reason}: `{count}`")
    lines.extend(["", "## Global Reason Counts"])
    for reason, count in list(report["global_reason_counts"].items())[:20]:
        lines.append(f"- {reason}: `{count}`")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="tmp/controlled_kpi_after_20260604_120300.db")
    parser.add_argument("--targets", default="analysis/stronger_alpha_observation_targets_20260604_120300.json")
    parser.add_argument("--output-json", default="analysis/stronger_alpha_observation_blockers_20260604_120300.json")
    parser.add_argument("--output-md", default="analysis/stronger_alpha_observation_blockers_20260604_120300.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit_observation_blockers(WORKDIR / args.db, WORKDIR / args.targets)
    output_json = WORKDIR / args.output_json
    output_md = WORKDIR / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(report["classification"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
