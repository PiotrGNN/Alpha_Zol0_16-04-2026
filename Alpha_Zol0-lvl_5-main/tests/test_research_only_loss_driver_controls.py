import pytest

from core.BotCore import _research_only_loss_driver_controls


def test_research_flags_off_by_default(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("RESEARCH_KILL_SWITCH_ENABLE", raising=False)
    monkeypatch.delenv("RESEARCH_CONSTRAINT_MODE_ENABLE", raising=False)
    allow, mode, bucket, context = _research_only_loss_driver_controls(
        True,
        "buy",
        "TrendFollowing",
        "trend",
        "hold",
        {"history_ready": True, "reason": "edge_above_threshold"},
        {"edge_after_execution": 0.01},
        0.01,
        0.0008,
    )
    assert allow is True
    assert mode is None
    assert bucket is None
    assert context is None


@pytest.mark.parametrize(
    "entry_reason, edge_reason, expected_bucket",
    [
        ("no_candidate_seen", "edge_above_threshold", "no_candidate_seen"),
        ("RECOVERY_BELOW_COST", "edge_above_threshold", "recovery_below_cost"),
        ("NO_PRICE_RECOVERY", "edge_above_threshold", "no_price_recovery"),
    ],
)
def test_kill_switch_blocks_target_buckets(monkeypatch, entry_reason, edge_reason, expected_bucket):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_KILL_SWITCH_ENABLE", "1")
    monkeypatch.delenv("RESEARCH_CONSTRAINT_MODE_ENABLE", raising=False)
    allow, mode, bucket, context = _research_only_loss_driver_controls(
        True,
        "buy",
        "Momentum",
        "range",
        entry_reason,
        {"history_ready": True, "reason": edge_reason},
        {"edge_after_execution": 0.01},
        0.01,
        0.0008,
    )
    assert allow is False
    assert mode == "research_kill_switch"
    assert bucket == expected_bucket
    assert context["strategy"] == "momentum"


def test_kill_switch_blocks_trendfollowing_trend(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_KILL_SWITCH_ENABLE", "1")
    allow, mode, bucket, context = _research_only_loss_driver_controls(
        True,
        "buy",
        "TrendFollowing",
        "trend",
        "hold",
        {"history_ready": True, "reason": "edge_above_threshold"},
        {"edge_after_execution": 0.01},
        0.01,
        0.0008,
    )
    assert allow is False
    assert mode == "research_kill_switch"
    assert bucket == "trendfollowing_trend"
    assert context["strategy"] == "trendfollowing"
    assert context["regime"] == "trend"


def test_constraint_mode_uses_history_and_execution_threshold(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_CONSTRAINT_MODE_ENABLE", "1")
    monkeypatch.setenv("RESEARCH_CONSTRAINT_MIN_EDGE_AFTER_EXECUTION", "0.0010")
    allow, mode, bucket, context = _research_only_loss_driver_controls(
        True,
        "buy",
        "TrendFollowing",
        "trend",
        "hold",
        {
            "history_ready": True,
            "reason": "edge_above_threshold",
            "mean_fee_total": 0.0002,
            "mean_spread_slippage_proxy": 0.0001,
        },
        {"edge_after_execution": 0.0009},
        0.0009,
        0.0008,
    )
    assert allow is False
    assert mode == "research_constraint"
    assert bucket == "edge_after_execution_below_threshold"
    assert context["candidate_seen_any"] is True
    assert context["expected_recovery"] == pytest.approx(0.0009)


def test_constraint_mode_blocks_when_history_not_ready(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_CONSTRAINT_MODE_ENABLE", "1")
    allow, mode, bucket, context = _research_only_loss_driver_controls(
        True,
        "buy",
        "Momentum",
        "range",
        "hold",
        {"history_ready": False, "reason": "insufficient_history"},
        None,
        0.01,
        0.0008,
    )
    assert allow is False
    assert mode == "research_constraint"
    assert bucket == "candidate_seen_any_false"
    assert context["candidate_seen_any"] is False


def test_live_semantics_cannot_be_overridden(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("RESEARCH_KILL_SWITCH_ENABLE", "1")
    monkeypatch.setenv("RESEARCH_CONSTRAINT_MODE_ENABLE", "1")
    allow, mode, bucket, context = _research_only_loss_driver_controls(
        True,
        "buy",
        "TrendFollowing",
        "trend",
        "hold",
        {"history_ready": False, "reason": "insufficient_history"},
        {"edge_after_execution": 0.0},
        0.0,
        0.0008,
    )
    assert allow is True
    assert mode is None
    assert bucket is None
    assert context is None
