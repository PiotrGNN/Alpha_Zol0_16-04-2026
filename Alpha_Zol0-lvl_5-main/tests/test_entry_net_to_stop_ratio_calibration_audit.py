from __future__ import annotations

from scripts.entry_net_to_stop_ratio_calibration_audit import (
    bucket_for_ratio,
    classify_calibration,
    simulate_ratio_thresholds,
    summarize_ratio_buckets,
)


def test_bucket_for_ratio_uses_required_boundaries():
    assert bucket_for_ratio(0.49) == "<0.50"
    assert bucket_for_ratio(0.50) == "0.50-0.70"
    assert bucket_for_ratio(0.70) == "0.70-0.90"
    assert bucket_for_ratio(0.90) == "0.90-1.00"
    assert bucket_for_ratio(1.00) == "1.00-1.10"
    assert bucket_for_ratio(1.10) == ">=1.10"


def test_summarize_ratio_buckets_counts_events_candidates_and_trade_metrics():
    events = [
        {
            "canonical_key": "AVAXUSDTM:TrendFollowingV2:sell",
            "entry_net_to_stop_ratio": 0.91,
            "expected_net_after_full_cost": 0.04,
            "estimated_stop_loss_net_usdt": 0.044,
            "reason_code": "entry_net_to_stop_guard",
            "only_net_to_stop_blocked": True,
        },
        {
            "canonical_key": "DOTUSDTM:TrendFollowingV2:sell",
            "entry_net_to_stop_ratio": 1.05,
            "expected_net_after_full_cost": 0.05,
            "estimated_stop_loss_net_usdt": 0.047,
            "reason_code": "entry_net_to_stop_guard",
            "only_net_to_stop_blocked": True,
        },
    ]
    trades = [
        {
            "canonical_key": "AVAXUSDTM:TrendFollowingV2:sell",
            "entry_net_to_stop_ratio": 0.91,
            "realized_pnl": -0.01,
            "mfe": 0.02,
            "mae": -0.03,
            "exit_reason": "auto_close_hard",
        }
    ]

    summary = summarize_ratio_buckets(events, trades)

    assert summary["0.90-1.00"]["event_count"] == 1
    assert summary["0.90-1.00"]["candidate_count"] == 1
    assert summary["0.90-1.00"]["completed_clean_trade_count"] == 1
    assert summary["0.90-1.00"]["net_pnl"] == -0.01
    assert summary["1.00-1.10"]["event_count"] == 1


def test_simulate_ratio_thresholds_reports_additional_ratio_only_events():
    events = [
        {"entry_net_to_stop_ratio": 0.91, "only_net_to_stop_blocked": True, "canonical_key": "A"},
        {"entry_net_to_stop_ratio": 0.96, "only_net_to_stop_blocked": True, "canonical_key": "B"},
        {"entry_net_to_stop_ratio": 1.09, "only_net_to_stop_blocked": True, "canonical_key": "C"},
        {"entry_net_to_stop_ratio": 0.89, "only_net_to_stop_blocked": True, "canonical_key": "D"},
        {"entry_net_to_stop_ratio": 0.95, "only_net_to_stop_blocked": False, "canonical_key": "E"},
    ]

    simulation = simulate_ratio_thresholds(events, [])

    assert simulation["1.10"]["additional_admitted_events"] == 0
    assert simulation["1.00"]["additional_admitted_events"] == 1
    assert simulation["0.95"]["additional_admitted_events"] == 2
    assert simulation["0.90"]["additional_admitted_events"] == 3


def test_classify_calibration_prefers_weak_strategy_when_no_clean_lower_trade_sample():
    result = classify_calibration(
        ratio_events=[
            {
                "entry_net_to_stop_ratio": 0.91,
                "expected_net_after_full_cost": 0.04,
                "only_net_to_stop_blocked": True,
            },
            {
                "entry_net_to_stop_ratio": 0.95,
                "expected_net_after_full_cost": 0.05,
                "only_net_to_stop_blocked": True,
            },
        ],
        bucket_summary={"0.90-1.00": {"completed_clean_trade_count": 0}},
        simulation={"1.00": {"additional_admitted_events": 2}},
    )

    assert result["classification"] == "STRATEGY_EDGE_TOO_WEAK_RELATIVE_TO_STOP_RISK"
    assert result["final_verdict"] == "STRATEGY_EDGE_REPAIR_REQUIRED"
    assert result["patch_decision"] == "no_semantic_patch"
