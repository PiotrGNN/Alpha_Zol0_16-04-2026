from core.BotCore import _should_fail_closed_post_green_red_close


def test_fail_closed_blocks_post_green_red_close_with_positive_feasible_alternative():
    blocked = _should_fail_closed_post_green_red_close(
        exit_reason="post_green_protective_exit",
        selected_expected_net_after_fee=-0.002,
        post_green_peak_mfe=0.014,
        pre_hard_close_best_feasible_net=0.006,
    )

    assert blocked is True


def test_fail_closed_does_not_block_non_post_green_exit_reason():
    blocked = _should_fail_closed_post_green_red_close(
        exit_reason="auto_close_hard",
        selected_expected_net_after_fee=-0.002,
        post_green_peak_mfe=0.014,
        pre_hard_close_best_feasible_net=0.006,
    )

    assert blocked is False


def test_fail_closed_blocks_weak_peak_red_close_with_positive_feasible_alternative():
    blocked = _should_fail_closed_post_green_red_close(
        exit_reason="weak_peak_stale_decay_hard_window_feefloor_override",
        selected_expected_net_after_fee=-0.0015,
        post_green_peak_mfe=0.012,
        pre_hard_close_best_feasible_net=0.004,
    )

    assert blocked is True


def test_fail_closed_does_not_block_when_no_positive_feasible_alternative():
    blocked = _should_fail_closed_post_green_red_close(
        exit_reason="post_green_protective_exit",
        selected_expected_net_after_fee=-0.001,
        post_green_peak_mfe=0.010,
        pre_hard_close_best_feasible_net=0.0,
    )

    assert blocked is False
