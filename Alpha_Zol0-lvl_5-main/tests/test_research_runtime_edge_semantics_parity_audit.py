import json
from pathlib import Path

from scripts.research_runtime_edge_semantics_parity_audit import (
    build_report,
    canonical_strategy,
    compute_delta,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_canonical_strategy_collapses_trendfollowing_variants():
    assert canonical_strategy("TrendFollowingV2") == "TRENDFOLLOWING"
    assert canonical_strategy("TrendFollowing") == "TRENDFOLLOWING"
    assert canonical_strategy("TRENDFOLLOWING") == "TRENDFOLLOWING"
    assert canonical_strategy("MomentumV2") == "MOMENTUM"


def test_compute_delta_reports_absolute_and_percent_drop():
    delta = compute_delta(0.1236719064890212, 0.06944317126030092)

    assert round(delta["absolute"], 12) == -0.054228735229
    assert round(delta["percent"], 6) == -43.848871
    assert delta["runtime_would_pass_at_research_value"] is True
    assert delta["runtime_observed_passes_effective_threshold"] is False


def test_build_report_classifies_source_mismatch_with_correct_threshold(tmp_path):
    research_path = _write_json(
        tmp_path / "analysis" / "new_alpha_research_validation_current.json",
        {
            "classification": "NEW_ALPHA_CANDIDATE_FOUND_FOR_PAPER_VALIDATION",
            "scope": {
                "source": "kucoin_public_futures_klines",
                "min_expected_net_usdt": 0.08,
                "spread_bps": 1.0,
            },
            "selected_hypothesis": {
                "symbol": "AVAXUSDTM",
                "strategy": "TrendFollowingV2",
                "side": "buy",
                "source": "fresh_kucoin_public_klines_research",
                "expected_move": 0.009348978046933987,
                "expected_net_after_cost": 0.009088978046933973,
                "expected_net_after_full_cost": 0.1236719064890212,
                "final_notional_usdt": 13.606800000000002,
                "sample_count": 17,
                "profile_span_sec": 960.0,
                "decision_reason": "allow",
                "risk_reason": "allow",
            },
            "candidate_rank": [],
        },
    )
    fresh_runtime_path = _write_json(
        tmp_path / "analysis" / "fresh_alpha_candidate_runtime_smoke_current.json",
        {
            "classification": "NEXT_CANDIDATE_BLOCKED_BY_MIN_NET",
            "scope": {"entry_min_net_usdt": 0.12},
            "candidate": {
                "candidate": "AVAXUSDTM:TrendFollowingV2:buy",
                "canonical_candidate_key": "AVAXUSDTM:TRENDFOLLOWING:buy",
                "runtime_profile_exists": True,
                "runtime_profile_keys_top": {
                    "AVAXUSDTM|rolling_quote_window|n=115|span=788": 4
                },
                "expected_net_after_full_cost_stats": {
                    "count": 15,
                    "max": 0.06944317126030092,
                    "mean": 0.03215126180322969,
                },
                "target_reason_distribution": {
                    "allow": 30,
                    "entry_edge_filtered": 144,
                    "entry_min_net_guard": 30,
                },
                "effective_entry_min_net_usdt_values": [0.12],
                "min_net_guard_count": 30,
                "position_open_count": 0,
            },
        },
    )
    next_runtime_path = _write_json(
        tmp_path / "analysis" / "next_research_candidate_runtime_smoke_current.json",
        {
            "classification": "NO_RESEARCH_CANDIDATE_PASSES_CURRENT_RUNTIME_GATES",
            "candidates": [
                {
                    "candidate": "BNBUSDTM:TrendFollowingV2:buy",
                    "canonical_candidate_key": "BNBUSDTM:TRENDFOLLOWING:buy",
                    "expected_net_after_full_cost_stats": {"max": 0.023},
                    "target_reason_distribution": {"entry_min_net_guard": 10},
                    "effective_entry_min_net_usdt_values": [0.12],
                }
            ],
        },
    )
    discovery_path = _write_json(
        tmp_path / "analysis" / "v2_economic_candidate_discovery_current.json",
        {
            "summary": {
                "classification": "NO_ECONOMIC_CANDIDATES_OBSERVED",
                "max_observed_expected_net_after_full_cost": 0.056727152451426704,
                "ranked_candidates": [],
            }
        },
    )

    report = build_report(
        research_path=research_path,
        fresh_runtime_path=fresh_runtime_path,
        next_runtime_path=next_runtime_path,
        discovery_path=discovery_path,
        code_root=Path.cwd(),
    )

    assert report["edge_parity_classification"] == "RESEARCH_RUNTIME_SOURCE_MISMATCH"
    assert report["threshold_classification"] == "MIN_NET_THRESHOLD_APPLIED_CORRECTLY"
    assert report["strategy_classification"] == "TRENDFOLLOWINGV2_RUNTIME_EDGE_TOO_WEAK"
    assert (
        report["overall_classification"]
        == "FRESH_RESEARCH_EDGE_NOT_RUNTIME_ADMISSIBLE_DUE_TO_SOURCE_MISMATCH"
    )
    assert report["final_verdict"] == "SOURCE_PARITY_REPAIR_REQUIRED"
    avax = report["candidate_findings"]["AVAXUSDTM:TrendFollowingV2:buy"]
    assert avax["data_source_mismatch"] is True
    assert avax["runtime_would_pass_at_research_value"] is True
    assert avax["runtime_observed_passes_effective_threshold"] is False
