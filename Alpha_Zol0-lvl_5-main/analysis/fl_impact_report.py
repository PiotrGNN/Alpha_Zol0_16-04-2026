import json
from dataclasses import dataclass, asdict
from statistics import mean
from typing import List, Dict


@dataclass(frozen=True)
class FLDecisionSnapshot:
    id: str
    decision_before: str
    decision_after: str
    edge_before: float
    edge_after: float
    admission_before: bool
    admission_after: bool

    @property
    def decision_changed(self) -> bool:
        return self.decision_before != self.decision_after

    @property
    def edge_delta(self) -> float:
        return self.edge_after - self.edge_before


def evaluate_fl_impact(snapshots: List[FLDecisionSnapshot]) -> Dict:
    if not isinstance(snapshots, list):
        raise ValueError("snapshots must be a list of FLDecisionSnapshot")

    total = len(snapshots)
    changed_snapshots = [s for s in snapshots if s.decision_changed]
    changed = len(changed_snapshots)

    edge_deltas = [s.edge_delta for s in snapshots]
    positive = sum(1 for d in edge_deltas if d > 0)
    negative = sum(1 for d in edge_deltas if d < 0)
    neutral = sum(1 for d in edge_deltas if d == 0)

    avg_edge_delta = float(mean(edge_deltas)) if edge_deltas else 0.0

    has_positive_signal = bool(
        changed > 0 and positive > 0 and avg_edge_delta > 0.0
    )
    go_no_go = "GO" if (has_positive_signal and positive >= negative) else "NO-GO"

    top_positive_changes = sorted(
        changed_snapshots, key=lambda s: s.edge_delta, reverse=True
    )[:5]
    top_negative_changes = sorted(
        changed_snapshots, key=lambda s: s.edge_delta
    )[:5]

    return {
        "total_decisions": total,
        "changed_decisions": changed,
        "percent_changed": float((changed / total * 100) if total > 0 else 0.0),
        "avg_edge_delta": avg_edge_delta,
        "positive_impact_count": positive,
        "negative_impact_count": negative,
        "neutral_impact_count": neutral,
        "positive_vs_negative": positive - negative,
        "go_no_go": go_no_go,
        "evidence": {
            "changed_snapshot_ids": [s.id for s in changed_snapshots],
            "top_positive_impacts": [
                {
                    "id": s.id,
                    "decision_before": s.decision_before,
                    "decision_after": s.decision_after,
                    "edge_before": s.edge_before,
                    "edge_after": s.edge_after,
                    "edge_delta": s.edge_delta,
                }
                for s in top_positive_changes
            ],
            "top_negative_impacts": [
                {
                    "id": s.id,
                    "decision_before": s.decision_before,
                    "decision_after": s.decision_after,
                    "edge_before": s.edge_before,
                    "edge_after": s.edge_after,
                    "edge_delta": s.edge_delta,
                }
                for s in top_negative_changes
            ],
        },
    }


def derive_fl_telemetry_summary(fl_telemetry: Dict) -> Dict:
    try:
        rows_with_hint = int(fl_telemetry.get("rows_with_fl_trend_hint") or 0)
    except Exception:
        rows_with_hint = 0
    try:
        override_applied = int(fl_telemetry.get("override_applied_count") or 0)
    except Exception:
        override_applied = 0
    try:
        override_up = int(fl_telemetry.get("override_up_count") or 0)
    except Exception:
        override_up = 0
    try:
        override_down = int(fl_telemetry.get("override_down_count") or 0)
    except Exception:
        override_down = 0
    try:
        max_override_count_symbol = int(
            fl_telemetry.get("max_override_count_symbol") or 0
        )
    except Exception:
        max_override_count_symbol = 0

    override_applied_share = (
        float(override_applied) / float(rows_with_hint)
        if rows_with_hint > 0
        else 0.0
    )
    override_up_share = (
        float(override_up) / float(override_applied)
        if override_applied > 0
        else 0.0
    )
    override_down_share = (
        float(override_down) / float(override_applied)
        if override_applied > 0
        else 0.0
    )

    return {
        "override_applied_share": override_applied_share,
        "override_up_share": override_up_share,
        "override_down_share": override_down_share,
        "max_override_count_symbol": max_override_count_symbol,
    }


def create_report_json(
    snapshots: List[FLDecisionSnapshot],
    fl_telemetry: Dict | None = None,
    fl_telemetry_breakdown: Dict | None = None,
    fl_telemetry_impact_summary: Dict | None = None,
) -> str:
    metrics = evaluate_fl_impact(snapshots)
    report = {
        "snapshots": [asdict(s) for s in sorted(snapshots, key=lambda x: x.id)],
        "metrics": metrics,
        "audit_evidence": metrics.get("evidence", {}),
    }
    if isinstance(fl_telemetry, dict):
        report["fl_telemetry"] = fl_telemetry
        report["fl_telemetry_summary"] = derive_fl_telemetry_summary(fl_telemetry)
    if isinstance(fl_telemetry_breakdown, dict):
        report["fl_telemetry_breakdown"] = fl_telemetry_breakdown
    if isinstance(fl_telemetry_impact_summary, dict):
        report["fl_telemetry_impact_summary"] = fl_telemetry_impact_summary
    return json.dumps(report, indent=2, sort_keys=True)


def create_report_markdown(snapshots: List[FLDecisionSnapshot]) -> str:
    metrics = evaluate_fl_impact(snapshots)
    lines = ["# FL Impact Decision Report", ""]
    lines.append("## Metrics summary")
    lines.append("")
    for key, value in metrics.items():
        if key != "evidence":
            lines.append(f"- **{key.replace('_', ' ').title()}**: {value}")
    evidence = metrics.get("evidence", {})
    lines.append("")
    lines.append("## Evidence summary")
    lines.append("")
    changed_ids = evidence.get('changed_snapshot_ids', [])
    lines.append(
        f"- **Changed decisions (IDs)**: {changed_ids}"
    )

    def _format_evidence_list(items):
        lines_out = []
        for item in items:
            part1 = (
                f"  - {item['id']}: {item['decision_before']} -> "
                f"{item['decision_after']} "
            )
            part2 = (
                f"(edge {item['edge_before']:.4f} -> {item['edge_after']:.4f}, "
                f"delta {item['edge_delta']:.4f})"
            )
            lines_out.append(part1 + part2)
        return "\n".join(lines_out)

    top_positive = evidence.get("top_positive_impacts", [])
    top_negative = evidence.get("top_negative_impacts", [])

    lines.append("### Top positive impacts")
    if top_positive:
        lines.append(_format_evidence_list(top_positive))
    else:
        lines.append("- none")

    lines.append("")
    lines.append("### Top negative impacts")
    if top_negative:
        lines.append(_format_evidence_list(top_negative))
    else:
        lines.append("- none")

    lines.append("")
    lines.append("## Snapshot details")
    lines.append("")
    lines.append(
        "| Id | Decision Before | Decision After | Edge Before | Edge After | "
        "Admission Before | Admission After | Changed | Edge Delta |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for s in sorted(snapshots, key=lambda x: x.id):
        lines.append(
            "| {} | {} | {} | {:.4f} | {:.4f} | {} | {} | {} | {:.4f} |".format(
                s.id,
                s.decision_before,
                s.decision_after,
                s.edge_before,
                s.edge_after,
                s.admission_before,
                s.admission_after,
                s.decision_changed,
                s.edge_delta,
            )
        )
    lines.append("")
    lines.append(f"### GO/NO-GO: **{metrics['go_no_go']}**")
    return "\n".join(lines)
