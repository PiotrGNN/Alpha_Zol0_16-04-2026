import pytest

from core.runtime_v2.contracts import QuoteTick
from core.runtime_v2.immediate_adverse_shadow import ImmediateAdverseShadowTracker


def _quote(mid: float) -> QuoteTick:
    return QuoteTick(
        symbol="SOLUSDTM",
        ts_ms=1,
        bid=mid - 0.01,
        ask=mid + 0.01,
        mid=mid,
        spread_abs=0.02,
        spread_bps=(0.02 / mid) * 10000.0,
        best_bid_size=10.0,
        best_ask_size=10.0,
        raw={},
    )


def test_shadow_tracker_classifies_blocked_candidate_as_missed_winner():
    tracker = ImmediateAdverseShadowTracker()
    tracker.add_blocked_candidate(
        symbol="SOLUSDTM",
        side="buy",
        strategy="TrendFollowingV2",
        opened_ts=100.0,
        entry_price=100.0,
        quantity_base=1.0,
        fee_rate=0.0,
        take_profit_net_usdt=0.05,
        stop_loss_net_usdt=0.10,
        max_hold_sec=20.0,
        guard_fields={"expected_net": 0.12},
    )

    terminal = tracker.observe_quotes({"SOLUSDTM": _quote(100.08)}, now_ts=104.0)

    assert len(terminal) == 1
    payload = terminal[0]
    assert payload["shadow_outcome_classification"] == "MISSED_WINNER"
    assert payload["shadow_exit_reason"] == "take_profit_net"
    assert payload["mfe_unrealized_net"] == pytest.approx(0.08)
    assert payload["realized_proxy_net"] == pytest.approx(0.08)
    assert tracker.active_count == 0


def test_shadow_tracker_classifies_blocked_candidate_as_immediate_adverse_loss():
    tracker = ImmediateAdverseShadowTracker()
    tracker.add_blocked_candidate(
        symbol="SOLUSDTM",
        side="sell",
        strategy="TrendFollowingV2",
        opened_ts=100.0,
        entry_price=100.0,
        quantity_base=1.0,
        fee_rate=0.0,
        take_profit_net_usdt=0.05,
        stop_loss_net_usdt=0.10,
        max_hold_sec=20.0,
        guard_fields={"expected_net": 0.12},
    )

    terminal = tracker.observe_quotes({"SOLUSDTM": _quote(100.11)}, now_ts=104.0)

    assert len(terminal) == 1
    payload = terminal[0]
    assert payload["shadow_outcome_classification"] == "IMMEDIATE_ADVERSE_LOSS"
    assert payload["shadow_exit_reason"] == "protective_exit"
    assert payload["mfe_unrealized_net"] == pytest.approx(-0.11)
    assert payload["mae_unrealized_net"] == pytest.approx(-0.11)
    assert payload["realized_proxy_net"] == pytest.approx(-0.11)


def test_shadow_tracker_flushes_unresolved_candidate_at_shutdown_once():
    tracker = ImmediateAdverseShadowTracker()
    shadow_id = tracker.add_blocked_candidate(
        symbol="SOLUSDTM",
        side="buy",
        strategy="TrendFollowingV2",
        opened_ts=100.0,
        entry_price=100.0,
        quantity_base=1.0,
        fee_rate=0.0,
        take_profit_net_usdt=0.50,
        stop_loss_net_usdt=0.50,
        max_hold_sec=20.0,
        guard_fields={"expected_net": 0.12},
    )
    assert tracker.observe_quotes({"SOLUSDTM": _quote(100.01)}, now_ts=104.0) == []

    terminal = tracker.flush_expired(
        {"SOLUSDTM": _quote(100.02)},
        now_ts=105.0,
        shutdown=True,
    )
    duplicate = tracker.flush_expired(
        {"SOLUSDTM": _quote(100.03)},
        now_ts=106.0,
        shutdown=True,
    )

    assert len(terminal) == 1
    payload = terminal[0]
    assert payload["candidate_id"] == shadow_id
    assert payload["terminal_classification"] == "SHADOW_OPEN_AT_SHUTDOWN"
    assert payload["shadow_outcome_classification"] == "SHADOW_OPEN_AT_SHUTDOWN"
    assert payload["final_shadow_ts"] == pytest.approx(105.0)
    assert payload["shadow_duration_sec"] == pytest.approx(5.0)
    assert payload["last_observed_price"] == pytest.approx(100.02)
    assert payload["max_favorable_net_proxy"] == pytest.approx(0.02)
    assert payload["max_adverse_net_proxy"] == pytest.approx(0.01)
    assert payload["proxy_net_result"] == pytest.approx(0.02)
    assert payload["trajectory_coverage"] == pytest.approx(5.0 / 20.0)
    assert payload["quote_sample_count"] == 2
    assert payload["reason_detail"] == "shutdown_unresolved"
    assert tracker.active_count == 0
    assert duplicate == []


def test_shadow_tracker_flushes_expired_candidate_without_terminal_move():
    tracker = ImmediateAdverseShadowTracker()
    tracker.add_blocked_candidate(
        symbol="SOLUSDTM",
        side="buy",
        strategy="TrendFollowingV2",
        opened_ts=100.0,
        entry_price=100.0,
        quantity_base=1.0,
        fee_rate=0.0,
        take_profit_net_usdt=0.50,
        stop_loss_net_usdt=0.50,
        max_hold_sec=5.0,
        guard_fields={"expected_net": 0.12},
    )
    assert tracker.observe_quotes({"SOLUSDTM": _quote(100.01)}, now_ts=102.0) == []

    terminal = tracker.flush_expired({}, now_ts=106.0)

    assert len(terminal) == 1
    payload = terminal[0]
    assert payload["terminal_classification"] == "SHADOW_EXPIRED_NO_TERMINAL_MOVE"
    assert payload["shadow_exit_reason"] == "shadow_expired_no_terminal_move"
    assert payload["quote_sample_count"] == 1
    assert tracker.active_count == 0


def test_shadow_tracker_flushes_insufficient_quotes_candidate():
    tracker = ImmediateAdverseShadowTracker()
    tracker.add_blocked_candidate(
        symbol="SOLUSDTM",
        side="buy",
        strategy="TrendFollowingV2",
        opened_ts=100.0,
        entry_price=100.0,
        quantity_base=1.0,
        fee_rate=0.0,
        take_profit_net_usdt=0.50,
        stop_loss_net_usdt=0.50,
        max_hold_sec=5.0,
        guard_fields={"expected_net": 0.12},
    )

    terminal = tracker.flush_expired({}, now_ts=106.0)

    assert len(terminal) == 1
    payload = terminal[0]
    assert payload["terminal_classification"] == "SHADOW_INSUFFICIENT_QUOTES"
    assert payload["last_observed_price"] is None
    assert payload["quote_sample_count"] == 0
    assert tracker.active_count == 0
