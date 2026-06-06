from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_json(raw: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_events(db_path: Path) -> List[Dict[str, Any]]:
    with sqlite3.connect(str(db_path)) as connection:
        rows = connection.execute(
            "select event, details from logs order by id"
        ).fetchall()
    return [{"event": event, "payload": _safe_json(details)} for event, details in rows]


def _load_report_json(report_json_path: Optional[Path]) -> Dict[str, Any]:
    if report_json_path is None or not report_json_path.exists():
        return {}
    return _safe_json(report_json_path.read_text(encoding="utf-8"))


def _latest_payload(events: List[Dict[str, Any]], event_name: str) -> Dict[str, Any]:
    for row in reversed(events):
        if row["event"] == event_name:
            return dict(row["payload"])
    return {}


def _event_payloads(events: List[Dict[str, Any]], event_name: str) -> List[Dict[str, Any]]:
    return [dict(row["payload"]) for row in events if row["event"] == event_name]


def analyze_reachability_gap(
    *,
    db_path: Path,
    report_json_path: Optional[Path],
) -> Dict[str, Any]:
    events = _load_events(Path(db_path))
    report_json = _load_report_json(report_json_path)
    event_counts = Counter(row["event"] for row in events)
    entry_evals = _event_payloads(events, "entry_eval_v2")
    gate_summaries = _event_payloads(events, "entry_gate_decision_summary")
    entry_rejects = _event_payloads(events, "entry_reject_v2")
    guard_evals = _event_payloads(events, "immediate_adverse_guard_evaluated")
    shadow_outcomes = _event_payloads(events, "immediate_adverse_shadow_outcome")
    stopped = _latest_payload(events, "runtime_v2_stopped")

    entry_eval_reasons = Counter(str(row.get("reason_code")) for row in entry_evals)
    gate_reasons = Counter(
        str(row.get("local_gate_reason") or row.get("effective_gate_reason"))
        for row in gate_summaries
    )
    entry_reject_reasons = Counter(str(row.get("reason_code")) for row in entry_rejects)
    risk_block_reasons = Counter(
        str(row.get("reason_code"))
        for row in entry_rejects
        if isinstance(row.get("risk_block_fields"), dict)
        and row.get("risk_block_fields")
    )
    top_before_risk = None
    if gate_reasons:
        top_before_risk = gate_reasons.most_common(1)[0][0]
    elif entry_eval_reasons:
        top_before_risk = entry_eval_reasons.most_common(1)[0][0]

    inferred_risk_candidate_seen_count = sum(
        1 for row in entry_evals if bool(row.get("final_allow"))
    )
    risk_candidate_seen_count = int(
        stopped.get("risk_candidate_seen_count") or inferred_risk_candidate_seen_count
    )
    shadow_registered = int(stopped.get("shadow_candidate_registered_count") or 0)
    shadow_terminal = int(
        stopped.get("shadow_terminal_outcome_count") or len(shadow_outcomes)
    )
    skipped_count = int(stopped.get("shadow_registration_skipped_count") or 0)
    skip_distribution = dict(
        stopped.get("shadow_registration_skip_reason_distribution") or {}
    )
    exact_pattern_seen = any(
        str(row.get("symbol")).upper() == "SOLUSDTM"
        and str(row.get("side")).lower() == "buy"
        and str(row.get("strategy")) == "TrendFollowingV2"
        for row in entry_evals
    )
    exact_pattern_selected = any(
        str(row.get("symbol")).upper() == "SOLUSDTM"
        and str(row.get("side")).lower() == "buy"
        and str(row.get("strategy")) == "TrendFollowingV2"
        and bool(row.get("final_allow"))
        for row in entry_evals
    )
    runtime_profile_exists = any(
        row.get("runtime_profile_key") or row.get("runtime_profile_source")
        for row in entry_evals
    )
    if shadow_registered > 0 and shadow_terminal > 0:
        classification = "SHADOW_REACHABILITY_RESTORED"
    elif risk_candidate_seen_count > 0 and skipped_count > 0:
        classification = "SHADOW_REACHABILITY_BLOCKED_AT_REGISTRATION"
    else:
        classification = "SHADOW_REACHABILITY_BLOCKED_UPSTREAM"

    return {
        "source_db": str(db_path),
        "source_json": str(report_json_path) if report_json_path else None,
        "event_counts": dict(sorted(event_counts.items())),
        "funnel": {
            "total_ticks_or_quote_observations": int(event_counts.get("entry_eval_v2", 0)),
            "strategy_candidates_produced": len(entry_evals),
            "selected_strategy_candidates": sum(
                1 for row in entry_evals if bool(row.get("final_allow"))
            ),
            "risk_decisions_reached": int(event_counts.get("risk_decision", 0)),
            "risk_candidate_seen_count": risk_candidate_seen_count,
            "immediate_adverse_guard_evaluated_count": len(guard_evals),
            "shadow_candidate_registered_count": shadow_registered,
            "shadow_terminal_outcome_count": shadow_terminal,
            "shadow_open_at_shutdown_count": int(
                stopped.get("shadow_open_at_shutdown_count") or 0
            ),
            "shadow_expired_no_terminal_move_count": int(
                stopped.get("shadow_expired_no_terminal_move_count") or 0
            ),
            "shadow_insufficient_quotes_count": int(
                stopped.get("shadow_insufficient_quotes_count") or 0
            ),
            "shadow_registration_skipped_count": skipped_count,
            "shadow_registration_skip_reason_distribution": skip_distribution,
        },
        "entry_eval_reason_distribution": dict(sorted(entry_eval_reasons.items())),
        "entry_gate_reason_distribution": dict(sorted(gate_reasons.items())),
        "entry_reject_reason_distribution": dict(sorted(entry_reject_reasons.items())),
        "risk_block_reason_distribution": dict(sorted(risk_block_reasons.items())),
        "top_blocker_before_risk_engine": top_before_risk,
        "top_blocker_inside_risk_engine": (
            risk_block_reasons.most_common(1)[0][0] if risk_block_reasons else None
        ),
        "solusdtm_buy_trendfollowing_seen": exact_pattern_seen,
        "exact_historical_guard_pattern_selected": exact_pattern_selected,
        "runtime_profile_existed_in_entry_eval": runtime_profile_exists,
        "admission_blocked_before_shadow_registration": shadow_registered == 0,
        "shadow_registration_condition_too_narrow": (
            risk_candidate_seen_count > 0 and shadow_registered == 0 and skipped_count > 0
        ),
        "report_summary": {
            "position_open_count": (
                report_json.get("after", {})
                .get("final_close_drain_snapshot", {})
                .get("position_open_count")
            ),
            "position_close_count": (
                report_json.get("after", {})
                .get("final_close_drain_snapshot", {})
                .get("position_close_count")
            ),
        },
        "classification": classification,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    funnel = report["funnel"]
    lines = [
        "# Immediate Adverse Shadow Reachability Gap",
        "",
        f"- classification: `{report['classification']}`",
        f"- source_db: `{report['source_db']}`",
        f"- source_json: `{report['source_json']}`",
        "",
        "## Funnel",
    ]
    for key, value in funnel.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Blockers",
            f"- top_blocker_before_risk_engine: `{report['top_blocker_before_risk_engine']}`",
            f"- top_blocker_inside_risk_engine: `{report['top_blocker_inside_risk_engine']}`",
            f"- entry_eval_reason_distribution: `{report['entry_eval_reason_distribution']}`",
            f"- entry_gate_reason_distribution: `{report['entry_gate_reason_distribution']}`",
            f"- risk_block_reason_distribution: `{report['risk_block_reason_distribution']}`",
            "",
            "## Pattern",
            f"- solusdtm_buy_trendfollowing_seen: `{report['solusdtm_buy_trendfollowing_seen']}`",
            f"- exact_historical_guard_pattern_selected: `{report['exact_historical_guard_pattern_selected']}`",
            f"- runtime_profile_existed_in_entry_eval: `{report['runtime_profile_existed_in_entry_eval']}`",
            f"- shadow_registration_condition_too_narrow: `{report['shadow_registration_condition_too_narrow']}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--json", default=None)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    args = parser.parse_args()
    report = analyze_reachability_gap(
        db_path=Path(args.db),
        report_json_path=Path(args.json) if args.json else None,
    )
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    out_md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"out_json": str(out_json), "out_md": str(out_md), **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
