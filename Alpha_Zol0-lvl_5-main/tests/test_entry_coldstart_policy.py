from core.BotCore import _should_fail_closed_on_history_not_ready


def test_history_not_ready_policy_fails_closed_for_seed_only():
    assert _should_fail_closed_on_history_not_ready("seed_only") is True


def test_history_not_ready_policy_fails_closed_for_strict_modes():
    assert _should_fail_closed_on_history_not_ready("strict") is True
    assert _should_fail_closed_on_history_not_ready("fail_closed") is True


def test_history_not_ready_policy_allows_fail_open_mode():
    assert _should_fail_closed_on_history_not_ready("fail_open") is False


def test_history_not_ready_policy_defaults_to_fail_open_for_unknown_mode():
    assert _should_fail_closed_on_history_not_ready("some_unknown_mode") is False
