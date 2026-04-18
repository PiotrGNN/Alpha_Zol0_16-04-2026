from core.BotCore import (
    _build_post_green_hold_guard_bypass_telemetry,
    _should_post_green_hold_guard_bypass,
)


def test_post_green_hold_guard_bypass_when_hard_window_imminent():
    assert _should_post_green_hold_guard_bypass(
        exit_reason="post_green_protective_exit",
        post_green_metrics={
            "post_green_hard_close_imminent": True,
            "post_green_giveback_ratio": 0.4,
        },
        current_net_after_fee=0.001,
    )


def test_post_green_hold_guard_bypass_when_trigger_already_armed():
    assert _should_post_green_hold_guard_bypass(
        exit_reason="post_green_protective_exit",
        post_green_metrics=None,
        current_net_after_fee=-0.001,
        post_green_trigger_seen=True,
    )


def test_post_green_hold_guard_bypass_when_severe_giveback_and_negative_residual():
    assert _should_post_green_hold_guard_bypass(
        exit_reason="post_green_protective_exit",
        post_green_metrics={
            "post_green_hard_close_imminent": False,
            "post_green_giveback_ratio": 1.25,
        },
        current_net_after_fee=-0.0004,
    )


def test_post_green_hold_guard_no_bypass_for_non_post_green_reasons():
    assert not _should_post_green_hold_guard_bypass(
        exit_reason="auto_close_hard",
        post_green_metrics={
            "post_green_hard_close_imminent": True,
            "post_green_giveback_ratio": 2.0,
        },
        current_net_after_fee=-0.01,
    )


def test_post_green_hold_guard_bypass_telemetry_marks_armed_trigger():
    payload = _build_post_green_hold_guard_bypass_telemetry(
        symbol="ETHUSDTM",
        trade_id="trade-1",
        reason="post_green_protective_exit",
        source_branch="branch_auto_close",
        exit_min_hold_sec=40,
        post_green_candidate_seen=True,
        post_green_trigger_seen=True,
    )

    assert payload["event"] == "close_execute_post_green_hold_guard_bypass"
    assert payload["symbol"] == "ETHUSDTM"
    assert payload["trade_id"] == "trade-1"
    assert payload["reason"] == "post_green_protective_exit"
    assert payload["source_branch"] == "branch_auto_close"
    assert payload["exit_min_hold_sec"] == 40
    assert payload["post_green_hold_guard_bypass"] is True
    assert (
        payload["post_green_hold_guard_bypass_reason"]
        == "armed_post_green_trigger_seen"
    )
    assert payload["post_green_lifecycle_candidate_seen"] is True
    assert payload["post_green_lifecycle_trigger_seen"] is True


def test_post_green_hold_guard_bypass_telemetry_carries_branch_attribution():
    payload = _build_post_green_hold_guard_bypass_telemetry(
        symbol="ETHUSDTM",
        trade_id="trade-2",
        reason="post_green_protective_exit",
        source_branch="branch_auto_close",
        exit_min_hold_sec=40,
        post_green_candidate_seen=True,
        post_green_trigger_seen=False,
        post_green_metrics={
            "post_green_hard_close_imminent": True,
            "post_green_giveback_ratio": 1.25,
            "post_green_trigger_mode": "bnr_time_forced_exit",
            "post_green_attempt_seq": 7,
            "post_green_branch_seq": "bnr_time_forced_exit",
            "post_green_peak_to_burden_ratio": 0.82,
            "post_green_bnr_time_forced_exit_sec": 1.0,
            "post_green_trigger_reason_detail": "bnr_time_forced_exit",
            "post_green_rescue_exit_reason": "post_green_protective_exit",
        },
    )

    assert (
        payload["post_green_hold_guard_bypass_reason"]
        == "post_green_hard_close_imminent"
    )
    assert payload["post_green_attempt_seq"] == 7
    assert payload["post_green_branch_seq"] == "bnr_time_forced_exit"
    assert payload["post_green_peak_to_burden_ratio"] == 0.82
    assert payload["post_green_bnr_time_forced_exit_sec"] == 1.0
    assert payload["post_green_trigger_reason_detail"] == "bnr_time_forced_exit"
    assert payload["post_green_rescue_exit_reason"] == "post_green_protective_exit"


def test_post_green_hold_guard_no_bypass_without_metrics():
    assert not _should_post_green_hold_guard_bypass(
        exit_reason="post_green_protective_exit",
        post_green_metrics=None,
        current_net_after_fee=-0.01,
    )
