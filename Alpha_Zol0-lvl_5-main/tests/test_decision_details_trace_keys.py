import json
import time as _time


def _run_single_cycle(monkeypatch, *, enable_shadow_rule: bool):
    # Run exactly one PAPER cycle with mock market data.
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("ZOL0_TOKEN", "testtoken")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("DECISION_THROTTLE_SEC", "0")
    monkeypatch.setenv(
        "MR_BOUNDARY_FILTER_ENABLE",
        "1" if enable_shadow_rule else "0",
    )

    # Block network as a hard assertion.
    import requests

    def fail_net(*args, **kwargs):
        raise AssertionError("Network call blocked in PAPER trace-keys test")

    monkeypatch.setattr(requests, "get", fail_net)
    monkeypatch.setattr(requests, "post", fail_net)

    # Disable news scheduler thread.
    import utils.news_social_scheduler as nss

    monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)

    # Freeze wall-clock time for determinism.
    monkeypatch.setattr(_time, "time", lambda: 1700000000)

    import core.BotCore as botcore

    captured = []

    def capture_decision(timestamp, decision, details=None):
        captured.append(
            {"timestamp": timestamp, "decision": decision, "details": details}
        )
        return True

    # Avoid DB writes in this unit-level test.
    monkeypatch.setattr(botcore, "save_decision_to_db", capture_decision)
    monkeypatch.setattr(botcore, "save_equity_to_db", lambda *a, **k: True)

    botcore.run_bot(simulate=True)
    assert captured, "Expected at least one decision to be captured"

    return json.loads(captured[-1]["details"])


def test_decision_details_include_trace_keys(monkeypatch):
    details = _run_single_cycle(monkeypatch, enable_shadow_rule=False)

    assert isinstance(details, dict)

    for key in (
        "ensemble_signals",
        "signal_votes",
        "signal_score",
        "trend",
        "volatility",
        "tick",
        "ai_pred",
        "ai_base_weight",
        "ai_weight",
        "ai_feedback",
        "regime",
        "allocations",
        "main_strategy",
        "mr_features",
    ):
        assert key in details, f"missing decision_details key: {key}"

    assert isinstance(details["allocations"], dict)
    mr_features = details["mr_features"]
    assert isinstance(mr_features, dict)
    for key in (
        "rsi",
        "bb_lower",
        "bb_upper",
        "bb_width",
        "price",
        "price_dist_to_bb_lower_pct",
        "price_dist_to_bb_lower_std",
    ):
        assert key in mr_features, f"missing mr_features key: {key}"


def test_mr_shadow_rule_diagnostics_are_opt_in_and_non_blocking(monkeypatch):
    disabled = _run_single_cycle(monkeypatch, enable_shadow_rule=False)
    enabled = _run_single_cycle(monkeypatch, enable_shadow_rule=True)

    assert disabled["entry_decision"] == enabled["entry_decision"]
    assert disabled["entry_decision_final"] == enabled["entry_decision_final"]
    assert disabled["mr_features"] == enabled["mr_features"]

    assert disabled["mr_shadow_rule_pass"] is None
    assert disabled["mr_shadow_rule_reject_reason"] is None
    assert disabled["mr_shadow_rule_thresholds"] is None
    assert disabled["mr_shadow_rule_checks"] is None
    assert disabled["mr_shadow_rule_variant"] == "ml_light_candidate_v1"

    assert enabled["mr_shadow_rule_variant"] == "ml_light_candidate_v1"
    assert isinstance(enabled["mr_shadow_rule_thresholds"], dict)
    assert isinstance(enabled["mr_shadow_rule_checks"], dict)
    assert "trend_ok" in enabled["mr_shadow_rule_checks"]
    assert "bb_width" in enabled["mr_shadow_rule_checks"]
    assert "price_dist_to_bb_lower_pct" in enabled["mr_shadow_rule_checks"]
    assert "rsi" in enabled["mr_shadow_rule_checks"]
    assert "price_dist_to_bb_lower_std" in enabled["mr_shadow_rule_checks"]
