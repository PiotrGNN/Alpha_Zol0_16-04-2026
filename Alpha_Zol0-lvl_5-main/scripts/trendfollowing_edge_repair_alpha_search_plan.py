from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def classify_next_action(
    *,
    final_verdict: str,
    max_expected_net_after_full_cost: float | None,
    clean_trade_with_ratio_count: int,
    lower_threshold_runtime_trades: int,
) -> dict[str, Any]:
    weak_edge = (
        str(final_verdict) == "THRESHOLD_CHANGE_NOT_JUSTIFIED_STRATEGY_EDGE_REPAIR_REQUIRED"
        and _safe_float(max_expected_net_after_full_cost, 0.0) < 0.08
    )
    no_lower_ratio_sample = int(clean_trade_with_ratio_count or 0) <= 0
    no_lower_threshold_trades = int(lower_threshold_runtime_trades or 0) <= 0
    if weak_edge and no_lower_ratio_sample and no_lower_threshold_trades:
        classification = "EDGE_REPAIR_AND_STRONGER_ALPHA_SEARCH"
    elif weak_edge:
        classification = "EDGE_REPAIR_WITH_PAPER_VALIDATION_REQUIRED"
    else:
        classification = "RECOMMENDATION_INCONCLUSIVE"
    return {
        "next_action_classification": classification,
        "threshold_patch_allowed": False,
        "ratio_patch_allowed": False,
        "strategy_patch_allowed": False,
        "paper_experiment_allowed": classification != "RECOMMENDATION_INCONCLUSIVE",
        "profitability_claim_allowed": False,
    }


def rank_alpha_search_lanes(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def score(row: dict[str, Any]) -> tuple[float, float]:
        strategy = str(row.get("strategy") or "")
        expected = _safe_float(row.get("max_expected_net_after_full_cost"), 0.0) or 0.0
        non_trend_bonus = 1.0 if strategy != "TrendFollowingV2" else 0.0
        return (non_trend_bonus, expected)

    ranked = sorted((dict(row) for row in candidates), key=score, reverse=True)
    for idx, row in enumerate(ranked, start=1):
        row["priority"] = idx
        row["minimum_expected_net_after_full_cost"] = 0.08
        row["current_runtime_semantics_required"] = True
    return ranked


def _candidate_rows_from_semantics(semantics: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, row in (semantics.get("candidate_level_findings") or {}).items():
        item = dict(row)
        item["candidate"] = key
        item["max_expected_net_after_full_cost"] = row.get(
            "highest_observed_expected_net_after_full_cost"
        )
        item["max_ratio"] = row.get("highest_observed_ratio")
        rows.append(item)
    return rows


def _lane_seed_candidates(semantics: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _candidate_rows_from_semantics(semantics)
    lanes = [
        {
            "strategy": "MicroBreakoutV2",
            "candidate_source": "fresh discovery required",
            "max_expected_net_after_full_cost": 0.08,
            "rationale": "search for impulse edges with expected_net_after_full_cost >= 0.08 under current gates",
        },
        {
            "strategy": "MomentumV2",
            "candidate_source": "fresh discovery required",
            "max_expected_net_after_full_cost": 0.08,
            "rationale": "one-tick impulse horizon may better match short PAPER exit geometry than ret_3 trend lag",
        },
        {
            "strategy": "MeanReversionV2",
            "candidate_source": "fresh discovery required",
            "max_expected_net_after_full_cost": 0.08,
            "rationale": "test opposite-side extreme reversion where stop-risk ratio can exceed 1.10 naturally",
        },
    ]
    lanes.extend(
        {
            "strategy": row.get("strategy"),
            "candidate": row.get("candidate"),
            "candidate_source": "current rejected runtime evidence",
            "max_expected_net_after_full_cost": row.get("max_expected_net_after_full_cost"),
            "max_ratio": row.get("max_ratio"),
            "rationale": "keep as repair benchmark, not as immediate runtime candidate",
        }
        for row in rows
    )
    return lanes


def build_repair_plan(
    *,
    semantics: dict[str, Any],
    ratio: dict[str, Any],
) -> dict[str, Any]:
    locked = semantics.get("locked_facts") or {}
    expected_stats = locked.get("expected_net_after_full_cost_stats") or {}
    matrix_trades = 0
    next_action = classify_next_action(
        final_verdict=str(semantics.get("final_verdict") or ""),
        max_expected_net_after_full_cost=_safe_float(expected_stats.get("max")),
        clean_trade_with_ratio_count=_safe_int(locked.get("clean_trade_with_ratio_count")),
        lower_threshold_runtime_trades=matrix_trades,
    )
    alpha_lanes = rank_alpha_search_lanes(_lane_seed_candidates(semantics))
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": next_action["next_action_classification"],
        "profitability_claim": False,
        "evidence": {
            "semantics_final_verdict": semantics.get("final_verdict"),
            "threshold_classification": semantics.get("threshold_classification"),
            "strategy_classification": semantics.get("strategy_classification"),
            "stop_risk_classification": semantics.get("stop_risk_classification"),
            "max_expected_net_after_full_cost": expected_stats.get("max"),
            "ratio_stats": locked.get("ratio_stats"),
            "clean_trade_with_ratio_count": locked.get("clean_trade_with_ratio_count"),
            "candidate_findings": semantics.get("candidate_level_findings"),
            "ratio_threshold_simulation": ratio.get("hypothetical_ratio_threshold_simulation"),
        },
        "patch_policy": {
            "do_not_lower_thresholds": True,
            "do_not_weaken_ratio_guard": True,
            "do_not_patch_strategy_without_offline_replay": True,
            "paper_only": True,
            "kucoin_only": True,
            "live_allowed": False,
        },
        "trendfollowing_repair_plan": [
            {
                "gate": "offline_expected_net_replay",
                "objective": "Replay TrendFollowingV2 ret_3 signals against current cost and risk formulas before any strategy mutation.",
                "required_evidence": [
                    "expected_move_raw",
                    "expected_move_scaled",
                    "expected_net_after_cost",
                    "expected_net_after_full_cost",
                    "entry_net_to_stop_ratio",
                    "MFE/MAE after signal timestamp where available",
                ],
                "pass_condition": "candidate families produce expected_net_after_full_cost >= 0.08 and ratio >= 1.10 without threshold relaxation",
            },
            {
                "gate": "signal_timing_audit",
                "objective": "Measure whether ret_3 enters after most move has already occurred.",
                "required_evidence": [
                    "signal_horizon_ticks",
                    "post-signal MFE",
                    "post-signal MAE",
                    "time_to_first_MFE",
                    "time_from_peak_to_close",
                ],
                "pass_condition": "post-signal MFE supports current expected_move formula after costs",
            },
            {
                "gate": "cost_burden_replay",
                "objective": "Separate weak signal from fee/spread/slippage overburden.",
                "required_evidence": [
                    "fee_round_trip_ratio",
                    "spread_ratio",
                    "slippage_ratio",
                    "expected_edge_after_fee",
                    "expected_net_after_cost",
                ],
                "pass_condition": "edge remains positive after current total cost ratio with margin to reach full-cost net >= 0.08",
            },
            {
                "gate": "paper_only_shadow_candidate_test",
                "objective": "Run clean PAPER-only runtime smoke only after offline replay finds stronger TFV2 parameter family.",
                "required_evidence": [
                    "LIVE=0",
                    "USE_MOCK=0",
                    "seed=0",
                    "fallback=0",
                    "force_open=0",
                    "position_open natural only",
                ],
                "pass_condition": "natural current-semantics admission, completed clean trades, no profitability claim until sufficient sample",
            },
        ],
        "stronger_alpha_search_plan": alpha_lanes,
        "rejected_current_candidates": [
            {
                "candidate": key,
                "reason": row.get("failure_classification"),
                "max_expected_net_after_full_cost": row.get(
                    "highest_observed_expected_net_after_full_cost"
                ),
                "max_ratio": row.get("highest_observed_ratio"),
            }
            for key, row in (semantics.get("candidate_level_findings") or {}).items()
        ],
        "execution_sequence": [
            "Do not mutate thresholds.",
            "Build/refresh clean discovery corpus under KuCoin PAPER only.",
            "Rank non-TrendFollowing and repaired TrendFollowing candidates by expected_net_after_full_cost >= 0.08 and ratio >= 1.10.",
            "Run one candidate at a time through clean current runtime smoke.",
            "Promote only candidates with natural opens and clean completed trade evidence; do not claim profitability before sample sufficiency.",
        ],
        "completion_criteria": {
            "minimum_expected_net_after_full_cost": 0.08,
            "minimum_entry_net_to_stop_ratio": 1.10,
            "current_runtime_semantics": True,
            "clean_natural_trade_sample_required_before_profitability_claim": True,
            "profitability_claim_allowed": False,
        },
        "next_action": next_action,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TrendFollowingV2 edge repair and stronger-alpha search plan",
        "",
        f"- classification: `{report.get('classification')}`",
        f"- profitability_claim: `{report.get('profitability_claim')}`",
        f"- max_expected_net_after_full_cost: `{(report.get('evidence') or {}).get('max_expected_net_after_full_cost')}`",
        f"- do_not_lower_thresholds: `{(report.get('patch_policy') or {}).get('do_not_lower_thresholds')}`",
        f"- live_allowed: `{(report.get('patch_policy') or {}).get('live_allowed')}`",
        "",
        "## TrendFollowingV2 repair gates",
    ]
    for item in report.get("trendfollowing_repair_plan") or []:
        lines.append(f"- {item['gate']}: {item['objective']} Pass: `{item['pass_condition']}`")
    lines.extend(["", "## Stronger-alpha search lanes"])
    for lane in report.get("stronger_alpha_search_plan") or []:
        lines.append(
            "- "
            f"P{lane.get('priority')} `{lane.get('strategy')}` source=`{lane.get('candidate_source')}` "
            f"min_expected=`{lane.get('minimum_expected_net_after_full_cost')}` "
            f"rationale=`{lane.get('rationale')}`"
        )
    lines.extend(["", "## Rejected current candidates"])
    for row in report.get("rejected_current_candidates") or []:
        lines.append(
            "- "
            f"{row.get('candidate')}: reason=`{row.get('reason')}`, "
            f"max_expected=`{row.get('max_expected_net_after_full_cost')}`, max_ratio=`{row.get('max_ratio')}`"
        )
    lines.extend(["", "## Execution sequence"])
    for item in report.get("execution_sequence") or []:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--semantics-json",
        type=Path,
        default=ANALYSIS_DIR / "strategy_threshold_semantics_autopsy_current.json",
    )
    parser.add_argument(
        "--ratio-json",
        type=Path,
        default=ANALYSIS_DIR / "entry_net_to_stop_ratio_calibration_current.json",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ANALYSIS_DIR / "trendfollowing_edge_repair_alpha_search_plan_current.json",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=ANALYSIS_DIR / "trendfollowing_edge_repair_alpha_search_plan_current.md",
    )
    args = parser.parse_args(argv)
    semantics = json.loads(args.semantics_json.read_text(encoding="utf-8"))
    ratio = json.loads(args.ratio_json.read_text(encoding="utf-8"))
    report = build_repair_plan(semantics=semantics, ratio=ratio)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    args.md_out.write_text(render_markdown(report), encoding="utf-8")
    print(report["classification"])
    print(args.json_out)
    print(args.md_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
