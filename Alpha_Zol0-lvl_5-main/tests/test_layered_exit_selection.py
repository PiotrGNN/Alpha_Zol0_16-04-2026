from core.BotCore import _select_layered_exit_candidate


def test_select_layered_exit_prefers_non_hard_pool_when_available():
    selected, non_hard_exists = _select_layered_exit_candidate(
        [
            {
                "reason": "auto_close_hard",
                "expected_net_after_fee": 5.0,
                "priority": 65,
            },
            {
                "reason": "post_green_protective_exit",
                "expected_net_after_fee": 1.0,
                "priority": 82,
            },
        ],
        hard_reason_names={"auto_close_hard", "auto_close_hard_near_zero"},
        prefer_non_hard=True,
    )

    assert non_hard_exists is True
    assert selected["reason"] == "post_green_protective_exit"


def test_select_layered_exit_uses_hard_pool_when_only_hard_candidates_exist():
    selected, non_hard_exists = _select_layered_exit_candidate(
        [
            {
                "reason": "auto_close_hard_near_zero",
                "expected_net_after_fee": 0.1,
                "priority": 70,
            },
            {
                "reason": "auto_close_hard",
                "expected_net_after_fee": 0.2,
                "priority": 65,
            },
        ],
        hard_reason_names={"auto_close_hard", "auto_close_hard_near_zero"},
        prefer_non_hard=True,
    )

    assert non_hard_exists is False
    assert selected["reason"] == "auto_close_hard"


def test_select_layered_exit_ranks_non_hard_by_net_then_priority():
    selected, non_hard_exists = _select_layered_exit_candidate(
        [
            {
                "reason": "post_green_protective_exit",
                "expected_net_after_fee": 0.5,
                "priority": 82,
            },
            {
                "reason": "auto_close_time_economics",
                "expected_net_after_fee": 0.5,
                "priority": 90,
            },
            {
                "reason": "auto_close_hard",
                "expected_net_after_fee": 2.0,
                "priority": 65,
            },
        ],
        hard_reason_names={"auto_close_hard", "auto_close_hard_near_zero"},
        prefer_non_hard=True,
    )

    assert non_hard_exists is True
    assert selected["reason"] == "auto_close_time_economics"


def test_select_layered_exit_handles_empty_and_invalid_candidates():
    selected, non_hard_exists = _select_layered_exit_candidate([])
    assert selected is None
    assert non_hard_exists is False

    selected, non_hard_exists = _select_layered_exit_candidate(
        [None, "bad", {"reason": "ignored"}],
        hard_reason_names={"ignored"},
        prefer_non_hard=True,
    )
    assert selected["reason"] == "ignored"
    assert non_hard_exists is False


def test_select_layered_exit_can_keep_hard_pool_when_requested():
    selected, non_hard_exists = _select_layered_exit_candidate(
        [
            {
                "reason": "auto_close_hard",
                "expected_net_after_fee": 3.0,
                "priority": 99,
            },
            {
                "reason": "post_green_protective_exit",
                "expected_net_after_fee": 1.0,
                "priority": 10,
            },
        ],
        hard_reason_names={"auto_close_hard"},
        prefer_non_hard=False,
    )

    assert non_hard_exists is True
    assert selected["reason"] == "auto_close_hard"
