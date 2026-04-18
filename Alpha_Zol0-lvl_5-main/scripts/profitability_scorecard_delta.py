from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"

MATERIAL_ALPHA_SCORE_DELTA = 10.0
MATERIAL_COST_SCORE_DELTA = 5.0


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _index_areas(scorecard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(area.get("id") or ""): area
        for area in (scorecard.get("areas") or [])
        if isinstance(area, dict)
    }


def _workspace_rel(path_value: str | Path) -> str:
    path = Path(path_value)
    try:
        return str(path.resolve().relative_to(WORKDIR.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def build_delta(
    *,
    baseline_path: Path,
    candidate_path: Path,
) -> dict[str, Any]:
    baseline = _load_json(baseline_path)
    candidate = _load_json(candidate_path)
    baseline_kpis = baseline.get("global_kpis") or {}
    candidate_kpis = candidate.get("global_kpis") or {}
    baseline_areas = _index_areas(baseline)
    candidate_areas = _index_areas(candidate)

    baseline_avg_trade_count = _safe_float(baseline_kpis.get("avg_trade_count"))
    candidate_avg_trade_count = _safe_float(candidate_kpis.get("avg_trade_count"))
    baseline_avg_pf = _safe_float(baseline_kpis.get("avg_profit_factor"))
    candidate_avg_pf = _safe_float(candidate_kpis.get("avg_profit_factor"))
    baseline_avg_net = _safe_float(baseline_kpis.get("avg_net_pnl"))
    candidate_avg_net = _safe_float(candidate_kpis.get("avg_net_pnl"))

    alpha_before = _safe_float(
        (baseline_areas.get("AlphaSelection") or {}).get("score")
    )
    alpha_after = _safe_float(
        (candidate_areas.get("AlphaSelection") or {}).get("score")
    )
    cost_before = _safe_float(
        (baseline_areas.get("CostEfficiency") or {}).get("score")
    )
    cost_after = _safe_float(
        (candidate_areas.get("CostEfficiency") or {}).get("score")
    )
    data_before = _safe_float(
        (baseline_areas.get("DataIntegrity") or {}).get("score")
    )
    data_after = _safe_float(
        (candidate_areas.get("DataIntegrity") or {}).get("score")
    )
    ops_before = _safe_float(
        (baseline_areas.get("OperationalReadiness") or {}).get("score")
    )
    ops_after = _safe_float(
        (candidate_areas.get("OperationalReadiness") or {}).get("score")
    )

    pass_criteria = {
        "alpha_selection_material_improvement": {
            "passed": (alpha_after - alpha_before) >= MATERIAL_ALPHA_SCORE_DELTA,
            "threshold": f"delta >= {MATERIAL_ALPHA_SCORE_DELTA}",
            "before": alpha_before,
            "after": alpha_after,
            "delta": round(alpha_after - alpha_before, 6),
        },
        "cost_efficiency_material_improvement": {
            "passed": (cost_after - cost_before) >= MATERIAL_COST_SCORE_DELTA,
            "threshold": f"delta >= {MATERIAL_COST_SCORE_DELTA}",
            "before": cost_before,
            "after": cost_after,
            "delta": round(cost_after - cost_before, 6),
        },
        "entry_funnel_not_collapsed": {
            "passed": candidate_avg_trade_count >= baseline_avg_trade_count,
            "threshold": f"avg_trade_count >= {baseline_avg_trade_count}",
            "before": baseline_avg_trade_count,
            "after": candidate_avg_trade_count,
            "delta": round(candidate_avg_trade_count - baseline_avg_trade_count, 6),
        },
        "avg_profit_factor_improved": {
            "passed": candidate_avg_pf > baseline_avg_pf,
            "threshold": f"avg_profit_factor > {baseline_avg_pf}",
            "before": baseline_avg_pf,
            "after": candidate_avg_pf,
            "delta": round(candidate_avg_pf - baseline_avg_pf, 6),
        },
        "avg_net_pnl_improved": {
            "passed": candidate_avg_net > baseline_avg_net,
            "threshold": f"avg_net_pnl > {baseline_avg_net}",
            "before": baseline_avg_net,
            "after": candidate_avg_net,
            "delta": round(candidate_avg_net - baseline_avg_net, 6),
        },
        "data_integrity_no_regression": {
            "passed": data_after >= data_before,
            "threshold": f"data_integrity_score >= {data_before}",
            "before": data_before,
            "after": data_after,
            "delta": round(data_after - data_before, 6),
        },
        "operational_readiness_no_regression": {
            "passed": ops_after >= ops_before,
            "threshold": f"operational_readiness_score >= {ops_before}",
            "before": ops_before,
            "after": ops_after,
            "delta": round(ops_after - ops_before, 6),
        },
    }

    alpha_improved = pass_criteria["alpha_selection_material_improvement"]["passed"]
    cost_improved = pass_criteria["cost_efficiency_material_improvement"]["passed"]
    funnel_ok = pass_criteria["entry_funnel_not_collapsed"]["passed"]
    pf_ok = pass_criteria["avg_profit_factor_improved"]["passed"]
    net_ok = pass_criteria["avg_net_pnl_improved"]["passed"]
    integrity_ok = pass_criteria["data_integrity_no_regression"]["passed"]
    ops_ok = pass_criteria["operational_readiness_no_regression"]["passed"]

    if not funnel_ok:
        final_classification = "ENTRY_FUNNEL_COLLAPSED_AFTER_FILTER_TIGHTENING"
    elif alpha_improved and cost_improved and pf_ok and net_ok and integrity_ok and ops_ok:
        if candidate_avg_pf > 1.0 and candidate_avg_net > 0.0:
            final_classification = "MATERIAL_PROFITABILITY_IMPROVEMENT_CONFIRMED"
        else:
            final_classification = "ALPHA_AND_COST_FILTER_IMPROVED_BUT_STILL_NOT_PROFITABLE"
    else:
        final_classification = "NO_MEANINGFUL_ECONOMIC_IMPROVEMENT"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_type": "zol0_profitability_scorecard_delta",
        "baseline_scorecard_path": str(baseline_path),
        "candidate_scorecard_path": str(candidate_path),
        "baseline_run_ids": (
            ((baseline.get("metadata") or {}).get("selection") or {}).get("accepted_run_ids")
            or []
        ),
        "candidate_run_ids": (
            ((candidate.get("metadata") or {}).get("selection") or {}).get("accepted_run_ids")
            or []
        ),
        "kpi_delta": {
            "avg_profit_factor": {
                "before": baseline_avg_pf,
                "after": candidate_avg_pf,
                "delta": round(candidate_avg_pf - baseline_avg_pf, 6),
            },
            "avg_net_pnl": {
                "before": baseline_avg_net,
                "after": candidate_avg_net,
                "delta": round(candidate_avg_net - baseline_avg_net, 6),
            },
            "avg_trade_count": {
                "before": baseline_avg_trade_count,
                "after": candidate_avg_trade_count,
                "delta": round(candidate_avg_trade_count - baseline_avg_trade_count, 6),
            },
            "avg_conversion_rate": {
                "before": _safe_float(baseline_kpis.get("avg_conversion_rate")),
                "after": _safe_float(candidate_kpis.get("avg_conversion_rate")),
                "delta": round(
                    _safe_float(candidate_kpis.get("avg_conversion_rate"))
                    - _safe_float(baseline_kpis.get("avg_conversion_rate")),
                    6,
                ),
            },
            "avg_winrate": {
                "before": _safe_float(baseline_kpis.get("avg_winrate")),
                "after": _safe_float(candidate_kpis.get("avg_winrate")),
                "delta": round(
                    _safe_float(candidate_kpis.get("avg_winrate"))
                    - _safe_float(baseline_kpis.get("avg_winrate")),
                    6,
                ),
            },
        },
        "area_delta": {
            "AlphaSelection": {
                "before": alpha_before,
                "after": alpha_after,
                "delta": round(alpha_after - alpha_before, 6),
            },
            "CostEfficiency": {
                "before": cost_before,
                "after": cost_after,
                "delta": round(cost_after - cost_before, 6),
            },
            "EntryFunnel": {
                "before": _safe_float((baseline_areas.get("EntryFunnel") or {}).get("score")),
                "after": _safe_float((candidate_areas.get("EntryFunnel") or {}).get("score")),
                "delta": round(
                    _safe_float((candidate_areas.get("EntryFunnel") or {}).get("score"))
                    - _safe_float((baseline_areas.get("EntryFunnel") or {}).get("score")),
                    6,
                ),
            },
            "DataIntegrity": {
                "before": data_before,
                "after": data_after,
                "delta": round(data_after - data_before, 6),
            },
            "OperationalReadiness": {
                "before": ops_before,
                "after": ops_after,
                "delta": round(ops_after - ops_before, 6),
            },
        },
        "pass_criteria": pass_criteria,
        "final_classification": final_classification,
    }


def render_markdown(delta: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Profitability Delta")
    lines.append("")
    lines.append(f"- Baseline: `{_workspace_rel(delta['baseline_scorecard_path'])}`")
    lines.append(f"- Candidate: `{_workspace_rel(delta['candidate_scorecard_path'])}`")
    lines.append(f"- Final classification: `{delta['final_classification']}`")
    lines.append("")
    lines.append("## KPI Delta")
    for metric, payload in (delta.get("kpi_delta") or {}).items():
        lines.append(
            f"- `{metric}`: before=`{payload['before']}` after=`{payload['after']}` delta=`{payload['delta']}`"
        )
    lines.append("")
    lines.append("## Area Delta")
    for area_id, payload in (delta.get("area_delta") or {}).items():
        lines.append(
            f"- `{area_id}`: before=`{payload['before']}` after=`{payload['after']}` delta=`{payload['delta']}`"
        )
    lines.append("")
    lines.append("## Pass Criteria")
    for name, payload in (delta.get("pass_criteria") or {}).items():
        lines.append(
            f"- `{name}`: passed=`{payload['passed']}` threshold=`{payload['threshold']}` before=`{payload['before']}` after=`{payload['after']}` delta=`{payload['delta']}`"
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(delta: dict[str, Any], analysis_dir: Path, stem: str) -> tuple[Path, Path]:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    json_path = analysis_dir / f"{stem}.json"
    md_path = analysis_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(delta, indent=2, ensure_ascii=True, allow_nan=False),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(delta), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two profitability audit scorecards.")
    parser.add_argument(
        "--baseline",
        default=str(ANALYSIS_DIR / "zol0_profitability_audit_scorecard.json"),
    )
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--analysis-dir", default=str(ANALYSIS_DIR))
    parser.add_argument("--output-stem", default="zol0_profitability_audit_delta")
    args = parser.parse_args(argv)

    delta = build_delta(
        baseline_path=Path(args.baseline),
        candidate_path=Path(args.candidate),
    )
    json_path, md_path = write_outputs(
        delta,
        Path(args.analysis_dir),
        stem=str(args.output_stem),
    )
    print(f"JSON={json_path}")
    print(f"MARKDOWN={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
