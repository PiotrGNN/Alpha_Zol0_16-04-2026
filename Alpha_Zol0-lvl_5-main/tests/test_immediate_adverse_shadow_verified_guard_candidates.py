import pytest

from scripts.immediate_adverse_shadow_verified_guard_candidates import (
    evaluate_guard_candidates,
)


def test_evaluate_guard_candidates_rejects_missed_winner_dominant_rule():
    outcomes = [
        {
            "symbol": "SOLUSDTM",
            "side": "buy",
            "strategy": "TrendFollowingV2",
            "terminal_classification": "MISSED_WINNER",
            "proxy_net_result": 0.10,
        }
        for _ in range(7)
    ] + [
        {
            "symbol": "SOLUSDTM",
            "side": "buy",
            "strategy": "TrendFollowingV2",
            "terminal_classification": "IMMEDIATE_ADVERSE_LOSS",
            "proxy_net_result": -0.05,
        }
        for _ in range(3)
    ]

    report = evaluate_guard_candidates(outcomes)

    assert report["final_classification"] == "NO_SHADOW_VERIFIED_GUARD_RULE_FOUND"
    candidate = report["candidates"][0]
    assert candidate["passed"] is False
    assert candidate["missed_winner_rate"] == pytest.approx(0.70)
    assert candidate["net_shadow_benefit"] == pytest.approx(-0.55)
    assert "missed_winner_rate_gt_0.35" in candidate["failed_criteria"]


def test_evaluate_guard_candidates_accepts_positive_shadow_net_benefit_rule():
    outcomes = [
        {
            "symbol": "ETHUSDTM",
            "side": "sell",
            "strategy": "TrendFollowingV2",
            "terminal_classification": "IMMEDIATE_ADVERSE_LOSS",
            "proxy_net_result": -0.20,
        }
        for _ in range(7)
    ] + [
        {
            "symbol": "ETHUSDTM",
            "side": "sell",
            "strategy": "TrendFollowingV2",
            "terminal_classification": "MISSED_WINNER",
            "proxy_net_result": 0.08,
        }
        for _ in range(3)
    ]

    report = evaluate_guard_candidates(outcomes)

    assert report["final_classification"] == "SHADOW_VERIFIED_GUARD_RULE_FOUND"
    candidate = report["candidates"][0]
    assert candidate["passed"] is True
    assert candidate["rule_key"] == "ETHUSDTM:sell:TrendFollowingV2"
    assert candidate["net_shadow_benefit"] == pytest.approx(1.16)
