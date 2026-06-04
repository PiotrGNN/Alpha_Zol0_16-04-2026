import json
from pathlib import Path

from scripts.discover_runtime_compatible_stronger_alpha import (
    canonical_strategy,
    classify_candidate,
    discover_from_runtime_report,
    strategy_family_priority,
)


def test_strategy_family_priority_demotes_trendfollowing_baseline():
    assert strategy_family_priority("MicroBreakoutV2") == 0
    assert strategy_family_priority("MomentumV2") == 1
    assert strategy_family_priority("MeanReversionV2") == 2
    assert strategy_family_priority("TrendFollowingV2") == 3
    assert canonical_strategy("MicroBreakoutV2") == "MICROBREAKOUT"


def test_classify_candidate_fails_closed_on_edge_ratio_and_profile():
    base = {
        "source": "rolling_quote_window",
        "source_parity_proven": True,
        "runtime_profile_exists": True,
        "expected_net_after_full_cost": 0.13,
        "effective_entry_min_net_usdt": 0.12,
        "entry_net_to_stop_ratio": 1.2,
        "effective_entry_min_net_to_stop_ratio": 1.1,
        "edge_filter_passes": True,
        "profile_stale": False,
        "contamination_counts": {
            "seed": 0,
            "fallback": 0,
            "mock": 0,
            "force_open": 0,
            "forced_cycle": 0,
        },
    }

    assert classify_candidate(base)["runtime_admissible"] is True
    low_edge = {**base, "expected_net_after_full_cost": 0.08}
    assert low_edge["expected_net_after_full_cost"] < 0.12
    assert classify_candidate(low_edge)["classification"] == (
        "NOT_RUNTIME_ADMISSIBLE_EDGE_BELOW_THRESHOLD"
    )
    low_ratio = {**base, "entry_net_to_stop_ratio": 0.9}
    assert classify_candidate(low_ratio)["classification"] == (
        "NOT_RUNTIME_ADMISSIBLE_RATIO_BELOW_REQUIRED"
    )
    missing_profile = {**base, "runtime_profile_exists": False}
    assert classify_candidate(missing_profile)["classification"] == (
        "NOT_RUNTIME_ADMISSIBLE_PROFILE_MISSING"
    )


def test_discover_from_runtime_report_ranks_non_trend_stronger_families(tmp_path):
    runtime_report = {
        "summary": {
            "db_count": 2,
            "candidate_event_count": 4,
            "candidate_count": 3,
        },
        "candidates": [
            {
                "candidate_key": "AVAXUSDTM:TRENDFOLLOWING:buy",
                "symbol": "AVAXUSDTM",
                "strategy": "TrendFollowingV2",
                "canonical_strategy": "TRENDFOLLOWING",
                "side": "buy",
                "source": "rolling_quote_window",
                "source_parity_status": "SOURCE_PARITY_PROVEN",
                "source_parity_proven": True,
                "profile_source": "rolling_quote_window",
                "profile_timestamp": "2026-06-04T00:00:00Z",
                "quote_window_start": "2026-06-03T23:50:00Z",
                "quote_window_end": "2026-06-04T00:00:00Z",
                "expected_net_after_full_cost": 0.069,
                "expected_net_before_cost": 0.071,
                "fee_model": {"fee_round_trip_ratio": 0.0002},
                "spread_model": {"spread_ratio": 0.00001},
                "slippage_model": {"slippage_ratio": 0.00005},
                "effective_entry_min_net_usdt": 0.12,
                "entry_net_to_stop_ratio": 1.2,
                "effective_entry_min_net_to_stop_ratio": 1.1,
                "runtime_profile_exists": True,
                "runtime_profile_age_sec": 100.0,
                "max_profile_age_sec": 1200.0,
                "clean_runtime_evidence": True,
                "contamination_counts": {
                    "seed": 0,
                    "fallback": 0,
                    "mock": 0,
                    "force_open": 0,
                    "forced_cycle": 0,
                },
            },
            {
                "candidate_key": "SOLUSDTM:MOMENTUM:buy",
                "symbol": "SOLUSDTM",
                "strategy": "MomentumV2",
                "canonical_strategy": "MOMENTUM",
                "side": "buy",
                "source": "rolling_quote_window",
                "source_parity_status": "SOURCE_PARITY_PROVEN",
                "source_parity_proven": True,
                "profile_source": "rolling_quote_window",
                "profile_timestamp": "2026-06-04T00:00:00Z",
                "quote_window_start": "2026-06-03T23:58:00Z",
                "quote_window_end": "2026-06-04T00:00:00Z",
                "expected_net_after_full_cost": 0.13,
                "expected_net_before_cost": 0.132,
                "effective_entry_min_net_usdt": 0.12,
                "entry_net_to_stop_ratio": 1.2,
                "effective_entry_min_net_to_stop_ratio": 1.1,
                "runtime_profile_exists": True,
                "runtime_profile_age_sec": 60.0,
                "max_profile_age_sec": 1200.0,
                "clean_runtime_evidence": True,
                "contamination_counts": {
                    "seed": 0,
                    "fallback": 0,
                    "mock": 0,
                    "force_open": 0,
                    "forced_cycle": 0,
                },
            },
        ],
    }
    path = tmp_path / "runtime_compatible_alpha_candidates_current.json"
    path.write_text(json.dumps(runtime_report), encoding="utf-8")

    report = discover_from_runtime_report(path)

    assert report["classification"] == "STRONGER_RUNTIME_COMPATIBLE_CANDIDATE_FOUND"
    assert report["summary"]["candidates_above_0_12"] == 1
    assert report["summary"]["promotion_contract_pass_count"] == 1
    assert report["summary"]["best_candidate_per_family"]["MOMENTUM"]["candidate_key"] == (
        "SOLUSDTM:MOMENTUM:buy"
    )
    assert report["final_selected_candidate"]["candidate_key"] == "SOLUSDTM:MOMENTUM:buy"
