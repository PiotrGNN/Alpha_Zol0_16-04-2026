import importlib.util
import json
import sqlite3
from pathlib import Path


def _load_controlled_kpi_run():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "controlled_kpi_run.py"
    )
    spec = importlib.util.spec_from_file_location(
        "controlled_kpi_run_testmod", module_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_db(tmp_path: Path, rows: list[tuple[str, dict]]):
    db_path = tmp_path / "diagnostic.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE logs (timestamp TEXT, event TEXT, details TEXT)"
        )
        for idx, (event, payload) in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
                (f"2026-03-27T21:00:{idx:02d}+00:00", event, json.dumps(payload)),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_empty_trace_summary(tmp_path):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(tmp_path, [])
    summary = mod._build_diagnostic_runtime_summary(
        db_path=db_path,
        run_id="run1",
        started_at_utc="2026-03-27T21:00:00+00:00",
        ended_at_utc="2026-03-27T21:01:00+00:00",
        variant="before",
        symbols=["ETHUSDTM"],
        env_flags={"DIAGNOSTIC_MODE": "1", "LIVE": "0"},
        metrics={"decisions_count": 0, "trade_count": 0},
    )
    assert summary["gate_trace_summary"]["total_trace_events"] == 0
    assert summary["gate_trace_by_gate"] == []
    assert summary["top_blockers_after_skip"] == []
    assert summary["admission_outcome_summary"]["rows"] == 0


def test_single_gate_skip_summary(tmp_path):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(
        tmp_path,
        [
            (
                "diagnostic_gate_trace",
                {
                    "gate_name": "side_guard",
                    "gate_blocked": False,
                    "gate_skipped": True,
                    "skip_reason": "diagnostic_override",
                    "local_gate_reason_final": "current_side",
                },
            ),
        ],
    )
    summary = mod._build_diagnostic_runtime_summary(
        db_path=db_path,
        run_id="run2",
        started_at_utc="2026-03-27T21:00:00+00:00",
        ended_at_utc="2026-03-27T21:01:00+00:00",
        variant="before",
        symbols=["ETHUSDTM"],
        env_flags={"DIAGNOSTIC_MODE": "1", "LIVE": "0"},
        metrics={"decisions_count": 1, "trade_count": 0},
    )
    gate = summary["gate_trace_by_gate"][0]
    assert gate["gate_name"] == "side_guard"
    assert gate["blocked_count"] == 0
    assert gate["skipped_count"] == 1
    assert gate["skip_reason_counts"] == {"diagnostic_override": 1}
    assert summary["gate_trace_summary"]["total_gate_skipped"] == 1


def test_multi_gate_trace_summary(tmp_path):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(
        tmp_path,
        [
            (
                "diagnostic_gate_trace",
                {
                    "gate_name": "net_target_guard",
                    "gate_blocked": False,
                    "gate_skipped": True,
                    "skip_reason": "diagnostic_override",
                    "local_gate_reason_final": "current_side",
                },
            ),
            (
                "diagnostic_gate_trace",
                {
                    "gate_name": "side_expectancy",
                    "gate_blocked": True,
                    "gate_skipped": False,
                    "skip_reason": None,
                    "local_gate_reason_final": "side_expectancy",
                },
            ),
            (
                "entry_gate_decision_summary",
                {
                    "final_allow": False,
                    "local_gate_reason": "current_side",
                },
            ),
            (
                "entry_gate_decision_summary",
                {
                    "final_allow": False,
                    "local_gate_reason": "side_expectancy",
                },
            ),
        ],
    )
    summary = mod._build_diagnostic_runtime_summary(
        db_path=db_path,
        run_id="run3",
        started_at_utc="2026-03-27T21:00:00+00:00",
        ended_at_utc="2026-03-27T21:01:00+00:00",
        variant="before",
        symbols=["ETHUSDTM"],
        env_flags={"DIAGNOSTIC_MODE": "1", "LIVE": "0"},
        metrics={"decisions_count": 2, "trade_count": 0},
    )
    by_gate = {row["gate_name"]: row for row in summary["gate_trace_by_gate"]}
    assert by_gate["net_target_guard"]["skipped_count"] == 1
    assert by_gate["side_expectancy"]["blocked_count"] == 1
    assert summary["top_blockers_after_skip"][0] == ["current_side", 1]
    assert summary["admission_outcome_summary"]["rows"] == 2
    assert summary["admission_outcome_summary"]["blocked"] == 2
    assert summary["admission_outcome_summary"]["top_local_gate_reason"] == [
        ["current_side", 1],
        ["side_expectancy", 1],
    ]


def test_diagnostic_runtime_summary_coerces_final_allow_strings(tmp_path):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(
        tmp_path,
        [
            (
                "entry_gate_decision_summary",
                {
                    "final_allow": "false",
                    "local_gate_reason": "current_side",
                },
            ),
            (
                "entry_gate_decision_summary",
                {
                    "final_allow": "true",
                    "local_gate_reason": "net_target_guard",
                },
            ),
        ],
    )
    summary = mod._build_diagnostic_runtime_summary(
        db_path=db_path,
        run_id="run3b",
        started_at_utc="2026-03-27T21:00:00+00:00",
        ended_at_utc="2026-03-27T21:01:00+00:00",
        variant="before",
        symbols=["ETHUSDTM"],
        env_flags={"DIAGNOSTIC_MODE": "1", "LIVE": "0"},
        metrics={"decisions_count": 2, "trade_count": 0},
    )

    assert summary["admission_outcome_summary"]["rows"] == 2
    assert summary["admission_outcome_summary"]["admitted"] == 1
    assert summary["admission_outcome_summary"]["blocked"] == 1


def test_diagnostic_runtime_summary_coerces_gate_flags_strings(tmp_path):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(
        tmp_path,
        [
            (
                "diagnostic_gate_trace",
                {
                    "gate_name": "side_guard",
                    "gate_blocked": "true",
                    "gate_skipped": "false",
                    "skip_reason": None,
                    "local_gate_reason_final": "current_side",
                },
            ),
            (
                "diagnostic_gate_trace",
                {
                    "gate_name": "net_target_guard",
                    "gate_blocked": "false",
                    "gate_skipped": "true",
                    "skip_reason": "diagnostic_override",
                    "local_gate_reason_final": "net_target_guard",
                },
            ),
        ],
    )
    summary = mod._build_diagnostic_runtime_summary(
        db_path=db_path,
        run_id="run3c",
        started_at_utc="2026-03-27T21:00:00+00:00",
        ended_at_utc="2026-03-27T21:01:00+00:00",
        variant="before",
        symbols=["ETHUSDTM"],
        env_flags={"DIAGNOSTIC_MODE": "1", "LIVE": "0"},
        metrics={"decisions_count": 2, "trade_count": 0},
    )

    by_gate = {row["gate_name"]: row for row in summary["gate_trace_by_gate"]}
    assert by_gate["side_guard"]["blocked_count"] == 1
    assert by_gate["side_guard"]["skipped_count"] == 0
    assert by_gate["net_target_guard"]["blocked_count"] == 0
    assert by_gate["net_target_guard"]["skipped_count"] == 1
    assert summary["gate_trace_summary"]["total_gate_blocked"] == 1
    assert summary["gate_trace_summary"]["total_gate_skipped"] == 1


def test_runtime_summary_counts_insufficient_history_seed_only_as_blocked_coldstart(
    tmp_path,
):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(
        tmp_path,
        [
            (
                "diagnostic_gate_trace",
                {
                    "gate_name": "entry_gate",
                    "gate_blocked": True,
                    "gate_skipped": False,
                    "skip_reason": None,
                    "local_gate_reason_final": "insufficient_history_seed_only",
                },
            ),
            (
                "entry_gate_decision_summary",
                {
                    "final_allow": False,
                    "entry_gate_bucket": "history_coldstart",
                    "local_gate_reason": "insufficient_history_seed_only",
                },
            ),
        ],
    )

    summary = mod._build_diagnostic_runtime_summary(
        db_path=db_path,
        run_id="run-history-coldstart",
        started_at_utc="2026-03-27T21:00:00+00:00",
        ended_at_utc="2026-03-27T21:01:00+00:00",
        variant="after",
        symbols=["ETHUSDTM"],
        env_flags={"DIAGNOSTIC_MODE": "1", "LIVE": "0"},
        metrics={"decisions_count": 1, "trade_count": 0},
    )
    entry_rows = mod._load_entry_gate_summary_payloads(db_path)

    assert entry_rows[0]["payload"]["final_allow"] is False
    assert entry_rows[0]["payload"]["entry_gate_bucket"] == "history_coldstart"
    assert summary["gate_trace_summary"]["total_gate_blocked"] == 1
    assert summary["top_blockers_after_skip"] == [
        ["insufficient_history_seed_only", 1]
    ]
    assert summary["admission_outcome_summary"]["blocked"] == 1
    assert summary["admission_outcome_summary"]["admitted"] == 0
    assert summary["admission_outcome_summary"]["top_local_gate_reason"] == [
        ["insufficient_history_seed_only", 1]
    ]


def test_runtime_summary_counts_explicit_pass_through_only_as_pass_through(
    tmp_path,
):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(
        tmp_path,
        [
            (
                "diagnostic_gate_trace",
                {
                    "gate_name": "prefilter_guard",
                    "gate_blocked": False,
                    "gate_skipped": False,
                    "skip_reason": None,
                    "local_gate_reason_final": "",
                },
            ),
        ],
    )

    summary = mod._build_diagnostic_runtime_summary(
        db_path=db_path,
        run_id="run-pass-through",
        started_at_utc="2026-03-27T21:00:00+00:00",
        ended_at_utc="2026-03-27T21:01:00+00:00",
        variant="after",
        symbols=["ETHUSDTM"],
        env_flags={"DIAGNOSTIC_MODE": "1", "LIVE": "0"},
        metrics={"decisions_count": 1, "trade_count": 0},
    )

    gate = summary["gate_trace_by_gate"][0]
    assert gate["gate_name"] == "prefilter_guard"
    assert gate["blocked_count"] == 0
    assert gate["skipped_count"] == 0
    assert gate["pass_through_count"] == 1
    assert summary["gate_trace_summary"]["total_gate_blocked"] == 0
    assert summary["gate_trace_summary"]["total_gate_skipped"] == 0


def test_json_sections_present(tmp_path):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(
        tmp_path,
        [
            (
                "diagnostic_gate_trace",
                {
                    "gate_name": "current_side",
                    "gate_blocked": True,
                    "gate_skipped": False,
                    "skip_reason": None,
                    "local_gate_reason_final": "current_side",
                },
            )
        ],
    )
    summary = mod._build_diagnostic_runtime_summary(
        db_path=db_path,
        run_id="run4",
        started_at_utc="2026-03-27T21:00:00+00:00",
        ended_at_utc="2026-03-27T21:01:00+00:00",
        variant="before",
        symbols=["ETHUSDTM"],
        env_flags={
            "DIAGNOSTIC_MODE": "1",
            "LIVE": "0",
            "DIAG_DISABLE_NET_TARGET_GUARD": "1",
            "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION": "1",
            "DIAG_DISABLE_SIDE_GUARD": "1",
            "DIAG_DISABLE_SIDE_EXPECTANCY": "1",
        },
        metrics={"decisions_count": 1, "trade_count": 0},
    )
    assert "run_metadata" in summary
    assert "env_diagnostic_flags" in summary
    assert "gate_trace_summary" in summary
    assert "gate_trace_by_gate" in summary
    assert "top_blockers_after_skip" in summary
    assert "admission_outcome_summary" in summary


def test_net_target_guard_trace_included(tmp_path):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(
        tmp_path,
        [
            (
                "diagnostic_gate_trace",
                {
                    "gate_name": "net_target_guard",
                    "gate_blocked": True,
                    "gate_skipped": False,
                    "skip_reason": None,
                    "local_gate_reason_final": "net_target_guard",
                },
            )
        ],
    )
    summary = mod._build_diagnostic_runtime_summary(
        db_path=db_path,
        run_id="run5",
        started_at_utc="2026-03-27T21:00:00+00:00",
        ended_at_utc="2026-03-27T21:01:00+00:00",
        variant="before",
        symbols=["ETHUSDTM"],
        env_flags={"DIAGNOSTIC_MODE": "1", "LIVE": "0"},
        metrics={"decisions_count": 1, "trade_count": 0},
    )
    by_gate = {row["gate_name"]: row for row in summary["gate_trace_by_gate"]}
    assert "net_target_guard" in by_gate
    assert by_gate["net_target_guard"]["blocked_count"] == 1


def test_close_drain_snapshot_caps_requests_to_real_expected_closes(tmp_path):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(
        tmp_path,
        [
            (
                "position_open",
                {"symbol": "BTCUSDTM", "position": {"symbol": "BTCUSDTM"}},
            ),
            ("position_close_request", {"symbol": "BTCUSDTM", "reason": "window_end"}),
            ("position_close_request", {"symbol": "ETHUSDTM", "reason": "window_end"}),
            (
                "position_close",
                {"symbol": "BTCUSDTM", "position": {"symbol": "BTCUSDTM"}},
            ),
        ],
    )
    snapshot = mod._close_drain_snapshot(db_path)
    assert snapshot["position_open_count"] == 1
    assert snapshot["position_close_request_count_raw"] == 2
    assert snapshot["position_close_request_count"] == 1
    assert snapshot["close_request_backlog_raw"] == 1
    assert snapshot["close_request_backlog"] == 0
    assert snapshot["duplicate_close_request_count"] == 1
    assert snapshot["duplicate_close_request_symbols"] == ["ETHUSDTM"]
    assert snapshot["progress_complete"] is True


def test_enqueue_close_requests_only_targets_pending_open_symbols(tmp_path):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(
        tmp_path,
        [
            (
                "position_open",
                {"symbol": "BTCUSDTM", "position": {"symbol": "BTCUSDTM"}},
            ),
        ],
    )
    diag = []

    def _diag(event_name, **payload):
        diag.append((event_name, payload))

    inserted = mod._enqueue_close_requests(
        db_path,
        ["BTCUSDTM", "ETHUSDTM"],
        reason="controlled_kpi_window_end",
        diag_cb=_diag,
    )

    assert inserted == 1
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            (
                "SELECT details FROM logs "
                "WHERE event='position_close_request' ORDER BY rowid"
            )
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    payload = json.loads(rows[0][0])
    assert payload["symbol"] == "BTCUSDTM"
    started = next(
        payload
        for event, payload in diag
        if event == "position_close_request_enqueue_started"
    )
    assert started["requested_symbols"] == ["BTCUSDTM", "ETHUSDTM"]
    assert started["symbols"] == ["BTCUSDTM"]
    assert started["skipped_symbols"] == ["ETHUSDTM"]


def test_post_promotion_reeval_enqueue_retries_locked_sqlite(monkeypatch, tmp_path):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(tmp_path, [])
    real_connect = sqlite3.connect
    calls = {"count": 0}

    def flaky_connect(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(mod.sqlite3, "connect", flaky_connect)
    diag = []

    def _diag(event_name, **payload):
        diag.append((event_name, payload))

    row_id = mod._enqueue_post_promotion_reeval_request(
        db_path,
        {
            "symbol": "BTCUSDTM",
            "strategy": "TrendFollowing",
            "side": "buy",
            "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "promotion_runtime_seq": 123,
            "requested_by": "unit_test",
            "request_reason": "phase4_lock_retry",
        },
        diag_cb=_diag,
    )

    assert row_id is not None
    assert calls["count"] >= 3
    retry_events = [
        event
        for event, _ in diag
        if event == "post_promotion_reeval_request_retry"
    ]
    assert len(retry_events) >= 2
    assert any(event == "post_promotion_reeval_requested" for event, _ in diag)


def test_post_promotion_reeval_enqueue_reports_failure_on_persistent_lock(
    monkeypatch, tmp_path
):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(tmp_path, [])

    def always_locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(mod.sqlite3, "connect", always_locked)
    diag = []

    def _diag(event_name, **payload):
        diag.append((event_name, payload))

    row_id = mod._enqueue_post_promotion_reeval_request(
        db_path,
        {
            "symbol": "BTCUSDTM",
            "strategy": "TrendFollowing",
            "side": "buy",
            "canonical_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "promotion_runtime_seq": 123,
            "requested_by": "unit_test",
            "request_reason": "phase4_lock_fail",
        },
        diag_cb=_diag,
    )

    assert row_id is None
    final_events = [
        payload
        for event, payload in diag
        if event == "post_promotion_reeval_requested"
        and payload.get("post_promotion_reeval_result") == "enqueue_failed"
    ]
    assert final_events


def test_should_request_forced_cycle_after_reeval_enqueue_failure():
    mod = _load_controlled_kpi_run()
    assert (
        mod._should_request_post_promotion_forced_cycle(
            post_promotion_reeval_completed=False,
            post_promotion_reeval_result="request_enqueue_failed",
            post_promotion_forced_cycle_requested=False,
        )
        is True
    )
    assert (
        mod._should_request_post_promotion_forced_cycle(
            post_promotion_reeval_completed=False,
            post_promotion_reeval_result="request_enqueue_failed",
            post_promotion_forced_cycle_requested=True,
        )
        is False
    )
    assert (
        mod._should_request_post_promotion_forced_cycle(
            post_promotion_reeval_completed=False,
            post_promotion_reeval_result="request_enqueued",
            post_promotion_forced_cycle_requested=False,
        )
        is False
    )
    assert (
        mod._should_request_post_promotion_forced_cycle(
            post_promotion_reeval_completed=True,
            post_promotion_reeval_result="reevaluation_completed",
            post_promotion_forced_cycle_requested=False,
        )
        is True
    )


def test_resolve_forced_cycle_trigger_after_reeval_completed():
    mod = _load_controlled_kpi_run()
    trigger = mod._resolve_post_promotion_forced_cycle_trigger(
        post_promotion_reeval_completed=True,
        post_promotion_reeval_result="reevaluation_completed",
    )
    assert trigger["mode"] == "after_reeval_completed"
    assert trigger["request_reason"] == "post_promotion_forced_cycle"


def test_resolve_forced_cycle_trigger_after_enqueue_failure():
    mod = _load_controlled_kpi_run()
    trigger = mod._resolve_post_promotion_forced_cycle_trigger(
        post_promotion_reeval_completed=False,
        post_promotion_reeval_result="request_enqueue_failed",
    )
    assert trigger["mode"] == "after_reeval_enqueue_failure"
    assert (
        trigger["request_reason"]
        == "post_promotion_forced_cycle_after_enqueue_failure"
    )


def test_finalize_forced_cycle_trigger_contract_inactive_when_not_requested():
    mod = _load_controlled_kpi_run()
    contract = mod._finalize_post_promotion_forced_cycle_trigger_contract(
        post_promotion_forced_cycle_requested=False,
        post_promotion_forced_cycle_trigger_mode=None,
        post_promotion_forced_cycle_request_reason=None,
        post_promotion_reeval_completed=False,
        post_promotion_reeval_result="request_enqueue_failed",
    )
    assert contract["active"] is False
    assert contract["status"] == "inactive"
    assert contract["ok"] is True
    assert contract["reason_codes"] == []


def test_finalize_forced_cycle_trigger_contract_ok_after_enqueue_failure():
    mod = _load_controlled_kpi_run()
    contract = mod._finalize_post_promotion_forced_cycle_trigger_contract(
        post_promotion_forced_cycle_requested=True,
        post_promotion_forced_cycle_trigger_mode="after_reeval_enqueue_failure",
        post_promotion_forced_cycle_request_reason=(
            "post_promotion_forced_cycle_after_enqueue_failure"
        ),
        post_promotion_reeval_completed=False,
        post_promotion_reeval_result="request_enqueue_failed",
    )
    assert contract["active"] is True
    assert contract["status"] == "ok"
    assert contract["ok"] is True
    assert contract["reason_codes"] == []


def test_finalize_forced_cycle_trigger_contract_detects_mode_mismatch():
    mod = _load_controlled_kpi_run()
    contract = mod._finalize_post_promotion_forced_cycle_trigger_contract(
        post_promotion_forced_cycle_requested=True,
        post_promotion_forced_cycle_trigger_mode="after_reeval_completed",
        post_promotion_forced_cycle_request_reason="post_promotion_forced_cycle",
        post_promotion_reeval_completed=False,
        post_promotion_reeval_result="request_enqueue_failed",
    )
    assert contract["active"] is True
    assert contract["status"] == "mismatch"
    assert contract["ok"] is False
    assert "trigger_mode_mismatch" in contract["reason_codes"]
    assert "request_reason_mismatch" in contract["reason_codes"]


def test_successful_shutdown_normalizes_wrapper_returncode_when_drain_complete():
    mod = _load_controlled_kpi_run()
    assert (
        mod._normalize_process_returncode(
            shutdown_classification="real_post_promotion_read_observed",
            raw_returncode=1,
            final_close_drain_snapshot={
                "pending_positions": 0,
                "close_request_backlog": 0,
            },
        )
        == 0
    )
    assert (
        mod._normalize_process_returncode(
            shutdown_classification="real_post_promotion_read_observed",
            raw_returncode=1,
            final_close_drain_snapshot={
                "pending_positions": 1,
                "close_request_backlog": 0,
            },
        )
        == 1
    )
    assert (
        mod._normalize_process_returncode(
            shutdown_classification="close_flush_done_pending_positions_zero",
            raw_returncode=1,
            final_close_drain_snapshot={
                "pending_positions": 0,
                "close_request_backlog": 1,
            },
        )
        == 1
    )
    assert (
        mod._normalize_process_returncode(
            shutdown_classification="deterministic_stall_pending_close_drain",
            raw_returncode=0,
            final_close_drain_snapshot=None,
        )
        == 0
    )
    assert (
        mod._normalize_process_returncode(
            shutdown_classification="deterministic_stall_pending_close_drain",
            raw_returncode=1,
            final_close_drain_snapshot="not-a-dict",
        )
        == 1
    )


def test_final_shutdown_recheck_handles_missing_snapshot_as_not_applicable():
    mod = _load_controlled_kpi_run()
    resolved = mod._resolve_final_shutdown_state(
        shutdown_classification=None,
        termination_reason=None,
        final_close_drain_snapshot=None,
    )
    assert resolved["candidate_shutdown_classification"] is None
    assert resolved["candidate_termination_reason"] is None
    assert resolved["final_shutdown_classification"] is None
    assert resolved["final_termination_reason"] is None
    assert resolved["final_progress_complete"] is False
    assert resolved["final_drain_recheck_result"] == "not_applicable"


def test_final_shutdown_recheck_downgrades_success_when_pending_positions_remain():
    mod = _load_controlled_kpi_run()
    resolved = mod._resolve_final_shutdown_state(
        shutdown_classification="close_flush_done_pending_positions_zero",
        termination_reason="close_flush_done_pending_positions_zero",
        final_close_drain_snapshot={
            "position_open_count": 13,
            "position_close_count": 12,
            "pending_positions": 1,
            "close_request_backlog": 0,
            "progress_complete": False,
        },
    )
    assert (
        resolved["final_shutdown_classification"]
        == "close_drain_incomplete_pending_positions"
    )
    assert (
        resolved["final_termination_reason"]
        == "close_drain_incomplete_pending_positions"
    )
    assert resolved["final_progress_complete"] is False
    assert (
        resolved["final_drain_recheck_result"]
        == "success_classification_invalidated_by_final_snapshot"
    )


def test_final_shutdown_recheck_revises_latched_stall_after_late_drain_completion():
    mod = _load_controlled_kpi_run()
    resolved = mod._resolve_final_shutdown_state(
        shutdown_classification="deterministic_stall_pending_close_drain",
        termination_reason="deterministic_stall_pending_close_drain",
        final_close_drain_snapshot={
            "position_close_count": 4,
            "pending_positions": 0,
            "close_request_backlog": 0,
            "progress_complete": True,
        },
    )
    assert (
        resolved["candidate_shutdown_classification"]
        == "deterministic_stall_pending_close_drain"
    )
    assert (
        resolved["final_shutdown_classification"]
        == "close_flush_done_pending_positions_zero"
    )
    assert (
        resolved["final_termination_reason"]
        == "close_flush_done_pending_positions_zero"
    )
    assert (
        resolved["final_drain_recheck_result"]
        == "late_close_drain_completion_observed"
    )
    assert resolved["final_progress_complete"] is True


def test_final_shutdown_recheck_preserves_real_stall_when_drain_incomplete():
    mod = _load_controlled_kpi_run()
    resolved = mod._resolve_final_shutdown_state(
        shutdown_classification="deterministic_stall_pending_close_drain",
        termination_reason="deterministic_stall_pending_close_drain",
        final_close_drain_snapshot={
            "position_close_count": 3,
            "pending_positions": 1,
            "close_request_backlog": 1,
            "progress_complete": False,
        },
    )
    assert (
        resolved["final_shutdown_classification"]
        == "deterministic_stall_pending_close_drain"
    )
    assert (
        resolved["final_termination_reason"]
        == "deterministic_stall_pending_close_drain"
    )
    assert (
        resolved["final_drain_recheck_result"]
        == "stall_persisted_after_final_recheck"
    )
    assert resolved["final_progress_complete"] is False


def test_final_shutdown_recheck_revises_timeout_after_late_drain_completion():
    mod = _load_controlled_kpi_run()
    resolved = mod._resolve_final_shutdown_state(
        shutdown_classification="close_drain_timeout_pending_positions",
        termination_reason="close_drain_timeout_pending_positions",
        final_close_drain_snapshot={
            "position_close_count": 5,
            "pending_positions": 0,
            "close_request_backlog": 0,
            "progress_complete": True,
        },
    )
    assert (
        resolved["candidate_shutdown_classification"]
        == "close_drain_timeout_pending_positions"
    )
    assert (
        resolved["final_shutdown_classification"]
        == "close_flush_done_pending_positions_zero"
    )
    assert (
        resolved["final_termination_reason"]
        == "close_flush_done_pending_positions_zero"
    )
    assert (
        resolved["final_drain_recheck_result"]
        == "late_close_drain_completion_observed"
    )
    assert resolved["final_progress_complete"] is True


def test_final_shutdown_recheck_preserves_timeout_when_drain_incomplete():
    mod = _load_controlled_kpi_run()
    resolved = mod._resolve_final_shutdown_state(
        shutdown_classification="close_drain_timeout_pending_positions",
        termination_reason="close_drain_timeout_pending_positions",
        final_close_drain_snapshot={
            "position_close_count": 3,
            "pending_positions": 2,
            "close_request_backlog": 1,
            "progress_complete": False,
        },
    )
    assert (
        resolved["final_shutdown_classification"]
        == "close_drain_timeout_pending_positions"
    )
    assert (
        resolved["final_termination_reason"]
        == "close_drain_timeout_pending_positions"
    )
    assert (
        resolved["final_drain_recheck_result"]
        == "timeout_persisted_after_final_recheck"
    )
    assert resolved["final_progress_complete"] is False


def test_controlled_entry_cutoff_scales_for_short_corridors():
    mod = _load_controlled_kpi_run()
    assert mod._controlled_entry_cutoff_sec(60, 10) == 15
    assert mod._controlled_entry_cutoff_sec(120, 10) == 20
    assert mod._controlled_entry_cutoff_sec(360, 10) == 20


def test_parse_json_payload_handles_nested_strings_and_non_dict_inputs():
    mod = _load_controlled_kpi_run()

    assert mod._parse_json_payload(None) == {}
    assert mod._parse_json_payload({"alpha": 1}) == {"alpha": 1}
    assert mod._parse_json_payload(["alpha"]) == {}
    assert mod._parse_json_payload('{"alpha": 1}') == {"alpha": 1}
    assert mod._parse_json_payload(
        json.dumps(json.dumps({"alpha": 1}))
    ) == {"alpha": 1}
    assert mod._parse_json_payload("not-json") == {}


def test_diagnostic_payload_loaders_preserve_order_and_coerce_invalid_rows(
    tmp_path,
):
    mod = _load_controlled_kpi_run()
    db_path = _make_db(
        tmp_path,
        [
            (
                "entry_gate_decision_summary",
                {"final_allow": False, "local_gate_reason": "current_side"},
            ),
            ("entry_gate_decision_summary", ["skip", "me"]),
            (
                "entry_gate_decision_summary",
                '{"final_allow": true, "local_gate_reason": "side_guard"}',
            ),
            (
                "diagnostic_gate_trace",
                {
                    "gate_name": "side_guard",
                    "gate_blocked": True,
                    "gate_skipped": False,
                    "skip_reason": None,
                    "local_gate_reason_final": "current_side",
                },
            ),
            ("diagnostic_gate_trace", ["skip", "me"]),
            (
                "diagnostic_gate_trace",
                '{"gate_name": "net_target_guard", "gate_blocked": false, '
                '"gate_skipped": true, "skip_reason": '
                '"diagnostic_override", "local_gate_reason_final": '
                '"net_target_guard"}',
            ),
        ],
    )

    entry_rows = mod._load_entry_gate_summary_payloads(db_path)
    trace_rows = mod._load_diagnostic_trace_rows(db_path)

    assert [row["rowid"] for row in entry_rows] == [1, 2, 3]
    assert entry_rows[1]["payload"] == {}
    assert [
        row["payload"]["local_gate_reason"]
        for row in entry_rows
        if row["payload"]
    ] == [
        "current_side",
        "side_guard",
    ]
    assert [row["rowid"] for row in trace_rows] == [4, 5, 6]
    assert trace_rows[1]["payload"] == {}
    assert [row["payload"]["gate_name"] for row in trace_rows if row["payload"]] == [
        "side_guard",
        "net_target_guard",
    ]

    missing_db = tmp_path / "missing.db"
    assert mod._load_entry_gate_summary_payloads(missing_db) == []
    assert mod._load_diagnostic_trace_rows(missing_db) == []


def test_diagnostic_payload_loaders_return_empty_on_query_exception(tmp_path):
    mod = _load_controlled_kpi_run()
    db_path = tmp_path / "no_logs_table.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
    finally:
        conn.close()

    assert mod._load_entry_gate_summary_payloads(db_path) == []
    assert mod._load_diagnostic_trace_rows(db_path) == []


def test_write_diagnostic_runtime_summary_persists_json(tmp_path, monkeypatch):
    mod = _load_controlled_kpi_run()
    monkeypatch.setattr(mod, "WORKDIR", tmp_path)

    report = {"run_id": "run-123", "status": "ok"}
    out_path = mod._write_diagnostic_runtime_summary(report, "run-123")

    assert out_path == (
        tmp_path
        / "artifacts"
        / "diagnostics"
        / "diagnostic_runtime_summary_run-123.json"
    )
    assert out_path is not None
    assert json.loads(out_path.read_text(encoding="utf-8")) == report


def test_write_diagnostic_runtime_summary_fail_closed_on_write_error(
    tmp_path, monkeypatch, capsys
):
    mod = _load_controlled_kpi_run()
    monkeypatch.setattr(mod, "WORKDIR", tmp_path)

    def boom(self, *args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(mod.Path, "write_text", boom)

    assert (
        mod._write_diagnostic_runtime_summary({"run_id": "run-456"}, "run-456")
        is None
    )
    captured = capsys.readouterr()
    assert "failed to write diagnostic runtime summary" in captured.out.lower()
