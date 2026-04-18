import pytest

from core.BotCore import _research_only_exit_loss_driver_controls


def test_exit_research_flags_off_by_default(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("RESEARCH_EXIT_KILL_SWITCH_ENABLE", raising=False)
    monkeypatch.delenv("RESEARCH_EXIT_CONSTRAINT_MODE_ENABLE", raising=False)
    bucket, mode, out_bucket, context = _research_only_exit_loss_driver_controls(
        "no_candidate_seen",
        False,
        0.0,
        False,
        False,
    )
    assert bucket == "no_candidate_seen"
    assert mode is None
    assert out_bucket is None
    assert context is None


def test_exit_live_semantics_cannot_be_overridden(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("RESEARCH_EXIT_KILL_SWITCH_ENABLE", "1")
    monkeypatch.setenv("RESEARCH_EXIT_CONSTRAINT_MODE_ENABLE", "1")
    bucket, mode, out_bucket, context = _research_only_exit_loss_driver_controls(
        "no_candidate_seen",
        False,
        0.0,
        False,
        False,
    )
    assert bucket == "no_candidate_seen"
    assert mode is None
    assert out_bucket is None
    assert context is None


@pytest.mark.parametrize(
    "missed_reason",
    [
        "no_candidate_seen",
        "candidate_missing_expected_net",
        "candidate_nonpositive_net",
        "candidate_present_no_positive_window",
        "positive_candidate_20_40_missed",
        "positive_candidate_0_40_missed",
    ],
)
def test_exit_kill_switch_blocks_forensic_buckets(monkeypatch, missed_reason):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_EXIT_KILL_SWITCH_ENABLE", "1")
    bucket, mode, out_bucket, context = _research_only_exit_loss_driver_controls(
        missed_reason,
        True,
        0.01,
        True,
        True,
    )
    assert bucket == f"research_exit_{missed_reason.lower()}"
    assert mode == "research_exit_kill_switch"
    assert out_bucket == missed_reason.lower()
    assert context["candidate_seen_any"] is True


def test_exit_constraint_mode_blocks_when_no_candidate_seen(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_EXIT_CONSTRAINT_MODE_ENABLE", "1")
    monkeypatch.setenv("RESEARCH_EXIT_EXPECTED_COST", "0.0010")
    bucket, mode, out_bucket, context = _research_only_exit_loss_driver_controls(
        "candidate_present_no_positive_window",
        False,
        0.0005,
        False,
        False,
    )
    assert bucket == "research_exit_candidate_seen_any_false"
    assert mode == "research_exit_constraint"
    assert out_bucket == "candidate_seen_any_false"
    assert context["candidate_seen_any"] is False


def test_exit_constraint_mode_blocks_when_feasible_net_below_cost(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_EXIT_CONSTRAINT_MODE_ENABLE", "1")
    monkeypatch.setenv("RESEARCH_EXIT_EXPECTED_COST", "0.0010")
    bucket, mode, out_bucket, context = _research_only_exit_loss_driver_controls(
        "candidate_present_no_positive_window",
        True,
        0.0005,
        False,
        False,
    )
    assert bucket == "research_exit_expected_recovery_below_cost"
    assert mode == "research_exit_constraint"
    assert out_bucket == "expected_recovery_below_cost"
    assert context["pre_hard_close_best_feasible_net"] == pytest.approx(0.0005)


def test_exit_constraint_mode_allows_when_signal_is_ok(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_EXIT_CONSTRAINT_MODE_ENABLE", "1")
    monkeypatch.setenv("RESEARCH_EXIT_EXPECTED_COST", "0.0010")
    bucket, mode, out_bucket, context = _research_only_exit_loss_driver_controls(
        "candidate_present_no_positive_window",
        True,
        0.0020,
        False,
        False,
    )
    assert bucket == "candidate_present_no_positive_window"
    assert mode is None
    assert out_bucket is None
    assert context is None

