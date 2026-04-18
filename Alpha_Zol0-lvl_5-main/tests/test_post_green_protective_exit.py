from datetime import datetime, timedelta, timezone

import pytest

from core.BotCore import (
    _build_post_green_close_contract_fields,
    _build_post_green_protective_exit_skipped_telemetry,
    _paper_momentum_mixed_expected_edge_after_execution_gate,
    _paper_momentum_mixed_never_green_filter,
    _paper_post_green_protective_exit_decision,
    _paper_post_green_protective_terminal_outcome_marker,
    _paper_trend_mixed_edge_over_fee_gate,
    _paper_weak_peak_decay_decision,
    _resolve_close_reason_with_owner,
    _select_layered_exit_candidate,
    _should_post_green_hold_guard_bypass,
)


def test_post_green_protective_exit_triggers_for_kucoin_paper_trade():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0100,
        "peak_mfe_ts": (now_dt - timedelta(seconds=45)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=0.0030,
        pos_age_sec=90.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["post_green_peak_mfe"] == 0.0100
    assert metrics["post_green_time_since_peak_sec"] == 45.0
    assert metrics["post_green_giveback_ratio"] == 0.7
    assert metrics["post_green_peak_capture_ratio"] == 0.3
    assert metrics["post_green_time_until_hard_close_sec"] is None
    assert metrics["post_green_hard_close_window_sec"] is None
    assert metrics["post_green_hard_close_imminent"] is False
    assert metrics["post_green_exit_reason"] == "post_green_protective_exit"
    assert metrics["post_green_trigger_mode"] == "peak_giveback_positive_residual"
    assert metrics["post_green_trigger_reason_detail"] == "positive_residual_giveback"
    assert metrics["post_green_trigger_giveback_threshold"] == 0.06
    assert (
        metrics["post_green_trigger_residual_floor_mode"]
        == "absolute_negative_epsilon"
    )
    assert metrics["post_green_trigger_residual_floor_value"] == 0.003
    assert metrics["post_green_trigger_time_since_peak_sec"] == 45.0
    assert metrics["post_green_trigger_giveback_ratio"] == 0.7
    assert metrics["post_green_trigger_residual_edge"] == 0.0030
    assert metrics["post_green_trigger_soft_floor_passed"] is True
    assert metrics["post_green_trigger_soft_floor_blocked"] is False
    assert metrics["post_green_trigger_blocked_negative_residual"] is False


def test_post_green_protective_exit_skips_never_green_trade():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0,
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=position,
        current_net_after_fee=-0.0020,
        pos_age_sec=120.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "never_green"
    assert metrics["post_green_peak_mfe"] == 0.0
    assert metrics["post_green_giveback_ratio"] is None
    assert metrics["post_green_attempt_seq"] == 1
    assert metrics["post_green_branch_seq"] == "skip:never_green"


def test_post_green_protective_exit_skips_when_peak_is_too_recent():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "SOLUSDTM",
        "mfe": 0.0080,
        "peak_mfe_ts": (now_dt - timedelta(seconds=4)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="SOLUSDTM",
        position=position,
        current_net_after_fee=0.0020,
        pos_age_sec=30.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "peak_too_recent"
    assert metrics["post_green_peak_mfe"] == 0.0080
    assert metrics["post_green_time_since_peak_sec"] == 4.0
    assert metrics["post_green_giveback_ratio"] == 0.75


def test_post_green_protective_exit_allows_small_negative_residual_via_soft_floor():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0020,
        "peak_mfe_ts": (now_dt - timedelta(seconds=25)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0010,
        pos_age_sec=120.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["post_green_trigger_mode"] == "peak_giveback_soft_residual_floor"
    assert (
        metrics["post_green_trigger_residual_floor_mode"]
        == "absolute_negative_epsilon"
    )
    assert metrics["post_green_trigger_residual_floor_value"] == 0.003
    assert metrics["post_green_trigger_residual_edge"] == -0.0010
    assert metrics["post_green_trigger_soft_floor_passed"] is True
    assert metrics["post_green_trigger_soft_floor_blocked"] is False
    assert metrics["post_green_trigger_blocked_negative_residual"] is False
    assert metrics["post_green_rescue_refine_candidate"] is False


def test_post_green_protective_exit_blocks_below_soft_residual_floor():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0080,
        "peak_mfe_ts": (now_dt - timedelta(seconds=25)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0040,
        pos_age_sec=120.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "blocked_negative_residual"
    assert metrics["post_green_peak_mfe"] == 0.0080
    assert metrics["post_green_time_since_peak_sec"] == 25.0
    assert metrics["post_green_giveback_ratio"] == 1.5
    assert metrics["post_green_trigger_mode"] is None
    assert (
        metrics["post_green_trigger_residual_floor_mode"]
        == "absolute_negative_epsilon"
    )
    assert metrics["post_green_trigger_residual_floor_value"] == 0.003
    assert metrics["post_green_trigger_residual_edge"] == -0.0040
    assert metrics["post_green_trigger_soft_floor_passed"] is False
    assert metrics["post_green_trigger_soft_floor_blocked"] is True
    assert metrics["post_green_trigger_blocked_negative_residual"] is True


def test_post_green_protective_exit_triggers_earlier_on_positive_residual_giveback():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0080,
        "peak_mfe_ts": (now_dt - timedelta(seconds=12)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=0.0050,
        pos_age_sec=120.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["post_green_time_since_peak_sec"] == 12.0
    assert metrics["post_green_giveback_ratio"] == 0.375
    assert metrics["post_green_trigger_mode"] == "peak_giveback_positive_residual"
    assert metrics["post_green_trigger_reason_detail"] == "positive_residual_giveback"
    assert metrics["post_green_trigger_giveback_threshold"] == 0.06
    assert metrics["post_green_trigger_residual_edge"] == 0.0050


def test_post_green_protective_exit_triggers_at_lower_paper_giveback_trigger(
    monkeypatch,
):
    monkeypatch.setenv("PAPER_POST_GREEN_GIVEBACK_TRIGGER", "0.06")

    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0100,
        "peak_mfe_ts": (now_dt - timedelta(seconds=12)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=0.0093,
        pos_age_sec=90.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["post_green_time_since_peak_sec"] == 12.0
    assert abs(metrics["post_green_giveback_ratio"] - 0.07) < 1e-12
    assert metrics["post_green_trigger_giveback_threshold"] == 0.06
    assert metrics["post_green_trigger_mode"] == "peak_giveback_positive_residual"
    assert metrics["post_green_trigger_reason_detail"] == "positive_residual_giveback"


def test_post_green_protective_exit_triggers_in_hard_window_positive_giveback():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0100,
        "peak_mfe_ts": (now_dt - timedelta(seconds=20)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=position,
        current_net_after_fee=0.0090,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["post_green_time_until_hard_close_sec"] == 10.0
    assert metrics["post_green_hard_close_window_sec"] == 20.0
    assert metrics["post_green_hard_close_imminent"] is True
    assert abs(metrics["post_green_giveback_ratio"] - 0.1) < 1e-12
    assert metrics["post_green_trigger_giveback_threshold"] == 0.05
    assert (
        metrics["post_green_trigger_mode"]
        == "peak_giveback_positive_residual_hard_window"
    )
    assert (
        metrics["post_green_trigger_reason_detail"]
        == "positive_residual_hard_close_window"
    )


def test_post_green_protective_exit_triggers_positive_residual_tight_quality():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0100,
        "peak_mfe_ts": (now_dt - timedelta(seconds=18)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=position,
        current_net_after_fee=0.0089,
        pos_age_sec=80.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert abs(metrics["post_green_giveback_ratio"] - 0.11) < 1e-12
    assert metrics["post_green_trigger_giveback_threshold"] == 0.06
    assert metrics["post_green_trigger_mode"] == "peak_giveback_positive_residual"


def test_post_green_protective_exit_refines_near_breakeven_rescue_for_ratio_ge_one():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0032,
        "peak_mfe_ts": (now_dt - timedelta(seconds=20)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=position,
        current_net_after_fee=-0.0012,
        pos_age_sec=120.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "rescue_refine_hold"
    assert metrics["post_green_rescue_refine_candidate"] is True
    assert metrics["post_green_rescue_refine_triggered"] is True
    assert metrics["post_green_rescue_refine_skipped"] is False
    assert metrics["post_green_rescue_ratio_band"] == "ge_1.0"
    assert metrics["post_green_rescue_burden_equivalent"] == 0.003
    assert metrics["post_green_rescue_peak_mfe"] == 0.0032
    assert metrics["post_green_rescue_time_since_peak_sec"] == 20.0
    assert metrics["post_green_rescue_giveback_ratio"] == 1.375
    assert metrics["post_green_rescue_exit_reason"] == "post_green_rescue_refine_hold"


def test_post_green_protective_exit_extends_rescue_window_for_meaningful_green_trade():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0036,
        "peak_mfe_ts": (now_dt - timedelta(seconds=40)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0029,
        pos_age_sec=140.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "rescue_refine_hold"
    assert metrics["post_green_rescue_refine_candidate"] is True
    assert metrics["post_green_rescue_refine_triggered"] is True
    assert metrics["post_green_rescue_refine_skipped"] is False
    assert metrics["post_green_rescue_exit_reason"] == "post_green_rescue_refine_hold"


def test_post_green_protective_exit_keeps_sol_on_existing_path():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "SOLUSDTM",
        "mfe": 0.0032,
        "peak_mfe_ts": (now_dt - timedelta(seconds=20)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="SOLUSDTM",
        position=position,
        current_net_after_fee=-0.0012,
        pos_age_sec=120.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["post_green_trigger_mode"] == "peak_giveback_soft_residual_floor"
    assert metrics["post_green_rescue_refine_candidate"] is False
    assert metrics["post_green_rescue_refine_triggered"] is False
    assert metrics["post_green_rescue_refine_skipped"] is False
    assert metrics["post_green_rescue_ratio_band"] == "ge_1.0"
    assert metrics["post_green_rescue_exit_reason"] == "post_green_protective_exit"


def test_post_green_protective_exit_blocks_late_soft_floor_quality_failure():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0033,
        "peak_mfe_ts": (now_dt - timedelta(seconds=60)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0016,
        pos_age_sec=150.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "quality_filter_blocked"
    assert metrics["post_green_quality_filter_candidate"] is True
    assert metrics["post_green_quality_filter_passed"] is False
    assert metrics["post_green_quality_filter_blocked"] is True
    assert (
        metrics["post_green_quality_filter_reason"]
        == "late_after_peak_and_excessive_giveback"
    )
    assert metrics["post_green_quality_filter_peak_mfe"] == 0.0033
    assert metrics["post_green_quality_filter_residual_edge"] == -0.0016
    assert (
        abs(metrics["post_green_quality_filter_giveback_ratio"] - 1.4848484848484849)
        < 1e-12
    )
    assert metrics["post_green_quality_filter_time_since_peak_sec"] == 60.0
    assert metrics["post_green_skip_reason"] == "quality_filter_blocked"


def test_post_green_protective_exit_hard_window_override_triggers_when_late():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0060,
        "peak_mfe_ts": (now_dt - timedelta(seconds=60)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0045,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["post_green_hard_close_imminent"] is True
    assert metrics["post_green_trigger_hard_window_soft_floor_override"] is True
    assert metrics["post_green_quality_filter_hard_window_override"] is True
    assert metrics["post_green_quality_filter_passed"] is True
    assert metrics["post_green_quality_filter_blocked"] is False
    assert metrics["post_green_quality_filter_reason"] == "hard_window_override"
    assert (
        metrics["post_green_trigger_mode"]
        == "peak_giveback_soft_residual_floor_hard_window_override"
    )
    assert metrics["post_green_trigger_mode"] != "micro_mfe_forced_exit"
    assert metrics["post_green_skip_reason"] is None


def test_post_green_protective_exit_blocks_hard_window_override_on_negative_residual():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0022,
        "peak_mfe_ts": (now_dt - timedelta(seconds=8)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0018,
        pos_age_sec=95.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=100.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "quality_filter_blocked"
    assert metrics["post_green_quality_filter_candidate"] is True
    assert metrics["post_green_quality_filter_hard_window_override"] is True
    assert metrics["post_green_quality_filter_blocked"] is True
    assert (
        metrics["post_green_quality_filter_reason"]
        == "hard_window_override_blocked_weak_peak_to_burden"
    )
    assert metrics["post_green_skip_reason"] == "quality_filter_blocked"


def test_post_green_protective_exit_blocks_late_weak_candidate():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0025,
        "peak_mfe_ts": (now_dt - timedelta(seconds=60)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0018,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "quality_filter_blocked"
    assert metrics["post_green_quality_filter_candidate"] is True
    assert metrics["post_green_quality_filter_hard_window_override"] is True
    assert metrics["post_green_quality_filter_blocked"] is True
    assert metrics["post_green_quality_filter_time_since_peak_sec"] == 60.0
    assert (
        metrics["post_green_quality_filter_reason"]
        == "hard_window_override_blocked_weak_peak_to_burden"
    )
    assert metrics["post_green_skip_reason"] == "quality_filter_blocked"


def test_post_green_protective_exit_keeps_executor_bypass_armed():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0060,
        "peak_mfe_ts": (now_dt - timedelta(seconds=60)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0045,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["post_green_quality_filter_hard_window_override"] is True
    assert metrics["post_green_quality_filter_blocked"] is False
    assert metrics["post_green_quality_filter_reason"] == "hard_window_override"
    assert _should_post_green_hold_guard_bypass(
        exit_reason=metrics["post_green_exit_reason"],
        post_green_metrics=metrics,
        current_net_after_fee=-0.0045,
        post_green_trigger_seen=True,
    )


def test_post_green_weak_negative_hard_window_no_old_override_branch():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0006,
        "peak_mfe_ts": (now_dt - timedelta(seconds=60)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0027,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert metrics["post_green_hard_close_imminent"] is True
    assert metrics["post_green_trigger_hard_window_soft_floor_override"] is False
    assert (
        metrics["post_green_trigger_mode"]
        != "peak_giveback_soft_residual_floor_hard_window_override"
    )
    assert should_trigger is False
    assert skip_reason == "quality_filter_blocked"
    assert metrics["post_green_trigger_mode"] is None
    assert metrics["post_green_quality_filter_blocked"] is True
    assert metrics["post_green_quality_filter_reason"] == (
        "hard_window_override_blocked_weak_peak_to_burden"
    )


def test_post_green_protective_exit_triggers_earlier_bnr_time_forced_exit():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0008,
        "peak_mfe_ts": (now_dt - timedelta(seconds=10.0)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0048,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "bnr_time_forced_exit"
    assert metrics["post_green_trigger_mode"] == "bnr_time_forced_exit"
    assert metrics["post_green_attempt_seq"] == 1
    assert metrics["post_green_branch_seq"] == "bnr_time_forced_exit"
    assert metrics["post_green_bnr_time_forced_exit_sec"] == 1.0
    assert metrics["post_green_peak_to_burden_ratio"] is not None
    assert metrics["post_green_peak_to_burden_ratio"] < 1.0
    assert metrics["post_green_time_since_peak_sec"] == 10.0
    assert metrics["post_green_trigger_reason_detail"] == "bnr_time_forced_exit"
    assert metrics["post_green_rescue_exit_reason"] == "post_green_protective_exit"
    assert metrics["post_green_exit_reason"] == "post_green_protective_exit"


def test_post_green_protective_exit_bnr_time_boundary_giveback_floor():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0008,
        "peak_mfe_ts": (now_dt - timedelta(seconds=10.0)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.003608,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "bnr_time_forced_exit"
    assert metrics["post_green_trigger_mode"] == "bnr_time_forced_exit"
    assert metrics["post_green_branch_seq"] == "bnr_time_forced_exit"
    assert metrics["post_green_bnr_time_forced_exit_sec"] == 1.0
    assert metrics["post_green_time_since_peak_sec"] == 10.0
    assert metrics["post_green_giveback_ratio"] == pytest.approx(5.51, abs=1e-12)
    assert metrics["post_green_trigger_reason_detail"] == "bnr_time_forced_exit"


def test_post_green_protective_exit_bnr_time_triggers_before_old_shared_hold_floor():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    paper_auto_close_sec = 10.0
    old_peak_hold_floor_sec = max(4.0, min(8.0, paper_auto_close_sec * 0.4))
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0008,
        "peak_mfe_ts": (now_dt - timedelta(seconds=2.0)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.003608,
        pos_age_sec=170.0,
        paper_auto_close_sec=paper_auto_close_sec,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert old_peak_hold_floor_sec == 4.0
    assert metrics["post_green_time_since_peak_sec"] == 2.0
    assert metrics["post_green_time_since_peak_sec"] < old_peak_hold_floor_sec
    assert metrics["post_green_time_since_peak_sec"] >= metrics[
        "post_green_bnr_time_forced_exit_sec"
    ]
    assert metrics["post_green_peak_to_burden_ratio"] is not None
    assert metrics["post_green_peak_to_burden_ratio"] < 1.0
    assert metrics["post_green_giveback_ratio"] == pytest.approx(5.51, abs=1e-12)
    assert should_trigger is True
    assert skip_reason == "bnr_time_forced_exit"
    assert metrics["post_green_trigger_mode"] == "bnr_time_forced_exit"
    assert metrics["post_green_branch_seq"] == "bnr_time_forced_exit"
    assert metrics["post_green_trigger_reason_detail"] == "bnr_time_forced_exit"


def test_post_green_protective_exit_bnr_time_no_trigger_before_floor():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0012,
        "peak_mfe_ts": (now_dt - timedelta(seconds=0.9)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0056,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "peak_too_recent"
    assert metrics["post_green_branch_seq"] == "skip:peak_too_recent"
    assert metrics["post_green_bnr_time_forced_exit_sec"] == 1.0
    assert metrics["post_green_time_since_peak_sec"] == 0.9


def test_post_green_skip_peak_too_recent_allows_auto_close_timer_takeover():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0012,
        "peak_mfe_ts": (now_dt - timedelta(seconds=0.9)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0011,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "peak_too_recent"
    assert metrics["post_green_branch_seq"] == "skip:peak_too_recent"
    assert metrics["post_green_trigger_mode"] is None

    selected, non_hard_exists = _select_layered_exit_candidate(
        [
            {
                "reason": "auto_close_hard",
                "expected_net_after_fee": -0.0011,
                "priority": 65,
            }
        ],
        hard_reason_names={"auto_close_hard", "auto_close_hard_near_zero"},
        prefer_non_hard=True,
    )

    assert non_hard_exists is False
    assert selected["reason"] == "auto_close_hard"

    marker = _paper_post_green_protective_terminal_outcome_marker(
        candidate_seen=True,
        skipped_seen=True,
        triggered_seen=False,
        final_exit_reason=selected["reason"],
        last_skip_reason=skip_reason,
        post_green_metrics=metrics,
    )

    assert marker["post_green_protective_terminal_outcome"] == "SKIPPED_ONLY"
    assert marker["post_green_protective_terminal_trigger_seen"] is False
    assert (
        marker["post_green_protective_terminal_last_skip_reason"]
        == "peak_too_recent"
    )
    assert marker["post_green_branch_seq"] == "skip:peak_too_recent"

    resolved = _resolve_close_reason_with_owner(
        payload_exit_reason=selected["reason"],
        close_execute_reason=None,
        execute_call_reason=None,
        candidate_reason="post_green_protective_exit",
        weak_peak_reason=None,
        source_branch="branch_auto_close",
    )
    owner_resolved_bucket = (
        "AUTO_CLOSE_TIMER_RED"
        if resolved["exit_reason"] == "auto_close_hard"
        and resolved["exit_owner"] == "time_based_exit"
        and marker["post_green_protective_terminal_outcome"] == "SKIPPED_ONLY"
        else "MIXED_OR_UNCLEAR"
    )

    assert resolved["exit_reason"] == "auto_close_hard"
    assert resolved["exit_owner"] == "time_based_exit"
    assert owner_resolved_bucket == "AUTO_CLOSE_TIMER_RED"


def test_post_green_skip_peak_too_recent_blocks_near_threshold_micro_and_bnr():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0005,
        "peak_mfe_ts": (now_dt - timedelta(seconds=0.9)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=position,
        current_net_after_fee=-0.0040,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "peak_too_recent"
    assert metrics["post_green_branch_seq"] == "skip:peak_too_recent"
    assert metrics["post_green_trigger_mode"] is None
    assert metrics["post_green_trigger_reason_detail"] is None
    assert metrics["post_green_peak_to_burden_ratio"] == pytest.approx(0.125, abs=1e-12)
    assert metrics["post_green_giveback_ratio"] == pytest.approx(9.0, abs=1e-12)
    assert metrics.get("post_green_micro_mfe_forced_exit") is not True
    assert metrics.get("post_green_bnr_time_forced_exit") is not True


def test_post_green_protective_exit_assigns_stable_attempt_and_branch_sequence():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0012,
        "peak_mfe_ts": (now_dt - timedelta(seconds=4)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    first_trigger, first_skip_reason, first_metrics = (
        _paper_post_green_protective_exit_decision(
            simulate=True,
            symbol="ETHUSDTM",
            position=position,
            current_net_after_fee=-0.0018,
            pos_age_sec=95.0,
            paper_auto_close_sec=10.0,
            paper_auto_close_hard_sec=100.0,
            now_dt=now_dt,
        )
    )

    assert first_trigger is False
    assert first_skip_reason == "peak_too_recent"
    assert first_metrics["post_green_attempt_seq"] == 1
    assert first_metrics["post_green_branch_seq"] == "skip:peak_too_recent"

    position["peak_mfe_ts"] = (now_dt - timedelta(seconds=45)).isoformat()
    position["mfe"] = 0.0008

    second_trigger, second_skip_reason, second_metrics = (
        _paper_post_green_protective_exit_decision(
            simulate=True,
            symbol="ETHUSDTM",
            position=position,
            current_net_after_fee=-0.0048,
            pos_age_sec=170.0,
            paper_auto_close_sec=10.0,
            paper_auto_close_hard_sec=180.0,
            now_dt=now_dt,
        )
    )

    assert second_trigger is True
    assert second_skip_reason == "bnr_time_forced_exit"
    assert second_metrics["post_green_attempt_seq"] == 2
    assert second_metrics["post_green_branch_seq"] == "bnr_time_forced_exit"
    assert position["post_green_attempt_seq"] == 2
    assert position["post_green_branch_seq"] == "bnr_time_forced_exit"


def test_post_green_skip_telemetry_carries_branch_identity():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0032,
        "peak_mfe_ts": (now_dt - timedelta(seconds=20)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0012,
        pos_age_sec=120.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "rescue_refine_hold"

    payload = _build_post_green_protective_exit_skipped_telemetry(
        timestamp=now_dt.isoformat(),
        symbol="ETHUSDTM",
        trade_id="trade-7",
        position_side="buy",
        post_green_metrics=metrics,
        current_expected_net_after_fee=-0.0012,
        skip_reason=skip_reason,
    )

    assert payload["post_green_attempt_seq"] == metrics["post_green_attempt_seq"]
    assert payload["post_green_branch_seq"] == metrics["post_green_branch_seq"]
    assert payload["post_green_peak_to_burden_ratio"] == metrics[
        "post_green_peak_to_burden_ratio"
    ]
    assert payload["post_green_bnr_time_forced_exit_sec"] == metrics[
        "post_green_bnr_time_forced_exit_sec"
    ]
    assert payload["post_green_rescue_exit_reason"] == "post_green_rescue_refine_hold"


def test_post_green_terminal_marker_and_close_contract_keep_bnr_fields():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0012,
        "peak_mfe_ts": (now_dt - timedelta(seconds=45)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0056,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "bnr_time_forced_exit"
    assert position["post_green_attempt_seq"] == metrics["post_green_attempt_seq"]
    assert position["post_green_branch_seq"] == metrics["post_green_branch_seq"]
    assert (
        position["post_green_peak_to_burden_ratio"]
        == metrics["post_green_peak_to_burden_ratio"]
    )
    assert position["post_green_bnr_time_forced_exit_sec"] == 1.0
    assert position["post_green_trigger_reason_detail"] == "bnr_time_forced_exit"
    assert position["post_green_rescue_exit_reason"] == "post_green_protective_exit"

    marker = _paper_post_green_protective_terminal_outcome_marker(
        candidate_seen=True,
        skipped_seen=True,
        triggered_seen=True,
        final_exit_reason="post_green_protective_exit",
        last_skip_reason="blocked_negative_residual",
        post_green_metrics=metrics,
    )

    assert marker["post_green_attempt_seq"] == metrics["post_green_attempt_seq"]
    assert marker["post_green_branch_seq"] == "bnr_time_forced_exit"
    assert marker["post_green_peak_to_burden_ratio"] == metrics[
        "post_green_peak_to_burden_ratio"
    ]
    assert marker["post_green_bnr_time_forced_exit_sec"] == 1.0
    assert marker["post_green_trigger_reason_detail"] == "bnr_time_forced_exit"
    assert marker["post_green_rescue_exit_reason"] == "post_green_protective_exit"


def test_post_green_close_contract_fields_join_bnr_candidate_trigger_close_chain():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0012,
        "peak_mfe_ts": (now_dt - timedelta(seconds=45)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0056,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "bnr_time_forced_exit"

    marker = _paper_post_green_protective_terminal_outcome_marker(
        candidate_seen=True,
        skipped_seen=False,
        triggered_seen=True,
        final_exit_reason="post_green_protective_exit",
        last_skip_reason=None,
        post_green_metrics=metrics,
    )
    payload = dict(position)
    payload.update(marker)
    close_fields = _build_post_green_close_contract_fields(
        payload,
        terminal_marker=marker,
    )

    assert close_fields["post_green_attempt_seq"] == metrics["post_green_attempt_seq"]
    assert close_fields["post_green_branch_seq"] == "bnr_time_forced_exit"
    assert close_fields["post_green_trigger_mode"] == "bnr_time_forced_exit"
    assert close_fields["post_green_trigger_reason_detail"] == "bnr_time_forced_exit"
    assert close_fields["post_green_peak_to_burden_ratio"] == metrics[
        "post_green_peak_to_burden_ratio"
    ]
    assert close_fields["post_green_bnr_time_forced_exit_sec"] == 1.0
    assert close_fields["post_green_protective_terminal_outcome"] == "TRIGGERED_ONLY"
    assert close_fields["post_green_peak_mfe"] == metrics["post_green_peak_mfe"]
    assert close_fields["post_green_time_since_peak_sec"] == metrics[
        "post_green_time_since_peak_sec"
    ]
    assert close_fields["post_green_giveback_ratio"] == metrics[
        "post_green_giveback_ratio"
    ]


def test_post_green_close_contract_fields_keep_terminal_and_close_consistent_for_skip():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0012,
        "peak_mfe_ts": (now_dt - timedelta(seconds=0.9)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0011,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "peak_too_recent"

    marker = _paper_post_green_protective_terminal_outcome_marker(
        candidate_seen=True,
        skipped_seen=True,
        triggered_seen=False,
        final_exit_reason="auto_close_hard",
        last_skip_reason=skip_reason,
        post_green_metrics=metrics,
    )
    payload = dict(position)
    payload.update(marker)
    close_fields = _build_post_green_close_contract_fields(
        payload,
        terminal_marker=marker,
    )

    assert close_fields["post_green_attempt_seq"] == metrics["post_green_attempt_seq"]
    assert close_fields["post_green_branch_seq"] == "skip:peak_too_recent"
    assert close_fields["post_green_skip_reason"] == "peak_too_recent"
    assert close_fields["post_green_trigger_mode"] is None
    assert close_fields["post_green_protective_terminal_last_skip_reason"] == (
        "peak_too_recent"
    )
    assert close_fields["post_green_protective_terminal_outcome"] == "SKIPPED_ONLY"


def test_post_green_micro_mfe_branch_remains_distinct_from_bnr():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    micro_position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0005,
        "peak_mfe_ts": (now_dt - timedelta(seconds=45)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }
    micro_trigger, micro_skip_reason, micro_metrics = (
        _paper_post_green_protective_exit_decision(
            simulate=True,
            symbol="ETHUSDTM",
            position=micro_position,
            current_net_after_fee=-0.0001,
            pos_age_sec=95.0,
            paper_auto_close_sec=10.0,
            now_dt=now_dt,
        )
    )

    assert micro_trigger is True
    assert micro_skip_reason == "micro_mfe_forced_exit"
    assert micro_metrics["post_green_attempt_seq"] == 1
    assert micro_metrics["post_green_branch_seq"] == "micro_mfe_forced_exit"
    assert micro_metrics["post_green_trigger_reason_detail"] == "micro_mfe_forced_exit"
    assert micro_metrics["post_green_peak_to_burden_ratio"] is not None
    assert micro_metrics["post_green_peak_to_burden_ratio"] <= 0.20
    assert micro_metrics["post_green_giveback_ratio"] <= 1.35
    assert micro_metrics["post_green_time_since_peak_sec"] == 45.0
    assert (
        micro_metrics["post_green_rescue_exit_reason"]
        == "post_green_protective_exit"
    )

    bnr_position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0008,
        "peak_mfe_ts": (now_dt - timedelta(seconds=45)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }
    bnr_trigger, bnr_skip_reason, bnr_metrics = (
        _paper_post_green_protective_exit_decision(
            simulate=True,
            symbol="ETHUSDTM",
            position=bnr_position,
            current_net_after_fee=-0.0048,
            pos_age_sec=170.0,
            paper_auto_close_sec=10.0,
            paper_auto_close_hard_sec=180.0,
            now_dt=now_dt,
        )
    )

    assert bnr_trigger is True
    assert bnr_skip_reason == "bnr_time_forced_exit"
    assert bnr_metrics["post_green_attempt_seq"] == 1
    assert bnr_metrics["post_green_branch_seq"] == "bnr_time_forced_exit"
    assert bnr_metrics["post_green_trigger_reason_detail"] == "bnr_time_forced_exit"
    assert bnr_metrics["post_green_rescue_exit_reason"] == "post_green_protective_exit"


def test_post_green_micro_mfe_cost_aware_kill_does_not_fire_above_quality_ceiling():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "SOLUSDTM",
        "mfe": 0.0005,
        "peak_mfe_ts": (now_dt - timedelta(seconds=45)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="SOLUSDTM",
        position=position,
        current_net_after_fee=-0.00025,
        pos_age_sec=95.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert metrics["post_green_giveback_ratio"] > 1.35
    assert skip_reason != "micro_mfe_forced_exit"
    assert metrics["post_green_trigger_mode"] != "micro_mfe_forced_exit"


def test_post_green_micro_mfe_cost_aware_kill_boundary_giveback_ratio_equal_ceiling():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "SOLUSDTM",
        "mfe": 0.0005,
        "peak_mfe_ts": (now_dt - timedelta(seconds=45)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="SOLUSDTM",
        position=position,
        current_net_after_fee=-0.000175,
        pos_age_sec=95.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "micro_mfe_forced_exit"
    assert metrics["post_green_trigger_mode"] == "micro_mfe_forced_exit"
    assert metrics["post_green_branch_seq"] == "micro_mfe_forced_exit"
    assert metrics["post_green_giveback_ratio"] == pytest.approx(1.35, abs=1e-12)
    assert metrics["post_green_peak_to_burden_ratio"] <= 0.20


def test_post_green_micro_mfe_cost_aware_kill_boundary_ratio_equal_micro_ceiling():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "SOLUSDTM",
        "mfe": 0.0006,
        "peak_mfe_ts": (now_dt - timedelta(seconds=45)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="SOLUSDTM",
        position=position,
        current_net_after_fee=-0.00018,
        pos_age_sec=95.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "micro_mfe_forced_exit"
    assert metrics["post_green_trigger_mode"] == "micro_mfe_forced_exit"
    assert metrics["post_green_branch_seq"] == "micro_mfe_forced_exit"
    assert metrics["post_green_peak_to_burden_ratio"] == pytest.approx(0.20, abs=1e-12)
    assert metrics["post_green_giveback_ratio"] == pytest.approx(1.3, abs=1e-12)


def test_post_green_micro_mfe_cost_aware_kill_does_not_fire_above_micro_ratio_ceiling():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "SOLUSDTM",
        "mfe": 0.00063,
        "peak_mfe_ts": (now_dt - timedelta(seconds=45)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="SOLUSDTM",
        position=position,
        current_net_after_fee=-0.00018,
        pos_age_sec=95.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["post_green_trigger_mode"] == "peak_giveback_soft_residual_floor"
    assert metrics["post_green_branch_seq"] == "peak_giveback_soft_residual_floor"
    assert metrics["post_green_trigger_reason_detail"] == "soft_residual_floor"
    assert metrics["post_green_peak_to_burden_ratio"] == pytest.approx(0.21, abs=1e-12)
    assert metrics["post_green_trigger_mode"] != "micro_mfe_forced_exit"


def test_post_green_micro_mfe_cost_aware_kill_waits_for_timing_floor():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "SOLUSDTM",
        "mfe": 0.0005,
        "peak_mfe_ts": (now_dt - timedelta(seconds=0.9)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="SOLUSDTM",
        position=position,
        current_net_after_fee=-0.0001,
        pos_age_sec=95.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "peak_too_recent"
    assert metrics["post_green_branch_seq"] == "skip:peak_too_recent"
    assert metrics["post_green_peak_to_burden_ratio"] < 1.0
    assert metrics["post_green_giveback_ratio"] <= 1.35
    assert metrics["post_green_time_since_peak_sec"] == 0.9


def test_post_green_micro_mfe_cost_aware_kill_boundary_ratio_equal_one():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "SOLUSDTM",
        "mfe": 0.003,
        "peak_mfe_ts": (now_dt - timedelta(seconds=45)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_post_green_protective_exit_decision(
        simulate=True,
        symbol="SOLUSDTM",
        position=position,
        current_net_after_fee=-0.003,
        pos_age_sec=95.0,
        paper_auto_close_sec=10.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "blocked_negative_residual"
    assert metrics["post_green_peak_to_burden_ratio"] == 1.0
    assert metrics["post_green_trigger_mode"] is None


def test_paper_weak_peak_decay_triggers_for_stale_peak_below_fee_floor():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0008,
        "peak_mfe_ts": (now_dt - timedelta(seconds=60)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=position,
        current_net_after_fee=-0.0048,
        fee_floor=0.0020,
        pos_age_sec=170.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["weak_peak_decay_candidate"] is True
    assert metrics["weak_peak_decay_triggered"] is True
    assert metrics["weak_peak_decay_reason"] == "weak_peak_stale_decay_hard_window"
    assert metrics["weak_peak_decay_peak_mfe"] == 0.0008
    assert metrics["weak_peak_decay_fee_floor"] == 0.0020
    assert metrics["weak_peak_decay_peak_fee_ratio"] == 0.4
    assert metrics["weak_peak_decay_time_since_peak_sec"] == 60.0
    assert metrics["weak_peak_decay_time_until_hard_close_sec"] == 10.0
    assert metrics["weak_peak_decay_hard_close_imminent"] is True
    assert metrics["weak_peak_decay_giveback_ratio"] == 7.0
    assert metrics["weak_peak_decay_current_net_after_fee"] == -0.0048
    assert metrics["weak_peak_decay_stale_after_peak_sec"] == 35.0


def test_post_green_terminal_outcome_marker_skipped_only():
    marker = _paper_post_green_protective_terminal_outcome_marker(
        candidate_seen=True,
        skipped_seen=True,
        triggered_seen=False,
        final_exit_reason="auto_close_hard",
        last_skip_reason="quality_filter_blocked",
    )

    assert marker["post_green_protective_terminal_outcome"] == "SKIPPED_ONLY"
    assert marker["post_green_protective_terminal_candidate_seen"] is True
    assert marker["post_green_protective_terminal_skip_seen"] is True
    assert marker["post_green_protective_terminal_trigger_seen"] is False
    assert (
        marker["post_green_protective_terminal_last_skip_reason"]
        == "quality_filter_blocked"
    )


def test_post_green_terminal_outcome_marker_skipped_and_triggered():
    marker = _paper_post_green_protective_terminal_outcome_marker(
        candidate_seen=True,
        skipped_seen=True,
        triggered_seen=True,
        final_exit_reason="post_green_protective_exit",
        last_skip_reason="rescue_refine_hold",
    )

    assert (
        marker["post_green_protective_terminal_outcome"]
        == "SKIPPED_AND_TRIGGERED"
    )
    assert marker["post_green_protective_terminal_candidate_seen"] is True
    assert marker["post_green_protective_terminal_skip_seen"] is True
    assert marker["post_green_protective_terminal_trigger_seen"] is True


def test_post_green_terminal_outcome_marker_final_reason_promotes_triggered_only():
    marker = _paper_post_green_protective_terminal_outcome_marker(
        candidate_seen=True,
        skipped_seen=False,
        triggered_seen=False,
        final_exit_reason="post_green_protective_exit",
        last_skip_reason=None,
    )

    assert marker["post_green_protective_terminal_outcome"] == "TRIGGERED_ONLY"
    assert marker["post_green_protective_terminal_candidate_seen"] is True
    assert marker["post_green_protective_terminal_skip_seen"] is False
    assert marker["post_green_protective_terminal_trigger_seen"] is True
    assert marker["post_green_protective_terminal_last_skip_reason"] is None


def test_paper_weak_peak_decay_skips_when_peak_clears_fee_floor():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "SOLUSDTM",
        "mfe": 0.0032,
        "peak_mfe_ts": (now_dt - timedelta(seconds=60)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="SOLUSDTM",
        position=position,
        current_net_after_fee=-0.0002,
        fee_floor=0.0025,
        pos_age_sec=150.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "peak_above_fee_floor"
    assert metrics["weak_peak_decay_candidate"] is False
    assert metrics["weak_peak_decay_triggered"] is False
    assert metrics["weak_peak_decay_peak_fee_ratio"] == 1.28
    assert metrics["weak_peak_decay_reason"] == "peak_above_fee_floor"


def test_paper_weak_peak_decay_hard_window_override_for_feefloor_peak():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0025,
        "peak_mfe_ts": (now_dt - timedelta(seconds=50)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=position,
        current_net_after_fee=-0.0008,
        fee_floor=0.0020,
        pos_age_sec=175.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["weak_peak_decay_candidate"] is True
    assert metrics["weak_peak_decay_triggered"] is True
    assert (
        metrics["weak_peak_decay_reason"]
        == "weak_peak_stale_decay_hard_window_feefloor_override"
    )
    assert metrics["weak_peak_decay_hard_close_imminent"] is True
    assert metrics["weak_peak_decay_peak_fee_ratio"] == 1.25
    assert abs(metrics["weak_peak_decay_giveback_ratio"] - 1.3199999999999998) < 1e-12


def test_paper_weak_peak_decay_skips_when_peak_is_too_weak_for_decay():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "ETHUSDTM",
        "mfe": 0.0003,
        "peak_mfe_ts": (now_dt - timedelta(seconds=60)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="ETHUSDTM",
        position=position,
        current_net_after_fee=-0.0020,
        fee_floor=0.0020,
        pos_age_sec=150.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=180.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "peak_too_weak_for_decay"
    assert metrics["weak_peak_decay_candidate"] is False
    assert metrics["weak_peak_decay_triggered"] is False
    assert metrics["weak_peak_decay_peak_fee_ratio"] == 0.15
    assert metrics["weak_peak_decay_min_peak_fee_ratio"] == 0.20
    assert metrics["weak_peak_decay_reason"] == "peak_too_weak_for_decay"


def test_paper_weak_peak_decay_rejects_early_invalid_inputs():
    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=False,
        symbol="BTCUSDTM",
        position={"symbol": "BTCUSDTM"},
        current_net_after_fee=-0.0001,
        fee_floor=0.0010,
        pos_age_sec=1.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=60.0,
        now_dt=datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc),
    )

    assert should_trigger is False
    assert skip_reason == "not_paper_simulation"
    assert metrics["weak_peak_decay_reason"] == "not_paper_simulation"

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=None,
        current_net_after_fee=-0.0001,
        fee_floor=0.0010,
        pos_age_sec=1.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=60.0,
        now_dt=datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc),
    )

    assert should_trigger is False
    assert skip_reason == "position_unavailable"
    assert metrics["weak_peak_decay_reason"] == "position_unavailable"

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position={
            "symbol": "BTCUSDTM",
            "mfe": 0.0020,
            "open_snapshot": {"source": "other_feed"},
        },
        current_net_after_fee=-0.0001,
        fee_floor=0.0010,
        pos_age_sec=1.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=60.0,
        now_dt=datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc),
    )

    assert should_trigger is False
    assert skip_reason == "not_kucoin_paper_symbol"
    assert metrics["weak_peak_decay_reason"] == "not_kucoin_paper_symbol"

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position={
            "symbol": "BTCUSDTM",
            "mfe": 0.0,
            "open_snapshot": {"source": "kucoin_futures_ticker"},
        },
        current_net_after_fee=-0.0001,
        fee_floor=0.0010,
        pos_age_sec=1.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=60.0,
        now_dt=datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc),
    )

    assert should_trigger is False
    assert skip_reason == "never_green"
    assert metrics["weak_peak_decay_reason"] == "never_green"


def test_paper_weak_peak_decay_rejects_invalid_net_and_fee_floor_inputs():
    base_position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0020,
        "peak_mfe_ts": datetime(2026, 4, 3, 11, 59, 0, tzinfo=timezone.utc).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=base_position,
        current_net_after_fee="not-a-number",
        fee_floor=0.0010,
        pos_age_sec=10.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=60.0,
        now_dt=datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc),
    )

    assert should_trigger is False
    assert skip_reason == "current_net_unavailable"
    assert metrics["weak_peak_decay_reason"] == "current_net_unavailable"

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=base_position,
        current_net_after_fee=0.0001,
        fee_floor=0.0010,
        pos_age_sec=10.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=60.0,
        now_dt=datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc),
    )

    assert should_trigger is False
    assert skip_reason == "current_net_nonnegative"
    assert metrics["weak_peak_decay_reason"] == "current_net_nonnegative"

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=base_position,
        current_net_after_fee=-0.0001,
        fee_floor="bad-floor",
        pos_age_sec=10.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=60.0,
        now_dt=datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc),
    )

    assert should_trigger is False
    assert skip_reason == "fee_floor_unavailable"
    assert metrics["weak_peak_decay_reason"] == "fee_floor_unavailable"


def test_paper_weak_peak_decay_rejects_missing_or_unparseable_peak_timestamp():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0030,
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position={**position, "peak_mfe_ts": ""},
        current_net_after_fee=-0.0002,
        fee_floor=0.0035,
        pos_age_sec=50.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=500.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "peak_timestamp_unavailable"
    assert metrics["weak_peak_decay_reason"] == "peak_timestamp_unavailable"

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position={**position, "peak_mfe_ts": "not-a-timestamp"},
        current_net_after_fee=-0.0002,
        fee_floor=0.0035,
        pos_age_sec=50.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=500.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "peak_timestamp_unavailable"
    assert metrics["weak_peak_decay_reason"] == "peak_timestamp_unavailable"

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position={
            **position,
            "peak_mfe_ts": (now_dt - timedelta(seconds=10)).isoformat(),
        },
        current_net_after_fee=-0.0002,
        fee_floor=0.0035,
        pos_age_sec=50.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=500.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "peak_not_stale"
    assert metrics["weak_peak_decay_reason"] == "peak_not_stale"


def test_paper_weak_peak_decay_handles_naive_datetimes_and_plain_decay():
    naive_peak_ts = datetime(2026, 4, 3, 11, 59, 0).isoformat()
    aware_peak_ts = datetime(2026, 4, 3, 11, 59, 0, tzinfo=timezone.utc).isoformat()
    position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0030,
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position={**position, "peak_mfe_ts": naive_peak_ts},
        current_net_after_fee=-0.0003,
        fee_floor=0.0035,
        pos_age_sec=400.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=1000.0,
        now_dt=None,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["weak_peak_decay_reason"] == "weak_peak_stale_decay"
    assert metrics["weak_peak_decay_candidate"] is True
    assert metrics["weak_peak_decay_triggered"] is True
    assert metrics["weak_peak_decay_time_since_peak_sec"] > 35.0

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position={**position, "peak_mfe_ts": aware_peak_ts},
        current_net_after_fee=-0.0003,
        fee_floor=0.0035,
        pos_age_sec=400.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=1000.0,
        now_dt=datetime(2026, 4, 3, 12, 0, 0),
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["weak_peak_decay_reason"] == "weak_peak_stale_decay"
    assert metrics["weak_peak_decay_candidate"] is True
    assert metrics["weak_peak_decay_triggered"] is True
    assert metrics["weak_peak_decay_time_since_peak_sec"] == 60.0


def test_paper_weak_peak_decay_uses_max_unrealized_pnl_when_mfe_missing():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "BTCUSDTM",
        "mfe": None,
        "max_unrealized_pnl": 0.0030,
        "peak_mfe_ts": (now_dt - timedelta(seconds=60)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=position,
        current_net_after_fee=-0.0003,
        fee_floor=0.0035,
        pos_age_sec=400.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=1000.0,
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["weak_peak_decay_peak_mfe"] == 0.0030
    assert metrics["weak_peak_decay_reason"] == "weak_peak_stale_decay"


def test_paper_weak_peak_decay_ignores_invalid_age_and_hard_window_inputs():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0030,
        "peak_mfe_ts": (now_dt - timedelta(seconds=60)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=position,
        current_net_after_fee=-0.0003,
        fee_floor=0.0035,
        pos_age_sec="bad-age",
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec="bad-hard",
        now_dt=now_dt,
    )

    assert should_trigger is True
    assert skip_reason == "triggered"
    assert metrics["weak_peak_decay_reason"] == "weak_peak_stale_decay"
    assert metrics["weak_peak_decay_time_until_hard_close_sec"] is None
    assert metrics["weak_peak_decay_hard_close_imminent"] is False


def test_paper_weak_peak_decay_blocks_when_giveback_is_below_trigger():
    now_dt = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    position = {
        "symbol": "BTCUSDTM",
        "mfe": 0.0030,
        "peak_mfe_ts": (now_dt - timedelta(seconds=60)).isoformat(),
        "open_snapshot": {"source": "kucoin_futures_ticker"},
    }

    should_trigger, skip_reason, metrics = _paper_weak_peak_decay_decision(
        simulate=True,
        symbol="BTCUSDTM",
        position=position,
        current_net_after_fee=-0.00005,
        fee_floor=0.0035,
        pos_age_sec=400.0,
        paper_auto_close_sec=10.0,
        paper_auto_close_hard_sec=1000.0,
        now_dt=now_dt,
    )

    assert should_trigger is False
    assert skip_reason == "giveback_below_trigger"
    assert metrics["weak_peak_decay_reason"] == "giveback_below_trigger"


def test_trend_mixed_edge_over_fee_gate_blocks_when_net_edge_is_below_margin():
    payload = _paper_trend_mixed_edge_over_fee_gate(
        simulate=True,
        symbol="BTCUSDTM",
        strategy_name="TrendFollowing",
        regime_name="mixed",
        entry_decision="buy",
        expected_edge_raw=0.0020,
        estimated_round_trip_fee=0.0023,
        expected_edge_net=-0.0003,
        edge_safety_margin=0.0002,
    )

    assert payload["trend_mixed_edge_over_fee_candidate"] is True
    assert payload["trend_mixed_edge_over_fee_blocked"] is True
    assert payload["trend_mixed_edge_over_fee_allowed"] is False
    assert payload["trend_mixed_expected_edge_raw"] == 0.0020
    assert payload["trend_mixed_estimated_round_trip_fee"] == 0.0023
    assert payload["trend_mixed_expected_edge_net"] == -0.0003
    assert payload["trend_mixed_edge_safety_margin"] == 0.0002
    assert (
        payload["trend_mixed_block_reason"]
        == "expected_edge_net_below_or_equal_margin"
    )


def test_trend_mixed_edge_over_fee_gate_allows_when_net_edge_clears_margin():
    payload = _paper_trend_mixed_edge_over_fee_gate(
        simulate=True,
        symbol="ETHUSDTM",
        strategy_name="TrendFollowing",
        regime_name="mixed",
        entry_decision="sell",
        expected_edge_raw=0.0060,
        estimated_round_trip_fee=0.0035,
        expected_edge_net=0.0025,
        edge_safety_margin=0.0002,
    )

    assert payload["trend_mixed_edge_over_fee_candidate"] is True
    assert payload["trend_mixed_edge_over_fee_blocked"] is False
    assert payload["trend_mixed_edge_over_fee_allowed"] is True
    assert payload["trend_mixed_block_reason"] is None


def test_trend_mixed_edge_over_fee_gate_is_bucket_scoped_only():
    payload = _paper_trend_mixed_edge_over_fee_gate(
        simulate=True,
        symbol="ETHUSDTM",
        strategy_name="Momentum",
        regime_name="mixed",
        entry_decision="buy",
        expected_edge_raw=0.0010,
        estimated_round_trip_fee=0.0008,
        expected_edge_net=0.0002,
        edge_safety_margin=0.0001,
    )

    assert payload["trend_mixed_edge_over_fee_candidate"] is False
    assert payload["trend_mixed_edge_over_fee_blocked"] is False
    assert payload["trend_mixed_edge_over_fee_allowed"] is False
    assert payload["trend_mixed_block_reason"] is None


def test_momentum_mixed_expected_edge_after_execution_gate_blocks_when_below_margin():
    payload = _paper_momentum_mixed_expected_edge_after_execution_gate(
        simulate=True,
        symbol="BTCUSDTM",
        strategy_name="Momentum",
        regime_name="mixed",
        entry_decision="buy",
        history_ready=True,
        expected_edge_raw=0.0020,
        estimated_round_trip_fee=0.0023,
        expected_edge_after_execution=-0.0003,
        edge_safety_margin=0.0002,
    )

    assert payload["momentum_mixed_expected_edge_after_execution_candidate"] is True
    assert payload["momentum_mixed_expected_edge_after_execution_blocked"] is True
    assert payload["momentum_mixed_expected_edge_after_execution_allowed"] is False
    assert payload["momentum_mixed_expected_edge_raw"] == 0.0020
    assert payload["momentum_mixed_estimated_round_trip_fee"] == 0.0023
    assert payload["momentum_mixed_expected_edge_after_execution"] == -0.0003
    assert payload["momentum_mixed_edge_safety_margin"] == 0.0002
    assert (
        payload["momentum_mixed_block_reason"]
        == "expected_edge_after_execution_below_or_equal_margin"
    )


def test_momentum_mixed_expected_edge_after_execution_gate_allows_when_above_margin():
    payload = _paper_momentum_mixed_expected_edge_after_execution_gate(
        simulate=True,
        symbol="ETHUSDTM",
        strategy_name="Momentum",
        regime_name="mixed",
        entry_decision="sell",
        history_ready=True,
        expected_edge_raw=0.0060,
        estimated_round_trip_fee=0.0035,
        expected_edge_after_execution=0.0025,
        edge_safety_margin=0.0002,
    )

    assert payload["momentum_mixed_expected_edge_after_execution_candidate"] is True
    assert payload["momentum_mixed_expected_edge_after_execution_blocked"] is False
    assert payload["momentum_mixed_expected_edge_after_execution_allowed"] is True
    assert payload["momentum_mixed_block_reason"] is None


def test_momentum_mixed_gate_fail_open_on_missing_history():
    payload = _paper_momentum_mixed_expected_edge_after_execution_gate(
        simulate=True,
        symbol="ETHUSDTM",
        strategy_name="Momentum",
        regime_name="mixed",
        entry_decision="buy",
        history_ready=False,
        expected_edge_raw=None,
        estimated_round_trip_fee=None,
        expected_edge_after_execution=None,
        edge_safety_margin=0.0002,
    )

    assert payload["momentum_mixed_expected_edge_after_execution_candidate"] is True
    assert payload["momentum_mixed_expected_edge_after_execution_blocked"] is False
    assert payload["momentum_mixed_expected_edge_after_execution_allowed"] is True
    assert payload["momentum_mixed_block_reason"] == "insufficient_history_fail_open"


def test_momentum_mixed_expected_edge_after_execution_gate_is_bucket_scoped_only():
    payload = _paper_momentum_mixed_expected_edge_after_execution_gate(
        simulate=True,
        symbol="ETHUSDTM",
        strategy_name="TrendFollowing",
        regime_name="mixed",
        entry_decision="buy",
        history_ready=True,
        expected_edge_raw=0.0010,
        estimated_round_trip_fee=0.0008,
        expected_edge_after_execution=0.0002,
        edge_safety_margin=0.0001,
    )

    assert payload["momentum_mixed_expected_edge_after_execution_candidate"] is False
    assert payload["momentum_mixed_expected_edge_after_execution_blocked"] is False
    assert payload["momentum_mixed_expected_edge_after_execution_allowed"] is False
    assert payload["momentum_mixed_block_reason"] is None


def test_momentum_mixed_never_green_filter_blocks_weak_raw_edge():
    payload = _paper_momentum_mixed_never_green_filter(
        simulate=True,
        symbol="BTCUSDTM",
        strategy_name="Momentum",
        regime_name="mixed",
        entry_decision="buy",
        history_ready=True,
        expected_edge_raw=0.0031,
        estimated_round_trip_fee=0.0026,
        expected_edge_after_execution=0.0003,
        edge_safety_margin=0.0002,
        hard_floor_usdt=0.0006,
    )

    assert payload["momentum_mixed_never_green_filter_candidate"] is True
    assert payload["momentum_mixed_never_green_filter_blocked"] is True
    assert payload["momentum_mixed_never_green_filter_allowed"] is False
    assert payload["momentum_mixed_expected_edge_raw"] == 0.0031
    assert payload["momentum_mixed_estimated_round_trip_fee"] == 0.0026
    assert payload["momentum_mixed_expected_edge_after_execution"] == 0.0003
    assert payload["momentum_mixed_never_green_hard_floor_usdt"] == 0.0006
    assert (
        payload["momentum_mixed_never_green_filter_block_reason"]
        == "weak_raw_edge_confidence_after_execution_pass"
    )


def test_momentum_mixed_never_green_filter_allows_strong_raw_edge():
    payload = _paper_momentum_mixed_never_green_filter(
        simulate=True,
        symbol="ETHUSDTM",
        strategy_name="Momentum",
        regime_name="mixed",
        entry_decision="sell",
        history_ready=True,
        expected_edge_raw=0.0042,
        estimated_round_trip_fee=0.0026,
        expected_edge_after_execution=0.0004,
        edge_safety_margin=0.0002,
        hard_floor_usdt=0.0006,
    )

    assert payload["momentum_mixed_never_green_filter_candidate"] is True
    assert payload["momentum_mixed_never_green_filter_blocked"] is False
    assert payload["momentum_mixed_never_green_filter_allowed"] is True
    assert payload["momentum_mixed_never_green_filter_block_reason"] is None


def test_momentum_mixed_never_green_filter_fail_open_on_missing_history():
    payload = _paper_momentum_mixed_never_green_filter(
        simulate=True,
        symbol="ETHUSDTM",
        strategy_name="Momentum",
        regime_name="mixed",
        entry_decision="buy",
        history_ready=False,
        expected_edge_raw=None,
        estimated_round_trip_fee=None,
        expected_edge_after_execution=None,
        edge_safety_margin=0.0002,
        hard_floor_usdt=0.0006,
    )

    assert payload["momentum_mixed_never_green_filter_candidate"] is True
    assert payload["momentum_mixed_never_green_filter_blocked"] is False
    assert payload["momentum_mixed_never_green_filter_allowed"] is True
    assert (
        payload["momentum_mixed_never_green_filter_block_reason"]
        == "insufficient_history_fail_open"
    )


def test_momentum_mixed_never_green_filter_is_bucket_scoped_only():
    payload = _paper_momentum_mixed_never_green_filter(
        simulate=True,
        symbol="ETHUSDTM",
        strategy_name="TrendFollowing",
        regime_name="mixed",
        entry_decision="buy",
        history_ready=True,
        expected_edge_raw=0.0031,
        estimated_round_trip_fee=0.0026,
        expected_edge_after_execution=0.0004,
        edge_safety_margin=0.0002,
        hard_floor_usdt=0.0006,
    )

    assert payload["momentum_mixed_never_green_filter_candidate"] is False
    assert payload["momentum_mixed_never_green_filter_blocked"] is False
    assert payload["momentum_mixed_never_green_filter_allowed"] is False
    assert payload["momentum_mixed_never_green_filter_block_reason"] is None
