from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"

CLASS_CONSISTENT = "POST_SIGNAL_ALPHA_TARGET_UNITS_CONSISTENT"
CLASS_MISMATCH = "POST_SIGNAL_ALPHA_TARGET_UNIT_MISMATCH_FOUND"
CLASS_BLOCKED = "POST_SIGNAL_ALPHA_TARGET_UNIT_SANITY_BLOCKED_BY_MISSING_FIELDS"
CLASS_INCONCLUSIVE = "POST_SIGNAL_ALPHA_TARGET_UNIT_SANITY_INCONCLUSIVE"

FINAL_UNITS_CONSISTENT = "STRONGER_ALPHA_SEARCH_CONFIRMED_UNITS_CONSISTENT"
FINAL_ANALYZER_PATCH = "ANALYZER_UNIT_PATCH_REQUIRED"
FINAL_TELEMETRY_PATCH = "TELEMETRY_ONLY_PATCH_REQUIRED"
FINAL_INCONCLUSIVE = "UNIT_SANITY_AUDIT_INCONCLUSIVE"

DEFAULT_SOURCE_FILES = {
    "tracker": WORKDIR / "core/runtime_v2/post_signal_trajectory.py",
    "runtime_analyzer": WORKDIR / "scripts/analyze_runtime_post_signal_trajectory.py",
    "failure_analyzer": WORKDIR / "scripts/analyze_post_signal_alpha_target_failure.py",
}

REQUIRED_BEST_EVENT_FIELDS = (
    "signed_gross_move",
    "estimated_cost",
    "signed_net_move",
    "mfe",
    "mae",
    "expected_net_after_cost",
)


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _source_evidence(source_files: dict[str, Path] | None = None) -> dict[str, Any]:
    files = {**DEFAULT_SOURCE_FILES, **(source_files or {})}
    tracker = _read_source(Path(files["tracker"]))
    runtime_analyzer = _read_source(Path(files["runtime_analyzer"]))
    failure_analyzer = _read_source(Path(files["failure_analyzer"]))
    return {
        "files": {key: str(value) for key, value in files.items()},
        "raw_move_ratio_formula_present": "(float(quote.mid) - start_mid) / start_mid" in tracker,
        "signed_net_ratio_formula_present": "signed_net_move = signed_gross_move - estimated_cost" in tracker,
        "cost_ratio_source_present": "total_cost_ratio" in tracker,
        "runtime_analyzer_compares_p95_signed_net": (
            "p95_signed_net_move" in runtime_analyzer and "min_p95_signed_net" in runtime_analyzer
        ),
        "failure_mfe_from_signed_gross_present": (
            "mfe = max(gross, 0.0)" in failure_analyzer and "mae = abs(min(gross, 0.0))" in failure_analyzer
        ),
        "notional_full_cost_formula_present": (
            "expected_net_after_full_cost" in tracker
            and ("notional" in tracker or "final_notional" in tracker)
        ),
        "source_readable": bool(tracker and runtime_analyzer and failure_analyzer),
    }


def _best_event(failure_artifact: dict[str, Any]) -> dict[str, Any]:
    rows = failure_artifact.get("best_20_trajectory_events_by_net_opportunity")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    rows = failure_artifact.get("best_events_by_net_opportunity")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return {}


def _missing_best_event_fields(best_event: dict[str, Any]) -> list[str]:
    return [field for field in REQUIRED_BEST_EVENT_FIELDS if best_event.get(field) in (None, "")]


def _infer_alpha_target_unit(runtime_artifact: dict[str, Any], source: dict[str, Any]) -> tuple[str, str]:
    inputs = runtime_artifact.get("inputs") if isinstance(runtime_artifact.get("inputs"), dict) else {}
    explicit = inputs.get("min_p95_signed_net_unit") or inputs.get("alpha_target_unit")
    if explicit:
        normalized = str(explicit).strip()
        return normalized, "explicit_artifact_unit"
    if "min_p95_signed_net_usdt" in inputs or "alpha_target_usdt" in inputs:
        return "USDT", "artifact_usdt_key"
    if "min_p95_signed_net" in inputs and source.get("runtime_analyzer_compares_p95_signed_net"):
        return "ratio", "derived_from_p95_signed_net_move_comparison"
    return "unknown", "no_target_unit_evidence"


def _unit_findings(
    runtime_artifact: dict[str, Any],
    failure_artifact: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    alpha_unit, alpha_reason = _infer_alpha_target_unit(runtime_artifact, source)
    movement_unit = "ratio" if source.get("raw_move_ratio_formula_present") else "unknown"
    cost_unit = "ratio" if source.get("cost_ratio_source_present") else "unknown"
    net_unit = "ratio" if source.get("signed_net_ratio_formula_present") and movement_unit == cost_unit == "ratio" else "unknown"
    mfe_unit = "ratio" if source.get("failure_mfe_from_signed_gross_present") and movement_unit == "ratio" else "unknown"
    expected_unit = "ratio"
    best_event = _best_event(failure_artifact)
    if best_event and best_event.get("expected_net_after_cost") in (None, ""):
        expected_unit = "unknown"
    return {
        "alpha_target": {"unit": alpha_unit, "reason": alpha_reason},
        "signed_gross_move": {"unit": movement_unit, "reason": "quote_mid_relative_delta"},
        "MFE": {"unit": mfe_unit, "reason": "max_positive_signed_gross_move"},
        "MAE": {"unit": mfe_unit, "reason": "absolute_negative_signed_gross_move"},
        "estimated_cost": {"unit": cost_unit, "reason": "total_cost_ratio_or_ratio_components"},
        "signed_net_move": {"unit": net_unit, "reason": "signed_gross_move_minus_estimated_cost"},
        "expected_net_after_cost": {"unit": expected_unit, "reason": "candidate.expected_net_after_cost_ratio"},
        "expected_net_after_full_cost": {
            "unit": "USDT" if source.get("notional_full_cost_formula_present") else "not_present_in_post_signal_tracker",
            "reason": "requires_notional_multiplication",
        },
    }


def _compatibility(unit_findings: dict[str, Any]) -> dict[str, bool]:
    alpha_unit = str(unit_findings["alpha_target"]["unit"])
    return {
        "p95_signed_net_vs_alpha_target": unit_findings["signed_net_move"]["unit"] == alpha_unit,
        "mfe_vs_cost_burden": unit_findings["MFE"]["unit"] == unit_findings["estimated_cost"]["unit"],
        "expected_net_vs_post_signal_mfe": unit_findings["expected_net_after_cost"]["unit"] == unit_findings["MFE"]["unit"],
    }


def _normalization_check(runtime_artifact: dict[str, Any], failure_artifact: dict[str, Any]) -> dict[str, Any]:
    inputs = runtime_artifact.get("inputs") if isinstance(runtime_artifact.get("inputs"), dict) else {}
    target = _safe_float(inputs.get("min_p95_signed_net"))
    best = _best_event(failure_artifact)
    best_net = _safe_float(best.get("signed_net_move"))
    best_mfe = _safe_float(best.get("mfe"))
    ratio_to_target = (best_net / target) if best_net is not None and target not in (None, 0.0) else None
    return {
        "alpha_target_value": target,
        "best_signed_net_move": best_net,
        "best_mfe": best_mfe,
        "best_event_remains_far_from_target": (
            bool(best_net is not None and target is not None and best_net < target * 0.25)
        ),
        "best_net_to_target_ratio": ratio_to_target,
    }


def _classify(
    runtime_artifact: dict[str, Any] | None,
    failure_artifact: dict[str, Any] | None,
    source: dict[str, Any],
    unit_findings: dict[str, Any] | None,
    compatibility: dict[str, bool] | None,
    missing_fields: list[str],
) -> str:
    if runtime_artifact is None or failure_artifact is None or not source.get("source_readable"):
        return CLASS_INCONCLUSIVE
    alpha_unit = str((unit_findings or {}).get("alpha_target", {}).get("unit", "unknown"))
    if alpha_unit == "USDT" and missing_fields:
        return CLASS_BLOCKED
    if alpha_unit == "unknown":
        return CLASS_INCONCLUSIVE
    if compatibility and not compatibility.get("p95_signed_net_vs_alpha_target", False):
        return CLASS_MISMATCH
    if compatibility and all(compatibility.values()):
        return CLASS_CONSISTENT
    return CLASS_INCONCLUSIVE


def _final_verdict(classification: str) -> str:
    return {
        CLASS_CONSISTENT: FINAL_UNITS_CONSISTENT,
        CLASS_MISMATCH: FINAL_ANALYZER_PATCH,
        CLASS_BLOCKED: FINAL_TELEMETRY_PATCH,
        CLASS_INCONCLUSIVE: FINAL_INCONCLUSIVE,
    }[classification]


def stronger_alpha_search_plan() -> dict[str, Any]:
    return {
        "classification": "STRONGER_ALPHA_SEARCH_PLAN_READY",
        "scope": {
            "mode": "PAPER_ONLY",
            "exchange": "KuCoin",
            "forbidden_changes": [
                "threshold_mutation",
                "strategy_patch",
                "readiness_mutation",
                "execution_semantics_mutation",
                "LIVE",
                "fallback",
                "seed",
                "force_open",
            ],
        },
        "ranked_families": [
            {
                "rank": 1,
                "family": "MicroBreakoutV2",
                "role": "primary_search",
                "signal_hypothesis": "Short-horizon order-flow/quote-window impulse can create post-cost signed movement before spread decay.",
                "expected_source_of_edge": "Fresh rolling_quote_window compression-to-expansion movement with low spread burden.",
                "required_runtime_compatible_telemetry": [
                    "rolling_quote_window source",
                    "post_signal_trajectory_v2 horizons",
                    "expected_net_after_cost",
                    "estimated_cost",
                    "runtime_profile_key",
                    "contamination_flags",
                ],
                "candidate_promotion_criteria": [
                    "clean source=rolling_quote_window",
                    "non-contaminated seed/fallback/mock/force_open/forced_cycle flags",
                    "sample_count >= 20 per symbol/side/horizon bucket",
                    "p95_signed_net_move >= 0.12 in the same ratio unit as trajectory net",
                    "expected_net_after_cost remains positive after total_cost_ratio",
                ],
                "post_signal_target_criteria": "p95 signed_net_move ratio >= configured alpha target with best MFE not dominated by cost.",
                "cost_fee_spread_guards": "Reject buckets where max MFE <= median estimated_cost or cost fields are missing.",
                "stop_risk_ratio_requirements": "Require stop_risk telemetry before promotion to execution; fail closed if ratio is missing.",
                "fail_closed_conditions": [
                    "unit mismatch",
                    "missing trajectory cost fields",
                    "contaminated evidence",
                    "public-kline-only source",
                    "insufficient sample",
                ],
                "paper_validation_path": "Run PAPER-only capture with RUNTIME_V2_POST_SIGNAL_TRAJECTORY=1, LIVE=0, USE_MOCK=0, no seed/fallback/force-open; analyze only natural post_signal_trajectory_v2 rows.",
            },
            {
                "rank": 2,
                "family": "MomentumV2",
                "role": "secondary_search",
                "signal_hypothesis": "Directional continuation after quote-window momentum can exceed fee/spread burden in selected symbol/side buckets.",
                "expected_source_of_edge": "Rolling quote-window continuation where signed movement persists through 3-5 tick horizons.",
                "required_runtime_compatible_telemetry": [
                    "rolling_quote_window source",
                    "signal_horizon_ticks",
                    "post_signal_trajectory_v2 horizon distribution",
                    "expected_net_after_cost",
                    "estimated_cost",
                ],
                "candidate_promotion_criteria": [
                    "clean non-TrendFollowing bucket",
                    "sample_count >= 20",
                    "p95_signed_net_move >= 0.12 ratio target",
                    "median MFE minus cost burden > 0",
                ],
                "post_signal_target_criteria": "3/5 tick p95 signed_net_move reaches ratio target without adverse MAE dominance.",
                "cost_fee_spread_guards": "Reject if median estimated_cost exceeds median MFE.",
                "stop_risk_ratio_requirements": "Require expected net to stop-risk ratio telemetry before any runtime gate promotion.",
                "fail_closed_conditions": [
                    "horizon mismatch not explained by telemetry",
                    "missing cost fields",
                    "contamination",
                    "sample below contract",
                ],
                "paper_validation_path": "Observe naturally rejected/admitted MomentumV2 candidates in PAPER-only runtime and compare against TrendFollowing baseline.",
            },
            {
                "rank": 3,
                "family": "MeanReversionV2",
                "role": "tertiary_search",
                "signal_hypothesis": "Quote-window overextension can revert enough to create post-cost signed net movement.",
                "expected_source_of_edge": "Short horizon reversion after local quote-window extremes, especially sell-side overextension buckets.",
                "required_runtime_compatible_telemetry": [
                    "rolling_quote_window source",
                    "post_signal_trajectory_v2 h1/h3 observations",
                    "estimated_cost",
                    "expected_net_after_cost",
                    "reason_code",
                ],
                "candidate_promotion_criteria": [
                    "clean bucket with sample_count >= 20",
                    "p95_signed_net_move >= 0.12 ratio target",
                    "best events repeat across more than one run or timestamp cluster",
                ],
                "post_signal_target_criteria": "h1/h3 signed_net_move p95 reaches ratio target and does not rely on one isolated event.",
                "cost_fee_spread_guards": "Reject if max MFE is only marginally above estimated_cost or spread burden is unstable.",
                "stop_risk_ratio_requirements": "Require stop-risk and entry-net-to-stop ratio telemetry for promotion beyond research.",
                "fail_closed_conditions": [
                    "single-event only evidence",
                    "missing expected fields",
                    "contaminated evidence",
                    "unit mismatch",
                ],
                "paper_validation_path": "Focus PAPER observation on best clean near-target symbol/side only after unit sanity remains consistent.",
            },
            {
                "rank": 4,
                "family": "TrendFollowingV2",
                "role": "demoted_comparator_only",
                "signal_hypothesis": "Baseline directional continuation comparator, not primary stronger-alpha source.",
                "expected_source_of_edge": "Existing runtime-compatible TrendFollowing quote-window behavior.",
                "required_runtime_compatible_telemetry": [
                    "rolling_quote_window source",
                    "post_signal_trajectory_v2",
                    "expected_net_after_cost",
                    "estimated_cost",
                ],
                "candidate_promotion_criteria": [
                    "comparator only",
                    "do not promote over non-TrendFollowing unless explicitly requested",
                ],
                "post_signal_target_criteria": "Used to benchmark non-TrendFollowing MFE/net opportunity only.",
                "cost_fee_spread_guards": "Same cost dominance checks as primary families.",
                "stop_risk_ratio_requirements": "Comparator ratio telemetry only.",
                "fail_closed_conditions": [
                    "treated as primary stronger-alpha candidate",
                    "contaminated evidence",
                    "source mismatch",
                ],
                "paper_validation_path": "Keep as baseline in the same PAPER-only post-signal reports.",
            },
        ],
    }


def render_search_plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# Stronger Alpha Search Plan",
        "",
        f"- classification: `{plan['classification']}`",
        f"- mode: `{plan['scope']['mode']}`",
        f"- exchange: `{plan['scope']['exchange']}`",
        "",
        "## Ranked Families",
    ]
    for family in plan["ranked_families"]:
        lines.extend(
            [
                f"- `{family['rank']}. {family['family']}` role=`{family['role']}`",
                f"  - hypothesis: {family['signal_hypothesis']}",
                f"  - promotion: {'; '.join(family['candidate_promotion_criteria'])}",
                f"  - validation: {family['paper_validation_path']}",
            ]
        )
    return "\n".join(lines) + "\n"


def analyze_unit_sanity(
    runtime_artifact: Path | str,
    failure_artifact: Path | str,
    *,
    source_files: dict[str, Path] | None = None,
) -> dict[str, Any]:
    runtime_path = Path(runtime_artifact)
    failure_path = Path(failure_artifact)
    runtime = _read_json(runtime_path)
    failure = _read_json(failure_path)
    source = _source_evidence(source_files)
    if runtime is None or failure is None:
        classification = CLASS_INCONCLUSIVE
        unit_findings: dict[str, Any] = {}
        compatibility: dict[str, bool] = {}
        missing_fields: list[str] = []
        normalization = {}
    else:
        best = _best_event(failure)
        missing_fields = _missing_best_event_fields(best)
        unit_findings = _unit_findings(runtime, failure, source)
        compatibility = _compatibility(unit_findings)
        normalization = _normalization_check(runtime, failure)
        classification = _classify(runtime, failure, source, unit_findings, compatibility, missing_fields)
    return {
        "classification": classification,
        "final_verdict": _final_verdict(classification),
        "inputs": {
            "runtime_artifact": str(runtime_path),
            "failure_artifact": str(failure_path),
        },
        "source_evidence": source,
        "unit_findings": unit_findings,
        "comparison_compatibility": compatibility,
        "normalization_check": normalization,
        "blocking_missing_fields": missing_fields if classification == CLASS_BLOCKED else [],
        "summary": {
            "runtime_artifact_classification": runtime.get("classification") if runtime else None,
            "failure_artifact_classification": failure.get("classification") if failure else None,
            "trajectory_event_count": ((runtime or {}).get("summary") or {}).get("trajectory_event_count"),
            "clean_event_count": ((runtime or {}).get("summary") or {}).get("clean_event_count"),
            "alpha_target_count": ((runtime or {}).get("summary") or {}).get("alpha_target_count"),
        },
        "patch_decision": _patch_decision(classification),
    }


def _patch_decision(classification: str) -> dict[str, Any]:
    if classification == CLASS_CONSISTENT:
        return {
            "patch_runtime": False,
            "patch_analyzer": False,
            "create_stronger_alpha_search_plan": True,
            "reason": "alpha target and trajectory net are unit-compatible ratio values",
        }
    if classification == CLASS_MISMATCH:
        return {
            "patch_runtime": False,
            "patch_analyzer": True,
            "create_stronger_alpha_search_plan": False,
            "reason": "analyzer/reporting compares incompatible target and trajectory units",
        }
    if classification == CLASS_BLOCKED:
        return {
            "patch_runtime": False,
            "patch_analyzer": False,
            "create_stronger_alpha_search_plan": False,
            "reason": "normalization is blocked by missing telemetry fields",
        }
    return {
        "patch_runtime": False,
        "patch_analyzer": False,
        "create_stronger_alpha_search_plan": False,
        "reason": "unit evidence is inconclusive",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Post-Signal Alpha Target Unit Sanity Audit",
        "",
        f"- classification: `{report['classification']}`",
        f"- final_verdict: `{report['final_verdict']}`",
        f"- runtime_artifact_classification: `{report['summary']['runtime_artifact_classification']}`",
        f"- failure_artifact_classification: `{report['summary']['failure_artifact_classification']}`",
        f"- trajectory_event_count: `{report['summary']['trajectory_event_count']}`",
        f"- clean_event_count: `{report['summary']['clean_event_count']}`",
        f"- alpha_target_count: `{report['summary']['alpha_target_count']}`",
        "",
        "## Unit Findings",
    ]
    for name, finding in report["unit_findings"].items():
        lines.append(f"- {name}: unit=`{finding['unit']}` reason=`{finding['reason']}`")
    lines.extend(["", "## Compatibility"])
    for name, value in report["comparison_compatibility"].items():
        lines.append(f"- {name}: `{value}`")
    lines.extend(["", "## Normalization Check"])
    for name, value in report["normalization_check"].items():
        lines.append(f"- {name}: `{value}`")
    lines.extend(
        [
            "",
            "## Patch Decision",
            f"- patch_runtime: `{report['patch_decision']['patch_runtime']}`",
            f"- patch_analyzer: `{report['patch_decision']['patch_analyzer']}`",
            f"- create_stronger_alpha_search_plan: `{report['patch_decision']['create_stronger_alpha_search_plan']}`",
            f"- reason: {report['patch_decision']['reason']}",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-artifact", default="analysis/runtime_post_signal_trajectory_current.json")
    parser.add_argument("--failure-artifact", default="analysis/post_signal_alpha_target_failure_current.json")
    parser.add_argument("--output-json", default="analysis/post_signal_alpha_target_unit_sanity_current.json")
    parser.add_argument("--output-md", default="analysis/post_signal_alpha_target_unit_sanity_current.md")
    parser.add_argument("--search-plan-json", default="analysis/stronger_alpha_search_plan_current.json")
    parser.add_argument("--search-plan-md", default="analysis/stronger_alpha_search_plan_current.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = analyze_unit_sanity(WORKDIR / args.runtime_artifact, WORKDIR / args.failure_artifact)
    output_json = WORKDIR / args.output_json
    output_md = WORKDIR / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    if report["classification"] == CLASS_CONSISTENT:
        plan = stronger_alpha_search_plan()
        search_plan_json = WORKDIR / args.search_plan_json
        search_plan_md = WORKDIR / args.search_plan_md
        search_plan_json.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
        search_plan_md.write_text(render_search_plan_markdown(plan), encoding="utf-8")
    print(report["classification"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
