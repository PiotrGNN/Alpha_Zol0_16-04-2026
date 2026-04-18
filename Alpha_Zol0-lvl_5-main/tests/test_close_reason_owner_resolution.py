from core.BotCore import (
    _classify_exit_owner,
    _normalize_exit_reason_value,
    _resolve_close_reason_with_owner,
)


class _ExplodingString:
    def __str__(self):
        raise RuntimeError("boom")


def test_resolve_close_reason_prefers_payload_and_economic_owner():
    resolved = _resolve_close_reason_with_owner(
        payload_exit_reason="auto_close_time_economics",
        close_execute_reason=None,
        execute_call_reason=None,
        candidate_reason=None,
        weak_peak_reason=None,
        source_branch="branch_auto_close",
    )

    assert resolved["exit_reason"] == "auto_close_time_economics"
    assert resolved["reason_source"] == "position_payload_exit_reason"
    assert resolved["exit_owner"] == "economic_exit"


def test_resolve_close_reason_uses_candidate_reason_when_payload_missing():
    resolved = _resolve_close_reason_with_owner(
        payload_exit_reason=None,
        close_execute_reason=None,
        execute_call_reason=None,
        candidate_reason="post_green_protective_exit",
        weak_peak_reason=None,
        source_branch="branch_auto_close",
    )

    assert resolved["exit_reason"] == "post_green_protective_exit"
    assert (
        resolved["reason_source"]
        == "close_candidate_normal.exit_reason_candidate"
    )
    assert resolved["exit_owner"] == "post_green_protection_exit"


def test_resolve_close_reason_prefers_timer_payload_after_post_green_skip():
    resolved = _resolve_close_reason_with_owner(
        payload_exit_reason="auto_close_hard",
        close_execute_reason=None,
        execute_call_reason=None,
        candidate_reason="post_green_protective_exit",
        weak_peak_reason=None,
        source_branch="branch_auto_close",
    )

    assert resolved["exit_reason"] == "auto_close_hard"
    assert resolved["reason_source"] == "position_payload_exit_reason"
    assert resolved["exit_owner"] == "time_based_exit"


def test_resolve_close_reason_uses_timer_close_execute_fallback_after_skip():
    resolved = _resolve_close_reason_with_owner(
        payload_exit_reason=None,
        close_execute_reason="auto_close_hard",
        execute_call_reason=None,
        candidate_reason="post_green_protective_exit",
        weak_peak_reason=None,
        source_branch="branch_auto_close",
    )

    assert resolved["exit_reason"] == "auto_close_hard"
    assert resolved["reason_source"] == "close_execute_exit.reason"
    assert resolved["exit_owner"] == "time_based_exit"


def test_resolve_close_reason_keeps_post_green_payload_owner_over_weak_peak_overlap():
    resolved = _resolve_close_reason_with_owner(
        payload_exit_reason="post_green_protective_exit",
        close_execute_reason=None,
        execute_call_reason=None,
        candidate_reason=None,
        weak_peak_reason="weak_peak_stale_decay_hard_window",
        source_branch="branch_auto_close",
    )

    assert resolved["exit_reason"] == "post_green_protective_exit"
    assert resolved["reason_source"] == "position_payload_exit_reason"
    assert resolved["exit_owner"] == "post_green_protection_exit"


def test_resolve_close_reason_uses_weak_peak_when_available():
    resolved = _resolve_close_reason_with_owner(
        payload_exit_reason=None,
        close_execute_reason=None,
        execute_call_reason=None,
        candidate_reason=None,
        weak_peak_reason="weak_peak_stale_decay_hard_window",
        source_branch="branch_auto_close",
    )

    assert resolved["exit_reason"] == "weak_peak_stale_decay_hard_window"
    assert resolved["reason_source"] == "weak_peak_decay_reason"
    assert resolved["exit_owner"] == "peak_decay_exit"


def test_classify_exit_owner_maps_plain_weak_peak_decay_reason():
    assert _classify_exit_owner("weak_peak_stale_decay") == "peak_decay_exit"


def test_classify_exit_owner_covers_all_fallback_buckets():
    assert _classify_exit_owner("sl") == "risk_guard_exit"
    assert _classify_exit_owner("auto_close_time_fee_floor") == "economic_exit"
    assert _classify_exit_owner("auto_close_hard") == "time_based_exit"
    assert _classify_exit_owner("opposite_signal") == "signal_reversal_exit"
    assert _classify_exit_owner("paper_run_end_force_close") == (
        "run_end_cleanup_exit"
    )
    assert _classify_exit_owner("", source_branch="exchange_sync") == (
        "run_end_cleanup_exit"
    )
    assert _classify_exit_owner("", source_branch="mark_to_market_loop") == (
        "time_based_exit"
    )


def test_classify_exit_owner_run_once_force_close_without_branch():
    assert _classify_exit_owner("paper_run_once_force_close") == (
        "unclassified_exit_owner"
    )


def test_normalize_exit_reason_value_returns_none_on_exploding_str():
    assert _normalize_exit_reason_value(_ExplodingString()) is None


def test_resolve_close_reason_has_deterministic_non_unknown_fallback():
    resolved = _resolve_close_reason_with_owner(
        payload_exit_reason=None,
        close_execute_reason=None,
        execute_call_reason=None,
        candidate_reason=None,
        weak_peak_reason=None,
        source_branch="position_close_request",
    )

    assert resolved["exit_reason"] == "close_reason_unclassified"
    assert resolved["reason_source"] == "deterministic_fallback_unclassified"
    assert resolved["exit_owner"] == "manual_close_request"
