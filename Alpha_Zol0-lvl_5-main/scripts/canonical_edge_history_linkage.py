from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
from uuid import uuid4

WORKDIR = Path(__file__).resolve().parents[1]
if str(WORKDIR) not in sys.path:
    sys.path.insert(0, str(WORKDIR))


def _normalize_side(value):
    txt = str(value or "").strip().lower()
    if txt in {"long", "buy"}:
        return "buy"
    if txt in {"short", "sell"}:
        return "sell"
    return txt or "unknown"


def _normalize_symbol(value):
    txt = str(value or "").strip().upper()
    return txt or "UNKNOWN"


def _normalize_strategy(value):
    txt = str(value or "").strip()
    if not txt:
        return None
    upper = txt.upper()
    if upper in {"UNKNOWN", "ALL", "__ALL__"}:
        return None
    return upper


canonical_edge_history_state = defaultdict(
    lambda: defaultdict(lambda: defaultdict(lambda: {
        "gross_hist": [],
        "fee_hist": [],
        "slippage_hist": [],
        "trade_count": 0,
        "last_update_ts": None,
        "last_write_key": None,
        "last_write_ts": None,
    }))
)
canonical_unresolved_pool = []
canonical_promotion_count = 0
canonical_trace_seq = 0
CANONICAL_SHADOW_STORAGE_NAME = "canonical_shadow_storage"
CANONICAL_EVENT_SCHEMA_VERSION = "1.0"


def reset_canonical_edge_history_state():
    canonical_edge_history_state.clear()
    canonical_unresolved_pool.clear()
    global canonical_promotion_count
    global canonical_trace_seq
    canonical_promotion_count = 0
    canonical_trace_seq = 0


def next_canonical_trace_seq():
    global canonical_trace_seq
    canonical_trace_seq += 1
    return int(canonical_trace_seq)


def _coerce_epoch_seconds(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    txt = str(value).strip()
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def build_canonical_correlation_id(
    *,
    canonical_key: str | None,
    symbol: str | None,
    strategy: str | None,
    side: str | None,
    runtime_seq: int | None = None,
    created_at: str | None = None,
):
    seed = "|".join(
        [
            str(canonical_key or ""),
            str(symbol or ""),
            str(strategy or ""),
            str(side or ""),
            str(runtime_seq or ""),
            str(created_at or ""),
        ]
    )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]
    return f"corr_{digest}"


def build_canonical_event_envelope(
    *,
    event_type: str,
    canonical_key: str | None,
    symbol: str | None,
    strategy: str | None,
    side: str | None,
    correlation_id: str | None = None,
    runtime_seq: int | None = None,
    created_at: str | None = None,
    event_id: str | None = None,
    schema_version: str = CANONICAL_EVENT_SCHEMA_VERSION,
):
    created = str(created_at or _utc_now_iso())
    resolved_correlation_id = str(
        correlation_id
        or build_canonical_correlation_id(
            canonical_key=canonical_key,
            symbol=symbol,
            strategy=strategy,
            side=side,
            runtime_seq=runtime_seq,
            created_at=created,
        )
    )
    return {
        "event_id": str(event_id or uuid4()),
        "correlation_id": resolved_correlation_id,
        "event_type": str(event_type or "unknown"),
        "schema_version": str(schema_version or CANONICAL_EVENT_SCHEMA_VERSION),
        "created_at": created,
        "canonical_key": canonical_key,
        "symbol": symbol,
        "strategy": strategy,
        "side": side,
    }


def _bucket_shape(bucket):
    bucket = bucket if isinstance(bucket, dict) else {}
    gross_hist = list(bucket.get("gross_hist") or [])
    fee_hist = list(bucket.get("fee_hist") or [])
    slippage_hist = list(bucket.get("slippage_hist") or [])
    trade_count = int(bucket.get("trade_count") or 0)
    history_ready = bool(bucket.get("history_ready")) if "history_ready" in bucket else False
    return {
        "gross_hist": gross_hist,
        "fee_hist": fee_hist,
        "slippage_hist": slippage_hist,
        "trade_count": trade_count,
        "history_ready": history_ready,
        "last_update_ts": bucket.get("last_update_ts"),
        "gross_hist_len": len(gross_hist),
        "fee_hist_len": len(fee_hist),
        "slippage_hist_len": len(slippage_hist),
    }


def _resolve_strategy_trace(payload: dict):
    if not isinstance(payload, dict):
        return None, "UNRESOLVED", "malformed_payload", None, None, None
    entry_edge = payload.get("entry_edge_over_fee")
    if entry_edge is not None and not isinstance(entry_edge, dict):
        return None, "UNRESOLVED", "malformed_payload", None, None, None
    pos = payload.get("position")
    if pos is not None and not isinstance(pos, dict):
        return None, "UNRESOLVED", "malformed_payload", None, None, None

    candidates = []
    if isinstance(entry_edge, dict):
        candidates.append(("entry_edge_over_fee.strategy", entry_edge.get("strategy")))
    candidates.append(("strategy", payload.get("strategy")))
    if isinstance(pos, dict):
        candidates.append(("position.entry_main_strategy", pos.get("entry_main_strategy")))
        candidates.append(("position.strategy", pos.get("strategy")))

    seen_missing_entry_edge = False
    seen_missing_strategy = False
    for idx, (source_name, candidate) in enumerate(candidates):
        raw = str(candidate or "").strip()
        if not raw:
            if idx == 0 and source_name == "entry_edge_over_fee.strategy":
                seen_missing_entry_edge = True
            else:
                seen_missing_strategy = True
            continue
        upper = raw.upper()
        if upper in {"ALL", "__ALL__"}:
            return None, "UNRESOLVED", "strategy_is___ALL__", source_name, raw, upper
        if upper == "UNKNOWN":
            return None, "UNRESOLVED", "fallback_unknown", source_name, raw, upper
        return upper, "RESOLVED", "explicit_strategy", source_name, raw, upper

    if seen_missing_entry_edge:
        return None, "UNRESOLVED", "missing_entry_edge_payload", None, None, None
    if seen_missing_strategy:
        return None, "UNRESOLVED", "missing_strategy_field", None, None, None
    return None, "UNRESOLVED", "missing_strategy_field", None, None, None


def resolve_canonical_strategy(payload: dict):
    strategy_identity, status, reason, _, _, _ = _resolve_strategy_trace(payload)
    return strategy_identity, status, reason


def build_canonical_bucket_key(payload: dict):
    if not isinstance(payload, dict):
        return {
            "canonical_bucket_key": None,
            "bucket_identity_status": "UNRESOLVED",
            "bucket_identity_reason": "malformed_payload",
            "symbol": "UNKNOWN",
            "side": "unknown",
            "strategy_identity": None,
            "raw_symbol": None,
            "raw_strategy": None,
            "raw_side": None,
            "normalized_symbol": "UNKNOWN",
            "normalized_strategy": None,
            "normalized_side": "unknown",
            "strategy_source": None,
        }
    raw_symbol = payload.get("symbol")
    if raw_symbol in (None, ""):
        pos = payload.get("position") or {}
        raw_symbol = pos.get("symbol")
    normalized_symbol = _normalize_symbol(raw_symbol)

    raw_side = payload.get("side")
    if raw_side in (None, ""):
        pos = payload.get("position") or {}
        raw_side = pos.get("side")
    normalized_side = _normalize_side(raw_side)

    strategy_identity, status, reason, strategy_source, raw_strategy, normalized_strategy = _resolve_strategy_trace(payload)
    canonical_bucket_key = None
    if status == "RESOLVED" and strategy_identity:
        canonical_bucket_key = f"{normalized_symbol}|{strategy_identity}|{normalized_side}"
    return {
        "canonical_bucket_key": canonical_bucket_key,
        "bucket_identity_status": status,
        "bucket_identity_reason": reason,
        "symbol": normalized_symbol,
        "side": normalized_side,
        "strategy_identity": strategy_identity,
        "raw_symbol": raw_symbol,
        "raw_strategy": raw_strategy,
        "raw_side": raw_side,
        "normalized_symbol": normalized_symbol,
        "normalized_strategy": normalized_strategy,
        "normalized_side": normalized_side,
        "strategy_source": strategy_source,
    }


def record_unresolved_row(payload: dict, reason: str | None = None, event_name: str | None = None):
    canonical = build_canonical_bucket_key(payload)
    if canonical["bucket_identity_status"] == "RESOLVED":
        return canonical
    canonical_unresolved_pool.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_name,
            "reason": reason or canonical["bucket_identity_reason"],
            "raw_payload": payload if isinstance(payload, dict) else {"raw_payload": str(payload)},
        }
    )
    return canonical


def build_canonical_promotion_telemetry(
    *,
    canonical_result: dict,
    source_event_type: str,
    gross_fill_pnl_model,
    fee_total,
    spread_slippage_proxy=None,
    position_id=None,
    close_ts=None,
    run_ts=None,
    bucket_created_on_this_event=None,
    runtime_seq: int | None = None,
    promotion_context: str | None = None,
    correlation_id: str | None = None,
    event_id: str | None = None,
    schema_version: str = CANONICAL_EVENT_SCHEMA_VERSION,
):
    canonical_result = dict(canonical_result or {})
    canonical_shadow_bucket = canonical_result.get("shadow_bucket")
    raw_symbol = canonical_result.get("raw_symbol")
    raw_strategy = canonical_result.get("raw_strategy")
    raw_side = canonical_result.get("raw_side")
    normalized_symbol = canonical_result.get("normalized_symbol") or canonical_result.get("symbol")
    normalized_strategy = canonical_result.get("normalized_strategy") or canonical_result.get("strategy_identity")
    normalized_side = canonical_result.get("normalized_side") or canonical_result.get("side")
    if runtime_seq is None:
        runtime_seq = next_canonical_trace_seq()
    run_ts_value = run_ts or datetime.now(timezone.utc).isoformat()
    event_envelope = build_canonical_event_envelope(
        event_type="promotion_write",
        canonical_key=canonical_result.get("canonical_bucket_key"),
        symbol=normalized_symbol,
        strategy=normalized_strategy,
        side=normalized_side,
        correlation_id=correlation_id or canonical_result.get("correlation_id"),
        runtime_seq=runtime_seq,
        created_at=run_ts_value,
        event_id=event_id,
        schema_version=schema_version,
    )
    stored_trade_count = int(
        (canonical_shadow_bucket or {}).get("trade_count")
        if isinstance(canonical_shadow_bucket, dict)
        else int(canonical_result.get("canonical_shadow_trade_count") or 0)
    )
    stored_history_ready = bool(
        (canonical_shadow_bucket or {}).get("trade_count", 0) >= 20
        if isinstance(canonical_shadow_bucket, dict)
        else bool(canonical_result.get("canonical_shadow_history_ready"))
    )
    promotion_write_source_payload_present = bool(
        gross_fill_pnl_model is not None
        or fee_total is not None
        or spread_slippage_proxy is not None
    )
    promotion_write_bucket_exists_after_append = bool(
        canonical_result.get("storage_bucket_id") is not None
        and canonical_result.get("shadow_bucket") is not None
    )
    if not promotion_write_source_payload_present:
        promotion_write_effective_value_state = "NO_SOURCE_PAYLOAD"
    elif stored_trade_count > 0:
        promotion_write_effective_value_state = "NONZERO_WRITTEN"
    else:
        promotion_write_effective_value_state = "ZERO_WRITTEN"
    return {
        **event_envelope,
        "event": "canonical_promotion",
        "runtime_seq": int(runtime_seq),
        "run_ts": run_ts_value,
        "timestamp": run_ts_value,
        "source_event_type": source_event_type,
        "promotion_context": promotion_context,
        "symbol": normalized_symbol,
        "strategy": normalized_strategy,
        "side": normalized_side,
        "raw_symbol": raw_symbol,
        "raw_strategy": raw_strategy,
        "raw_side": raw_side,
        "normalized_symbol": normalized_symbol,
        "normalized_strategy": normalized_strategy,
        "normalized_side": normalized_side,
        "canonical_key": canonical_result.get("canonical_bucket_key"),
        "canonical_key_write": canonical_result.get("canonical_bucket_key"),
        "promotion_write_canonical_key": canonical_result.get("canonical_bucket_key"),
        "bucket_identity_status": canonical_result.get("bucket_identity_status"),
        "bucket_identity_reason": canonical_result.get("bucket_identity_reason"),
        "storage_target_name": "canonical_shadow_storage",
        "storage_container_name": "canonical_edge_history_state",
        "storage_container_id": canonical_result.get("storage_container_id")
        or id(canonical_edge_history_state),
        "storage_bucket_id": canonical_result.get("storage_bucket_id"),
        "stored_trade_count": int(stored_trade_count),
        "trade_count_written": int(stored_trade_count),
        "stored_history_ready": bool(stored_history_ready),
        "promotion_write_trade_count": int(stored_trade_count),
        "promotion_write_history_ready": bool(stored_history_ready),
        "promotion_write_source_payload_present": bool(
            promotion_write_source_payload_present
        ),
        "promotion_write_bucket_exists_after_append": bool(
            promotion_write_bucket_exists_after_append
        ),
        "promotion_write_storage_trade_count_after_append": int(stored_trade_count),
        "promotion_write_storage_history_ready_after_append": bool(
            stored_history_ready
        ),
        "promotion_write_effective_value_state": promotion_write_effective_value_state,
        "stored_bucket_shape": {
            "gross_hist_len": len((canonical_shadow_bucket or {}).get("gross_hist") or [])
            if isinstance(canonical_shadow_bucket, dict)
            else int(canonical_result.get("canonical_shadow_trade_count") or 0),
            "fee_hist_len": len((canonical_shadow_bucket or {}).get("fee_hist") or [])
            if isinstance(canonical_shadow_bucket, dict)
            else int(canonical_result.get("canonical_shadow_trade_count") or 0),
            "slippage_hist_len": len((canonical_shadow_bucket or {}).get("slippage_hist") or [])
            if isinstance(canonical_shadow_bucket, dict)
            else int(canonical_result.get("canonical_shadow_trade_count") or 0),
        },
        "trade_count_after": int(canonical_result.get("canonical_shadow_trade_count") or 0),
        "write_timestamp": canonical_result.get("write_timestamp") or run_ts_value,
        "gross_hist_len": int(canonical_result.get("canonical_shadow_trade_count") or 0),
        "fee_hist_len": int(canonical_result.get("canonical_shadow_trade_count") or 0),
        "slippage_hist_len": int(canonical_result.get("canonical_shadow_trade_count") or 0),
        "last_update_ts": canonical_result.get("canonical_shadow_last_update_ts"),
        "position_id": position_id,
        "close_ts": close_ts,
        "realized_gross": gross_fill_pnl_model,
        "realized_fee": fee_total,
        "realized_slippage": spread_slippage_proxy,
        "bucket_created_on_this_event": bucket_created_on_this_event,
        "post_write_readback_confirmed": bool(
            canonical_result.get("post_write_readback_confirmed")
        ),
        "post_write_readback_trade_count": int(
            canonical_result.get("post_write_readback_trade_count") or 0
        ),
        "post_write_readback_key": canonical_result.get("post_write_readback_key"),
        "post_write_readback_stage": canonical_result.get("post_write_readback_stage"),
        "post_write_readback_exception_class": canonical_result.get(
            "post_write_readback_exception_class"
        ),
        "post_write_readback_exception_message": canonical_result.get(
            "post_write_readback_exception_message"
        ),
        "promotion_write_invariant_ok": bool(
            canonical_result.get("post_write_readback_confirmed")
        ),
    }


def build_canonical_storage_write_trace(
    *,
    canonical_result: dict,
    runtime_seq: int | None = None,
    timestamp: str | None = None,
    correlation_id: str | None = None,
    event_id: str | None = None,
    schema_version: str = CANONICAL_EVENT_SCHEMA_VERSION,
):
    canonical_result = dict(canonical_result or {})
    shadow_bucket = canonical_result.get("shadow_bucket")
    if runtime_seq is None:
        runtime_seq = next_canonical_trace_seq()
    created_at = timestamp or datetime.now(timezone.utc).isoformat()
    event_envelope = build_canonical_event_envelope(
        event_type="persist",
        canonical_key=canonical_result.get("canonical_bucket_key"),
        symbol=canonical_result.get("symbol"),
        strategy=canonical_result.get("strategy_identity"),
        side=canonical_result.get("side"),
        correlation_id=correlation_id or canonical_result.get("correlation_id"),
        runtime_seq=runtime_seq,
        created_at=created_at,
        event_id=event_id,
        schema_version=schema_version,
    )
    return {
        **event_envelope,
        "event": "canonical_storage_write_trace",
        "runtime_seq": int(runtime_seq),
        "timestamp": created_at,
        "symbol": canonical_result.get("symbol"),
        "strategy": canonical_result.get("strategy_identity"),
        "side": canonical_result.get("side"),
        "canonical_key": canonical_result.get("canonical_bucket_key"),
        "storage_target_name": CANONICAL_SHADOW_STORAGE_NAME,
        "storage_container_name": "canonical_edge_history_state",
        "storage_container_id": canonical_result.get("storage_container_id"),
        "nested_key_path": canonical_result.get("nested_key_path"),
        "stored_trade_count": int(canonical_result.get("canonical_shadow_trade_count") or 0),
        "stored_history_ready": bool(canonical_result.get("canonical_shadow_history_ready")),
        "gross_hist_len": len((shadow_bucket or {}).get("gross_hist") or [])
        if isinstance(shadow_bucket, dict)
        else 0,
        "fee_hist_len": len((shadow_bucket or {}).get("fee_hist") or [])
        if isinstance(shadow_bucket, dict)
        else 0,
        "slippage_hist_len": len((shadow_bucket or {}).get("slippage_hist") or [])
        if isinstance(shadow_bucket, dict)
        else 0,
        "last_update_ts": (shadow_bucket or {}).get("last_update_ts")
        if isinstance(shadow_bucket, dict)
        else None,
        "storage_bucket_id": canonical_result.get("storage_bucket_id"),
        "full_bucket_shape": _bucket_shape(shadow_bucket),
    }


def build_canonical_gate_read_telemetry(
    *,
    gate_payload: dict,
    production_source_name: str,
    production_trade_count,
    production_history_ready,
    canonical_shadow_result: dict,
    row_ts=None,
    evaluation_index=None,
    runtime_seq: int | None = None,
    read_context: str | None = None,
    timing_replay_index: int | None = None,
    timing_replay_target_reads: int | None = None,
    gate_read_source_function: str | None = None,
    primary_snapshot: dict | None = None,
    fallback_snapshot: dict | None = None,
    bucket_used_final: str | None = None,
    trade_count_primary: int | None = None,
    trade_count_fallback: int | None = None,
    selected_snapshot: dict | None = None,
    bucket_key_primary: str | None = None,
    bucket_key_fallback: str | None = None,
    forced_same_bucket_next_eval: bool | None = None,
    override_type: str | None = None,
    override_consumed: bool | None = None,
    promoted_bucket_key: str | None = None,
    promotion_write_timestamp: str | None = None,
    post_promotion_eval_enter: bool | None = None,
    post_promotion_eval_exit: bool | None = None,
    post_promotion_eval_skip_reason: str | None = None,
    post_promotion_gate_read_emit_attempt: bool | None = None,
    post_promotion_gate_read_emit_done: bool | None = None,
    post_promotion_gate_read_emit_block_reason: str | None = None,
    post_promotion_eval_arm_consumed: bool | None = None,
    evaluated_path_enter_after_promotion: bool | None = None,
    evaluated_path_skip_reason: str | None = None,
    evaluated_path_exit_reason: str | None = None,
    canonical_gate_read_emit_candidate: bool | None = None,
    canonical_gate_read_emit_guard_considered: bool | None = None,
    canonical_gate_read_emit_guard_blocked: bool | None = None,
    canonical_gate_read_emit_guard_reason: str | None = None,
    canonical_gate_read_emit_payload_built: bool | None = None,
    canonical_gate_read_emit_attempt: bool | None = None,
    canonical_gate_read_emit_enter: bool | None = None,
    canonical_gate_read_emit_done: bool | None = None,
    evaluation_phase: str | None = None,
    is_explicit_post_promotion_eval: bool | None = None,
    is_forced_post_promotion_cycle: bool | None = None,
    skip_reason: str | None = None,
    promotion_runtime_seq: int | None = None,
    forced_cycle_runtime_seq: int | None = None,
    reeval_runtime_seq: int | None = None,
    evaluated_path_runtime_seq: int | None = None,
    canonical_gate_read_runtime_seq: int | None = None,
    correlation_id: str | None = None,
    event_id: str | None = None,
    schema_version: str = CANONICAL_EVENT_SCHEMA_VERSION,
):
    canonical = build_canonical_bucket_key(gate_payload)
    canonical_shadow_result = dict(canonical_shadow_result or {})
    if runtime_seq is None:
        runtime_seq = next_canonical_trace_seq()
    row_ts_value = row_ts or datetime.now(timezone.utc).isoformat()
    event_envelope = build_canonical_event_envelope(
        event_type="readback",
        canonical_key=canonical.get("canonical_bucket_key"),
        symbol=canonical.get("symbol"),
        strategy=canonical.get("strategy_identity"),
        side=canonical.get("side"),
        correlation_id=correlation_id or canonical_shadow_result.get("correlation_id"),
        runtime_seq=runtime_seq,
        created_at=row_ts_value,
        event_id=event_id,
        schema_version=schema_version,
    )
    read_trade_count = int(
        canonical_shadow_result.get("canonical_shadow_trade_count") or 0
    )
    next_read_canonical_key = canonical.get("canonical_bucket_key")
    next_read_storage_bucket_id = canonical_shadow_result.get("storage_bucket_id")
    next_read_storage_container_id = canonical_shadow_result.get("storage_container_id")
    last_write_key = canonical_shadow_result.get("last_write_key")
    last_write_ts = canonical_shadow_result.get("last_write_ts") or promotion_write_timestamp
    same_bucket_match = bool(
        next_read_canonical_key
        and next_read_canonical_key == last_write_key
    )
    same_bucket_match_strict = bool(
        same_bucket_match
        and next_read_storage_bucket_id is not None
        and canonical_shadow_result.get("storage_bucket_id") is not None
    )
    row_epoch = _coerce_epoch_seconds(row_ts_value)
    write_epoch = _coerce_epoch_seconds(last_write_ts)
    write_to_read_delay_ms = None
    if row_epoch is not None and write_epoch is not None:
        write_to_read_delay_ms = max(0.0, (float(row_epoch) - float(write_epoch)) * 1000.0)
    post_promotion_read_path_stage = "not_post_promotion"
    if bool(post_promotion_eval_enter):
        post_promotion_read_path_stage = "entered"
    if bool(post_promotion_gate_read_emit_attempt):
        post_promotion_read_path_stage = "emit_attempted"
    if bool(post_promotion_gate_read_emit_done):
        post_promotion_read_path_stage = "emit_done"
    if bool(post_promotion_eval_exit):
        post_promotion_read_path_stage = "exited"
    if bool(read_trade_count > 0):
        post_promotion_read_path_stage = "persisted_nonzero"
    elif bool(post_promotion_gate_read_emit_done):
        post_promotion_read_path_stage = "persisted_zero"
    elif bool(post_promotion_gate_read_emit_attempt):
        post_promotion_read_path_stage = "attempted_not_persisted"
    elif post_promotion_eval_skip_reason:
        post_promotion_read_path_stage = "skipped"
    return {
        **event_envelope,
        "event": "canonical_gate_read",
        "runtime_seq": int(runtime_seq),
        "row_ts": row_ts_value,
        "timestamp": row_ts_value,
        "evaluation_index": evaluation_index,
        "read_context": read_context,
        "timing_replay_index": timing_replay_index,
        "timing_replay_target_reads": timing_replay_target_reads,
        "gate_read_source_function": gate_read_source_function,
        "forced_same_bucket_next_eval": bool(forced_same_bucket_next_eval),
        "override_type": override_type,
        "override_consumed": bool(override_consumed),
        "promoted_bucket_key": promoted_bucket_key,
        "promotion_write_timestamp": promotion_write_timestamp,
        "post_promotion_eval_enter": bool(post_promotion_eval_enter),
        "post_promotion_eval_exit": bool(post_promotion_eval_exit),
        "post_promotion_eval_skip_reason": post_promotion_eval_skip_reason,
        "post_promotion_gate_read_emit_attempt": bool(post_promotion_gate_read_emit_attempt),
        "post_promotion_gate_read_emit_done": bool(post_promotion_gate_read_emit_done),
        "post_promotion_gate_read_emit_block_reason": post_promotion_gate_read_emit_block_reason,
        "post_promotion_eval_arm_consumed": bool(post_promotion_eval_arm_consumed),
        "evaluated_path_enter_after_promotion": bool(
            evaluated_path_enter_after_promotion
        ),
        "evaluated_path_skip_reason": evaluated_path_skip_reason,
        "evaluated_path_exit_reason": evaluated_path_exit_reason,
        "canonical_gate_read_emit_candidate": bool(canonical_gate_read_emit_candidate),
        "canonical_gate_read_emit_guard_considered": bool(canonical_gate_read_emit_guard_considered),
        "canonical_gate_read_emit_guard_blocked": bool(canonical_gate_read_emit_guard_blocked),
        "canonical_gate_read_emit_guard_reason": canonical_gate_read_emit_guard_reason,
        "canonical_gate_read_emit_payload_built": bool(canonical_gate_read_emit_payload_built),
        "canonical_gate_read_emit_attempt": bool(canonical_gate_read_emit_attempt),
        "canonical_gate_read_emit_enter": bool(canonical_gate_read_emit_enter),
        "canonical_gate_read_emit_done": bool(canonical_gate_read_emit_done),
        "evaluation_phase": evaluation_phase,
        "is_explicit_post_promotion_eval": bool(is_explicit_post_promotion_eval),
        "is_forced_post_promotion_cycle": bool(is_forced_post_promotion_cycle),
        "skip_reason": skip_reason,
        "promotion_runtime_seq": promotion_runtime_seq,
        "forced_cycle_runtime_seq": forced_cycle_runtime_seq,
        "reeval_runtime_seq": reeval_runtime_seq,
        "evaluated_path_runtime_seq": evaluated_path_runtime_seq,
        "canonical_gate_read_runtime_seq": (
            int(canonical_gate_read_runtime_seq)
            if canonical_gate_read_runtime_seq is not None
            else int(runtime_seq)
        ),
        "post_promotion_read_path_stage": post_promotion_read_path_stage,
        "symbol": canonical.get("symbol"),
        "strategy": canonical.get("strategy_identity"),
        "side": canonical.get("side"),
        "raw_symbol": canonical.get("raw_symbol"),
        "raw_strategy": canonical.get("raw_strategy"),
        "raw_side": canonical.get("raw_side"),
        "normalized_symbol": canonical.get("normalized_symbol"),
        "normalized_strategy": canonical.get("normalized_strategy"),
        "normalized_side": canonical.get("normalized_side"),
        "canonical_key": canonical.get("canonical_bucket_key"),
        "canonical_key_read": canonical.get("canonical_bucket_key"),
        "next_read_canonical_key": next_read_canonical_key,
        "bucket_identity_status": canonical.get("bucket_identity_status"),
        "bucket_identity_reason": canonical.get("bucket_identity_reason"),
        "read_source_name": canonical_shadow_result.get("read_source_name")
        or "canonical_shadow_storage",
        "snapshot_source": production_source_name,
        "read_trade_count": read_trade_count,
        "trade_count_read": read_trade_count,
        "next_read_trade_count": read_trade_count,
        "read_history_ready": bool(
            canonical_shadow_result.get("canonical_shadow_history_ready")
        ),
        "next_read_history_ready": bool(
            canonical_shadow_result.get("canonical_shadow_history_ready")
        ),
        "last_update_ts_seen": canonical_shadow_result.get("canonical_shadow_last_update_ts")
        or (
            (canonical_shadow_result.get("shadow_bucket") or {}).get("last_update_ts")
            if isinstance(canonical_shadow_result.get("shadow_bucket"), dict)
            else None
        ),
        "next_read_storage_bucket_id": next_read_storage_bucket_id,
        "next_read_storage_container_id": next_read_storage_container_id,
        "canonical_shadow_source_name": canonical_shadow_result.get("read_source_name")
        or "canonical_shadow_storage",
        "canonical_shadow_trade_count": int(
            canonical_shadow_result.get("canonical_shadow_trade_count") or 0
        ),
        "canonical_shadow_history_ready": bool(
            canonical_shadow_result.get("canonical_shadow_history_ready")
        ),
        "same_bucket_match": same_bucket_match,
        "write_to_read_delay_ms": write_to_read_delay_ms,
        "last_write_key": last_write_key,
        "last_write_ts": last_write_ts,
        "canonical_shadow_bucket": canonical_shadow_result.get("shadow_bucket"),
        "decision_source_name": production_source_name,
        "decision_trade_count": int(production_trade_count or 0),
        "decision_history_ready": bool(production_history_ready),
        "same_bucket_match_strict": bool(same_bucket_match_strict),
        "promotion_to_next_read_delay_ms": write_to_read_delay_ms,
        "canonical_shadow_storage_bucket": canonical_shadow_result.get("shadow_bucket"),
        "read_source_bucket_shape": {
            "gross_hist_len": len((canonical_shadow_result.get("shadow_bucket") or {}).get("gross_hist") or [])
            if isinstance(canonical_shadow_result.get("shadow_bucket"), dict)
            else 0,
            "fee_hist_len": len((canonical_shadow_result.get("shadow_bucket") or {}).get("fee_hist") or [])
            if isinstance(canonical_shadow_result.get("shadow_bucket"), dict)
            else 0,
            "slippage_hist_len": len((canonical_shadow_result.get("shadow_bucket") or {}).get("slippage_hist") or [])
            if isinstance(canonical_shadow_result.get("shadow_bucket"), dict)
            else 0,
        },
        "decision_snapshot_selection": {
            "bucket_used_final": bucket_used_final,
            "bucket_key_primary": bucket_key_primary,
            "bucket_key_fallback": bucket_key_fallback,
            "trade_count_primary": int(trade_count_primary or 0),
            "trade_count_fallback": int(trade_count_fallback or 0),
            "decision_snapshot_selection_reason": None,
            "selected_trade_count": int((selected_snapshot or {}).get("trade_count") or 0),
            "selected_history_ready": bool((selected_snapshot or {}).get("history_ready"))
            if isinstance(selected_snapshot, dict)
            else False,
            "primary_snapshot": primary_snapshot,
            "fallback_snapshot": fallback_snapshot,
            "selected_snapshot": selected_snapshot,
        },
    }


def build_canonical_bucket_pre_materialization(
    *,
    canonical_shadow_result: dict,
    runtime_seq: int | None = None,
    timestamp: str | None = None,
):
    canonical_shadow_result = dict(canonical_shadow_result or {})
    shadow_bucket = canonical_shadow_result.get("shadow_bucket")
    if runtime_seq is None:
        runtime_seq = next_canonical_trace_seq()
    shape = _bucket_shape(shadow_bucket)
    return {
        "event": "canonical_bucket_pre_materialization",
        "runtime_seq": int(runtime_seq),
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "symbol": canonical_shadow_result.get("symbol"),
        "strategy": canonical_shadow_result.get("strategy_identity"),
        "side": canonical_shadow_result.get("side"),
        "canonical_key": canonical_shadow_result.get("canonical_bucket_key"),
        "source_container_name": canonical_shadow_result.get("read_container_name")
        or "canonical_edge_history_state",
        "nested_key_path": canonical_shadow_result.get("nested_key_path"),
        "trade_count": int(canonical_shadow_result.get("canonical_shadow_trade_count") or 0),
        "history_ready": bool(canonical_shadow_result.get("canonical_shadow_history_ready")),
        "gross_hist_len": shape["gross_hist_len"],
        "fee_hist_len": shape["fee_hist_len"],
        "slippage_hist_len": shape["slippage_hist_len"],
        "last_update_ts": shape["last_update_ts"],
        "object_id_or_equivalent_if_safe": canonical_shadow_result.get("storage_bucket_id"),
        "storage_container_id": canonical_shadow_result.get("storage_container_id"),
        "full_bucket_shape": shape,
    }


def build_canonical_bucket_post_materialization(
    *,
    canonical_key: str,
    symbol: str,
    strategy: str,
    side: str,
    materializer_name: str,
    source_container_name: str,
    nested_key_path: str | None,
    materialized_bucket: dict | None,
    storage_bucket_id=None,
    storage_container_id=None,
    runtime_seq: int | None = None,
    timestamp: str | None = None,
):
    if runtime_seq is None:
        runtime_seq = next_canonical_trace_seq()
    shape = _bucket_shape(materialized_bucket)
    return {
        "event": "canonical_bucket_post_materialization",
        "runtime_seq": int(runtime_seq),
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "strategy": strategy,
        "side": side,
        "canonical_key": canonical_key,
        "materializer_name": materializer_name,
        "source_container_name": source_container_name,
        "nested_key_path": nested_key_path,
        "trade_count": shape["trade_count"],
        "history_ready": shape["history_ready"],
        "gross_hist_len": shape["gross_hist_len"],
        "fee_hist_len": shape["fee_hist_len"],
        "slippage_hist_len": shape["slippage_hist_len"],
        "last_update_ts": shape["last_update_ts"],
        "object_id_or_equivalent_if_safe": id(materialized_bucket)
        if isinstance(materialized_bucket, dict)
        else None,
        "storage_bucket_id": storage_bucket_id,
        "storage_container_id": storage_container_id,
        "full_bucket_shape": shape,
    }


def build_canonical_bucket_collapse_compare(
    *,
    pre_payload: dict | None,
    post_payload: dict | None,
    runtime_seq: int | None = None,
    timestamp: str | None = None,
):
    pre_payload = dict(pre_payload or {})
    post_payload = dict(post_payload or {})
    if runtime_seq is None:
        runtime_seq = next_canonical_trace_seq()
    pre_trade_count = int(pre_payload.get("trade_count") or 0)
    post_trade_count = int(post_payload.get("trade_count") or 0)
    pre_gross_hist_len = int(pre_payload.get("gross_hist_len") or 0)
    post_gross_hist_len = int(post_payload.get("gross_hist_len") or 0)
    pre_fee_hist_len = int(pre_payload.get("fee_hist_len") or 0)
    post_fee_hist_len = int(post_payload.get("fee_hist_len") or 0)
    pre_slippage_hist_len = int(pre_payload.get("slippage_hist_len") or 0)
    post_slippage_hist_len = int(post_payload.get("slippage_hist_len") or 0)
    same_object = (
        pre_payload.get("object_id_or_equivalent_if_safe") is not None
        and post_payload.get("object_id_or_equivalent_if_safe") is not None
        and pre_payload.get("object_id_or_equivalent_if_safe")
        == post_payload.get("object_id_or_equivalent_if_safe")
    )
    same_nested_key_path = pre_payload.get("nested_key_path") == post_payload.get("nested_key_path")
    collapse_result = "UNKNOWN_COLLAPSE_STATE"
    if pre_trade_count > 0 and post_trade_count > 0:
        collapse_result = "NO_COLLAPSE_VISIBLE"
    elif pre_trade_count > 0 and post_trade_count == 0:
        if pre_gross_hist_len > 0 and post_gross_hist_len == 0 and pre_fee_hist_len > 0 and post_fee_hist_len == 0 and pre_slippage_hist_len > 0 and post_slippage_hist_len == 0:
            collapse_result = "FULL_DEFAULT_SHAPE_COLLAPSE"
        else:
            collapse_result = "TRADE_COUNT_COLLAPSED_TO_ZERO"
    elif pre_gross_hist_len > 0 and post_gross_hist_len == 0:
        collapse_result = "HISTORY_ARRAYS_COLLAPSED_TO_EMPTY"
    if not same_nested_key_path:
        collapse_result = "DIFFERENT_NESTED_PATH_AFTER_MATERIALIZATION"
    elif (
        pre_payload.get("storage_bucket_id") is not None
        and post_payload.get("storage_bucket_id") is not None
        and pre_payload.get("storage_bucket_id") != post_payload.get("storage_bucket_id")
    ):
        collapse_result = "DIFFERENT_OBJECT_AFTER_MATERIALIZATION"
    return {
        "event": "canonical_bucket_collapse_compare",
        "runtime_seq": int(runtime_seq),
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "canonical_key": pre_payload.get("canonical_key") or post_payload.get("canonical_key"),
        "pre_trade_count": pre_trade_count,
        "post_trade_count": post_trade_count,
        "pre_gross_hist_len": pre_gross_hist_len,
        "post_gross_hist_len": post_gross_hist_len,
        "pre_fee_hist_len": pre_fee_hist_len,
        "post_fee_hist_len": post_fee_hist_len,
        "pre_slippage_hist_len": pre_slippage_hist_len,
        "post_slippage_hist_len": post_slippage_hist_len,
        "same_object_identity_if_available": same_object,
        "same_nested_key_path": same_nested_key_path,
        "collapse_result": collapse_result,
        "pre_payload": pre_payload,
        "post_payload": post_payload,
    }


def classify_canonical_close_input_trace(
    gross_fill_pnl_model,
    fee_total,
    pnl_decompose: dict | None = None,
):
    gross_present = gross_fill_pnl_model is not None
    fee_present = fee_total is not None
    has_pnl_decompose = isinstance(pnl_decompose, dict)
    if not has_pnl_decompose:
        return "PNL_DECOMPOSE_MISSING"
    if gross_present and fee_present:
        return "REALIZED_INPUTS_PRESENT"
    if not gross_present and not fee_present:
        return "GROSS_AND_FEE_MISSING"
    if not gross_present:
        return "GROSS_MISSING_ONLY"
    if not fee_present:
        return "FEE_MISSING_ONLY"
    return "UNKNOWN"


def resolve_simulated_close_quantity(payload: dict):
    payload = dict(payload or {}) if isinstance(payload, dict) else {}
    candidates = []
    amount = payload.get("amount")
    amount_contracts = payload.get("amount_contracts")
    allocation_usdt = payload.get("allocation_usdt")
    paper_auto_open_usdt = payload.get("paper_auto_open_usdt")
    price = payload.get("entry_price") or payload.get("price") or payload.get("close_price")
    candidates.append(("amount", amount))
    candidates.append(("amount_contracts", amount_contracts))
    if allocation_usdt is not None and price not in (None, 0, 0.0):
        try:
            candidates.append(("allocation_usdt_div_price", float(allocation_usdt) / float(price)))
        except Exception:
            pass
    if paper_auto_open_usdt is not None and price not in (None, 0, 0.0):
        try:
            candidates.append(("paper_auto_open_usdt_div_entry_price", float(paper_auto_open_usdt) / float(price)))
        except Exception:
            pass
    for source, candidate in candidates:
        try:
            qty = float(candidate)
        except Exception:
            continue
        if qty > 0:
            return qty, source, "RAW_INPUTS_PRESENT"
    try:
        amount_val = float(amount) if amount is not None else None
    except Exception:
        amount_val = None
    try:
        amount_contracts_val = (
            float(amount_contracts) if amount_contracts is not None else None
        )
    except Exception:
        amount_contracts_val = None
    if amount_val in (0.0, None) and amount_contracts_val in (0.0, None):
        return 0.0, "amount", "ZERO_SIZE_CLOSE_INPUT"
    return None, "unknown", "UNKNOWN_RAW_INPUT_STATE"


def build_canonical_close_input_trace(
    *,
    symbol: str,
    strategy: str,
    side: str,
    position_id=None,
    net_pnl=None,
    gross_fill_pnl_model=None,
    fee_total=None,
    slippage_total=None,
    pnl_decompose: dict | None = None,
    source_function_name: str | None = None,
    upstream_source_name: str | None = None,
    runtime_seq: int | None = None,
    timestamp: str | None = None,
):
    canonical = build_canonical_bucket_key(
        {
            "symbol": symbol,
            "strategy": strategy,
            "side": side,
        }
    )
    if runtime_seq is None:
        runtime_seq = next_canonical_trace_seq()
    gross_present = gross_fill_pnl_model is not None
    fee_present = fee_total is not None
    promotion_inputs_ready = bool(gross_present and fee_present)
    return {
        "event": "canonical_close_input_trace",
        "runtime_seq": int(runtime_seq),
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "symbol": canonical.get("symbol"),
        "strategy": canonical.get("strategy_identity"),
        "side": canonical.get("side"),
        "canonical_key": canonical.get("canonical_bucket_key"),
        "raw_symbol": symbol,
        "raw_strategy": strategy,
        "raw_side": side,
        "normalized_symbol": canonical.get("normalized_symbol"),
        "normalized_strategy": canonical.get("normalized_strategy"),
        "normalized_side": canonical.get("normalized_side"),
        "position_id": position_id,
        "net_pnl": net_pnl,
        "gross_fill_pnl_model": gross_fill_pnl_model,
        "fee_total": fee_total,
        "slippage_total": slippage_total,
        "has_pnl_decompose": bool(isinstance(pnl_decompose, dict)),
        "source_function_name": source_function_name,
        "upstream_source_name": upstream_source_name,
        "gross_present": gross_present,
        "fee_present": fee_present,
        "promotion_inputs_ready": promotion_inputs_ready,
        "null_state_classification": classify_canonical_close_input_trace(
            gross_fill_pnl_model,
            fee_total,
            pnl_decompose=pnl_decompose,
        ),
    }


def promote_to_canonical_edge_history(
    *,
    symbol,
    strategy,
    side,
    gross_fill_pnl_model,
    fee_total,
    spread_slippage_proxy=None,
    ts=None,
    correlation_id: str | None = None,
):
    payload = {
        "symbol": symbol,
        "side": side,
        "strategy": strategy,
    }
    canonical = build_canonical_bucket_key(payload)
    if canonical["bucket_identity_status"] != "RESOLVED" or not canonical["canonical_bucket_key"]:
        record_unresolved_row(payload, reason=canonical["bucket_identity_reason"], event_name="position_close")
        return {
            **canonical,
            "canonical_shadow_trade_count": 0,
            "canonical_shadow_history_ready": False,
            "canonical_shadow_last_update_ts": None,
            "shadow_bucket": None,
            "storage_target_name": "canonical_shadow_storage",
            "bucket_created_on_this_event": False,
        }

    symbol_key = canonical["symbol"]
    strategy_key = canonical["strategy_identity"]
    side_key = canonical["side"]
    symbol_exists = symbol_key in canonical_edge_history_state
    symbol_map = canonical_edge_history_state[symbol_key]
    strategy_exists = strategy_key in symbol_map
    strategy_map = symbol_map[strategy_key]
    bucket_exists = side_key in strategy_map
    bucket = strategy_map[side_key]
    bucket_created_on_this_event = not (symbol_exists and strategy_exists and bucket_exists)
    bucket["gross_hist"].append(float(gross_fill_pnl_model or 0.0))
    bucket["fee_hist"].append(float(fee_total or 0.0))
    bucket["slippage_hist"].append(float(spread_slippage_proxy or 0.0))
    bucket["trade_count"] = len(bucket["gross_hist"])
    bucket["last_update_ts"] = ts or datetime.now(timezone.utc).timestamp()
    bucket["last_write_key"] = canonical["canonical_bucket_key"]
    bucket["last_write_ts"] = bucket["last_update_ts"]
    resolved_correlation_id = str(
        correlation_id
        or build_canonical_correlation_id(
            canonical_key=canonical["canonical_bucket_key"],
            symbol=canonical["symbol"],
            strategy=canonical["strategy_identity"],
            side=canonical["side"],
            runtime_seq=bucket["trade_count"],
            created_at=str(bucket["last_write_ts"]),
        )
    )
    post_write_readback_trade_count = 0
    post_write_readback_key = None
    post_write_readback_confirmed = False
    post_write_readback_exception_class = None
    post_write_readback_exception_message = None
    try:
        readback_bucket = (
            canonical_edge_history_state.get(symbol_key, {})
            .get(strategy_key, {})
            .get(side_key, {})
        )
        post_write_readback_trade_count = int(readback_bucket.get("trade_count") or 0)
        post_write_readback_key = readback_bucket.get("last_write_key")
        post_write_readback_confirmed = bool(
            post_write_readback_key == canonical["canonical_bucket_key"]
            and post_write_readback_trade_count == int(bucket["trade_count"] or 0)
        )
        if not post_write_readback_confirmed:
            raise RuntimeError(
                "post-write canonical readback invariant failed"
            )
    except Exception as exc:
        post_write_readback_exception_class = type(exc).__name__
        post_write_readback_exception_message = str(exc)
    global canonical_promotion_count
    canonical_promotion_count += 1
    return {
        **canonical,
        "correlation_id": resolved_correlation_id,
        "canonical_key_write": canonical["canonical_bucket_key"],
        "canonical_shadow_trade_count": bucket["trade_count"],
        "trade_count_written": bucket["trade_count"],
        "canonical_shadow_history_ready": bool(bucket["trade_count"] >= 20),
        "canonical_shadow_last_update_ts": bucket["last_update_ts"],
        "write_timestamp": bucket["last_write_ts"],
        "storage_container_name": "canonical_edge_history_state",
        "storage_container_id": id(canonical_edge_history_state),
        "storage_bucket_id": id(bucket),
        "nested_key_path": f"[{symbol_key}][{strategy_key}][{side_key}]",
        "shadow_bucket": {
            "gross_hist": list(bucket.get("gross_hist") or []),
            "fee_hist": list(bucket.get("fee_hist") or []),
            "slippage_hist": list(bucket.get("slippage_hist") or []),
            "trade_count": int(bucket.get("trade_count") or 0),
            "history_ready": bool(int(bucket.get("trade_count") or 0) >= 20),
            "last_update_ts": bucket.get("last_update_ts"),
            "last_write_key": bucket.get("last_write_key"),
            "last_write_ts": bucket.get("last_write_ts"),
        },
        "storage_target_name": "canonical_shadow_storage",
        "bucket_created_on_this_event": bucket_created_on_this_event,
        "post_write_readback_stage": "readback",
        "post_write_readback_trade_count": post_write_readback_trade_count,
        "post_write_readback_key": post_write_readback_key,
        "post_write_readback_confirmed": bool(post_write_readback_confirmed),
        "post_write_readback_exception_class": post_write_readback_exception_class,
        "post_write_readback_exception_message": post_write_readback_exception_message,
    }


def get_canonical_edge_history(symbol, strategy, side, min_trades=20, correlation_id: str | None = None):
    payload = {"symbol": symbol, "strategy": strategy, "side": side}
    canonical = build_canonical_bucket_key(payload)
    if canonical["bucket_identity_status"] != "RESOLVED" or not canonical["canonical_bucket_key"]:
        return {
            **canonical,
            "correlation_id": correlation_id,
            "canonical_shadow_trade_count": 0,
            "canonical_shadow_history_ready": False,
            "canonical_shadow_last_update_ts": None,
            "canonical_key_read": canonical["canonical_bucket_key"],
            "trade_count_read": 0,
            "last_write_key": None,
            "last_write_ts": None,
            "read_source_name": "canonical_shadow_storage",
            "read_container_name": "canonical_edge_history_state",
            "storage_container_id": id(canonical_edge_history_state),
            "shadow_bucket": None,
        }
    bucket = (
        canonical_edge_history_state.get(canonical["symbol"], {})
        .get(canonical["strategy_identity"], {})
        .get(canonical["side"], {})
    )
    trade_count = int(bucket.get("trade_count") or 0)
    return {
        **canonical,
        "correlation_id": correlation_id,
        "canonical_key_read": canonical["canonical_bucket_key"],
        "canonical_shadow_trade_count": trade_count,
        "trade_count_read": trade_count,
        "canonical_shadow_history_ready": bool(trade_count >= int(min_trades)),
        "canonical_shadow_last_update_ts": bucket.get("last_update_ts"),
        "last_write_key": bucket.get("last_write_key"),
        "last_write_ts": bucket.get("last_write_ts"),
        "read_source_name": "canonical_shadow_storage",
        "read_container_name": "canonical_edge_history_state",
        "storage_container_id": id(canonical_edge_history_state),
        "storage_bucket_id": id(bucket),
        "nested_key_path": (
            f"[{canonical['symbol']}][{canonical['strategy_identity']}][{canonical['side']}]"
        ),
        "shadow_bucket": {
            "gross_hist": list(bucket.get("gross_hist") or []),
            "fee_hist": list(bucket.get("fee_hist") or []),
            "slippage_hist": list(bucket.get("slippage_hist") or []),
            "trade_count": trade_count,
            "last_update_ts": bucket.get("last_update_ts"),
            "last_write_key": bucket.get("last_write_key"),
            "last_write_ts": bucket.get("last_write_ts"),
        },
    }


def get_canonical_unresolved_pool():
    return list(canonical_unresolved_pool)


def get_canonical_promotion_count():
    return int(canonical_promotion_count)


def classify_post_promotion_read_path_trace(trace: dict | None):
    trace = dict(trace or {})
    if not bool(trace.get("post_promotion_eval_enter")):
        return "POST_PROMOTION_EVAL_NOT_ENTERED"
    if not bool(trace.get("post_promotion_gate_read_emit_attempt")):
        return "POST_PROMOTION_EVAL_ENTERED_BUT_GATE_READ_NOT_EMITTED"
    if not bool(trace.get("post_promotion_gate_read_emit_done")):
        return "POST_PROMOTION_GATE_READ_EMITTED_BUT_NOT_PERSISTED"
    visible_trade_count = int(
        trace.get("post_promotion_read_trade_count_visible")
        or trace.get("read_trade_count")
        or trace.get("trade_count_read")
        or 0
    )
    if visible_trade_count > 0:
        return "POST_PROMOTION_GATE_READ_PERSISTED_WITH_NONZERO_VISIBILITY"
    return "POST_PROMOTION_GATE_READ_EMITTED_BUT_NOT_PERSISTED"


def classify_post_promotion_arm_trace(trace: dict | None):
    trace = dict(trace or {})
    if not bool(trace.get("post_promotion_arm_considered")):
        return "ARM_NOT_CONSIDERED"
    if not bool(trace.get("post_promotion_arm_allowed")):
        return "ARM_CONSIDERED_BUT_PREDICATE_FAILED"
    if bool(trace.get("post_promotion_arm_cleared")) and not bool(
        trace.get("post_promotion_invoke_expected")
    ):
        return "ARM_SET_THEN_CLEARED_BEFORE_INVOKE"
    if bool(trace.get("post_promotion_arm_set")) and bool(trace.get("post_promotion_invoke_missed_reason")):
        return "ARM_SET_BUT_INVOKE_PATH_MISSED"
    if bool(trace.get("post_promotion_arm_set")) and bool(trace.get("post_promotion_invoke_expected")):
        return "ARM_SET_AND_INVOKED"
    return "ARM_SET_BUT_INVOKE_PATH_MISSED"


def classify_explicit_post_promotion_eval_disabled_provenance(trace: dict | None):
    trace = dict(trace or {})
    if bool(trace.get("explicit_post_promotion_eval_enabled_resolved")) and bool(
        trace.get("post_promotion_arm_set")
    ):
        return "ENABLED_AND_ARMED"
    if str(trace.get("explicit_post_promotion_eval_enabled_source") or "").upper() == "BOTCORE_LOCAL_OVERRIDE":
        return "DISABLED_BY_BOTCORE_LOCAL_OVERRIDE"
    if bool(trace.get("explicit_post_promotion_eval_runner_request_present")) and not bool(
        trace.get("explicit_post_promotion_eval_botcore_flag_present")
    ):
        return "DISABLED_BY_RUNNER_HANDOFF_MISMATCH"
    if bool(trace.get("explicit_post_promotion_eval_default_used")) or str(
        trace.get("explicit_post_promotion_eval_enabled_source") or ""
    ).upper() == "DEFAULT_CONFIG":
        return "DISABLED_BY_DEFAULT_CONFIG"
    if str(trace.get("explicit_post_promotion_eval_enabled_source") or "").upper() == "ENV_RESOLUTION":
        return "DISABLED_BY_ENV_RESOLUTION"
    return "DISABLED_BY_DEFAULT_CONFIG"


def classify_explicit_post_promotion_invoke_trace(trace: dict | None):
    trace = dict(trace or {})
    if bool(trace.get("post_invoke_emit_attempt_call_enter")) or bool(trace.get("post_invoke_emit_attempt_reached")):
        return "EMIT_ATTEMPT_CALL_REACHED"
    if bool(trace.get("post_invoke_emit_early_return")):
        return "INVOKE_COMPLETED_BUT_EARLY_RETURN"
    if bool(trace.get("post_invoke_emit_guard_considered")) and not bool(
        trace.get("post_invoke_emit_guard_allowed")
    ):
        return "INVOKE_COMPLETED_BUT_EMIT_GUARD_FALSE"
    if bool(trace.get("post_invoke_emit_path_enter")) and not bool(
        trace.get("post_invoke_emit_attempt_call_enter")
    ):
        return "INVOKE_COMPLETED_BUT_EMIT_STAGE_NOT_REACHED"
    if not bool(trace.get("explicit_post_promotion_invoke_enter")):
        return "INVOKE_EXITED_BEFORE_EMIT_BRANCH"
    if not bool(trace.get("explicit_post_promotion_emit_branch_considered")):
        return "INVOKE_EXITED_BEFORE_EMIT_BRANCH"
    if trace.get("explicit_post_promotion_emit_exception_class"):
        return "EMIT_BRANCH_ABORTED_BY_EXCEPTION"
    if bool(trace.get("explicit_post_promotion_invoke_stage") == "emit_branch_exception_before_attempt"):
        return "EMIT_BRANCH_ABORTED_BY_EXCEPTION"
    if not bool(trace.get("explicit_post_promotion_emit_branch_allowed")):
        return "EMIT_BRANCH_CONSIDERED_BUT_PREDICATE_FAILED"
    if trace.get("explicit_post_promotion_emit_early_return_reason"):
        return "EMIT_BRANCH_BLOCKED_BY_SUBPREDICATE"
    if bool(trace.get("explicit_post_promotion_gate_read_emit_attempt")) and not bool(
        trace.get("explicit_post_promotion_gate_read_emit_done")
    ):
        return "EMIT_ATTEMPTED_BUT_NOT_PERSISTED"
    if bool(trace.get("explicit_post_promotion_invoke_exit")) and not bool(
        trace.get("explicit_post_promotion_gate_read_emit_done")
    ):
        return "EMIT_ATTEMPTED_BUT_NOT_PERSISTED"
    if bool(trace.get("canonical_gate_read")) and bool(
        trace.get("explicit_post_promotion_invoke_exit")
    ):
        return "EMIT_DONE_AND_PERSISTED"
    if bool(trace.get("explicit_post_promotion_gate_read_emit_attempt")) and not bool(
        trace.get("explicit_post_promotion_gate_read_emit_done")
    ):
        return "EMIT_ATTEMPTED_BUT_NOT_PERSISTED"
    if bool(trace.get("canonical_gate_read")):
        return "EMIT_DONE_AND_PERSISTED"
    if not bool(trace.get("explicit_post_promotion_emit_branch_entered")):
        return "EMIT_BRANCH_ENTERED_BUT_ATTEMPT_NOT_REACHED"
    return "EMIT_BRANCH_ENTERED_BUT_ATTEMPT_NOT_REACHED"


def classify_post_promotion_force_cycle_handoff_trace(trace: dict | None):
    trace = dict(trace or {})
    if not bool(trace.get("post_promotion_force_cycle_handoff_enter")):
        return "FORCE_CYCLE_HANDOFF_NOT_REACHED"
    if bool(trace.get("handoff_child_mailbox_dequeue_enter")):
        return "HANDOFF_CHILD_MAILBOX_DEQUEUED"
    if bool(trace.get("handoff_child_mailbox_observed")):
        return "HANDOFF_CHILD_MAILBOX_OBSERVED"
    if bool(trace.get("handoff_parent_signal_sent")):
        return "HANDOFF_PARENT_SIGNAL_SENT"
    if bool(trace.get("handoff_parent_enqueue_done")):
        return "HANDOFF_PARENT_ENQUEUE_COMPLETED"
    if bool(trace.get("handoff_parent_enqueue_enter")):
        return "HANDOFF_PARENT_ENQUEUE_ENTERED"
    if bool(trace.get("handoff_decision_emit_call_done")):
        decision = str(trace.get("post_promotion_force_cycle_handoff_decision") or "").strip()
        if decision in {
            "HANDOFF_REJECTED_BY_LOCK",
            "HANDOFF_REJECTED_BY_DEDUPE",
            "HANDOFF_REJECTED_BY_OBSERVATION_WINDOW",
            "HANDOFF_REJECTED_BY_MISSING_CONTEXT",
            "HANDOFF_REACHED_BUT_REQUEST_NOT_ENQUEUED",
            "HANDOFF_ACCEPTED_AND_REQUESTED",
        }:
            return decision
        return "HANDOFF_DECISION_EMIT_SITE_REACHED"
    if bool(trace.get("handoff_child_callback_enter")):
        return "HANDOFF_CHILD_CALLBACK_ENTERED"
    if bool(trace.get("handoff_child_loop_enter")):
        return "HANDOFF_CHILD_LOOP_ENTERED"
    if bool(trace.get("handoff_child_dispatch_accept_for_processing")):
        return "HANDOFF_CHILD_ACCEPTED_FOR_PROCESSING"
    if bool(trace.get("handoff_child_dispatch_enter")):
        return "HANDOFF_CHILD_DISPATCH_ENTERED"
    if bool(trace.get("handoff_decision_emit_prelude_enter")) and not bool(trace.get("handoff_decision_emit_call_done")):
        return "HANDOFF_DECISION_PAYLOAD_BUILT_BUT_EMIT_NOT_COMPLETED"
    pre_decision_return_site_id = str(trace.get("handoff_pre_decision_return_site_id") or "").strip()
    pre_decision_return_reason = str(trace.get("handoff_pre_decision_return_reason") or "").strip()
    if pre_decision_return_site_id:
        return pre_decision_return_site_id.upper()
    decision = str(trace.get("post_promotion_force_cycle_handoff_decision") or "").strip()
    if decision in {
        "HANDOFF_REJECTED_BY_LOCK",
        "HANDOFF_REJECTED_BY_DEDUPE",
        "HANDOFF_REJECTED_BY_OBSERVATION_WINDOW",
        "HANDOFF_REJECTED_BY_MISSING_CONTEXT",
        "HANDOFF_REACHED_BUT_REQUEST_NOT_ENQUEUED",
        "HANDOFF_ACCEPTED_AND_REQUESTED",
    }:
        return decision
    reject_reason = str(trace.get("post_promotion_force_cycle_handoff_reject_reason") or trace.get("reject_reason") or trace.get("skip_reason") or "").strip()
    if reject_reason == "HANDOFF_REJECTED_BY_LOCK":
        return "HANDOFF_REJECTED_BY_LOCK"
    if reject_reason == "HANDOFF_REJECTED_BY_DEDUPE":
        return "HANDOFF_REJECTED_BY_DEDUPE"
    if reject_reason == "HANDOFF_REJECTED_BY_OBSERVATION_WINDOW":
        return "HANDOFF_REJECTED_BY_OBSERVATION_WINDOW"
    if reject_reason == "HANDOFF_REJECTED_BY_MISSING_CONTEXT":
        return "HANDOFF_REJECTED_BY_MISSING_CONTEXT"
    if reject_reason == "HANDOFF_REACHED_BUT_REQUEST_NOT_ENQUEUED":
        return "HANDOFF_REACHED_BUT_REQUEST_NOT_ENQUEUED"
    if bool(trace.get("post_promotion_force_cycle_handoff_reject")) or reject_reason:
        return "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED"
    if not bool(trace.get("post_promotion_force_cycle_handoff_accept")):
        return "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED"
    return "HANDOFF_ACCEPTED_AND_REQUESTED"


def classify_forced_cycle_trace(trace: dict | None):
    trace = dict(trace or {})
    caller_enter = bool(trace.get("forced_cycle_scheduler_caller_enter"))
    caller_exit = bool(trace.get("forced_cycle_scheduler_caller_exit"))
    scheduler_tick_enter = bool(trace.get("forced_cycle_scheduler_tick_enter"))
    request_scan_enter = bool(trace.get("forced_cycle_request_scan_enter"))
    request_scan_empty = bool(trace.get("forced_cycle_request_scan_empty"))
    request_scan_nonempty = bool(trace.get("forced_cycle_request_scan_nonempty"))
    request_scan_result = bool(trace.get("forced_cycle_request_scan_result"))
    pre_drain_candidate = bool(trace.get("forced_cycle_pre_drain_candidate"))
    pre_drain_enter = bool(trace.get("forced_cycle_pre_drain_enter"))
    pre_drain_reject = bool(trace.get("forced_cycle_pre_drain_reject"))
    pre_drain_reject_reason = str(
        trace.get("forced_cycle_pre_drain_reject_reason") or trace.get("pre_drain_reject_reason") or ""
    ).strip()
    pre_drain_return_reason = str(
        trace.get("forced_cycle_pre_drain_return_reason") or trace.get("pre_drain_return_reason") or ""
    ).strip()
    if scheduler_tick_enter or request_scan_enter or request_scan_empty or request_scan_nonempty or request_scan_result:
        if scheduler_tick_enter:
            if request_scan_enter and not request_scan_result and not request_scan_empty and not request_scan_nonempty:
                return "FORCED_CYCLE_REQUEST_SCAN_NOT_ENTERED"
            if bool(trace.get("forced_cycle_request_scan_empty")):
                return "FORCED_CYCLE_REQUEST_SCAN_EMPTY"
            if bool(trace.get("forced_cycle_request_scan_nonempty")):
                if pre_drain_enter and bool(trace.get("post_promotion_force_cycle_drain_enter")):
                    return "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
                if pre_drain_enter:
                    return "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
                if pre_drain_candidate or pre_drain_reject or pre_drain_reject_reason or pre_drain_return_reason:
                    return "PRE_DRAIN_TRANSITION_BLOCKER_PROVEN_BUT_NOT_FIXED"
                if not bool(trace.get("post_promotion_force_cycle_drain_enter")):
                    return "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY_BUT_PRE_DRAIN_NOT_ENTERED"
                return "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY"
            if bool(trace.get("forced_cycle_request_scan_result")):
                return "FORCED_CYCLE_REQUEST_SCAN_RESULT_REACHED"
            return "FORCED_CYCLE_SCHEDULER_TICK_ENTERED"
        if request_scan_enter and not request_scan_result and not request_scan_empty and not request_scan_nonempty:
            return "FORCED_CYCLE_REQUEST_SCAN_NOT_ENTERED"
        if request_scan_nonempty:
            if pre_drain_enter and bool(trace.get("post_promotion_force_cycle_drain_enter")):
                return "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
            if pre_drain_enter:
                return "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
            if pre_drain_candidate or pre_drain_reject or pre_drain_reject_reason or pre_drain_return_reason:
                return "PRE_DRAIN_TRANSITION_BLOCKER_PROVEN_BUT_NOT_FIXED"
            if not bool(trace.get("post_promotion_force_cycle_drain_enter")):
                return "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY_BUT_PRE_DRAIN_NOT_ENTERED"
            return "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY"
        if request_scan_empty:
            return "FORCED_CYCLE_REQUEST_SCAN_EMPTY"
        if request_scan_result:
            return "FORCED_CYCLE_REQUEST_SCAN_RESULT_REACHED"
    if caller_enter or caller_exit:
        if caller_enter and caller_exit and not scheduler_tick_enter:
            return "FORCED_CYCLE_SCHEDULER_CALLER_RETURNED_WITHOUT_TICK"
        if caller_enter and not scheduler_tick_enter:
            return "FORCED_CYCLE_SCHEDULER_CALLER_ENTERED_BUT_TICK_NOT_ENTERED"
        if caller_exit and not caller_enter and not scheduler_tick_enter:
            return "FORCED_CYCLE_SCHEDULER_CALLER_NOT_ENTERED"
    forced_cycle_deeper_evidence = bool(
        trace.get("post_promotion_force_cycle_drain_enter")
        or trace.get("forced_cycle_pre_drain_candidate")
        or trace.get("forced_cycle_pre_drain_reject")
        or trace.get("forced_cycle_pre_drain_enter")
        or trace.get("forced_cycle_pre_drain_return")
        or trace.get("forced_cycle_pending_check_enter")
        or trace.get("forced_cycle_pending_check_result")
        or trace.get("forced_cycle_pending_visible")
        or trace.get("forced_cycle_pending_not_visible")
        or trace.get("forced_cycle_drain_enter")
        or trace.get("forced_cycle_eval_entry")
        or trace.get("forced_cycle_eval_pre_router")
        or trace.get("forced_cycle_eval_post_router")
        or trace.get("forced_cycle_eval_pre_entry_edge_check")
        or trace.get("forced_cycle_eval_post_entry_edge_check")
    )
    if bool(trace.get("forced_cycle_requested")) and not bool(trace.get("forced_cycle_started")) and not forced_cycle_deeper_evidence:
        return "FORCED_CYCLE_SCHEDULER_TICK_NOT_ENTERED"
    if bool(trace.get("forced_cycle_scheduler_gate_blocked")):
        return "FORCED_CYCLE_SCHEDULER_GATE_BLOCKED"
    if bool(trace.get("forced_cycle_scheduler_gate_allowed")) and not bool(trace.get("forced_cycle_scheduler_tick_enter")):
        return "FORCED_CYCLE_SCHEDULER_GATE_ALLOWED_BUT_TICK_NOT_ENTERED"
    if bool(trace.get("forced_cycle_pending_visible")):
        return "FORCED_CYCLE_PENDING_VISIBLE"
    if bool(trace.get("forced_cycle_pending_not_visible")):
        return "FORCED_CYCLE_PENDING_NOT_VISIBLE"
    if bool(trace.get("forced_cycle_drain_skipped")):
        return "FORCED_CYCLE_DRAIN_SKIPPED"
    if bool(trace.get("forced_cycle_drain_enter")) and not bool(trace.get("forced_cycle_started")):
        return "FORCED_CYCLE_DRAIN_ENTERED"
    if not bool(trace.get("post_promotion_force_cycle_handoff_enter")):
        return "FORCE_CYCLE_HANDOFF_NOT_REACHED"
    if bool(trace.get("post_promotion_force_cycle_handoff_reject")) or trace.get(
        "post_promotion_force_cycle_handoff_reject_reason"
    ):
        return "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED"
    if not bool(trace.get("post_promotion_force_cycle_handoff_accept")):
        return "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED"
    if not bool(trace.get("forced_cycle_started")):
        return "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED"
    if not bool(trace.get("forced_cycle_eval_entry")):
        return "FORCED_CYCLE_CALLED_BUT_LOOP_NOT_ENTERED"
    if not bool(trace.get("forced_cycle_eval_pre_entry_edge_check")):
        return "FORCED_CYCLE_LOOP_ENTERED_BUT_EVALUATED_PATH_NOT_INVOKED"
    if not bool(trace.get("forced_cycle_eval_post_router")):
        return "FORCED_CYCLE_EVALUATED_PATH_INVOKED_BUT_SELECTOR_NOT_ENTERED"
    pre_selector_site_id = str(
        trace.get("forced_cycle_eval_pre_selector_return_site_id") or ""
    ).strip()
    pre_selector_return_reason = str(
        trace.get("forced_cycle_eval_pre_selector_return_reason") or ""
    ).strip()
    pre_selector_helper_result_type = str(
        trace.get("forced_cycle_eval_pre_selector_helper_result_type") or ""
    ).strip()
    pre_selector_contract_failure_reason = str(
        trace.get("forced_cycle_eval_pre_selector_contract_failure_reason") or ""
    ).strip()
    pre_selector_actual_return_type = str(
        trace.get("forced_cycle_eval_pre_selector_actual_return_type") or ""
    ).strip()
    pre_selector_actual_return_is_none = bool(
        trace.get("forced_cycle_eval_pre_selector_actual_return_is_none")
    )
    pre_selector_callable_name = str(
        trace.get("forced_cycle_eval_pre_selector_callable_name") or ""
    ).strip()
    pre_selector_callable_module = str(
        trace.get("forced_cycle_eval_pre_selector_callable_module") or ""
    ).strip()
    if pre_selector_site_id == "pre_selector_guard_return":
        return "FORCED_CYCLE_PRE_SELECTOR_GUARD_RETURN"
    if pre_selector_site_id == "missing_selector_context":
        return "FORCED_CYCLE_MISSING_SELECTOR_CONTEXT"
    if pre_selector_site_id == "non_emit_success_path":
        return "FORCED_CYCLE_NON_EMIT_SUCCESS_PATH"
    if pre_selector_site_id == "position_state_short_circuit":
        return "FORCED_CYCLE_POSITION_STATE_SHORT_CIRCUIT"
    if pre_selector_site_id == "router_postprocess_return":
        return "FORCED_CYCLE_ROUTER_POSTPROCESS_RETURN"
    if pre_selector_site_id == "helper_returned_none" or (
        pre_selector_contract_failure_reason == "HELPER_RETURNED_NONE"
        or pre_selector_actual_return_is_none
        or pre_selector_helper_result_type == "NoneType"
        or pre_selector_return_reason == "HELPER_RETURNED_NONE"
    ):
        return "HELPER_RETURNED_NONE"
    if pre_selector_site_id == "helper_returned_non_dict_result" or (
        pre_selector_contract_failure_reason == "HELPER_RETURNED_NON_DICT_RESULT"
        or pre_selector_return_reason == "HELPER_RETURNED_NON_DICT_RESULT"
        or (
            pre_selector_actual_return_type
            and pre_selector_actual_return_type != "dict"
            and not pre_selector_actual_return_is_none
        )
    ):
        return "HELPER_RETURNED_NON_DICT_RESULT"
    if pre_selector_site_id == "helper_returned_dict_missing_required_fields" or (
        pre_selector_contract_failure_reason
        == "HELPER_RETURNED_DICT_MISSING_REQUIRED_FIELDS"
        or pre_selector_return_reason
        == "HELPER_RETURNED_DICT_MISSING_REQUIRED_FIELDS"
    ):
        return "HELPER_RETURNED_DICT_MISSING_REQUIRED_FIELDS"
    if pre_selector_site_id == "wrapper_expectation_mismatch" or (
        pre_selector_contract_failure_reason == "WRAPPER_EXPECTATION_MISMATCH"
        or pre_selector_return_reason == "WRAPPER_EXPECTATION_MISMATCH"
    ):
        return "WRAPPER_EXPECTATION_MISMATCH"
    if pre_selector_site_id == "selector_context_not_built" or (
        pre_selector_contract_failure_reason
        == "VALID_HELPER_RESULT_BUT_SELECTOR_CONTEXT_NOT_BUILT"
        or pre_selector_return_reason
        == "VALID_HELPER_RESULT_BUT_SELECTOR_CONTEXT_NOT_BUILT"
    ):
        return "VALID_HELPER_RESULT_BUT_SELECTOR_CONTEXT_NOT_BUILT"
    if pre_selector_site_id == "unknown_pre_selector_return":
        return "FORCED_CYCLE_UNKNOWN_PRE_SELECTOR_RETURN"
    if not pre_selector_site_id and (
        pre_selector_helper_result_type == "NoneType"
        or pre_selector_return_reason == "non_dict_helper_result"
    ):
        return "FORCED_CYCLE_UNKNOWN_PRE_SELECTOR_RETURN"
    if not bool(trace.get("evaluated_path_enter_after_forced_cycle")):
        return "FORCED_CYCLE_EVALUATED_PATH_INVOKED_BUT_SELECTOR_NOT_ENTERED"
    if not bool(trace.get("canonical_gate_read_branch_selector_enter")):
        return "FORCED_CYCLE_EVALUATED_PATH_INVOKED_BUT_SELECTOR_NOT_ENTERED"
    if not bool(trace.get("canonical_gate_read_emit_candidate")):
        return "FORCED_CYCLE_REACHED_SELECTOR_BUT_CANDIDATE_NOT_CREATED"
    if not bool(trace.get("canonical_gate_read_emit_guard_considered")):
        return "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_NOT_ENTERED"
    if bool(trace.get("canonical_gate_read_emit_guard_blocked")):
        return "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_BLOCKED"
    if bool(trace.get("canonical_gate_read_emit_candidate")) and bool(trace.get("canonical_gate_read_emit_guard_considered")) and not bool(trace.get("canonical_gate_read_emit_attempt")):
        return "FORCED_CYCLE_REACHED_CANDIDATE_BUT_EMIT_NOT_ATTEMPTED"
    if not bool(trace.get("canonical_gate_read_emit_done")):
        return "FORCED_CYCLE_REACHED_EMIT_ATTEMPT_BUT_NOT_DONE"
    return "FULL_POST_PROMOTION_PIPELINE_CONFIRMED"


def compare_canonical_shadow_materialization(write_payload: dict | None, read_payload: dict | None):
    write_payload = dict(write_payload or {})
    read_payload = dict(read_payload or {})
    correlation_id = (
        write_payload.get("correlation_id")
        or read_payload.get("correlation_id")
    )
    stage_written = bool(write_payload.get("canonical_bucket_key") or write_payload.get("promotion_write_canonical_key"))
    stage_emit_attempted = bool(
        read_payload.get("post_promotion_gate_read_emit_attempt")
        or read_payload.get("explicit_post_promotion_gate_read_emit_attempt")
    )
    stage_persisted = bool(
        read_payload.get("post_promotion_gate_read_emit_done")
        or read_payload.get("explicit_post_promotion_gate_read_emit_done")
        or read_payload.get("canonical_key_read")
        or read_payload.get("next_read_canonical_key")
    )
    stage_observed = bool(
        int(read_payload.get("read_trade_count") or read_payload.get("next_read_trade_count") or 0) > 0
    )
    stage_exception = bool(
        write_payload.get("post_write_readback_exception_class")
        or read_payload.get("explicit_post_promotion_emit_exception_class")
    )
    final_per_correlation_verdict = "WRITE_SUCCEEDED_BUT_EMIT_NOT_ATTEMPTED"
    if stage_exception:
        final_per_correlation_verdict = "EXCEPTION_SWALLOWED_IN_CRITICAL_PATH"
    elif stage_written and stage_observed:
        final_per_correlation_verdict = "WRITE_SUCCEEDED_READBACK_CONFIRMED"
    elif stage_emit_attempted and not stage_persisted:
        final_per_correlation_verdict = "EMIT_ATTEMPTED_BUT_NOT_PERSISTED"
    elif stage_persisted and not stage_observed:
        final_per_correlation_verdict = "PERSISTED_BUT_NOT_OBSERVED"
    elif stage_written and not stage_emit_attempted:
        final_per_correlation_verdict = "WRITE_SUCCEEDED_BUT_EMIT_NOT_ATTEMPTED"
    write_key = write_payload.get("canonical_bucket_key")
    read_key = read_payload.get("canonical_bucket_key")
    next_read_canonical_key = read_payload.get("next_read_canonical_key") or read_payload.get(
        "canonical_key_read"
    )
    comparison_result = "UNKNOWN_COMPARISON_STATE"
    same_container_name = write_payload.get("storage_target_name") == read_payload.get("read_source_name")
    same_nested_key_path = write_payload.get("nested_key_path") == read_payload.get("nested_key_path")
    same_object_identity_if_available = (
        write_payload.get("storage_bucket_id") is not None
        and read_payload.get("storage_bucket_id") is not None
        and write_payload.get("storage_bucket_id") == read_payload.get("storage_bucket_id")
    )
    write_trade_count = int(write_payload.get("stored_trade_count") or write_payload.get("trade_count_after") or 0)
    read_trade_count = int(read_payload.get("read_trade_count") or read_payload.get("canonical_shadow_trade_count") or 0)
    write_gross_hist_len = int((write_payload.get("stored_bucket_shape") or {}).get("gross_hist_len") or write_trade_count)
    read_gross_hist_len = int((read_payload.get("read_source_bucket_shape") or {}).get("gross_hist_len") or 0)
    write_seen = bool(write_key)
    read_seen = bool(next_read_canonical_key or read_key)
    same_bucket_match_strict = bool(
        write_seen
        and read_seen
        and write_key == (next_read_canonical_key or read_key)
        and write_trade_count > 0
        and read_trade_count > 0
    )
    promotion_to_next_read_delay_ms = None
    try:
        if read_payload.get("promotion_to_next_read_delay_ms") is not None:
            promotion_to_next_read_delay_ms = float(
                read_payload.get("promotion_to_next_read_delay_ms")
            )
    except Exception:
        promotion_to_next_read_delay_ms = None
    if promotion_to_next_read_delay_ms is None:
        try:
            if read_payload.get("write_to_read_delay_ms") is not None:
                promotion_to_next_read_delay_ms = float(
                    read_payload.get("write_to_read_delay_ms")
                )
        except Exception:
            promotion_to_next_read_delay_ms = None
    if promotion_to_next_read_delay_ms is None:
        write_ts = write_payload.get("write_timestamp") or write_payload.get("timestamp")
        read_ts = read_payload.get("timestamp") or read_payload.get("row_ts")
        write_epoch = _coerce_epoch_seconds(write_ts)
        read_epoch = _coerce_epoch_seconds(read_ts)
        if write_epoch is not None and read_epoch is not None:
            promotion_to_next_read_delay_ms = max(0.0, (float(read_epoch) - float(write_epoch)) * 1000.0)
    if not write_seen or not write_payload.get("promotion_write_source_payload_present", True):
        classification = "WRITE_PATH_DID_NOT_APPEND_BUCKET"
    elif write_trade_count <= 0:
        classification = "WRITE_PATH_APPENDED_ZERO_HISTORY_BUCKET"
    elif same_bucket_match_strict:
        classification = "WRITE_PATH_APPENDED_NONZERO_BUCKET_AND_READ_SAW_IT"
    else:
        classification = "WRITE_PATH_APPENDED_NONZERO_BUCKET_BUT_READ_DID_NOT_SEE_IT"
    if not write_seen and read_seen:
        comparison_result = "READ_WITHOUT_MATCHING_WRITE"
    elif write_seen and not read_seen:
        comparison_result = "WRITE_WITHOUT_MATCHING_READ"
    elif same_container_name and same_nested_key_path and same_object_identity_if_available:
        if write_trade_count > 0 and read_trade_count > 0:
            comparison_result = "MATCH_VISIBLE"
        elif write_trade_count > 0 and read_trade_count == 0:
            comparison_result = "MATCH_BUT_ZEROED_ON_READ"
        else:
            comparison_result = "UNKNOWN_COMPARISON_STATE"
    elif same_container_name and not same_nested_key_path:
        comparison_result = "MATCH_BUT_DIFFERENT_NESTED_PATH"
    elif write_key == read_key and not same_object_identity_if_available:
        comparison_result = "MATCH_BUT_DIFFERENT_OBJECT"
    return {
        "event": "canonical_storage_compare_trace",
        "correlation_id": correlation_id,
        "canonical_key": write_key or read_key,
        "promotion_write_canonical_key": write_key,
        "promotion_write_trade_count": write_trade_count,
        "promotion_write_history_ready": bool(write_payload.get("stored_history_ready") or write_payload.get("promotion_write_history_ready")),
        "promotion_write_source_payload_present": bool(write_payload.get("promotion_write_source_payload_present")),
        "promotion_write_bucket_exists_after_append": bool(write_payload.get("promotion_write_bucket_exists_after_append")),
        "promotion_write_storage_trade_count_after_append": int(write_payload.get("promotion_write_storage_trade_count_after_append") or write_trade_count),
        "promotion_write_storage_history_ready_after_append": bool(write_payload.get("promotion_write_storage_history_ready_after_append") or write_payload.get("stored_history_ready") or write_payload.get("promotion_write_history_ready")),
        "promotion_write_effective_value_state": write_payload.get("promotion_write_effective_value_state"),
        "next_read_canonical_key": next_read_canonical_key,
        "next_read_trade_count": read_trade_count,
        "next_read_history_ready": bool(read_payload.get("next_read_history_ready") if read_payload.get("next_read_history_ready") is not None else read_payload.get("read_history_ready")),
        "same_bucket_match_strict": bool(same_bucket_match_strict),
        "promotion_to_next_read_delay_ms": promotion_to_next_read_delay_ms,
        "per_promotion_classification": classification,
        "write_seen": write_seen,
        "read_seen": read_seen,
        "same_container_name": same_container_name,
        "same_nested_key_path": same_nested_key_path,
        "same_object_identity_if_available": same_object_identity_if_available,
        "write_trade_count": write_trade_count,
        "read_trade_count": read_trade_count,
        "write_gross_hist_len": write_gross_hist_len,
        "read_gross_hist_len": read_gross_hist_len,
        "comparison_result": comparison_result,
        "stage_written": stage_written,
        "stage_emit_attempted": stage_emit_attempted,
        "stage_persisted": stage_persisted,
        "stage_observed": stage_observed,
        "stage_exception": stage_exception,
        "final_per_correlation_verdict": final_per_correlation_verdict,
        "write_payload": write_payload,
        "read_payload": read_payload,
    }
