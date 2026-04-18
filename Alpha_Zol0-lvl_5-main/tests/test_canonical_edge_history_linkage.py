import json
import sqlite3
from pathlib import Path

import core.BotCore as botcore
from scripts.controlled_kpi_run import _probe_real_post_promotion_reevaluation
from scripts.controlled_kpi_run import _variant_env
from scripts.canonical_edge_history_audit import _build_report_from_logs, _transport_finalist_state_from_diag
from scripts.canonical_edge_history_linkage import (
    build_canonical_bucket_collapse_compare,
    build_canonical_bucket_post_materialization,
    build_canonical_bucket_pre_materialization,
    build_canonical_bucket_key,
    _coerce_epoch_seconds,
    _normalize_side,
    _normalize_strategy,
    _resolve_strategy_trace,
    resolve_canonical_strategy,
    build_canonical_close_input_trace,
    build_canonical_gate_read_telemetry,
    build_canonical_promotion_telemetry,
    build_canonical_storage_write_trace,
    classify_explicit_post_promotion_eval_disabled_provenance,
    classify_explicit_post_promotion_invoke_trace,
    classify_canonical_close_input_trace,
    classify_forced_cycle_trace,
    classify_post_promotion_force_cycle_handoff_trace,
    classify_post_promotion_arm_trace,
    classify_post_promotion_read_path_trace,
    compare_canonical_shadow_materialization,
    get_canonical_edge_history,
    get_canonical_unresolved_pool,
    get_canonical_promotion_count,
    next_canonical_trace_seq,
    record_unresolved_row,
    promote_to_canonical_edge_history,
    resolve_simulated_close_quantity,
    reset_canonical_edge_history_state,
)


def _run_meta():
    return {
        "run_id": "unit-test",
        "results_path": "unit-test.json",
        "db_path": "unit-test.db",
        "duration_sec_actual": 0.0,
        "before": {},
    }


def _log_row(row_id, event, payload, ts="2026-03-28T00:00:00+00:00"):
    return {"id": row_id, "timestamp": ts, "event": event, "details": payload}


def _write_runner_probe_logs(db_path, rows):
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, event TEXT, details TEXT)"
        )
        for row in rows:
            cur.execute(
                "INSERT INTO logs (id, timestamp, event, details) VALUES (?, ?, ?, ?)",
                (
                    row["id"],
                    row["timestamp"],
                    row["event"],
                    json.dumps(row["details"]),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def test_canonical_shadow_state_promotes_and_builders_emit_required_fields():
    reset_canonical_edge_history_state()
    before = get_canonical_edge_history("BTCUSDTM", "TrendFollowing", "buy", min_trades=20)
    assert before["canonical_shadow_trade_count"] == 0
    assert before["canonical_shadow_history_ready"] is False

    promo1 = promote_to_canonical_edge_history(
        symbol="BTCUSDTM",
        strategy="TrendFollowing",
        side="buy",
        gross_fill_pnl_model=1.25,
        fee_total=0.25,
        spread_slippage_proxy=0.05,
        ts=1.0,
    )
    promo2 = promote_to_canonical_edge_history(
        symbol="BTCUSDTM",
        strategy="TrendFollowing",
        side="buy",
        gross_fill_pnl_model=1.10,
        fee_total=0.20,
        spread_slippage_proxy=0.03,
        ts=2.0,
    )
    assert promo1["bucket_created_on_this_event"] is True
    assert promo2["bucket_created_on_this_event"] is False

    promotion_telemetry = build_canonical_promotion_telemetry(
        canonical_result=promo2,
        source_event_type="position_close",
        gross_fill_pnl_model=1.10,
        fee_total=0.20,
        spread_slippage_proxy=0.03,
        position_id="trade-1",
        close_ts="2026-03-28T00:00:02+00:00",
        run_ts="2026-03-28T00:00:02+00:00",
        bucket_created_on_this_event=promo2["bucket_created_on_this_event"],
        runtime_seq=next_canonical_trace_seq(),
    )
    for key in (
        "event_id",
        "correlation_id",
        "event_type",
        "schema_version",
        "created_at",
        "event",
        "runtime_seq",
        "symbol",
        "strategy",
        "side",
        "canonical_key",
        "storage_target_name",
        "stored_trade_count",
        "stored_history_ready",
        "stored_bucket_shape",
        "trade_count_after",
        "gross_hist_len",
        "fee_hist_len",
        "slippage_hist_len",
        "last_update_ts",
        "source_event_type",
    ):
        assert key in promotion_telemetry
    assert promotion_telemetry["event"] == "canonical_promotion"
    assert promotion_telemetry["event_type"] == "promotion_write"
    assert str(promotion_telemetry["correlation_id"]).startswith("corr_")
    assert promotion_telemetry["canonical_key"] == "BTCUSDTM|TRENDFOLLOWING|buy"
    assert promotion_telemetry["stored_trade_count"] == 2
    assert promotion_telemetry["stored_history_ready"] is False
    assert promotion_telemetry["storage_target_name"] == "canonical_shadow_storage"

    after = get_canonical_edge_history("BTCUSDTM", "TrendFollowing", "buy", min_trades=2)
    assert after["canonical_shadow_trade_count"] == 2
    assert after["canonical_shadow_history_ready"] is True
    assert after["shadow_bucket"]["trade_count"] == 2

    gate_telemetry = build_canonical_gate_read_telemetry(
        gate_payload={"symbol": "BTCUSDTM", "strategy": "TrendFollowing", "side": "buy"},
        production_source_name="production_snapshot_primary",
        production_trade_count=0,
        production_history_ready=False,
        canonical_shadow_result=after,
        row_ts="2026-03-28T00:00:03+00:00",
        evaluation_index=7,
        runtime_seq=next_canonical_trace_seq(),
        read_context="forced_post_promotion_replay",
        timing_replay_index=1,
        timing_replay_target_reads=3,
        gate_read_source_function="_entry_edge_over_fee_check_forced_timing_replay",
        primary_snapshot={"trade_count": 0, "history_ready": False},
        fallback_snapshot={"trade_count": 2, "history_ready": True},
        bucket_used_final="fallback",
        trade_count_primary=0,
        trade_count_fallback=2,
        selected_snapshot={"trade_count": 2, "history_ready": True},
        bucket_key_primary="BTCUSDTM|TRENDFOLLOWING|buy",
        bucket_key_fallback="BTCUSDTM|__ALL__|buy",
    )
    for key in (
        "event_id",
        "correlation_id",
        "event_type",
        "schema_version",
        "created_at",
        "event",
        "runtime_seq",
        "symbol",
        "strategy",
        "side",
        "canonical_key",
        "read_source_name",
        "read_trade_count",
        "read_history_ready",
        "canonical_shadow_trade_count",
        "canonical_shadow_history_ready",
        "decision_source_name",
        "decision_trade_count",
        "decision_history_ready",
        "canonical_shadow_storage_bucket",
        "read_source_bucket_shape",
        "decision_snapshot_selection",
        "read_context",
        "timing_replay_index",
        "timing_replay_target_reads",
        "gate_read_source_function",
    ):
        assert key in gate_telemetry
    assert gate_telemetry["event"] == "canonical_gate_read"
    assert gate_telemetry["event_type"] == "readback"
    assert gate_telemetry["canonical_key"] == "BTCUSDTM|TRENDFOLLOWING|buy"
    assert gate_telemetry["timing_replay_index"] == 1
    assert gate_telemetry["timing_replay_target_reads"] == 3
    assert gate_telemetry["gate_read_source_function"] == "_entry_edge_over_fee_check_forced_timing_replay"
    assert gate_telemetry["decision_snapshot_selection"]["bucket_used_final"] == "fallback"
    assert gate_telemetry["decision_snapshot_selection"]["selected_trade_count"] == 2
    assert gate_telemetry["decision_snapshot_selection"]["selected_history_ready"] is True
    assert gate_telemetry["read_source_bucket_shape"]["gross_hist_len"] == 2

    materialized = {
        **after,
        "shadow_bucket": after["shadow_bucket"],
    }
    materialized["canonical_shadow_trade_count"] = 2
    materialized["canonical_shadow_history_ready"] = True
    assert materialized["shadow_bucket"]["trade_count"] == 2

    write_trace = build_canonical_storage_write_trace(
        canonical_result=promo2,
        runtime_seq=next_canonical_trace_seq(),
        timestamp="2026-03-28T00:00:02+00:00",
    )
    assert write_trace["stored_trade_count"] == 2
    assert write_trace["gross_hist_len"] == 2

    pre_materialization = build_canonical_bucket_pre_materialization(
        canonical_shadow_result=after,
        runtime_seq=next_canonical_trace_seq(),
        timestamp="2026-03-28T00:00:03+00:00",
    )
    assert pre_materialization["trade_count"] == 2
    assert pre_materialization["gross_hist_len"] == 2

    post_materialization = build_canonical_bucket_post_materialization(
        canonical_key=after["canonical_bucket_key"],
        symbol=after["symbol"],
        strategy=after["strategy_identity"],
        side=after["side"],
        materializer_name="_entry_edge_over_fee_check.snapshot_primary",
        source_container_name=after["read_container_name"],
        nested_key_path=after["nested_key_path"],
        materialized_bucket={},
        storage_bucket_id=after["storage_bucket_id"],
        storage_container_id=after["storage_container_id"],
        runtime_seq=next_canonical_trace_seq(),
        timestamp="2026-03-28T00:00:04+00:00",
    )
    compare = build_canonical_bucket_collapse_compare(
        pre_payload=pre_materialization,
        post_payload=post_materialization,
        runtime_seq=next_canonical_trace_seq(),
        timestamp="2026-03-28T00:00:04+00:00",
    )
    assert compare["collapse_result"] == "FULL_DEFAULT_SHAPE_COLLAPSE"


def test_build_canonical_gate_read_telemetry_tracks_read_path_stage_ladder():
    base_kwargs = dict(
        gate_payload={"symbol": "BTCUSDTM", "strategy": "TrendFollowing", "side": "buy"},
        production_source_name="production_snapshot_primary",
        production_trade_count=0,
        production_history_ready=False,
        canonical_shadow_result={
            "canonical_shadow_trade_count": 0,
            "storage_bucket_id": 1,
            "storage_container_id": 2,
            "last_write_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "last_write_ts": "2026-03-28T00:00:00+00:00",
        },
        row_ts="2026-03-28T00:00:03+00:00",
        evaluation_index=1,
        runtime_seq=next_canonical_trace_seq(),
        read_context="forced_post_promotion_replay",
        timing_replay_index=1,
        timing_replay_target_reads=3,
        gate_read_source_function="_entry_edge_over_fee_check_forced_timing_replay",
        primary_snapshot={"trade_count": 0, "history_ready": False},
        fallback_snapshot={"trade_count": 0, "history_ready": False},
        bucket_used_final="primary",
        trade_count_primary=0,
        trade_count_fallback=0,
        selected_snapshot={"trade_count": 0, "history_ready": False},
        bucket_key_primary="BTCUSDTM|TRENDFOLLOWING|buy",
        bucket_key_fallback="BTCUSDTM|__ALL__|buy",
    )

    assert (
        build_canonical_gate_read_telemetry(**base_kwargs)["post_promotion_read_path_stage"]
        == "not_post_promotion"
    )
    assert (
        build_canonical_gate_read_telemetry(
            **{**base_kwargs, "post_promotion_eval_enter": True}
        )["post_promotion_read_path_stage"]
        == "entered"
    )
    assert (
        build_canonical_gate_read_telemetry(
            **{**base_kwargs, "post_promotion_eval_enter": True, "post_promotion_gate_read_emit_attempt": True}
        )["post_promotion_read_path_stage"]
        == "attempted_not_persisted"
    )
    assert (
        build_canonical_gate_read_telemetry(
            **{**base_kwargs, "post_promotion_eval_enter": True, "post_promotion_gate_read_emit_attempt": True, "post_promotion_gate_read_emit_done": True}
        )["post_promotion_read_path_stage"]
        == "persisted_zero"
    )
    assert (
        build_canonical_gate_read_telemetry(
            **{**base_kwargs, "post_promotion_eval_exit": True}
        )["post_promotion_read_path_stage"]
        == "exited"
    )
    assert (
        build_canonical_gate_read_telemetry(
            **{
                **base_kwargs,
                "canonical_shadow_result": {
                    "canonical_shadow_trade_count": 2,
                    "storage_bucket_id": 1,
                    "storage_container_id": 2,
                    "last_write_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                    "last_write_ts": "2026-03-28T00:00:00+00:00",
                },
            }
        )["post_promotion_read_path_stage"]
        == "persisted_nonzero"
    )
    assert (
        build_canonical_gate_read_telemetry(
            **{
                **base_kwargs,
                "post_promotion_gate_read_emit_done": True,
                "canonical_shadow_result": {
                    "canonical_shadow_trade_count": 0,
                    "storage_bucket_id": 1,
                    "storage_container_id": 2,
                    "last_write_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                    "last_write_ts": "2026-03-28T00:00:00+00:00",
                },
            }
        )["post_promotion_read_path_stage"]
        == "persisted_zero"
    )
    assert (
        build_canonical_gate_read_telemetry(
            **{**base_kwargs, "post_promotion_gate_read_emit_attempt": True}
        )["post_promotion_read_path_stage"]
        == "attempted_not_persisted"
    )
    assert (
        build_canonical_gate_read_telemetry(
            **{**base_kwargs, "post_promotion_eval_skip_reason": "explicit_skip"}
        )["post_promotion_read_path_stage"]
        == "skipped"
    )


def test_unresolved_rows_are_captured():
    reset_canonical_edge_history_state()
    payload = {"symbol": "BTCUSDTM", "side": "buy", "entry_edge_over_fee": {"strategy": "__ALL__"}}
    canonical = build_canonical_bucket_key(payload)
    assert canonical["bucket_identity_status"] == "UNRESOLVED"
    record_unresolved_row(payload, reason=canonical["bucket_identity_reason"], event_name="entry_gate_decision_summary")
    pool = get_canonical_unresolved_pool()
    assert len(pool) == 1
    assert pool[0]["reason"] == "strategy_is___ALL__"


def test_coerce_epoch_seconds_rejects_boolean_input():
    assert _coerce_epoch_seconds(True) is None
    assert _coerce_epoch_seconds(False) is None


def test_normalize_side_maps_valid_and_fallback_values():
    assert _normalize_side("long") == "buy"
    assert _normalize_side("BUY") == "buy"
    assert _normalize_side("short") == "sell"
    assert _normalize_side("sell") == "sell"
    assert _normalize_side("") == "unknown"
    assert _normalize_side(None) == "unknown"
    assert _normalize_side("hold") == "hold"


def test_normalize_strategy_maps_valid_and_sentinel_values():
    assert _normalize_strategy("TrendFollowing") == "TRENDFOLLOWING"
    assert _normalize_strategy("  momentum  ") == "MOMENTUM"
    assert _normalize_strategy("") is None
    assert _normalize_strategy(None) is None
    assert _normalize_strategy("UNKNOWN") is None
    assert _normalize_strategy("ALL") is None
    assert _normalize_strategy("__ALL__") is None


def test_resolve_strategy_trace_handles_malformed_and_missing_sources():
    assert _resolve_strategy_trace(None) == (
        None,
        "UNRESOLVED",
        "malformed_payload",
        None,
        None,
        None,
    )
    assert _resolve_strategy_trace({"entry_edge_over_fee": "bad"}) == (
        None,
        "UNRESOLVED",
        "malformed_payload",
        None,
        None,
        None,
    )
    assert _resolve_strategy_trace({"position": "bad"}) == (
        None,
        "UNRESOLVED",
        "malformed_payload",
        None,
        None,
        None,
    )
    assert _resolve_strategy_trace({"symbol": "BTCUSDTM"}) == (
        None,
        "UNRESOLVED",
        "missing_strategy_field",
        None,
        None,
        None,
    )


def test_resolve_strategy_trace_prefers_entry_edge_strategy_and_handles_sentinels():
    assert _resolve_strategy_trace(
        {
            "entry_edge_over_fee": {"strategy": "__ALL__"},
            "strategy": "TrendFollowing",
        }
    ) == (
        None,
        "UNRESOLVED",
        "strategy_is___ALL__",
        "entry_edge_over_fee.strategy",
        "__ALL__",
        "__ALL__",
    )
    assert _resolve_strategy_trace(
        {
            "entry_edge_over_fee": {"strategy": "momentum"},
            "strategy": "TrendFollowing",
        }
    ) == (
        "MOMENTUM",
        "RESOLVED",
        "explicit_strategy",
        "entry_edge_over_fee.strategy",
        "momentum",
        "MOMENTUM",
    )
    assert _resolve_strategy_trace(
        {
            "strategy": "UNKNOWN",
        }
    ) == (
        None,
        "UNRESOLVED",
        "fallback_unknown",
        "strategy",
        "UNKNOWN",
        "UNKNOWN",
    )


def test_resolve_canonical_strategy_returns_compact_contract():
    assert resolve_canonical_strategy(
        {
            "entry_edge_over_fee": {"strategy": "momentum"},
            "strategy": "TrendFollowing",
        }
    ) == ("MOMENTUM", "RESOLVED", "explicit_strategy")
    assert resolve_canonical_strategy({"symbol": "BTCUSDTM"}) == (
        None,
        "UNRESOLVED",
        "missing_strategy_field",
    )


def test_get_canonical_promotion_count_tracks_incrementing_state():
    reset_canonical_edge_history_state()
    assert get_canonical_promotion_count() == 0
    promote_to_canonical_edge_history(
        symbol="BTCUSDTM",
        strategy="TrendFollowing",
        side="buy",
        gross_fill_pnl_model=1.0,
        fee_total=0.25,
        spread_slippage_proxy=0.05,
        ts=1.0,
    )
    assert get_canonical_promotion_count() == 1
    promote_to_canonical_edge_history(
        symbol="BTCUSDTM",
        strategy="TrendFollowing",
        side="buy",
        gross_fill_pnl_model=1.5,
        fee_total=0.20,
        spread_slippage_proxy=0.03,
        ts=2.0,
    )
    assert get_canonical_promotion_count() == 2


def test_audit_tracks_skipped_promotions():
    rows = [
        _log_row(
            1,
            "canonical_promotion_skipped",
                {
                    "runtime_seq": 1,
                    "run_ts": "2026-03-28T00:00:01+00:00",
                    "correlation_id": "corr-1",
                    "symbol": "BTCUSDTM",
                    "strategy": "TRENDFOLLOWING",
                    "side": "buy",
                "skip_reason": "missing_gross_fill_pnl_model",
            },
        )
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    assert report["aggregate"]["total_promotion_skips"] == 1
    assert report["aggregate"]["promotion_skip_reasons"]["missing_gross_fill_pnl_model"] == 1
    assert report["final_classification"] == "PARTIAL_PROOF_MORE_TRACE_NEEDED"


def test_audit_classifies_emit_guard_blocked_with_reason():
    meta = _run_meta()
    meta["before"] = {
        "post_promotion_reeval_completed": True,
        "post_promotion_reeval_result": "reevaluation_completed",
    }
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 2,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "canonical_explicit_post_promotion_invoke_trace",
            {
                "runtime_seq": 2,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "evaluated_path_enter_after_promotion": True,
                "post_promotion_eval_arm_consumed": True,
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
            },
        ),
        _log_row(
            3,
            "canonical_gate_read_emit_candidate",
            {
                "runtime_seq": 3,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
            },
        ),
        _log_row(
            4,
            "canonical_gate_read_emit_guard_considered",
            {
                "runtime_seq": 4,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
            },
        ),
        _log_row(
            5,
            "canonical_gate_read_emit_guard_blocked",
            {
                "runtime_seq": 5,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
                "skip_reason": "forced_same_bucket_next_eval_false",
                "canonical_gate_read_emit_guard_reason": "forced_same_bucket_next_eval_false",
            },
        ),
    ]
    report = _build_report_from_logs(meta, rows)
    assert report["aggregate"]["post_promotion_emit_verdict_counts"]["EMIT_GUARD_BLOCKED_WITH_REASON"] == 1
    assert report["correlation_diagnostics"]["corr-1"]["post_promotion_emit_verdict"] == "EMIT_GUARD_BLOCKED_WITH_REASON"


def test_audit_classifies_branch_selector_skip_with_reason():
    meta = _run_meta()
    meta["before"] = {
        "post_promotion_reeval_completed": True,
        "post_promotion_reeval_result": "reevaluation_completed",
    }
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 2,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "canonical_explicit_post_promotion_invoke_trace",
            {
                "runtime_seq": 2,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "evaluated_path_enter_after_promotion": True,
                "post_promotion_eval_arm_consumed": True,
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
            },
        ),
        _log_row(
            3,
            "canonical_gate_read_branch_selector_enter",
            {
                "runtime_seq": 3,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "selected_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "decision_source_name": "production_snapshot_primary",
                "entry_decision": "hold",
                "local_gate_reason": "current_side",
                "position_state": "in_position",
                "current_side": "buy",
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
                "skip_reason": "explicit_post_promotion_eval_inactive",
            },
        ),
        _log_row(
            4,
            "canonical_gate_read_branch_selector_inputs",
            {
                "runtime_seq": 4,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "selected_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "decision_source_name": "production_snapshot_primary",
                "entry_decision": "hold",
                "local_gate_reason": "current_side",
                "position_state": "in_position",
                "current_side": "buy",
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
                "skip_reason": "explicit_post_promotion_eval_inactive",
            },
        ),
        _log_row(
            5,
            "canonical_gate_read_branch_selector_selected_path",
            {
                "runtime_seq": 5,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "selected_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "decision_source_name": "production_snapshot_primary",
                "entry_decision": "hold",
                "local_gate_reason": "current_side",
                "position_state": "in_position",
                "current_side": "buy",
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
                "canonical_gate_read_branch_selector_selected_path": "skip",
                "skip_reason": "explicit_post_promotion_eval_inactive",
            },
        ),
        _log_row(
            6,
            "canonical_gate_read_branch_selector_skip",
            {
                "runtime_seq": 6,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "selected_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "decision_source_name": "production_snapshot_primary",
                "entry_decision": "hold",
                "local_gate_reason": "current_side",
                "position_state": "in_position",
                "current_side": "buy",
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
                "canonical_gate_read_branch_selector_selected_path": "skip",
                "canonical_gate_read_branch_selector_skip": True,
                "canonical_gate_read_branch_selector_skip_reason": "explicit_post_promotion_eval_inactive",
                "skip_reason": "explicit_post_promotion_eval_inactive",
            },
        ),
    ]
    report = _build_report_from_logs(meta, rows)
    assert report["aggregate"]["post_promotion_branch_verdict_counts"]["PRE_CANDIDATE_BRANCH_SKIPPED_WITH_REASON"] == 1
    assert report["final_classification"] == "PRE_CANDIDATE_BRANCH_SKIPPED_WITH_REASON"


def test_audit_classifies_forced_cycle_candidate_not_reached():
    meta = _run_meta()
    meta["before"] = {
        "post_promotion_reeval_completed": True,
        "post_promotion_reeval_result": "reevaluation_completed",
        "post_promotion_forced_cycle_requested": True,
        "post_promotion_forced_cycle_completed": True,
        "post_promotion_forced_cycle_result": "FORCED_CYCLE_CALLED_BUT_LOOP_NOT_ENTERED",
    }
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 2,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "post_promotion_force_cycle_handoff_enter",
            {
                "runtime_seq": 2,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_runtime_seq": 1,
                "reeval_runtime_seq": 2,
                "forced_cycle_runtime_seq": 2,
                "evaluation_phase": "direct_post_promotion_handoff",
                "is_explicit_post_promotion_eval": True,
                "is_forced_post_promotion_cycle": False,
            },
        ),
        _log_row(
            3,
            "post_promotion_force_cycle_handoff_accept",
            {
                "runtime_seq": 3,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_runtime_seq": 1,
                "reeval_runtime_seq": 2,
                "forced_cycle_runtime_seq": 2,
                "evaluation_phase": "direct_post_promotion_handoff",
                "is_explicit_post_promotion_eval": True,
                "is_forced_post_promotion_cycle": False,
            },
        ),
        _log_row(
            4,
            "post_promotion_force_cycle_handoff_call_start",
            {
                "runtime_seq": 4,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_runtime_seq": 1,
                "reeval_runtime_seq": 2,
                "forced_cycle_runtime_seq": 2,
                "evaluation_phase": "direct_post_promotion_handoff",
                "is_explicit_post_promotion_eval": True,
                "is_forced_post_promotion_cycle": False,
            },
        ),
        _log_row(
            5,
            "forced_cycle_started",
            {
                "runtime_seq": 5,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_runtime_seq": 1,
                "reeval_runtime_seq": 2,
                "forced_cycle_runtime_seq": 2,
                "evaluation_phase": "direct_post_promotion_handoff",
                "is_forced_post_promotion_cycle": True,
            },
        ),
        _log_row(
            6,
            "canonical_explicit_post_promotion_invoke_trace",
            {
                "runtime_seq": 6,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "evaluated_path_enter_after_forced_cycle": False,
                "evaluated_path_enter_after_promotion": True,
                "post_promotion_eval_arm_consumed": True,
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "post_promotion_force_cycle_handoff_call_start": True,
                "post_promotion_force_cycle_handoff_call_done": True,
            },
        ),
    ]
    report = _build_report_from_logs(meta, rows)
    assert report["final_classification"] == "FORCED_CYCLE_CALLED_BUT_LOOP_NOT_ENTERED"


def test_audit_classifies_forced_cycle_drain_entered():
    meta = _run_meta()
    meta["before"] = {
        "post_promotion_reeval_completed": True,
        "post_promotion_reeval_result": "reevaluation_completed",
        "post_promotion_forced_cycle_requested": True,
        "post_promotion_forced_cycle_completed": True,
        "post_promotion_forced_cycle_result": "FORCED_CYCLE_DRAIN_ENTERED",
    }
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 2,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "post_promotion_force_cycle_drain_enter",
            {
                "runtime_seq": 2,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "transfer_site_id": "child_drain_loop",
                "mailbox_stage": "drain_enter",
                "handoff_transport_state": "drain_enter",
            },
        ),
    ]
    report = _build_report_from_logs(meta, rows)
    assert report["final_classification"] == "FORCED_CYCLE_DRAIN_ENTERED"


def test_audit_classifies_forced_cycle_pending_not_visible():
    meta = _run_meta()
    meta["before"] = {
        "post_promotion_reeval_completed": True,
        "post_promotion_reeval_result": "reevaluation_completed",
        "post_promotion_forced_cycle_requested": True,
        "post_promotion_forced_cycle_completed": True,
        "post_promotion_forced_cycle_result": "FORCED_CYCLE_PENDING_NOT_VISIBLE",
    }
    rows = [
        _log_row(
            1,
            "post_promotion_force_cycle_pending_check_enter",
            {
                "runtime_seq": 1,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_id": 1,
                "transfer_site_id": "child_drain_loop",
                "mailbox_stage": "pending_check_enter",
                "handoff_transport_state": "pending_check_enter",
            },
        ),
        _log_row(
            2,
            "post_promotion_force_cycle_pending_not_visible",
            {
                "runtime_seq": 2,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_id": 1,
                "visibility_reason": "pending_request_not_visible",
                "skip_reason": "pending_request_not_visible",
                "transfer_site_id": "child_drain_loop",
                "mailbox_stage": "pending_check_not_visible",
                "handoff_transport_state": "pending_request_not_visible",
            },
        ),
    ]
    report = _build_report_from_logs(meta, rows)
    assert report["final_classification"] == "FORCED_CYCLE_PENDING_NOT_VISIBLE"


def test_audit_classifies_forced_cycle_request_scan_empty():
    meta = _run_meta()
    meta["before"] = {
        "post_promotion_reeval_completed": True,
        "post_promotion_reeval_result": "reevaluation_completed",
        "post_promotion_forced_cycle_requested": True,
        "post_promotion_forced_cycle_completed": True,
        "post_promotion_forced_cycle_result": "FORCED_CYCLE_REQUEST_SCAN_EMPTY",
    }
    rows = [
        _log_row(
            1,
            "post_promotion_force_cycle_scheduler_tick_enter",
            {
                "runtime_seq": 1,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_count_seen": 0,
                "tick_reason": "forced_cycle_request_scan",
            },
        ),
        _log_row(
            2,
            "post_promotion_force_cycle_request_scan_candidate_seen",
            {
                "runtime_seq": 2,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_id": 715,
                "promotion_runtime_seq": 2,
                "request_count_seen": 0,
                "scan_reason": "request_rows_absent",
                "empty_reason": "request_consumed_or_already_seen_before_scan",
            },
        ),
        _log_row(
            3,
            "post_promotion_force_cycle_request_scan_candidate_reject",
            {
                "runtime_seq": 3,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_id": 715,
                "promotion_runtime_seq": 2,
                "request_count_seen": 0,
                "scan_reason": "request_rows_absent",
                "candidate_reject_reason": "request_consumed_or_already_seen_before_scan",
            },
        ),
        _log_row(
            4,
            "post_promotion_force_cycle_request_scan_empty_reason",
            {
                "runtime_seq": 4,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_count_seen": 0,
                "scan_reason": "request_rows_absent",
                "empty_reason": "request_consumed_or_already_seen_before_scan",
            },
        ),
        _log_row(
            5,
            "post_promotion_force_cycle_request_scan_empty",
            {
                "runtime_seq": 5,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_count_seen": 0,
                "scan_reason": "request_rows_absent",
                "tick_reason": "forced_cycle_request_scan",
                "forced_cycle_request_scan_empty_reason": "request_consumed_or_already_seen_before_scan",
            },
        ),
    ]
    report = _build_report_from_logs(meta, rows)
    assert report["final_classification"] == "FORCED_CYCLE_REQUEST_SCAN_EMPTY"
    assert report["correlation_diagnostics"]["corr-1"]["forced_cycle_request_scan_candidate_seen"] is True
    assert report["correlation_diagnostics"]["corr-1"]["forced_cycle_request_scan_candidate_reject"] is True
    assert (
        report["correlation_diagnostics"]["corr-1"]["forced_cycle_request_scan_candidate_reject_reason"]
        == "request_consumed_or_already_seen_before_scan"
    )
    assert (
        report["correlation_diagnostics"]["corr-1"]["forced_cycle_request_scan_empty_reason"]
        == "request_consumed_or_already_seen_before_scan"
    )


def test_audit_classifies_pre_drain_transition_fixed():
    meta = _run_meta()
    meta["before"] = {
        "post_promotion_reeval_completed": True,
        "post_promotion_reeval_result": "reevaluation_completed",
        "post_promotion_forced_cycle_requested": True,
        "post_promotion_forced_cycle_completed": True,
        "post_promotion_forced_cycle_result": "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED",
    }
    rows = [
        _log_row(
            1,
            "post_promotion_force_cycle_request_scan_nonempty",
            {
                "runtime_seq": 1,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_id": 715,
                "promotion_runtime_seq": 2,
                "request_count_seen": 1,
                "scan_reason": "request_rows_present",
                "tick_reason": "forced_cycle_request_scan",
            },
        ),
        _log_row(
            2,
            "post_promotion_force_cycle_pre_drain_candidate",
            {
                "runtime_seq": 2,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_id": 715,
                "promotion_runtime_seq": 2,
                "request_count_seen": 1,
                "gate_reason": "pending_request_visible",
                "visibility_reason": "pending_request_visible",
            },
        ),
        _log_row(
            3,
            "post_promotion_force_cycle_pre_drain_enter",
            {
                "runtime_seq": 3,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_id": 715,
                "promotion_runtime_seq": 2,
                "request_count_seen": 1,
                "gate_reason": "pending_request_visible",
                "visibility_reason": "pending_request_visible",
            },
        ),
        _log_row(
            4,
            "post_promotion_force_cycle_pre_drain_return",
            {
                "runtime_seq": 4,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_id": 715,
                "promotion_runtime_seq": 2,
                "request_count_seen": 1,
                "pre_drain_return_reason": "drain_entered",
                "gate_reason": "pending_request_visible",
                "visibility_reason": "pending_request_visible",
            },
        ),
        _log_row(
            5,
            "post_promotion_force_cycle_drain_enter",
            {
                "runtime_seq": 5,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "request_id": 715,
                "promotion_runtime_seq": 2,
                "request_count_seen": 1,
                "gate_reason": "pending_request_visible",
                "visibility_reason": "pending_request_visible",
            },
        ),
    ]
    report = _build_report_from_logs(meta, rows)
    assert report["final_classification"] == "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
    diag = report["correlation_diagnostics"]["corr-1"]
    assert diag["forced_cycle_pre_drain_candidate"] is True
    assert diag["forced_cycle_pre_drain_enter"] is True
    assert diag["forced_cycle_pre_drain_return"] is True


def test_audit_classifies_forced_cycle_reached_candidate_but_emit_blocked():
    meta = _run_meta()
    meta["before"] = {
        "post_promotion_reeval_completed": True,
        "post_promotion_reeval_result": "reevaluation_completed",
        "post_promotion_forced_cycle_requested": True,
        "post_promotion_forced_cycle_completed": True,
        "post_promotion_forced_cycle_result": "FORCED_CYCLE_CALLED_BUT_LOOP_NOT_ENTERED",
    }
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 2,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "post_promotion_force_cycle_handoff_enter",
            {
                "runtime_seq": 2,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_runtime_seq": 1,
                "reeval_runtime_seq": 2,
                "forced_cycle_runtime_seq": 2,
                "evaluation_phase": "direct_post_promotion_handoff",
                "is_explicit_post_promotion_eval": True,
                "is_forced_post_promotion_cycle": False,
            },
        ),
        _log_row(
            3,
            "post_promotion_force_cycle_handoff_accept",
            {
                "runtime_seq": 3,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_runtime_seq": 1,
                "reeval_runtime_seq": 2,
                "forced_cycle_runtime_seq": 2,
                "evaluation_phase": "direct_post_promotion_handoff",
                "is_explicit_post_promotion_eval": True,
                "is_forced_post_promotion_cycle": False,
            },
        ),
        _log_row(
            4,
            "post_promotion_force_cycle_handoff_call_start",
            {
                "runtime_seq": 4,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_runtime_seq": 1,
                "reeval_runtime_seq": 2,
                "forced_cycle_runtime_seq": 2,
                "evaluation_phase": "direct_post_promotion_handoff",
                "is_explicit_post_promotion_eval": True,
                "is_forced_post_promotion_cycle": False,
            },
        ),
        _log_row(
            5,
            "forced_cycle_started",
            {
                "runtime_seq": 5,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_runtime_seq": 1,
                "reeval_runtime_seq": 2,
                "forced_cycle_runtime_seq": 2,
                "evaluation_phase": "direct_post_promotion_handoff",
                "is_forced_post_promotion_cycle": True,
            },
        ),
        _log_row(
            6,
            "canonical_explicit_post_promotion_invoke_trace",
            {
                "runtime_seq": 6,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "evaluated_path_enter_after_forced_cycle": True,
                "evaluated_path_enter_after_promotion": True,
                "post_promotion_eval_arm_consumed": True,
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "post_promotion_force_cycle_handoff_call_start": True,
                "post_promotion_force_cycle_handoff_call_done": True,
            },
        ),
        _log_row(
            7,
            "canonical_gate_read_branch_selector_enter",
            {
                "runtime_seq": 7,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "selected_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "decision_source_name": "production_snapshot_primary",
                "entry_decision": "hold",
                "local_gate_reason": "current_side",
                "position_state": "in_position",
                "current_side": "buy",
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
                "skip_reason": None,
            },
        ),
        _log_row(
            8,
            "canonical_gate_read_emit_candidate",
            {
                "runtime_seq": 8,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
                "skip_reason": None,
                "canonical_gate_read_emit_candidate": True,
            },
        ),
        _log_row(
            9,
            "canonical_gate_read_emit_guard_considered",
            {
                "runtime_seq": 9,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
                "skip_reason": None,
                "canonical_gate_read_emit_guard_considered": True,
                "canonical_gate_read_emit_guard_blocked": False,
            },
        ),
        _log_row(
            10,
            "canonical_gate_read_emit_payload_built",
            {
                "runtime_seq": 10,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "evaluation_phase": "post_promotion_materialization",
                "is_explicit_post_promotion_eval": True,
                "skip_reason": None,
                "canonical_gate_read_emit_payload_built": True,
                "canonical_gate_read_emit_attempt": False,
                "canonical_gate_read_emit_done": False,
            },
        ),
    ]
    report = _build_report_from_logs(meta, rows)
    assert report["final_classification"] == "FORCED_CYCLE_CALLED_BUT_LOOP_NOT_ENTERED"


def test_classify_forced_cycle_trace_covers_direct_stage_ladder():
    assert classify_forced_cycle_trace({}) == "FORCE_CYCLE_HANDOFF_NOT_REACHED"
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
            }
        )
        == "FORCE_CYCLE_HANDOFF_ACCEPTED_BUT_NOT_STARTED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_tick_enter": True,
                "forced_cycle_request_scan_empty": True,
            }
        )
        == "FORCED_CYCLE_REQUEST_SCAN_EMPTY"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_requested": True,
            }
        )
        == "FORCED_CYCLE_SCHEDULER_TICK_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_caller_enter": True,
                "forced_cycle_scheduler_caller_exit": True,
            }
        )
        == "FORCED_CYCLE_SCHEDULER_CALLER_RETURNED_WITHOUT_TICK"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_tick_enter": True,
                "forced_cycle_request_scan_enter": True,
                "forced_cycle_request_scan_result": False,
                "forced_cycle_request_scan_empty": False,
                "forced_cycle_request_scan_nonempty": False,
            }
        )
        == "FORCED_CYCLE_REQUEST_SCAN_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_tick_enter": True,
                "forced_cycle_request_scan_enter": True,
                "forced_cycle_request_scan_nonempty": True,
                "post_promotion_force_cycle_drain_enter": False,
            }
        )
        == "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY_BUT_PRE_DRAIN_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_tick_enter": True,
                "forced_cycle_request_scan_enter": True,
                "forced_cycle_request_scan_nonempty": True,
                "forced_cycle_pre_drain_candidate": True,
                "forced_cycle_pre_drain_enter": True,
                "post_promotion_force_cycle_drain_enter": True,
            }
        )
        == "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
            }
        )
        == "FORCED_CYCLE_CALLED_BUT_LOOP_NOT_ENTERED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_decision": "HANDOFF_REJECTED_BY_LOCK",
            }
        )
        == "HANDOFF_REJECTED_BY_LOCK"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_decision": "HANDOFF_REJECTED_BY_DEDUPE",
            }
        )
        == "HANDOFF_REJECTED_BY_DEDUPE"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_decision": "HANDOFF_REACHED_BUT_REQUEST_NOT_ENQUEUED",
            }
        )
        == "HANDOFF_REACHED_BUT_REQUEST_NOT_ENQUEUED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_decision": "HANDOFF_ACCEPTED_AND_REQUESTED",
            }
        )
        == "HANDOFF_ACCEPTED_AND_REQUESTED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_parent_enqueue_enter": True,
            }
        )
        == "HANDOFF_PARENT_ENQUEUE_ENTERED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_parent_enqueue_done": True,
            }
        )
        == "HANDOFF_PARENT_ENQUEUE_COMPLETED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_parent_enqueue_done": True,
                "handoff_child_mailbox_observed": True,
            }
        )
        == "HANDOFF_CHILD_MAILBOX_OBSERVED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_parent_signal_sent": True,
            }
        )
        == "HANDOFF_PARENT_SIGNAL_SENT"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_child_mailbox_observed": True,
            }
        )
        == "HANDOFF_CHILD_MAILBOX_OBSERVED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_child_mailbox_dequeue_enter": True,
            }
        )
        == "HANDOFF_CHILD_MAILBOX_DEQUEUED"
    )


def test_audit_exposes_transport_verdict_eligibility_and_blocker():
    deepest, reason, blocker = _transport_finalist_state_from_diag(
        {
            "handoff_parent_enqueue_enter": True,
            "handoff_parent_enqueue_done": True,
            "handoff_parent_signal_sent": True,
        }
    )
    assert deepest == "HANDOFF_PARENT_SIGNAL_SENT"
    assert reason == "eligible_for_bucket_local_finalist"
    assert blocker is None
    deepest, reason, blocker = _transport_finalist_state_from_diag(
        {
            "handoff_parent_enqueue_enter": True,
        }
    )
    assert deepest == "HANDOFF_PARENT_ENQUEUE_ENTERED"
    assert reason == "transport_seen_but_not_bucket_local_finalist"
    assert blocker == "missing_downstream_reachability_state"
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_child_dispatch_enter": True,
            }
        )
        == "HANDOFF_CHILD_DISPATCH_ENTERED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_child_dispatch_enter": True,
                "handoff_child_dispatch_accept_for_processing": True,
            }
        )
        == "HANDOFF_CHILD_ACCEPTED_FOR_PROCESSING"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_child_dispatch_enter": True,
                "handoff_child_dispatch_accept_for_processing": True,
                "handoff_child_loop_enter": True,
            }
        )
        == "HANDOFF_CHILD_LOOP_ENTERED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_child_dispatch_enter": True,
                "handoff_child_dispatch_accept_for_processing": True,
                "handoff_child_loop_enter": True,
                "handoff_child_callback_enter": True,
            }
        )
        == "HANDOFF_CHILD_CALLBACK_ENTERED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_decision_emit_prelude_enter": True,
            }
        )
        == "HANDOFF_DECISION_PAYLOAD_BUILT_BUT_EMIT_NOT_COMPLETED"
    )


def test_audit_threads_child_force_cycle_rows_into_bucket_local_trace_stream():
    meta = _run_meta()
    meta["before"] = {
        "post_promotion_reeval_completed": True,
        "post_promotion_reeval_result": "reevaluation_completed",
    }
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "AUTO_TEST",
                "side": "buy",
                "canonical_key": "BTCUSDTM|AUTO_TEST|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "post_promotion_force_cycle_request",
            {
                "runtime_seq": 2,
                "correlation_id": "corr-1",
                "symbol": "BTCUSDTM",
                "strategy": "AUTO_TEST",
                "side": "buy",
                "canonical_key": "BTCUSDTM|AUTO_TEST|buy",
                "promotion_runtime_seq": 1,
            },
        ),
        _log_row(
            3,
            "post_promotion_force_cycle_scheduler_gate_enter",
            {
                "runtime_seq": 0,
                "last_post_promotion_force_cycle_request_id": 2,
                "gate_reason": "forced_cycle_scheduler_gate",
                "observation_window_state": "active",
                "post_promotion_execution_lock": False,
                "has_pending_forced_cycle_request": True,
                "scheduler_tick_eligible": True,
                "transfer_site_id": "child_drain_loop",
                "mailbox_stage": "scheduler_gate_enter",
                "handoff_transport_state": "scheduler_gate_enter",
            },
        ),
        _log_row(
            4,
            "post_promotion_force_cycle_pending_check_enter",
            {
                "runtime_seq": 0,
                "last_post_promotion_force_cycle_request_id": 2,
                "visibility_reason": None,
                "skip_reason": None,
                "transfer_site_id": "child_drain_loop",
                "mailbox_stage": "pending_check_enter",
                "handoff_transport_state": "pending_check_enter",
            },
        ),
        _log_row(
            5,
            "post_promotion_force_cycle_request_scan_enter",
            {
                "runtime_seq": 0,
                "last_post_promotion_force_cycle_request_id": 2,
                "request_count_seen": 1,
                "scan_reason": "request_rows_present",
                "tick_reason": "forced_cycle_request_scan",
                "transfer_site_id": "child_drain_loop",
                "mailbox_stage": "request_scan_enter",
                "handoff_transport_state": "request_scan_enter",
            },
        ),
        _log_row(
            6,
            "post_promotion_force_cycle_request_scan_nonempty",
            {
                "runtime_seq": 0,
                "last_post_promotion_force_cycle_request_id": 2,
                "request_count_seen": 1,
                "scan_reason": "request_rows_present",
                "tick_reason": "forced_cycle_request_scan",
                "transfer_site_id": "child_drain_loop",
                "mailbox_stage": "request_scan_nonempty",
                "handoff_transport_state": "request_scan_nonempty",
            },
        ),
        _log_row(
            7,
            "post_promotion_force_cycle_pending_check_result",
            {
                "runtime_seq": 0,
                "last_post_promotion_force_cycle_request_id": 2,
                "visibility_reason": "pending_request_visible",
                "skip_reason": None,
                "transfer_site_id": "child_drain_loop",
                "mailbox_stage": "pending_check_result",
                "handoff_transport_state": "pending_request_visible",
            },
        ),
        _log_row(
            8,
            "post_promotion_force_cycle_pending_visible",
            {
                "runtime_seq": 0,
                "last_post_promotion_force_cycle_request_id": 2,
                "visibility_reason": "pending_request_visible",
                "skip_reason": None,
                "transfer_site_id": "child_drain_loop",
                "mailbox_stage": "pending_check_visible",
                "handoff_transport_state": "pending_request_visible",
            },
        ),
            _log_row(
                9,
                "post_promotion_force_cycle_pre_drain_enter",
                {
                    "runtime_seq": 0,
                    "last_post_promotion_force_cycle_request_id": 2,
                    "canonical_key": "BTCUSDTM|AUTO_TEST|buy",
                    "correlation_id": "corr-1",
                    "symbol": "BTCUSDTM",
                    "strategy": "AUTO_TEST",
                    "side": "buy",
                    "request_id": 2,
                    "request_count_seen": 1,
                    "gate_reason": "pending_request_visible",
                    "observation_window_state": "active",
                    "post_promotion_execution_lock": False,
                    "has_pending_forced_cycle_request": True,
                    "scheduler_tick_eligible": True,
                    "promotion_runtime_seq": 1,
                    "visibility_reason": "pending_request_visible",
                    "pre_drain_skip_reason": None,
                    "transfer_site_id": "child_drain_loop",
                    "mailbox_stage": "pre_drain_enter",
                    "handoff_transport_state": "pre_drain_enter",
            },
        ),
    ]
    report = _build_report_from_logs(meta, rows)
    bucket = report["per_bucket"]["BTCUSDTM|AUTO_TEST|buy"]
    trace_names = [trace["trace_event_name"] for trace in bucket["forced_cycle_traces"]]
    assert "post_promotion_force_cycle_request" in trace_names
    assert "post_promotion_force_cycle_scheduler_gate_enter" in trace_names
    assert "post_promotion_force_cycle_pending_check_enter" in trace_names
    assert "post_promotion_force_cycle_request_scan_enter" in trace_names
    assert "post_promotion_force_cycle_request_scan_nonempty" in trace_names
    assert "post_promotion_force_cycle_pending_visible" in trace_names
    assert "post_promotion_force_cycle_pre_drain_enter" in trace_names
    assert report["final_classification"] == "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
    assert bucket["forced_cycle_pre_drain_seen"] is True
    assert bucket["winning_verdict"] == "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
    assert bucket["winning_verdict_reason"] == "forced_cycle_pre_drain_priority"
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": False,
            }
        )
        == "FORCED_CYCLE_LOOP_ENTERED_BUT_EVALUATED_PATH_NOT_INVOKED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
            }
        )
        == "FORCED_CYCLE_EVALUATED_PATH_INVOKED_BUT_SELECTOR_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_site_id": "pre_selector_guard_return",
            }
        )
        == "FORCED_CYCLE_PRE_SELECTOR_GUARD_RETURN"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_site_id": "missing_selector_context",
            }
        )
        == "FORCED_CYCLE_MISSING_SELECTOR_CONTEXT"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_site_id": "position_state_short_circuit",
            }
        )
        == "FORCED_CYCLE_POSITION_STATE_SHORT_CIRCUIT"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_site_id": "router_postprocess_return",
            }
        )
        == "FORCED_CYCLE_ROUTER_POSTPROCESS_RETURN"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_site_id": "unknown_pre_selector_return",
            }
        )
        == "FORCED_CYCLE_UNKNOWN_PRE_SELECTOR_RETURN"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_helper_result_type": "NoneType",
            }
        )
        == "HELPER_RETURNED_NONE"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_reason": "non_dict_helper_result",
            }
        )
        == "FORCED_CYCLE_UNKNOWN_PRE_SELECTOR_RETURN"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_site_id": "non_emit_success_path",
            }
        )
        == "FORCED_CYCLE_NON_EMIT_SUCCESS_PATH"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "evaluated_path_enter_after_forced_cycle": True,
                "canonical_gate_read_branch_selector_enter": True,
                "canonical_gate_read_emit_candidate": True,
                "canonical_gate_read_emit_guard_considered": True,
                "canonical_gate_read_emit_guard_blocked": True,
                "canonical_gate_read_emit_attempt": False,
                "canonical_gate_read_emit_done": False,
            }
        )
        == "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_BLOCKED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "evaluated_path_enter_after_forced_cycle": True,
                "canonical_gate_read_branch_selector_enter": True,
                "canonical_gate_read_emit_candidate": True,
                "canonical_gate_read_emit_guard_considered": True,
                "canonical_gate_read_emit_attempt": True,
                "canonical_gate_read_emit_done": True,
            }
        )
        == "FULL_POST_PROMOTION_PIPELINE_CONFIRMED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_site_id": "helper_returned_none",
                "forced_cycle_eval_pre_selector_return_reason": "HELPER_RETURNED_NONE",
                "forced_cycle_eval_pre_selector_helper_result_type": "NoneType",
                "forced_cycle_eval_pre_selector_actual_return_is_none": True,
                "forced_cycle_eval_pre_selector_contract_failure_reason": "HELPER_RETURNED_NONE",
            }
        )
        == "HELPER_RETURNED_NONE"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_site_id": "helper_returned_non_dict_result",
                "forced_cycle_eval_pre_selector_return_reason": "HELPER_RETURNED_NON_DICT_RESULT",
                "forced_cycle_eval_pre_selector_helper_result_type": "tuple",
                "forced_cycle_eval_pre_selector_actual_return_type": "tuple",
                "forced_cycle_eval_pre_selector_actual_return_is_none": False,
                "forced_cycle_eval_pre_selector_contract_failure_reason": "HELPER_RETURNED_NON_DICT_RESULT",
            }
        )
        == "HELPER_RETURNED_NON_DICT_RESULT"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_site_id": "helper_returned_dict_missing_required_fields",
                "forced_cycle_eval_pre_selector_return_reason": "HELPER_RETURNED_DICT_MISSING_REQUIRED_FIELDS",
                "forced_cycle_eval_pre_selector_helper_result_type": "dict",
                "forced_cycle_eval_pre_selector_actual_return_type": "dict",
                "forced_cycle_eval_pre_selector_actual_return_is_none": False,
                "forced_cycle_eval_pre_selector_contract_failure_reason": "HELPER_RETURNED_DICT_MISSING_REQUIRED_FIELDS",
            }
        )
        == "HELPER_RETURNED_DICT_MISSING_REQUIRED_FIELDS"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_site_id": "wrapper_expectation_mismatch",
                "forced_cycle_eval_pre_selector_return_reason": "WRAPPER_EXPECTATION_MISMATCH",
                "forced_cycle_eval_pre_selector_helper_result_type": "dict",
                "forced_cycle_eval_pre_selector_actual_return_type": "dict",
                "forced_cycle_eval_pre_selector_actual_return_is_none": False,
                "forced_cycle_eval_pre_selector_contract_failure_reason": "WRAPPER_EXPECTATION_MISMATCH",
            }
        )
        == "WRAPPER_EXPECTATION_MISMATCH"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "forced_cycle_eval_pre_selector_return_site_id": "selector_context_not_built",
                "forced_cycle_eval_pre_selector_return_reason": "VALID_HELPER_RESULT_BUT_SELECTOR_CONTEXT_NOT_BUILT",
                "forced_cycle_eval_pre_selector_helper_result_type": "dict",
                "forced_cycle_eval_pre_selector_actual_return_type": "dict",
                "forced_cycle_eval_pre_selector_actual_return_is_none": False,
                "forced_cycle_eval_pre_selector_contract_failure_reason": "VALID_HELPER_RESULT_BUT_SELECTOR_CONTEXT_NOT_BUILT",
            }
        )
        == "VALID_HELPER_RESULT_BUT_SELECTOR_CONTEXT_NOT_BUILT"
    )


def test_classify_forced_cycle_trace_covers_remaining_branch_contracts():
    assert (
        classify_forced_cycle_trace({"forced_cycle_scheduler_tick_enter": True})
        == "FORCED_CYCLE_SCHEDULER_TICK_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_tick_enter": True,
                "forced_cycle_request_scan_enter": True,
                "forced_cycle_request_scan_result": False,
                "forced_cycle_request_scan_empty": False,
                "forced_cycle_request_scan_nonempty": False,
            }
        )
        == "FORCED_CYCLE_REQUEST_SCAN_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_tick_enter": True,
                "forced_cycle_request_scan_result": True,
            }
        )
        == "FORCED_CYCLE_REQUEST_SCAN_RESULT_REACHED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_tick_enter": True,
                "forced_cycle_request_scan_nonempty": True,
                "forced_cycle_pre_drain_enter": True,
            }
        )
        == "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_tick_enter": True,
                "forced_cycle_request_scan_nonempty": True,
                "forced_cycle_pre_drain_candidate": True,
            }
        )
        == "PRE_DRAIN_TRANSITION_BLOCKER_PROVEN_BUT_NOT_FIXED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_tick_enter": True,
                "forced_cycle_request_scan_nonempty": True,
                "post_promotion_force_cycle_drain_enter": True,
            }
        )
        == "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_request_scan_enter": True,
                "forced_cycle_request_scan_nonempty": True,
                "forced_cycle_pre_drain_enter": True,
                "post_promotion_force_cycle_drain_enter": True,
            }
        )
        == "PRE_DRAIN_TRANSITION_BLOCKER_FIXED_BUT_NEXT_BLOCKER_EXPOSED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_request_scan_enter": True,
                "forced_cycle_request_scan_nonempty": True,
                "forced_cycle_pre_drain_candidate": True,
                "post_promotion_force_cycle_drain_enter": True,
            }
        )
        == "PRE_DRAIN_TRANSITION_BLOCKER_PROVEN_BUT_NOT_FIXED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_request_scan_enter": True,
                "forced_cycle_request_scan_nonempty": True,
            }
        )
        == "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY_BUT_PRE_DRAIN_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_request_scan_enter": True,
                "forced_cycle_request_scan_empty": True,
            }
        )
        == "FORCED_CYCLE_REQUEST_SCAN_EMPTY"
    )
    assert (
        classify_forced_cycle_trace({"forced_cycle_request_scan_empty": True})
        == "FORCED_CYCLE_REQUEST_SCAN_EMPTY"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_request_scan_enter": True,
                "forced_cycle_request_scan_result": False,
                "forced_cycle_request_scan_empty": False,
                "forced_cycle_request_scan_nonempty": False,
            }
        )
        == "FORCED_CYCLE_REQUEST_SCAN_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace({"forced_cycle_request_scan_result": True})
        == "FORCED_CYCLE_REQUEST_SCAN_RESULT_REACHED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_request_scan_enter": True,
                "forced_cycle_request_scan_nonempty": True,
            }
        )
        == "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY_BUT_PRE_DRAIN_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_request_scan_enter": True,
                "forced_cycle_request_scan_nonempty": True,
                "post_promotion_force_cycle_drain_enter": True,
            }
        )
        == "FORCED_CYCLE_REQUEST_SCAN_NONEMPTY"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_caller_enter": True,
                "forced_cycle_scheduler_caller_exit": True,
            }
        )
        == "FORCED_CYCLE_SCHEDULER_CALLER_RETURNED_WITHOUT_TICK"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_caller_enter": True,
            }
        )
        == "FORCED_CYCLE_SCHEDULER_CALLER_ENTERED_BUT_TICK_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "forced_cycle_scheduler_caller_exit": True,
            }
        )
        == "FORCED_CYCLE_SCHEDULER_CALLER_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace({"forced_cycle_scheduler_gate_blocked": True})
        == "FORCED_CYCLE_SCHEDULER_GATE_BLOCKED"
    )
    assert (
        classify_forced_cycle_trace({"forced_cycle_scheduler_gate_allowed": True})
        == "FORCED_CYCLE_SCHEDULER_GATE_ALLOWED_BUT_TICK_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace({"forced_cycle_pending_visible": True})
        == "FORCED_CYCLE_PENDING_VISIBLE"
    )
    assert (
        classify_forced_cycle_trace({"forced_cycle_pending_not_visible": True})
        == "FORCED_CYCLE_PENDING_NOT_VISIBLE"
    )
    assert (
        classify_forced_cycle_trace({"forced_cycle_drain_skipped": True})
        == "FORCED_CYCLE_DRAIN_SKIPPED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_reject_reason": "lock_rejected",
            }
        )
        == "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": False,
            }
        )
        == "FORCED_CYCLE_EVALUATED_PATH_INVOKED_BUT_SELECTOR_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "evaluated_path_enter_after_forced_cycle": True,
                "canonical_gate_read_branch_selector_enter": False,
            }
        )
        == "FORCED_CYCLE_EVALUATED_PATH_INVOKED_BUT_SELECTOR_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "evaluated_path_enter_after_forced_cycle": True,
                "canonical_gate_read_branch_selector_enter": True,
                "canonical_gate_read_emit_candidate": False,
            }
        )
        == "FORCED_CYCLE_REACHED_SELECTOR_BUT_CANDIDATE_NOT_CREATED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "evaluated_path_enter_after_forced_cycle": True,
                "canonical_gate_read_branch_selector_enter": True,
                "canonical_gate_read_emit_candidate": True,
                "canonical_gate_read_emit_guard_considered": False,
            }
        )
        == "FORCED_CYCLE_REACHED_CANDIDATE_BUT_GUARD_NOT_ENTERED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "evaluated_path_enter_after_forced_cycle": True,
                "canonical_gate_read_branch_selector_enter": True,
                "canonical_gate_read_emit_candidate": True,
                "canonical_gate_read_emit_guard_considered": True,
                "canonical_gate_read_emit_attempt": False,
            }
        )
        == "FORCED_CYCLE_REACHED_CANDIDATE_BUT_EMIT_NOT_ATTEMPTED"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "evaluated_path_enter_after_forced_cycle": True,
                "canonical_gate_read_branch_selector_enter": True,
                "canonical_gate_read_emit_candidate": True,
                "canonical_gate_read_emit_guard_considered": True,
                "canonical_gate_read_emit_attempt": True,
                "canonical_gate_read_emit_done": False,
            }
        )
        == "FORCED_CYCLE_REACHED_EMIT_ATTEMPT_BUT_NOT_DONE"
    )
    assert (
        classify_forced_cycle_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_accept": True,
                "forced_cycle_started": True,
                "forced_cycle_eval_entry": True,
                "forced_cycle_eval_pre_router": True,
                "forced_cycle_eval_pre_entry_edge_check": True,
                "forced_cycle_eval_post_router": True,
                "evaluated_path_enter_after_forced_cycle": True,
                "canonical_gate_read_branch_selector_enter": True,
                "canonical_gate_read_emit_candidate": True,
                "canonical_gate_read_emit_guard_considered": True,
                "canonical_gate_read_emit_attempt": True,
                "canonical_gate_read_emit_done": True,
            }
        )
        == "FULL_POST_PROMOTION_PIPELINE_CONFIRMED"
    )


def test_classify_post_promotion_force_cycle_handoff_trace_covers_reject_reason_fallbacks():
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_decision_emit_call_done": True,
                "post_promotion_force_cycle_handoff_decision": "HANDOFF_ACCEPTED_AND_REQUESTED",
            }
        )
        == "HANDOFF_ACCEPTED_AND_REQUESTED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_decision_emit_call_done": True,
                "post_promotion_force_cycle_handoff_decision": "unexpected_decision",
            }
        )
        == "HANDOFF_DECISION_EMIT_SITE_REACHED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_reject_reason": "HANDOFF_REJECTED_BY_OBSERVATION_WINDOW",
            }
        )
        == "HANDOFF_REJECTED_BY_OBSERVATION_WINDOW"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_reject_reason": "HANDOFF_REJECTED_BY_MISSING_CONTEXT",
            }
        )
        == "HANDOFF_REJECTED_BY_MISSING_CONTEXT"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_reject_reason": "HANDOFF_REACHED_BUT_REQUEST_NOT_ENQUEUED",
            }
        )
        == "HANDOFF_REACHED_BUT_REQUEST_NOT_ENQUEUED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_reject_reason": "HANDOFF_REJECTED_BY_LOCK",
            }
        )
        == "HANDOFF_REJECTED_BY_LOCK"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_reject_reason": "HANDOFF_REJECTED_BY_DEDUPE",
            }
        )
        == "HANDOFF_REJECTED_BY_DEDUPE"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "post_promotion_force_cycle_handoff_reject": True,
                "post_promotion_force_cycle_handoff_reject_reason": "some_other_reason",
            }
        )
        == "FORCE_CYCLE_HANDOFF_REACHED_BUT_NOT_ACCEPTED"
    )


def test_close_input_trace_classifies_nulls():
    trace = build_canonical_close_input_trace(
        symbol="BTCUSDTM",
        strategy="TrendFollowing",
        side="buy",
        position_id="trade-1",
        net_pnl=0.0,
        gross_fill_pnl_model=None,
        fee_total=None,
        slippage_total=None,
        pnl_decompose={"net_pnl": 0.0},
        source_function_name="_execute_close_order",
        upstream_source_name="position_close",
        runtime_seq=99,
        timestamp="2026-03-28T00:00:01+00:00",
    )
    assert trace["event"] == "canonical_close_input_trace"
    assert trace["canonical_key"] == "BTCUSDTM|TRENDFOLLOWING|buy"
    assert trace["has_pnl_decompose"] is True
    assert trace["gross_present"] is False
    assert trace["fee_present"] is False
    assert trace["promotion_inputs_ready"] is False
    assert trace["null_state_classification"] == "GROSS_AND_FEE_MISSING"
    assert classify_canonical_close_input_trace(None, None, pnl_decompose={"net_pnl": 0.0}) == "GROSS_AND_FEE_MISSING"
    assert classify_canonical_close_input_trace(None, 1.0, pnl_decompose={"net_pnl": 0.0}) == "GROSS_MISSING_ONLY"
    assert classify_canonical_close_input_trace(1.0, None, pnl_decompose={"net_pnl": 0.0}) == "FEE_MISSING_ONLY"
    assert classify_canonical_close_input_trace(1.0, 1.0, pnl_decompose={"net_pnl": 0.0}) == "REALIZED_INPUTS_PRESENT"
    assert classify_canonical_close_input_trace(1.0, 1.0, pnl_decompose=None) == "PNL_DECOMPOSE_MISSING"


def test_simulated_close_quantity_resolution_prefers_positive_source():
    qty, source, state = resolve_simulated_close_quantity(
        {"amount": 0.0, "amount_contracts": 2.0, "allocation_usdt": 100.0, "entry_price": 50.0}
    )
    assert qty == 2.0
    assert source == "amount_contracts"
    assert state == "RAW_INPUTS_PRESENT"


def test_simulated_close_quantity_resolution_flags_zero_size():
    qty, source, state = resolve_simulated_close_quantity(
        {
            "amount": 0.0,
            "amount_contracts": 0.0,
            "allocation_usdt": 0.0,
            "paper_auto_open_usdt": 100.0,
            "entry_price": 50.0,
        }
    )
    assert qty == 2.0
    assert source == "paper_auto_open_usdt_div_entry_price"
    assert state == "RAW_INPUTS_PRESENT"


def test_simulated_close_quantity_resolution_flags_zero_size_without_fallbacks():
    qty, source, state = resolve_simulated_close_quantity(
        {
            "amount": 0.0,
            "amount_contracts": 0.0,
            "allocation_usdt": 0.0,
            "paper_auto_open_usdt": 0.0,
            "entry_price": 50.0,
        }
    )
    assert qty == 0.0
    assert source == "amount"
    assert state == "ZERO_SIZE_CLOSE_INPUT"


def test_simulated_close_quantity_resolution_flags_unknown_raw_state():
    qty, source, state = resolve_simulated_close_quantity(
        {
            "amount": -1.0,
            "amount_contracts": "also-bad",
            "allocation_usdt": "invalid",
            "paper_auto_open_usdt": "invalid",
            "entry_price": 50.0,
        }
    )
    assert qty is None
    assert source == "unknown"
    assert state == "UNKNOWN_RAW_INPUT_STATE"


def test_classify_post_promotion_force_cycle_handoff_trace_covers_emit_site_and_pre_decision_returns():
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_decision_emit_call_done": True,
                "post_promotion_force_cycle_handoff_decision": "unexpected_decision",
            }
        )
        == "HANDOFF_DECISION_EMIT_SITE_REACHED"
    )
    assert (
        classify_post_promotion_force_cycle_handoff_trace(
            {
                "post_promotion_force_cycle_handoff_enter": True,
                "handoff_pre_decision_return_site_id": "child_callback_enter",
                "handoff_pre_decision_return_reason": "not-used",
            }
        )
        == "CHILD_CALLBACK_ENTER"
    )


def test_audit_tracks_close_input_and_output_traces():
    rows = [
        _log_row(
            1,
            "close_pnl_decompose_input_trace",
            {
                "runtime_seq": 10,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "position_id": "trade-1",
                "net_pnl": 0.0,
                "gross_fill_pnl_model": None,
                "fee_total": None,
                "has_pnl_decompose": True,
                "gross_present": False,
                "fee_present": False,
                "promotion_inputs_ready": False,
                "raw_input_classification": "ZERO_SIZE_CLOSE_INPUT",
            },
        ),
        _log_row(
            2,
            "close_pnl_decompose_output_trace",
            {
                "runtime_seq": 10,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "position_id": "trade-1",
                "has_pnl_decompose": True,
                "gross_fill_pnl_model": None,
                "fee_total": None,
                "slippage_total": None,
                "output_null_classification": "GROSS_AND_FEE_MISSING",
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    assert report["aggregate"]["close_input_rows"] == 1
    assert report["aggregate"]["close_output_rows"] == 1
    assert report["aggregate"]["rows_with_zero_size_close_input"] == 1
    assert report["aggregate"]["row_diagnosis_counts"]["ZERO_SIZE_CLOSE_INPUT"] == 1


def test_audit_classifies_no_later_read_after_promotion():
    rows = [
        _log_row(
            1,
            "canonical_gate_read",
            {
                "runtime_seq": 1,
                "row_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "read_trade_count": 0,
                "read_history_ready": False,
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 0,
                "canonical_shadow_history_ready": False,
                "decision_source_name": "production_snapshot_primary",
                "decision_trade_count": 0,
                "decision_history_ready": False,
            },
        ),
        _log_row(
            2,
            "canonical_promotion",
            {
                "runtime_seq": 2,
                "run_ts": "2026-03-28T00:00:02+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": False,
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    assert report["bucket_verdict_counts"]["PROMOTION_ONLY_AT_TERMINAL_END"] == 1
    assert (
        report["per_bucket"]["BTCUSDTM|TRENDFOLLOWING|buy"]["post_promotion_read_verdict"]
        == "CORRIDOR_END_BEFORE_REEVALUATION"
    )
    assert report["final_classification"] == "CORRIDOR_END_BEFORE_REEVALUATION"


def test_audit_classifies_loop_termination_before_next_evaluation_with_probe():
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "canonical_post_promotion_loop_probe_armed",
            {
                "runtime_seq": 2,
                "run_ts": "2026-03-28T00:00:02+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_seq": 1,
                "reason": "canonical_promotion",
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    bucket = report["per_bucket"]["BTCUSDTM|TRENDFOLLOWING|buy"]
    assert bucket["next_loop_iteration_seq_after_promotion"] is None
    assert bucket["entry_pipeline_entered_after_promotion"] is False
    assert bucket["entry_edge_check_reached_after_promotion"] is False
    assert bucket["post_promotion_loop_probe_verdict"] == "LOOP_TERMINATES_BEFORE_NEXT_EVALUATION"


def test_audit_classifies_entry_edge_check_reached_with_probe():
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "canonical_post_promotion_loop_probe_armed",
            {
                "runtime_seq": 2,
                "run_ts": "2026-03-28T00:00:02+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_seq": 1,
                "reason": "canonical_promotion",
            },
        ),
        _log_row(
            3,
            "canonical_post_promotion_loop_probe_next_iteration",
            {
                "runtime_seq": 3,
                "run_ts": "2026-03-28T00:00:03+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_seq": 1,
                "loop_iteration_seq": 3,
                "reason": "canonical_promotion",
            },
        ),
        _log_row(
            4,
            "canonical_post_promotion_entry_pipeline_entered",
            {
                "runtime_seq": 4,
                "run_ts": "2026-03-28T00:00:04+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_seq": 1,
                "next_iteration_seq": 3,
                "entry_pipeline_entered_seq": 4,
                "reason": "canonical_promotion",
            },
        ),
        _log_row(
            5,
            "canonical_post_promotion_entry_edge_check_reached",
            {
                "runtime_seq": 5,
                "run_ts": "2026-03-28T00:00:05+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "promotion_seq": 1,
                "next_iteration_seq": 3,
                "entry_pipeline_entered_seq": 4,
                "entry_edge_check_reached_seq": 5,
                "reason": "canonical_promotion",
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    bucket = report["per_bucket"]["BTCUSDTM|TRENDFOLLOWING|buy"]
    assert bucket["next_loop_iteration_seq_after_promotion"] == 3
    assert bucket["entry_pipeline_entered_after_promotion"] is True
    assert bucket["entry_edge_check_reached_after_promotion"] is True
    assert bucket["post_promotion_loop_probe_verdict"] == "ENTRY_EDGE_CHECK_REACHED"


def test_post_promotion_loop_probe_enabled_accepts_observation_alias(monkeypatch):
    monkeypatch.delenv("RESEARCH_ONLY_POST_PROMOTION_LOOP_PROBE", raising=False)
    monkeypatch.setenv("POST_PROMOTION_OBSERVATION_ENABLED", "1")
    assert botcore._research_only_post_promotion_loop_probe_enabled() is True


def test_post_promotion_loop_probe_enabled_accepts_diagnostic_mode(monkeypatch):
    monkeypatch.delenv("RESEARCH_ONLY_POST_PROMOTION_LOOP_PROBE", raising=False)
    monkeypatch.delenv("POST_PROMOTION_OBSERVATION_ENABLED", raising=False)
    monkeypatch.setenv("DIAGNOSTIC_MODE", "1")
    assert botcore._research_only_post_promotion_loop_probe_enabled() is True


def test_post_promotion_loop_probe_enabled_defaults_on_in_paper(monkeypatch):
    monkeypatch.delenv("RESEARCH_ONLY_POST_PROMOTION_LOOP_PROBE", raising=False)
    monkeypatch.delenv("POST_PROMOTION_OBSERVATION_ENABLED", raising=False)
    monkeypatch.delenv("DIAGNOSTIC_MODE", raising=False)
    monkeypatch.delenv("LIVE", raising=False)
    assert botcore._research_only_post_promotion_loop_probe_enabled() is True


def test_audit_classifies_zero_visible_after_promotion():
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "entry_gate_decision_summary",
            {
                "runtime_seq": 2,
                "ts": "2026-03-28T00:00:02+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            },
        ),
        _log_row(
            3,
            "canonical_gate_read",
            {
                "runtime_seq": 3,
                "row_ts": "2026-03-28T00:00:03+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "read_trade_count": 0,
                "read_history_ready": False,
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 0,
                "canonical_shadow_history_ready": False,
                "decision_source_name": "production_snapshot_primary",
                "decision_trade_count": 0,
                "decision_history_ready": False,
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    assert report["bucket_verdict_counts"]["READ_AFTER_PROMOTION_BUT_ZERO_VISIBLE"] == 1
    assert (
        report["per_bucket"]["BTCUSDTM|TRENDFOLLOWING|buy"]["post_promotion_read_verdict"]
        == "ENTRY_EDGE_CHECK_NOT_REENTERED"
    )
    assert report["final_classification"] == "ENTRY_EDGE_CHECK_NOT_REENTERED"


def test_audit_classifies_post_promotion_stale_zero_state():
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "canonical_bucket_pre_materialization",
            {
                "runtime_seq": 2,
                "timestamp": "2026-03-28T00:00:02+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "source_container_name": "canonical_edge_history_state",
                "nested_key_path": "[BTCUSDTM][TRENDFOLLOWING][buy]",
                "trade_count": 0,
                "history_ready": False,
                "gross_hist_len": 0,
                "fee_hist_len": 0,
                "slippage_hist_len": 0,
            },
        ),
        _log_row(
            3,
            "canonical_gate_read",
            {
                "runtime_seq": 3,
                "row_ts": "2026-03-28T00:00:03+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "read_trade_count": 0,
                "read_history_ready": False,
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 0,
                "canonical_shadow_history_ready": False,
                "decision_source_name": "production_snapshot_fallback",
                "decision_trade_count": 0,
                "decision_history_ready": False,
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    bucket = report["per_bucket"]["BTCUSDTM|TRENDFOLLOWING|buy"]
    assert bucket["first_pre_materialization_seq_after_promotion"] == 2
    assert bucket["first_gate_read_seq_after_promotion"] == 3
    assert bucket["first_gate_read_trade_count_after_promotion"] == 0
    assert bucket["post_promotion_read_verdict"] == "CORRIDOR_END_BEFORE_REEVALUATION"
    assert "READ_AFTER_PROMOTION_BUT_ZERO_VISIBLE" in bucket["candidate_verdicts_seen"]
    assert "CORRIDOR_END_BEFORE_REEVALUATION" in bucket["candidate_verdicts_seen"]
    assert bucket["winning_verdict"] == "CORRIDOR_END_BEFORE_REEVALUATION"
    assert bucket["winning_verdict_reason"] == "post_promotion_read_path_priority"


def test_audit_classifies_visible_after_promotion():
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": False,
            },
        ),
            _log_row(
                2,
                "entry_gate_decision_summary",
                {
                    "runtime_seq": 2,
                    "ts": "2026-03-28T00:00:02+00:00",
                    "symbol": "BTCUSDTM",
                    "strategy": "TRENDFOLLOWING",
                    "side": "buy",
                    "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                },
            ),
            _log_row(
                3,
                "canonical_gate_read",
                {
                    "runtime_seq": 3,
                    "row_ts": "2026-03-28T00:00:03+00:00",
                    "correlation_id": "corr-eligibility",
                    "symbol": "BTCUSDTM",
                    "strategy": "TRENDFOLLOWING",
                    "side": "buy",
                    "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "read_trade_count": 1,
                "read_history_ready": False,
                "read_context": "forced_post_promotion_replay",
                "timing_replay_index": 1,
                "timing_replay_target_reads": 3,
                "gate_read_source_function": "_entry_edge_over_fee_check_forced_timing_replay",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": False,
                "decision_source_name": "production_snapshot_primary",
                "decision_trade_count": 1,
                "decision_history_ready": False,
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    assert report["aggregate"]["buckets_with_forced_replay"] == 1
    assert report["per_bucket"]["BTCUSDTM|TRENDFOLLOWING|buy"]["forced_post_promotion_read_count"] == 1
    assert report["bucket_verdict_counts"]["READ_AFTER_PROMOTION_AND_VISIBLE"] == 1
    assert report["final_classification"] == "POST_PROMOTION_READ_SEES_NONZERO_STATE"


def test_audit_classifies_materialization_boundary_collapse_with_pre_post_traces():
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "canonical_bucket_pre_materialization",
            {
                "runtime_seq": 2,
                "timestamp": "2026-03-28T00:00:02+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "source_container_name": "canonical_edge_history_state",
                "nested_key_path": "[BTCUSDTM][TRENDFOLLOWING][buy]",
                "trade_count": 1,
                "history_ready": False,
                "gross_hist_len": 1,
                "fee_hist_len": 1,
                "slippage_hist_len": 1,
            },
        ),
        _log_row(
            3,
            "canonical_bucket_post_materialization",
            {
                "runtime_seq": 2,
                "timestamp": "2026-03-28T00:00:02+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "materializer_name": "_entry_edge_over_fee_check.snapshot_primary",
                "source_container_name": "canonical_edge_history_state",
                "nested_key_path": "[BTCUSDTM][TRENDFOLLOWING][buy]",
                "trade_count": 0,
                "history_ready": False,
                "gross_hist_len": 0,
                "fee_hist_len": 0,
                "slippage_hist_len": 0,
            },
        ),
        _log_row(
            4,
            "canonical_bucket_collapse_compare",
            {
                "runtime_seq": 2,
                "timestamp": "2026-03-28T00:00:02+00:00",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "pre_trade_count": 1,
                "post_trade_count": 0,
                "pre_gross_hist_len": 1,
                "post_gross_hist_len": 0,
                "pre_fee_hist_len": 1,
                "post_fee_hist_len": 0,
                "pre_slippage_hist_len": 1,
                "post_slippage_hist_len": 0,
                "same_object_identity_if_available": False,
                "same_nested_key_path": True,
                "collapse_result": "FULL_DEFAULT_SHAPE_COLLAPSE",
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    bucket = report["per_bucket"]["BTCUSDTM|TRENDFOLLOWING|buy"]
    assert bucket["max_pre_trade_count_after_promotion"] == 1
    assert bucket["max_post_trade_count_after_promotion"] == 0
    assert bucket["first_post_promotion_collapse_result"] == "FULL_DEFAULT_SHAPE_COLLAPSE"
    assert report["final_classification"] == "CORRIDOR_END_BEFORE_REEVALUATION"


def test_audit_classifies_timing_replay_without_true_evaluated_read():
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "position_close",
            {
                "runtime_seq": 2,
                "row_ts": "2026-03-28T00:00:02+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "position": {"symbol": "BTCUSDTM", "side": "buy", "entry_main_strategy": "TrendFollowing"},
            },
        ),
        _log_row(
            3,
            "entry_gate_decision_summary",
            {
                "runtime_seq": 3,
                "ts": "2026-03-28T00:00:03+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
            },
        ),
        _log_row(
            4,
            "canonical_gate_read",
            {
                "runtime_seq": 4,
                "row_ts": "2026-03-28T00:00:04+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "read_trade_count": 0,
                "read_history_ready": False,
                "timing_replay_index": 1,
                "timing_replay_target_reads": 3,
                "gate_read_source_function": "_entry_edge_over_fee_check_forced_timing_replay",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 0,
                "canonical_shadow_history_ready": False,
                "decision_source_name": "production_snapshot_fallback",
                "decision_trade_count": 0,
                "decision_history_ready": False,
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    bucket = report["per_bucket"]["BTCUSDTM|TRENDFOLLOWING|buy"]
    assert bucket["first_entry_edge_check_seq_after_promotion"] == 3
    assert bucket["was_entry_edge_check_reentered_after_promotion"] is True
    assert bucket["post_promotion_read_verdict"] == "TIMING_REPLAY_IS_NOT_TRUE_EVALUATED_READ"


def test_runner_probe_detects_real_post_promotion_read(tmp_path):
    db_path = tmp_path / "probe_real.db"
    _write_runner_probe_logs(
        db_path,
        [
            _log_row(
                1,
                "canonical_promotion",
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                    "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                },
            ),
            _log_row(
                2,
                "entry_gate_decision_summary",
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                    "canonical_bucket": {
                        "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                    },
                },
            ),
            _log_row(
                3,
                "canonical_explicit_post_promotion_eval_invoked",
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                    "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                    "runtime_seq": 7003,
                },
            ),
            _log_row(
                4,
                "canonical_gate_read",
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                    "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                    "read_trade_count": 1,
                    "canonical_shadow_trade_count": 1,
                },
            ),
        ],
    )
    probe = _probe_real_post_promotion_reevaluation(db_path)
    assert probe["promotion_count"] == 1
    assert probe["promotion_runtime_seq"] == 1
    assert probe["reeval_runtime_seq"] == 7003
    assert probe["observed_real_post_promotion_read"] is True
    assert probe["real_post_promotion_read_count"] == 1
    assert probe["gate_read_after_promotion_runtime_seq"] == 4
    assert probe["real_post_promotion_read_buckets"] == ["BTCUSDTM|TRENDFOLLOWING|buy"]


def test_runner_probe_ignores_summary_and_replay_only_rows(tmp_path):
    db_path = tmp_path / "probe_replay_only.db"
    _write_runner_probe_logs(
        db_path,
        [
            _log_row(
                1,
                "canonical_promotion",
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                    "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                },
            ),
            _log_row(
                2,
                "entry_gate_decision_summary",
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                    "canonical_bucket": {
                        "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                    },
                },
            ),
            _log_row(
                3,
                "canonical_gate_read",
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                    "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                    "timing_replay_index": 1,
                    "timing_replay_target_reads": 3,
                    "read_trade_count": 1,
                    "canonical_shadow_trade_count": 1,
                },
            ),
        ],
    )
    probe = _probe_real_post_promotion_reevaluation(db_path)
    assert probe["promotion_count"] == 1
    assert probe["promotion_runtime_seq"] == 1
    assert probe["reeval_runtime_seq"] is None
    assert probe["observed_real_post_promotion_read"] is False
    assert probe["real_post_promotion_read_count"] == 0
    assert probe["gate_read_after_promotion_runtime_seq"] is None
    assert probe["timing_replay_only_buckets"] == ["BTCUSDTM|TRENDFOLLOWING|buy"]


def test_next_bucket_pin_arms_in_paper(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_ONLY_PIN_NEXT_BUCKET_REEVAL", "1")
    botcore._RESEARCH_ONLY_NEXT_BUCKET_PIN_BY_SYMBOL.clear()

    pin = botcore._research_only_next_bucket_pin_arm("BTCUSDTM", "TrendFollowing", "buy", "canonical_promotion")
    assert pin is not None
    assert pin["symbol"] == "BTCUSDTM"
    assert pin["strategy"] == "TrendFollowing"
    assert pin["side"] == "buy"
    assert pin["consumed"] is False


def test_next_bucket_pin_does_not_arm_in_live(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("RESEARCH_ONLY_PIN_NEXT_BUCKET_REEVAL", "1")
    botcore._RESEARCH_ONLY_NEXT_BUCKET_PIN_BY_SYMBOL.clear()

    pin = botcore._research_only_next_bucket_pin_arm("BTCUSDTM", "TrendFollowing", "buy", "canonical_promotion")
    assert pin is None


def test_next_bucket_pin_consumes_once(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_ONLY_PIN_NEXT_BUCKET_REEVAL", "1")
    botcore._RESEARCH_ONLY_NEXT_BUCKET_PIN_BY_SYMBOL.clear()

    pin = botcore._research_only_next_bucket_pin_arm("BTCUSDTM", "TrendFollowing", "buy", "canonical_promotion")
    matched, expired = botcore._research_only_next_bucket_pin_match("BTCUSDTM", "TrendFollowing", "buy")
    assert expired is None
    assert matched is not None
    consumed = botcore._research_only_next_bucket_pin_consume("BTCUSDTM", "TrendFollowing", "buy")
    assert consumed is not None
    cleared = botcore._research_only_next_bucket_pin_clear("BTCUSDTM", reason="consumed")
    assert cleared is not None
    matched_again, expired_again = botcore._research_only_next_bucket_pin_match("BTCUSDTM", "TrendFollowing", "buy")
    assert matched_again is None
    assert expired_again is None


def test_audit_marks_true_evaluated_same_bucket_read():
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": True,
            },
        ),
        _log_row(
            2,
            "entry_gate_decision_summary",
            {
                "runtime_seq": 2,
                "ts": "2026-03-28T00:00:02+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            },
        ),
        _log_row(
            3,
            "canonical_gate_read",
            {
                "runtime_seq": 3,
                "row_ts": "2026-03-28T00:00:03+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "read_trade_count": 1,
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": True,
                "forced_same_bucket_next_eval": True,
                "override_type": "next_bucket_pin",
                "override_consumed": True,
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    bucket = report["per_bucket"]["BTCUSDTM|TRENDFOLLOWING|buy"]
    assert bucket["post_promotion_read_verdict"] == "TRUE_EVALUATED_SAME_BUCKET_REEVALUATION"
    assert bucket["stayed_on_promoted_canonical_bucket"] is True
    assert bucket["first_true_evaluated_same_bucket_read_seq_after_promotion"] == 3


def test_explicit_post_promotion_eval_arms_in_paper(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL", "1")
    botcore._RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL_BY_SYMBOL.clear()

    events = []

    class _Logger:
        def log(self, event, payload):
            events.append((event, payload))

    logger = _Logger()

    record = botcore._research_only_explicit_post_promotion_eval_arm(
        "BTCUSDTM",
        "TrendFollowing",
        "buy",
        "BTCUSDTM|TRENDFOLLOWING|buy",
        "canonical_promotion",
        logger=logger,
    )
    assert record is not None
    assert record["symbol"] == "BTCUSDTM"
    assert record["strategy"] == "TrendFollowing"
    assert record["side"] == "buy"
    assert record["promoted_bucket_key"] == "BTCUSDTM|TRENDFOLLOWING|buy"
    assert record["consumed"] is False
    assert any(event == "canonical_explicit_post_promotion_eval_arm_considered" for event, _ in events)
    assert any(event == "canonical_explicit_post_promotion_eval_armed" for event, _ in events)


def test_explicit_post_promotion_eval_does_not_arm_in_live(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL", "1")
    botcore._RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL_BY_SYMBOL.clear()

    record = botcore._research_only_explicit_post_promotion_eval_arm(
        "BTCUSDTM",
        "TrendFollowing",
        "buy",
        "BTCUSDTM|TRENDFOLLOWING|buy",
        "canonical_promotion",
    )
    assert record is None


def test_explicit_post_promotion_eval_invokes_once_and_clears(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL", "1")
    botcore._RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL_BY_SYMBOL.clear()

    events = []

    class _Logger:
        def log(self, event, payload):
            events.append((event, payload))

    monkeypatch.setattr(botcore, "infinity_logger", _Logger(), raising=False)

    record = botcore._research_only_explicit_post_promotion_eval_arm(
        "BTCUSDTM",
        "TrendFollowing",
        "buy",
        "BTCUSDTM|TRENDFOLLOWING|buy",
        "canonical_promotion",
    )
    assert record is not None

    calls = []

    def _fake_entry_edge_over_fee_check(
        symbol_name,
        strategy_name,
        side_name,
        **kwargs,
    ):
        calls.append(
            {
                "symbol_name": symbol_name,
                "strategy_name": strategy_name,
                "side_name": side_name,
                **kwargs,
            }
        )
        return {"ok": True}

    emitted = botcore._research_only_explicit_post_promotion_eval_invoke(
        _fake_entry_edge_over_fee_check,
        "BTCUSDTM",
        "TrendFollowing",
        "buy",
    )
    assert emitted == 1
    assert len(calls) == 2
    assert calls[0]["read_context"] == "explicit_research_post_promotion_eval"
    assert calls[0]["forced_same_bucket_next_eval"] is True
    assert calls[0]["override_type"] == "explicit_post_promotion_eval"
    assert calls[0]["override_consumed"] is True
    assert calls[0]["promoted_bucket_key"] == "BTCUSDTM|TRENDFOLLOWING|buy"
    assert calls[0]["timing_replay_index"] is None
    assert calls[1]["read_context"] == "forced_post_promotion_evaluated_cycle"
    assert calls[1]["forced_same_bucket_next_eval"] is True
    assert calls[1]["override_type"] == "explicit_post_promotion_eval"
    assert calls[1]["override_consumed"] is True
    assert calls[1]["promoted_bucket_key"] == "BTCUSDTM|TRENDFOLLOWING|buy"
    assert calls[1]["timing_replay_index"] == 1
    assert botcore._RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL_BY_SYMBOL == {}
    event_names = [event for event, _payload in events]
    assert "canonical_explicit_post_promotion_eval_arm_considered" in event_names
    assert "canonical_explicit_post_promotion_eval_armed" in event_names
    assert "canonical_explicit_post_promotion_eval_invoked" in event_names
    assert "canonical_explicit_post_promotion_eval_completed" in event_names
    assert "canonical_explicit_post_promotion_eval_cleared" in event_names


def test_audit_classifies_explicit_post_promotion_read():
    corr_id = "corr_test_explicit_001"
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "correlation_id": corr_id,
                "run_ts": "2026-03-29T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": True,
            },
        ),
        _log_row(
            2,
            "canonical_explicit_post_promotion_eval_armed",
            {
                "runtime_seq": 2,
                "correlation_id": corr_id,
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "armed_at_seq": 2,
                "reason": "canonical_promotion",
            },
        ),
        _log_row(
            3,
            "canonical_explicit_post_promotion_eval_invoked",
            {
                "runtime_seq": 3,
                "correlation_id": corr_id,
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "armed_at_seq": 2,
                "invoked_at_seq": 3,
                "reason": "canonical_promotion",
            },
        ),
        _log_row(
            4,
            "entry_gate_decision_summary",
            {
                "runtime_seq": 4,
                "ts": "2026-03-29T00:00:04+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            },
        ),
        _log_row(
            5,
            "canonical_gate_read",
            {
                "runtime_seq": 5,
                "correlation_id": corr_id,
                "row_ts": "2026-03-29T00:00:05+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "canonical_shadow_storage",
                "read_trade_count": 1,
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": True,
                "forced_same_bucket_next_eval": True,
                "override_type": "explicit_post_promotion_eval",
                "override_consumed": True,
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "timing_replay_index": None,
                "timing_replay_target_reads": None,
            },
        ),
        _log_row(
            6,
            "canonical_explicit_post_promotion_eval_completed",
            {
                "runtime_seq": 6,
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "armed_at_seq": 2,
                "invoked_at_seq": 3,
                "consumed_at_seq": 3,
                "success": True,
                "reason": "canonical_promotion",
            },
        ),
        _log_row(
            7,
            "canonical_explicit_post_promotion_eval_cleared",
            {
                "runtime_seq": 7,
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "promoted_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "armed_at_seq": 2,
                "consumed_at_seq": 3,
                "cleared_at_seq": 7,
                "clear_reason": "completed",
                "reason": "canonical_promotion",
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    bucket = report["per_bucket"]["BTCUSDTM|TRENDFOLLOWING|buy"]
    assert bucket["post_promotion_read_verdict"] == "EXPLICIT_RESEARCH_POST_PROMOTION_EVALUATED_READ"
    assert bucket["first_true_evaluated_same_bucket_read_seq_after_promotion"] == 5
    assert bucket["stayed_on_promoted_canonical_bucket"] is True
    assert bucket["explicit_post_promotion_eval_trace_count"] == 4
    assert report["aggregate"]["correlation_stage_counts"]["written"] >= 1
    assert report["aggregate"]["correlation_stage_counts"]["persisted"] >= 1
    assert report["aggregate"]["correlation_stage_counts"]["observed"] >= 1


def test_audit_detects_read_source_mismatch():
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "run_ts": "2026-03-28T00:00:01+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "production_snapshot_primary",
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 1,
                "canonical_shadow_history_ready": False,
            },
        ),
        _log_row(
            2,
            "canonical_gate_read",
            {
                "runtime_seq": 2,
                "row_ts": "2026-03-28T00:00:02+00:00",
                "symbol": "BTCUSDTM",
                "strategy": "TRENDFOLLOWING",
                "side": "buy",
                "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
                "read_source_name": "production_snapshot_primary",
                "read_trade_count": 0,
                "read_history_ready": False,
                "canonical_shadow_source_name": "canonical_shadow_storage",
                "canonical_shadow_trade_count": 0,
                "canonical_shadow_history_ready": False,
                "decision_source_name": "production_snapshot_primary",
                "decision_trade_count": 0,
                "decision_history_ready": False,
            },
        ),
    ]
    report = _build_report_from_logs(_run_meta(), rows)
    assert report["bucket_verdict_counts"]["READ_SOURCE_MISMATCH_CONFIRMED"] == 1
    assert report["aggregate"]["top_failure_mode"] == "STILL_NO_VISIBILITY_AFTER_FORCED_POST_PROMOTION_READS"


def test_compare_canonical_shadow_materialization_classifies_write_and_next_read():
    write_missing = compare_canonical_shadow_materialization({}, {})
    assert write_missing["per_promotion_classification"] == "WRITE_PATH_DID_NOT_APPEND_BUCKET"

    zero_history_write = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 0,
            "stored_history_ready": False,
            "promotion_write_source_payload_present": True,
            "promotion_write_bucket_exists_after_append": True,
            "promotion_write_storage_trade_count_after_append": 0,
            "promotion_write_storage_history_ready_after_append": False,
            "promotion_write_effective_value_state": "ZERO_WRITTEN",
        },
        {
            "canonical_key_read": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_trade_count": 0,
            "next_read_history_ready": False,
            "read_trade_count": 0,
            "read_history_ready": False,
            "read_source_name": "canonical_shadow_storage",
            "promotion_to_next_read_delay_ms": 15.0,
        },
    )
    assert zero_history_write["per_promotion_classification"] == "WRITE_PATH_APPENDED_ZERO_HISTORY_BUCKET"
    assert zero_history_write["promotion_write_trade_count"] == 0
    assert zero_history_write["next_read_trade_count"] == 0
    assert zero_history_write["same_bucket_match_strict"] is False

    nonzero_visible = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 2,
            "stored_history_ready": True,
            "promotion_write_source_payload_present": True,
            "promotion_write_bucket_exists_after_append": True,
            "promotion_write_storage_trade_count_after_append": 2,
            "promotion_write_storage_history_ready_after_append": True,
            "promotion_write_effective_value_state": "NONZERO_WRITTEN",
        },
        {
            "canonical_key_read": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_trade_count": 2,
            "next_read_history_ready": True,
            "read_trade_count": 2,
            "read_history_ready": True,
            "read_source_name": "canonical_shadow_storage",
            "promotion_to_next_read_delay_ms": 25.0,
            "storage_bucket_id": 7,
        },
    )
    assert nonzero_visible["per_promotion_classification"] == "WRITE_PATH_APPENDED_NONZERO_BUCKET_AND_READ_SAW_IT"
    assert nonzero_visible["same_bucket_match_strict"] is True
    assert nonzero_visible["promotion_to_next_read_delay_ms"] == 25.0

    nonzero_missing = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 3,
            "stored_history_ready": True,
            "promotion_write_source_payload_present": True,
            "promotion_write_bucket_exists_after_append": True,
            "promotion_write_storage_trade_count_after_append": 3,
            "promotion_write_storage_history_ready_after_append": True,
            "promotion_write_effective_value_state": "NONZERO_WRITTEN",
        },
        {
            "canonical_key_read": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_trade_count": 0,
            "next_read_history_ready": False,
            "read_trade_count": 0,
            "read_history_ready": False,
            "read_source_name": "canonical_shadow_storage",
            "promotion_to_next_read_delay_ms": 30.0,
        },
    )
    assert nonzero_missing["per_promotion_classification"] == "WRITE_PATH_APPENDED_NONZERO_BUCKET_BUT_READ_DID_NOT_SEE_IT"


def test_compare_canonical_shadow_materialization_covers_remaining_verdict_paths():
    exception_case = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 1,
            "promotion_write_source_payload_present": True,
            "post_write_readback_exception_class": "RuntimeError",
        },
        {},
    )
    assert exception_case["stage_exception"] is True
    assert exception_case["final_per_correlation_verdict"] == "EXCEPTION_SWALLOWED_IN_CRITICAL_PATH"

    emit_attempted = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 2,
            "promotion_write_source_payload_present": True,
        },
        {
            "post_promotion_gate_read_emit_attempt": True,
            "read_trade_count": 0,
        },
    )
    assert emit_attempted["stage_emit_attempted"] is True
    assert emit_attempted["stage_persisted"] is False
    assert emit_attempted["final_per_correlation_verdict"] == "EMIT_ATTEMPTED_BUT_NOT_PERSISTED"

    write_only = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 2,
            "promotion_write_source_payload_present": True,
        },
        {},
    )
    assert write_only["stage_written"] is True
    assert write_only["stage_emit_attempted"] is False
    assert write_only["final_per_correlation_verdict"] == "WRITE_SUCCEEDED_BUT_EMIT_NOT_ATTEMPTED"

    invalid_primary_delay = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 1,
            "promotion_write_source_payload_present": True,
        },
        {
            "promotion_to_next_read_delay_ms": "not-a-number",
        },
    )
    assert invalid_primary_delay["promotion_to_next_read_delay_ms"] is None

    invalid_fallback_delay = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 1,
            "promotion_write_source_payload_present": True,
        },
        {
            "write_to_read_delay_ms": "not-a-number",
        },
    )
    assert invalid_fallback_delay["promotion_to_next_read_delay_ms"] is None

    timestamp_delay = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 1,
            "promotion_write_source_payload_present": True,
            "write_timestamp": "2026-03-28T00:00:00+00:00",
        },
        {
            "canonical_key_read": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_trade_count": 1,
            "read_trade_count": 1,
            "read_source_name": "canonical_shadow_storage",
            "timestamp": "2026-03-28T00:00:02+00:00",
            "storage_bucket_id": 7,
            "next_read_history_ready": True,
        },
    )
    assert timestamp_delay["promotion_to_next_read_delay_ms"] == 2000.0

    read_without_write = compare_canonical_shadow_materialization(
        {},
        {
            "canonical_key_read": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_trade_count": 1,
            "read_trade_count": 1,
            "read_source_name": "canonical_shadow_storage",
            "storage_bucket_id": 7,
        },
    )
    assert read_without_write["comparison_result"] == "READ_WITHOUT_MATCHING_WRITE"

    write_without_read = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 1,
            "promotion_write_source_payload_present": True,
        },
        {},
    )
    assert write_without_read["comparison_result"] == "WRITE_WITHOUT_MATCHING_READ"

    match_visible = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 2,
            "promotion_write_source_payload_present": True,
            "storage_bucket_id": 7,
            "stored_bucket_shape": {"gross_hist_len": 2},
        },
        {
            "canonical_key_read": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_trade_count": 2,
            "read_trade_count": 2,
            "read_source_name": "canonical_shadow_storage",
            "storage_bucket_id": 7,
            "read_source_bucket_shape": {"gross_hist_len": 2},
        },
    )
    assert match_visible["comparison_result"] == "MATCH_VISIBLE"
    assert match_visible["same_bucket_match_strict"] is True

    zeroed_on_read = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 2,
            "promotion_write_source_payload_present": True,
            "storage_bucket_id": 8,
        },
        {
            "canonical_key_read": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_trade_count": 0,
            "read_trade_count": 0,
            "read_source_name": "canonical_shadow_storage",
            "storage_bucket_id": 8,
        },
    )
    assert zeroed_on_read["comparison_result"] == "MATCH_BUT_ZEROED_ON_READ"

    unknown_comparison = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 0,
            "promotion_write_source_payload_present": True,
            "storage_bucket_id": 9,
        },
        {
            "canonical_key_read": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_trade_count": 0,
            "read_trade_count": 0,
            "read_source_name": "canonical_shadow_storage",
            "storage_bucket_id": 9,
        },
    )
    assert unknown_comparison["comparison_result"] == "UNKNOWN_COMPARISON_STATE"

    different_nested_path = compare_canonical_shadow_materialization(
        {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "storage_target_name": "canonical_shadow_storage",
            "stored_trade_count": 1,
            "promotion_write_source_payload_present": True,
            "storage_bucket_id": 11,
            "nested_key_path": "[BTCUSDTM][TRENDFOLLOWING][buy]",
        },
        {
            "canonical_key_read": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "next_read_trade_count": 1,
            "read_trade_count": 1,
            "read_source_name": "canonical_shadow_storage",
            "storage_bucket_id": 11,
            "nested_key_path": "[BTCUSDTM][OTHER][buy]",
        },
    )
    assert different_nested_path["comparison_result"] == "MATCH_BUT_DIFFERENT_NESTED_PATH"


def test_classify_post_promotion_read_path_trace_covers_read_path_stages():
    assert (
        classify_post_promotion_read_path_trace({})
        == "POST_PROMOTION_EVAL_NOT_ENTERED"
    )
    assert (
        classify_post_promotion_read_path_trace(
            {"post_promotion_eval_enter": True, "post_promotion_gate_read_emit_attempt": False}
        )
        == "POST_PROMOTION_EVAL_ENTERED_BUT_GATE_READ_NOT_EMITTED"
    )
    assert (
        classify_post_promotion_read_path_trace(
            {
                "post_promotion_eval_enter": True,
                "post_promotion_gate_read_emit_attempt": True,
                "post_promotion_gate_read_emit_done": False,
            }
        )
        == "POST_PROMOTION_GATE_READ_EMITTED_BUT_NOT_PERSISTED"
    )
    assert (
        classify_post_promotion_read_path_trace(
            {
                "post_promotion_eval_enter": True,
                "post_promotion_gate_read_emit_attempt": True,
                "post_promotion_gate_read_emit_done": True,
                "post_promotion_read_trade_count_visible": 2,
                "post_promotion_read_history_ready_visible": True,
            }
        )
        == "POST_PROMOTION_GATE_READ_PERSISTED_WITH_NONZERO_VISIBILITY"
    )


def test_classify_post_promotion_arm_trace_covers_arm_lifecycle():
    assert classify_post_promotion_arm_trace({}) == "ARM_NOT_CONSIDERED"
    assert (
        classify_post_promotion_arm_trace(
            {
                "post_promotion_arm_considered": True,
                "post_promotion_arm_allowed": False,
                "post_promotion_arm_skip_reason": "explicit_post_promotion_eval_disabled",
            }
        )
        == "ARM_CONSIDERED_BUT_PREDICATE_FAILED"
    )
    assert (
        classify_post_promotion_arm_trace(
            {
                "post_promotion_arm_considered": True,
                "post_promotion_arm_allowed": True,
                "post_promotion_arm_set": True,
                "post_promotion_arm_cleared": True,
                "post_promotion_invoke_expected": False,
            }
        )
        == "ARM_SET_THEN_CLEARED_BEFORE_INVOKE"
    )
    assert (
        classify_post_promotion_arm_trace(
            {
                "post_promotion_arm_considered": True,
                "post_promotion_arm_allowed": True,
                "post_promotion_arm_set": True,
                "post_promotion_invoke_expected": True,
                "post_promotion_invoke_missed_reason": "already_consumed",
            }
        )
        == "ARM_SET_BUT_INVOKE_PATH_MISSED"
    )
    assert (
        classify_post_promotion_arm_trace(
            {
                "post_promotion_arm_considered": True,
                "post_promotion_arm_allowed": True,
                "post_promotion_arm_set": True,
                "post_promotion_invoke_expected": True,
                "post_promotion_invoke_missed_reason": None,
            }
        )
        == "ARM_SET_AND_INVOKED"
    )


def test_classify_explicit_post_promotion_eval_disabled_provenance_covers_sources():
    assert (
        classify_explicit_post_promotion_eval_disabled_provenance({})
        == "DISABLED_BY_DEFAULT_CONFIG"
    )
    assert (
        classify_explicit_post_promotion_eval_disabled_provenance(
            {
                "explicit_post_promotion_eval_enabled_resolved": False,
                "explicit_post_promotion_eval_enabled_source": "DEFAULT_CONFIG",
                "explicit_post_promotion_eval_default_used": True,
            }
        )
        == "DISABLED_BY_DEFAULT_CONFIG"
    )
    assert (
        classify_explicit_post_promotion_eval_disabled_provenance(
            {
                "explicit_post_promotion_eval_enabled_resolved": False,
                "explicit_post_promotion_eval_enabled_source": "ENV_RESOLUTION",
                "explicit_post_promotion_eval_env_value": "0",
            }
        )
        == "DISABLED_BY_ENV_RESOLUTION"
    )
    assert (
        classify_explicit_post_promotion_eval_disabled_provenance(
            {
                "explicit_post_promotion_eval_enabled_resolved": False,
                "explicit_post_promotion_eval_runner_request_present": True,
                "explicit_post_promotion_eval_botcore_flag_present": False,
            }
        )
        == "DISABLED_BY_RUNNER_HANDOFF_MISMATCH"
    )
    assert (
        classify_explicit_post_promotion_eval_disabled_provenance(
            {
                "explicit_post_promotion_eval_enabled_resolved": False,
                "explicit_post_promotion_eval_enabled_source": "BOTCORE_LOCAL_OVERRIDE",
                "explicit_post_promotion_eval_botcore_flag_present": True,
            }
        )
        == "DISABLED_BY_BOTCORE_LOCAL_OVERRIDE"
    )
    assert (
        classify_explicit_post_promotion_eval_disabled_provenance(
            {
                "explicit_post_promotion_eval_enabled_resolved": True,
                "post_promotion_arm_set": True,
            }
        )
        == "ENABLED_AND_ARMED"
    )


def test_controlled_runner_before_variant_enables_explicit_post_promotion_eval():
    before_env = _variant_env(
        Path("unit-test.db"),
        "before",
        use_mock=True,
        market_type="futures",
        run_symbols="BTCUSDTM,ETHUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=10,
        equity_snapshot_sec=30,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///unit-test.db",
        alpha_bootstrap_source_db_glob="unit-test.db",
    )
    after_env = _variant_env(
        Path("unit-test.db"),
        "after",
        use_mock=True,
        market_type="futures",
        run_symbols="BTCUSDTM,ETHUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=10,
        equity_snapshot_sec=30,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///unit-test.db",
        alpha_bootstrap_source_db_glob="unit-test.db",
    )
    assert before_env["CONTROLLED_KPI_EXPLICIT_POST_PROMOTION_EVAL_REQUEST"] == "1"
    assert before_env["RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL"] == "1"
    assert "CONTROLLED_KPI_EXPLICIT_POST_PROMOTION_EVAL_REQUEST" not in after_env
    assert "RESEARCH_ONLY_EXPLICIT_POST_PROMOTION_EVAL" not in after_env


def test_classify_explicit_post_promotion_invoke_trace_covers_emit_boundaries():
    assert (
        classify_explicit_post_promotion_invoke_trace({})
        == "INVOKE_EXITED_BEFORE_EMIT_BRANCH"
    )
    assert (
        classify_explicit_post_promotion_invoke_trace(
            {
                "post_invoke_emit_path_enter": True,
                "post_invoke_emit_guard_considered": True,
                "post_invoke_emit_guard_allowed": False,
            }
        )
        == "INVOKE_COMPLETED_BUT_EMIT_GUARD_FALSE"
    )
    assert (
        classify_explicit_post_promotion_invoke_trace(
            {
                "post_invoke_emit_path_enter": True,
                "post_invoke_emit_guard_considered": True,
                "post_invoke_emit_guard_allowed": True,
                "post_invoke_emit_early_return": True,
            }
        )
        == "INVOKE_COMPLETED_BUT_EARLY_RETURN"
    )
    assert (
        classify_explicit_post_promotion_invoke_trace(
            {
                "post_invoke_emit_path_enter": True,
                "post_invoke_emit_guard_considered": True,
                "post_invoke_emit_guard_allowed": True,
                "post_invoke_emit_attempt_call_enter": True,
            }
        )
        == "EMIT_ATTEMPT_CALL_REACHED"
    )
    assert (
        classify_explicit_post_promotion_invoke_trace(
            {
                "explicit_post_promotion_invoke_enter": True,
                "explicit_post_promotion_emit_branch_considered": True,
                "explicit_post_promotion_emit_branch_allowed": False,
            }
        )
        == "EMIT_BRANCH_CONSIDERED_BUT_PREDICATE_FAILED"
    )
    assert (
        classify_explicit_post_promotion_invoke_trace(
            {
                "explicit_post_promotion_invoke_enter": True,
                "explicit_post_promotion_emit_branch_considered": True,
                "explicit_post_promotion_emit_branch_allowed": True,
                "explicit_post_promotion_emit_branch_entered": False,
            }
        )
        == "EMIT_BRANCH_ENTERED_BUT_ATTEMPT_NOT_REACHED"
    )
    assert (
        classify_explicit_post_promotion_invoke_trace(
            {
                "explicit_post_promotion_invoke_enter": True,
                "explicit_post_promotion_emit_branch_considered": True,
                "explicit_post_promotion_emit_branch_allowed": True,
                "explicit_post_promotion_emit_branch_entered": False,
                "explicit_post_promotion_emit_exception_class": "ValueError",
                "explicit_post_promotion_emit_exception_message": "boom",
            }
        )
        == "EMIT_BRANCH_ABORTED_BY_EXCEPTION"
    )
    assert (
        classify_explicit_post_promotion_invoke_trace(
            {
                "explicit_post_promotion_invoke_enter": True,
                "explicit_post_promotion_emit_branch_considered": True,
                "explicit_post_promotion_emit_branch_allowed": True,
                "explicit_post_promotion_emit_branch_entered": True,
                "explicit_post_promotion_gate_read_emit_attempt": True,
                "explicit_post_promotion_gate_read_emit_done": False,
            }
        )
        == "EMIT_ATTEMPTED_BUT_NOT_PERSISTED"
    )
    assert (
        classify_explicit_post_promotion_invoke_trace(
            {
                "explicit_post_promotion_invoke_enter": True,
                "explicit_post_promotion_emit_branch_considered": True,
                "explicit_post_promotion_emit_branch_allowed": True,
                "explicit_post_promotion_invoke_exit": True,
                "explicit_post_promotion_gate_read_emit_attempt": True,
                "explicit_post_promotion_gate_read_emit_done": True,
                "canonical_gate_read": True,
            }
        )
        == "EMIT_DONE_AND_PERSISTED"
    )


def test_audit_preserves_duplicate_forced_cycle_trace_rows_for_same_bucket():
    meta = _run_meta()
    rows = [
        _log_row(
            1,
            "canonical_promotion",
            {
                "runtime_seq": 1,
                "correlation_id": "corr-dup",
                "symbol": "BTCUSDTM",
                "strategy": "AUTO_TEST",
                "side": "buy",
                "canonical_key": "BTCUSDTM|AUTO_TEST|buy",
            },
        ),
        _log_row(
            2,
            "post_promotion_force_cycle_request",
            {
                "runtime_seq": 2,
                "correlation_id": "corr-dup",
                "symbol": "BTCUSDTM",
                "strategy": "AUTO_TEST",
                "side": "buy",
                "canonical_key": "BTCUSDTM|AUTO_TEST|buy",
                "promotion_runtime_seq": 1,
            },
        ),
        _log_row(
            3,
            "post_promotion_force_cycle_request_scan_enter",
            {
                "runtime_seq": 3,
                "correlation_id": "corr-dup",
                "symbol": "BTCUSDTM",
                "strategy": "AUTO_TEST",
                "side": "buy",
                "canonical_key": "BTCUSDTM|AUTO_TEST|buy",
                "request_count_seen": 1,
            },
        ),
        _log_row(
            4,
            "post_promotion_force_cycle_request_scan_enter",
            {
                "runtime_seq": 3,
                "correlation_id": "corr-dup",
                "symbol": "BTCUSDTM",
                "strategy": "AUTO_TEST",
                "side": "buy",
                "canonical_key": "BTCUSDTM|AUTO_TEST|buy",
                "request_count_seen": 1,
            },
        ),
    ]
    report = _build_report_from_logs(meta, rows)
    bucket = report["per_bucket"]["BTCUSDTM|AUTO_TEST|buy"]
    trace_names = [trace["trace_event_name"] for trace in bucket["forced_cycle_traces"]]
    assert trace_names.count("post_promotion_force_cycle_request_scan_enter") == 2


def test_canonical_promotion_write_history_ready_can_differ_from_gate_read_threshold():
    reset_canonical_edge_history_state()
    promote_to_canonical_edge_history(
        symbol="BTCUSDTM",
        strategy="TrendFollowing",
        side="buy",
        gross_fill_pnl_model=1.2,
        fee_total=0.2,
        spread_slippage_proxy=0.01,
        ts=1.0,
    )
    promo = promote_to_canonical_edge_history(
        symbol="BTCUSDTM",
        strategy="TrendFollowing",
        side="buy",
        gross_fill_pnl_model=1.3,
        fee_total=0.3,
        spread_slippage_proxy=0.02,
        ts=2.0,
    )
    promotion_telemetry = build_canonical_promotion_telemetry(
        canonical_result=promo,
        source_event_type="position_close",
        gross_fill_pnl_model=1.3,
        fee_total=0.3,
        spread_slippage_proxy=0.02,
        position_id="trade-2",
        close_ts="2026-03-28T00:00:02+00:00",
        run_ts="2026-03-28T00:00:02+00:00",
        bucket_created_on_this_event=bool(promo.get("bucket_created_on_this_event")),
        runtime_seq=next_canonical_trace_seq(),
    )
    readback = get_canonical_edge_history(
        "BTCUSDTM",
        "TrendFollowing",
        "buy",
        min_trades=2,
    )
    assert promotion_telemetry["promotion_write_history_ready"] is False
    assert readback["canonical_shadow_history_ready"] is True


def test_compare_canonical_shadow_materialization_keeps_payload_presence_flag_independent():
    comparison = compare_canonical_shadow_materialization(
        write_payload={
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "stored_trade_count": 1,
            "storage_target_name": "canonical_shadow_storage",
            "nested_key_path": "[BTCUSDTM][TRENDFOLLOWING][buy]",
            "storage_bucket_id": 123,
            "stored_history_ready": False,
        },
        read_payload={
            "canonical_key_read": "BTCUSDTM|TRENDFOLLOWING|buy",
            "read_trade_count": 1,
            "read_source_name": "canonical_shadow_storage",
            "nested_key_path": "[BTCUSDTM][TRENDFOLLOWING][buy]",
            "storage_bucket_id": 123,
            "read_history_ready": False,
        },
    )
    assert (
        comparison["per_promotion_classification"]
        == "WRITE_PATH_APPENDED_NONZERO_BUCKET_AND_READ_SAW_IT"
    )
    assert comparison["promotion_write_source_payload_present"] is False
