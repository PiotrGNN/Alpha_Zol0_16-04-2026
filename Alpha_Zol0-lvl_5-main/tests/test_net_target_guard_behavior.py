import pytest

from core.BotCore import _resolve_entry_min_net_threshold


def test_baseline_block_threshold_unchanged():
    out = _resolve_entry_min_net_threshold(0.12)
    assert out["base_entry_min_net_usdt"] == pytest.approx(0.12)
    assert out["effective_entry_min_net_usdt"] == pytest.approx(0.12)
    assert out["dynamic_adjustment_applied"] is False


def test_config_override_pass_threshold():
    out = _resolve_entry_min_net_threshold(0.01)
    assert out["base_entry_min_net_usdt"] == pytest.approx(0.01)
    assert out["effective_entry_min_net_usdt"] == pytest.approx(0.01)
    assert out["dynamic_adjustment_applied"] is False


def test_live_mode_safety_no_adjustment():
    out = _resolve_entry_min_net_threshold(0.01)
    assert out["effective_entry_min_net_usdt"] == pytest.approx(0.01)
    assert out["dynamic_adjustment_applied"] is False


def test_dynamic_threshold_scales_micro_and_universe_exploration():
    micro_state = {"only_micro_signals": True}
    out = _resolve_entry_min_net_threshold(
        0.2,
        alpha_micro_exploration_state=micro_state,
        alpha_micro_exploration_net_target_scale=0.25,
    )
    assert out["base_entry_min_net_usdt"] == pytest.approx(0.2)
    assert out["effective_entry_min_net_usdt"] == pytest.approx(0.05)
    assert out["dynamic_adjustment_applied"] is True
    assert micro_state["net_target_scale_applied"] == pytest.approx(0.25)

    universe_out = _resolve_entry_min_net_threshold(
        0.2,
        alpha_universe_exploration_active=True,
        alpha_universe_exploration_net_target_scale=0.5,
    )
    assert universe_out["effective_entry_min_net_usdt"] == pytest.approx(0.1)
    assert universe_out["dynamic_adjustment_applied"] is True


def test_dynamic_threshold_falls_back_on_invalid_scale():
    micro_state = {"only_micro_signals": True}
    out = _resolve_entry_min_net_threshold(
        0.2,
        alpha_micro_exploration_state=micro_state,
        alpha_micro_exploration_net_target_scale="not-a-number",
    )
    assert out["effective_entry_min_net_usdt"] == pytest.approx(0.1)
    assert out["dynamic_adjustment_applied"] is True
    assert micro_state["net_target_scale_applied"] == pytest.approx(0.5)
