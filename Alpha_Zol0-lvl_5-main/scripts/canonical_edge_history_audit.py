from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

WORKDIR = Path(__file__).resolve().parents[1]
if str(WORKDIR) not in sys.path:
    sys.path.insert(0, str(WORKDIR))

from scripts.canonical_edge_history_linkage import (
    build_canonical_bucket_key,
    classify_forced_cycle_trace,
    classify_post_promotion_force_cycle_handoff_trace,
)

DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_EVENT_TYPES = {
    "canonical_storage_write_trace",
    "canonical_bucket_pre_materialization",
    "canonical_bucket_post_materialization",
    "canonical_bucket_collapse_compare",
    "canonical_storage_compare_trace",
    "critical_path_exception",
    "close_pnl_decompose_input_trace",
    "close_pnl_decompose_output_trace",
    "canonical_promotion",
    "canonical_promotion_skipped",
    "canonical_gate_read",
    "canonical_explicit_post_promotion_eval_armed",
    "canonical_explicit_post_promotion_eval_invoked",
    "canonical_explicit_post_promotion_eval_completed",
    "canonical_explicit_post_promotion_eval_cleared",
    "canonical_explicit_post_promotion_invoke_trace",
    "canonical_gate_read_branch_selector_enter",
    "canonical_gate_read_branch_selector_inputs",
    "canonical_gate_read_branch_selector_selected_path",
    "canonical_gate_read_branch_selector_skip",
    "canonical_explicit_post_promotion_post_invoke_emit_attempt_enter",
    "canonical_explicit_post_promotion_emit_branch_probe",
    "canonical_explicit_post_promotion_branch_entry_before",
    "canonical_explicit_post_promotion_branch_entry_after",
    "canonical_explicit_post_promotion_gate_read_emit_attempt",
    "canonical_explicit_post_promotion_gate_read_emit_done",
    "canonical_explicit_post_promotion_gate_read_emit_blocked",
    "post_promotion_force_cycle_handoff_enter",
    "post_promotion_force_cycle_handoff_accept",
    "post_promotion_force_cycle_handoff_reject",
    "post_promotion_force_cycle_handoff_reject_reason",
    "post_promotion_force_cycle_handoff_call_start",
    "post_promotion_force_cycle_handoff_call_done",
    "forced_cycle_eval_entry",
    "forced_cycle_eval_pre_router",
    "forced_cycle_eval_post_router",
    "forced_cycle_eval_pre_entry_edge_check",
    "forced_cycle_eval_post_entry_edge_check",
    "forced_cycle_eval_bypass",
    "forced_cycle_eval_pre_selector_return_site",
    "post_promotion_force_cycle_request",
    "forced_cycle_requested",
    "forced_cycle_enter",
    "forced_cycle_started",
    "forced_cycle_completed",
    "forced_cycle_failed",
    "post_promotion_force_cycle_scheduler_tick_enter",
    "post_promotion_force_cycle_scheduler_tick_exit",
    "post_promotion_force_cycle_scheduler_gate_enter",
    "post_promotion_force_cycle_scheduler_gate_result",
    "post_promotion_force_cycle_scheduler_gate_blocked",
    "post_promotion_force_cycle_scheduler_gate_allowed",
    "post_promotion_force_cycle_scheduler_caller_enter",
    "post_promotion_force_cycle_scheduler_caller_exit",
    "post_promotion_force_cycle_request_scan_enter",
    "post_promotion_force_cycle_request_scan_result",
    "post_promotion_force_cycle_request_scan_empty",
    "post_promotion_force_cycle_request_scan_nonempty",
    "post_promotion_force_cycle_request_scan_candidate_seen",
    "post_promotion_force_cycle_request_scan_candidate_reject",
    "post_promotion_force_cycle_request_scan_candidate_reject_reason",
    "post_promotion_force_cycle_request_scan_empty_reason",
    "post_promotion_force_cycle_pre_drain_candidate",
    "post_promotion_force_cycle_pre_drain_reject",
    "post_promotion_force_cycle_pre_drain_reject_reason",
    "post_promotion_force_cycle_pre_drain_enter",
    "post_promotion_force_cycle_pending_check_enter",
    "post_promotion_force_cycle_pending_check_result",
    "post_promotion_force_cycle_pending_visible",
    "post_promotion_force_cycle_pending_not_visible",
    "post_promotion_force_cycle_drain_skipped",
    "canonical_post_promotion_loop_probe_armed",
    "canonical_post_promotion_loop_probe_next_iteration",
    "canonical_post_promotion_entry_pipeline_entered",
    "canonical_post_promotion_entry_edge_check_reached",
    "entry_gate_decision_summary",
    "position_close",
}

REQUIRES_NONEMPTY_DETAILS = {
    "canonical_storage_write_trace",
    "canonical_bucket_pre_materialization",
    "canonical_bucket_post_materialization",
    "canonical_bucket_collapse_compare",
    "canonical_storage_compare_trace",
    "critical_path_exception",
    "close_pnl_decompose_input_trace",
    "close_pnl_decompose_output_trace",
    "canonical_promotion",
    "canonical_promotion_skipped",
    "canonical_gate_read",
    "canonical_explicit_post_promotion_eval_armed",
    "canonical_explicit_post_promotion_eval_invoked",
    "canonical_explicit_post_promotion_eval_completed",
    "canonical_explicit_post_promotion_eval_cleared",
    "canonical_explicit_post_promotion_invoke_trace",
    "canonical_gate_read_branch_selector_enter",
    "canonical_gate_read_branch_selector_inputs",
    "canonical_gate_read_branch_selector_selected_path",
    "canonical_gate_read_branch_selector_skip",
    "canonical_explicit_post_promotion_post_invoke_emit_attempt_enter",
    "canonical_explicit_post_promotion_emit_branch_probe",
    "canonical_explicit_post_promotion_branch_entry_before",
    "canonical_explicit_post_promotion_branch_entry_after",
    "canonical_explicit_post_promotion_gate_read_emit_attempt",
    "canonical_explicit_post_promotion_gate_read_emit_done",
    "canonical_explicit_post_promotion_gate_read_emit_blocked",
    "post_promotion_force_cycle_handoff_enter",
    "post_promotion_force_cycle_handoff_accept",
    "post_promotion_force_cycle_handoff_reject",
    "post_promotion_force_cycle_handoff_reject_reason",
    "post_promotion_force_cycle_handoff_call_start",
    "post_promotion_force_cycle_handoff_call_done",
    "forced_cycle_eval_entry",
    "forced_cycle_eval_pre_router",
    "forced_cycle_eval_post_router",
    "forced_cycle_eval_pre_entry_edge_check",
    "forced_cycle_eval_post_entry_edge_check",
    "forced_cycle_eval_bypass",
    "forced_cycle_eval_pre_selector_return_site",
    "post_promotion_force_cycle_request",
    "forced_cycle_requested",
    "forced_cycle_enter",
    "forced_cycle_started",
    "forced_cycle_completed",
    "forced_cycle_failed",
    "post_promotion_force_cycle_scheduler_tick_enter",
    "post_promotion_force_cycle_scheduler_tick_exit",
    "post_promotion_force_cycle_scheduler_gate_enter",
    "post_promotion_force_cycle_scheduler_gate_result",
    "post_promotion_force_cycle_scheduler_gate_blocked",
    "post_promotion_force_cycle_scheduler_gate_allowed",
    "post_promotion_force_cycle_scheduler_caller_enter",
    "post_promotion_force_cycle_scheduler_caller_exit",
    "post_promotion_force_cycle_request_scan_enter",
    "post_promotion_force_cycle_request_scan_result",
    "post_promotion_force_cycle_request_scan_empty",
    "post_promotion_force_cycle_request_scan_nonempty",
    "post_promotion_force_cycle_pre_drain_candidate",
    "post_promotion_force_cycle_pre_drain_reject",
    "post_promotion_force_cycle_pre_drain_reject_reason",
    "post_promotion_force_cycle_pre_drain_enter",
    "post_promotion_force_cycle_pending_check_enter",
    "post_promotion_force_cycle_pending_check_result",
    "post_promotion_force_cycle_pending_visible",
    "post_promotion_force_cycle_pending_not_visible",
    "post_promotion_force_cycle_drain_skipped",
    "canonical_post_promotion_loop_probe_armed",
    "canonical_post_promotion_loop_probe_next_iteration",
    "canonical_post_promotion_entry_pipeline_entered",
    "canonical_post_promotion_entry_edge_check_reached",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_int(v, d=0):
    try:
        return d if v is None or isinstance(v, bool) else int(v)
    except Exception:
        return d


def _safe_float(v, d=0.0):
    try:
        return d if v is None or isinstance(v, bool) else float(v)
    except Exception:
        return d


def _parse_dt(v):
    if v in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def _dt_delta_ms(later, earlier):
    if later is None or earlier is None:
        return None
    try:
        later_ts = _parse_dt(later) if not isinstance(later, datetime) else later
        earlier_ts = _parse_dt(earlier) if not isinstance(earlier, datetime) else earlier
        if later_ts is None or earlier_ts is None:
            return None
        if later_ts.tzinfo is None:
            later_ts = later_ts.replace(tzinfo=timezone.utc)
        if earlier_ts.tzinfo is None:
            earlier_ts = earlier_ts.replace(tzinfo=timezone.utc)
        return (later_ts - earlier_ts).total_seconds() * 1000.0
    except Exception:
        return None


def _new_data_quality() -> dict:
    return {
        "rows_total": 0,
        "rows_valid": 0,
        "rows_skipped": 0,
        "skip_reasons": {},
    }


def _dq_skip(data_quality: dict, reason: str) -> None:
    data_quality["rows_skipped"] = int(data_quality.get("rows_skipped", 0)) + 1
    skip_reasons = data_quality.setdefault("skip_reasons", {})
    skip_reasons[reason] = int(skip_reasons.get(reason, 0)) + 1


def _load_logs(db_path: Path) -> tuple[list[dict], dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select id, timestamp, event, details from logs order by id asc"
        ).fetchall()
    finally:
        conn.close()
    data_quality = _new_data_quality()
    out = []
    for row in rows:
        data_quality["rows_total"] = int(data_quality.get("rows_total", 0)) + 1
        row_id = row["id"]
        row_ts = row["timestamp"]
        raw_event = row["event"]
        if row_id is None or row_ts in (None, ""):
            _dq_skip(data_quality, "partial_corpus_missing_required_columns")
            continue
        event = str(raw_event or "").strip()
        if not event:
            _dq_skip(data_quality, "invalid_event_type_empty")
            continue
        if event not in AUDIT_EVENT_TYPES:
            _dq_skip(data_quality, "invalid_event_type")
            continue
        raw_details = row["details"]
        if raw_details in (None, ""):
            payload = {}
        else:
            try:
                payload = json.loads(raw_details)
            except Exception:
                _dq_skip(data_quality, "malformed_json")
                continue
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            _dq_skip(data_quality, "details_not_object")
            continue
        if event in REQUIRES_NONEMPTY_DETAILS and not payload:
            _dq_skip(data_quality, "partial_corpus_empty_details")
            continue
        try:
            out.append(
                {
                    "id": int(row_id),
                    "timestamp": str(row_ts),
                    "event": event,
                    "details": payload,
                }
            )
            data_quality["rows_valid"] = int(data_quality.get("rows_valid", 0)) + 1
        except Exception:
            _dq_skip(data_quality, "partial_corpus_invalid_row_shape")
    data_quality["skip_reasons"] = dict(sorted((data_quality.get("skip_reasons") or {}).items()))
    return out, data_quality


def _select_run(result_path: str | None, results_dir: Path) -> dict:
    if result_path:
        path = Path(result_path)
        if not path.is_absolute():
            path = (WORKDIR / path).resolve()
        payload = _load_json(path)
        before = payload.get("before") or {}
        db_path = Path(str(before.get("db_path") or "")).expanduser()
        if not db_path.is_absolute():
            db_path = (WORKDIR / db_path).resolve()
        return {"run_id": str(payload.get("run_id") or path.stem), "results_path": str(path), "db_path": db_path, "duration_sec_actual": _safe_float(before.get("duration_sec_actual")), "before": before}
    candidates = []
    for path in sorted(results_dir.glob("controlled_kpi_*.json")):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        before = payload.get("before") or {}
        if str(before.get("variant") or "") != "before":
            continue
        db_path = Path(str(before.get("db_path") or "")).expanduser()
        if not db_path.is_absolute():
            db_path = (WORKDIR / db_path).resolve()
        if not db_path.exists():
            continue
        candidates.append({"run_id": str(payload.get("run_id") or path.stem), "results_path": str(path), "db_path": db_path, "duration_sec_actual": _safe_float(before.get("duration_sec_actual")), "before": before})
    if not candidates:
        raise FileNotFoundError("No controlled_kpi before runs found")
    candidates.sort(key=lambda r: (r["duration_sec_actual"], r["results_path"]))
    return candidates[-1]


def _row_payload_for_canonical(row: dict) -> dict:
    event = row["event"]
    details = row["details"] or {}
    if event == "entry_gate_decision_summary":
        payload = dict(details)
        if "strategy" not in payload and isinstance(payload.get("entry_edge_over_fee"), dict):
            payload["strategy"] = payload["entry_edge_over_fee"].get("strategy")
        return payload
    if event == "position_close":
        pos = details.get("position") or {}
        return {"symbol": details.get("symbol") or pos.get("symbol"), "side": pos.get("side") or details.get("side"), "position": pos, "strategy": pos.get("entry_main_strategy") or pos.get("strategy") or details.get("main_strategy")}
    return details


def _canon_from_row(row: dict) -> dict | None:
    event = row["event"]
    details = row["details"] or {}
    if event in {
        "canonical_storage_write_trace",
        "canonical_bucket_pre_materialization",
        "canonical_bucket_post_materialization",
        "canonical_bucket_collapse_compare",
    }:
        payload = dict(details)
        canonical_key = payload.get("canonical_key")
        canonical = (
            build_canonical_bucket_key(
                {
                    "symbol": payload.get("symbol"),
                    "strategy": payload.get("strategy"),
                    "side": payload.get("side"),
                }
            )
            if canonical_key
            else build_canonical_bucket_key({})
        )
        payload.setdefault("runtime_seq", _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("row_ts", payload.get("timestamp") or row["timestamp"])
        return {"kind": event, "payload": payload, "canonical": canonical}
    if event == "canonical_storage_compare_trace":
        payload = dict(details)
        canonical_key = payload.get("canonical_key")
        canonical = (
            build_canonical_bucket_key(
                {
                    "symbol": payload.get("symbol"),
                    "strategy": payload.get("strategy"),
                    "side": payload.get("side"),
                }
            )
            if canonical_key
            else build_canonical_bucket_key({})
        )
        payload.setdefault("runtime_seq", _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("row_ts", payload.get("timestamp") or row["timestamp"])
        payload.setdefault("correlation_id", payload.get("correlation_id"))
        return {"kind": "canonical_storage_compare_trace", "payload": payload, "canonical": canonical}
    if event == "critical_path_exception":
        payload = dict(details)
        payload.setdefault("runtime_seq", _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("row_ts", payload.get("created_at") or row["timestamp"])
        payload.setdefault("correlation_id", payload.get("correlation_id"))
        canonical = build_canonical_bucket_key(
            {
                "symbol": payload.get("symbol"),
                "strategy": payload.get("strategy"),
                "side": payload.get("side"),
            }
        )
        return {"kind": "critical_path_exception", "payload": payload, "canonical": canonical}
    if event in {"close_pnl_decompose_input_trace", "close_pnl_decompose_output_trace"}:
        payload = dict(details)
        payload.setdefault("runtime_seq", _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("run_ts", payload.get("run_ts") or row["timestamp"])
        canonical = build_canonical_bucket_key(payload)
        return {"kind": "close_trace", "payload": payload, "canonical": canonical}
    if event == "canonical_promotion":
        canonical = details.get("canonical_bucket") or build_canonical_bucket_key(_row_payload_for_canonical(row))
        payload = dict(details)
        payload.setdefault("canonical_key", canonical.get("canonical_bucket_key"))
        payload.setdefault("bucket_identity_status", canonical.get("bucket_identity_status"))
        payload.setdefault("bucket_identity_reason", canonical.get("bucket_identity_reason"))
        payload.setdefault("symbol", canonical.get("symbol"))
        payload.setdefault("strategy", canonical.get("strategy_identity"))
        payload.setdefault("side", canonical.get("side"))
        payload.setdefault("raw_symbol", canonical.get("raw_symbol"))
        payload.setdefault("raw_strategy", canonical.get("raw_strategy"))
        payload.setdefault("raw_side", canonical.get("raw_side"))
        payload.setdefault("normalized_symbol", canonical.get("normalized_symbol"))
        payload.setdefault("normalized_strategy", canonical.get("normalized_strategy"))
        payload.setdefault("normalized_side", canonical.get("normalized_side"))
        payload.setdefault("runtime_seq", _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("run_ts", payload.get("run_ts") or row["timestamp"])
        payload.setdefault("correlation_id", payload.get("correlation_id"))
        payload.setdefault("read_source_name", "canonical_shadow_storage")
        payload.setdefault("canonical_shadow_source_name", "canonical_shadow_storage")
        payload.setdefault("canonical_shadow_trade_count", _safe_int(payload.get("canonical_shadow_trade_count")))
        payload.setdefault("canonical_shadow_history_ready", bool(payload.get("canonical_shadow_history_ready")))
        payload.setdefault("canonical_shadow_last_update_ts", payload.get("canonical_shadow_last_update_ts"))
        return {"kind": "promotion", "payload": payload, "canonical": canonical}
    if event == "canonical_promotion_skipped":
        payload = dict(details)
        return {"kind": "promotion_skipped", "payload": payload, "canonical": build_canonical_bucket_key(_row_payload_for_canonical(row))}
    if event == "canonical_gate_read":
        canonical = details.get("canonical_bucket") or build_canonical_bucket_key(_row_payload_for_canonical(row))
        payload = dict(details)
        payload.setdefault("canonical_key", canonical.get("canonical_bucket_key"))
        payload.setdefault("bucket_identity_status", canonical.get("bucket_identity_status"))
        payload.setdefault("bucket_identity_reason", canonical.get("bucket_identity_reason"))
        payload.setdefault("symbol", canonical.get("symbol"))
        payload.setdefault("strategy", canonical.get("strategy_identity"))
        payload.setdefault("side", canonical.get("side"))
        payload.setdefault("raw_symbol", canonical.get("raw_symbol"))
        payload.setdefault("raw_strategy", canonical.get("raw_strategy"))
        payload.setdefault("raw_side", canonical.get("raw_side"))
        payload.setdefault("normalized_symbol", canonical.get("normalized_symbol"))
        payload.setdefault("normalized_strategy", canonical.get("normalized_strategy"))
        payload.setdefault("normalized_side", canonical.get("normalized_side"))
        payload.setdefault("runtime_seq", _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("row_ts", payload.get("row_ts") or row["timestamp"])
        payload.setdefault("correlation_id", payload.get("correlation_id"))
        payload.setdefault("read_source_name", payload.get("read_source_name") or "canonical_shadow_storage")
        payload.setdefault("canonical_shadow_source_name", payload.get("canonical_shadow_source_name") or "canonical_shadow_storage")
        payload.setdefault("canonical_shadow_trade_count", _safe_int(payload.get("canonical_shadow_trade_count")))
        payload.setdefault("canonical_shadow_history_ready", bool(payload.get("canonical_shadow_history_ready")))
        payload.setdefault("canonical_shadow_last_update_ts", payload.get("canonical_shadow_last_update_ts"))
        payload.setdefault("read_context", payload.get("read_context"))
        payload.setdefault("timing_replay_index", payload.get("timing_replay_index"))
        payload.setdefault("timing_replay_target_reads", payload.get("timing_replay_target_reads"))
        payload.setdefault("gate_read_source_function", payload.get("gate_read_source_function"))
        payload.setdefault("decision_source_name", payload.get("decision_source_name"))
        payload.setdefault("decision_trade_count", _safe_int(payload.get("decision_trade_count"), _safe_int(payload.get("trade_count"))))
        payload.setdefault("decision_history_ready", bool(payload.get("decision_history_ready", payload.get("history_ready"))))
        payload.setdefault("forced_same_bucket_next_eval", bool(payload.get("forced_same_bucket_next_eval")))
        payload.setdefault("override_type", payload.get("override_type"))
        payload.setdefault("override_consumed", bool(payload.get("override_consumed")))
        payload.setdefault("promoted_bucket_key", payload.get("promoted_bucket_key"))
        payload.setdefault("post_promotion_eval_arm_consumed", bool(payload.get("post_promotion_eval_arm_consumed")))
        payload.setdefault("evaluated_path_enter_after_promotion", bool(payload.get("evaluated_path_enter_after_promotion")))
        payload.setdefault("evaluated_path_skip_reason", payload.get("evaluated_path_skip_reason"))
        payload.setdefault("evaluated_path_exit_reason", payload.get("evaluated_path_exit_reason"))
        payload.setdefault("canonical_gate_read_branch_selector_enter", bool(payload.get("canonical_gate_read_branch_selector_enter")))
        payload.setdefault("canonical_gate_read_branch_selector_inputs", bool(payload.get("canonical_gate_read_branch_selector_inputs")))
        payload.setdefault("canonical_gate_read_branch_selector_selected_path", payload.get("canonical_gate_read_branch_selector_selected_path"))
        payload.setdefault("canonical_gate_read_branch_selector_skip", bool(payload.get("canonical_gate_read_branch_selector_skip")))
        payload.setdefault("canonical_gate_read_branch_selector_skip_reason", payload.get("canonical_gate_read_branch_selector_skip_reason"))
        payload.setdefault("canonical_gate_read_emit_candidate", bool(payload.get("canonical_gate_read_emit_candidate")))
        payload.setdefault("canonical_gate_read_emit_guard_considered", bool(payload.get("canonical_gate_read_emit_guard_considered")))
        payload.setdefault("canonical_gate_read_emit_guard_blocked", bool(payload.get("canonical_gate_read_emit_guard_blocked")))
        payload.setdefault("canonical_gate_read_emit_guard_reason", payload.get("canonical_gate_read_emit_guard_reason"))
        payload.setdefault("canonical_gate_read_emit_payload_built", bool(payload.get("canonical_gate_read_emit_payload_built")))
        payload.setdefault("canonical_gate_read_emit_attempt", bool(payload.get("canonical_gate_read_emit_attempt")))
        payload.setdefault("canonical_gate_read_emit_enter", bool(payload.get("canonical_gate_read_emit_enter")))
        payload.setdefault("canonical_gate_read_emit_done", bool(payload.get("canonical_gate_read_emit_done")))
        payload.setdefault("post_promotion_force_cycle_handoff_enter", bool(payload.get("post_promotion_force_cycle_handoff_enter")))
        payload.setdefault("post_promotion_force_cycle_handoff_accept", bool(payload.get("post_promotion_force_cycle_handoff_accept")))
        payload.setdefault("post_promotion_force_cycle_handoff_reject", bool(payload.get("post_promotion_force_cycle_handoff_reject")))
        payload.setdefault("post_promotion_force_cycle_handoff_reject_reason", payload.get("post_promotion_force_cycle_handoff_reject_reason"))
        payload.setdefault("post_promotion_force_cycle_handoff_call_start", bool(payload.get("post_promotion_force_cycle_handoff_call_start")))
        payload.setdefault("post_promotion_force_cycle_handoff_call_done", bool(payload.get("post_promotion_force_cycle_handoff_call_done")))
        payload.setdefault("forced_cycle_runtime_seq", _safe_int(payload.get("forced_cycle_runtime_seq"), None) if payload.get("forced_cycle_runtime_seq") is not None else None)
        payload.setdefault("evaluation_phase", payload.get("evaluation_phase"))
        payload.setdefault("is_explicit_post_promotion_eval", bool(payload.get("is_explicit_post_promotion_eval")))
        payload.setdefault("is_forced_post_promotion_cycle", bool(payload.get("is_forced_post_promotion_cycle")))
        payload.setdefault("skip_reason", payload.get("skip_reason"))
        payload.setdefault("promotion_runtime_seq", _safe_int(payload.get("promotion_runtime_seq"), None) if payload.get("promotion_runtime_seq") is not None else None)
        payload.setdefault("reeval_runtime_seq", _safe_int(payload.get("reeval_runtime_seq"), None) if payload.get("reeval_runtime_seq") is not None else None)
        payload.setdefault("evaluated_path_runtime_seq", _safe_int(payload.get("evaluated_path_runtime_seq"), None) if payload.get("evaluated_path_runtime_seq") is not None else None)
        return {"kind": "gate", "payload": payload, "canonical": canonical}
    if event in {
        "canonical_explicit_post_promotion_eval_armed",
        "canonical_explicit_post_promotion_eval_invoked",
        "canonical_explicit_post_promotion_eval_completed",
        "canonical_explicit_post_promotion_eval_cleared",
        "canonical_explicit_post_promotion_invoke_trace",
        "handoff_parent_enqueue_enter",
        "handoff_parent_enqueue_done",
        "handoff_parent_signal_sent",
        "handoff_child_mailbox_observed",
        "handoff_child_mailbox_dequeue_enter",
        "post_promotion_force_cycle_handoff_enter",
        "post_promotion_force_cycle_handoff_accept",
        "post_promotion_force_cycle_handoff_reject",
        "post_promotion_force_cycle_handoff_reject_reason",
        "post_promotion_force_cycle_handoff_call_start",
        "post_promotion_force_cycle_handoff_call_done",
        "handoff_parent_enqueue_enter",
        "handoff_parent_enqueue_done",
        "handoff_parent_signal_sent",
        "handoff_child_mailbox_observed",
        "handoff_child_mailbox_dequeue_enter",
        "canonical_gate_read_branch_selector_enter",
        "canonical_gate_read_branch_selector_inputs",
        "canonical_gate_read_branch_selector_selected_path",
        "canonical_gate_read_branch_selector_skip",
        "canonical_gate_read_emit_candidate",
        "canonical_gate_read_emit_guard_considered",
        "canonical_gate_read_emit_guard_blocked",
        "canonical_gate_read_emit_payload_built",
        "canonical_gate_read_emit_attempt",
        "canonical_gate_read_emit_done",
        "canonical_explicit_post_promotion_post_invoke_emit_attempt_enter",
        "canonical_explicit_post_promotion_emit_branch_probe",
        "canonical_explicit_post_promotion_branch_entry_before",
        "canonical_explicit_post_promotion_branch_entry_after",
        "canonical_explicit_post_promotion_gate_read_emit_attempt",
        "canonical_explicit_post_promotion_gate_read_emit_done",
        "canonical_explicit_post_promotion_gate_read_emit_blocked",
    }:
        canonical = details.get("canonical_bucket") or build_canonical_bucket_key(_row_payload_for_canonical(row))
        payload = dict(details)
        payload.setdefault("canonical_key", canonical.get("canonical_bucket_key"))
        payload.setdefault("bucket_identity_status", canonical.get("bucket_identity_status"))
        payload.setdefault("bucket_identity_reason", canonical.get("bucket_identity_reason"))
        payload.setdefault("symbol", canonical.get("symbol"))
        payload.setdefault("strategy", canonical.get("strategy_identity"))
        payload.setdefault("side", canonical.get("side"))
        payload.setdefault("runtime_seq", _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("row_ts", payload.get("row_ts") or row["timestamp"])
        payload.setdefault("correlation_id", payload.get("correlation_id"))
        payload.setdefault("promoted_bucket_key", payload.get("promoted_bucket_key"))
        payload.setdefault("armed_at_seq", payload.get("armed_at_seq"))
        payload.setdefault("invoked_at_seq", payload.get("invoked_at_seq"))
        payload.setdefault("consumed_at_seq", payload.get("consumed_at_seq"))
        payload.setdefault("cleared_at_seq", payload.get("cleared_at_seq"))
        payload.setdefault("reason", payload.get("reason"))
        payload.setdefault("clear_reason", payload.get("clear_reason"))
        payload.setdefault("post_invoke_emit_path_enter", bool(payload.get("post_invoke_emit_path_enter")))
        payload.setdefault("post_invoke_emit_guard_considered", bool(payload.get("post_invoke_emit_guard_considered")))
        payload.setdefault("post_invoke_emit_guard_allowed", bool(payload.get("post_invoke_emit_guard_allowed")))
        payload.setdefault("post_invoke_emit_guard_reason", payload.get("post_invoke_emit_guard_reason"))
        payload.setdefault("post_invoke_emit_early_return", bool(payload.get("post_invoke_emit_early_return")))
        payload.setdefault("post_invoke_emit_early_return_reason", payload.get("post_invoke_emit_early_return_reason"))
        payload.setdefault("post_invoke_emit_attempt_reached", bool(payload.get("post_invoke_emit_attempt_reached")))
        payload.setdefault("post_invoke_emit_micro_stage", payload.get("post_invoke_emit_micro_stage"))
        payload.setdefault("post_invoke_emit_hidden_branch_taken", bool(payload.get("post_invoke_emit_hidden_branch_taken")))
        payload.setdefault("post_invoke_emit_hidden_branch_reason", payload.get("post_invoke_emit_hidden_branch_reason"))
        payload.setdefault("post_invoke_emit_local_return", bool(payload.get("post_invoke_emit_local_return")))
        payload.setdefault("post_invoke_emit_local_return_reason", payload.get("post_invoke_emit_local_return_reason"))
        payload.setdefault("post_invoke_emit_exception_class", payload.get("post_invoke_emit_exception_class"))
        payload.setdefault("post_invoke_emit_exception_message", payload.get("post_invoke_emit_exception_message"))
        payload.setdefault("post_invoke_emit_attempt_call_enter", bool(payload.get("post_invoke_emit_attempt_call_enter")))
        payload.setdefault("post_promotion_eval_arm_consumed", bool(payload.get("post_promotion_eval_arm_consumed")))
        payload.setdefault("evaluated_path_enter_after_promotion", bool(payload.get("evaluated_path_enter_after_promotion")))
        payload.setdefault("evaluated_path_skip_reason", payload.get("evaluated_path_skip_reason"))
        payload.setdefault("evaluated_path_exit_reason", payload.get("evaluated_path_exit_reason"))
        payload.setdefault("transfer_site_id", payload.get("transfer_site_id"))
        payload.setdefault("mailbox_stage", payload.get("mailbox_stage"))
        payload.setdefault("handoff_transport_state", payload.get("handoff_transport_state"))
        payload.setdefault("canonical_gate_read_branch_selector_enter", bool(payload.get("canonical_gate_read_branch_selector_enter")))
        payload.setdefault("canonical_gate_read_branch_selector_inputs", bool(payload.get("canonical_gate_read_branch_selector_inputs")))
        payload.setdefault("canonical_gate_read_branch_selector_selected_path", payload.get("canonical_gate_read_branch_selector_selected_path"))
        payload.setdefault("canonical_gate_read_branch_selector_skip", bool(payload.get("canonical_gate_read_branch_selector_skip")))
        payload.setdefault("canonical_gate_read_branch_selector_skip_reason", payload.get("canonical_gate_read_branch_selector_skip_reason"))
        payload.setdefault("canonical_gate_read_emit_candidate", bool(payload.get("canonical_gate_read_emit_candidate")))
        payload.setdefault("canonical_gate_read_emit_guard_considered", bool(payload.get("canonical_gate_read_emit_guard_considered")))
        payload.setdefault("canonical_gate_read_emit_guard_blocked", bool(payload.get("canonical_gate_read_emit_guard_blocked")))
        payload.setdefault("canonical_gate_read_emit_guard_reason", payload.get("canonical_gate_read_emit_guard_reason"))
        payload.setdefault("canonical_gate_read_emit_payload_built", bool(payload.get("canonical_gate_read_emit_payload_built")))
        payload.setdefault("canonical_gate_read_emit_attempt", bool(payload.get("canonical_gate_read_emit_attempt")))
        payload.setdefault("canonical_gate_read_emit_enter", bool(payload.get("canonical_gate_read_emit_enter")))
        payload.setdefault("canonical_gate_read_emit_done", bool(payload.get("canonical_gate_read_emit_done")))
        payload.setdefault("evaluation_phase", payload.get("evaluation_phase"))
        payload.setdefault("is_explicit_post_promotion_eval", bool(payload.get("is_explicit_post_promotion_eval")))
        payload.setdefault("is_forced_post_promotion_cycle", bool(payload.get("is_forced_post_promotion_cycle")))
        payload.setdefault("skip_reason", payload.get("skip_reason"))
        payload.setdefault("promotion_runtime_seq", _safe_int(payload.get("promotion_runtime_seq"), None) if payload.get("promotion_runtime_seq") is not None else None)
        payload.setdefault("reeval_runtime_seq", _safe_int(payload.get("reeval_runtime_seq"), None) if payload.get("reeval_runtime_seq") is not None else None)
        payload.setdefault("evaluated_path_runtime_seq", _safe_int(payload.get("evaluated_path_runtime_seq"), None) if payload.get("evaluated_path_runtime_seq") is not None else None)
        payload.setdefault("canonical_gate_read_runtime_seq", _safe_int(payload.get("canonical_gate_read_runtime_seq"), None) if payload.get("canonical_gate_read_runtime_seq") is not None else _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("post_promotion_eval_arm_consumed", bool(payload.get("post_promotion_eval_arm_consumed")))
        payload.setdefault("evaluated_path_enter_after_promotion", bool(payload.get("evaluated_path_enter_after_promotion")))
        payload.setdefault("evaluated_path_skip_reason", payload.get("evaluated_path_skip_reason"))
        payload.setdefault("evaluated_path_exit_reason", payload.get("evaluated_path_exit_reason"))
        payload.setdefault("canonical_gate_read_emit_candidate", bool(payload.get("canonical_gate_read_emit_candidate")))
        payload.setdefault("canonical_gate_read_emit_guard_considered", bool(payload.get("canonical_gate_read_emit_guard_considered")))
        payload.setdefault("canonical_gate_read_emit_guard_blocked", bool(payload.get("canonical_gate_read_emit_guard_blocked")))
        payload.setdefault("canonical_gate_read_emit_guard_reason", payload.get("canonical_gate_read_emit_guard_reason"))
        payload.setdefault("canonical_gate_read_emit_payload_built", bool(payload.get("canonical_gate_read_emit_payload_built")))
        payload.setdefault("canonical_gate_read_emit_attempt", bool(payload.get("canonical_gate_read_emit_attempt")))
        payload.setdefault("canonical_gate_read_emit_enter", bool(payload.get("canonical_gate_read_emit_enter")))
        payload.setdefault("canonical_gate_read_emit_done", bool(payload.get("canonical_gate_read_emit_done")))
        payload.setdefault("evaluation_phase", payload.get("evaluation_phase"))
        payload.setdefault("is_explicit_post_promotion_eval", bool(payload.get("is_explicit_post_promotion_eval")))
        payload.setdefault("skip_reason", payload.get("skip_reason"))
        payload.setdefault("promotion_runtime_seq", _safe_int(payload.get("promotion_runtime_seq"), None) if payload.get("promotion_runtime_seq") is not None else None)
        payload.setdefault("reeval_runtime_seq", _safe_int(payload.get("reeval_runtime_seq"), None) if payload.get("reeval_runtime_seq") is not None else None)
        payload.setdefault("evaluated_path_runtime_seq", _safe_int(payload.get("evaluated_path_runtime_seq"), None) if payload.get("evaluated_path_runtime_seq") is not None else None)
        payload.setdefault("canonical_gate_read_runtime_seq", _safe_int(payload.get("canonical_gate_read_runtime_seq"), None) if payload.get("canonical_gate_read_runtime_seq") is not None else _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("post_promotion_eval_arm_consumed", bool(payload.get("post_promotion_eval_arm_consumed")))
        payload.setdefault("evaluated_path_enter_after_promotion", bool(payload.get("evaluated_path_enter_after_promotion")))
        payload.setdefault("evaluated_path_skip_reason", payload.get("evaluated_path_skip_reason"))
        payload.setdefault("evaluated_path_exit_reason", payload.get("evaluated_path_exit_reason"))
        return {"kind": "explicit_post_promotion_eval_trace", "payload": payload, "canonical": canonical}
    if event in {
        "post_promotion_force_cycle_request",
        "forced_cycle_requested",
        "post_promotion_force_cycle_scheduler_caller_enter",
        "post_promotion_force_cycle_scheduler_caller_exit",
        "post_promotion_force_cycle_scheduler_gate_enter",
        "post_promotion_force_cycle_scheduler_gate_result",
        "post_promotion_force_cycle_scheduler_gate_blocked",
        "post_promotion_force_cycle_scheduler_gate_allowed",
        "post_promotion_force_cycle_request_scan_enter",
        "post_promotion_force_cycle_request_scan_result",
        "post_promotion_force_cycle_request_scan_empty",
        "post_promotion_force_cycle_request_scan_nonempty",
        "post_promotion_force_cycle_request_scan_candidate_seen",
        "post_promotion_force_cycle_request_scan_candidate_reject",
        "post_promotion_force_cycle_request_scan_candidate_reject_reason",
        "post_promotion_force_cycle_request_scan_empty_reason",
        "post_promotion_force_cycle_pre_drain_enter",
        "post_promotion_force_cycle_pre_drain_skip",
        "post_promotion_force_cycle_pre_drain_skip_reason",
        "post_promotion_force_cycle_pre_drain_return",
        "post_promotion_force_cycle_pre_drain_exception",
        "post_promotion_force_cycle_pending_check_enter",
        "post_promotion_force_cycle_pending_check_result",
        "post_promotion_force_cycle_pending_visible",
        "post_promotion_force_cycle_pending_not_visible",
        "post_promotion_force_cycle_drain_skipped",
        "post_promotion_force_cycle_drain_enter",
        "post_promotion_force_cycle_drain_exit",
        "handoff_parent_enqueue_enter",
        "handoff_parent_enqueue_done",
        "handoff_parent_signal_sent",
        "handoff_child_mailbox_observed",
        "handoff_child_mailbox_dequeue_enter",
        "forced_cycle_eval_entry",
        "forced_cycle_eval_pre_router",
        "forced_cycle_eval_post_router",
        "forced_cycle_eval_pre_entry_edge_check",
        "forced_cycle_eval_post_entry_edge_check",
        "forced_cycle_eval_bypass",
        "forced_cycle_enter",
        "forced_cycle_started",
        "forced_cycle_completed",
        "forced_cycle_failed",
    }:
        canonical = details.get("canonical_bucket") or build_canonical_bucket_key(_row_payload_for_canonical(row))
        payload = dict(details)
        payload.setdefault("canonical_key", canonical.get("canonical_bucket_key"))
        payload.setdefault("bucket_identity_status", canonical.get("bucket_identity_status"))
        payload.setdefault("bucket_identity_reason", canonical.get("bucket_identity_reason"))
        payload.setdefault("symbol", canonical.get("symbol"))
        payload.setdefault("strategy", canonical.get("strategy_identity"))
        payload.setdefault("side", canonical.get("side"))
        payload.setdefault("runtime_seq", _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("row_ts", payload.get("row_ts") or row["timestamp"])
        payload.setdefault("correlation_id", payload.get("correlation_id"))
        payload.setdefault("promotion_runtime_seq", _safe_int(payload.get("promotion_runtime_seq"), None) if payload.get("promotion_runtime_seq") is not None else None)
        payload.setdefault("forced_cycle_request_runtime_seq", _safe_int(payload.get("forced_cycle_request_runtime_seq"), None) if payload.get("forced_cycle_request_runtime_seq") is not None else None)
        payload.setdefault("forced_cycle_runtime_seq", _safe_int(payload.get("forced_cycle_runtime_seq"), None) if payload.get("forced_cycle_runtime_seq") is not None else None)
        payload.setdefault("forced_cycle_exit_reason", payload.get("forced_cycle_exit_reason"))
        payload.setdefault("request_id", _safe_int(payload.get("request_id"), None) if payload.get("request_id") is not None else None)
        payload.setdefault("visibility_reason", payload.get("visibility_reason"))
        payload.setdefault("request_count_seen", _safe_int(payload.get("request_count_seen"), None) if payload.get("request_count_seen") is not None else None)
        payload.setdefault("scan_reason", payload.get("scan_reason"))
        payload.setdefault("tick_reason", payload.get("tick_reason"))
        payload.setdefault("forced_cycle_scheduler_tick_enter", bool(payload.get("forced_cycle_scheduler_tick_enter")))
        payload.setdefault("forced_cycle_scheduler_tick_exit", bool(payload.get("forced_cycle_scheduler_tick_exit")))
        payload.setdefault("forced_cycle_scheduler_gate_enter", bool(payload.get("forced_cycle_scheduler_gate_enter")))
        payload.setdefault("forced_cycle_scheduler_gate_result", payload.get("forced_cycle_scheduler_gate_result"))
        payload.setdefault("forced_cycle_scheduler_gate_blocked", bool(payload.get("forced_cycle_scheduler_gate_blocked")))
        payload.setdefault("forced_cycle_scheduler_gate_allowed", bool(payload.get("forced_cycle_scheduler_gate_allowed")))
        payload.setdefault("forced_cycle_scheduler_caller_enter", bool(payload.get("forced_cycle_scheduler_caller_enter")))
        payload.setdefault("forced_cycle_scheduler_caller_exit", bool(payload.get("forced_cycle_scheduler_caller_exit")))
        payload.setdefault("forced_cycle_request_scan_enter", bool(payload.get("forced_cycle_request_scan_enter")))
        payload.setdefault("forced_cycle_request_scan_result", payload.get("forced_cycle_request_scan_result"))
        payload.setdefault("forced_cycle_request_scan_empty", bool(payload.get("forced_cycle_request_scan_empty")))
        payload.setdefault("forced_cycle_request_scan_nonempty", bool(payload.get("forced_cycle_request_scan_nonempty")))
        payload.setdefault("forced_cycle_request_scan_candidate_seen", bool(payload.get("forced_cycle_request_scan_candidate_seen")))
        payload.setdefault("forced_cycle_request_scan_candidate_reject", bool(payload.get("forced_cycle_request_scan_candidate_reject")))
        payload.setdefault("forced_cycle_request_scan_candidate_reject_reason", payload.get("forced_cycle_request_scan_candidate_reject_reason"))
        payload.setdefault("forced_cycle_request_scan_empty_reason", payload.get("forced_cycle_request_scan_empty_reason"))
        payload.setdefault("forced_cycle_pre_drain_candidate", bool(payload.get("forced_cycle_pre_drain_candidate")))
        payload.setdefault("forced_cycle_pre_drain_reject", bool(payload.get("forced_cycle_pre_drain_reject")))
        payload.setdefault("forced_cycle_pre_drain_reject_reason", payload.get("forced_cycle_pre_drain_reject_reason"))
        payload.setdefault("forced_cycle_pre_drain_enter", bool(payload.get("forced_cycle_pre_drain_enter")))
        payload.setdefault("forced_cycle_pre_drain_skip", bool(payload.get("forced_cycle_pre_drain_skip")))
        payload.setdefault("forced_cycle_pre_drain_skip_reason", payload.get("forced_cycle_pre_drain_skip_reason"))
        payload.setdefault("forced_cycle_pre_drain_return", bool(payload.get("forced_cycle_pre_drain_return")))
        payload.setdefault("forced_cycle_pre_drain_return_reason", payload.get("forced_cycle_pre_drain_return_reason"))
        payload.setdefault("forced_cycle_pre_drain_exception_class", payload.get("forced_cycle_pre_drain_exception_class"))
        payload.setdefault("forced_cycle_pre_drain_exception_message", payload.get("forced_cycle_pre_drain_exception_message"))
        payload.setdefault("forced_cycle_pending_check_enter", bool(payload.get("forced_cycle_pending_check_enter")))
        payload.setdefault("forced_cycle_pending_check_result", payload.get("forced_cycle_pending_check_result"))
        payload.setdefault("forced_cycle_pending_visible", bool(payload.get("forced_cycle_pending_visible")))
        payload.setdefault("forced_cycle_pending_not_visible", bool(payload.get("forced_cycle_pending_not_visible")))
        payload.setdefault("forced_cycle_drain_skipped", bool(payload.get("forced_cycle_drain_skipped")))
        payload.setdefault("forced_cycle_drain_enter", bool(payload.get("forced_cycle_drain_enter")))
        payload.setdefault("forced_cycle_drain_exit", bool(payload.get("forced_cycle_drain_exit")))
        payload.setdefault("forced_cycle_eval_entry", bool(payload.get("forced_cycle_eval_entry")))
        payload.setdefault("forced_cycle_eval_pre_router", bool(payload.get("forced_cycle_eval_pre_router")))
        payload.setdefault("forced_cycle_eval_post_router", bool(payload.get("forced_cycle_eval_post_router")))
        payload.setdefault("forced_cycle_eval_pre_entry_edge_check", bool(payload.get("forced_cycle_eval_pre_entry_edge_check")))
        payload.setdefault("forced_cycle_eval_post_entry_edge_check", bool(payload.get("forced_cycle_eval_post_entry_edge_check")))
        payload.setdefault("forced_cycle_eval_exit_reason", payload.get("forced_cycle_eval_exit_reason"))
        payload.setdefault("forced_cycle_eval_bypass_reason", payload.get("forced_cycle_eval_bypass_reason"))
        payload.setdefault("forced_cycle_eval_pre_selector_return_site", bool(payload.get("forced_cycle_eval_pre_selector_return_site")))
        payload.setdefault("forced_cycle_eval_pre_selector_return_site_id", payload.get("forced_cycle_eval_pre_selector_return_site_id"))
        payload.setdefault("forced_cycle_eval_pre_selector_return_reason", payload.get("forced_cycle_eval_pre_selector_return_reason"))
        payload.setdefault("forced_cycle_eval_pre_selector_has_selector_context", bool(payload.get("forced_cycle_eval_pre_selector_has_selector_context")))
        payload.setdefault("forced_cycle_eval_pre_selector_has_candidate_context", bool(payload.get("forced_cycle_eval_pre_selector_has_candidate_context")))
        payload.setdefault("forced_cycle_eval_pre_selector_helper_result_type", payload.get("forced_cycle_eval_pre_selector_helper_result_type"))
        payload.setdefault("forced_cycle_eval_pre_selector_callable_name", payload.get("forced_cycle_eval_pre_selector_callable_name"))
        payload.setdefault("forced_cycle_eval_pre_selector_callable_module", payload.get("forced_cycle_eval_pre_selector_callable_module"))
        payload.setdefault("forced_cycle_eval_pre_selector_args_summary", payload.get("forced_cycle_eval_pre_selector_args_summary"))
        payload.setdefault("forced_cycle_eval_pre_selector_expected_result_type", payload.get("forced_cycle_eval_pre_selector_expected_result_type"))
        payload.setdefault("forced_cycle_eval_pre_selector_required_fields_expected", payload.get("forced_cycle_eval_pre_selector_required_fields_expected"))
        payload.setdefault("forced_cycle_eval_pre_selector_wrapper_expected_fields", payload.get("forced_cycle_eval_pre_selector_wrapper_expected_fields"))
        payload.setdefault("forced_cycle_eval_pre_selector_actual_return_type", payload.get("forced_cycle_eval_pre_selector_actual_return_type"))
        payload.setdefault("forced_cycle_eval_pre_selector_actual_return_is_none", bool(payload.get("forced_cycle_eval_pre_selector_actual_return_is_none")))
        payload.setdefault("forced_cycle_eval_pre_selector_safe_return_repr", payload.get("forced_cycle_eval_pre_selector_safe_return_repr"))
        payload.setdefault("forced_cycle_eval_pre_selector_contract_failure_reason", payload.get("forced_cycle_eval_pre_selector_contract_failure_reason"))
        payload.setdefault("forced_cycle_result_classification", payload.get("forced_cycle_result_classification") or payload.get("result_classification"))
        payload.setdefault("candidate_reached", bool(payload.get("candidate_reached")))
        payload.setdefault("emit_attempt_reached", bool(payload.get("emit_attempt_reached")))
        payload.setdefault("emit_done_reached", bool(payload.get("emit_done_reached")))
        payload.setdefault("is_forced_post_promotion_cycle", bool(payload.get("is_forced_post_promotion_cycle")))
        return {"kind": "forced_cycle_trace", "payload": payload, "canonical": canonical}
    if event in {
        "canonical_post_promotion_loop_probe_armed",
        "canonical_post_promotion_loop_probe_next_iteration",
        "canonical_post_promotion_entry_pipeline_entered",
        "canonical_post_promotion_entry_edge_check_reached",
    }:
        canonical = details.get("canonical_bucket") or build_canonical_bucket_key(_row_payload_for_canonical(row))
        payload = dict(details)
        payload.setdefault("canonical_key", canonical.get("canonical_bucket_key"))
        payload.setdefault("bucket_identity_status", canonical.get("bucket_identity_status"))
        payload.setdefault("bucket_identity_reason", canonical.get("bucket_identity_reason"))
        payload.setdefault("symbol", canonical.get("symbol"))
        payload.setdefault("strategy", canonical.get("strategy_identity"))
        payload.setdefault("side", canonical.get("side"))
        payload.setdefault("runtime_seq", _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("row_ts", payload.get("row_ts") or row["timestamp"])
        payload.setdefault("promoted_bucket_key", payload.get("promoted_bucket_key"))
        payload.setdefault(
            "promotion_seq",
            _safe_int(payload.get("promotion_seq"), None) if payload.get("promotion_seq") is not None else None,
        )
        payload.setdefault(
            "loop_iteration_seq",
            _safe_int(payload.get("loop_iteration_seq"), None) if payload.get("loop_iteration_seq") is not None else None,
        )
        payload.setdefault(
            "entry_pipeline_entered_seq",
            _safe_int(payload.get("entry_pipeline_entered_seq"), None)
            if payload.get("entry_pipeline_entered_seq") is not None
            else None,
        )
        payload.setdefault(
            "entry_edge_check_reached_seq",
            _safe_int(payload.get("entry_edge_check_reached_seq"), None)
            if payload.get("entry_edge_check_reached_seq") is not None
            else None,
        )
        payload.setdefault("reason", payload.get("reason"))
        return {"kind": "post_promotion_loop_probe_trace", "payload": payload, "canonical": canonical}
    if event == "entry_gate_decision_summary":
        canonical = details.get("canonical_bucket") or build_canonical_bucket_key(_row_payload_for_canonical(row))
        payload = dict(details)
        payload.setdefault("runtime_seq", _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("row_ts", payload.get("ts") or payload.get("timestamp") or row["timestamp"])
        return {"kind": "entry_gate_decision_summary", "payload": payload, "canonical": canonical}
    if event == "position_close":
        canonical = details.get("canonical_bucket") or build_canonical_bucket_key(_row_payload_for_canonical(row))
        payload = dict(details)
        payload.setdefault("runtime_seq", _safe_int(payload.get("runtime_seq"), row["id"]))
        payload.setdefault("row_ts", payload.get("ts") or payload.get("timestamp") or row["timestamp"])
        return {"kind": "position_close", "payload": payload, "canonical": canonical}
    return None


def _bucket_record(key: str, canonical: dict | None = None):
    return {
        "canonical_key": key,
        "symbol": (canonical or {}).get("symbol"),
        "strategy": (canonical or {}).get("strategy_identity"),
        "side": (canonical or {}).get("side"),
        "promotion_events": [],
        "gate_read_events": [],
        "explicit_post_promotion_eval_traces": [],
        "forced_cycle_traces": [],
        "forced_cycle_pre_drain_seen": False,
        "post_promotion_loop_probe_traces": [],
        "canonical_keys_seen": set(),
        "read_source_names": Counter(),
        "decision_source_names": Counter(),
        "gate_read_source_functions": Counter(),
        "timing_replay_read_count": 0,
        "post_promotion_loop_probe_trace_count": 0,
        "close_input_traces": [],
        "close_output_traces": [],
        "storage_write_events": [],
        "pre_materialization_events": [],
        "post_materialization_events": [],
        "collapse_compare_events": [],
        "entry_gate_summary_events": [],
        "position_close_events": [],
    }


def _finalize_bucket(bucket: dict, run_max_gate_seq: int) -> dict:
    promotions = sorted(bucket["promotion_events"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    reads = sorted(bucket["gate_read_events"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    explicit_traces = sorted(bucket["explicit_post_promotion_eval_traces"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    forced_cycle_traces = sorted(bucket["forced_cycle_traces"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    forced_cycle_trace_names = {trace.get("trace_event_name") for trace in forced_cycle_traces}
    for trace in explicit_traces:
        trace_name = trace.get("trace_event_name")
        if trace_name in {
            "post_promotion_force_cycle_pre_drain_candidate",
            "post_promotion_force_cycle_pre_drain_reject",
            "post_promotion_force_cycle_pre_drain_reject_reason",
            "post_promotion_force_cycle_pre_drain_enter",
            "post_promotion_force_cycle_pre_drain_return",
            "post_promotion_force_cycle_pre_drain_skip",
            "post_promotion_force_cycle_pre_drain_skip_reason",
        } and trace_name not in forced_cycle_trace_names:
            forced_cycle_traces.append(dict(trace))
            forced_cycle_trace_names.add(trace_name)
    forced_cycle_traces.sort(key=lambda e: (e["runtime_seq"], e["seq_order"]))
    loop_probe_traces = sorted(bucket["post_promotion_loop_probe_traces"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    storage_writes = sorted(bucket["storage_write_events"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    pre_materializations = sorted(bucket["pre_materialization_events"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    post_materializations = sorted(bucket["post_materialization_events"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    collapse_compares = sorted(bucket["collapse_compare_events"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    entry_gate_summaries = sorted(bucket["entry_gate_summary_events"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    position_closes = sorted(bucket["position_close_events"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    first_promo_seq = promotions[0]["runtime_seq"] if promotions else None
    first_promo_order = promotions[0]["seq_order"] if promotions else None
    last_promo_seq = promotions[-1]["runtime_seq"] if promotions else None
    gate_after = [r for r in reads if first_promo_order is not None and r["seq_order"] > first_promo_order]
    forced_after = [r for r in gate_after if r.get("timing_replay_index") is not None]
    gate_after_last = [r for r in reads if promotions and r["seq_order"] > promotions[-1]["seq_order"]]
    first_read_after = gate_after[0] if gate_after else None
    first_visible_after = next((r for r in gate_after if int(r["canonical_shadow_trade_count"]) > 0), None)
    tc_after = [int(r["canonical_shadow_trade_count"]) for r in gate_after]
    ready_after = [bool(r["canonical_shadow_history_ready"]) for r in gate_after]
    explicit_after = [
        r
        for r in gate_after
        if r.get("override_type") == "explicit_post_promotion_eval"
        and r.get("timing_replay_index") is None
    ]
    first_same_bucket_forced = next(
        (
            r
            for r in gate_after
            if r.get("forced_same_bucket_next_eval")
            and r.get("timing_replay_index") is None
        ),
        None,
    )
    first_explicit_after = explicit_after[0] if explicit_after else None
    first_forced_cycle_trace = forced_cycle_traces[0] if forced_cycle_traces else None
    forced_cycle_requested = any(t["trace_event_name"] == "post_promotion_force_cycle_request" for t in forced_cycle_traces)
    forced_cycle_started = any(t["trace_event_name"] == "forced_cycle_started" for t in forced_cycle_traces)
    forced_cycle_completed = any(t["trace_event_name"] == "forced_cycle_completed" for t in forced_cycle_traces)
    forced_cycle_failed = any(t["trace_event_name"] == "forced_cycle_failed" for t in forced_cycle_traces)
    forced_cycle_candidate_reached = any(
        bool(t.get("candidate_reached")) for t in forced_cycle_traces if t["trace_event_name"] == "forced_cycle_completed"
    )
    forced_cycle_emit_attempt_reached = any(
        bool(t.get("emit_attempt_reached")) for t in forced_cycle_traces if t["trace_event_name"] == "forced_cycle_completed"
    )
    forced_cycle_emit_done_reached = any(
        bool(t.get("emit_done_reached")) for t in forced_cycle_traces if t["trace_event_name"] == "forced_cycle_completed"
    )
    forced_cycle_result_classification = next(
        (
            t.get("forced_cycle_result_classification")
            for t in reversed(forced_cycle_traces)
            if t.get("forced_cycle_result_classification")
        ),
        None,
    )
    forced_cycle_exit_reason = next(
        (
            t.get("forced_cycle_exit_reason")
            for t in reversed(forced_cycle_traces)
            if t.get("forced_cycle_exit_reason")
        ),
        None,
    )
    first_loop_next_iteration = next(
        (
            r
            for r in loop_probe_traces
            if r.get("trace_event_name") == "canonical_post_promotion_loop_probe_next_iteration"
            and first_promo_order is not None
            and r["seq_order"] > first_promo_order
        ),
        None,
    )
    first_loop_entry_pipeline = next(
        (
            r
            for r in loop_probe_traces
            if r.get("trace_event_name") == "canonical_post_promotion_entry_pipeline_entered"
            and first_promo_order is not None
            and r["seq_order"] > first_promo_order
        ),
        None,
    )
    first_loop_entry_edge_check = next(
        (
            r
            for r in loop_probe_traces
            if r.get("trace_event_name") == "canonical_post_promotion_entry_edge_check_reached"
            and first_promo_order is not None
            and r["seq_order"] > first_promo_order
        ),
        None,
    )
    bucket_verdict = "INSUFFICIENT_EVIDENCE"
    if promotions:
        if any(name != "canonical_shadow_storage" for name in bucket["read_source_names"]):
            bucket_verdict = "READ_SOURCE_MISMATCH_CONFIRMED"
        elif len(bucket["canonical_keys_seen"]) > 1:
            bucket_verdict = "KEY_MISMATCH_SUSPECTED"
        elif gate_after:
            bucket_verdict = "READ_AFTER_PROMOTION_AND_VISIBLE" if max(tc_after, default=0) > 0 else "READ_AFTER_PROMOTION_BUT_ZERO_VISIBLE"
        else:
            bucket_verdict = "PROMOTION_ONLY_AT_TERMINAL_END" if last_promo_seq is not None and last_promo_seq >= run_max_gate_seq else "PROMOTED_NEVER_READ_AFTERWARD"
    bucket_verdict_candidate_verdicts_seen = []
    bucket_verdict_candidate_evidence = {}
    bucket_winning_verdict = bucket_verdict
    bucket_winning_verdict_reason = "bucket_read_path_priority"
    first_promo_ts = _parse_dt(promotions[0]["run_ts"]) if promotions else None
    first_read_after_ts = _parse_dt(first_read_after["row_ts"]) if first_read_after else None
    first_visible_ts = _parse_dt(first_visible_after["row_ts"]) if first_visible_after else None
    close_inputs = sorted(bucket["close_input_traces"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    close_outputs = sorted(bucket["close_output_traces"], key=lambda e: (e["runtime_seq"], e["seq_order"]))
    pre_after = [e for e in pre_materializations if first_promo_order is not None and e["seq_order"] > first_promo_order]
    post_after = [e for e in post_materializations if first_promo_order is not None and e["seq_order"] > first_promo_order]
    compare_after = [e for e in collapse_compares if first_promo_order is not None and e["seq_order"] > first_promo_order]
    entry_after = [e for e in entry_gate_summaries if first_promo_order is not None and e["seq_order"] > first_promo_order]
    close_after = [e for e in position_closes if first_promo_order is not None and e["seq_order"] > first_promo_order]
    first_pre_after = pre_after[0] if pre_after else None
    first_post_after = post_after[0] if post_after else None
    max_pre_trade_count_after = max((int(e.get("trade_count") or 0) for e in pre_after), default=0)
    max_post_trade_count_after = max((int(e.get("trade_count") or 0) for e in post_after), default=0)
    first_compare_after = compare_after[0] if compare_after else None
    first_entry_after = entry_after[0] if entry_after else None
    first_close_after = close_after[0] if close_after else None
    last_close_seq = position_closes[-1]["runtime_seq"] if position_closes else None
    last_close_order = position_closes[-1]["seq_order"] if position_closes else None
    next_same_bucket_after_close = None
    if last_close_order is not None:
        bucket_stream = sorted(
            [
                *({"event": "entry_gate_decision_summary", **e} for e in entry_gate_summaries),
                *({"event": "position_close", **e} for e in position_closes),
                *({"event": "canonical_promotion", **e} for e in promotions),
                *({"event": "canonical_gate_read", **e} for e in reads),
                *({"event": "canonical_bucket_pre_materialization", **e} for e in pre_materializations),
                *({"event": "canonical_bucket_post_materialization", **e} for e in post_materializations),
                *({"event": "canonical_bucket_collapse_compare", **e} for e in collapse_compares),
            ],
            key=lambda e: (e["seq_order"], e["runtime_seq"]),
        )
        next_same_bucket_after_close = next((e for e in bucket_stream if e["seq_order"] > last_close_order), None)
    collapse_class = None
    if first_promo_seq is not None and (pre_after or post_after or compare_after):
        if compare_after and max_pre_trade_count_after > 0 and max_post_trade_count_after == 0:
            collapse_class = "MATERIALIZATION_BOUNDARY_COLLAPSE_CONFIRMED"
        elif pre_after and max_pre_trade_count_after == 0:
            collapse_class = "STALE_SNAPSHOT_COLLAPSE_CONFIRMED"
    post_promotion_loop_probe_verdict = "INSUFFICIENT_EVIDENCE"
    if first_promo_seq is not None and loop_probe_traces:
        if first_loop_next_iteration is None:
            post_promotion_loop_probe_verdict = "LOOP_TERMINATES_BEFORE_NEXT_EVALUATION"
        elif first_loop_entry_pipeline is None:
            post_promotion_loop_probe_verdict = "ENTRY_PIPELINE_NOT_REENTERED"
        elif first_loop_entry_edge_check is not None:
            post_promotion_loop_probe_verdict = "ENTRY_EDGE_CHECK_REACHED"
    post_promotion_read_verdict = "INSUFFICIENT_EVIDENCE"
    if first_promo_seq is not None:
        # Explicit override rows are the runtime-confirmed evaluated-read path;
        # timing replay remains a separate diagnostic and the natural pin stays
        # comparison-only.
        if first_explicit_after is not None:
            post_promotion_read_verdict = "EXPLICIT_RESEARCH_POST_PROMOTION_EVALUATED_READ"
        elif first_same_bucket_forced is not None:
            post_promotion_read_verdict = "TRUE_EVALUATED_SAME_BUCKET_REEVALUATION"
        elif first_entry_after is None and next_same_bucket_after_close is None:
            post_promotion_read_verdict = "CORRIDOR_END_BEFORE_REEVALUATION"
        elif first_entry_after is None and next_same_bucket_after_close is not None:
            post_promotion_read_verdict = "NO_SAME_BUCKET_REENTRY_TRIGGER"
        elif first_entry_after is not None and bucket["timing_replay_read_count"] > 0 and max(tc_after, default=0) == 0:
            post_promotion_read_verdict = "TIMING_REPLAY_IS_NOT_TRUE_EVALUATED_READ"
        elif first_entry_after is not None and max(tc_after, default=0) == 0:
            post_promotion_read_verdict = "ENTRY_EDGE_CHECK_NOT_REENTERED"
        elif int(first_read_after.get("canonical_shadow_trade_count") or 0) > 0:
            post_promotion_read_verdict = "POST_PROMOTION_READ_SEES_NONZERO_STATE"
    forced_cycle_progress_verdict = "INSUFFICIENT_EVIDENCE"
    if bucket.get("forced_cycle_pre_drain_seen"):
        forced_cycle_progress_verdict = "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
    bucket_verdict_candidate_verdicts_seen.extend(
        [
            bucket_verdict,
            forced_cycle_progress_verdict,
            post_promotion_read_verdict,
            post_promotion_loop_probe_verdict,
        ]
    )
    bucket_verdict_candidate_evidence[bucket_verdict] = {
        "evidence_type": "bucket_read_path",
        "gate_reads_after_first_promotion": len(gate_after),
        "post_promotion_read_count": len(gate_after),
        "post_promotion_read_verdict": post_promotion_read_verdict,
        "post_promotion_loop_probe_verdict": post_promotion_loop_probe_verdict,
        "first_entry_edge_check_seq_after_promotion": (
            int(first_entry_after["seq_order"]) if first_entry_after else None
        ),
        "was_entry_edge_check_reentered_after_promotion": bool(first_entry_after),
    }
    bucket_verdict_candidate_evidence[post_promotion_read_verdict] = {
        "evidence_type": "post_promotion_read_path",
        "entry_pipeline_entered_after_promotion": bool(first_loop_entry_pipeline),
        "entry_edge_check_reached_after_promotion": bool(first_loop_entry_edge_check),
        "first_true_evaluated_same_bucket_read_seq_after_promotion": (
            int(first_explicit_after["runtime_seq"]) if first_explicit_after else (
                int(first_same_bucket_forced["runtime_seq"]) if first_same_bucket_forced else None
            )
        ),
        "stayed_on_promoted_canonical_bucket": bool(first_explicit_after or first_same_bucket_forced),
        "max_post_trade_count_after_promotion": max_post_trade_count_after,
    }
    bucket_verdict_candidate_evidence[post_promotion_loop_probe_verdict] = {
        "evidence_type": "loop_probe_path",
        "next_loop_iteration_seq_after_promotion": (
            int(first_loop_next_iteration["runtime_seq"]) if first_loop_next_iteration else None
        ),
        "entry_pipeline_entered_after_promotion": bool(first_loop_entry_pipeline),
        "entry_edge_check_reached_after_promotion": bool(first_loop_entry_edge_check),
    }
    bucket_verdict_candidate_evidence[forced_cycle_progress_verdict] = {
        "evidence_type": "forced_cycle_pre_drain_path",
        "forced_cycle_pre_drain_seen": bool(bucket.get("forced_cycle_pre_drain_seen")),
        "forced_cycle_pre_drain_trace_count": sum(
            1 for trace in forced_cycle_traces if trace.get("trace_event_name") == "post_promotion_force_cycle_pre_drain_enter"
        ),
        "forced_cycle_request_scan_nonempty": bool(
            any(trace.get("trace_event_name") == "post_promotion_force_cycle_request_scan_nonempty" for trace in forced_cycle_traces)
        ),
        "forced_cycle_request_scan_empty": bool(
            any(trace.get("trace_event_name") == "post_promotion_force_cycle_request_scan_empty" for trace in forced_cycle_traces)
        ),
    }
    if forced_cycle_progress_verdict != "INSUFFICIENT_EVIDENCE":
        bucket_winning_verdict = forced_cycle_progress_verdict
        bucket_winning_verdict_reason = "forced_cycle_pre_drain_priority"
    elif post_promotion_loop_probe_verdict == "ENTRY_EDGE_CHECK_REACHED":
        bucket_winning_verdict = post_promotion_loop_probe_verdict
        bucket_winning_verdict_reason = "loop_probe_confirms_reentry"
    elif post_promotion_read_verdict != "INSUFFICIENT_EVIDENCE":
        bucket_winning_verdict = post_promotion_read_verdict
        bucket_winning_verdict_reason = "post_promotion_read_path_priority"
    return {
        **bucket,
        "canonical_keys_seen": sorted(bucket["canonical_keys_seen"]),
        "read_source_names": dict(bucket["read_source_names"]),
        "decision_source_names": dict(bucket["decision_source_names"]),
        "promotion_count": len(promotions),
        "gate_read_count": len(reads),
        "first_promotion_seq": first_promo_seq,
        "last_promotion_seq": last_promo_seq,
        "first_gate_read_seq": reads[0]["runtime_seq"] if reads else None,
        "last_gate_read_seq": reads[-1]["runtime_seq"] if reads else None,
        "gate_reads_after_first_promotion": len(gate_after),
        "post_promotion_read_count": len(gate_after),
        "explicit_post_promotion_eval_trace_count": len(explicit_traces),
        "post_promotion_loop_probe_trace_count": len(loop_probe_traces),
        "explicit_post_promotion_read_count": len(explicit_after),
        "forced_post_promotion_read_count": len(forced_after),
        "gate_reads_after_last_promotion": len(gate_after_last),
        "max_gate_trade_count_after_promotion": max(tc_after, default=0),
        "history_ready_after_promotion_any": any(ready_after),
        "first_visible_trade_count_after_promotion": int(first_visible_after["canonical_shadow_trade_count"]) if first_visible_after else None,
        "first_visible_seq_after_promotion": int(first_visible_after["runtime_seq"]) if first_visible_after else None,
        "first_true_evaluated_same_bucket_read_seq_after_promotion": int(first_explicit_after["runtime_seq"]) if first_explicit_after else (int(first_same_bucket_forced["runtime_seq"]) if first_same_bucket_forced else None),
        "stayed_on_promoted_canonical_bucket": bool(first_explicit_after or first_same_bucket_forced),
        "next_loop_iteration_seq_after_promotion": int(first_loop_next_iteration["runtime_seq"]) if first_loop_next_iteration else None,
        "entry_pipeline_entered_after_promotion": bool(first_loop_entry_pipeline),
        "entry_edge_check_reached_after_promotion": bool(first_loop_entry_edge_check),
        "post_promotion_loop_probe_verdict": post_promotion_loop_probe_verdict,
        "last_seen_trade_count": int(reads[-1]["canonical_shadow_trade_count"]) if reads else 0,
        "last_seen_history_ready": bool(reads[-1]["canonical_shadow_history_ready"]) if reads else False,
        "never_visible_after_promotion": bool(gate_after and max(tc_after, default=0) == 0),
        "promotion_to_first_read_delta_seq": (int(first_read_after["runtime_seq"] - first_promo_seq) if first_read_after is not None and first_promo_seq is not None else None),
        "promotion_to_first_visible_delta_seq": (int(first_visible_after["runtime_seq"] - first_promo_seq) if first_visible_after is not None and first_promo_seq is not None else None),
        "promotion_to_first_read_delta_ms": _dt_delta_ms(first_read_after_ts, first_promo_ts),
        "promotion_to_first_visible_delta_ms": _dt_delta_ms(first_visible_ts, first_promo_ts),
        "reads_between_first_and_last_promotion": sum(1 for r in reads if first_promo_seq is not None and last_promo_seq is not None and first_promo_seq < r["runtime_seq"] < last_promo_seq),
        "reads_after_last_promotion": len(gate_after_last),
        "was_any_read_for_same_bucket_after_promotion": bool(gate_after),
        "was_any_forced_read_after_promotion": bool(forced_after),
        "bucket_verdict": bucket_verdict,
        "storage_write_count": len(storage_writes),
        "pre_materialization_count": len(pre_materializations),
        "post_materialization_count": len(post_materializations),
        "collapse_compare_count": len(collapse_compares),
        "entry_gate_summary_count": len(entry_gate_summaries),
        "position_close_count": len(position_closes),
        "first_pre_materialization_seq_after_promotion": (
            int(first_pre_after["runtime_seq"]) if first_pre_after else None
        ),
        "first_post_materialization_seq_after_promotion": (
            int(first_post_after["runtime_seq"]) if first_post_after else None
        ),
        "first_gate_read_seq_after_promotion": (
            int(first_read_after["runtime_seq"]) if first_read_after else None
        ),
        "first_gate_read_trade_count_after_promotion": (
            int(first_read_after["canonical_shadow_trade_count"]) if first_read_after else None
        ),
        "first_entry_edge_check_seq_after_promotion": (
            int(first_entry_after["seq_order"]) if first_entry_after else None
        ),
        "was_entry_edge_check_reentered_after_promotion": bool(first_entry_after),
        "last_close_seq": last_close_seq,
        "next_same_bucket_runtime_seq_after_close": (
            int(next_same_bucket_after_close["runtime_seq"]) if next_same_bucket_after_close else None
        ),
        "next_same_bucket_event_name_after_close": (
            next_same_bucket_after_close.get("event") if next_same_bucket_after_close else None
        ),
        "post_promotion_pre_materialization_count": len(pre_after),
        "post_promotion_post_materialization_count": len(post_after),
        "post_promotion_collapse_compare_count": len(compare_after),
        "max_pre_trade_count_after_promotion": max_pre_trade_count_after,
        "max_post_trade_count_after_promotion": max_post_trade_count_after,
        "first_post_promotion_collapse_result": first_compare_after.get("collapse_result") if first_compare_after else None,
        "collapse_class": collapse_class,
        "post_promotion_read_verdict": post_promotion_read_verdict,
        "no_read_cause_verdict": post_promotion_read_verdict,
        "candidate_verdicts_seen": bucket_verdict_candidate_verdicts_seen,
        "candidate_verdict_evidence": bucket_verdict_candidate_evidence,
        "winning_verdict": bucket_winning_verdict,
        "winning_verdict_reason": bucket_winning_verdict_reason,
        "first_explicit_post_promotion_eval_seq_after_promotion": int(first_explicit_after["runtime_seq"]) if first_explicit_after else None,
    }


def _build_report_from_logs(run: dict, logs: list[dict], data_quality: dict | None = None) -> dict:
    return _build_report_from_logs_impl(run, logs, data_quality)


def _sync_forced_cycle_pre_drain_trace_state(buckets: dict, logs: list[dict]) -> None:
    for row in logs:
        if row.get("event") != "post_promotion_force_cycle_pre_drain_enter":
            continue
        kinded = _canon_from_row(row)
        if kinded is None:
            continue
        canonical = kinded["canonical"]
        if canonical.get("bucket_identity_status") != "RESOLVED" or not canonical.get("canonical_bucket_key"):
            continue
        payload = kinded["payload"]
        event = {
            "canonical_key": canonical.get("canonical_bucket_key"),
            "correlation_id": payload.get("correlation_id"),
            "runtime_seq": _safe_int(payload.get("runtime_seq"), row["id"]),
            "seq_order": row["id"],
            "row_ts": payload.get("row_ts") or row["timestamp"],
            "symbol": canonical.get("symbol"),
            "strategy": canonical.get("strategy_identity"),
            "side": canonical.get("side"),
            "promoted_bucket_key": payload.get("promoted_bucket_key"),
            "request_id": _safe_int(payload.get("request_id"), None) if payload.get("request_id") is not None else None,
            "request_count_seen": _safe_int(payload.get("request_count_seen"), None) if payload.get("request_count_seen") is not None else None,
            "gate_reason": payload.get("gate_reason"),
            "visibility_reason": payload.get("visibility_reason"),
            "transfer_site_id": payload.get("transfer_site_id"),
            "mailbox_stage": payload.get("mailbox_stage"),
            "handoff_transport_state": payload.get("handoff_transport_state"),
            "promotion_runtime_seq": _safe_int(payload.get("promotion_runtime_seq"), None) if payload.get("promotion_runtime_seq") is not None else None,
            "trace_event_name": row["event"],
        }
        bucket = buckets.setdefault(event["canonical_key"], _bucket_record(event["canonical_key"], canonical))
        if not any(trace.get("trace_event_name") == row["event"] for trace in bucket.get("forced_cycle_traces", [])):
            bucket["forced_cycle_traces"].append(event)
        bucket["forced_cycle_pre_drain_seen"] = True
        bucket["canonical_keys_seen"].add(event["canonical_key"])


def _build_report_from_logs_impl(run: dict, logs: list[dict], data_quality: dict | None = None) -> dict:
    runner_before = run.get("before") or {}
    promotions = []
    promotion_skips = []
    gate_reads = []
    close_traces = []
    storage_write_traces = []
    pre_materialization_traces = []
    post_materialization_traces = []
    collapse_compare_traces = []
    storage_compare_traces = []
    critical_path_exceptions = []
    unresolved_rows = 0
    unresolved_reasons = Counter()
    evaluated_total = 0
    close_total = 0
    buckets = {}
    forced_cycle_bucket_key_by_correlation = {}
    forced_cycle_bucket_canonical_by_key = {}
    active_forced_cycle_bucket_key = None
    active_forced_cycle_bucket_canonical = None

    for row in logs:
        kinded = _canon_from_row(row)
        if kinded is None:
            continue
        canonical = kinded["canonical"]
        status = canonical.get("bucket_identity_status")
        if kinded["kind"] == "promotion":
            close_total += 1
            if status != "RESOLVED" or not canonical.get("canonical_bucket_key"):
                unresolved_rows += 1
                unresolved_reasons[canonical.get("bucket_identity_reason") or "unknown"] += 1
                continue
            event = {
                "canonical_key": canonical.get("canonical_bucket_key"),
                "correlation_id": kinded["payload"].get("correlation_id"),
                "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                "seq_order": row["id"],
                "row_ts": kinded["payload"].get("run_ts") or row["timestamp"],
                "run_ts": kinded["payload"].get("run_ts") or row["timestamp"],
                "read_source_name": kinded["payload"].get("read_source_name") or "canonical_shadow_storage",
                "decision_source_name": kinded["payload"].get("decision_source_name"),
                "canonical_shadow_trade_count": _safe_int(kinded["payload"].get("canonical_shadow_trade_count")),
                "canonical_shadow_history_ready": bool(kinded["payload"].get("canonical_shadow_history_ready")),
                "canonical_shadow_last_update_ts": kinded["payload"].get("canonical_shadow_last_update_ts"),
                "canonical_shadow_source_name": kinded["payload"].get("canonical_shadow_source_name") or "canonical_shadow_storage",
                "canonical_shadow_storage_bucket": kinded["payload"].get("canonical_shadow_storage_bucket"),
                "read_source_bucket_shape": kinded["payload"].get("read_source_bucket_shape"),
                "decision_snapshot_selection": kinded["payload"].get("decision_snapshot_selection"),
                "raw_symbol": canonical.get("raw_symbol"),
                "raw_strategy": canonical.get("raw_strategy"),
                "raw_side": canonical.get("raw_side"),
            }
            promotions.append(event)
        elif kinded["kind"] == "promotion_skipped":
            skipped_reason = str(kinded["payload"].get("skip_reason") or "unknown")
            promotion_skips.append(
                {
                    "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                    "reason": skipped_reason,
                    "symbol": kinded["payload"].get("symbol"),
                    "strategy": kinded["payload"].get("strategy"),
                    "side": kinded["payload"].get("side"),
                }
            )
        elif kinded["kind"] == "gate":
            evaluated_total += 1
            if status != "RESOLVED" or not canonical.get("canonical_bucket_key"):
                unresolved_rows += 1
                unresolved_reasons[canonical.get("bucket_identity_reason") or "unknown"] += 1
                continue
            event = {
                "canonical_key": canonical.get("canonical_bucket_key"),
                "correlation_id": kinded["payload"].get("correlation_id"),
                "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                "seq_order": row["id"],
                "row_ts": kinded["payload"].get("row_ts") or row["timestamp"],
                "read_source_name": kinded["payload"].get("read_source_name") or "canonical_shadow_storage",
                "read_trade_count": _safe_int(kinded["payload"].get("read_trade_count")),
                "read_history_ready": bool(kinded["payload"].get("read_history_ready")),
                "read_context": kinded["payload"].get("read_context"),
                "timing_replay_index": _safe_int(kinded["payload"].get("timing_replay_index"), None) if kinded["payload"].get("timing_replay_index") is not None else None,
                "timing_replay_target_reads": _safe_int(kinded["payload"].get("timing_replay_target_reads"), None) if kinded["payload"].get("timing_replay_target_reads") is not None else None,
                "gate_read_source_function": kinded["payload"].get("gate_read_source_function"),
                "canonical_shadow_source_name": kinded["payload"].get("canonical_shadow_source_name") or "canonical_shadow_storage",
                "canonical_shadow_trade_count": _safe_int(kinded["payload"].get("canonical_shadow_trade_count")),
                "canonical_shadow_history_ready": bool(kinded["payload"].get("canonical_shadow_history_ready")),
                "canonical_shadow_last_update_ts": kinded["payload"].get("canonical_shadow_last_update_ts"),
                "decision_source_name": kinded["payload"].get("decision_source_name"),
                "decision_trade_count": _safe_int(kinded["payload"].get("decision_trade_count")),
                "decision_history_ready": bool(kinded["payload"].get("decision_history_ready")),
                "canonical_shadow_storage_bucket": kinded["payload"].get("canonical_shadow_storage_bucket"),
                "read_source_bucket_shape": kinded["payload"].get("read_source_bucket_shape"),
                "decision_snapshot_selection": kinded["payload"].get("decision_snapshot_selection"),
                "forced_same_bucket_next_eval": bool(kinded["payload"].get("forced_same_bucket_next_eval")),
                "override_type": kinded["payload"].get("override_type"),
                "override_consumed": bool(kinded["payload"].get("override_consumed")),
                "promoted_bucket_key": kinded["payload"].get("promoted_bucket_key"),
                "post_invoke_emit_path_enter": bool(kinded["payload"].get("post_invoke_emit_path_enter")),
                "post_invoke_emit_guard_considered": bool(kinded["payload"].get("post_invoke_emit_guard_considered")),
                "post_invoke_emit_guard_allowed": bool(kinded["payload"].get("post_invoke_emit_guard_allowed")),
                "post_invoke_emit_guard_reason": kinded["payload"].get("post_invoke_emit_guard_reason"),
                "post_invoke_emit_early_return": bool(kinded["payload"].get("post_invoke_emit_early_return")),
                "post_invoke_emit_early_return_reason": kinded["payload"].get("post_invoke_emit_early_return_reason"),
                "post_invoke_emit_attempt_reached": bool(kinded["payload"].get("post_invoke_emit_attempt_reached")),
                "raw_symbol": canonical.get("raw_symbol"),
                "raw_strategy": canonical.get("raw_strategy"),
                "raw_side": canonical.get("raw_side"),
            }
            gate_reads.append(event)
        elif kinded["kind"] == "explicit_post_promotion_eval_trace":
            if status != "RESOLVED" or not canonical.get("canonical_bucket_key"):
                unresolved_rows += 1
                unresolved_reasons[canonical.get("bucket_identity_reason") or "unknown"] += 1
                continue
            event = {
                "canonical_key": canonical.get("canonical_bucket_key"),
                "correlation_id": kinded["payload"].get("correlation_id"),
                "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                "seq_order": row["id"],
                "row_ts": kinded["payload"].get("row_ts") or row["timestamp"],
                "symbol": canonical.get("symbol"),
                "strategy": canonical.get("strategy_identity"),
                "side": canonical.get("side"),
                "promoted_bucket_key": kinded["payload"].get("promoted_bucket_key"),
                "armed_at_seq": kinded["payload"].get("armed_at_seq"),
                "invoked_at_seq": kinded["payload"].get("invoked_at_seq"),
                "consumed_at_seq": kinded["payload"].get("consumed_at_seq"),
                "cleared_at_seq": kinded["payload"].get("cleared_at_seq"),
                "reason": kinded["payload"].get("reason"),
                "clear_reason": kinded["payload"].get("clear_reason"),
                "post_invoke_emit_path_enter": bool(kinded["payload"].get("post_invoke_emit_path_enter")),
                "post_invoke_emit_guard_considered": bool(kinded["payload"].get("post_invoke_emit_guard_considered")),
                "post_invoke_emit_guard_allowed": bool(kinded["payload"].get("post_invoke_emit_guard_allowed")),
                "post_invoke_emit_guard_reason": kinded["payload"].get("post_invoke_emit_guard_reason"),
                "post_invoke_emit_early_return": bool(kinded["payload"].get("post_invoke_emit_early_return")),
                "post_invoke_emit_early_return_reason": kinded["payload"].get("post_invoke_emit_early_return_reason"),
                "post_invoke_emit_attempt_reached": bool(kinded["payload"].get("post_invoke_emit_attempt_reached")),
                "trace_event_name": row["event"],
            }
            bucket = buckets.setdefault(canonical.get("canonical_bucket_key"), _bucket_record(canonical.get("canonical_bucket_key"), canonical))
            bucket["explicit_post_promotion_eval_traces"].append(event)
            if row["event"].startswith("post_promotion_force_cycle_handoff_") or row["event"] == "post_promotion_force_cycle_pre_drain_enter":
                bucket["forced_cycle_traces"].append(event)
                if row["event"] == "post_promotion_force_cycle_pre_drain_enter":
                    bucket["forced_cycle_pre_drain_seen"] = True
            bucket["canonical_keys_seen"].add(event["canonical_key"])
        elif kinded["kind"] == "forced_cycle_trace":
            event = {
                "canonical_key": canonical.get("canonical_bucket_key"),
                "correlation_id": kinded["payload"].get("correlation_id"),
                "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                "seq_order": row["id"],
                "row_ts": kinded["payload"].get("row_ts") or row["timestamp"],
                "symbol": canonical.get("symbol"),
                "strategy": canonical.get("strategy_identity"),
                "side": canonical.get("side"),
                "promoted_bucket_key": kinded["payload"].get("canonical_key"),
                "promotion_runtime_seq": _safe_int(kinded["payload"].get("promotion_runtime_seq"), None) if kinded["payload"].get("promotion_runtime_seq") is not None else None,
                "forced_cycle_request_runtime_seq": _safe_int(kinded["payload"].get("forced_cycle_request_runtime_seq"), None) if kinded["payload"].get("forced_cycle_request_runtime_seq") is not None else None,
                "forced_cycle_runtime_seq": _safe_int(kinded["payload"].get("forced_cycle_runtime_seq"), None) if kinded["payload"].get("forced_cycle_runtime_seq") is not None else None,
                "forced_cycle_exit_reason": kinded["payload"].get("forced_cycle_exit_reason"),
                "forced_cycle_request_scan_candidate_seen": bool(
                    kinded["payload"].get("forced_cycle_request_scan_candidate_seen")
                    or kinded["payload"].get("request_id")
                    or kinded["payload"].get("empty_reason")
                ),
                "forced_cycle_request_scan_candidate_reject": bool(
                    kinded["payload"].get("forced_cycle_request_scan_candidate_reject")
                    or kinded["payload"].get("candidate_reject_reason")
                ),
                "forced_cycle_request_scan_candidate_reject_reason": kinded["payload"].get("candidate_reject_reason"),
                "forced_cycle_request_scan_empty_reason": kinded["payload"].get("empty_reason"),
                "forced_cycle_eval_entry": bool(kinded["payload"].get("forced_cycle_eval_entry")),
                "forced_cycle_eval_pre_router": bool(kinded["payload"].get("forced_cycle_eval_pre_router")),
                "forced_cycle_eval_post_router": bool(kinded["payload"].get("forced_cycle_eval_post_router")),
                "forced_cycle_eval_pre_entry_edge_check": bool(kinded["payload"].get("forced_cycle_eval_pre_entry_edge_check")),
                "forced_cycle_eval_post_entry_edge_check": bool(kinded["payload"].get("forced_cycle_eval_post_entry_edge_check")),
                "forced_cycle_eval_exit_reason": kinded["payload"].get("forced_cycle_eval_exit_reason"),
                "forced_cycle_eval_bypass_reason": kinded["payload"].get("forced_cycle_eval_bypass_reason"),
                "forced_cycle_eval_pre_selector_return_site": bool(kinded["payload"].get("forced_cycle_eval_pre_selector_return_site")),
                "forced_cycle_eval_pre_selector_return_site_id": kinded["payload"].get("forced_cycle_eval_pre_selector_return_site_id"),
                "forced_cycle_eval_pre_selector_return_reason": kinded["payload"].get("forced_cycle_eval_pre_selector_return_reason"),
                "forced_cycle_eval_pre_selector_has_selector_context": bool(kinded["payload"].get("forced_cycle_eval_pre_selector_has_selector_context")),
                "forced_cycle_eval_pre_selector_has_candidate_context": bool(kinded["payload"].get("forced_cycle_eval_pre_selector_has_candidate_context")),
                "forced_cycle_eval_pre_selector_helper_result_type": kinded["payload"].get("forced_cycle_eval_pre_selector_helper_result_type"),
                "forced_cycle_result_classification": kinded["payload"].get("forced_cycle_result_classification"),
                "candidate_reached": bool(kinded["payload"].get("candidate_reached")),
                "emit_attempt_reached": bool(kinded["payload"].get("emit_attempt_reached")),
                "emit_done_reached": bool(kinded["payload"].get("emit_done_reached")),
                "transfer_site_id": kinded["payload"].get("transfer_site_id"),
                "mailbox_stage": kinded["payload"].get("mailbox_stage"),
                "handoff_transport_state": kinded["payload"].get("handoff_transport_state"),
                "evaluation_phase": kinded["payload"].get("evaluation_phase"),
                "is_forced_post_promotion_cycle": bool(kinded["payload"].get("is_forced_post_promotion_cycle")),
                "trace_event_name": row["event"],
            }
            event_bucket_key = canonical.get("canonical_bucket_key")
            event_correlation_id = kinded["payload"].get("correlation_id")
            if event_bucket_key:
                forced_cycle_bucket_key_by_correlation[event_correlation_id] = event_bucket_key
                forced_cycle_bucket_canonical_by_key[event_bucket_key] = canonical
                active_forced_cycle_bucket_key = event_bucket_key
                active_forced_cycle_bucket_canonical = canonical
            else:
                event_bucket_key = forced_cycle_bucket_key_by_correlation.get(event_correlation_id) or active_forced_cycle_bucket_key
                if event_bucket_key:
                    event_bucket_canonical = forced_cycle_bucket_canonical_by_key.get(event_bucket_key) or active_forced_cycle_bucket_canonical
                    if event_bucket_canonical is not None:
                        canonical = event_bucket_canonical
                    event["canonical_key"] = event_bucket_key
                    event["symbol"] = canonical.get("symbol")
                    event["strategy"] = canonical.get("strategy_identity")
                    event["side"] = canonical.get("side")
            if status != "RESOLVED" and not event_bucket_key:
                unresolved_rows += 1
                unresolved_reasons[canonical.get("bucket_identity_reason") or "unknown"] += 1
                continue
            bucket = buckets.setdefault(event_bucket_key, _bucket_record(event_bucket_key, canonical))
            if event_bucket_key:
                forced_cycle_bucket_key_by_correlation[event_correlation_id] = event_bucket_key
                forced_cycle_bucket_canonical_by_key[event_bucket_key] = canonical
                active_forced_cycle_bucket_key = event_bucket_key
                active_forced_cycle_bucket_canonical = canonical
            if row["event"] in {
                "handoff_parent_enqueue_enter",
                "handoff_parent_enqueue_done",
                "handoff_parent_signal_sent",
                "handoff_child_mailbox_observed",
                "handoff_child_mailbox_dequeue_enter",
                "post_promotion_force_cycle_pre_drain_enter",
            }:
                explicit_event = {
                    **event,
                    "trace_event_name": row["event"],
                    "is_forced_post_promotion_cycle": True,
                }
                bucket["explicit_post_promotion_eval_traces"].append(explicit_event)
                bucket["forced_cycle_traces"].append(explicit_event)
                if row["event"] == "post_promotion_force_cycle_pre_drain_enter":
                    bucket["forced_cycle_pre_drain_seen"] = True
            else:
                bucket["forced_cycle_traces"].append(event)
            bucket["canonical_keys_seen"].add(event["canonical_key"])
        elif kinded["kind"] == "post_promotion_loop_probe_trace":
            if status != "RESOLVED" or not canonical.get("canonical_bucket_key"):
                unresolved_rows += 1
                unresolved_reasons[canonical.get("bucket_identity_reason") or "unknown"] += 1
                continue
            event = {
                "canonical_key": canonical.get("canonical_bucket_key"),
                "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                "seq_order": row["id"],
                "row_ts": kinded["payload"].get("row_ts") or row["timestamp"],
                "symbol": canonical.get("symbol"),
                "strategy": canonical.get("strategy_identity"),
                "side": canonical.get("side"),
                "promoted_bucket_key": kinded["payload"].get("promoted_bucket_key"),
                "promotion_seq": _safe_int(kinded["payload"].get("promotion_seq"), None)
                if kinded["payload"].get("promotion_seq") is not None
                else None,
                "loop_iteration_seq": _safe_int(kinded["payload"].get("loop_iteration_seq"), None)
                if kinded["payload"].get("loop_iteration_seq") is not None
                else None,
                "entry_pipeline_entered_seq": _safe_int(kinded["payload"].get("entry_pipeline_entered_seq"), None)
                if kinded["payload"].get("entry_pipeline_entered_seq") is not None
                else None,
                "entry_edge_check_reached_seq": _safe_int(kinded["payload"].get("entry_edge_check_reached_seq"), None)
                if kinded["payload"].get("entry_edge_check_reached_seq") is not None
                else None,
                "reason": kinded["payload"].get("reason"),
                "trace_event_name": row["event"],
            }
            bucket = buckets.setdefault(canonical.get("canonical_bucket_key"), _bucket_record(canonical.get("canonical_bucket_key"), canonical))
            bucket["post_promotion_loop_probe_traces"].append(event)
            bucket["canonical_keys_seen"].add(event["canonical_key"])
        elif kinded["kind"] == "close_trace":
            canonical_key = canonical.get("canonical_bucket_key")
            if not canonical_key:
                unresolved_rows += 1
                unresolved_reasons[canonical.get("bucket_identity_reason") or "unknown"] += 1
                continue
            event = {
                "trace_kind": kinded["kind"],
                "canonical_key": canonical_key,
                "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                "seq_order": row["id"],
                "row_ts": kinded["payload"].get("run_ts") or row["timestamp"],
                "symbol": canonical.get("symbol"),
                "strategy": canonical.get("strategy_identity"),
                "side": canonical.get("side"),
                "raw_symbol": canonical.get("raw_symbol"),
                "raw_strategy": canonical.get("raw_strategy"),
                "raw_side": canonical.get("raw_side"),
                "normalized_symbol": canonical.get("normalized_symbol"),
                "normalized_strategy": canonical.get("normalized_strategy"),
                "normalized_side": canonical.get("normalized_side"),
                "position_id": kinded["payload"].get("position_id"),
                "net_pnl": kinded["payload"].get("net_pnl"),
                "gross_fill_pnl_model": kinded["payload"].get("gross_fill_pnl_model"),
                "fee_total": kinded["payload"].get("fee_total"),
                "slippage_total": kinded["payload"].get("slippage_total"),
                "has_pnl_decompose": bool(kinded["payload"].get("has_pnl_decompose")),
                "source_function_name": kinded["payload"].get("source_function_name"),
                "upstream_source_name": kinded["payload"].get("upstream_source_name"),
                "gross_present": bool(kinded["payload"].get("gross_present")),
                "fee_present": bool(kinded["payload"].get("fee_present")),
                "promotion_inputs_ready": bool(kinded["payload"].get("promotion_inputs_ready")),
                "raw_input_classification": kinded["payload"].get("raw_input_classification"),
                "output_null_classification": kinded["payload"].get("output_null_classification"),
                "source_branch": kinded["payload"].get("source_branch"),
            }
            close_traces.append(event)
        elif kinded["kind"] == "canonical_storage_write_trace":
            storage_write_traces.append(
                {
                    "canonical_key": kinded["payload"].get("canonical_key"),
                    "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                    "seq_order": row["id"],
                    "row_ts": kinded["payload"].get("timestamp") or row["timestamp"],
                    "storage_container_name": kinded["payload"].get("storage_container_name"),
                    "storage_container_id": kinded["payload"].get("storage_container_id"),
                    "nested_key_path": kinded["payload"].get("nested_key_path"),
                    "trade_count": _safe_int(kinded["payload"].get("stored_trade_count")),
                    "history_ready": bool(kinded["payload"].get("stored_history_ready")),
                    "gross_hist_len": _safe_int(kinded["payload"].get("gross_hist_len")),
                    "fee_hist_len": _safe_int(kinded["payload"].get("fee_hist_len")),
                    "slippage_hist_len": _safe_int(kinded["payload"].get("slippage_hist_len")),
                    "object_id_or_equivalent_if_safe": kinded["payload"].get("storage_bucket_id"),
                    "full_bucket_shape": kinded["payload"].get("full_bucket_shape"),
                }
            )
        elif kinded["kind"] == "canonical_bucket_pre_materialization":
            pre_materialization_traces.append(
                {
                    "canonical_key": kinded["payload"].get("canonical_key"),
                    "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                    "seq_order": row["id"],
                    "row_ts": kinded["payload"].get("timestamp") or row["timestamp"],
                    "source_container_name": kinded["payload"].get("source_container_name"),
                    "storage_container_id": kinded["payload"].get("storage_container_id"),
                    "nested_key_path": kinded["payload"].get("nested_key_path"),
                    "trade_count": _safe_int(kinded["payload"].get("trade_count")),
                    "history_ready": bool(kinded["payload"].get("history_ready")),
                    "gross_hist_len": _safe_int(kinded["payload"].get("gross_hist_len")),
                    "fee_hist_len": _safe_int(kinded["payload"].get("fee_hist_len")),
                    "slippage_hist_len": _safe_int(kinded["payload"].get("slippage_hist_len")),
                    "object_id_or_equivalent_if_safe": kinded["payload"].get("object_id_or_equivalent_if_safe"),
                    "full_bucket_shape": kinded["payload"].get("full_bucket_shape"),
                }
            )
        elif kinded["kind"] == "canonical_bucket_post_materialization":
            post_materialization_traces.append(
                {
                    "canonical_key": kinded["payload"].get("canonical_key"),
                    "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                    "seq_order": row["id"],
                    "row_ts": kinded["payload"].get("timestamp") or row["timestamp"],
                    "materializer_name": kinded["payload"].get("materializer_name"),
                    "source_container_name": kinded["payload"].get("source_container_name"),
                    "storage_container_id": kinded["payload"].get("storage_container_id"),
                    "nested_key_path": kinded["payload"].get("nested_key_path"),
                    "trade_count": _safe_int(kinded["payload"].get("trade_count")),
                    "history_ready": bool(kinded["payload"].get("history_ready")),
                    "gross_hist_len": _safe_int(kinded["payload"].get("gross_hist_len")),
                    "fee_hist_len": _safe_int(kinded["payload"].get("fee_hist_len")),
                    "slippage_hist_len": _safe_int(kinded["payload"].get("slippage_hist_len")),
                    "object_id_or_equivalent_if_safe": kinded["payload"].get("object_id_or_equivalent_if_safe"),
                    "full_bucket_shape": kinded["payload"].get("full_bucket_shape"),
                }
            )
        elif kinded["kind"] == "canonical_bucket_collapse_compare":
            collapse_compare_traces.append(
                {
                    "canonical_key": kinded["payload"].get("canonical_key"),
                    "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                    "seq_order": row["id"],
                    "row_ts": kinded["payload"].get("timestamp") or row["timestamp"],
                    "pre_trade_count": _safe_int(kinded["payload"].get("pre_trade_count")),
                    "post_trade_count": _safe_int(kinded["payload"].get("post_trade_count")),
                    "pre_gross_hist_len": _safe_int(kinded["payload"].get("pre_gross_hist_len")),
                    "post_gross_hist_len": _safe_int(kinded["payload"].get("post_gross_hist_len")),
                    "pre_fee_hist_len": _safe_int(kinded["payload"].get("pre_fee_hist_len")),
                    "post_fee_hist_len": _safe_int(kinded["payload"].get("post_fee_hist_len")),
                    "pre_slippage_hist_len": _safe_int(kinded["payload"].get("pre_slippage_hist_len")),
                    "post_slippage_hist_len": _safe_int(kinded["payload"].get("post_slippage_hist_len")),
                    "same_object_identity_if_available": bool(kinded["payload"].get("same_object_identity_if_available")),
                    "same_nested_key_path": bool(kinded["payload"].get("same_nested_key_path")),
                    "collapse_result": kinded["payload"].get("collapse_result"),
                }
            )
        elif kinded["kind"] == "canonical_storage_compare_trace":
            storage_compare_traces.append(
                {
                    "canonical_key": kinded["payload"].get("canonical_key"),
                    "correlation_id": kinded["payload"].get("correlation_id"),
                    "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                    "seq_order": row["id"],
                    "row_ts": kinded["payload"].get("row_ts") or row["timestamp"],
                    "stage_written": bool(kinded["payload"].get("stage_written")),
                    "stage_emit_attempted": bool(kinded["payload"].get("stage_emit_attempted")),
                    "stage_persisted": bool(kinded["payload"].get("stage_persisted")),
                    "stage_observed": bool(kinded["payload"].get("stage_observed")),
                    "stage_exception": bool(kinded["payload"].get("stage_exception")),
                    "final_per_correlation_verdict": kinded["payload"].get(
                        "final_per_correlation_verdict"
                    ),
                }
            )
        elif kinded["kind"] == "critical_path_exception":
            critical_path_exceptions.append(
                {
                    "canonical_key": kinded["canonical"].get("canonical_bucket_key"),
                    "correlation_id": kinded["payload"].get("correlation_id"),
                    "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                    "seq_order": row["id"],
                    "stage": kinded["payload"].get("stage"),
                    "exception_class": kinded["payload"].get("exception_class"),
                    "exception_message": kinded["payload"].get("exception_message"),
                }
            )
        elif kinded["kind"] == "entry_gate_decision_summary":
            canonical_key = canonical.get("canonical_bucket_key")
            if not canonical_key:
                unresolved_rows += 1
                unresolved_reasons[canonical.get("bucket_identity_reason") or "unknown"] += 1
                continue
            entry_event = {
                "canonical_key": canonical_key,
                "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                "seq_order": row["id"],
                "row_ts": kinded["payload"].get("row_ts") or row["timestamp"],
                "event": "entry_gate_decision_summary",
            }
            bucket = buckets.setdefault(entry_event["canonical_key"], _bucket_record(entry_event["canonical_key"]))
            bucket["entry_gate_summary_events"].append(entry_event)
            bucket["canonical_keys_seen"].add(entry_event["canonical_key"])
        elif kinded["kind"] == "position_close":
            canonical_key = canonical.get("canonical_bucket_key")
            if not canonical_key:
                unresolved_rows += 1
                unresolved_reasons[canonical.get("bucket_identity_reason") or "unknown"] += 1
                continue
            close_event = {
                "canonical_key": canonical_key,
                "runtime_seq": _safe_int(kinded["payload"].get("runtime_seq"), row["id"]),
                "seq_order": row["id"],
                "row_ts": kinded["payload"].get("row_ts") or row["timestamp"],
                "event": "position_close",
            }
            bucket = buckets.setdefault(close_event["canonical_key"], _bucket_record(close_event["canonical_key"]))
            bucket["position_close_events"].append(close_event)
            bucket["canonical_keys_seen"].add(close_event["canonical_key"])

    for event in promotions:
        bucket = buckets.setdefault(event["canonical_key"], _bucket_record(event["canonical_key"]))
        bucket["promotion_events"].append(event)
        bucket["canonical_keys_seen"].add(event["canonical_key"])
        bucket["read_source_names"][event["read_source_name"]] += 1
        if event.get("decision_source_name"):
            bucket["decision_source_names"][event["decision_source_name"]] += 1
    for event in gate_reads:
        bucket = buckets.setdefault(event["canonical_key"], _bucket_record(event["canonical_key"]))
        bucket["gate_read_events"].append(event)
        bucket["canonical_keys_seen"].add(event["canonical_key"])
        bucket["read_source_names"][event["read_source_name"]] += 1
        bucket["gate_read_source_functions"][event.get("gate_read_source_function") or "unknown"] += 1
        if event.get("timing_replay_index") is not None:
            bucket["timing_replay_read_count"] += 1
        if event.get("decision_source_name"):
            bucket["decision_source_names"][event["decision_source_name"]] += 1
    for event in close_traces:
        bucket = buckets.setdefault(event["canonical_key"], _bucket_record(event["canonical_key"]))
        if event.get("trace_kind") == "close_trace" and event.get("raw_input_classification") in {
            "RAW_INPUTS_PRESENT",
            "RAW_FEE_INPUT_MISSING",
            "RAW_FILL_INPUTS_MISSING",
            "ZERO_SIZE_CLOSE_INPUT",
            "RAW_INPUTS_PARTIAL",
            "UNKNOWN_RAW_INPUT_STATE",
        }:
            bucket["close_input_traces"].append(event)
        elif event.get("trace_kind") == "close_trace":
            bucket["close_output_traces"].append(event)
        bucket["canonical_keys_seen"].add(event["canonical_key"])
    for event in storage_write_traces:
        bucket = buckets.setdefault(event["canonical_key"], _bucket_record(event["canonical_key"]))
        bucket["storage_write_events"].append(event)
        bucket["canonical_keys_seen"].add(event["canonical_key"])
    for event in pre_materialization_traces:
        bucket = buckets.setdefault(event["canonical_key"], _bucket_record(event["canonical_key"]))
        bucket["pre_materialization_events"].append(event)
        bucket["canonical_keys_seen"].add(event["canonical_key"])
    for event in post_materialization_traces:
        bucket = buckets.setdefault(event["canonical_key"], _bucket_record(event["canonical_key"]))
        bucket["post_materialization_events"].append(event)
        bucket["canonical_keys_seen"].add(event["canonical_key"])
    for event in collapse_compare_traces:
        bucket = buckets.setdefault(event["canonical_key"], _bucket_record(event["canonical_key"]))
        bucket["collapse_compare_events"].append(event)
        bucket["canonical_keys_seen"].add(event["canonical_key"])

    for row in logs:
        if row["event"] != "post_promotion_force_cycle_pre_drain_enter":
            continue
        kinded = _canon_from_row(row)
        if kinded is None:
            continue
        canonical = kinded["canonical"]
        if canonical.get("bucket_identity_status") != "RESOLVED" or not canonical.get("canonical_bucket_key"):
            continue
        payload = kinded["payload"]
        event = {
            "canonical_key": canonical.get("canonical_bucket_key"),
            "correlation_id": payload.get("correlation_id"),
            "runtime_seq": _safe_int(payload.get("runtime_seq"), row["id"]),
            "seq_order": row["id"],
            "row_ts": payload.get("row_ts") or row["timestamp"],
            "symbol": canonical.get("symbol"),
            "strategy": canonical.get("strategy_identity"),
            "side": canonical.get("side"),
            "promoted_bucket_key": payload.get("promoted_bucket_key"),
            "request_id": _safe_int(payload.get("request_id"), None) if payload.get("request_id") is not None else None,
            "request_count_seen": _safe_int(payload.get("request_count_seen"), None) if payload.get("request_count_seen") is not None else None,
            "gate_reason": payload.get("gate_reason"),
            "visibility_reason": payload.get("visibility_reason"),
            "transfer_site_id": payload.get("transfer_site_id"),
            "mailbox_stage": payload.get("mailbox_stage"),
            "handoff_transport_state": payload.get("handoff_transport_state"),
            "promotion_runtime_seq": _safe_int(payload.get("promotion_runtime_seq"), None) if payload.get("promotion_runtime_seq") is not None else None,
            "trace_event_name": row["event"],
        }
        bucket = buckets.setdefault(event["canonical_key"], _bucket_record(event["canonical_key"], canonical))
        if not any(trace.get("trace_event_name") == row["event"] for trace in bucket.get("forced_cycle_traces", [])):
            bucket["forced_cycle_traces"].append(event)
        bucket["forced_cycle_pre_drain_seen"] = True
        bucket["canonical_keys_seen"].add(event["canonical_key"])

    run_max_gate_seq = max((e["runtime_seq"] for e in gate_reads), default=0)
    _sync_forced_cycle_pre_drain_trace_state(buckets, logs)
    per_bucket = {k: _finalize_bucket(v, run_max_gate_seq) for k, v in buckets.items()}
    verdict_counts = Counter(v["bucket_verdict"] for v in per_bucket.values())

    buckets_promoted = sum(1 for v in per_bucket.values() if v["promotion_count"] > 0)
    buckets_read = sum(1 for v in per_bucket.values() if v["gate_read_count"] > 0)
    buckets_read_after_promotion = sum(1 for v in per_bucket.values() if v["gate_reads_after_first_promotion"] > 0)
    buckets_with_forced_replay = sum(1 for v in per_bucket.values() if v["forced_post_promotion_read_count"] > 0)
    forced_replay_reads_total = sum(v["forced_post_promotion_read_count"] for v in per_bucket.values())
    buckets_with_nonzero_visible_trade_count = sum(1 for v in per_bucket.values() if v["max_gate_trade_count_after_promotion"] > 0)
    buckets_with_history_ready_after_promotion = sum(1 for v in per_bucket.values() if v["history_ready_after_promotion_any"])
    promotion_visibility_rate = buckets_with_nonzero_visible_trade_count / max(1, buckets_promoted)
    promotion_skip_reasons = Counter(e["reason"] for e in promotion_skips)
    close_input_rows = len(close_traces) // 2 if close_traces else 0
    close_input_count = sum(1 for e in close_traces if e.get("trace_kind") == "close_trace" and e.get("raw_input_classification") is not None)
    close_output_count = sum(1 for e in close_traces if e.get("trace_kind") == "close_trace" and e.get("raw_input_classification") is None)
    row_diagnoses = []
    for inp in sorted([e for e in close_traces if e.get("raw_input_classification") is not None], key=lambda e: (e["runtime_seq"], e["seq_order"])):
        out = next((o for o in close_traces if o.get("raw_input_classification") is None and o["runtime_seq"] == inp["runtime_seq"] and o["canonical_key"] == inp["canonical_key"]), None)
        diagnosis = inp["raw_input_classification"]
        if diagnosis == "RAW_INPUTS_PRESENT" and out and out.get("output_null_classification") == "REALIZED_INPUTS_PRESENT":
            diagnosis = "INPUTS_PRESENT_OUTPUT_STILL_NULL"
        elif diagnosis == "RAW_INPUTS_PRESENT" and out and out.get("output_null_classification") != "REALIZED_INPUTS_PRESENT":
            diagnosis = "DECOMPOSE_OUTPUT_NOT_ASSIGNED"
        row_diagnoses.append({
            "runtime_seq": inp["runtime_seq"],
            "canonical_key": inp["canonical_key"],
            "input_classification": inp["raw_input_classification"],
            "output_classification": out.get("output_null_classification") if out else None,
            "branch": inp.get("source_branch"),
            "diagnosis": diagnosis,
        })
    diagnosis_counts = Counter(r["diagnosis"] for r in row_diagnoses)
    top_root_cause = diagnosis_counts.most_common(1)[0][0] if diagnosis_counts else "INSUFFICIENT_EVIDENCE"

    visibility_ms = [v["promotion_to_first_visible_delta_ms"] for v in per_bucket.values() if v["promotion_to_first_visible_delta_ms"] is not None]
    top_failure_mode = "INSUFFICIENT_EVIDENCE"
    if top_root_cause in {
        "RAW_FEE_INPUT_MISSING",
        "RAW_FILL_INPUTS_MISSING",
        "ZERO_SIZE_CLOSE_INPUT",
        "MOCK_BRANCH_UNPOPULATED_REALIZED_FIELDS",
        "DECOMPOSE_OUTPUT_NOT_ASSIGNED",
        "PAYLOAD_CONSTRUCTION_LOSS_BEFORE_DECOMPOSE",
        "INPUTS_PRESENT_OUTPUT_STILL_NULL",
        "MIXED_UPSTREAM_NULL_SOURCES",
    }:
        top_failure_mode = top_root_cause
    else:
        if buckets_promoted == 0:
            top_failure_mode = "INSUFFICIENT_EVIDENCE"
        elif buckets_read_after_promotion == 0:
            top_failure_mode = "STILL_NO_VISIBILITY_AFTER_FORCED_POST_PROMOTION_READS"
        elif buckets_with_nonzero_visible_trade_count > 0 and buckets_with_history_ready_after_promotion > 0:
            top_failure_mode = "PURE_TIMING_CUTOFF_CONFIRMED"
        elif buckets_with_nonzero_visible_trade_count > 0:
            top_failure_mode = "TIMING_FIXED_SECOND_BLOCKER_REVEALED"
        else:
            top_failure_mode = "STILL_NO_VISIBILITY_AFTER_FORCED_POST_PROMOTION_READS"

    read_source_names_seen = sorted(set(
        [e["read_source_name"] for e in gate_reads if e.get("read_source_name")] +
        [e["decision_source_name"] for e in gate_reads if e.get("decision_source_name")]
    ))
    read_source_functions_seen = sorted(set(
        [e["gate_read_source_function"] for e in gate_reads if e.get("gate_read_source_function")]
    ))

    collapse_classes = Counter(
        v["collapse_class"] for v in per_bucket.values() if v.get("collapse_class")
    )
    boundary_classification = "PARTIAL_PROOF_MORE_TRACE_NEEDED"
    if collapse_classes.get("MATERIALIZATION_BOUNDARY_COLLAPSE_CONFIRMED"):
        boundary_classification = "MATERIALIZATION_BOUNDARY_COLLAPSE_CONFIRMED"
    elif collapse_classes.get("STALE_SNAPSHOT_COLLAPSE_CONFIRMED"):
        boundary_classification = "STALE_SNAPSHOT_COLLAPSE_CONFIRMED"
    no_read_cause_counts = Counter(
        v["no_read_cause_verdict"] for v in per_bucket.values() if v.get("no_read_cause_verdict")
    )
    no_read_cause_classification = "PARTIAL_PROOF_MORE_TRACE_NEEDED"
    if len(no_read_cause_counts) == 1 and buckets_promoted > 0:
        no_read_cause_classification = next(iter(no_read_cause_counts))

    def _corr_key(raw_corr, canonical_key, runtime_seq):
        corr = str(raw_corr or "").strip()
        if corr:
            return corr
        return f"fallback::{str(canonical_key or 'UNKNOWN')}::{int(runtime_seq or 0)}"

    correlation_diagnostics = {}
    for event in promotions:
        corr = _corr_key(event.get("correlation_id"), event.get("canonical_key"), event.get("runtime_seq"))
        diag = correlation_diagnostics.setdefault(
            corr,
            {
                "correlation_id": corr,
                "canonical_key": event.get("canonical_key"),
                "written": False,
                "armed": False,
                "invoked": False,
                "emit_attempted": False,
                "persisted": False,
                "observed": False,
                "exception_swallowed": False,
                "final_verdict": None,
            },
        )
        _ensure_corr_diag_fields(diag)
        diag["written"] = True
    for bucket in buckets.values():
        for trace in bucket.get("explicit_post_promotion_eval_traces", []):
            corr = _corr_key(trace.get("correlation_id"), trace.get("canonical_key"), trace.get("runtime_seq"))
            diag = correlation_diagnostics.setdefault(
                corr,
                {
                    "correlation_id": corr,
                    "canonical_key": trace.get("canonical_key"),
                    "written": False,
                    "armed": False,
                    "invoked": False,
                    "emit_attempted": False,
                    "persisted": False,
                    "observed": False,
                    "exception_swallowed": False,
                    "final_verdict": None,
                },
            )
            _ensure_corr_diag_fields(diag)
            trace_name = str(trace.get("trace_event_name") or "")
            if trace_name == "canonical_explicit_post_promotion_eval_armed":
                diag["armed"] = True
            if trace_name == "canonical_explicit_post_promotion_eval_invoked":
                diag["invoked"] = True
            if trace_name == "handoff_parent_enqueue_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_enqueue_done":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_signal_sent":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["handoff_parent_signal_sent"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_observed":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_dequeue_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["handoff_child_mailbox_dequeue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "post_promotion_force_cycle_pre_drain_enter":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_enter"] = True
                diag["post_promotion_forced_cycle_verdict"] = "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
                if trace.get("canonical_key") is not None:
                    diag["canonical_key"] = trace.get("canonical_key")
                if trace.get("correlation_id") is not None:
                    diag["correlation_id"] = trace.get("correlation_id")
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("promotion_runtime_seq") is not None:
                    diag["promotion_runtime_seq"] = trace.get("promotion_runtime_seq")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_handoff_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                if trace.get("observation_window_enabled") is not None:
                    diag["post_promotion_force_cycle_handoff_observation_window_enabled"] = bool(trace.get("observation_window_enabled"))
                if trace.get("observation_window_active") is not None:
                    diag["post_promotion_force_cycle_handoff_observation_window_active"] = bool(trace.get("observation_window_active"))
                if trace.get("post_promotion_execution_lock") is not None:
                    diag["post_promotion_force_cycle_handoff_post_promotion_execution_lock"] = bool(trace.get("post_promotion_execution_lock"))
                if trace.get("already_seen_forced_cycle_marker") is not None:
                    diag["post_promotion_force_cycle_handoff_already_seen_forced_cycle_marker"] = bool(trace.get("already_seen_forced_cycle_marker"))
                if trace.get("request_enqueue_attempted") is not None:
                    diag["post_promotion_force_cycle_handoff_request_enqueue_attempted"] = bool(trace.get("request_enqueue_attempted"))
                if trace.get("request_enqueue_completed") is not None:
                    diag["post_promotion_force_cycle_handoff_request_enqueue_completed"] = bool(trace.get("request_enqueue_completed"))
            if trace_name == "post_promotion_force_cycle_handoff_accept":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_accept"] = True
                if trace.get("accept_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_accept_reason"] = trace.get("accept_reason")
                if trace.get("request_enqueue_completed") is not None:
                    diag["post_promotion_force_cycle_handoff_request_enqueue_completed"] = bool(trace.get("request_enqueue_completed"))
            if trace_name == "post_promotion_force_cycle_handoff_reject":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_reject"] = True
                if trace.get("reject_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_reject_reason"] = trace.get("reject_reason")
                if trace.get("skip_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_reject_reason"] = trace.get("skip_reason")
            if trace_name == "post_promotion_force_cycle_handoff_reject_reason":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_reject"] = True
                if trace.get("reject_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_reject_reason"] = trace.get("reject_reason")
                if trace.get("skip_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_reject_reason"] = trace.get("skip_reason")
            if trace_name == "post_promotion_force_cycle_handoff_call_start":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_accept"] = True
                diag["post_promotion_force_cycle_handoff_call_start"] = True
            if trace_name == "post_promotion_force_cycle_handoff_call_done":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_accept"] = True
                diag["post_promotion_force_cycle_handoff_call_start"] = True
                diag["post_promotion_force_cycle_handoff_call_done"] = True
            if trace_name == "handoff_decision_emit_prelude_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_decision_emit_prelude_enter"] = True
                if trace.get("handoff_pre_decision_return_site_id") is not None:
                    diag["handoff_pre_decision_return_site_id"] = trace.get("handoff_pre_decision_return_site_id")
                if trace.get("handoff_pre_decision_return_reason") is not None:
                    diag["handoff_pre_decision_return_reason"] = trace.get("handoff_pre_decision_return_reason")
            if trace_name == "handoff_decision_emit_prelude_exit":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_decision_emit_prelude_exit"] = True
            if trace_name == "handoff_decision_emit_call_done":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_decision_emit_call_done"] = True
            if trace_name == "handoff_parent_enqueue_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_enqueue_done":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_signal_sent":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["handoff_parent_signal_sent"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_observed":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_dequeue_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["handoff_child_mailbox_dequeue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_dispatch_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_dispatch_enter"] = True
                if trace.get("dispatch_site_id") is not None:
                    diag["dispatch_site_id"] = trace.get("dispatch_site_id")
                if trace.get("processing_stage") is not None:
                    diag["processing_stage"] = trace.get("processing_stage")
            if trace_name == "handoff_child_dispatch_accept_for_processing":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_dispatch_enter"] = True
                diag["handoff_child_dispatch_accept_for_processing"] = True
                if trace.get("dispatch_site_id") is not None:
                    diag["dispatch_site_id"] = trace.get("dispatch_site_id")
                if trace.get("processing_stage") is not None:
                    diag["processing_stage"] = trace.get("processing_stage")
            if trace_name == "handoff_child_loop_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_dispatch_enter"] = True
                diag["handoff_child_dispatch_accept_for_processing"] = True
                diag["handoff_child_loop_enter"] = True
                if trace.get("dispatch_site_id") is not None:
                    diag["dispatch_site_id"] = trace.get("dispatch_site_id")
                if trace.get("processing_stage") is not None:
                    diag["processing_stage"] = trace.get("processing_stage")
            if trace_name == "handoff_child_callback_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_dispatch_enter"] = True
                diag["handoff_child_dispatch_accept_for_processing"] = True
                diag["handoff_child_loop_enter"] = True
                diag["handoff_child_callback_enter"] = True
                if trace.get("dispatch_site_id") is not None:
                    diag["dispatch_site_id"] = trace.get("dispatch_site_id")
                if trace.get("callback_site_id") is not None:
                    diag["callback_site_id"] = trace.get("callback_site_id")
                if trace.get("processing_stage") is not None:
                    diag["processing_stage"] = trace.get("processing_stage")
            if trace_name == "post_promotion_force_cycle_handoff_decision":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_decision"] = trace.get("handoff_decision")
                if trace.get("handoff_decision_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_decision_reason"] = trace.get("handoff_decision_reason")
                if trace.get("handoff_decision_site_id") is not None:
                    diag["post_promotion_force_cycle_handoff_decision_site_id"] = trace.get("handoff_decision_site_id")
                if trace.get("request_enqueue_attempted") is not None:
                    diag["post_promotion_force_cycle_handoff_request_enqueue_attempted"] = bool(trace.get("request_enqueue_attempted"))
                if trace.get("request_enqueue_completed") is not None:
                    diag["post_promotion_force_cycle_handoff_request_enqueue_completed"] = bool(trace.get("request_enqueue_completed"))
            if trace_name == "post_promotion_force_cycle_handoff_enter":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_NOT_REACHED"
            if trace_name == "post_promotion_force_cycle_handoff_accept":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED"
            if trace_name == "post_promotion_force_cycle_handoff_reject":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED"
            if trace_name == "post_promotion_force_cycle_handoff_reject_reason":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED"
            if trace_name == "post_promotion_force_cycle_handoff_call_start":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED"
            if trace_name == "post_promotion_force_cycle_handoff_call_done":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED"
            if trace_name == "handoff_decision_emit_prelude_enter":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_DECISION_EMIT_PRELUDE_ENTERED"
            if trace_name == "handoff_decision_emit_prelude_exit":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_DECISION_EMIT_PRELUDE_EXITED"
            if trace_name == "handoff_decision_emit_call_done":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_DECISION_EMIT_SITE_REACHED"
            if trace_name == "handoff_child_callback_enter":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_CHILD_CALLBACK_ENTERED"
            if trace_name == "handoff_child_loop_enter":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_CHILD_LOOP_ENTERED"
            if trace_name == "handoff_child_dispatch_accept_for_processing":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_CHILD_ACCEPTED_FOR_PROCESSING"
            if trace_name == "handoff_child_dispatch_enter":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_CHILD_DISPATCH_ENTERED"
            if trace_name == "handoff_pre_decision_return":
                diag["handoff_pre_decision_return_site_id"] = trace.get("handoff_pre_decision_return_site_id")
                diag["handoff_pre_decision_return_reason"] = trace.get("handoff_pre_decision_return_reason")
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_PRE_DECISION_RETURN_SITE_IDENTIFIED"
            if trace_name == "post_promotion_force_cycle_handoff_decision":
                decision = str(trace.get("handoff_decision") or "").strip()
                if decision:
                    diag["post_promotion_force_cycle_handoff_verdict"] = decision
            if trace_name == "canonical_explicit_post_promotion_invoke_trace":
                diag["post_promotion_eval_arm_consumed"] = True
                diag["evaluated_path_enter_after_promotion"] = True
                if trace.get("evaluated_path_enter_after_forced_cycle") is not None:
                    diag["evaluated_path_enter_after_forced_cycle"] = bool(
                        trace.get("evaluated_path_enter_after_forced_cycle")
                    )
                if trace.get("evaluated_path_skip_reason") is not None:
                    diag["evaluated_path_skip_reason"] = trace.get("evaluated_path_skip_reason")
                if trace.get("evaluated_path_exit_reason") is not None:
                    diag["evaluated_path_exit_reason"] = trace.get("evaluated_path_exit_reason")
            if trace_name == "canonical_gate_read_branch_selector_enter":
                diag["canonical_gate_read_branch_selector_enter"] = True
            if trace_name == "canonical_gate_read_branch_selector_inputs":
                diag["canonical_gate_read_branch_selector_inputs"] = True
            if trace_name == "canonical_gate_read_branch_selector_selected_path":
                diag["canonical_gate_read_branch_selector_enter"] = True
                diag["canonical_gate_read_branch_selector_inputs"] = True
                if trace.get("canonical_gate_read_branch_selector_selected_path") is not None:
                    diag["canonical_gate_read_branch_selector_selected_path"] = trace.get("canonical_gate_read_branch_selector_selected_path")
            if trace_name == "canonical_gate_read_branch_selector_skip":
                diag["canonical_gate_read_branch_selector_skip"] = True
                if trace.get("canonical_gate_read_branch_selector_skip_reason") is not None:
                    diag["canonical_gate_read_branch_selector_skip_reason"] = trace.get("canonical_gate_read_branch_selector_skip_reason")
            if trace_name == "canonical_gate_read_emit_candidate":
                diag["canonical_gate_read_emit_candidate"] = True
            if trace_name == "canonical_gate_read_emit_guard_considered":
                diag["canonical_gate_read_emit_guard_considered"] = True
            if trace_name == "canonical_gate_read_emit_guard_blocked":
                diag["canonical_gate_read_emit_guard_blocked"] = True
            if trace_name == "canonical_gate_read_emit_payload_built":
                diag["canonical_gate_read_emit_payload_built"] = True
            if trace_name == "canonical_gate_read_emit_attempt":
                diag["canonical_gate_read_emit_attempt"] = True
            if trace_name == "canonical_gate_read_emit_done":
                diag["canonical_gate_read_emit_done"] = True
            diag["post_invoke_emit_path_enter"] = bool(
                diag["post_invoke_emit_path_enter"] or trace.get("post_invoke_emit_path_enter")
            )
            diag["post_invoke_emit_guard_considered"] = bool(
                diag["post_invoke_emit_guard_considered"] or trace.get("post_invoke_emit_guard_considered")
            )
            diag["post_invoke_emit_guard_allowed"] = bool(
                diag["post_invoke_emit_guard_allowed"] or trace.get("post_invoke_emit_guard_allowed")
            )
            if trace.get("post_invoke_emit_guard_reason") is not None:
                diag["post_invoke_emit_guard_reason"] = trace.get("post_invoke_emit_guard_reason")
            diag["post_invoke_emit_early_return"] = bool(
                diag["post_invoke_emit_early_return"] or trace.get("post_invoke_emit_early_return")
            )
            if trace.get("post_invoke_emit_early_return_reason") is not None:
                diag["post_invoke_emit_early_return_reason"] = trace.get("post_invoke_emit_early_return_reason")
            diag["post_invoke_emit_attempt_reached"] = bool(
                diag["post_invoke_emit_attempt_reached"] or trace.get("post_invoke_emit_attempt_reached")
            )
            if trace.get("post_invoke_emit_micro_stage") is not None:
                diag["post_invoke_emit_micro_stage"] = trace.get("post_invoke_emit_micro_stage")
            diag["post_invoke_emit_hidden_branch_taken"] = bool(
                diag["post_invoke_emit_hidden_branch_taken"] or trace.get("post_invoke_emit_hidden_branch_taken")
            )
            if trace.get("post_invoke_emit_hidden_branch_reason") is not None:
                diag["post_invoke_emit_hidden_branch_reason"] = trace.get("post_invoke_emit_hidden_branch_reason")
            diag["post_invoke_emit_local_return"] = bool(
                diag["post_invoke_emit_local_return"] or trace.get("post_invoke_emit_local_return")
            )
            if trace.get("post_invoke_emit_local_return_reason") is not None:
                diag["post_invoke_emit_local_return_reason"] = trace.get("post_invoke_emit_local_return_reason")
            if trace.get("post_invoke_emit_exception_class") is not None:
                diag["post_invoke_emit_exception_class"] = trace.get("post_invoke_emit_exception_class")
            if trace.get("post_invoke_emit_exception_message") is not None:
                diag["post_invoke_emit_exception_message"] = trace.get("post_invoke_emit_exception_message")
            diag["post_invoke_emit_attempt_call_enter"] = bool(
                diag["post_invoke_emit_attempt_call_enter"] or trace.get("post_invoke_emit_attempt_call_enter")
            )
            if trace.get("canonical_gate_read_emit_guard_reason") is not None:
                diag["canonical_gate_read_emit_guard_reason"] = trace.get("canonical_gate_read_emit_guard_reason")
            if trace.get("evaluation_phase") is not None:
                diag["evaluation_phase"] = trace.get("evaluation_phase")
            if trace.get("is_explicit_post_promotion_eval") is not None:
                diag["is_explicit_post_promotion_eval"] = bool(trace.get("is_explicit_post_promotion_eval"))
            if trace.get("skip_reason") is not None:
                diag["skip_reason"] = trace.get("skip_reason")
        for trace in bucket.get("forced_cycle_traces", []):
            corr = _corr_key(trace.get("correlation_id"), trace.get("canonical_key"), trace.get("runtime_seq"))
            diag = correlation_diagnostics.setdefault(
                corr,
                {
                    "correlation_id": corr,
                    "canonical_key": trace.get("canonical_key"),
                    "written": False,
                    "armed": False,
                    "invoked": False,
                    "emit_attempted": False,
                    "persisted": False,
                    "observed": False,
                    "exception_swallowed": False,
                    "final_verdict": None,
                },
            )
            _ensure_corr_diag_fields(diag)
            trace_name = str(trace.get("trace_event_name") or "")
            if trace_name == "post_promotion_force_cycle_request":
                diag["forced_cycle_requested"] = True
            if trace_name == "forced_cycle_requested":
                diag["forced_cycle_requested"] = True
            if trace_name == "post_promotion_force_cycle_scheduler_tick_enter":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_tick_enter"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
                if trace.get("forced_cycle_request_runtime_seq") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("forced_cycle_request_runtime_seq")
            if trace_name == "post_promotion_force_cycle_scheduler_tick_exit":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_tick_exit"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
                if trace.get("forced_cycle_request_runtime_seq") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("forced_cycle_request_runtime_seq")
            if trace_name == "post_promotion_force_cycle_request_scan_enter":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_enter"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_request_scan_result":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_result"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_request_scan_empty":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_empty"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_request_scan_nonempty":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_nonempty"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_request_scan_candidate_seen":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_request_scan_candidate_seen"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("forced_cycle_request_scan_empty_reason") is not None:
                    diag["forced_cycle_request_scan_empty_reason"] = trace.get("forced_cycle_request_scan_empty_reason")
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
            if trace_name == "post_promotion_force_cycle_request_scan_candidate_reject":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_request_scan_candidate_seen"] = True
                diag["forced_cycle_request_scan_candidate_reject"] = True
                if trace.get("forced_cycle_request_scan_candidate_reject_reason") is not None:
                    diag["forced_cycle_request_scan_candidate_reject_reason"] = trace.get("forced_cycle_request_scan_candidate_reject_reason")
                if trace.get("forced_cycle_request_scan_empty_reason") is not None:
                    diag["forced_cycle_request_scan_empty_reason"] = trace.get("forced_cycle_request_scan_empty_reason")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
            if trace_name == "post_promotion_force_cycle_request_scan_empty_reason":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_request_scan_empty"] = True
                diag["forced_cycle_request_scan_candidate_seen"] = True
                diag["forced_cycle_request_scan_candidate_reject"] = True
                if trace.get("forced_cycle_request_scan_empty_reason") is not None:
                    diag["forced_cycle_request_scan_empty_reason"] = trace.get("forced_cycle_request_scan_empty_reason")
                    diag["forced_cycle_request_scan_candidate_reject_reason"] = trace.get("forced_cycle_request_scan_empty_reason")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
            if trace_name == "forced_cycle_enter":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_started"] = True
                diag["forced_cycle_enter"] = True
                if trace.get("forced_cycle_runtime_seq") is not None:
                    diag["forced_cycle_runtime_seq"] = trace.get("forced_cycle_runtime_seq")
                if trace.get("evaluation_phase") is not None:
                    diag["evaluation_phase"] = trace.get("evaluation_phase")
                if trace.get("is_forced_post_promotion_cycle") is not None:
                    diag["is_forced_post_promotion_cycle"] = bool(trace.get("is_forced_post_promotion_cycle"))
            if trace_name == "forced_cycle_started":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_started"] = True
            if trace_name == "post_promotion_force_cycle_scheduler_tick_enter":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_tick_enter"] = True
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
                if trace.get("forced_cycle_request_runtime_seq") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("forced_cycle_request_runtime_seq")
            if trace_name == "post_promotion_force_cycle_scheduler_tick_exit":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_tick_exit"] = True
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
                if trace.get("forced_cycle_request_runtime_seq") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("forced_cycle_request_runtime_seq")
            if trace_name == "post_promotion_force_cycle_scheduler_gate_enter":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_gate_enter"] = True
                if trace.get("gate_reason") is not None:
                    diag["scheduler_gate_reason"] = trace.get("gate_reason")
                if trace.get("observation_window_state") is not None:
                    diag["observation_window_state"] = trace.get("observation_window_state")
                if trace.get("post_promotion_execution_lock") is not None:
                    diag["post_promotion_execution_lock"] = bool(trace.get("post_promotion_execution_lock"))
                if trace.get("has_pending_forced_cycle_request") is not None:
                    diag["has_pending_forced_cycle_request"] = bool(trace.get("has_pending_forced_cycle_request"))
                if trace.get("scheduler_tick_eligible") is not None:
                    diag["scheduler_tick_eligible"] = bool(trace.get("scheduler_tick_eligible"))
            if trace_name == "post_promotion_force_cycle_scheduler_gate_result":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_gate_result"] = trace.get("gate_reason")
                if trace.get("observation_window_state") is not None:
                    diag["observation_window_state"] = trace.get("observation_window_state")
                if trace.get("post_promotion_execution_lock") is not None:
                    diag["post_promotion_execution_lock"] = bool(trace.get("post_promotion_execution_lock"))
                if trace.get("has_pending_forced_cycle_request") is not None:
                    diag["has_pending_forced_cycle_request"] = bool(trace.get("has_pending_forced_cycle_request"))
                if trace.get("scheduler_tick_eligible") is not None:
                    diag["scheduler_tick_eligible"] = bool(trace.get("scheduler_tick_eligible"))
            if trace_name == "post_promotion_force_cycle_scheduler_gate_blocked":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_gate_blocked"] = True
                if trace.get("gate_reason") is not None:
                    diag["scheduler_gate_reason"] = trace.get("gate_reason")
                if trace.get("observation_window_state") is not None:
                    diag["observation_window_state"] = trace.get("observation_window_state")
                if trace.get("post_promotion_execution_lock") is not None:
                    diag["post_promotion_execution_lock"] = bool(trace.get("post_promotion_execution_lock"))
                if trace.get("has_pending_forced_cycle_request") is not None:
                    diag["has_pending_forced_cycle_request"] = bool(trace.get("has_pending_forced_cycle_request"))
                if trace.get("scheduler_tick_eligible") is not None:
                    diag["scheduler_tick_eligible"] = bool(trace.get("scheduler_tick_eligible"))
            if trace_name == "post_promotion_force_cycle_scheduler_gate_allowed":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_gate_allowed"] = True
                if trace.get("gate_reason") is not None:
                    diag["scheduler_gate_reason"] = trace.get("gate_reason")
                if trace.get("observation_window_state") is not None:
                    diag["observation_window_state"] = trace.get("observation_window_state")
                if trace.get("post_promotion_execution_lock") is not None:
                    diag["post_promotion_execution_lock"] = bool(trace.get("post_promotion_execution_lock"))
                if trace.get("has_pending_forced_cycle_request") is not None:
                    diag["has_pending_forced_cycle_request"] = bool(trace.get("has_pending_forced_cycle_request"))
                if trace.get("scheduler_tick_eligible") is not None:
                    diag["scheduler_tick_eligible"] = bool(trace.get("scheduler_tick_eligible"))
            if trace_name == "post_promotion_force_cycle_scheduler_caller_enter":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_caller_enter"] = True
                if trace.get("caller_reason") is not None:
                    diag["caller_reason"] = trace.get("caller_reason")
                if trace.get("post_promotion_execution_lock") is not None:
                    diag["post_promotion_execution_lock"] = bool(trace.get("post_promotion_execution_lock"))
                if trace.get("has_pending_forced_cycle_request") is not None:
                    diag["has_pending_forced_cycle_request"] = bool(trace.get("has_pending_forced_cycle_request"))
            if trace_name == "post_promotion_force_cycle_scheduler_caller_exit":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_caller_exit"] = True
                if trace.get("caller_reason") is not None:
                    diag["caller_reason"] = trace.get("caller_reason")
                if trace.get("post_promotion_execution_lock") is not None:
                    diag["post_promotion_execution_lock"] = bool(trace.get("post_promotion_execution_lock"))
                if trace.get("has_pending_forced_cycle_request") is not None:
                    diag["has_pending_forced_cycle_request"] = bool(trace.get("has_pending_forced_cycle_request"))
            if trace_name == "post_promotion_force_cycle_request_scan_enter":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_enter"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_request_scan_result":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_result"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_request_scan_empty":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_empty"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_request_scan_nonempty":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_nonempty"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_request_scan_candidate_seen":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_request_scan_candidate_seen"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("forced_cycle_request_scan_empty_reason") is not None:
                    diag["forced_cycle_request_scan_empty_reason"] = trace.get("forced_cycle_request_scan_empty_reason")
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
            if trace_name == "post_promotion_force_cycle_request_scan_candidate_reject":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_request_scan_candidate_seen"] = True
                diag["forced_cycle_request_scan_candidate_reject"] = True
                if trace.get("forced_cycle_request_scan_candidate_reject_reason") is not None:
                    diag["forced_cycle_request_scan_candidate_reject_reason"] = trace.get("forced_cycle_request_scan_candidate_reject_reason")
                if trace.get("forced_cycle_request_scan_empty_reason") is not None:
                    diag["forced_cycle_request_scan_empty_reason"] = trace.get("forced_cycle_request_scan_empty_reason")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
            if trace_name == "post_promotion_force_cycle_request_scan_empty_reason":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_request_scan_empty"] = True
                diag["forced_cycle_request_scan_candidate_seen"] = True
                diag["forced_cycle_request_scan_candidate_reject"] = True
                if trace.get("forced_cycle_request_scan_empty_reason") is not None:
                    diag["forced_cycle_request_scan_empty_reason"] = trace.get("forced_cycle_request_scan_empty_reason")
                    diag["forced_cycle_request_scan_candidate_reject_reason"] = trace.get("forced_cycle_request_scan_empty_reason")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
            if trace_name == "post_promotion_force_cycle_pending_check_enter":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pending_check_enter"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_pending_check_result":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pending_check_result"] = trace.get("visibility_reason")
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_pending_visible":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pending_visible"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_pending_not_visible":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pending_not_visible"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_candidate":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("pre_drain_reject_reason") is not None:
                    diag["forced_cycle_pre_drain_reject_reason"] = trace.get("pre_drain_reject_reason")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_reject":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_reject"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("pre_drain_reject_reason") is not None:
                    diag["forced_cycle_pre_drain_reject_reason"] = trace.get("pre_drain_reject_reason")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_reject_reason":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_reject"] = True
                if trace.get("pre_drain_reject_reason") is not None:
                    diag["forced_cycle_pre_drain_reject_reason"] = trace.get("pre_drain_reject_reason")
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_enter":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_enter"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_skip":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_reject"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("pre_drain_skip_reason") is not None:
                    diag["forced_cycle_pre_drain_reject_reason"] = trace.get("pre_drain_skip_reason")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_return":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_return"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("pre_drain_return_reason") is not None:
                    diag["forced_cycle_pre_drain_return_reason"] = trace.get("pre_drain_return_reason")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_drain_skipped":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_drain_skipped"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("skip_reason") is not None:
                    diag["skip_reason"] = trace.get("skip_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_drain_enter":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_drain_enter"] = True
                if trace.get("forced_cycle_drain_runtime_seq") is not None:
                    diag["forced_cycle_drain_runtime_seq"] = trace.get("forced_cycle_drain_runtime_seq")
                if trace.get("transfer_site_id") is not None:
                    diag["transfer_site_id"] = trace.get("transfer_site_id")
                if trace.get("mailbox_stage") is not None:
                    diag["mailbox_stage"] = trace.get("mailbox_stage")
                if trace.get("handoff_transport_state") is not None:
                    diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "post_promotion_force_cycle_drain_exit":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_drain_exit"] = True
                if trace.get("forced_cycle_drain_runtime_seq") is not None:
                    diag["forced_cycle_drain_runtime_seq"] = trace.get("forced_cycle_drain_runtime_seq")
            if trace_name == "handoff_parent_enqueue_enter":
                diag["forced_cycle_requested"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_enqueue_done":
                diag["forced_cycle_requested"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_signal_sent":
                diag["forced_cycle_requested"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["handoff_parent_signal_sent"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_observed":
                diag["forced_cycle_requested"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_dequeue_enter":
                diag["forced_cycle_requested"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["handoff_child_mailbox_dequeue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "forced_cycle_completed":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_started"] = True
                diag["forced_cycle_enter"] = True
                diag["forced_cycle_completed"] = True
                if trace.get("candidate_reached") is not None:
                    diag["forced_cycle_candidate_reached"] = bool(trace.get("candidate_reached"))
                if trace.get("emit_attempt_reached") is not None:
                    diag["forced_cycle_emit_attempt_reached"] = bool(trace.get("emit_attempt_reached"))
                if trace.get("emit_done_reached") is not None:
                    diag["forced_cycle_emit_done_reached"] = bool(trace.get("emit_done_reached"))
                if trace.get("forced_cycle_exit_reason") is not None:
                    diag["forced_cycle_exit_reason"] = trace.get("forced_cycle_exit_reason")
                if trace.get("forced_cycle_result_classification") is not None:
                    diag["forced_cycle_result_classification"] = trace.get("forced_cycle_result_classification")
                if trace.get("forced_cycle_eval_pre_selector_return_site") is not None:
                    diag["forced_cycle_eval_pre_selector_return_site"] = bool(trace.get("forced_cycle_eval_pre_selector_return_site"))
                if trace.get("forced_cycle_eval_pre_selector_return_site_id") is not None:
                    diag["forced_cycle_eval_pre_selector_return_site_id"] = trace.get("forced_cycle_eval_pre_selector_return_site_id")
                if trace.get("forced_cycle_eval_pre_selector_return_reason") is not None:
                    diag["forced_cycle_eval_pre_selector_return_reason"] = trace.get("forced_cycle_eval_pre_selector_return_reason")
                if trace.get("forced_cycle_eval_pre_selector_has_selector_context") is not None:
                    diag["forced_cycle_eval_pre_selector_has_selector_context"] = bool(trace.get("forced_cycle_eval_pre_selector_has_selector_context"))
                if trace.get("forced_cycle_eval_pre_selector_has_candidate_context") is not None:
                    diag["forced_cycle_eval_pre_selector_has_candidate_context"] = bool(trace.get("forced_cycle_eval_pre_selector_has_candidate_context"))
                if trace.get("forced_cycle_eval_pre_selector_helper_result_type") is not None:
                    diag["forced_cycle_eval_pre_selector_helper_result_type"] = trace.get("forced_cycle_eval_pre_selector_helper_result_type")
                if trace.get("forced_cycle_eval_pre_selector_callable_name") is not None:
                    diag["forced_cycle_eval_pre_selector_callable_name"] = trace.get("forced_cycle_eval_pre_selector_callable_name")
                if trace.get("forced_cycle_eval_pre_selector_callable_module") is not None:
                    diag["forced_cycle_eval_pre_selector_callable_module"] = trace.get("forced_cycle_eval_pre_selector_callable_module")
                if trace.get("forced_cycle_eval_pre_selector_args_summary") is not None:
                    diag["forced_cycle_eval_pre_selector_args_summary"] = trace.get("forced_cycle_eval_pre_selector_args_summary")
                if trace.get("forced_cycle_eval_pre_selector_expected_result_type") is not None:
                    diag["forced_cycle_eval_pre_selector_expected_result_type"] = trace.get("forced_cycle_eval_pre_selector_expected_result_type")
                if trace.get("forced_cycle_eval_pre_selector_required_fields_expected") is not None:
                    diag["forced_cycle_eval_pre_selector_required_fields_expected"] = trace.get("forced_cycle_eval_pre_selector_required_fields_expected")
                if trace.get("forced_cycle_eval_pre_selector_wrapper_expected_fields") is not None:
                    diag["forced_cycle_eval_pre_selector_wrapper_expected_fields"] = trace.get("forced_cycle_eval_pre_selector_wrapper_expected_fields")
                if trace.get("forced_cycle_eval_pre_selector_actual_return_type") is not None:
                    diag["forced_cycle_eval_pre_selector_actual_return_type"] = trace.get("forced_cycle_eval_pre_selector_actual_return_type")
                if trace.get("forced_cycle_eval_pre_selector_actual_return_is_none") is not None:
                    diag["forced_cycle_eval_pre_selector_actual_return_is_none"] = bool(trace.get("forced_cycle_eval_pre_selector_actual_return_is_none"))
                if trace.get("forced_cycle_eval_pre_selector_safe_return_repr") is not None:
                    diag["forced_cycle_eval_pre_selector_safe_return_repr"] = trace.get("forced_cycle_eval_pre_selector_safe_return_repr")
                if trace.get("forced_cycle_eval_pre_selector_contract_failure_reason") is not None:
                    diag["forced_cycle_eval_pre_selector_contract_failure_reason"] = trace.get("forced_cycle_eval_pre_selector_contract_failure_reason")
            if trace_name in {
                "forced_cycle_eval_entry",
                "forced_cycle_eval_pre_router",
                "forced_cycle_eval_post_router",
                "forced_cycle_eval_pre_entry_edge_check",
                "forced_cycle_eval_post_entry_edge_check",
                "forced_cycle_eval_bypass",
                "forced_cycle_eval_pre_selector_return_site",
            }:
                diag["forced_cycle_requested"] = True
                if trace_name == "forced_cycle_eval_entry":
                    diag["forced_cycle_eval_entry"] = True
                if trace_name == "forced_cycle_eval_pre_router":
                    diag["forced_cycle_eval_pre_router"] = True
                if trace_name == "forced_cycle_eval_post_router":
                    diag["forced_cycle_eval_post_router"] = True
                if trace_name == "forced_cycle_eval_pre_entry_edge_check":
                    diag["forced_cycle_eval_pre_entry_edge_check"] = True
                if trace_name == "forced_cycle_eval_post_entry_edge_check":
                    diag["forced_cycle_eval_post_entry_edge_check"] = True
                if trace_name == "forced_cycle_eval_pre_selector_return_site":
                    diag["forced_cycle_eval_pre_selector_return_site"] = True
                    if trace.get("return_site_id") is not None:
                        diag["forced_cycle_eval_pre_selector_return_site_id"] = trace.get("return_site_id")
                    if trace.get("return_reason") is not None:
                        diag["forced_cycle_eval_pre_selector_return_reason"] = trace.get("return_reason")
                    if trace.get("has_selector_context") is not None:
                        diag["forced_cycle_eval_pre_selector_has_selector_context"] = bool(trace.get("has_selector_context"))
                    if trace.get("has_candidate_context") is not None:
                        diag["forced_cycle_eval_pre_selector_has_candidate_context"] = bool(trace.get("has_candidate_context"))
                    if trace.get("helper_result_type") is not None:
                        diag["forced_cycle_eval_pre_selector_helper_result_type"] = trace.get("helper_result_type")
                    if trace.get("callable_name") is not None:
                        diag["forced_cycle_eval_pre_selector_callable_name"] = trace.get("callable_name")
                    if trace.get("callable_module") is not None:
                        diag["forced_cycle_eval_pre_selector_callable_module"] = trace.get("callable_module")
                    if trace.get("args_summary") is not None:
                        diag["forced_cycle_eval_pre_selector_args_summary"] = trace.get("args_summary")
                    if trace.get("expected_result_type") is not None:
                        diag["forced_cycle_eval_pre_selector_expected_result_type"] = trace.get("expected_result_type")
                    if trace.get("required_fields_expected") is not None:
                        diag["forced_cycle_eval_pre_selector_required_fields_expected"] = trace.get("required_fields_expected")
                    if trace.get("wrapper_expected_fields") is not None:
                        diag["forced_cycle_eval_pre_selector_wrapper_expected_fields"] = trace.get("wrapper_expected_fields")
                    if trace.get("actual_return_type") is not None:
                        diag["forced_cycle_eval_pre_selector_actual_return_type"] = trace.get("actual_return_type")
                    if trace.get("actual_return_is_none") is not None:
                        diag["forced_cycle_eval_pre_selector_actual_return_is_none"] = bool(trace.get("actual_return_is_none"))
                    if trace.get("safe_return_repr") is not None:
                        diag["forced_cycle_eval_pre_selector_safe_return_repr"] = trace.get("safe_return_repr")
                    if trace.get("contract_failure_reason") is not None:
                        diag["forced_cycle_eval_pre_selector_contract_failure_reason"] = trace.get("contract_failure_reason")
                if trace.get("forced_cycle_eval_exit_reason") is not None:
                    diag["forced_cycle_eval_exit_reason"] = trace.get("forced_cycle_eval_exit_reason")
                if trace.get("forced_cycle_eval_bypass_reason") is not None:
                    diag["forced_cycle_eval_bypass_reason"] = trace.get("forced_cycle_eval_bypass_reason")
            if trace_name == "forced_cycle_failed":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_failed"] = True
                if trace.get("forced_cycle_runtime_seq") is not None:
                    diag["forced_cycle_runtime_seq"] = trace.get("forced_cycle_runtime_seq")
                if trace.get("forced_cycle_exit_reason") is not None:
                    diag["forced_cycle_exit_reason"] = trace.get("forced_cycle_exit_reason")
                if trace.get("forced_cycle_result_classification") is not None:
                    diag["forced_cycle_result_classification"] = trace.get("forced_cycle_result_classification")
                if trace.get("forced_cycle_eval_pre_selector_return_site") is not None:
                    diag["forced_cycle_eval_pre_selector_return_site"] = bool(trace.get("forced_cycle_eval_pre_selector_return_site"))
                if trace.get("forced_cycle_eval_pre_selector_return_site_id") is not None:
                    diag["forced_cycle_eval_pre_selector_return_site_id"] = trace.get("forced_cycle_eval_pre_selector_return_site_id")
                if trace.get("forced_cycle_eval_pre_selector_return_reason") is not None:
                    diag["forced_cycle_eval_pre_selector_return_reason"] = trace.get("forced_cycle_eval_pre_selector_return_reason")
                if trace.get("forced_cycle_eval_pre_selector_has_selector_context") is not None:
                    diag["forced_cycle_eval_pre_selector_has_selector_context"] = bool(trace.get("forced_cycle_eval_pre_selector_has_selector_context"))
                if trace.get("forced_cycle_eval_pre_selector_has_candidate_context") is not None:
                    diag["forced_cycle_eval_pre_selector_has_candidate_context"] = bool(trace.get("forced_cycle_eval_pre_selector_has_candidate_context"))
                if trace.get("forced_cycle_eval_pre_selector_helper_result_type") is not None:
                    diag["forced_cycle_eval_pre_selector_helper_result_type"] = trace.get("forced_cycle_eval_pre_selector_helper_result_type")
                if trace.get("forced_cycle_eval_pre_selector_callable_name") is not None:
                    diag["forced_cycle_eval_pre_selector_callable_name"] = trace.get("forced_cycle_eval_pre_selector_callable_name")
                if trace.get("forced_cycle_eval_pre_selector_callable_module") is not None:
                    diag["forced_cycle_eval_pre_selector_callable_module"] = trace.get("forced_cycle_eval_pre_selector_callable_module")
                if trace.get("forced_cycle_eval_pre_selector_args_summary") is not None:
                    diag["forced_cycle_eval_pre_selector_args_summary"] = trace.get("forced_cycle_eval_pre_selector_args_summary")
                if trace.get("forced_cycle_eval_pre_selector_expected_result_type") is not None:
                    diag["forced_cycle_eval_pre_selector_expected_result_type"] = trace.get("forced_cycle_eval_pre_selector_expected_result_type")
                if trace.get("forced_cycle_eval_pre_selector_required_fields_expected") is not None:
                    diag["forced_cycle_eval_pre_selector_required_fields_expected"] = trace.get("forced_cycle_eval_pre_selector_required_fields_expected")
                if trace.get("forced_cycle_eval_pre_selector_wrapper_expected_fields") is not None:
                    diag["forced_cycle_eval_pre_selector_wrapper_expected_fields"] = trace.get("forced_cycle_eval_pre_selector_wrapper_expected_fields")
                if trace.get("forced_cycle_eval_pre_selector_actual_return_type") is not None:
                    diag["forced_cycle_eval_pre_selector_actual_return_type"] = trace.get("forced_cycle_eval_pre_selector_actual_return_type")
                if trace.get("forced_cycle_eval_pre_selector_actual_return_is_none") is not None:
                    diag["forced_cycle_eval_pre_selector_actual_return_is_none"] = bool(trace.get("forced_cycle_eval_pre_selector_actual_return_is_none"))
                if trace.get("forced_cycle_eval_pre_selector_safe_return_repr") is not None:
                    diag["forced_cycle_eval_pre_selector_safe_return_repr"] = trace.get("forced_cycle_eval_pre_selector_safe_return_repr")
                if trace.get("forced_cycle_eval_pre_selector_contract_failure_reason") is not None:
                    diag["forced_cycle_eval_pre_selector_contract_failure_reason"] = trace.get("forced_cycle_eval_pre_selector_contract_failure_reason")
    for event in gate_reads:
        corr = _corr_key(event.get("correlation_id"), event.get("canonical_key"), event.get("runtime_seq"))
        diag = correlation_diagnostics.setdefault(
            corr,
            {
                "correlation_id": corr,
                "canonical_key": event.get("canonical_key"),
                "written": False,
                "armed": False,
                "invoked": False,
                "emit_attempted": False,
                "persisted": False,
                "observed": False,
                "exception_swallowed": False,
                "final_verdict": None,
            },
        )
        _ensure_corr_diag_fields(diag)
        if bool(event.get("override_type") == "explicit_post_promotion_eval"):
            diag["emit_attempted"] = True
        diag["canonical_gate_read_emit_candidate"] = bool(
            diag["canonical_gate_read_emit_candidate"] or event.get("canonical_gate_read_emit_candidate")
        )
        diag["canonical_gate_read_emit_guard_considered"] = bool(
            diag["canonical_gate_read_emit_guard_considered"] or event.get("canonical_gate_read_emit_guard_considered")
        )
        diag["canonical_gate_read_emit_guard_blocked"] = bool(
            diag["canonical_gate_read_emit_guard_blocked"] or event.get("canonical_gate_read_emit_guard_blocked")
        )
        if event.get("canonical_gate_read_emit_guard_reason") is not None:
            diag["canonical_gate_read_emit_guard_reason"] = event.get("canonical_gate_read_emit_guard_reason")
        diag["canonical_gate_read_emit_payload_built"] = bool(
            diag["canonical_gate_read_emit_payload_built"] or event.get("canonical_gate_read_emit_payload_built")
        )
        diag["canonical_gate_read_emit_attempt"] = bool(
            diag["canonical_gate_read_emit_attempt"] or event.get("canonical_gate_read_emit_attempt")
        )
        diag["canonical_gate_read_emit_done"] = bool(
            diag["canonical_gate_read_emit_done"] or event.get("canonical_gate_read_emit_done")
        )
        if event.get("evaluation_phase") is not None:
            diag["evaluation_phase"] = event.get("evaluation_phase")
        if event.get("is_explicit_post_promotion_eval") is not None:
            diag["is_explicit_post_promotion_eval"] = bool(event.get("is_explicit_post_promotion_eval"))
        if event.get("skip_reason") is not None:
            diag["skip_reason"] = event.get("skip_reason")
        diag["post_invoke_emit_path_enter"] = bool(
            diag["post_invoke_emit_path_enter"] or event.get("post_invoke_emit_path_enter")
        )
        diag["post_invoke_emit_guard_considered"] = bool(
            diag["post_invoke_emit_guard_considered"] or event.get("post_invoke_emit_guard_considered")
        )
        diag["post_invoke_emit_guard_allowed"] = bool(
            diag["post_invoke_emit_guard_allowed"] or event.get("post_invoke_emit_guard_allowed")
        )
        if event.get("post_invoke_emit_guard_reason") is not None:
            diag["post_invoke_emit_guard_reason"] = event.get("post_invoke_emit_guard_reason")
        diag["post_invoke_emit_early_return"] = bool(
            diag["post_invoke_emit_early_return"] or event.get("post_invoke_emit_early_return")
        )
        if event.get("post_invoke_emit_early_return_reason") is not None:
            diag["post_invoke_emit_early_return_reason"] = event.get("post_invoke_emit_early_return_reason")
        diag["post_invoke_emit_attempt_reached"] = bool(
            diag["post_invoke_emit_attempt_reached"] or event.get("post_invoke_emit_attempt_reached")
        )
        diag["post_invoke_emit_attempt_call_enter"] = bool(
            diag["post_invoke_emit_attempt_call_enter"] or event.get("post_invoke_emit_attempt_call_enter")
        )
        diag["persisted"] = True
        if int(event.get("read_trade_count") or 0) > 0:
            diag["observed"] = True
    for event in storage_compare_traces:
        corr = _corr_key(event.get("correlation_id"), event.get("canonical_key"), event.get("runtime_seq"))
        diag = correlation_diagnostics.setdefault(
            corr,
            {
                "correlation_id": corr,
                "canonical_key": event.get("canonical_key"),
                "written": False,
                "armed": False,
                "invoked": False,
                "emit_attempted": False,
                "persisted": False,
                "observed": False,
                "exception_swallowed": False,
                "final_verdict": None,
            },
        )
        _ensure_corr_diag_fields(diag)
        diag["written"] = bool(diag["written"] or event.get("stage_written"))
        diag["emit_attempted"] = bool(
            diag["emit_attempted"] or event.get("stage_emit_attempted")
        )
        diag["persisted"] = bool(diag["persisted"] or event.get("stage_persisted"))
        diag["observed"] = bool(diag["observed"] or event.get("stage_observed"))
        diag["exception_swallowed"] = bool(
            diag["exception_swallowed"] or event.get("stage_exception")
        )
        if event.get("final_per_correlation_verdict"):
            diag["final_verdict"] = event.get("final_per_correlation_verdict")
    for event in critical_path_exceptions:
        corr = _corr_key(event.get("correlation_id"), event.get("canonical_key"), event.get("runtime_seq"))
        diag = correlation_diagnostics.setdefault(
            corr,
            {
                "correlation_id": corr,
                "canonical_key": event.get("canonical_key"),
                "written": False,
                "armed": False,
                "invoked": False,
                "emit_attempted": False,
                "persisted": False,
                "observed": False,
                "exception_swallowed": False,
                "final_verdict": None,
            },
        )
        _ensure_corr_diag_fields(diag)
        diag["exception_swallowed"] = True

    for diag in correlation_diagnostics.values():
        if diag["final_verdict"] is None:
            if diag["exception_swallowed"]:
                diag["final_verdict"] = "EXCEPTION_SWALLOWED_IN_CRITICAL_PATH"
            elif diag["written"] and diag["observed"]:
                diag["final_verdict"] = "WRITE_SUCCEEDED_READBACK_CONFIRMED"
            elif diag["written"] and not diag["emit_attempted"]:
                diag["final_verdict"] = "WRITE_SUCCEEDED_BUT_EMIT_NOT_ATTEMPTED"
            elif diag["emit_attempted"] and not diag["persisted"]:
                diag["final_verdict"] = "EMIT_ATTEMPTED_BUT_NOT_PERSISTED"
            elif diag["persisted"] and not diag["observed"]:
                diag["final_verdict"] = "PERSISTED_BUT_NOT_OBSERVED"
            else:
                diag["final_verdict"] = "WRITE_SUCCEEDED_BUT_EMIT_NOT_ATTEMPTED"
        if diag["post_invoke_emit_verdict"] is None:
            if diag["post_invoke_emit_attempt_call_enter"] or diag["post_invoke_emit_attempt_reached"]:
                diag["post_invoke_emit_verdict"] = "EMIT_ATTEMPT_CALL_REACHED"
            elif diag["post_invoke_emit_exception_class"]:
                diag["post_invoke_emit_verdict"] = "EXCEPTION_BEFORE_EMIT_ATTEMPT"
            elif diag["post_invoke_emit_local_return"] or diag["post_invoke_emit_early_return"]:
                diag["post_invoke_emit_verdict"] = "LOCAL_RETURN_BLOCKS_EMIT_ATTEMPT"
            elif diag["post_invoke_emit_hidden_branch_taken"]:
                diag["post_invoke_emit_verdict"] = "HIDDEN_BRANCH_BLOCKS_EMIT_ATTEMPT"
            else:
                diag["post_invoke_emit_verdict"] = "INSUFFICIENT_CODE_EVIDENCE"

    reevaluation_completed = bool(runner_before.get("post_promotion_reeval_completed"))
    reeval_result = str(runner_before.get("post_promotion_reeval_result") or "")
    runner_forced_cycle_result = str(runner_before.get("post_promotion_forced_cycle_result") or "")
    emit_verdict_counts = Counter()
    branch_verdict_counts = Counter()
    handoff_verdict_counts = Counter()
    forced_cycle_verdict_counts = Counter()
    first_missing_emit_stage_after_reeval = "INSUFFICIENT_RUNTIME_EVIDENCE"
    first_missing_branch_stage_after_reeval = "INSUFFICIENT_RUNTIME_EVIDENCE"
    if reevaluation_completed:
        for diag in correlation_diagnostics.values():
            candidate_verdicts_seen = []
            candidate_verdict_evidence = {}
            if diag["observed"]:
                emit_verdict = "CANONICAL_GATE_READ_OBSERVED"
            elif not diag["evaluated_path_enter_after_promotion"]:
                emit_verdict = "REEVAL_COMPLETES_BUT_EVALUATED_PATH_NOT_ENTERED"
            elif not diag["canonical_gate_read_emit_candidate"]:
                emit_verdict = "EVALUATED_PATH_REENTERED_BUT_EMIT_ATTEMPT_NOT_REACHED"
            elif diag["canonical_gate_read_emit_guard_blocked"]:
                emit_verdict = "EMIT_GUARD_BLOCKED_WITH_REASON"
            elif diag["canonical_gate_read_emit_attempt"] and not diag["canonical_gate_read_emit_done"]:
                emit_verdict = "EMIT_ATTEMPT_REACHED_BUT_NOT_COMPLETED"
            elif diag["canonical_gate_read_emit_payload_built"] and not diag["canonical_gate_read_emit_attempt"]:
                emit_verdict = "EVALUATED_PATH_REENTERED_BUT_EMIT_ATTEMPT_NOT_REACHED"
            else:
                emit_verdict = "EVALUATED_PATH_REENTERED_BUT_EMIT_ATTEMPT_NOT_REACHED"
            diag["post_promotion_emit_verdict"] = emit_verdict
            emit_verdict_counts[emit_verdict] += 1
            candidate_verdicts_seen.append(emit_verdict)
            candidate_verdict_evidence[emit_verdict] = {
                "evidence_type": "emit_stage",
                "observed": bool(diag["observed"]),
                "evaluated_path_enter_after_promotion": bool(diag["evaluated_path_enter_after_promotion"]),
                "canonical_gate_read_emit_candidate": bool(diag["canonical_gate_read_emit_candidate"]),
                "canonical_gate_read_emit_guard_considered": bool(diag["canonical_gate_read_emit_guard_considered"]),
                "canonical_gate_read_emit_guard_blocked": bool(diag["canonical_gate_read_emit_guard_blocked"]),
                "canonical_gate_read_emit_attempt": bool(diag["canonical_gate_read_emit_attempt"]),
                "canonical_gate_read_emit_done": bool(diag["canonical_gate_read_emit_done"]),
            }

            if diag["observed"]:
                branch_verdict = "CANONICAL_GATE_READ_OBSERVED"
            elif diag["handoff_child_mailbox_dequeue_enter"]:
                branch_verdict = "HANDOFF_CHILD_MAILBOX_DEQUEUED"
            elif diag["handoff_child_mailbox_observed"]:
                branch_verdict = "HANDOFF_CHILD_MAILBOX_OBSERVED"
            elif diag["handoff_parent_signal_sent"]:
                branch_verdict = "HANDOFF_PARENT_SIGNAL_SENT"
            elif diag["handoff_parent_enqueue_done"]:
                branch_verdict = "HANDOFF_PARENT_ENQUEUE_COMPLETED"
            elif diag["handoff_parent_enqueue_enter"]:
                branch_verdict = "HANDOFF_PARENT_ENQUEUE_ENTERED"
            elif not diag["evaluated_path_enter_after_promotion"]:
                branch_verdict = "REEVAL_COMPLETES_BUT_EVALUATED_PATH_NOT_ENTERED"
            elif diag["canonical_gate_read_branch_selector_skip"] or str(
                diag["canonical_gate_read_branch_selector_selected_path"] or ""
            ) == "skip":
                branch_verdict = "PRE_CANDIDATE_BRANCH_SKIPPED_WITH_REASON"
            elif diag["canonical_gate_read_emit_candidate"]:
                if not diag["canonical_gate_read_emit_guard_considered"]:
                    branch_verdict = "CANDIDATE_BRANCH_REACHED_BUT_GUARD_NOT_ENTERED"
                elif diag["canonical_gate_read_emit_guard_blocked"]:
                    branch_verdict = "CANDIDATE_BRANCH_REACHED_AND_GUARD_BLOCKED"
                elif diag["canonical_gate_read_emit_attempt"]:
                    branch_verdict = "CANDIDATE_BRANCH_REACHED_AND_EMIT_ATTEMPT_REACHED"
                else:
                    branch_verdict = "CANDIDATE_BRANCH_REACHED_BUT_GUARD_NOT_ENTERED"
            else:
                branch_verdict = "EVALUATED_PATH_REENTERED_BUT_PRE_CANDIDATE_BRANCH_NOT_REACHED"
            diag["post_promotion_stage_verdict"] = branch_verdict
            branch_verdict_counts[branch_verdict] += 1
            candidate_verdicts_seen.append(branch_verdict)
            candidate_verdict_evidence[branch_verdict] = {
                "evidence_type": "branch_stage",
                "observed": bool(diag["observed"]),
                "handoff_parent_enqueue_enter": bool(diag["handoff_parent_enqueue_enter"]),
                "handoff_parent_enqueue_done": bool(diag["handoff_parent_enqueue_done"]),
                "handoff_parent_signal_sent": bool(diag["handoff_parent_signal_sent"]),
                "handoff_child_mailbox_observed": bool(diag["handoff_child_mailbox_observed"]),
                "handoff_child_mailbox_dequeue_enter": bool(diag["handoff_child_mailbox_dequeue_enter"]),
                "evaluated_path_enter_after_promotion": bool(diag["evaluated_path_enter_after_promotion"]),
                "canonical_gate_read_branch_selector_enter": bool(diag["canonical_gate_read_branch_selector_enter"]),
                "canonical_gate_read_emit_candidate": bool(diag["canonical_gate_read_emit_candidate"]),
            }

            forced_cycle_evidence = bool(
                diag["post_promotion_force_cycle_handoff_enter"]
                or diag["post_promotion_force_cycle_handoff_accept"]
                or diag["post_promotion_force_cycle_handoff_call_start"]
                or diag["post_promotion_force_cycle_handoff_call_done"]
                or diag["forced_cycle_scheduler_gate_enter"]
                or diag["forced_cycle_scheduler_gate_result"]
                or diag["forced_cycle_scheduler_gate_blocked"]
                or diag["forced_cycle_scheduler_gate_allowed"]
                or diag["forced_cycle_scheduler_tick_enter"]
                or diag["forced_cycle_request_scan_enter"]
                or diag["forced_cycle_request_scan_result"]
                or diag["forced_cycle_request_scan_empty"]
                or diag["forced_cycle_request_scan_nonempty"]
                or diag["forced_cycle_drain_enter"]
                or diag["forced_cycle_eval_entry"]
                or diag["forced_cycle_eval_pre_router"]
                or diag["forced_cycle_eval_post_router"]
                or diag["forced_cycle_eval_pre_entry_edge_check"]
                or diag["forced_cycle_eval_post_entry_edge_check"]
                or diag["forced_cycle_requested"]
                or diag["forced_cycle_eval_pre_selector_return_site"]
                or diag["forced_cycle_started"]
                or diag["forced_cycle_completed"]
                or diag["forced_cycle_failed"]
            )
            if forced_cycle_evidence:
                handoff_verdict = classify_post_promotion_force_cycle_handoff_trace(diag)
                diag["post_promotion_force_cycle_handoff_verdict"] = handoff_verdict
                handoff_verdict_counts[handoff_verdict] += 1
                candidate_verdicts_seen.append(handoff_verdict)
                candidate_verdict_evidence[handoff_verdict] = {
                    "evidence_type": "handoff_stage",
                    "post_promotion_force_cycle_handoff_enter": bool(diag["post_promotion_force_cycle_handoff_enter"]),
                    "post_promotion_force_cycle_handoff_accept": bool(diag["post_promotion_force_cycle_handoff_accept"]),
                    "post_promotion_force_cycle_handoff_reject": bool(diag["post_promotion_force_cycle_handoff_reject"]),
                    "post_promotion_force_cycle_handoff_call_start": bool(diag["post_promotion_force_cycle_handoff_call_start"]),
                    "post_promotion_force_cycle_handoff_call_done": bool(diag["post_promotion_force_cycle_handoff_call_done"]),
                    "forced_cycle_scheduler_gate_enter": bool(diag["forced_cycle_scheduler_gate_enter"]),
                    "forced_cycle_scheduler_gate_result": diag["forced_cycle_scheduler_gate_result"],
                    "forced_cycle_scheduler_gate_blocked": bool(diag["forced_cycle_scheduler_gate_blocked"]),
                    "forced_cycle_scheduler_gate_allowed": bool(diag["forced_cycle_scheduler_gate_allowed"]),
                    "handoff_parent_enqueue_enter": bool(diag["handoff_parent_enqueue_enter"]),
                    "handoff_parent_enqueue_done": bool(diag["handoff_parent_enqueue_done"]),
                    "handoff_parent_signal_sent": bool(diag["handoff_parent_signal_sent"]),
                    "handoff_child_mailbox_observed": bool(diag["handoff_child_mailbox_observed"]),
                    "handoff_child_mailbox_dequeue_enter": bool(diag["handoff_child_mailbox_dequeue_enter"]),
                }

                deepest_transport_state_seen, transport_eligibility_reason, transport_blocker = _transport_finalist_state_from_diag(diag)
                if deepest_transport_state_seen:
                    diag["deepest_transport_downstream_state_seen"] = deepest_transport_state_seen
                    diag["transport_verdict_eligibility_reason"] = transport_eligibility_reason
                    diag["transport_finalist_blocker"] = transport_blocker
                    if transport_eligibility_reason == "eligible_for_bucket_local_finalist":
                        if deepest_transport_state_seen not in candidate_verdicts_seen:
                            candidate_verdicts_seen.append(deepest_transport_state_seen)
                            candidate_verdict_evidence[deepest_transport_state_seen] = {
                                "evidence_type": "transport_state",
                                "deepest_transport_downstream_state_seen": deepest_transport_state_seen,
                                "transport_verdict_eligibility_reason": transport_eligibility_reason,
                            }
                    else:
                        if "HANDOFF_PARENT_ENQUEUE_ENTERED" not in candidate_verdicts_seen:
                            candidate_verdicts_seen.append("HANDOFF_PARENT_ENQUEUE_ENTERED")
                            candidate_verdict_evidence["HANDOFF_PARENT_ENQUEUE_ENTERED"] = {
                                "evidence_type": "transport_state",
                                "deepest_transport_downstream_state_seen": deepest_transport_state_seen,
                                "transport_verdict_eligibility_reason": transport_eligibility_reason,
                                "transport_finalist_blocker": transport_blocker,
                            }

                forced_cycle_verdict = classify_forced_cycle_trace(diag)
                if (
                    forced_cycle_verdict == "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY_BUT_PRE_DRAIN_NOT_ENTERED"
                    and bool(diag.get("forced_cycle_request_scan_nonempty"))
                    and (
                        bool(bucket.get("forced_cycle_pre_drain_seen"))
                        or any(
                            trace.get("trace_event_name") == "post_promotion_force_cycle_pre_drain_enter"
                            for trace in bucket.get("forced_cycle_traces", [])
                        )
                    )
                ):
                    forced_cycle_verdict = "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
                diag["post_promotion_forced_cycle_verdict"] = forced_cycle_verdict
                forced_cycle_verdict_counts[forced_cycle_verdict] += 1
                candidate_verdicts_seen.append(forced_cycle_verdict)
                candidate_verdict_evidence[forced_cycle_verdict] = {
                    "evidence_type": "forced_cycle_stage",
                    "forced_cycle_scheduler_tick_enter": bool(diag["forced_cycle_scheduler_tick_enter"]),
                    "forced_cycle_scheduler_tick_exit": bool(diag["forced_cycle_scheduler_tick_exit"]),
                    "forced_cycle_request_scan_enter": bool(diag["forced_cycle_request_scan_enter"]),
                    "forced_cycle_request_scan_result": bool(diag["forced_cycle_request_scan_result"]),
                    "forced_cycle_request_scan_empty": bool(diag["forced_cycle_request_scan_empty"]),
                    "forced_cycle_request_scan_nonempty": bool(diag["forced_cycle_request_scan_nonempty"]),
                    "forced_cycle_request_scan_candidate_seen": bool(diag["forced_cycle_request_scan_candidate_seen"]),
                    "forced_cycle_request_scan_candidate_reject": bool(diag["forced_cycle_request_scan_candidate_reject"]),
                    "forced_cycle_request_scan_candidate_reject_reason": diag["forced_cycle_request_scan_candidate_reject_reason"],
                    "forced_cycle_request_scan_empty_reason": diag["forced_cycle_request_scan_empty_reason"],
                    "forced_cycle_started": bool(diag["forced_cycle_started"]),
                    "forced_cycle_completed": bool(diag["forced_cycle_completed"]),
                    "forced_cycle_eval_entry": bool(diag["forced_cycle_eval_entry"]),
                    "forced_cycle_eval_pre_router": bool(diag["forced_cycle_eval_pre_router"]),
                    "forced_cycle_eval_post_router": bool(diag["forced_cycle_eval_post_router"]),
                    "forced_cycle_eval_pre_entry_edge_check": bool(diag["forced_cycle_eval_pre_entry_edge_check"]),
                    "forced_cycle_eval_post_entry_edge_check": bool(diag["forced_cycle_eval_post_entry_edge_check"]),
                    "forced_cycle_eval_pre_selector_return_site": bool(diag["forced_cycle_eval_pre_selector_return_site"]),
                    "forced_cycle_eval_pre_selector_return_site_id": diag["forced_cycle_eval_pre_selector_return_site_id"],
                    "forced_cycle_eval_pre_selector_return_reason": diag["forced_cycle_eval_pre_selector_return_reason"],
                }
            diag["candidate_verdicts_seen"] = candidate_verdicts_seen
            diag["candidate_verdict_evidence"] = candidate_verdict_evidence
            diag["winning_verdict"] = diag.get("post_promotion_forced_cycle_verdict") or diag.get(
                "post_promotion_force_cycle_handoff_verdict"
            ) or diag.get("post_promotion_stage_verdict") or diag.get("post_promotion_emit_verdict")
            if diag.get("transport_verdict_eligibility_reason") == "eligible_for_bucket_local_finalist" and diag.get("deepest_transport_downstream_state_seen"):
                diag["winning_verdict"] = diag.get("deepest_transport_downstream_state_seen")
                diag["winning_verdict_reason"] = "transport_state_prioritized"
            elif diag["post_promotion_forced_cycle_verdict"]:
                diag["winning_verdict_reason"] = "forced_cycle_classifier_prioritized"
            elif diag["post_promotion_force_cycle_handoff_verdict"]:
                diag["winning_verdict_reason"] = "handoff_classifier_prioritized"
            elif diag["post_promotion_stage_verdict"]:
                diag["winning_verdict_reason"] = "bucket_stage_classifier_prioritized"
            elif diag["post_promotion_emit_verdict"]:
                diag["winning_verdict_reason"] = "emit_stage_classifier_prioritized"

        failure_counts = Counter({k: v for k, v in emit_verdict_counts.items() if k != "CANONICAL_GATE_READ_OBSERVED"})
        if failure_counts:
            emit_stage_rank = {
                "REEVAL_COMPLETES_BUT_EVALUATED_PATH_NOT_ENTERED": 0,
                "EVALUATED_PATH_REENTERED_BUT_EMIT_ATTEMPT_NOT_REACHED": 1,
                "EMIT_GUARD_BLOCKED_WITH_REASON": 2,
                "EMIT_ATTEMPT_REACHED_BUT_NOT_COMPLETED": 3,
            }
            first_missing_emit_stage_after_reeval = max(
                failure_counts.keys(),
                key=lambda classification: emit_stage_rank.get(classification, -1),
            )
        elif emit_verdict_counts.get("CANONICAL_GATE_READ_OBSERVED"):
            first_missing_emit_stage_after_reeval = "CANONICAL_GATE_READ_OBSERVED"

        branch_failure_counts = Counter({k: v for k, v in branch_verdict_counts.items() if k != "CANONICAL_GATE_READ_OBSERVED"})
        if branch_failure_counts:
            branch_stage_rank = {
                "REEVAL_COMPLETES_BUT_EVALUATED_PATH_NOT_ENTERED": 0,
                "PRE_CANDIDATE_BRANCH_SKIPPED_WITH_REASON": 1,
                "EVALUATED_PATH_REENTERED_BUT_PRE_CANDIDATE_BRANCH_NOT_REACHED": 2,
                "CANDIDATE_BRANCH_REACHED_BUT_GUARD_NOT_ENTERED": 3,
                "CANDIDATE_BRANCH_REACHED_AND_GUARD_BLOCKED": 4,
                "CANDIDATE_BRANCH_REACHED_AND_EMIT_ATTEMPT_REACHED": 5,
            }
            first_missing_branch_stage_after_reeval = max(
                branch_failure_counts.keys(),
                key=lambda classification: branch_stage_rank.get(classification, -1),
            )
        elif branch_verdict_counts.get("CANONICAL_GATE_READ_OBSERVED"):
            first_missing_branch_stage_after_reeval = "CANONICAL_GATE_READ_OBSERVED"

        forced_cycle_failure_counts = Counter(
            {k: v for k, v in forced_cycle_verdict_counts.items() if k != "FULL_POST_PROMOTION_PIPELINE_CONFIRMED"}
        )
        if forced_cycle_failure_counts:
            forced_cycle_stage_rank = {
                "FORCE_CYCLE_HANDOFF_NOT_REACHED": 0,
                "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED": 1,
                "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED": 2,
                "FORCED_CYCLE_SCHEDULER_GATE_BLOCKED": 3,
                "FORCED_CYCLE_SCHEDULER_GATE_ALLOWED_BUT_TICK_NOT_ENTERED": 4,
                "FORCED_CYCLE_SCHEDULER_TICK_NOT_ENTERED": 5,
                "FORCED_CYCLE_REQUEST_SCAN_NOT_ENTERED": 6,
                "FORCED_CYCLE_REQUEST_SCAN_RESULT_REACHED": 7,
                "FORCED_CYCLE_REQUEST_SCAN_EMPTY": 8,
                "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY_BUT_PRE_DRAIN_NOT_ENTERED": 9,
                "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY": 10,
                "PRE_DRAIN_TRANSITION_BLOCKER_PROVEN_BUT_NOT_FIXED": 11,
                "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED": 12,
                "FORCED_CYCLE_DRAIN_ENTERED": 13,
                "FORCED_CYCLE_CALLED_BUT_LOOP_NOT_ENTERED": 13,
                "FORCED_CYCLE_LOOP_ENTERED_BUT_EVALUATED_PATH_NOT_INVOKED": 14,
                "FORCED_CYCLE_EVALUATED_PATH_INVOKED_BUT_SELECTOR_NOT_ENTERED": 15,
                "FORCED_CYCLE_PRE_SELECTOR_GUARD_RETURN": 16,
                "FORCED_CYCLE_MISSING_SELECTOR_CONTEXT": 17,
                "FORCED_CYCLE_POSITION_STATE_SHORT_CIRCUIT": 18,
                "FORCED_CYCLE_ROUTER_POSTPROCESS_RETURN": 19,
                "FORCED_CYCLE_UNKNOWN_PRE_SELECTOR_RETURN": 20,
                "HELPER_RETURNED_NONE": 21,
                "HELPER_RETURNED_NON_DICT_RESULT": 22,
                "HELPER_RETURNED_DICT_MISSING_REQUIRED_FIELDS": 23,
                "WRAPPER_EXPECTATION_MISMATCH": 24,
                "VALID_HELPER_RESULT_BUT_SELECTOR_CONTEXT_NOT_BUILT": 25,
                "FORCED_CYCLE_REACHED_SELECTOR_BUT_CANDIDATE_NOT_CREATED": 26,
                "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_NOT_ENTERED": 27,
                "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_BLOCKED": 28,
                "FORCED_CYCLE_REACHED_CANDIDATE_BUT_EMIT_NOT_ATTEMPTED": 29,
                "FORCED_CYCLE_REACHED_EMIT_ATTEMPT_BUT_NOT_DONE": 30,
            }
            first_missing_forced_cycle_stage_after_reeval = max(
                forced_cycle_failure_counts.keys(),
                key=lambda classification: forced_cycle_stage_rank.get(classification, -1),
            )
        elif forced_cycle_verdict_counts.get("FULL_POST_PROMOTION_PIPELINE_CONFIRMED"):
            first_missing_forced_cycle_stage_after_reeval = "FULL_POST_PROMOTION_PIPELINE_CONFIRMED"
    else:
        for diag in correlation_diagnostics.values():
            diag["post_promotion_emit_verdict"] = "INSUFFICIENT_RUNTIME_EVIDENCE"
            diag["post_promotion_stage_verdict"] = "INSUFFICIENT_RUNTIME_EVIDENCE"
            emit_verdict_counts["INSUFFICIENT_RUNTIME_EVIDENCE"] += 1
    post_promotion_emit_verdict_counts = dict(sorted(emit_verdict_counts.items()))
    run_max_gate_seq = max((e["runtime_seq"] for e in gate_reads), default=0)
    _sync_forced_cycle_pre_drain_trace_state(buckets, logs)
    per_bucket = {k: _finalize_bucket(v, run_max_gate_seq) for k, v in buckets.items()}
    verdict_counts = Counter(v["bucket_verdict"] for v in per_bucket.values())

    buckets_promoted = sum(1 for v in per_bucket.values() if v["promotion_count"] > 0)
    buckets_read = sum(1 for v in per_bucket.values() if v["gate_read_count"] > 0)
    buckets_read_after_promotion = sum(1 for v in per_bucket.values() if v["gate_reads_after_first_promotion"] > 0)
    buckets_with_forced_replay = sum(1 for v in per_bucket.values() if v["forced_post_promotion_read_count"] > 0)
    forced_replay_reads_total = sum(v["forced_post_promotion_read_count"] for v in per_bucket.values())
    buckets_with_nonzero_visible_trade_count = sum(1 for v in per_bucket.values() if v["max_gate_trade_count_after_promotion"] > 0)
    buckets_with_history_ready_after_promotion = sum(1 for v in per_bucket.values() if v["history_ready_after_promotion_any"])
    promotion_visibility_rate = buckets_with_nonzero_visible_trade_count / max(1, buckets_promoted)
    promotion_skip_reasons = Counter(e["reason"] for e in promotion_skips)
    close_input_rows = len(close_traces) // 2 if close_traces else 0
    close_input_count = sum(1 for e in close_traces if e.get("trace_kind") == "close_trace" and e.get("raw_input_classification") is not None)
    close_output_count = sum(1 for e in close_traces if e.get("trace_kind") == "close_trace" and e.get("raw_input_classification") is None)
    row_diagnoses = []
    for inp in sorted([e for e in close_traces if e.get("raw_input_classification") is not None], key=lambda e: (e["runtime_seq"], e["seq_order"])):
        out = next((o for o in close_traces if o.get("raw_input_classification") is None and o["runtime_seq"] == inp["runtime_seq"] and o["canonical_key"] == inp["canonical_key"]), None)
        diagnosis = inp["raw_input_classification"]
        if diagnosis == "RAW_INPUTS_PRESENT" and out and out.get("output_null_classification") == "REALIZED_INPUTS_PRESENT":
            diagnosis = "INPUTS_PRESENT_OUTPUT_STILL_NULL"
        elif diagnosis == "RAW_INPUTS_PRESENT" and out and out.get("output_null_classification") != "REALIZED_INPUTS_PRESENT":
            diagnosis = "DECOMPOSE_OUTPUT_NOT_ASSIGNED"
        row_diagnoses.append({
            "runtime_seq": inp["runtime_seq"],
            "canonical_key": inp["canonical_key"],
            "input_classification": inp["raw_input_classification"],
            "output_classification": out.get("output_null_classification") if out else None,
            "branch": inp.get("source_branch"),
            "diagnosis": diagnosis,
        })
    diagnosis_counts = Counter(r["diagnosis"] for r in row_diagnoses)
    top_root_cause = diagnosis_counts.most_common(1)[0][0] if diagnosis_counts else "INSUFFICIENT_EVIDENCE"

    visibility_ms = [v["promotion_to_first_visible_delta_ms"] for v in per_bucket.values() if v["promotion_to_first_visible_delta_ms"] is not None]
    top_failure_mode = "INSUFFICIENT_EVIDENCE"
    if top_root_cause in {
        "RAW_FEE_INPUT_MISSING",
        "RAW_FILL_INPUTS_MISSING",
        "ZERO_SIZE_CLOSE_INPUT",
        "MOCK_BRANCH_UNPOPULATED_REALIZED_FIELDS",
        "DECOMPOSE_OUTPUT_NOT_ASSIGNED",
        "PAYLOAD_CONSTRUCTION_LOSS_BEFORE_DECOMPOSE",
        "INPUTS_PRESENT_OUTPUT_STILL_NULL",
        "MIXED_UPSTREAM_NULL_SOURCES",
    }:
        top_failure_mode = top_root_cause
    else:
        if buckets_promoted == 0:
            top_failure_mode = "INSUFFICIENT_EVIDENCE"
        elif buckets_read_after_promotion == 0:
            top_failure_mode = "STILL_NO_VISIBILITY_AFTER_FORCED_POST_PROMOTION_READS"
        elif buckets_with_nonzero_visible_trade_count > 0 and buckets_with_history_ready_after_promotion > 0:
            top_failure_mode = "PURE_TIMING_CUTOFF_CONFIRMED"
        elif buckets_with_nonzero_visible_trade_count > 0:
            top_failure_mode = "TIMING_FIXED_SECOND_BLOCKER_REVEALED"
        else:
            top_failure_mode = "STILL_NO_VISIBILITY_AFTER_FORCED_POST_PROMOTION_READS"

    read_source_names_seen = sorted(set(
        [e["read_source_name"] for e in gate_reads if e.get("read_source_name")] +
        [e["decision_source_name"] for e in gate_reads if e.get("decision_source_name")]
    ))
    read_source_functions_seen = sorted(set(
        [e["gate_read_source_function"] for e in gate_reads if e.get("gate_read_source_function")]
    ))

    collapse_classes = Counter(
        v["collapse_class"] for v in per_bucket.values() if v.get("collapse_class")
    )
    boundary_classification = "PARTIAL_PROOF_MORE_TRACE_NEEDED"
    if collapse_classes.get("MATERIALIZATION_BOUNDARY_COLLAPSE_CONFIRMED"):
        boundary_classification = "MATERIALIZATION_BOUNDARY_COLLAPSE_CONFIRMED"
    elif collapse_classes.get("STALE_SNAPSHOT_COLLAPSE_CONFIRMED"):
        boundary_classification = "STALE_SNAPSHOT_COLLAPSE_CONFIRMED"
    no_read_cause_counts = Counter(
        v["no_read_cause_verdict"] for v in per_bucket.values() if v.get("no_read_cause_verdict")
    )
    no_read_cause_classification = "PARTIAL_PROOF_MORE_TRACE_NEEDED"
    if len(no_read_cause_counts) == 1 and buckets_promoted > 0:
        no_read_cause_classification = next(iter(no_read_cause_counts))

    post_promotion_branch_verdict_counts = dict(sorted(branch_verdict_counts.items()))
    post_promotion_force_cycle_handoff_verdict_counts = dict(sorted(handoff_verdict_counts.items()))
    post_promotion_forced_cycle_verdict_counts = dict(sorted(forced_cycle_verdict_counts.items()))
    post_promotion_stage_verdict_counts = post_promotion_branch_verdict_counts
    first_missing_stage_after_reeval = first_missing_branch_stage_after_reeval
    if post_promotion_forced_cycle_verdict_counts:
        forced_cycle_stage_rank = {
            "FORCE_CYCLE_HANDOFF_NOT_REACHED": 0,
            "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED": 1,
            "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED": 2,
                "FORCED_CYCLE_SCHEDULER_GATE_BLOCKED": 3,
                "FORCED_CYCLE_SCHEDULER_GATE_ALLOWED_BUT_TICK_NOT_ENTERED": 4,
                "FORCED_CYCLE_SCHEDULER_CALLER_NOT_ENTERED": 5,
                "FORCED_CYCLE_SCHEDULER_CALLER_ENTERED_BUT_TICK_NOT_ENTERED": 6,
                "FORCED_CYCLE_SCHEDULER_CALLER_RETURNED_WITHOUT_TICK": 7,
                "FORCED_CYCLE_SCHEDULER_TICK_NOT_ENTERED": 8,
                "FORCED_CYCLE_REQUEST_SCAN_NOT_ENTERED": 9,
                "FORCED_CYCLE_REQUEST_SCAN_RESULT_REACHED": 10,
                "FORCED_CYCLE_REQUEST_SCAN_EMPTY": 11,
                "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY_BUT_PRE_DRAIN_NOT_ENTERED": 12,
                "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY": 13,
                "PRE_DRAIN_TRANSITION_BLOCKER_PROVEN_BUT_NOT_FIXED": 14,
                "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED": 15,
                "FORCED_CYCLE_DRAIN_ENTERED": 16,
                "FORCED_CYCLE_CALLED_BUT_LOOP_NOT_ENTERED": 16,
                "FORCED_CYCLE_LOOP_ENTERED_BUT_EVALUATED_PATH_NOT_INVOKED": 17,
                "FORCED_CYCLE_EVALUATED_PATH_INVOKED_BUT_SELECTOR_NOT_ENTERED": 18,
                "FORCED_CYCLE_PRE_SELECTOR_GUARD_RETURN": 19,
                "FORCED_CYCLE_MISSING_SELECTOR_CONTEXT": 20,
                "FORCED_CYCLE_POSITION_STATE_SHORT_CIRCUIT": 21,
                "FORCED_CYCLE_ROUTER_POSTPROCESS_RETURN": 22,
                "FORCED_CYCLE_UNKNOWN_PRE_SELECTOR_RETURN": 23,
                "HELPER_RETURNED_NONE": 24,
                "HELPER_RETURNED_NON_DICT_RESULT": 25,
                "HELPER_RETURNED_DICT_MISSING_REQUIRED_FIELDS": 26,
                "WRAPPER_EXPECTATION_MISMATCH": 27,
                "VALID_HELPER_RESULT_BUT_SELECTOR_CONTEXT_NOT_BUILT": 28,
                "FORCED_CYCLE_REACHED_SELECTOR_BUT_CANDIDATE_NOT_CREATED": 29,
                "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_NOT_ENTERED": 30,
                "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_BLOCKED": 31,
                "FORCED_CYCLE_REACHED_CANDIDATE_BUT_EMIT_NOT_ATTEMPTED": 32,
                "FORCED_CYCLE_REACHED_EMIT_ATTEMPT_BUT_NOT_DONE": 33,
                "FULL_POST_PROMOTION_PIPELINE_CONFIRMED": 34,
                "INSUFFICIENT_RUNTIME_EVIDENCE": -1,
            }
        final_classification = max(
            post_promotion_forced_cycle_verdict_counts.keys(),
            key=lambda classification: forced_cycle_stage_rank.get(classification, -1),
        )
    elif any(d["forced_cycle_scheduler_tick_enter"] for d in correlation_diagnostics.values()):
        scheduler_failure_counts = Counter()
        for diag in correlation_diagnostics.values():
            if diag["forced_cycle_scheduler_tick_enter"]:
                if diag["forced_cycle_request_scan_nonempty"]:
                    scheduler_failure_counts["FORCED_CYCLE_REQUEST_SCAN_NONEMPTY"] += 1
                elif diag["forced_cycle_request_scan_empty"]:
                    scheduler_failure_counts["FORCED_CYCLE_REQUEST_SCAN_EMPTY"] += 1
                elif diag["forced_cycle_request_scan_result"]:
                    scheduler_failure_counts["FORCED_CYCLE_REQUEST_SCAN_RESULT_REACHED"] += 1
                else:
                    scheduler_failure_counts["FORCED_CYCLE_SCHEDULER_TICK_ENTERED"] += 1
        scheduler_stage_rank = {
            "FORCED_CYCLE_SCHEDULER_TICK_ENTERED": 0,
            "FORCED_CYCLE_REQUEST_SCAN_RESULT_REACHED": 1,
            "FORCED_CYCLE_REQUEST_SCAN_EMPTY": 2,
            "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY": 3,
        }
        final_classification = max(
            scheduler_failure_counts.keys(),
            key=lambda classification: scheduler_stage_rank.get(classification, -1),
        )
    else:
        if reevaluation_completed and runner_forced_cycle_result:
            final_classification = runner_forced_cycle_result
        else:
            final_classification = (
                first_missing_stage_after_reeval if reevaluation_completed else no_read_cause_classification
            )

    correlation_stage_counts = {
        "written": sum(1 for d in correlation_diagnostics.values() if d["written"]),
        "armed": sum(1 for d in correlation_diagnostics.values() if d["armed"]),
        "invoked": sum(1 for d in correlation_diagnostics.values() if d["invoked"]),
        "emit_attempted": sum(1 for d in correlation_diagnostics.values() if d["emit_attempted"]),
        "persisted": sum(1 for d in correlation_diagnostics.values() if d["persisted"]),
        "observed": sum(1 for d in correlation_diagnostics.values() if d["observed"]),
    }
    correlation_verdict_counts = dict(
        sorted(Counter(d["final_verdict"] for d in correlation_diagnostics.values()).items())
    )
    post_invoke_emit_verdict_counts = dict(
        sorted(Counter(d["post_invoke_emit_verdict"] for d in correlation_diagnostics.values()).items())
    )

    resolved_data_quality = data_quality or _new_data_quality()
    resolved_data_quality["rows_total"] = _safe_int(resolved_data_quality.get("rows_total"), len(logs))
    resolved_data_quality["rows_valid"] = _safe_int(resolved_data_quality.get("rows_valid"), len(logs))
    resolved_data_quality["rows_skipped"] = _safe_int(
        resolved_data_quality.get("rows_skipped"),
        max(0, resolved_data_quality["rows_total"] - resolved_data_quality["rows_valid"]),
    )
    resolved_data_quality["skip_reasons"] = dict(sorted((resolved_data_quality.get("skip_reasons") or {}).items()))

    report = {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "scenarios": ["baseline", "disable_current_side", "disable_net_target_guard"],
            "classification": final_classification,
            "method_version": "v4",
        },
        "canonical_state": {"total_buckets": len(per_bucket), "total_promotions": len(promotions)},
        "coverage": {
            "evaluated_rows": evaluated_total,
            "evaluated_with_canonical": evaluated_total,
            "unresolved_rows": unresolved_rows,
        },
        "promotion_effect": {
            "max_trade_count": max((v["max_gate_trade_count_after_promotion"] for v in per_bucket.values()), default=0),
            "buckets_with_growth": buckets_with_nonzero_visible_trade_count,
        },
        "readiness": {
            "shadow_history_ready_any": bool(buckets_with_history_ready_after_promotion),
            "shadow_history_ready_count": buckets_with_history_ready_after_promotion,
        },
        "aggregate": {
            "total_promotions": len(promotions),
            "total_promotion_skips": len(promotion_skips),
            "total_gate_reads": len(gate_reads),
            "buckets_promoted": buckets_promoted,
            "buckets_read": buckets_read,
            "buckets_read_after_promotion": buckets_read_after_promotion,
            "buckets_with_forced_replay": buckets_with_forced_replay,
            "forced_replay_reads_total": forced_replay_reads_total,
            "buckets_with_nonzero_visible_trade_count": buckets_with_nonzero_visible_trade_count,
            "buckets_with_history_ready_after_promotion": buckets_with_history_ready_after_promotion,
            "promotion_visibility_rate": promotion_visibility_rate,
            "promotion_to_visibility_latency_min": min(visibility_ms) if visibility_ms else None,
            "promotion_to_visibility_latency_max": max(visibility_ms) if visibility_ms else None,
            "promotion_to_visibility_latency_median": median(visibility_ms) if visibility_ms else None,
            "read_source_names_seen": read_source_names_seen,
            "read_source_functions_seen": read_source_functions_seen,
            "promotion_skip_reasons": dict(sorted(promotion_skip_reasons.items())),
            "close_input_rows": close_input_count,
            "close_output_rows": close_output_count,
            "rows_with_raw_inputs_present": sum(1 for r in row_diagnoses if r["input_classification"] == "RAW_INPUTS_PRESENT"),
            "rows_with_raw_fee_missing": sum(1 for r in row_diagnoses if r["input_classification"] == "RAW_FEE_INPUT_MISSING"),
            "rows_with_raw_fill_missing": sum(1 for r in row_diagnoses if r["input_classification"] == "RAW_FILL_INPUTS_MISSING"),
            "rows_with_zero_size_close_input": sum(1 for r in row_diagnoses if r["input_classification"] == "ZERO_SIZE_CLOSE_INPUT"),
            "rows_with_outputs_null_despite_present_raw": sum(1 for r in row_diagnoses if r["diagnosis"] == "DECOMPOSE_OUTPUT_NOT_ASSIGNED"),
            "rows_by_branch": dict(sorted(Counter(r["branch"] for r in row_diagnoses if r.get("branch")).items())),
            "row_diagnosis_counts": dict(sorted(diagnosis_counts.items())),
            "top_failure_mode": top_failure_mode,
            "storage_write_trace_count": len(storage_write_traces),
            "pre_materialization_trace_count": len(pre_materialization_traces),
            "post_materialization_trace_count": len(post_materialization_traces),
            "collapse_compare_trace_count": len(collapse_compare_traces),
            "storage_compare_trace_count": len(storage_compare_traces),
            "critical_path_exception_count": len(critical_path_exceptions),
            "boundary_classification": boundary_classification,
            "no_read_cause_classification": no_read_cause_classification,
            "final_classification": final_classification,
            "correlation_stage_counts": correlation_stage_counts,
            "correlation_verdict_counts": correlation_verdict_counts,
            "post_invoke_emit_verdict_counts": post_invoke_emit_verdict_counts,
            "post_promotion_reeval_completed": int(bool(runner_before.get("post_promotion_reeval_completed"))),
            "post_promotion_reeval_requested": int(bool(runner_before.get("post_promotion_reeval_requested"))),
            "post_promotion_reeval_result": reeval_result or None,
            "reeval_exit_reason": runner_before.get("reeval_exit_reason"),
            "post_promotion_reeval_dispatch_entered": int(bool(runner_before.get("post_promotion_reeval_dispatch_entered"))),
            "post_promotion_reeval_dispatch_exited": int(bool(runner_before.get("post_promotion_reeval_dispatch_exited"))),
            "post_promotion_forced_cycle_requested": int(bool(runner_before.get("post_promotion_forced_cycle_requested"))),
            "post_promotion_forced_cycle_started": int(bool(runner_before.get("post_promotion_forced_cycle_started"))),
            "post_promotion_forced_cycle_completed": int(bool(runner_before.get("post_promotion_forced_cycle_completed"))),
            "post_promotion_forced_cycle_failed": int(bool(runner_before.get("post_promotion_forced_cycle_failed"))),
            "post_promotion_forced_cycle_result": runner_before.get("post_promotion_forced_cycle_result"),
            "post_promotion_forced_cycle_exit_reason": runner_before.get("post_promotion_forced_cycle_exit_reason"),
            "evaluated_path_enter_after_promotion_count": sum(1 for d in correlation_diagnostics.values() if d["evaluated_path_enter_after_promotion"]),
            "canonical_gate_read_emit_candidate_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_candidate"]),
            "canonical_gate_read_emit_guard_considered_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_guard_considered"]),
            "canonical_gate_read_emit_guard_blocked_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_guard_blocked"]),
            "canonical_gate_read_emit_payload_built_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_payload_built"]),
            "canonical_gate_read_emit_attempt_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_attempt"]),
            "canonical_gate_read_emit_enter_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_enter"]),
            "canonical_gate_read_emit_done_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_done"]),
            "canonical_gate_read_branch_selector_enter_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_branch_selector_enter"]),
            "canonical_gate_read_branch_selector_inputs_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_branch_selector_inputs"]),
            "canonical_gate_read_branch_selector_skip_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_branch_selector_skip"]),
            "canonical_gate_read_observed_count": sum(1 for d in correlation_diagnostics.values() if d["observed"]),
            "forced_cycle_requested_count": sum(1 for d in correlation_diagnostics.values() if d["forced_cycle_requested"]),
            "forced_cycle_started_count": sum(1 for d in correlation_diagnostics.values() if d["forced_cycle_started"]),
            "forced_cycle_completed_count": sum(1 for d in correlation_diagnostics.values() if d["forced_cycle_completed"]),
            "forced_cycle_failed_count": sum(1 for d in correlation_diagnostics.values() if d["forced_cycle_failed"]),
            "post_promotion_stage_verdict_counts": post_promotion_stage_verdict_counts,
            "post_promotion_emit_verdict_counts": post_promotion_emit_verdict_counts,
            "post_promotion_branch_verdict_counts": post_promotion_branch_verdict_counts,
            "post_promotion_force_cycle_handoff_verdict_counts": post_promotion_force_cycle_handoff_verdict_counts,
            "post_promotion_forced_cycle_verdict_counts": post_promotion_forced_cycle_verdict_counts,
            "first_missing_stage_after_reeval": first_missing_stage_after_reeval,
            "first_missing_emit_stage_after_reeval": first_missing_stage_after_reeval,
        },
        "bucket_verdict_counts": dict(sorted(verdict_counts.items())),
        "unresolved_reasons": dict(sorted(unresolved_reasons.items())),
        "per_bucket": dict(sorted(per_bucket.items())),
        "conclusion": {
            "linkage_working": bool(buckets_with_nonzero_visible_trade_count > 0),
            "readiness_unlocked": bool(buckets_with_history_ready_after_promotion > 0),
            "read_source_names_seen": read_source_names_seen,
            "read_source_functions_seen": read_source_functions_seen,
            "promotion_skip_reasons": dict(sorted(promotion_skip_reasons.items())),
            "row_diagnoses": row_diagnoses,
            "collapse_classes": dict(sorted(collapse_classes.items())),
            "no_read_cause_counts": dict(sorted(no_read_cause_counts.items())),
            "correlation_stage_counts": correlation_stage_counts,
            "correlation_verdict_counts": correlation_verdict_counts,
            "post_invoke_emit_verdict_counts": post_invoke_emit_verdict_counts,
            "post_promotion_stage_verdict_counts": post_promotion_stage_verdict_counts,
            "post_promotion_emit_verdict_counts": post_promotion_emit_verdict_counts,
            "post_promotion_branch_verdict_counts": post_promotion_branch_verdict_counts,
            "post_promotion_force_cycle_handoff_verdict_counts": post_promotion_force_cycle_handoff_verdict_counts,
            "first_missing_stage_after_reeval": first_missing_stage_after_reeval,
            "first_missing_emit_stage_after_reeval": first_missing_stage_after_reeval,
        },
        "correlation_diagnostics": dict(sorted(correlation_diagnostics.items())),
        "data_quality": resolved_data_quality,
        "final_classification": final_classification,
        "run_parameters": {
            "source_result": run["results_path"],
            "source_db": str(run["db_path"]),
            "duration_sec_actual": run["duration_sec_actual"],
            "before": runner_before,
        },
    }
    return report

def _ensure_corr_diag_fields(diag: dict):
        diag.setdefault("post_invoke_emit_path_enter", False)
        diag.setdefault("post_invoke_emit_guard_considered", False)
        diag.setdefault("post_invoke_emit_guard_allowed", False)
        diag.setdefault("post_invoke_emit_guard_reason", None)
        diag.setdefault("post_invoke_emit_early_return", False)
        diag.setdefault("post_invoke_emit_early_return_reason", None)
        diag.setdefault("post_invoke_emit_attempt_reached", False)
        diag.setdefault("post_invoke_emit_micro_stage", None)
        diag.setdefault("post_invoke_emit_hidden_branch_taken", False)
        diag.setdefault("post_invoke_emit_hidden_branch_reason", None)
        diag.setdefault("post_invoke_emit_local_return", False)
        diag.setdefault("post_invoke_emit_local_return_reason", None)
        diag.setdefault("post_invoke_emit_exception_class", None)
        diag.setdefault("post_invoke_emit_exception_message", None)
        diag.setdefault("post_invoke_emit_attempt_call_enter", False)
        diag.setdefault("post_promotion_eval_arm_consumed", False)
        diag.setdefault("evaluated_path_enter_after_promotion", False)
        diag.setdefault("evaluated_path_enter_after_forced_cycle", False)
        diag.setdefault("evaluated_path_skip_reason", None)
        diag.setdefault("evaluated_path_exit_reason", None)
        diag.setdefault("canonical_gate_read_branch_selector_enter", False)
        diag.setdefault("canonical_gate_read_branch_selector_inputs", False)
        diag.setdefault("canonical_gate_read_branch_selector_selected_path", None)
        diag.setdefault("canonical_gate_read_branch_selector_skip", False)
        diag.setdefault("canonical_gate_read_branch_selector_skip_reason", None)
        diag.setdefault("canonical_gate_read_emit_candidate", False)
        diag.setdefault("canonical_gate_read_emit_guard_considered", False)
        diag.setdefault("canonical_gate_read_emit_guard_blocked", False)
        diag.setdefault("canonical_gate_read_emit_guard_reason", None)
        diag.setdefault("canonical_gate_read_emit_payload_built", False)
        diag.setdefault("canonical_gate_read_emit_attempt", False)
        diag.setdefault("canonical_gate_read_emit_enter", False)
        diag.setdefault("canonical_gate_read_emit_done", False)
        diag.setdefault("forced_cycle_requested", False)
        diag.setdefault("forced_cycle_enter", False)
        diag.setdefault("forced_cycle_started", False)
        diag.setdefault("forced_cycle_completed", False)
        diag.setdefault("forced_cycle_failed", False)
        diag.setdefault("forced_cycle_scheduler_tick_enter", False)
        diag.setdefault("forced_cycle_scheduler_tick_exit", False)
        diag.setdefault("forced_cycle_scheduler_gate_enter", False)
        diag.setdefault("forced_cycle_scheduler_gate_result", None)
        diag.setdefault("forced_cycle_scheduler_gate_blocked", False)
        diag.setdefault("forced_cycle_scheduler_gate_allowed", False)
        diag.setdefault("forced_cycle_scheduler_caller_enter", False)
        diag.setdefault("forced_cycle_scheduler_caller_exit", False)
        diag.setdefault("forced_cycle_request_scan_enter", False)
        diag.setdefault("forced_cycle_request_scan_result", None)
        diag.setdefault("forced_cycle_request_scan_empty", False)
        diag.setdefault("forced_cycle_request_scan_nonempty", False)
        diag.setdefault("forced_cycle_request_scan_candidate_seen", False)
        diag.setdefault("forced_cycle_request_scan_candidate_reject", False)
        diag.setdefault("forced_cycle_request_scan_candidate_reject_reason", None)
        diag.setdefault("forced_cycle_request_scan_empty_reason", None)
        diag.setdefault("forced_cycle_pre_drain_candidate", False)
        diag.setdefault("forced_cycle_pre_drain_reject", False)
        diag.setdefault("forced_cycle_pre_drain_reject_reason", None)
        diag.setdefault("forced_cycle_pre_drain_enter", False)
        diag.setdefault("forced_cycle_pre_drain_return", False)
        diag.setdefault("forced_cycle_pre_drain_return_reason", None)
        diag.setdefault("forced_cycle_drain_enter", False)
        diag.setdefault("forced_cycle_drain_exit", False)
        diag.setdefault("forced_cycle_drain_runtime_seq", None)
        diag.setdefault("forced_cycle_eval_entry", False)
        diag.setdefault("forced_cycle_eval_pre_router", False)
        diag.setdefault("forced_cycle_eval_post_router", False)
        diag.setdefault("forced_cycle_eval_pre_entry_edge_check", False)
        diag.setdefault("forced_cycle_eval_post_entry_edge_check", False)
        diag.setdefault("forced_cycle_eval_bypass_reason", None)
        diag.setdefault("forced_cycle_eval_exit_reason", None)
        diag.setdefault("forced_cycle_eval_pre_selector_return_site", False)
        diag.setdefault("forced_cycle_eval_pre_selector_return_site_id", None)
        diag.setdefault("forced_cycle_eval_pre_selector_return_reason", None)
        diag.setdefault("forced_cycle_eval_pre_selector_has_selector_context", False)
        diag.setdefault("forced_cycle_eval_pre_selector_has_candidate_context", False)
        diag.setdefault("forced_cycle_eval_pre_selector_helper_result_type", None)
        diag.setdefault("forced_cycle_eval_pre_selector_callable_name", None)
        diag.setdefault("forced_cycle_eval_pre_selector_callable_module", None)
        diag.setdefault("forced_cycle_eval_pre_selector_args_summary", None)
        diag.setdefault("forced_cycle_eval_pre_selector_expected_result_type", None)
        diag.setdefault("forced_cycle_eval_pre_selector_required_fields_expected", None)
        diag.setdefault("forced_cycle_eval_pre_selector_wrapper_expected_fields", None)
        diag.setdefault("forced_cycle_eval_pre_selector_actual_return_type", None)
        diag.setdefault("forced_cycle_eval_pre_selector_actual_return_is_none", False)
        diag.setdefault("forced_cycle_eval_pre_selector_safe_return_repr", None)
        diag.setdefault("forced_cycle_eval_pre_selector_contract_failure_reason", None)
        diag.setdefault("forced_cycle_candidate_reached", False)
        diag.setdefault("forced_cycle_emit_attempt_reached", False)
        diag.setdefault("forced_cycle_emit_done_reached", False)
        diag.setdefault("forced_cycle_exit_reason", None)
        diag.setdefault("forced_cycle_result_classification", None)
        diag.setdefault("forced_cycle_runtime_seq", None)
        diag.setdefault("post_promotion_forced_cycle_verdict", None)
        diag.setdefault("post_promotion_force_cycle_handoff_enter", False)
        diag.setdefault("post_promotion_force_cycle_handoff_accept", False)
        diag.setdefault("post_promotion_force_cycle_handoff_reject", False)
        diag.setdefault("post_promotion_force_cycle_handoff_reject_reason", None)
        diag.setdefault("post_promotion_force_cycle_handoff_call_start", False)
        diag.setdefault("post_promotion_force_cycle_handoff_call_done", False)
        diag.setdefault("candidate_verdicts_seen", [])
        diag.setdefault("candidate_verdict_evidence", {})
        diag.setdefault("winning_verdict", None)
        diag.setdefault("winning_verdict_reason", None)
        diag.setdefault("transport_verdict_eligibility_reason", None)
        diag.setdefault("transport_finalist_blocker", None)
        diag.setdefault("deepest_transport_downstream_state_seen", None)
        diag.setdefault("handoff_child_dispatch_enter", False)
        diag.setdefault("handoff_child_dispatch_accept_for_processing", False)
        diag.setdefault("handoff_child_loop_enter", False)
        diag.setdefault("handoff_child_callback_enter", False)
        diag.setdefault("dispatch_site_id", None)
        diag.setdefault("callback_site_id", None)
        diag.setdefault("processing_stage", None)
        diag.setdefault("handoff_decision_emit_prelude_enter", False)
        diag.setdefault("handoff_decision_emit_prelude_exit", False)
        diag.setdefault("handoff_decision_emit_call_done", False)
        diag.setdefault("handoff_parent_enqueue_enter", False)
        diag.setdefault("handoff_parent_enqueue_done", False)
        diag.setdefault("handoff_parent_signal_sent", False)
        diag.setdefault("handoff_child_mailbox_observed", False)
        diag.setdefault("handoff_child_mailbox_dequeue_enter", False)
        diag.setdefault("transfer_site_id", None)
        diag.setdefault("mailbox_stage", None)
        diag.setdefault("handoff_transport_state", None)
        diag.setdefault("handoff_child_dispatch_enter", False)
        diag.setdefault("handoff_child_dispatch_accept_for_processing", False)
        diag.setdefault("handoff_child_loop_enter", False)
        diag.setdefault("handoff_child_callback_enter", False)
        diag.setdefault("dispatch_site_id", None)
        diag.setdefault("callback_site_id", None)
        diag.setdefault("processing_stage", None)
        diag.setdefault("handoff_pre_decision_return_site_id", None)
        diag.setdefault("handoff_pre_decision_return_reason", None)
        diag.setdefault("post_promotion_force_cycle_handoff_decision", None)
        diag.setdefault("post_promotion_force_cycle_handoff_decision_reason", None)
        diag.setdefault("post_promotion_force_cycle_handoff_decision_site_id", None)
        diag.setdefault("post_promotion_force_cycle_handoff_observation_window_enabled", None)
        diag.setdefault("post_promotion_force_cycle_handoff_observation_window_active", None)
        diag.setdefault("post_promotion_force_cycle_handoff_post_promotion_execution_lock", None)
        diag.setdefault("post_promotion_force_cycle_handoff_already_seen_forced_cycle_marker", None)
        diag.setdefault("post_promotion_force_cycle_handoff_request_enqueue_attempted", None)
        diag.setdefault("post_promotion_force_cycle_handoff_request_enqueue_completed", None)
        diag.setdefault("post_promotion_force_cycle_handoff_accept_reason", None)
        diag.setdefault("post_promotion_force_cycle_handoff_verdict", None)
        diag.setdefault("evaluation_phase", None)
        diag.setdefault("is_explicit_post_promotion_eval", False)
        diag.setdefault("is_forced_post_promotion_cycle", False)
        diag.setdefault("skip_reason", None)
        diag.setdefault("promotion_runtime_seq", None)
        diag.setdefault("reeval_runtime_seq", None)
        diag.setdefault("evaluated_path_runtime_seq", None)
        diag.setdefault("canonical_gate_read_runtime_seq", None)
        diag.setdefault("post_invoke_emit_verdict", None)
        diag.setdefault("post_promotion_stage_verdict", None)
        diag.setdefault("post_promotion_emit_verdict", None)
        return diag


def _transport_finalist_state_from_diag(diag: dict) -> tuple[str | None, str, str | None]:
    transport_state_rank = [
        ("HANDOFF_CHILD_CALLBACK_ENTERED", bool(diag.get("handoff_child_callback_enter"))),
        ("HANDOFF_CHILD_LOOP_ENTERED", bool(diag.get("handoff_child_loop_enter"))),
        ("HANDOFF_CHILD_ACCEPTED_FOR_PROCESSING", bool(diag.get("handoff_child_dispatch_accept_for_processing"))),
        ("HANDOFF_CHILD_DISPATCH_ENTERED", bool(diag.get("handoff_child_dispatch_enter"))),
        ("HANDOFF_CHILD_MAILBOX_DEQUEUED", bool(diag.get("handoff_child_mailbox_dequeue_enter"))),
        ("HANDOFF_CHILD_MAILBOX_OBSERVED", bool(diag.get("handoff_child_mailbox_observed"))),
        ("HANDOFF_PARENT_SIGNAL_SENT", bool(diag.get("handoff_parent_signal_sent"))),
        ("HANDOFF_PARENT_ENQUEUE_COMPLETED", bool(diag.get("handoff_parent_enqueue_done"))),
        ("HANDOFF_PARENT_ENQUEUE_ENTERED", bool(diag.get("handoff_parent_enqueue_enter"))),
    ]
    deepest_transport_state_seen = next((name for name, seen in transport_state_rank if seen), None)
    if not deepest_transport_state_seen:
        return None, "transport_not_observed", None
    if deepest_transport_state_seen in {
        "HANDOFF_CHILD_CALLBACK_ENTERED",
        "HANDOFF_CHILD_LOOP_ENTERED",
        "HANDOFF_CHILD_ACCEPTED_FOR_PROCESSING",
        "HANDOFF_CHILD_DISPATCH_ENTERED",
        "HANDOFF_CHILD_MAILBOX_DEQUEUED",
        "HANDOFF_CHILD_MAILBOX_OBSERVED",
        "HANDOFF_PARENT_SIGNAL_SENT",
        "HANDOFF_PARENT_ENQUEUE_COMPLETED",
    }:
        return deepest_transport_state_seen, "eligible_for_bucket_local_finalist", None
    return deepest_transport_state_seen, "transport_seen_but_not_bucket_local_finalist", "missing_downstream_reachability_state"


def _build_report_from_logs_repaired(run: dict, logs: list[dict], data_quality: dict | None = None) -> dict:
    return _build_report_from_logs_impl(run, logs, data_quality)


# legacy body retained below for reference but no longer used
def _build_report_from_logs_repaired_legacy(run: dict, logs: list[dict], data_quality: dict | None = None) -> dict:
    runner_before = run.get("before") or {}
    promotions = []
    promotion_skips = []
    gate_reads = []
    close_traces = []
    storage_write_traces = []
    pre_materialization_traces = []
    post_materialization_traces = []
    collapse_compare_traces = []
    storage_compare_traces = []
    critical_path_exceptions = []
    unresolved_rows = 0
    unresolved_reasons = Counter()
    evaluated_total = 0
    close_total = 0
    buckets = {}
    correlation_diagnostics = {}
    for event in promotions:
        corr = _corr_key(event.get("correlation_id"), event.get("canonical_key"), event.get("runtime_seq"))
        diag = correlation_diagnostics.setdefault(
            corr,
            {
                "correlation_id": corr,
                "canonical_key": event.get("canonical_key"),
                "written": False,
                "armed": False,
                "invoked": False,
                "emit_attempted": False,
                "persisted": False,
                "observed": False,
                "exception_swallowed": False,
                "final_verdict": None,
            },
        )
        _ensure_corr_diag_fields(diag)
        diag["written"] = True
    for bucket in buckets.values():
        for trace in bucket.get("explicit_post_promotion_eval_traces", []):
            corr = _corr_key(trace.get("correlation_id"), trace.get("canonical_key"), trace.get("runtime_seq"))
            diag = correlation_diagnostics.setdefault(
                corr,
                {
                    "correlation_id": corr,
                    "canonical_key": trace.get("canonical_key"),
                    "written": False,
                    "armed": False,
                    "invoked": False,
                    "emit_attempted": False,
                    "persisted": False,
                    "observed": False,
                    "exception_swallowed": False,
                    "final_verdict": None,
                },
            )
            _ensure_corr_diag_fields(diag)
            trace_name = str(trace.get("trace_event_name") or "")
            if trace_name == "canonical_explicit_post_promotion_eval_armed":
                diag["armed"] = True
            if trace_name == "canonical_explicit_post_promotion_eval_invoked":
                diag["invoked"] = True
            if trace_name == "handoff_parent_enqueue_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_enqueue_done":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_signal_sent":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["handoff_parent_signal_sent"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_observed":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_dequeue_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["handoff_child_mailbox_dequeue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "post_promotion_force_cycle_pre_drain_enter":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_enter"] = True
                diag["post_promotion_forced_cycle_verdict"] = "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
                if trace.get("canonical_key") is not None:
                    diag["canonical_key"] = trace.get("canonical_key")
                if trace.get("correlation_id") is not None:
                    diag["correlation_id"] = trace.get("correlation_id")
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("promotion_runtime_seq") is not None:
                    diag["promotion_runtime_seq"] = trace.get("promotion_runtime_seq")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_handoff_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                if trace.get("observation_window_enabled") is not None:
                    diag["post_promotion_force_cycle_handoff_observation_window_enabled"] = bool(trace.get("observation_window_enabled"))
                if trace.get("observation_window_active") is not None:
                    diag["post_promotion_force_cycle_handoff_observation_window_active"] = bool(trace.get("observation_window_active"))
                if trace.get("post_promotion_execution_lock") is not None:
                    diag["post_promotion_force_cycle_handoff_post_promotion_execution_lock"] = bool(trace.get("post_promotion_execution_lock"))
                if trace.get("already_seen_forced_cycle_marker") is not None:
                    diag["post_promotion_force_cycle_handoff_already_seen_forced_cycle_marker"] = bool(trace.get("already_seen_forced_cycle_marker"))
                if trace.get("request_enqueue_attempted") is not None:
                    diag["post_promotion_force_cycle_handoff_request_enqueue_attempted"] = bool(trace.get("request_enqueue_attempted"))
                if trace.get("request_enqueue_completed") is not None:
                    diag["post_promotion_force_cycle_handoff_request_enqueue_completed"] = bool(trace.get("request_enqueue_completed"))
            if trace_name == "post_promotion_force_cycle_handoff_accept":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_accept"] = True
                if trace.get("accept_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_accept_reason"] = trace.get("accept_reason")
                if trace.get("request_enqueue_completed") is not None:
                    diag["post_promotion_force_cycle_handoff_request_enqueue_completed"] = bool(trace.get("request_enqueue_completed"))
            if trace_name == "post_promotion_force_cycle_handoff_reject":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_reject"] = True
                if trace.get("reject_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_reject_reason"] = trace.get("reject_reason")
                if trace.get("skip_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_reject_reason"] = trace.get("skip_reason")
            if trace_name == "post_promotion_force_cycle_handoff_reject_reason":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_reject"] = True
                if trace.get("reject_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_reject_reason"] = trace.get("reject_reason")
                if trace.get("skip_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_reject_reason"] = trace.get("skip_reason")
            if trace_name == "post_promotion_force_cycle_handoff_call_start":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_accept"] = True
                diag["post_promotion_force_cycle_handoff_call_start"] = True
            if trace_name == "post_promotion_force_cycle_handoff_call_done":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_accept"] = True
                diag["post_promotion_force_cycle_handoff_call_start"] = True
                diag["post_promotion_force_cycle_handoff_call_done"] = True
            if trace_name == "handoff_decision_emit_prelude_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_decision_emit_prelude_enter"] = True
                if trace.get("handoff_pre_decision_return_site_id") is not None:
                    diag["handoff_pre_decision_return_site_id"] = trace.get("handoff_pre_decision_return_site_id")
                if trace.get("handoff_pre_decision_return_reason") is not None:
                    diag["handoff_pre_decision_return_reason"] = trace.get("handoff_pre_decision_return_reason")
            if trace_name == "handoff_decision_emit_prelude_exit":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_decision_emit_prelude_exit"] = True
            if trace_name == "handoff_decision_emit_call_done":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_decision_emit_call_done"] = True
            if trace_name == "handoff_parent_enqueue_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_enqueue_done":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_signal_sent":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["handoff_parent_signal_sent"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_observed":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_dequeue_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["handoff_child_mailbox_dequeue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_dispatch_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_dispatch_enter"] = True
                if trace.get("dispatch_site_id") is not None:
                    diag["dispatch_site_id"] = trace.get("dispatch_site_id")
                if trace.get("processing_stage") is not None:
                    diag["processing_stage"] = trace.get("processing_stage")
            if trace_name == "handoff_child_dispatch_accept_for_processing":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_dispatch_enter"] = True
                diag["handoff_child_dispatch_accept_for_processing"] = True
                if trace.get("dispatch_site_id") is not None:
                    diag["dispatch_site_id"] = trace.get("dispatch_site_id")
                if trace.get("processing_stage") is not None:
                    diag["processing_stage"] = trace.get("processing_stage")
            if trace_name == "handoff_child_loop_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_dispatch_enter"] = True
                diag["handoff_child_dispatch_accept_for_processing"] = True
                diag["handoff_child_loop_enter"] = True
                if trace.get("dispatch_site_id") is not None:
                    diag["dispatch_site_id"] = trace.get("dispatch_site_id")
                if trace.get("processing_stage") is not None:
                    diag["processing_stage"] = trace.get("processing_stage")
            if trace_name == "handoff_child_callback_enter":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["handoff_child_dispatch_enter"] = True
                diag["handoff_child_dispatch_accept_for_processing"] = True
                diag["handoff_child_loop_enter"] = True
                diag["handoff_child_callback_enter"] = True
                if trace.get("dispatch_site_id") is not None:
                    diag["dispatch_site_id"] = trace.get("dispatch_site_id")
                if trace.get("callback_site_id") is not None:
                    diag["callback_site_id"] = trace.get("callback_site_id")
                if trace.get("processing_stage") is not None:
                    diag["processing_stage"] = trace.get("processing_stage")
            if trace_name == "post_promotion_force_cycle_handoff_decision":
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["post_promotion_force_cycle_handoff_decision"] = trace.get("handoff_decision")
                if trace.get("handoff_decision_reason") is not None:
                    diag["post_promotion_force_cycle_handoff_decision_reason"] = trace.get("handoff_decision_reason")
                if trace.get("handoff_decision_site_id") is not None:
                    diag["post_promotion_force_cycle_handoff_decision_site_id"] = trace.get("handoff_decision_site_id")
                if trace.get("request_enqueue_attempted") is not None:
                    diag["post_promotion_force_cycle_handoff_request_enqueue_attempted"] = bool(trace.get("request_enqueue_attempted"))
                if trace.get("request_enqueue_completed") is not None:
                    diag["post_promotion_force_cycle_handoff_request_enqueue_completed"] = bool(trace.get("request_enqueue_completed"))
            if trace_name == "post_promotion_force_cycle_handoff_enter":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_NOT_REACHED"
            if trace_name == "post_promotion_force_cycle_handoff_accept":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED"
            if trace_name == "post_promotion_force_cycle_handoff_reject":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED"
            if trace_name == "post_promotion_force_cycle_handoff_reject_reason":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED"
            if trace_name == "post_promotion_force_cycle_handoff_call_start":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED"
            if trace_name == "post_promotion_force_cycle_handoff_call_done":
                diag["post_promotion_force_cycle_handoff_verdict"] = "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED"
            if trace_name == "handoff_decision_emit_prelude_enter":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_DECISION_EMIT_PRELUDE_ENTERED"
            if trace_name == "handoff_decision_emit_prelude_exit":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_DECISION_EMIT_PRELUDE_EXITED"
            if trace_name == "handoff_decision_emit_call_done":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_DECISION_EMIT_SITE_REACHED"
            if trace_name == "handoff_child_callback_enter":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_CHILD_CALLBACK_ENTERED"
            if trace_name == "handoff_child_loop_enter":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_CHILD_LOOP_ENTERED"
            if trace_name == "handoff_child_dispatch_accept_for_processing":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_CHILD_ACCEPTED_FOR_PROCESSING"
            if trace_name == "handoff_child_dispatch_enter":
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_CHILD_DISPATCH_ENTERED"
            if trace_name == "handoff_pre_decision_return":
                diag["handoff_pre_decision_return_site_id"] = trace.get("handoff_pre_decision_return_site_id")
                diag["handoff_pre_decision_return_reason"] = trace.get("handoff_pre_decision_return_reason")
                diag["post_promotion_force_cycle_handoff_verdict"] = "HANDOFF_PRE_DECISION_RETURN_SITE_IDENTIFIED"
            if trace_name == "post_promotion_force_cycle_handoff_decision":
                decision = str(trace.get("handoff_decision") or "").strip()
                if decision:
                    diag["post_promotion_force_cycle_handoff_verdict"] = decision
            if trace_name == "canonical_explicit_post_promotion_invoke_trace":
                diag["post_promotion_eval_arm_consumed"] = True
                diag["evaluated_path_enter_after_promotion"] = True
                if trace.get("evaluated_path_enter_after_forced_cycle") is not None:
                    diag["evaluated_path_enter_after_forced_cycle"] = bool(
                        trace.get("evaluated_path_enter_after_forced_cycle")
                    )
                if trace.get("evaluated_path_skip_reason") is not None:
                    diag["evaluated_path_skip_reason"] = trace.get("evaluated_path_skip_reason")
                if trace.get("evaluated_path_exit_reason") is not None:
                    diag["evaluated_path_exit_reason"] = trace.get("evaluated_path_exit_reason")
            if trace_name == "canonical_gate_read_branch_selector_enter":
                diag["canonical_gate_read_branch_selector_enter"] = True
            if trace_name == "canonical_gate_read_branch_selector_inputs":
                diag["canonical_gate_read_branch_selector_inputs"] = True
            if trace_name == "canonical_gate_read_branch_selector_selected_path":
                diag["canonical_gate_read_branch_selector_enter"] = True
                diag["canonical_gate_read_branch_selector_inputs"] = True
                if trace.get("canonical_gate_read_branch_selector_selected_path") is not None:
                    diag["canonical_gate_read_branch_selector_selected_path"] = trace.get("canonical_gate_read_branch_selector_selected_path")
            if trace_name == "canonical_gate_read_branch_selector_skip":
                diag["canonical_gate_read_branch_selector_skip"] = True
                if trace.get("canonical_gate_read_branch_selector_skip_reason") is not None:
                    diag["canonical_gate_read_branch_selector_skip_reason"] = trace.get("canonical_gate_read_branch_selector_skip_reason")
            if trace_name == "canonical_gate_read_emit_candidate":
                diag["canonical_gate_read_emit_candidate"] = True
            if trace_name == "canonical_gate_read_emit_guard_considered":
                diag["canonical_gate_read_emit_guard_considered"] = True
            if trace_name == "canonical_gate_read_emit_guard_blocked":
                diag["canonical_gate_read_emit_guard_blocked"] = True
            if trace_name == "canonical_gate_read_emit_payload_built":
                diag["canonical_gate_read_emit_payload_built"] = True
            if trace_name == "canonical_gate_read_emit_attempt":
                diag["canonical_gate_read_emit_attempt"] = True
            if trace_name == "canonical_gate_read_emit_done":
                diag["canonical_gate_read_emit_done"] = True
            diag["post_invoke_emit_path_enter"] = bool(
                diag["post_invoke_emit_path_enter"] or trace.get("post_invoke_emit_path_enter")
            )
            diag["post_invoke_emit_guard_considered"] = bool(
                diag["post_invoke_emit_guard_considered"] or trace.get("post_invoke_emit_guard_considered")
            )
            diag["post_invoke_emit_guard_allowed"] = bool(
                diag["post_invoke_emit_guard_allowed"] or trace.get("post_invoke_emit_guard_allowed")
            )
            if trace.get("post_invoke_emit_guard_reason") is not None:
                diag["post_invoke_emit_guard_reason"] = trace.get("post_invoke_emit_guard_reason")
            diag["post_invoke_emit_early_return"] = bool(
                diag["post_invoke_emit_early_return"] or trace.get("post_invoke_emit_early_return")
            )
            if trace.get("post_invoke_emit_early_return_reason") is not None:
                diag["post_invoke_emit_early_return_reason"] = trace.get("post_invoke_emit_early_return_reason")
            diag["post_invoke_emit_attempt_reached"] = bool(
                diag["post_invoke_emit_attempt_reached"] or trace.get("post_invoke_emit_attempt_reached")
            )
            if trace.get("post_invoke_emit_micro_stage") is not None:
                diag["post_invoke_emit_micro_stage"] = trace.get("post_invoke_emit_micro_stage")
            diag["post_invoke_emit_hidden_branch_taken"] = bool(
                diag["post_invoke_emit_hidden_branch_taken"] or trace.get("post_invoke_emit_hidden_branch_taken")
            )
            if trace.get("post_invoke_emit_hidden_branch_reason") is not None:
                diag["post_invoke_emit_hidden_branch_reason"] = trace.get("post_invoke_emit_hidden_branch_reason")
            diag["post_invoke_emit_local_return"] = bool(
                diag["post_invoke_emit_local_return"] or trace.get("post_invoke_emit_local_return")
            )
            if trace.get("post_invoke_emit_local_return_reason") is not None:
                diag["post_invoke_emit_local_return_reason"] = trace.get("post_invoke_emit_local_return_reason")
            if trace.get("post_invoke_emit_exception_class") is not None:
                diag["post_invoke_emit_exception_class"] = trace.get("post_invoke_emit_exception_class")
            if trace.get("post_invoke_emit_exception_message") is not None:
                diag["post_invoke_emit_exception_message"] = trace.get("post_invoke_emit_exception_message")
            diag["post_invoke_emit_attempt_call_enter"] = bool(
                diag["post_invoke_emit_attempt_call_enter"] or trace.get("post_invoke_emit_attempt_call_enter")
            )
            if trace.get("canonical_gate_read_emit_guard_reason") is not None:
                diag["canonical_gate_read_emit_guard_reason"] = trace.get("canonical_gate_read_emit_guard_reason")
            if trace.get("evaluation_phase") is not None:
                diag["evaluation_phase"] = trace.get("evaluation_phase")
            if trace.get("is_explicit_post_promotion_eval") is not None:
                diag["is_explicit_post_promotion_eval"] = bool(trace.get("is_explicit_post_promotion_eval"))
            if trace.get("skip_reason") is not None:
                diag["skip_reason"] = trace.get("skip_reason")
        for trace in bucket.get("forced_cycle_traces", []):
            corr = _corr_key(trace.get("correlation_id"), trace.get("canonical_key"), trace.get("runtime_seq"))
            diag = correlation_diagnostics.setdefault(
                corr,
                {
                    "correlation_id": corr,
                    "canonical_key": trace.get("canonical_key"),
                    "written": False,
                    "armed": False,
                    "invoked": False,
                    "emit_attempted": False,
                    "persisted": False,
                    "observed": False,
                    "exception_swallowed": False,
                    "final_verdict": None,
                },
            )
            _ensure_corr_diag_fields(diag)
            trace_name = str(trace.get("trace_event_name") or "")
            if trace_name == "post_promotion_force_cycle_request":
                diag["forced_cycle_requested"] = True
            if trace_name == "forced_cycle_requested":
                diag["forced_cycle_requested"] = True
            if trace_name == "forced_cycle_enter":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_started"] = True
                diag["forced_cycle_enter"] = True
                if trace.get("forced_cycle_runtime_seq") is not None:
                    diag["forced_cycle_runtime_seq"] = trace.get("forced_cycle_runtime_seq")
                if trace.get("evaluation_phase") is not None:
                    diag["evaluation_phase"] = trace.get("evaluation_phase")
                if trace.get("is_forced_post_promotion_cycle") is not None:
                    diag["is_forced_post_promotion_cycle"] = bool(trace.get("is_forced_post_promotion_cycle"))
            if trace_name == "forced_cycle_started":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_started"] = True
            if trace_name == "post_promotion_force_cycle_scheduler_tick_enter":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_tick_enter"] = True
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
                if trace.get("forced_cycle_request_runtime_seq") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("forced_cycle_request_runtime_seq")
            if trace_name == "post_promotion_force_cycle_scheduler_tick_exit":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_scheduler_tick_exit"] = True
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
                if trace.get("forced_cycle_request_runtime_seq") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("forced_cycle_request_runtime_seq")
            if trace_name == "post_promotion_force_cycle_request_scan_enter":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_enter"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_request_scan_result":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_result"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_request_scan_empty":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_empty"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_request_scan_nonempty":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_request_scan_nonempty"] = True
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("scan_reason") is not None:
                    diag["scan_reason"] = trace.get("scan_reason")
                if trace.get("tick_reason") is not None:
                    diag["tick_reason"] = trace.get("tick_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_candidate":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
                if trace.get("pre_drain_reject_reason") is not None:
                    diag["forced_cycle_pre_drain_reject_reason"] = trace.get("pre_drain_reject_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_reject":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_reject"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
                if trace.get("pre_drain_reject_reason") is not None:
                    diag["forced_cycle_pre_drain_reject_reason"] = trace.get("pre_drain_reject_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_reject_reason":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_reject"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
                if trace.get("pre_drain_reject_reason") is not None:
                    diag["forced_cycle_pre_drain_reject_reason"] = trace.get("pre_drain_reject_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_enter":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_enter"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_skip":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_reject"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
                if trace.get("pre_drain_skip_reason") is not None:
                    diag["forced_cycle_pre_drain_reject_reason"] = trace.get("pre_drain_skip_reason")
            if trace_name == "post_promotion_force_cycle_pre_drain_return":
                diag["forced_cycle_requested"] = True
                diag["post_promotion_force_cycle_handoff_enter"] = True
                diag["forced_cycle_pre_drain_candidate"] = True
                diag["forced_cycle_pre_drain_return"] = True
                if trace.get("request_id") is not None:
                    diag["forced_cycle_request_runtime_seq"] = trace.get("request_id")
                if trace.get("request_count_seen") is not None:
                    diag["request_count_seen"] = trace.get("request_count_seen")
                if trace.get("gate_reason") is not None:
                    diag["gate_reason"] = trace.get("gate_reason")
                if trace.get("visibility_reason") is not None:
                    diag["visibility_reason"] = trace.get("visibility_reason")
                if trace.get("pre_drain_return_reason") is not None:
                    diag["forced_cycle_pre_drain_return_reason"] = trace.get("pre_drain_return_reason")
            if trace_name == "post_promotion_force_cycle_drain_enter":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_drain_enter"] = True
                if trace.get("runtime_seq") is not None:
                    diag["forced_cycle_drain_runtime_seq"] = trace.get("runtime_seq")
            if trace_name == "post_promotion_force_cycle_drain_exit":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_drain_exit"] = True
                if trace.get("runtime_seq") is not None:
                    diag["forced_cycle_drain_runtime_seq"] = trace.get("runtime_seq")
            if trace_name == "handoff_parent_enqueue_enter":
                diag["forced_cycle_requested"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_enqueue_done":
                diag["forced_cycle_requested"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_parent_signal_sent":
                diag["forced_cycle_requested"] = True
                diag["handoff_parent_enqueue_enter"] = True
                diag["handoff_parent_enqueue_done"] = True
                diag["handoff_parent_signal_sent"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_observed":
                diag["forced_cycle_requested"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "handoff_child_mailbox_dequeue_enter":
                diag["forced_cycle_requested"] = True
                diag["handoff_child_mailbox_observed"] = True
                diag["handoff_child_mailbox_dequeue_enter"] = True
                diag["transfer_site_id"] = trace.get("transfer_site_id")
                diag["mailbox_stage"] = trace.get("mailbox_stage")
                diag["handoff_transport_state"] = trace.get("handoff_transport_state")
            if trace_name == "forced_cycle_completed":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_started"] = True
                diag["forced_cycle_enter"] = True
                diag["forced_cycle_completed"] = True
                if trace.get("candidate_reached") is not None:
                    diag["forced_cycle_candidate_reached"] = bool(trace.get("candidate_reached"))
                if trace.get("emit_attempt_reached") is not None:
                    diag["forced_cycle_emit_attempt_reached"] = bool(trace.get("emit_attempt_reached"))
                if trace.get("emit_done_reached") is not None:
                    diag["forced_cycle_emit_done_reached"] = bool(trace.get("emit_done_reached"))
                if trace.get("forced_cycle_exit_reason") is not None:
                    diag["forced_cycle_exit_reason"] = trace.get("forced_cycle_exit_reason")
                if trace.get("forced_cycle_result_classification") is not None:
                    diag["forced_cycle_result_classification"] = trace.get("forced_cycle_result_classification")
                if trace.get("forced_cycle_eval_pre_selector_return_site") is not None:
                    diag["forced_cycle_eval_pre_selector_return_site"] = bool(trace.get("forced_cycle_eval_pre_selector_return_site"))
                if trace.get("forced_cycle_eval_pre_selector_return_site_id") is not None:
                    diag["forced_cycle_eval_pre_selector_return_site_id"] = trace.get("forced_cycle_eval_pre_selector_return_site_id")
                if trace.get("forced_cycle_eval_pre_selector_return_reason") is not None:
                    diag["forced_cycle_eval_pre_selector_return_reason"] = trace.get("forced_cycle_eval_pre_selector_return_reason")
                if trace.get("forced_cycle_eval_pre_selector_has_selector_context") is not None:
                    diag["forced_cycle_eval_pre_selector_has_selector_context"] = bool(trace.get("forced_cycle_eval_pre_selector_has_selector_context"))
                if trace.get("forced_cycle_eval_pre_selector_has_candidate_context") is not None:
                    diag["forced_cycle_eval_pre_selector_has_candidate_context"] = bool(trace.get("forced_cycle_eval_pre_selector_has_candidate_context"))
                if trace.get("forced_cycle_eval_pre_selector_helper_result_type") is not None:
                    diag["forced_cycle_eval_pre_selector_helper_result_type"] = trace.get("forced_cycle_eval_pre_selector_helper_result_type")
                if trace.get("forced_cycle_eval_pre_selector_callable_name") is not None:
                    diag["forced_cycle_eval_pre_selector_callable_name"] = trace.get("forced_cycle_eval_pre_selector_callable_name")
                if trace.get("forced_cycle_eval_pre_selector_callable_module") is not None:
                    diag["forced_cycle_eval_pre_selector_callable_module"] = trace.get("forced_cycle_eval_pre_selector_callable_module")
                if trace.get("forced_cycle_eval_pre_selector_args_summary") is not None:
                    diag["forced_cycle_eval_pre_selector_args_summary"] = trace.get("forced_cycle_eval_pre_selector_args_summary")
                if trace.get("forced_cycle_eval_pre_selector_expected_result_type") is not None:
                    diag["forced_cycle_eval_pre_selector_expected_result_type"] = trace.get("forced_cycle_eval_pre_selector_expected_result_type")
                if trace.get("forced_cycle_eval_pre_selector_required_fields_expected") is not None:
                    diag["forced_cycle_eval_pre_selector_required_fields_expected"] = trace.get("forced_cycle_eval_pre_selector_required_fields_expected")
                if trace.get("forced_cycle_eval_pre_selector_wrapper_expected_fields") is not None:
                    diag["forced_cycle_eval_pre_selector_wrapper_expected_fields"] = trace.get("forced_cycle_eval_pre_selector_wrapper_expected_fields")
                if trace.get("forced_cycle_eval_pre_selector_actual_return_type") is not None:
                    diag["forced_cycle_eval_pre_selector_actual_return_type"] = trace.get("forced_cycle_eval_pre_selector_actual_return_type")
                if trace.get("forced_cycle_eval_pre_selector_actual_return_is_none") is not None:
                    diag["forced_cycle_eval_pre_selector_actual_return_is_none"] = bool(trace.get("forced_cycle_eval_pre_selector_actual_return_is_none"))
                if trace.get("forced_cycle_eval_pre_selector_safe_return_repr") is not None:
                    diag["forced_cycle_eval_pre_selector_safe_return_repr"] = trace.get("forced_cycle_eval_pre_selector_safe_return_repr")
                if trace.get("forced_cycle_eval_pre_selector_contract_failure_reason") is not None:
                    diag["forced_cycle_eval_pre_selector_contract_failure_reason"] = trace.get("forced_cycle_eval_pre_selector_contract_failure_reason")
            if trace_name in {
                "forced_cycle_eval_entry",
                "forced_cycle_eval_pre_router",
                "forced_cycle_eval_post_router",
                "forced_cycle_eval_pre_entry_edge_check",
                "forced_cycle_eval_post_entry_edge_check",
                "forced_cycle_eval_bypass",
                "forced_cycle_eval_pre_selector_return_site",
            }:
                diag["forced_cycle_requested"] = True
                if trace_name == "forced_cycle_eval_entry":
                    diag["forced_cycle_eval_entry"] = True
                if trace_name == "forced_cycle_eval_pre_router":
                    diag["forced_cycle_eval_pre_router"] = True
                if trace_name == "forced_cycle_eval_post_router":
                    diag["forced_cycle_eval_post_router"] = True
                if trace_name == "forced_cycle_eval_pre_entry_edge_check":
                    diag["forced_cycle_eval_pre_entry_edge_check"] = True
                if trace_name == "forced_cycle_eval_post_entry_edge_check":
                    diag["forced_cycle_eval_post_entry_edge_check"] = True
                if trace_name == "forced_cycle_eval_pre_selector_return_site":
                    diag["forced_cycle_eval_pre_selector_return_site"] = True
                    if trace.get("return_site_id") is not None:
                        diag["forced_cycle_eval_pre_selector_return_site_id"] = trace.get("return_site_id")
                    if trace.get("return_reason") is not None:
                        diag["forced_cycle_eval_pre_selector_return_reason"] = trace.get("return_reason")
                    if trace.get("has_selector_context") is not None:
                        diag["forced_cycle_eval_pre_selector_has_selector_context"] = bool(trace.get("has_selector_context"))
                    if trace.get("has_candidate_context") is not None:
                        diag["forced_cycle_eval_pre_selector_has_candidate_context"] = bool(trace.get("has_candidate_context"))
                    if trace.get("helper_result_type") is not None:
                        diag["forced_cycle_eval_pre_selector_helper_result_type"] = trace.get("helper_result_type")
                    if trace.get("callable_name") is not None:
                        diag["forced_cycle_eval_pre_selector_callable_name"] = trace.get("callable_name")
                    if trace.get("callable_module") is not None:
                        diag["forced_cycle_eval_pre_selector_callable_module"] = trace.get("callable_module")
                    if trace.get("args_summary") is not None:
                        diag["forced_cycle_eval_pre_selector_args_summary"] = trace.get("args_summary")
                    if trace.get("expected_result_type") is not None:
                        diag["forced_cycle_eval_pre_selector_expected_result_type"] = trace.get("expected_result_type")
                    if trace.get("required_fields_expected") is not None:
                        diag["forced_cycle_eval_pre_selector_required_fields_expected"] = trace.get("required_fields_expected")
                    if trace.get("wrapper_expected_fields") is not None:
                        diag["forced_cycle_eval_pre_selector_wrapper_expected_fields"] = trace.get("wrapper_expected_fields")
                    if trace.get("actual_return_type") is not None:
                        diag["forced_cycle_eval_pre_selector_actual_return_type"] = trace.get("actual_return_type")
                    if trace.get("actual_return_is_none") is not None:
                        diag["forced_cycle_eval_pre_selector_actual_return_is_none"] = bool(trace.get("actual_return_is_none"))
                    if trace.get("safe_return_repr") is not None:
                        diag["forced_cycle_eval_pre_selector_safe_return_repr"] = trace.get("safe_return_repr")
                    if trace.get("contract_failure_reason") is not None:
                        diag["forced_cycle_eval_pre_selector_contract_failure_reason"] = trace.get("contract_failure_reason")
                if trace.get("forced_cycle_eval_exit_reason") is not None:
                    diag["forced_cycle_eval_exit_reason"] = trace.get("forced_cycle_eval_exit_reason")
                if trace.get("forced_cycle_eval_bypass_reason") is not None:
                    diag["forced_cycle_eval_bypass_reason"] = trace.get("forced_cycle_eval_bypass_reason")
            if trace_name == "forced_cycle_failed":
                diag["forced_cycle_requested"] = True
                diag["forced_cycle_failed"] = True
                if trace.get("forced_cycle_runtime_seq") is not None:
                    diag["forced_cycle_runtime_seq"] = trace.get("forced_cycle_runtime_seq")
                if trace.get("forced_cycle_exit_reason") is not None:
                    diag["forced_cycle_exit_reason"] = trace.get("forced_cycle_exit_reason")
                if trace.get("forced_cycle_result_classification") is not None:
                    diag["forced_cycle_result_classification"] = trace.get("forced_cycle_result_classification")
                if trace.get("forced_cycle_eval_pre_selector_return_site") is not None:
                    diag["forced_cycle_eval_pre_selector_return_site"] = bool(trace.get("forced_cycle_eval_pre_selector_return_site"))
                if trace.get("forced_cycle_eval_pre_selector_return_site_id") is not None:
                    diag["forced_cycle_eval_pre_selector_return_site_id"] = trace.get("forced_cycle_eval_pre_selector_return_site_id")
                if trace.get("forced_cycle_eval_pre_selector_return_reason") is not None:
                    diag["forced_cycle_eval_pre_selector_return_reason"] = trace.get("forced_cycle_eval_pre_selector_return_reason")
                if trace.get("forced_cycle_eval_pre_selector_has_selector_context") is not None:
                    diag["forced_cycle_eval_pre_selector_has_selector_context"] = bool(trace.get("forced_cycle_eval_pre_selector_has_selector_context"))
                if trace.get("forced_cycle_eval_pre_selector_has_candidate_context") is not None:
                    diag["forced_cycle_eval_pre_selector_has_candidate_context"] = bool(trace.get("forced_cycle_eval_pre_selector_has_candidate_context"))
                if trace.get("forced_cycle_eval_pre_selector_helper_result_type") is not None:
                    diag["forced_cycle_eval_pre_selector_helper_result_type"] = trace.get("forced_cycle_eval_pre_selector_helper_result_type")
                if trace.get("forced_cycle_eval_pre_selector_callable_name") is not None:
                    diag["forced_cycle_eval_pre_selector_callable_name"] = trace.get("forced_cycle_eval_pre_selector_callable_name")
                if trace.get("forced_cycle_eval_pre_selector_callable_module") is not None:
                    diag["forced_cycle_eval_pre_selector_callable_module"] = trace.get("forced_cycle_eval_pre_selector_callable_module")
                if trace.get("forced_cycle_eval_pre_selector_args_summary") is not None:
                    diag["forced_cycle_eval_pre_selector_args_summary"] = trace.get("forced_cycle_eval_pre_selector_args_summary")
                if trace.get("forced_cycle_eval_pre_selector_expected_result_type") is not None:
                    diag["forced_cycle_eval_pre_selector_expected_result_type"] = trace.get("forced_cycle_eval_pre_selector_expected_result_type")
                if trace.get("forced_cycle_eval_pre_selector_required_fields_expected") is not None:
                    diag["forced_cycle_eval_pre_selector_required_fields_expected"] = trace.get("forced_cycle_eval_pre_selector_required_fields_expected")
                if trace.get("forced_cycle_eval_pre_selector_wrapper_expected_fields") is not None:
                    diag["forced_cycle_eval_pre_selector_wrapper_expected_fields"] = trace.get("forced_cycle_eval_pre_selector_wrapper_expected_fields")
                if trace.get("forced_cycle_eval_pre_selector_actual_return_type") is not None:
                    diag["forced_cycle_eval_pre_selector_actual_return_type"] = trace.get("forced_cycle_eval_pre_selector_actual_return_type")
                if trace.get("forced_cycle_eval_pre_selector_actual_return_is_none") is not None:
                    diag["forced_cycle_eval_pre_selector_actual_return_is_none"] = bool(trace.get("forced_cycle_eval_pre_selector_actual_return_is_none"))
                if trace.get("forced_cycle_eval_pre_selector_safe_return_repr") is not None:
                    diag["forced_cycle_eval_pre_selector_safe_return_repr"] = trace.get("forced_cycle_eval_pre_selector_safe_return_repr")
                if trace.get("forced_cycle_eval_pre_selector_contract_failure_reason") is not None:
                    diag["forced_cycle_eval_pre_selector_contract_failure_reason"] = trace.get("forced_cycle_eval_pre_selector_contract_failure_reason")
    for event in gate_reads:
        corr = _corr_key(event.get("correlation_id"), event.get("canonical_key"), event.get("runtime_seq"))
        diag = correlation_diagnostics.setdefault(
            corr,
            {
                "correlation_id": corr,
                "canonical_key": event.get("canonical_key"),
                "written": False,
                "armed": False,
                "invoked": False,
                "emit_attempted": False,
                "persisted": False,
                "observed": False,
                "exception_swallowed": False,
                "final_verdict": None,
            },
        )
        _ensure_corr_diag_fields(diag)
        if bool(event.get("override_type") == "explicit_post_promotion_eval"):
            diag["emit_attempted"] = True
        diag["canonical_gate_read_emit_candidate"] = bool(
            diag["canonical_gate_read_emit_candidate"] or event.get("canonical_gate_read_emit_candidate")
        )
        diag["canonical_gate_read_emit_guard_considered"] = bool(
            diag["canonical_gate_read_emit_guard_considered"] or event.get("canonical_gate_read_emit_guard_considered")
        )
        diag["canonical_gate_read_emit_guard_blocked"] = bool(
            diag["canonical_gate_read_emit_guard_blocked"] or event.get("canonical_gate_read_emit_guard_blocked")
        )
        if event.get("canonical_gate_read_emit_guard_reason") is not None:
            diag["canonical_gate_read_emit_guard_reason"] = event.get("canonical_gate_read_emit_guard_reason")
        diag["canonical_gate_read_emit_payload_built"] = bool(
            diag["canonical_gate_read_emit_payload_built"] or event.get("canonical_gate_read_emit_payload_built")
        )
        diag["canonical_gate_read_emit_attempt"] = bool(
            diag["canonical_gate_read_emit_attempt"] or event.get("canonical_gate_read_emit_attempt")
        )
        diag["canonical_gate_read_emit_done"] = bool(
            diag["canonical_gate_read_emit_done"] or event.get("canonical_gate_read_emit_done")
        )
        if event.get("evaluation_phase") is not None:
            diag["evaluation_phase"] = event.get("evaluation_phase")
        if event.get("is_explicit_post_promotion_eval") is not None:
            diag["is_explicit_post_promotion_eval"] = bool(event.get("is_explicit_post_promotion_eval"))
        if event.get("skip_reason") is not None:
            diag["skip_reason"] = event.get("skip_reason")
        diag["post_invoke_emit_path_enter"] = bool(
            diag["post_invoke_emit_path_enter"] or event.get("post_invoke_emit_path_enter")
        )
        diag["post_invoke_emit_guard_considered"] = bool(
            diag["post_invoke_emit_guard_considered"] or event.get("post_invoke_emit_guard_considered")
        )
        diag["post_invoke_emit_guard_allowed"] = bool(
            diag["post_invoke_emit_guard_allowed"] or event.get("post_invoke_emit_guard_allowed")
        )
        if event.get("post_invoke_emit_guard_reason") is not None:
            diag["post_invoke_emit_guard_reason"] = event.get("post_invoke_emit_guard_reason")
        diag["post_invoke_emit_early_return"] = bool(
            diag["post_invoke_emit_early_return"] or event.get("post_invoke_emit_early_return")
        )
        if event.get("post_invoke_emit_early_return_reason") is not None:
            diag["post_invoke_emit_early_return_reason"] = event.get("post_invoke_emit_early_return_reason")
        diag["post_invoke_emit_attempt_reached"] = bool(
            diag["post_invoke_emit_attempt_reached"] or event.get("post_invoke_emit_attempt_reached")
        )
        diag["post_invoke_emit_attempt_call_enter"] = bool(
            diag["post_invoke_emit_attempt_call_enter"] or event.get("post_invoke_emit_attempt_call_enter")
        )
        diag["persisted"] = True
        if int(event.get("read_trade_count") or 0) > 0:
            diag["observed"] = True
    for event in storage_compare_traces:
        corr = _corr_key(event.get("correlation_id"), event.get("canonical_key"), event.get("runtime_seq"))
        diag = correlation_diagnostics.setdefault(
            corr,
            {
                "correlation_id": corr,
                "canonical_key": event.get("canonical_key"),
                "written": False,
                "armed": False,
                "invoked": False,
                "emit_attempted": False,
                "persisted": False,
                "observed": False,
                "exception_swallowed": False,
                "final_verdict": None,
            },
        )
        _ensure_corr_diag_fields(diag)
        diag["written"] = bool(diag["written"] or event.get("stage_written"))
        diag["emit_attempted"] = bool(
            diag["emit_attempted"] or event.get("stage_emit_attempted")
        )
        diag["persisted"] = bool(diag["persisted"] or event.get("stage_persisted"))
        diag["observed"] = bool(diag["observed"] or event.get("stage_observed"))
        diag["exception_swallowed"] = bool(
            diag["exception_swallowed"] or event.get("stage_exception")
        )
        if event.get("final_per_correlation_verdict"):
            diag["final_verdict"] = event.get("final_per_correlation_verdict")
    for event in critical_path_exceptions:
        corr = _corr_key(event.get("correlation_id"), event.get("canonical_key"), event.get("runtime_seq"))
        diag = correlation_diagnostics.setdefault(
            corr,
            {
                "correlation_id": corr,
                "canonical_key": event.get("canonical_key"),
                "written": False,
                "armed": False,
                "invoked": False,
                "emit_attempted": False,
                "persisted": False,
                "observed": False,
                "exception_swallowed": False,
                "final_verdict": None,
            },
        )
        _ensure_corr_diag_fields(diag)
        diag["exception_swallowed"] = True

    for diag in correlation_diagnostics.values():
        if diag["final_verdict"] is None:
            if diag["exception_swallowed"]:
                diag["final_verdict"] = "EXCEPTION_SWALLOWED_IN_CRITICAL_PATH"
            elif diag["written"] and diag["observed"]:
                diag["final_verdict"] = "WRITE_SUCCEEDED_READBACK_CONFIRMED"
            elif diag["written"] and not diag["emit_attempted"]:
                diag["final_verdict"] = "WRITE_SUCCEEDED_BUT_EMIT_NOT_ATTEMPTED"
            elif diag["emit_attempted"] and not diag["persisted"]:
                diag["final_verdict"] = "EMIT_ATTEMPTED_BUT_NOT_PERSISTED"
            elif diag["persisted"] and not diag["observed"]:
                diag["final_verdict"] = "PERSISTED_BUT_NOT_OBSERVED"
            else:
                diag["final_verdict"] = "WRITE_SUCCEEDED_BUT_EMIT_NOT_ATTEMPTED"
        if diag["post_invoke_emit_verdict"] is None:
            if diag["post_invoke_emit_attempt_call_enter"] or diag["post_invoke_emit_attempt_reached"]:
                diag["post_invoke_emit_verdict"] = "EMIT_ATTEMPT_CALL_REACHED"
            elif diag["post_invoke_emit_exception_class"]:
                diag["post_invoke_emit_verdict"] = "EXCEPTION_BEFORE_EMIT_ATTEMPT"
            elif diag["post_invoke_emit_local_return"] or diag["post_invoke_emit_early_return"]:
                diag["post_invoke_emit_verdict"] = "LOCAL_RETURN_BLOCKS_EMIT_ATTEMPT"
            elif diag["post_invoke_emit_hidden_branch_taken"]:
                diag["post_invoke_emit_verdict"] = "HIDDEN_BRANCH_BLOCKS_EMIT_ATTEMPT"
            else:
                diag["post_invoke_emit_verdict"] = "INSUFFICIENT_CODE_EVIDENCE"

    reevaluation_completed = bool(runner_before.get("post_promotion_reeval_completed"))
    reeval_result = str(runner_before.get("post_promotion_reeval_result") or "")
    emit_verdict_counts = Counter()
    branch_verdict_counts = Counter()
    handoff_verdict_counts = Counter()
    forced_cycle_verdict_counts = Counter()
    first_missing_emit_stage_after_reeval = "INSUFFICIENT_RUNTIME_EVIDENCE"
    first_missing_branch_stage_after_reeval = "INSUFFICIENT_RUNTIME_EVIDENCE"
    if reevaluation_completed:
        for diag in correlation_diagnostics.values():
            candidate_verdicts_seen = []
            candidate_verdict_evidence = {}
            if diag["observed"]:
                emit_verdict = "CANONICAL_GATE_READ_OBSERVED"
            elif not diag["evaluated_path_enter_after_promotion"]:
                emit_verdict = "REEVAL_COMPLETES_BUT_EVALUATED_PATH_NOT_ENTERED"
            elif not diag["canonical_gate_read_emit_candidate"]:
                emit_verdict = "EVALUATED_PATH_REENTERED_BUT_EMIT_ATTEMPT_NOT_REACHED"
            elif diag["canonical_gate_read_emit_guard_blocked"]:
                emit_verdict = "EMIT_GUARD_BLOCKED_WITH_REASON"
            elif diag["canonical_gate_read_emit_attempt"] and not diag["canonical_gate_read_emit_done"]:
                emit_verdict = "EMIT_ATTEMPT_REACHED_BUT_NOT_COMPLETED"
            elif diag["canonical_gate_read_emit_payload_built"] and not diag["canonical_gate_read_emit_attempt"]:
                emit_verdict = "EVALUATED_PATH_REENTERED_BUT_EMIT_ATTEMPT_NOT_REACHED"
            else:
                emit_verdict = "EVALUATED_PATH_REENTERED_BUT_EMIT_ATTEMPT_NOT_REACHED"
            diag["post_promotion_emit_verdict"] = emit_verdict
            emit_verdict_counts[emit_verdict] += 1
            candidate_verdicts_seen.append(emit_verdict)
            candidate_verdict_evidence[emit_verdict] = {
                "evidence_type": "emit_stage",
                "observed": bool(diag["observed"]),
                "evaluated_path_enter_after_promotion": bool(diag["evaluated_path_enter_after_promotion"]),
                "canonical_gate_read_emit_candidate": bool(diag["canonical_gate_read_emit_candidate"]),
                "canonical_gate_read_emit_guard_considered": bool(diag["canonical_gate_read_emit_guard_considered"]),
                "canonical_gate_read_emit_guard_blocked": bool(diag["canonical_gate_read_emit_guard_blocked"]),
                "canonical_gate_read_emit_attempt": bool(diag["canonical_gate_read_emit_attempt"]),
                "canonical_gate_read_emit_done": bool(diag["canonical_gate_read_emit_done"]),
            }

            if diag["observed"]:
                branch_verdict = "CANONICAL_GATE_READ_OBSERVED"
            elif diag["handoff_child_mailbox_dequeue_enter"]:
                branch_verdict = "HANDOFF_CHILD_MAILBOX_DEQUEUED"
            elif diag["handoff_child_mailbox_observed"]:
                branch_verdict = "HANDOFF_CHILD_MAILBOX_OBSERVED"
            elif diag["handoff_parent_signal_sent"]:
                branch_verdict = "HANDOFF_PARENT_SIGNAL_SENT"
            elif diag["handoff_parent_enqueue_done"]:
                branch_verdict = "HANDOFF_PARENT_ENQUEUE_COMPLETED"
            elif diag["handoff_parent_enqueue_enter"]:
                branch_verdict = "HANDOFF_PARENT_ENQUEUE_ENTERED"
            elif not diag["evaluated_path_enter_after_promotion"]:
                branch_verdict = "REEVAL_COMPLETES_BUT_EVALUATED_PATH_NOT_ENTERED"
            elif diag["canonical_gate_read_branch_selector_skip"] or str(
                diag["canonical_gate_read_branch_selector_selected_path"] or ""
            ) == "skip":
                branch_verdict = "PRE_CANDIDATE_BRANCH_SKIPPED_WITH_REASON"
            elif diag["canonical_gate_read_emit_candidate"]:
                if not diag["canonical_gate_read_emit_guard_considered"]:
                    branch_verdict = "CANDIDATE_BRANCH_REACHED_BUT_GUARD_NOT_ENTERED"
                elif diag["canonical_gate_read_emit_guard_blocked"]:
                    branch_verdict = "CANDIDATE_BRANCH_REACHED_AND_GUARD_BLOCKED"
                elif diag["canonical_gate_read_emit_attempt"]:
                    branch_verdict = "CANDIDATE_BRANCH_REACHED_AND_EMIT_ATTEMPT_REACHED"
                else:
                    branch_verdict = "CANDIDATE_BRANCH_REACHED_BUT_GUARD_NOT_ENTERED"
            else:
                branch_verdict = "EVALUATED_PATH_REENTERED_BUT_PRE_CANDIDATE_BRANCH_NOT_REACHED"
            diag["post_promotion_stage_verdict"] = branch_verdict
            branch_verdict_counts[branch_verdict] += 1
            candidate_verdicts_seen.append(branch_verdict)
            candidate_verdict_evidence[branch_verdict] = {
                "evidence_type": "branch_stage",
                "observed": bool(diag["observed"]),
                "handoff_parent_enqueue_enter": bool(diag["handoff_parent_enqueue_enter"]),
                "handoff_parent_enqueue_done": bool(diag["handoff_parent_enqueue_done"]),
                "handoff_parent_signal_sent": bool(diag["handoff_parent_signal_sent"]),
                "handoff_child_mailbox_observed": bool(diag["handoff_child_mailbox_observed"]),
                "handoff_child_mailbox_dequeue_enter": bool(diag["handoff_child_mailbox_dequeue_enter"]),
                "evaluated_path_enter_after_promotion": bool(diag["evaluated_path_enter_after_promotion"]),
                "canonical_gate_read_branch_selector_enter": bool(diag["canonical_gate_read_branch_selector_enter"]),
                "canonical_gate_read_emit_candidate": bool(diag["canonical_gate_read_emit_candidate"]),
            }

            forced_cycle_evidence = bool(
                diag["post_promotion_force_cycle_handoff_enter"]
                or diag["post_promotion_force_cycle_handoff_accept"]
                or diag["post_promotion_force_cycle_handoff_call_start"]
                or diag["post_promotion_force_cycle_handoff_call_done"]
                or diag["forced_cycle_scheduler_gate_enter"]
                or diag["forced_cycle_scheduler_gate_result"]
                or diag["forced_cycle_scheduler_gate_blocked"]
                or diag["forced_cycle_scheduler_gate_allowed"]
                or diag["forced_cycle_eval_entry"]
                or diag["forced_cycle_eval_pre_router"]
                or diag["forced_cycle_eval_post_router"]
                or diag["forced_cycle_eval_pre_entry_edge_check"]
                or diag["forced_cycle_eval_post_entry_edge_check"]
                or diag["forced_cycle_requested"]
                or diag["forced_cycle_eval_pre_selector_return_site"]
                or diag["forced_cycle_started"]
                or diag["forced_cycle_completed"]
                or diag["forced_cycle_failed"]
            )
            if forced_cycle_evidence:
                handoff_verdict = classify_post_promotion_force_cycle_handoff_trace(diag)
                diag["post_promotion_force_cycle_handoff_verdict"] = handoff_verdict
                handoff_verdict_counts[handoff_verdict] += 1
                candidate_verdicts_seen.append(handoff_verdict)
                candidate_verdict_evidence[handoff_verdict] = {
                    "evidence_type": "handoff_stage",
                    "post_promotion_force_cycle_handoff_enter": bool(diag["post_promotion_force_cycle_handoff_enter"]),
                    "post_promotion_force_cycle_handoff_accept": bool(diag["post_promotion_force_cycle_handoff_accept"]),
                    "post_promotion_force_cycle_handoff_reject": bool(diag["post_promotion_force_cycle_handoff_reject"]),
                    "post_promotion_force_cycle_handoff_call_start": bool(diag["post_promotion_force_cycle_handoff_call_start"]),
                    "post_promotion_force_cycle_handoff_call_done": bool(diag["post_promotion_force_cycle_handoff_call_done"]),
                    "forced_cycle_scheduler_gate_enter": bool(diag["forced_cycle_scheduler_gate_enter"]),
                    "forced_cycle_scheduler_gate_result": diag["forced_cycle_scheduler_gate_result"],
                    "forced_cycle_scheduler_gate_blocked": bool(diag["forced_cycle_scheduler_gate_blocked"]),
                    "forced_cycle_scheduler_gate_allowed": bool(diag["forced_cycle_scheduler_gate_allowed"]),
                    "handoff_parent_enqueue_enter": bool(diag["handoff_parent_enqueue_enter"]),
                    "handoff_parent_enqueue_done": bool(diag["handoff_parent_enqueue_done"]),
                    "handoff_parent_signal_sent": bool(diag["handoff_parent_signal_sent"]),
                    "handoff_child_mailbox_observed": bool(diag["handoff_child_mailbox_observed"]),
                    "handoff_child_mailbox_dequeue_enter": bool(diag["handoff_child_mailbox_dequeue_enter"]),
                }

                deepest_transport_state_seen, transport_eligibility_reason, transport_blocker = _transport_finalist_state_from_diag(diag)
                if deepest_transport_state_seen:
                    diag["deepest_transport_downstream_state_seen"] = deepest_transport_state_seen
                    diag["transport_verdict_eligibility_reason"] = transport_eligibility_reason
                    diag["transport_finalist_blocker"] = transport_blocker
                    if transport_eligibility_reason == "eligible_for_bucket_local_finalist":
                        if deepest_transport_state_seen not in candidate_verdicts_seen:
                            candidate_verdicts_seen.append(deepest_transport_state_seen)
                            candidate_verdict_evidence[deepest_transport_state_seen] = {
                                "evidence_type": "transport_state",
                                "deepest_transport_downstream_state_seen": deepest_transport_state_seen,
                                "transport_verdict_eligibility_reason": transport_eligibility_reason,
                            }
                    else:
                        if "HANDOFF_PARENT_ENQUEUE_ENTERED" not in candidate_verdicts_seen:
                            candidate_verdicts_seen.append("HANDOFF_PARENT_ENQUEUE_ENTERED")
                            candidate_verdict_evidence["HANDOFF_PARENT_ENQUEUE_ENTERED"] = {
                                "evidence_type": "transport_state",
                                "deepest_transport_downstream_state_seen": deepest_transport_state_seen,
                                "transport_verdict_eligibility_reason": transport_eligibility_reason,
                                "transport_finalist_blocker": transport_blocker,
                            }

                forced_cycle_verdict = classify_forced_cycle_trace(diag)
                if (
                    forced_cycle_verdict == "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY_BUT_PRE_DRAIN_NOT_ENTERED"
                    and bool(diag.get("forced_cycle_request_scan_nonempty"))
                    and (
                        bool(bucket.get("forced_cycle_pre_drain_seen"))
                        or any(
                            trace.get("trace_event_name") == "post_promotion_force_cycle_pre_drain_enter"
                            for trace in bucket.get("forced_cycle_traces", [])
                        )
                    )
                ):
                    forced_cycle_verdict = "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
                diag["post_promotion_forced_cycle_verdict"] = forced_cycle_verdict
                forced_cycle_verdict_counts[forced_cycle_verdict] += 1
                candidate_verdicts_seen.append(forced_cycle_verdict)
                candidate_verdict_evidence[forced_cycle_verdict] = {
                    "evidence_type": "forced_cycle_stage",
                    "forced_cycle_started": bool(diag["forced_cycle_started"]),
                    "forced_cycle_completed": bool(diag["forced_cycle_completed"]),
                    "forced_cycle_eval_entry": bool(diag["forced_cycle_eval_entry"]),
                    "forced_cycle_eval_pre_router": bool(diag["forced_cycle_eval_pre_router"]),
                    "forced_cycle_eval_post_router": bool(diag["forced_cycle_eval_post_router"]),
                    "forced_cycle_eval_pre_entry_edge_check": bool(diag["forced_cycle_eval_pre_entry_edge_check"]),
                    "forced_cycle_eval_post_entry_edge_check": bool(diag["forced_cycle_eval_post_entry_edge_check"]),
                    "forced_cycle_eval_pre_selector_return_site": bool(diag["forced_cycle_eval_pre_selector_return_site"]),
                    "forced_cycle_eval_pre_selector_return_site_id": diag["forced_cycle_eval_pre_selector_return_site_id"],
                    "forced_cycle_eval_pre_selector_return_reason": diag["forced_cycle_eval_pre_selector_return_reason"],
                }
            diag["candidate_verdicts_seen"] = candidate_verdicts_seen
            diag["candidate_verdict_evidence"] = candidate_verdict_evidence
            diag["winning_verdict"] = diag.get("post_promotion_forced_cycle_verdict") or diag.get(
                "post_promotion_force_cycle_handoff_verdict"
            ) or diag.get("post_promotion_stage_verdict") or diag.get("post_promotion_emit_verdict")
            if diag.get("transport_verdict_eligibility_reason") == "eligible_for_bucket_local_finalist" and diag.get("deepest_transport_downstream_state_seen"):
                diag["winning_verdict"] = diag.get("deepest_transport_downstream_state_seen")
                diag["winning_verdict_reason"] = "transport_state_prioritized"
            elif diag["post_promotion_forced_cycle_verdict"]:
                diag["winning_verdict_reason"] = "forced_cycle_classifier_prioritized"
            elif diag["post_promotion_force_cycle_handoff_verdict"]:
                diag["winning_verdict_reason"] = "handoff_classifier_prioritized"
            elif diag["post_promotion_stage_verdict"]:
                diag["winning_verdict_reason"] = "bucket_stage_classifier_prioritized"
            elif diag["post_promotion_emit_verdict"]:
                diag["winning_verdict_reason"] = "emit_stage_classifier_prioritized"

        failure_counts = Counter({k: v for k, v in emit_verdict_counts.items() if k != "CANONICAL_GATE_READ_OBSERVED"})
        if failure_counts:
            emit_stage_rank = {
                "REEVAL_COMPLETES_BUT_EVALUATED_PATH_NOT_ENTERED": 0,
                "EVALUATED_PATH_REENTERED_BUT_EMIT_ATTEMPT_NOT_REACHED": 1,
                "EMIT_GUARD_BLOCKED_WITH_REASON": 2,
                "EMIT_ATTEMPT_REACHED_BUT_NOT_COMPLETED": 3,
            }
            first_missing_emit_stage_after_reeval = max(
                failure_counts.keys(),
                key=lambda classification: emit_stage_rank.get(classification, -1),
            )
        elif emit_verdict_counts.get("CANONICAL_GATE_READ_OBSERVED"):
            first_missing_emit_stage_after_reeval = "CANONICAL_GATE_READ_OBSERVED"

        branch_failure_counts = Counter({k: v for k, v in branch_verdict_counts.items() if k != "CANONICAL_GATE_READ_OBSERVED"})
        if branch_failure_counts:
            branch_stage_rank = {
                "REEVAL_COMPLETES_BUT_EVALUATED_PATH_NOT_ENTERED": 0,
                "PRE_CANDIDATE_BRANCH_SKIPPED_WITH_REASON": 1,
                "EVALUATED_PATH_REENTERED_BUT_PRE_CANDIDATE_BRANCH_NOT_REACHED": 2,
                "CANDIDATE_BRANCH_REACHED_BUT_GUARD_NOT_ENTERED": 3,
                "CANDIDATE_BRANCH_REACHED_AND_GUARD_BLOCKED": 4,
                "CANDIDATE_BRANCH_REACHED_AND_EMIT_ATTEMPT_REACHED": 5,
            }
            first_missing_branch_stage_after_reeval = max(
                branch_failure_counts.keys(),
                key=lambda classification: branch_stage_rank.get(classification, -1),
            )
        elif branch_verdict_counts.get("CANONICAL_GATE_READ_OBSERVED"):
            first_missing_branch_stage_after_reeval = "CANONICAL_GATE_READ_OBSERVED"

        forced_cycle_failure_counts = Counter(
            {k: v for k, v in forced_cycle_verdict_counts.items() if k != "FULL_POST_PROMOTION_PIPELINE_CONFIRMED"}
        )
        if forced_cycle_failure_counts:
            forced_cycle_stage_rank = {
                "FORCE_CYCLE_HANDOFF_NOT_REACHED": 0,
                "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED": 1,
                "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED": 2,
                "FORCED_CYCLE_SCHEDULER_GATE_BLOCKED": 3,
                "FORCED_CYCLE_SCHEDULER_GATE_ALLOWED_BUT_TICK_NOT_ENTERED": 4,
                "FORCED_CYCLE_SCHEDULER_TICK_NOT_ENTERED": 5,
                "FORCED_CYCLE_REQUEST_SCAN_NOT_ENTERED": 6,
                "FORCED_CYCLE_REQUEST_SCAN_RESULT_REACHED": 5,
                "FORCED_CYCLE_REQUEST_SCAN_EMPTY": 6,
                "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY_BUT_PRE_DRAIN_NOT_ENTERED": 7,
                "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY": 8,
                "PRE_DRAIN_TRANSITION_BLOCKER_PROVEN_BUT_NOT_FIXED": 9,
                "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED": 10,
                "FORCED_CYCLE_DRAIN_ENTERED": 11,
                "FORCED_CYCLE_CALLED_BUT_LOOP_NOT_ENTERED": 11,
                "FORCED_CYCLE_LOOP_ENTERED_BUT_EVALUATED_PATH_NOT_INVOKED": 12,
                "FORCED_CYCLE_EVALUATED_PATH_INVOKED_BUT_SELECTOR_NOT_ENTERED": 13,
                "FORCED_CYCLE_PRE_SELECTOR_GUARD_RETURN": 14,
                "FORCED_CYCLE_MISSING_SELECTOR_CONTEXT": 15,
                "FORCED_CYCLE_POSITION_STATE_SHORT_CIRCUIT": 16,
                "FORCED_CYCLE_ROUTER_POSTPROCESS_RETURN": 17,
                "FORCED_CYCLE_UNKNOWN_PRE_SELECTOR_RETURN": 18,
                "HELPER_RETURNED_NONE": 19,
                "HELPER_RETURNED_NON_DICT_RESULT": 20,
                "HELPER_RETURNED_DICT_MISSING_REQUIRED_FIELDS": 21,
                "WRAPPER_EXPECTATION_MISMATCH": 22,
                "VALID_HELPER_RESULT_BUT_SELECTOR_CONTEXT_NOT_BUILT": 23,
                "FORCED_CYCLE_REACHED_SELECTOR_BUT_CANDIDATE_NOT_CREATED": 24,
                "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_NOT_ENTERED": 25,
                "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_BLOCKED": 26,
                "FORCED_CYCLE_REACHED_CANDIDATE_BUT_EMIT_NOT_ATTEMPTED": 27,
                "FORCED_CYCLE_REACHED_EMIT_ATTEMPT_BUT_NOT_DONE": 28,
            }
            first_missing_forced_cycle_stage_after_reeval = max(
                forced_cycle_failure_counts.keys(),
                key=lambda classification: forced_cycle_stage_rank.get(classification, -1),
            )
        elif forced_cycle_verdict_counts.get("FULL_POST_PROMOTION_PIPELINE_CONFIRMED"):
            first_missing_forced_cycle_stage_after_reeval = "FULL_POST_PROMOTION_PIPELINE_CONFIRMED"
    else:
        for diag in correlation_diagnostics.values():
            diag["post_promotion_emit_verdict"] = "INSUFFICIENT_RUNTIME_EVIDENCE"
            diag["post_promotion_stage_verdict"] = "INSUFFICIENT_RUNTIME_EVIDENCE"
            emit_verdict_counts["INSUFFICIENT_RUNTIME_EVIDENCE"] += 1
    post_promotion_emit_verdict_counts = dict(sorted(emit_verdict_counts.items()))
    _sync_forced_cycle_pre_drain_trace_state(buckets, logs)
    run_max_gate_seq = max((e["runtime_seq"] for e in gate_reads), default=0)
    per_bucket = {k: _finalize_bucket(v, run_max_gate_seq) for k, v in buckets.items()}
    verdict_counts = Counter(v["bucket_verdict"] for v in per_bucket.values())

    buckets_promoted = sum(1 for v in per_bucket.values() if v["promotion_count"] > 0)
    buckets_read = sum(1 for v in per_bucket.values() if v["gate_read_count"] > 0)
    buckets_read_after_promotion = sum(1 for v in per_bucket.values() if v["gate_reads_after_first_promotion"] > 0)
    buckets_with_forced_replay = sum(1 for v in per_bucket.values() if v["forced_post_promotion_read_count"] > 0)
    forced_replay_reads_total = sum(v["forced_post_promotion_read_count"] for v in per_bucket.values())
    buckets_with_nonzero_visible_trade_count = sum(1 for v in per_bucket.values() if v["max_gate_trade_count_after_promotion"] > 0)
    buckets_with_history_ready_after_promotion = sum(1 for v in per_bucket.values() if v["history_ready_after_promotion_any"])
    promotion_visibility_rate = buckets_with_nonzero_visible_trade_count / max(1, buckets_promoted)
    promotion_skip_reasons = Counter(e["reason"] for e in promotion_skips)
    close_input_rows = len(close_traces) // 2 if close_traces else 0
    close_input_count = sum(1 for e in close_traces if e.get("trace_kind") == "close_trace" and e.get("raw_input_classification") is not None)
    close_output_count = sum(1 for e in close_traces if e.get("trace_kind") == "close_trace" and e.get("raw_input_classification") is None)
    row_diagnoses = []
    for inp in sorted([e for e in close_traces if e.get("raw_input_classification") is not None], key=lambda e: (e["runtime_seq"], e["seq_order"])):
        out = next((o for o in close_traces if o.get("raw_input_classification") is None and o["runtime_seq"] == inp["runtime_seq"] and o["canonical_key"] == inp["canonical_key"]), None)
        diagnosis = inp["raw_input_classification"]
        if diagnosis == "RAW_INPUTS_PRESENT" and out and out.get("output_null_classification") == "REALIZED_INPUTS_PRESENT":
            diagnosis = "INPUTS_PRESENT_OUTPUT_STILL_NULL"
        elif diagnosis == "RAW_INPUTS_PRESENT" and out and out.get("output_null_classification") != "REALIZED_INPUTS_PRESENT":
            diagnosis = "DECOMPOSE_OUTPUT_NOT_ASSIGNED"
        row_diagnoses.append({
            "runtime_seq": inp["runtime_seq"],
            "canonical_key": inp["canonical_key"],
            "input_classification": inp["raw_input_classification"],
            "output_classification": out.get("output_null_classification") if out else None,
            "branch": inp.get("source_branch"),
            "diagnosis": diagnosis,
        })
    diagnosis_counts = Counter(r["diagnosis"] for r in row_diagnoses)
    top_root_cause = diagnosis_counts.most_common(1)[0][0] if diagnosis_counts else "INSUFFICIENT_EVIDENCE"

    visibility_ms = [v["promotion_to_first_visible_delta_ms"] for v in per_bucket.values() if v["promotion_to_first_visible_delta_ms"] is not None]
    top_failure_mode = "INSUFFICIENT_EVIDENCE"
    if top_root_cause in {
        "RAW_FEE_INPUT_MISSING",
        "RAW_FILL_INPUTS_MISSING",
        "ZERO_SIZE_CLOSE_INPUT",
        "MOCK_BRANCH_UNPOPULATED_REALIZED_FIELDS",
        "DECOMPOSE_OUTPUT_NOT_ASSIGNED",
        "PAYLOAD_CONSTRUCTION_LOSS_BEFORE_DECOMPOSE",
        "INPUTS_PRESENT_OUTPUT_STILL_NULL",
        "MIXED_UPSTREAM_NULL_SOURCES",
    }:
        top_failure_mode = top_root_cause
    else:
        if buckets_promoted == 0:
            top_failure_mode = "INSUFFICIENT_EVIDENCE"
        elif buckets_read_after_promotion == 0:
            top_failure_mode = "STILL_NO_VISIBILITY_AFTER_FORCED_POST_PROMOTION_READS"
        elif buckets_with_nonzero_visible_trade_count > 0 and buckets_with_history_ready_after_promotion > 0:
            top_failure_mode = "PURE_TIMING_CUTOFF_CONFIRMED"
        elif buckets_with_nonzero_visible_trade_count > 0:
            top_failure_mode = "TIMING_FIXED_SECOND_BLOCKER_REVEALED"
        else:
            top_failure_mode = "STILL_NO_VISIBILITY_AFTER_FORCED_POST_PROMOTION_READS"

    read_source_names_seen = sorted(set(
        [e["read_source_name"] for e in gate_reads if e.get("read_source_name")] +
        [e["decision_source_name"] for e in gate_reads if e.get("decision_source_name")]
    ))
    read_source_functions_seen = sorted(set(
        [e["gate_read_source_function"] for e in gate_reads if e.get("gate_read_source_function")]
    ))

    collapse_classes = Counter(
        v["collapse_class"] for v in per_bucket.values() if v.get("collapse_class")
    )
    boundary_classification = "PARTIAL_PROOF_MORE_TRACE_NEEDED"
    if collapse_classes.get("MATERIALIZATION_BOUNDARY_COLLAPSE_CONFIRMED"):
        boundary_classification = "MATERIALIZATION_BOUNDARY_COLLAPSE_CONFIRMED"
    elif collapse_classes.get("STALE_SNAPSHOT_COLLAPSE_CONFIRMED"):
        boundary_classification = "STALE_SNAPSHOT_COLLAPSE_CONFIRMED"
    no_read_cause_counts = Counter(
        v["no_read_cause_verdict"] for v in per_bucket.values() if v.get("no_read_cause_verdict")
    )
    no_read_cause_classification = "PARTIAL_PROOF_MORE_TRACE_NEEDED"
    if len(no_read_cause_counts) == 1 and buckets_promoted > 0:
        no_read_cause_classification = next(iter(no_read_cause_counts))

    post_promotion_branch_verdict_counts = dict(sorted(branch_verdict_counts.items()))
    post_promotion_force_cycle_handoff_verdict_counts = dict(sorted(handoff_verdict_counts.items()))
    post_promotion_forced_cycle_verdict_counts = dict(sorted(forced_cycle_verdict_counts.items()))
    post_promotion_stage_verdict_counts = post_promotion_branch_verdict_counts
    first_missing_stage_after_reeval = first_missing_branch_stage_after_reeval
    if post_promotion_forced_cycle_verdict_counts:
        forced_cycle_stage_rank = {
            "FORCE_CYCLE_HANDOFF_NOT_REACHED": 0,
            "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED": 1,
            "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED": 2,
            "FORCED_CYCLE_SCHEDULER_GATE_BLOCKED": 3,
            "FORCED_CYCLE_SCHEDULER_GATE_ALLOWED_BUT_TICK_NOT_ENTERED": 4,
            "FORCED_CYCLE_SCHEDULER_TICK_NOT_ENTERED": 5,
            "FORCED_CYCLE_REQUEST_SCAN_NOT_ENTERED": 6,
            "FORCED_CYCLE_REQUEST_SCAN_RESULT_REACHED": 7,
            "FORCED_CYCLE_REQUEST_SCAN_EMPTY": 8,
            "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY_BUT_PRE_DRAIN_NOT_ENTERED": 9,
            "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY": 10,
            "PRE_DRAIN_TRANSITION_BLOCKER_PROVEN_BUT_NOT_FIXED": 11,
            "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED": 12,
            "FORCED_CYCLE_DRAIN_ENTERED": 13,
            "FORCED_CYCLE_CALLED_BUT_LOOP_NOT_ENTERED": 13,
            "FORCED_CYCLE_LOOP_ENTERED_BUT_EVALUATED_PATH_NOT_INVOKED": 14,
            "FORCED_CYCLE_EVALUATED_PATH_INVOKED_BUT_SELECTOR_NOT_ENTERED": 15,
            "FORCED_CYCLE_PRE_SELECTOR_GUARD_RETURN": 16,
            "FORCED_CYCLE_MISSING_SELECTOR_CONTEXT": 17,
            "FORCED_CYCLE_POSITION_STATE_SHORT_CIRCUIT": 18,
            "FORCED_CYCLE_ROUTER_POSTPROCESS_RETURN": 19,
            "FORCED_CYCLE_UNKNOWN_PRE_SELECTOR_RETURN": 20,
            "HELPER_RETURNED_NONE": 21,
            "HELPER_RETURNED_NON_DICT_RESULT": 22,
            "HELPER_RETURNED_DICT_MISSING_REQUIRED_FIELDS": 23,
            "WRAPPER_EXPECTATION_MISMATCH": 24,
            "VALID_HELPER_RESULT_BUT_SELECTOR_CONTEXT_NOT_BUILT": 25,
            "FORCED_CYCLE_REACHED_SELECTOR_BUT_CANDIDATE_NOT_CREATED": 26,
            "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_NOT_ENTERED": 27,
            "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_BLOCKED": 28,
            "FORCED_CYCLE_REACHED_CANDIDATE_BUT_EMIT_NOT_ATTEMPTED": 29,
            "FORCED_CYCLE_REACHED_EMIT_ATTEMPT_BUT_NOT_DONE": 30,
            "FULL_POST_PROMOTION_PIPELINE_CONFIRMED": 29,
            "INSUFFICIENT_RUNTIME_EVIDENCE": -1,
        }
        final_classification = max(
            post_promotion_forced_cycle_verdict_counts.keys(),
            key=lambda classification: forced_cycle_stage_rank.get(classification, -1),
        )
    else:
        final_classification = (
            first_missing_stage_after_reeval if reevaluation_completed else no_read_cause_classification
        )

    correlation_stage_counts = {
        "written": sum(1 for d in correlation_diagnostics.values() if d["written"]),
        "armed": sum(1 for d in correlation_diagnostics.values() if d["armed"]),
        "invoked": sum(1 for d in correlation_diagnostics.values() if d["invoked"]),
        "emit_attempted": sum(1 for d in correlation_diagnostics.values() if d["emit_attempted"]),
        "persisted": sum(1 for d in correlation_diagnostics.values() if d["persisted"]),
        "observed": sum(1 for d in correlation_diagnostics.values() if d["observed"]),
    }
    correlation_verdict_counts = dict(
        sorted(Counter(d["final_verdict"] for d in correlation_diagnostics.values()).items())
    )
    post_invoke_emit_verdict_counts = dict(
        sorted(Counter(d["post_invoke_emit_verdict"] for d in correlation_diagnostics.values()).items())
    )

    resolved_data_quality = data_quality or _new_data_quality()
    resolved_data_quality["rows_total"] = _safe_int(resolved_data_quality.get("rows_total"), len(logs))
    resolved_data_quality["rows_valid"] = _safe_int(resolved_data_quality.get("rows_valid"), len(logs))
    resolved_data_quality["rows_skipped"] = _safe_int(
        resolved_data_quality.get("rows_skipped"),
        max(0, resolved_data_quality["rows_total"] - resolved_data_quality["rows_valid"]),
    )
    resolved_data_quality["skip_reasons"] = dict(sorted((resolved_data_quality.get("skip_reasons") or {}).items()))

    report = {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "scenarios": ["baseline", "disable_current_side", "disable_net_target_guard"],
            "classification": final_classification,
            "method_version": "v4",
        },
        "canonical_state": {"total_buckets": len(per_bucket), "total_promotions": len(promotions)},
        "coverage": {
            "evaluated_rows": evaluated_total,
            "evaluated_with_canonical": evaluated_total,
            "unresolved_rows": unresolved_rows,
        },
        "promotion_effect": {
            "max_trade_count": max((v["max_gate_trade_count_after_promotion"] for v in per_bucket.values()), default=0),
            "buckets_with_growth": buckets_with_nonzero_visible_trade_count,
        },
        "readiness": {
            "shadow_history_ready_any": bool(buckets_with_history_ready_after_promotion),
            "shadow_history_ready_count": buckets_with_history_ready_after_promotion,
        },
        "aggregate": {
            "total_promotions": len(promotions),
            "total_promotion_skips": len(promotion_skips),
            "total_gate_reads": len(gate_reads),
            "buckets_promoted": buckets_promoted,
            "buckets_read": buckets_read,
            "buckets_read_after_promotion": buckets_read_after_promotion,
            "buckets_with_forced_replay": buckets_with_forced_replay,
            "forced_replay_reads_total": forced_replay_reads_total,
            "buckets_with_nonzero_visible_trade_count": buckets_with_nonzero_visible_trade_count,
            "buckets_with_history_ready_after_promotion": buckets_with_history_ready_after_promotion,
            "promotion_visibility_rate": promotion_visibility_rate,
            "promotion_to_visibility_latency_min": min(visibility_ms) if visibility_ms else None,
            "promotion_to_visibility_latency_max": max(visibility_ms) if visibility_ms else None,
            "promotion_to_visibility_latency_median": median(visibility_ms) if visibility_ms else None,
            "read_source_names_seen": read_source_names_seen,
            "read_source_functions_seen": read_source_functions_seen,
            "promotion_skip_reasons": dict(sorted(promotion_skip_reasons.items())),
            "close_input_rows": close_input_count,
            "close_output_rows": close_output_count,
            "rows_with_raw_inputs_present": sum(1 for r in row_diagnoses if r["input_classification"] == "RAW_INPUTS_PRESENT"),
            "rows_with_raw_fee_missing": sum(1 for r in row_diagnoses if r["input_classification"] == "RAW_FEE_INPUT_MISSING"),
            "rows_with_raw_fill_missing": sum(1 for r in row_diagnoses if r["input_classification"] == "RAW_FILL_INPUTS_MISSING"),
            "rows_with_zero_size_close_input": sum(1 for r in row_diagnoses if r["input_classification"] == "ZERO_SIZE_CLOSE_INPUT"),
            "rows_with_outputs_null_despite_present_raw": sum(1 for r in row_diagnoses if r["diagnosis"] == "DECOMPOSE_OUTPUT_NOT_ASSIGNED"),
            "rows_by_branch": dict(sorted(Counter(r["branch"] for r in row_diagnoses if r.get("branch")).items())),
            "row_diagnosis_counts": dict(sorted(diagnosis_counts.items())),
            "top_failure_mode": top_failure_mode,
            "storage_write_trace_count": len(storage_write_traces),
            "pre_materialization_trace_count": len(pre_materialization_traces),
            "post_materialization_trace_count": len(post_materialization_traces),
            "collapse_compare_trace_count": len(collapse_compare_traces),
            "storage_compare_trace_count": len(storage_compare_traces),
            "critical_path_exception_count": len(critical_path_exceptions),
            "boundary_classification": boundary_classification,
            "no_read_cause_classification": no_read_cause_classification,
            "final_classification": final_classification,
            "correlation_stage_counts": correlation_stage_counts,
            "correlation_verdict_counts": correlation_verdict_counts,
            "post_invoke_emit_verdict_counts": post_invoke_emit_verdict_counts,
            "post_promotion_reeval_completed": int(bool(runner_before.get("post_promotion_reeval_completed"))),
            "post_promotion_reeval_requested": int(bool(runner_before.get("post_promotion_reeval_requested"))),
            "post_promotion_reeval_result": reeval_result or None,
            "reeval_exit_reason": runner_before.get("reeval_exit_reason"),
            "post_promotion_reeval_dispatch_entered": int(bool(runner_before.get("post_promotion_reeval_dispatch_entered"))),
            "post_promotion_reeval_dispatch_exited": int(bool(runner_before.get("post_promotion_reeval_dispatch_exited"))),
            "post_promotion_forced_cycle_requested": int(bool(runner_before.get("post_promotion_forced_cycle_requested"))),
            "post_promotion_forced_cycle_started": int(bool(runner_before.get("post_promotion_forced_cycle_started"))),
            "post_promotion_forced_cycle_completed": int(bool(runner_before.get("post_promotion_forced_cycle_completed"))),
            "post_promotion_forced_cycle_failed": int(bool(runner_before.get("post_promotion_forced_cycle_failed"))),
            "post_promotion_forced_cycle_result": runner_before.get("post_promotion_forced_cycle_result"),
            "post_promotion_forced_cycle_exit_reason": runner_before.get("post_promotion_forced_cycle_exit_reason"),
            "evaluated_path_enter_after_promotion_count": sum(1 for d in correlation_diagnostics.values() if d["evaluated_path_enter_after_promotion"]),
            "canonical_gate_read_emit_candidate_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_candidate"]),
            "canonical_gate_read_emit_guard_considered_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_guard_considered"]),
            "canonical_gate_read_emit_guard_blocked_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_guard_blocked"]),
            "canonical_gate_read_emit_payload_built_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_payload_built"]),
            "canonical_gate_read_emit_attempt_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_attempt"]),
            "canonical_gate_read_emit_enter_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_enter"]),
            "canonical_gate_read_emit_done_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_emit_done"]),
            "canonical_gate_read_branch_selector_enter_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_branch_selector_enter"]),
            "canonical_gate_read_branch_selector_inputs_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_branch_selector_inputs"]),
            "canonical_gate_read_branch_selector_skip_count": sum(1 for d in correlation_diagnostics.values() if d["canonical_gate_read_branch_selector_skip"]),
            "canonical_gate_read_observed_count": sum(1 for d in correlation_diagnostics.values() if d["observed"]),
            "forced_cycle_requested_count": sum(1 for d in correlation_diagnostics.values() if d["forced_cycle_requested"]),
            "forced_cycle_started_count": sum(1 for d in correlation_diagnostics.values() if d["forced_cycle_started"]),
            "forced_cycle_completed_count": sum(1 for d in correlation_diagnostics.values() if d["forced_cycle_completed"]),
            "forced_cycle_failed_count": sum(1 for d in correlation_diagnostics.values() if d["forced_cycle_failed"]),
            "post_promotion_stage_verdict_counts": post_promotion_stage_verdict_counts,
            "post_promotion_emit_verdict_counts": post_promotion_emit_verdict_counts,
            "post_promotion_branch_verdict_counts": post_promotion_branch_verdict_counts,
            "post_promotion_force_cycle_handoff_verdict_counts": post_promotion_force_cycle_handoff_verdict_counts,
            "post_promotion_forced_cycle_verdict_counts": post_promotion_forced_cycle_verdict_counts,
            "first_missing_stage_after_reeval": first_missing_stage_after_reeval,
            "first_missing_emit_stage_after_reeval": first_missing_stage_after_reeval,
        },
        "bucket_verdict_counts": dict(sorted(verdict_counts.items())),
        "unresolved_reasons": dict(sorted(unresolved_reasons.items())),
        "per_bucket": dict(sorted(per_bucket.items())),
        "conclusion": {
            "linkage_working": bool(buckets_with_nonzero_visible_trade_count > 0),
            "readiness_unlocked": bool(buckets_with_history_ready_after_promotion > 0),
            "read_source_names_seen": read_source_names_seen,
            "read_source_functions_seen": read_source_functions_seen,
            "promotion_skip_reasons": dict(sorted(promotion_skip_reasons.items())),
            "row_diagnoses": row_diagnoses,
            "collapse_classes": dict(sorted(collapse_classes.items())),
            "no_read_cause_counts": dict(sorted(no_read_cause_counts.items())),
            "correlation_stage_counts": correlation_stage_counts,
            "correlation_verdict_counts": correlation_verdict_counts,
            "post_invoke_emit_verdict_counts": post_invoke_emit_verdict_counts,
            "post_promotion_stage_verdict_counts": post_promotion_stage_verdict_counts,
            "post_promotion_emit_verdict_counts": post_promotion_emit_verdict_counts,
            "post_promotion_branch_verdict_counts": post_promotion_branch_verdict_counts,
            "post_promotion_force_cycle_handoff_verdict_counts": post_promotion_force_cycle_handoff_verdict_counts,
            "first_missing_stage_after_reeval": first_missing_stage_after_reeval,
            "first_missing_emit_stage_after_reeval": first_missing_stage_after_reeval,
        },
        "correlation_diagnostics": dict(sorted(correlation_diagnostics.items())),
        "data_quality": resolved_data_quality,
        "final_classification": final_classification,
        "run_parameters": {
            "source_result": run["results_path"],
            "source_db": str(run["db_path"]),
            "duration_sec_actual": run["duration_sec_actual"],
            "before": runner_before,
        },
    }
    return report


def _build_report(result_path: str | None = None, results_dir: str | None = None) -> dict:
    run = _select_run(result_path, Path(results_dir or WORKDIR / "results"))
    logs, data_quality = _load_logs(run["db_path"])
    return _build_report_from_logs(run, logs, data_quality)


def _render_md(report: dict) -> str:
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        f"Root cause: `{report['aggregate']['top_failure_mode']}`. Promotion telemetry exists, and the forced post-promotion replay window determines whether canonical shadow visibility becomes non-zero."
    )
    lines.append("")
    lines.append("## B. Scope")
    lines.append(f"- source result: `{report['run_parameters']['source_result']}`")
    lines.append(f"- source DB: `{report['run_parameters']['source_db']}`")
    lines.append("- PAPER only")
    lines.append("- research-only canonical linkage and timing-repair visibility audit")
    lines.append("")
    lines.append("## C. Controlled Timing Mechanism")
    lines.append(
        f"- forced replay reads: `{report['aggregate'].get('buckets_with_forced_replay', 0)}` buckets"
    )
    lines.append(
        f"- read source functions: `{', '.join(report['aggregate'].get('read_source_functions_seen', []))}`"
    )
    lines.append("The replay window re-invokes the exact gate read path after canonical promotion without changing production admission semantics.")
    lines.append("")
    lines.append("## D. Per-Bucket Correlation Result")
    for key in sorted(report["per_bucket"]):
        bucket = report["per_bucket"][key]
        lines.append(
            f"- {key}: promo_seq={bucket['first_promotion_seq']}, post_reads={bucket['post_promotion_read_count']}, "
            f"max_trade_count_after_promotion={bucket['max_gate_trade_count_after_promotion']}, "
            f"history_ready_after_promotion_any={bucket['history_ready_after_promotion_any']}, "
            f"first_visible_trade_count_after_promotion={bucket['first_visible_trade_count_after_promotion']}, "
            f"first_visible_seq_after_promotion={bucket['first_visible_seq_after_promotion']}"
        )
    lines.append("")
    lines.append("## E. Aggregate Metrics")
    lines.append(f"- total_promotions: `{report['aggregate']['total_promotions']}`")
    lines.append(f"- total_promotion_skips: `{report['aggregate'].get('total_promotion_skips', 0)}`")
    lines.append(f"- total_gate_reads: `{report['aggregate']['total_gate_reads']}`")
    lines.append(f"- buckets_promoted: `{report['aggregate']['buckets_promoted']}`")
    lines.append(f"- buckets_read_after_promotion: `{report['aggregate']['buckets_read_after_promotion']}`")
    lines.append(f"- buckets_with_nonzero_visible_trade_count: `{report['aggregate']['buckets_with_nonzero_visible_trade_count']}`")
    lines.append(f"- buckets_with_history_ready_after_promotion: `{report['aggregate']['buckets_with_history_ready_after_promotion']}`")
    lines.append(f"- promotion_visibility_rate: `{report['aggregate']['promotion_visibility_rate']:.6f}`")
    lines.append(
        f"- read_source_names_seen: `{', '.join(report['aggregate']['read_source_names_seen'])}`"
    )
    if report["aggregate"].get("promotion_skip_reasons"):
        lines.append(
            f"- promotion_skip_reasons: `{report['aggregate']['promotion_skip_reasons']}`"
        )
    corr_stage = report["aggregate"].get("correlation_stage_counts") or {}
    lines.append(f"- correlation_written: `{corr_stage.get('written', 0)}`")
    lines.append(f"- correlation_armed: `{corr_stage.get('armed', 0)}`")
    lines.append(f"- correlation_invoked: `{corr_stage.get('invoked', 0)}`")
    lines.append(f"- correlation_emit_attempted: `{corr_stage.get('emit_attempted', 0)}`")
    lines.append(f"- correlation_persisted: `{corr_stage.get('persisted', 0)}`")
    lines.append(f"- correlation_observed: `{corr_stage.get('observed', 0)}`")
    lines.append(f"- correlation_verdict_counts: `{report['aggregate'].get('correlation_verdict_counts', {})}`")
    lines.append(f"- post_promotion_stage_verdict_counts: `{report['aggregate'].get('post_promotion_stage_verdict_counts', {})}`")
    lines.append(f"- post_promotion_emit_verdict_counts: `{report['aggregate'].get('post_promotion_emit_verdict_counts', {})}`")
    lines.append(f"- first_missing_stage_after_reeval: `{report['aggregate'].get('first_missing_stage_after_reeval')}`")
    lines.append(f"- first_missing_emit_stage_after_reeval: `{report['aggregate'].get('first_missing_emit_stage_after_reeval')}`")
    lines.append(f"- post_promotion_force_cycle_handoff_verdict_counts: `{report['aggregate'].get('post_promotion_force_cycle_handoff_verdict_counts', {})}`")
    lines.append(f"- post_promotion_forced_cycle_verdict_counts: `{report['aggregate'].get('post_promotion_forced_cycle_verdict_counts', {})}`")
    lines.append(
        f"- post_promotion_reeval_completed: `{report['aggregate'].get('post_promotion_reeval_completed', 0)}`"
    )
    lines.append(
        f"- post_promotion_reeval_result: `{report['aggregate'].get('post_promotion_reeval_result')}`"
    )
    lines.append("")
    data_quality = report.get("data_quality") or {}
    lines.append("## F. Data Quality")
    lines.append(f"- rows_total: `{data_quality.get('rows_total', 0)}`")
    lines.append(f"- rows_valid: `{data_quality.get('rows_valid', 0)}`")
    lines.append(f"- rows_skipped: `{data_quality.get('rows_skipped', 0)}`")
    lines.append(f"- skip_reasons: `{data_quality.get('skip_reasons', {})}`")
    lines.append("")
    lines.append("## G. Per-Correlation Verdict")
    for corr_id, diag in sorted((report.get("correlation_diagnostics") or {}).items()):
        lines.append(
            f"- {corr_id}: key={diag.get('canonical_key')}, verdict={diag.get('final_verdict')}, "
            f"written={diag.get('written')}, armed={diag.get('armed')}, invoked={diag.get('invoked')}, "
            f"emit_attempted={diag.get('emit_attempted')}, persisted={diag.get('persisted')}, observed={diag.get('observed')}"
        )
    lines.append("")
    lines.append("## H. Validation Commands and Results")
    lines.append("- `python -m py_compile .\\core\\BotCore.py .\\scripts\\canonical_edge_history_linkage.py .\\scripts\\canonical_edge_history_audit.py .\\tests\\test_canonical_edge_history_linkage.py`")
    lines.append("- `pytest -q .\\tests\\test_canonical_edge_history_linkage.py`")
    lines.append("- `pytest -q .\\tests\\test_canonical_edge_history_linkage.py .\\tests\\test_canonical_bucket_alignment_audit.py .\\tests\\test_readiness_architecture_mismatch_audit.py`")
    lines.append("")
    lines.append("## I. Final Classification")
    lines.append(f"`{report['final_classification']}`")
    lines.append("")
    lines.append("## J. Artifact Paths")
    stamp = report["metadata"]["stamp"]
    lines.append(f"- JSON: `artifacts/diagnostics/canonical_edge_history_linkage_{stamp}.json`")
    lines.append(f"- MD: `artifacts/diagnostics/canonical_edge_history_linkage_{stamp}.md`")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit research-only canonical edge-history linkage.")
    parser.add_argument("--result-path", default=None)
    parser.add_argument("--results-dir", default=str(WORKDIR / "results"))
    args = parser.parse_args(argv)
    report = _build_report(args.result_path, args.results_dir)
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"canonical_edge_history_linkage_{stamp}.json"
    md_path = DIAG_DIR / f"canonical_edge_history_linkage_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
