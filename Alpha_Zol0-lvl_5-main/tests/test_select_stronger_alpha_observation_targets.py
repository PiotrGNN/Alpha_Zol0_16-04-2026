from __future__ import annotations

import json
from pathlib import Path

from scripts.select_stronger_alpha_observation_targets import (
    CLASS_BLOCKED_NO_CLEAN_NON_TREND,
    CLASS_BLOCKED_UNIT_MISMATCH,
    CLASS_TARGETS_SELECTED,
    select_observation_targets,
)


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _unit_payload(classification: str = "POST_SIGNAL_ALPHA_TARGET_UNITS_CONSISTENT") -> dict:
    return {
        "classification": classification,
        "final_verdict": "STRONGER_ALPHA_SEARCH_CONFIRMED_UNITS_CONSISTENT",
        "normalization_check": {
            "best_signed_net_move": 0.000510836592,
            "alpha_target_value": 0.12,
            "best_net_to_target_ratio": 0.0042569716,
        },
    }


def _plan_payload() -> dict:
    return {
        "classification": "STRONGER_ALPHA_SEARCH_PLAN_READY",
        "ranked_families": [
            {"rank": 1, "family": "MicroBreakoutV2", "role": "primary_search"},
            {"rank": 2, "family": "MomentumV2", "role": "secondary_search"},
            {"rank": 3, "family": "MeanReversionV2", "role": "tertiary_search"},
            {"rank": 4, "family": "TrendFollowingV2", "role": "demoted_comparator_only"},
        ],
    }


def _failure_payload() -> dict:
    return {
        "classification": "POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK",
        "summary": {"clean_event_count": 3, "contaminated_event_count": 0},
        "best_20_trajectory_events_by_net_opportunity": [
            {
                "symbol": "BNBUSDTM",
                "canonical_strategy": "MEANREVERSION",
                "strategy": "MeanReversionV2",
                "side": "sell",
                "horizon_ticks": 1,
                "signed_net_move": 0.000510836592,
                "mfe": 0.000762476326,
                "estimated_cost": 0.000251639734,
                "source": "rolling_quote_window",
                "contaminated": False,
                "reason_code": "entry_edge_filtered",
            },
            {
                "symbol": "SOLUSDTM",
                "canonical_strategy": "MOMENTUM",
                "strategy": "MomentumV2",
                "side": "sell",
                "horizon_ticks": 5,
                "signed_net_move": 0.000355407841,
                "mfe": 0.000612447467,
                "estimated_cost": 0.000257039626,
                "source": "rolling_quote_window",
                "contaminated": False,
                "reason_code": "allow",
            },
            {
                "symbol": "SOLUSDTM",
                "canonical_strategy": "TRENDFOLLOWING",
                "strategy": "TrendFollowingV2",
                "side": "sell",
                "horizon_ticks": 5,
                "signed_net_move": 0.000355407841,
                "mfe": 0.000612447467,
                "estimated_cost": 0.000257039626,
                "source": "rolling_quote_window",
                "contaminated": False,
                "reason_code": "allow",
            },
        ],
    }


def _stronger_payload() -> dict:
    return {
        "classification": "NO_STRONGER_RUNTIME_COMPATIBLE_CANDIDATE_FOUND",
        "summary": {
            "best_candidate_per_family": {
                "MOMENTUM": {
                    "candidate_key": "XRPUSDTM:MOMENTUM:sell",
                    "symbol": "XRPUSDTM",
                    "canonical_strategy": "MOMENTUM",
                    "strategy": "MomentumV2",
                    "side": "sell",
                    "source": "rolling_quote_window",
                    "expected_net_after_full_cost": 0.010554720597791629,
                    "runtime_profile_exists": True,
                    "runtime_admissible": False,
                    "runtime_admissibility_classification": "NOT_RUNTIME_ADMISSIBLE_EDGE_BELOW_THRESHOLD",
                    "telemetry_gap_fields": [],
                    "contamination_counts": {"seed": 0, "fallback": 0, "mock": 0, "force_open": 0, "forced_cycle": 0},
                }
            }
        },
    }


def test_selects_clean_non_trend_targets_in_family_priority_order(tmp_path: Path) -> None:
    unit = tmp_path / "unit.json"
    plan = tmp_path / "plan.json"
    failure = tmp_path / "failure.json"
    stronger = tmp_path / "stronger.json"
    _write(unit, _unit_payload())
    _write(plan, _plan_payload())
    _write(failure, _failure_payload())
    _write(stronger, _stronger_payload())

    report = select_observation_targets(unit, plan, failure, stronger)

    assert report["classification"] == CLASS_TARGETS_SELECTED
    assert [target["candidate_key"] for target in report["selected_targets"][:3]] == [
        "SOLUSDTM:MOMENTUM:sell",
        "XRPUSDTM:MOMENTUM:sell",
        "BNBUSDTM:MEANREVERSION:sell",
    ]
    assert report["selected_targets"][0]["paper_validation_env"]["LIVE"] == "0"
    assert report["selected_targets"][0]["paper_validation_env"]["USE_MOCK"] == "0"
    assert report["profitability_claim"] is False


def test_blocks_when_unit_sanity_is_not_consistent(tmp_path: Path) -> None:
    unit = tmp_path / "unit.json"
    plan = tmp_path / "plan.json"
    failure = tmp_path / "failure.json"
    stronger = tmp_path / "stronger.json"
    _write(unit, _unit_payload("POST_SIGNAL_ALPHA_TARGET_UNIT_MISMATCH_FOUND"))
    _write(plan, _plan_payload())
    _write(failure, _failure_payload())
    _write(stronger, _stronger_payload())

    report = select_observation_targets(unit, plan, failure, stronger)

    assert report["classification"] == CLASS_BLOCKED_UNIT_MISMATCH
    assert report["selected_targets"] == []


def test_blocks_when_only_trendfollowing_evidence_exists(tmp_path: Path) -> None:
    unit = tmp_path / "unit.json"
    plan = tmp_path / "plan.json"
    failure = tmp_path / "failure.json"
    stronger = tmp_path / "stronger.json"
    payload = _failure_payload()
    payload["best_20_trajectory_events_by_net_opportunity"] = [
        row for row in payload["best_20_trajectory_events_by_net_opportunity"] if row["canonical_strategy"] == "TRENDFOLLOWING"
    ]
    _write(unit, _unit_payload())
    _write(plan, _plan_payload())
    _write(failure, payload)
    _write(stronger, {"classification": "NO_STRONGER_RUNTIME_COMPATIBLE_CANDIDATE_FOUND", "summary": {"best_candidate_per_family": {}}})

    report = select_observation_targets(unit, plan, failure, stronger)

    assert report["classification"] == CLASS_BLOCKED_NO_CLEAN_NON_TREND
    assert report["selected_targets"] == []
