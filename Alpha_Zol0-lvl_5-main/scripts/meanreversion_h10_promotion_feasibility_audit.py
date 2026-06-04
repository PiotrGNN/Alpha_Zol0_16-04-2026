from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]

CLASS_PATCH_REQUIRED = "MEANREVERSION_H10_PROMOTION_PATCH_REQUIRED"
CLASS_ALREADY_REACHABLE = "MEANREVERSION_H10_ALREADY_RUNTIME_REACHABLE"
CLASS_NO_OPERATING_POINT = "MEANREVERSION_H10_NO_OPERATING_POINT"
CLASS_CONTAMINATED = "MEANREVERSION_H10_EVIDENCE_CONTAMINATED"
CLASS_INCONCLUSIVE = "MEANREVERSION_H10_PROMOTION_INCONCLUSIVE"

OPERATING_POINT_FOUND = "PROFITABILITY_OPERATING_POINT_CANDIDATE_FOUND"
EDGE_FILTER_BLOCKER = "STRONGER_ALPHA_OBSERVATION_BLOCKED_BY_ENTRY_EDGE_FILTER"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _meanreversion_block(source: str) -> str:
    match = re.search(r"class\s+MeanReversionV2\b(?P<body>.*?)(?:\nclass\s+\w+|\Z)", source, re.S)
    return match.group("body") if match else ""


def _extract_strategy_source(strategy_source_path: Path) -> dict[str, Any]:
    source = strategy_source_path.read_text(encoding="utf-8")
    block = _meanreversion_block(source)
    formula = None
    formula_match = re.search(r'"expected_move_formula"\s*:\s*"([^"]+)"', block)
    if formula_match:
        formula = formula_match.group(1)
    else:
        assignment_match = re.search(r"expected_move\s*=\s*([^\n]+)", block)
        if assignment_match:
            formula = assignment_match.group(1).strip()
    horizon = None
    horizon_match = re.search(r'"signal_horizon_ticks"\s*:\s*([0-9]+)', block)
    if horizon_match:
        horizon = int(horizon_match.group(1))
    formula_uses_ret3 = bool(formula and "ret_3" in formula)
    formula_uses_h10 = bool(formula and ("h10" in formula.lower() or "ret_10" in formula))
    return {
        "path": str(strategy_source_path),
        "meanreversion_found": bool(block),
        "meanreversion_formula": formula,
        "meanreversion_signal_horizon_ticks": horizon,
        "formula_uses_ret3": formula_uses_ret3,
        "formula_uses_h10": formula_uses_h10,
    }


def _is_meanreversion_h10(point: dict[str, Any] | None) -> bool:
    if not isinstance(point, dict):
        return False
    return (
        str(point.get("canonical_strategy") or "").upper() == "MEANREVERSION"
        and str(point.get("side") or "").lower() == "sell"
        and _safe_int(point.get("horizon_ticks")) == 10
        and bool(point.get("passes_operating_point"))
    )


def _contaminated(operating: dict[str, Any], blocker: dict[str, Any]) -> bool:
    op_summary = operating.get("summary") or {}
    blocker_summary = blocker.get("summary") or {}
    return _safe_int(op_summary.get("contaminated_event_count")) > 0 or _safe_int(
        blocker_summary.get("contaminated_event_count")
    ) > 0


def _position_open_count(blocker: dict[str, Any], operating: dict[str, Any]) -> int:
    blocker_summary = blocker.get("summary") or {}
    operating_summary = operating.get("summary") or {}
    return max(_safe_int(blocker_summary.get("position_open_count")), _safe_int(operating_summary.get("position_open_count")))


def _classify(operating: dict[str, Any], blocker: dict[str, Any], strategy_source: dict[str, Any]) -> str:
    selected = operating.get("best_operating_point")
    if _contaminated(operating, blocker):
        return CLASS_CONTAMINATED
    if _position_open_count(blocker, operating) > 0:
        return CLASS_ALREADY_REACHABLE
    if operating.get("classification") != OPERATING_POINT_FOUND or not _is_meanreversion_h10(selected):
        return CLASS_NO_OPERATING_POINT
    if (
        blocker.get("classification") == EDGE_FILTER_BLOCKER
        and _safe_int((blocker.get("target_reason_counts") or {}).get("entry_edge_filtered")) > 0
        and strategy_source["meanreversion_found"]
        and strategy_source["meanreversion_signal_horizon_ticks"] == 3
        and strategy_source["formula_uses_ret3"]
        and not strategy_source["formula_uses_h10"]
    ):
        return CLASS_PATCH_REQUIRED
    return CLASS_INCONCLUSIVE


def _decision(classification: str) -> dict[str, Any]:
    if classification == CLASS_PATCH_REQUIRED:
        return {
            "next_step": "test_first_meanreversion_h10_strategy_calibration_patch",
            "patch_strategy": True,
            "patch_threshold": False,
            "patch_risk": False,
            "patch_readiness": False,
            "patch_execution": False,
            "reason": "clean h10 MEANREVERSION sell operating point exists but runtime is blocked by entry edge filtering while strategy still estimates MeanReversionV2 on ret_3 horizon",
        }
    if classification == CLASS_ALREADY_REACHABLE:
        return {
            "next_step": "paper_validate_trade_outcomes_without_strategy_patch",
            "patch_strategy": False,
            "patch_threshold": False,
            "patch_risk": False,
            "patch_readiness": False,
            "patch_execution": False,
            "reason": "runtime already opened positions for this path",
        }
    if classification == CLASS_CONTAMINATED:
        return {
            "next_step": "discard_evidence_and_repeat_clean_paper",
            "patch_strategy": False,
            "patch_threshold": False,
            "patch_risk": False,
            "patch_readiness": False,
            "patch_execution": False,
            "reason": "contaminated evidence cannot justify promotion",
        }
    if classification == CLASS_NO_OPERATING_POINT:
        return {
            "next_step": "continue_observation_or_design_new_alpha",
            "patch_strategy": False,
            "patch_threshold": False,
            "patch_risk": False,
            "patch_readiness": False,
            "patch_execution": False,
            "reason": "no clean passing MEANREVERSION sell h10 operating point is present",
        }
    return {
        "next_step": "collect_missing_promotion_evidence",
        "patch_strategy": False,
        "patch_threshold": False,
        "patch_risk": False,
        "patch_readiness": False,
        "patch_execution": False,
        "reason": "promotion prerequisites are not all directly confirmed",
    }


def audit_promotion_feasibility(
    operating_point_artifact: Path | str,
    blocker_artifact: Path | str,
    strategy_source_path: Path | str,
) -> dict[str, Any]:
    operating_path = Path(operating_point_artifact)
    blocker_path = Path(blocker_artifact)
    strategy_path = Path(strategy_source_path)
    operating = _read_json(operating_path)
    blocker = _read_json(blocker_path)
    strategy_source = _extract_strategy_source(strategy_path)
    classification = _classify(operating, blocker, strategy_source)
    selected = operating.get("best_operating_point") if classification in {CLASS_PATCH_REQUIRED, CLASS_ALREADY_REACHABLE} else None
    return {
        "classification": classification,
        "inputs": {
            "operating_point_artifact": str(operating_path),
            "blocker_artifact": str(blocker_path),
            "strategy_source_path": str(strategy_path),
        },
        "summary": {
            "operating_point_classification": operating.get("classification"),
            "blocker_classification": blocker.get("classification"),
            "position_open_count": _position_open_count(blocker, operating),
            "entry_edge_filtered_count": _safe_int((blocker.get("target_reason_counts") or {}).get("entry_edge_filtered")),
            "operating_clean_event_count": _safe_int((operating.get("summary") or {}).get("clean_event_count")),
            "operating_contaminated_event_count": _safe_int((operating.get("summary") or {}).get("contaminated_event_count")),
            "blocker_contaminated_event_count": _safe_int((blocker.get("summary") or {}).get("contaminated_event_count")),
        },
        "selected_operating_point": selected,
        "strategy_source": strategy_source,
        "minimal_patch_boundary": {
            "allowed_candidate": "core/runtime_v2/strategy_stack.py::MeanReversionV2",
            "allowed_change": "calibrate MeanReversionV2 expected_move and signal_horizon_ticks to the observed h10 operating point",
            "forbidden_changes": [
                "ENTRY_MIN_NET_USDT threshold",
                "V2_MIN_EXPECTED_NET_RATIO threshold",
                "risk gate semantics",
                "readiness gate semantics",
                "execution semantics",
                "LIVE mode",
                "seed/fallback/force-open paths",
            ],
            "paper_validation_path": "BTCUSDTM/BNBUSDTM MEANREVERSION sell h10 PAPER-only admission and natural trade validation",
        },
        "decision": _decision(classification),
        "profitability_claim": False,
    }


def render_markdown(report: dict[str, Any]) -> str:
    selected = report.get("selected_operating_point")
    lines = [
        "# MeanReversion H10 Promotion Feasibility Audit",
        "",
        f"- classification: `{report['classification']}`",
        f"- profitability_claim: `{report['profitability_claim']}`",
        f"- next_step: `{report['decision']['next_step']}`",
        f"- patch_strategy: `{report['decision']['patch_strategy']}`",
        f"- patch_threshold: `{report['decision']['patch_threshold']}`",
        f"- position_open_count: `{report['summary']['position_open_count']}`",
        f"- entry_edge_filtered_count: `{report['summary']['entry_edge_filtered_count']}`",
        "",
        "## Selected Operating Point",
    ]
    if selected:
        lines.append(
            "- `{candidate}` samples=`{samples}` win_rate=`{win_rate}` payoff=`{payoff}` expectancy=`{expectancy}` cost_to_gross=`{cost}`".format(
                candidate=selected.get("candidate_key"),
                samples=selected.get("sample_count"),
                win_rate=selected.get("win_rate"),
                payoff=selected.get("payoff_ratio"),
                expectancy=selected.get("expectancy_per_signal"),
                cost=selected.get("cost_to_gross_ratio"),
            )
        )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Strategy Source",
            f"- meanreversion_formula: `{report['strategy_source']['meanreversion_formula']}`",
            f"- meanreversion_signal_horizon_ticks: `{report['strategy_source']['meanreversion_signal_horizon_ticks']}`",
            f"- formula_uses_ret3: `{report['strategy_source']['formula_uses_ret3']}`",
            f"- formula_uses_h10: `{report['strategy_source']['formula_uses_h10']}`",
            "",
            "## Minimal Patch Boundary",
            f"- allowed_candidate: `{report['minimal_patch_boundary']['allowed_candidate']}`",
            f"- allowed_change: `{report['minimal_patch_boundary']['allowed_change']}`",
            f"- paper_validation_path: `{report['minimal_patch_boundary']['paper_validation_path']}`",
            "",
            "## Forbidden Changes",
        ]
    )
    for item in report["minimal_patch_boundary"]["forbidden_changes"]:
        lines.append(f"- `{item}`")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--operating-point-artifact",
        default="analysis/profitability_operating_point_combined_20260604_121000_122000.json",
    )
    parser.add_argument(
        "--blocker-artifact",
        default="analysis/stronger_alpha_observation_blockers_20260604_122000.json",
    )
    parser.add_argument("--strategy-source", default="core/runtime_v2/strategy_stack.py")
    parser.add_argument("--output-json", default="analysis/meanreversion_h10_promotion_feasibility_current.json")
    parser.add_argument("--output-md", default="analysis/meanreversion_h10_promotion_feasibility_current.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit_promotion_feasibility(
        WORKDIR / args.operating_point_artifact,
        WORKDIR / args.blocker_artifact,
        WORKDIR / args.strategy_source,
    )
    output_json = WORKDIR / args.output_json
    output_md = WORKDIR / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(report["classification"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
