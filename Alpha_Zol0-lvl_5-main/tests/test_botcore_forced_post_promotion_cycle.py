import core.BotCore as botcore


class _RaisingLogger:
    def __init__(self):
        self.calls = []

    def log(self, event, details=None):
        self.calls.append((event, details))
        raise RuntimeError("logger-fail")


def _base_result_payload():
    return {
        "enabled": True,
        "symbol": "BTCUSDTM",
        "strategy": "TrendFollowing",
        "side": "buy",
        "window": 1,
        "min_trades": 1,
        "history_ready": True,
        "blocked": False,
        "reason": None,
        "snapshot": {},
        "trade_count": 9,
        "trade_count_primary": 9,
        "bucket_key_primary": "bucket-primary",
        "bucket_key_fallback": "bucket-fallback",
        "bucket_used_final": "bucket-primary",
        "canonical_shadow_bucket": {},
        "evaluated_path_enter_after_forced_cycle": True,
        "canonical_gate_read_branch_selector_enter": True,
        "canonical_gate_read_emit_candidate": True,
        "canonical_gate_read_emit_done": False,
    }


def test_force_single_post_promotion_cycle_returns_none_in_live_mode(monkeypatch):
    monkeypatch.setenv("LIVE", "1")

    result = botcore._force_single_post_promotion_evaluated_cycle(
        "BTCUSDTM",
        "TrendFollowing",
        "buy",
        "bucket-a",
        101,
    )

    assert result is None


def test_force_single_post_promotion_cycle_missing_context_is_fail_closed(
    monkeypatch,
):
    monkeypatch.setenv("LIVE", "0")
    emitted = []
    raising_logger = _RaisingLogger()
    monkeypatch.setattr(
        botcore,
        "_emit_critical_path_exception",
        lambda **kwargs: emitted.append(kwargs),
    )

    result = botcore._force_single_post_promotion_evaluated_cycle(
        "",
        "TrendFollowing",
        "buy",
        "bucket-a",
        102,
        logger=raising_logger,
    )

    assert result is None
    assert emitted
    assert emitted[-1]["stage"] == "force_single_post_promotion_evaluated_cycle.context"
    assert "missing forced cycle symbol context" in str(emitted[-1]["exc"])


def test_force_single_post_promotion_cycle_handles_missing_entry_edge_check(
    monkeypatch,
):
    monkeypatch.setenv("LIVE", "0")
    emitted = []
    raising_logger = _RaisingLogger()
    monkeypatch.setattr(
        botcore,
        "_emit_critical_path_exception",
        lambda **kwargs: emitted.append(kwargs),
    )

    result = botcore._force_single_post_promotion_evaluated_cycle(
        "BTCUSDTM",
        "TrendFollowing",
        "buy",
        "bucket-b",
        103,
        logger=raising_logger,
        entry_edge_check=None,
    )

    assert result is None
    assert emitted
    assert emitted[-1]["stage"] == "force_single_post_promotion_evaluated_cycle"
    assert emitted[-1]["exc"].__class__.__name__ == "NameError"


def test_force_single_post_promotion_cycle_non_dict_helper_result_is_classified(
    monkeypatch,
):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setattr(botcore, "_emit_critical_path_exception", lambda **kwargs: None)

    def fake_entry_edge_check(*args, **kwargs):
        return ["not-a-dict-result"]

    result = botcore._force_single_post_promotion_evaluated_cycle(
        "BTCUSDTM",
        "TrendFollowing",
        "buy",
        "bucket-c",
        104,
        logger=None,
        entry_edge_check=fake_entry_edge_check,
    )

    assert isinstance(result, dict)
    assert result["forced_cycle_eval_pre_selector_return_site_id"] == (
        "helper_returned_non_dict_result"
    )
    assert result["forced_cycle_eval_exit_reason"] == "helper_returned_before_selector"
    assert result["forced_cycle_exit_reason"] == "candidate_not_reached"


def test_force_single_post_promotion_cycle_wrapper_mismatch_with_logger_exceptions(
    monkeypatch,
):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setattr(botcore, "_emit_critical_path_exception", lambda **kwargs: None)
    raising_logger = _RaisingLogger()

    def fake_entry_edge_check(*args, **kwargs):
        return _base_result_payload()

    result = botcore._force_single_post_promotion_evaluated_cycle(
        "BTCUSDTM",
        "TrendFollowing",
        "buy",
        "bucket-d",
        105,
        logger=raising_logger,
        entry_edge_check=fake_entry_edge_check,
    )

    assert isinstance(result, dict)
    assert result["forced_cycle_eval_pre_selector_return_site_id"] == (
        "wrapper_expectation_mismatch"
    )
    assert result["forced_cycle_eval_exit_reason"] == (
        "candidate_emitted_but_emit_attempt_not_reached"
    )
    assert result["forced_cycle_exit_reason"] == "candidate_reached_but_emit_blocked"
