from __future__ import annotations

from scripts.trendfollowing_edge_repair_alpha_search_plan import (
    build_repair_plan,
    classify_next_action,
    rank_alpha_search_lanes,
)


def test_classify_next_action_rejects_threshold_patch_for_weak_edge():
    result = classify_next_action(
        final_verdict="THRESHOLD_CHANGE_NOT_JUSTIFIED_STRATEGY_EDGE_REPAIR_REQUIRED",
        max_expected_net_after_full_cost=0.056,
        clean_trade_with_ratio_count=0,
        lower_threshold_runtime_trades=0,
    )

    assert result["next_action_classification"] == "EDGE_REPAIR_AND_STRONGER_ALPHA_SEARCH"
    assert result["threshold_patch_allowed"] is False
    assert result["strategy_patch_allowed"] is False
    assert result["paper_experiment_allowed"] is True


def test_rank_alpha_search_lanes_prioritizes_non_trendfollowing_and_expected_net():
    lanes = rank_alpha_search_lanes(
        [
            {"strategy": "TrendFollowingV2", "max_expected_net_after_full_cost": 0.056},
            {"strategy": "MomentumV2", "max_expected_net_after_full_cost": 0.091},
            {"strategy": "MicroBreakoutV2", "max_expected_net_after_full_cost": 0.12},
        ]
    )

    assert lanes[0]["strategy"] == "MicroBreakoutV2"
    assert lanes[0]["priority"] == 1
    assert lanes[-1]["strategy"] == "TrendFollowingV2"


def test_build_repair_plan_contains_gates_and_deliverables():
    report = build_repair_plan(
        semantics={
            "final_verdict": "THRESHOLD_CHANGE_NOT_JUSTIFIED_STRATEGY_EDGE_REPAIR_REQUIRED",
            "locked_facts": {
                "expected_net_after_full_cost_stats": {"max": 0.0567},
                "clean_trade_with_ratio_count": 0,
            },
            "candidate_level_findings": {
                "BNBUSDTM:TrendFollowingV2:buy": {
                    "highest_observed_expected_net_after_full_cost": 0.053,
                    "highest_observed_ratio": 0.909,
                    "failure_classification": "strategy_weakness",
                }
            },
        },
        ratio={
            "hypothetical_ratio_threshold_simulation": {
                "0.90": {"additional_admitted_events": 10, "clean_completed_historical_trades_available": 0}
            }
        },
    )

    assert report["classification"] == "EDGE_REPAIR_AND_STRONGER_ALPHA_SEARCH"
    assert report["patch_policy"]["do_not_lower_thresholds"] is True
    assert report["trendfollowing_repair_plan"][0]["gate"] == "offline_expected_net_replay"
    assert report["stronger_alpha_search_plan"][0]["minimum_expected_net_after_full_cost"] >= 0.08
    assert report["completion_criteria"]["profitability_claim_allowed"] is False
