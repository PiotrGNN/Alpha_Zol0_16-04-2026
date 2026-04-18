#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


ORDERED_ROOT_CAUSE_IDS = [
    "RUNTIME_PROMOTION_BLOCKERS",
    "READINESS_VERDICT_INCOHERENCE",
    "ECONOMIC_NO_GO_RUNTIME",
    "INCOMPLETE_REPAIR_ARTIFACT_CONTRACT",
    "PERSISTENCE_MODE_DRIFT",
    "SILENT_EXCEPTION_SWALLOWING",
    "PLACEHOLDER_TESTS",
    "UNRESOLVED_TODO_FIXME",
    "ENV_TEMPLATE_DRIFT",
    "DEPLOYMENT_DOC_DRIFT",
    "AUDIT_CLAIM_DRIFT",
    "EXCESSIVE_ARTIFACT_FOOTPRINT",
]


ROOT_CAUSE_META: dict[str, dict[str, Any]] = {
    "RUNTIME_PROMOTION_BLOCKERS": {
        "title": "Runtime promote gates are failing on candidate patches",
        "why_now": "Directly blocks profitability/runtime promotion decisions.",
        "fix_steps": [
            "Freeze baseline run profile and rerun patch matrix with strict one-change isolation.",
            "For each rollback patch, map failing target (`profitability_floor`, `fee_inversion`, `green_to_red`) to exact code/config owner.",
            "Add targeted regression tests per failed gate before rerunning matrix.",
            "Promote only when a non-baseline patch passes all hard gates in at least two independent runs.",
        ],
        "acceptance_criteria": [
            "At least one non-baseline patch has `action=hold/promote` without rollback.",
            "Runtime target verification is `pass` for all hard gates.",
            "Process returncode stability is confirmed on repeated runs.",
        ],
    },
    "READINESS_VERDICT_INCOHERENCE": {
        "title": "Readiness output is operationally PASS but globally DO_NOT_PROMOTE",
        "why_now": "Creates false sense of runtime health and wrong go/no-go communication.",
        "fix_steps": [
            "Split readiness outputs into explicit operational and economic channels with separate status fields.",
            "Make deployment automation consume the economic verdict, not operational PASS alone.",
            "Backfill readiness reports with structured reason codes for DO_NOT_PROMOTE.",
        ],
        "acceptance_criteria": [
            "Readiness schema exposes independent operational/economic statuses.",
            "No ambiguity in next step: promote only when both channels are green.",
        ],
    },
    "ECONOMIC_NO_GO_RUNTIME": {
        "title": "Economic context repeatedly reports NO-GO",
        "why_now": "Main profitability objective remains unmet despite runtime continuity.",
        "fix_steps": [
            "Rank NO-GO drivers by impact (edge delta, changed decisions, negative impact count).",
            "Run focused experiments only on top 1-2 negative drivers, not broad multi-factor changes.",
            "Gate hypothesis promotion on positive economic delta over baseline across repeated windows.",
        ],
        "acceptance_criteria": [
            "Economic context switches to GO for promoted candidate.",
            "Positive edge delta is sustained in repeated validation windows.",
        ],
    },
    "INCOMPLETE_REPAIR_ARTIFACT_CONTRACT": {
        "title": "Repair iteration directories miss required artifacts",
        "why_now": "Breaks traceability and reproducibility of runtime decisions.",
        "fix_steps": [
            "Enforce required file set (`repair_iteration_summary.json`, `repair_plan.md`, `repair_iteration.md`, `repair_diff.md`) at pipeline end.",
            "Fail repair job if any mandatory artifact is missing.",
            "Backfill missing artifacts for already executed critical iterations.",
        ],
        "acceptance_criteria": [
            "100% repair iteration folders contain full mandatory artifact set.",
            "CI check fails on missing artifact contract.",
        ],
    },
    "PERSISTENCE_MODE_DRIFT": {
        "title": "Postgres-only claims conflict with SQLite runtime defaults",
        "why_now": "Architecture drift can invalidate runtime comparability and rollout safety.",
        "fix_steps": [
            "Decide single production persistence policy (Postgres-only or explicit dual-mode).",
            "If Postgres-only: remove SQLite production defaults and require DB URL in startup gate.",
            "Align docs (`README`, `AUDIT_STATUS`, `TODO`) with actual persistence behavior.",
        ],
        "acceptance_criteria": [
            "No production code path defaults to SQLite unintentionally.",
            "Docs and runtime persistence policy are fully consistent.",
        ],
    },
    "SILENT_EXCEPTION_SWALLOWING": {
        "title": "Silent `except: pass` blocks observability of runtime failures",
        "why_now": "Can hide real trading/runtime defects and bias diagnostics.",
        "fix_steps": [
            "Replace `except: pass` in critical runtime paths with structured error logging.",
            "Add bounded fallback actions per exception class.",
            "Add tests that assert error telemetry emission on failure branches.",
        ],
        "acceptance_criteria": [
            "Critical modules have no silent exception swallowing.",
            "Failure-path tests confirm telemetry and controlled fallback.",
        ],
    },
    "PLACEHOLDER_TESTS": {
        "title": "Placeholder tests reduce confidence in green test suite",
        "why_now": "A green CI can still miss regressions in profitability/runtime behavior.",
        "fix_steps": [
            "Replace `assert True`/TODO placeholders with behavior assertions tied to requirements.",
            "Tag runtime-critical tests and require them in pre-promotion test gate.",
        ],
        "acceptance_criteria": [
            "No placeholder tests remain in critical/high scope.",
            "Critical runtime test set is explicitly enforced in CI.",
        ],
    },
    "UNRESOLVED_TODO_FIXME": {
        "title": "High volume of TODO/FIXME markers in audited scope",
        "why_now": "Deferred issues accumulate technical risk in runtime path.",
        "fix_steps": [
            "Triage TODO/FIXME by runtime impact and owner.",
            "Convert remaining deferred items into tracked backlog tickets with deadlines.",
            "Block new critical-path TODO markers in CI.",
        ],
        "acceptance_criteria": [
            "Critical runtime paths have zero untracked TODO/FIXME markers.",
            "All remaining markers link to active tracked tickets.",
        ],
    },
    "ENV_TEMPLATE_DRIFT": {
        "title": "Runtime `.env` keys diverge from template files",
        "why_now": "Config drift increases misconfiguration risk and non-reproducible runs.",
        "fix_steps": [
            "Generate env schema from runtime config usage.",
            "Sync `.env.example` and `secrets.env.sample` with required/optional annotations.",
            "Add config validation on startup for missing required keys.",
        ],
        "acceptance_criteria": [
            "Template keys match runtime schema.",
            "Startup fails fast on missing required env keys.",
        ],
    },
    "DEPLOYMENT_DOC_DRIFT": {
        "title": "Deployment documentation references non-existent files/paths",
        "why_now": "Breaks reproducible deployment and incident recovery playbooks.",
        "fix_steps": [
            "Align README deployment commands with actual repo layout.",
            "Add docs validation script checking referenced files exist.",
        ],
        "acceptance_criteria": [
            "All documented deploy commands resolve to existing files.",
            "Docs validation gate passes in CI.",
        ],
    },
    "AUDIT_CLAIM_DRIFT": {
        "title": "Absolute completion claims conflict with measured findings",
        "why_now": "Misleading status can cause premature promotion decisions.",
        "fix_steps": [
            "Replace static 100% claims with generated quality metrics snapshot.",
            "Tie status docs to latest audit artifacts and timestamped evidence.",
        ],
        "acceptance_criteria": [
            "Status docs reference objective measured outputs.",
            "No unconditional completion claim without current evidence.",
        ],
    },
    "EXCESSIVE_ARTIFACT_FOOTPRINT": {
        "title": "Large artifacts inflate runtime workspace and slow operations",
        "why_now": "Increases audit and pipeline latency; affects iteration speed.",
        "fix_steps": [
            "Define retention/rotation policy for logs/db snapshots/tmp outputs.",
            "Archive cold artifacts outside hot workspace.",
            "Add size-budget checks for key directories.",
        ],
        "acceptance_criteria": [
            "Hot workspace footprint reduced and bounded by policy.",
            "Directory size budgets enforced automatically.",
        ],
    },
}


@dataclass
class RootCauseGroup:
    root_cause_id: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    evidence_paths: set[str] = field(default_factory=set)
    canonical_evidence_paths: set[str] = field(default_factory=set)

    def add(self, finding: dict[str, Any]) -> None:
        self.findings.append(finding)
        path = str(finding.get("evidence_path", "")).replace("\\", "/")
        self.evidence_paths.add(path)
        if path.startswith("Alpha_Zol0-lvl_5-main/"):
            self.canonical_evidence_paths.add(path)

    @property
    def max_severity(self) -> str:
        if not self.findings:
            return "low"
        return min(
            (str(f.get("severity", "low")).lower() for f in self.findings),
            key=lambda s: SEVERITY_RANK.get(s, 9),
        )


def normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def infer_root_cause_id(finding: dict[str, Any]) -> str | None:
    domain = str(finding.get("domain", "")).lower()
    scope = str(finding.get("scope", "")).lower()
    fact = str(finding.get("fact", "")).lower()

    if domain == "runtime_validation":
        return "RUNTIME_PROMOTION_BLOCKERS"
    if domain == "runtime_readiness":
        if scope in {"gate_consistency", "paper_ready_flag"}:
            return "READINESS_VERDICT_INCOHERENCE"
        return "READINESS_VERDICT_INCOHERENCE"
    if domain == "profitability_runtime":
        return "ECONOMIC_NO_GO_RUNTIME"
    if domain == "runtime_validation_artifacts":
        return "INCOMPLETE_REPAIR_ARTIFACT_CONTRACT"
    if domain == "architecture_consistency":
        return "PERSISTENCE_MODE_DRIFT"
    if domain == "runtime_resilience":
        return "SILENT_EXCEPTION_SWALLOWING"
    if domain == "test_quality":
        return "PLACEHOLDER_TESTS"
    if domain == "code_quality":
        return "UNRESOLVED_TODO_FIXME"
    if domain == "config_drift":
        return "ENV_TEMPLATE_DRIFT"
    if domain == "deployment_consistency":
        return "DEPLOYMENT_DOC_DRIFT"
    if domain == "docs_code_consistency":
        return "AUDIT_CLAIM_DRIFT"
    if domain == "operational_footprint":
        return "EXCESSIVE_ARTIFACT_FOOTPRINT"

    if "rollback" in fact or "failed runtime targets" in fact:
        return "RUNTIME_PROMOTION_BLOCKERS"
    return None


def pick_examples(findings: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    def key_fn(f: dict[str, Any]) -> tuple[int, str]:
        sev = str(f.get("severity", "low")).lower()
        path = normalize_path(str(f.get("evidence_path", "")))
        is_canonical = 0 if path.startswith("Alpha_Zol0-lvl_5-main/") else 1
        return (is_canonical, SEVERITY_RANK.get(sev, 9), str(f.get("id", "")))

    chosen = sorted(findings, key=key_fn)[:limit]
    out: list[dict[str, Any]] = []
    for c in chosen:
        out.append(
            {
                "id": c.get("id"),
                "severity": c.get("severity"),
                "evidence_path": normalize_path(str(c.get("evidence_path", ""))),
                "fact": str(c.get("fact", "")),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate deduplicated critical/high action backlog grouped by root cause."
    )
    parser.add_argument(
        "--findings-jsonl",
        required=True,
        help="Path to findings_registry.jsonl from system_full_audit output.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/diagnostics",
        help="Output directory for backlog artifacts.",
    )
    parser.add_argument(
        "--tag",
        default=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        help="Tag used in output file names.",
    )
    args = parser.parse_args()

    findings_path = Path(args.findings_jsonl).resolve()
    if not findings_path.exists():
        print(f"findings file not found: {findings_path}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    groups: dict[str, RootCauseGroup] = {}
    total_in = 0
    filtered_in = 0
    skipped_unmapped = 0

    with findings_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            total_in += 1
            finding = json.loads(line)
            sev = str(finding.get("severity", "")).lower()
            if sev not in {"critical", "high"}:
                continue
            filtered_in += 1
            root_cause_id = infer_root_cause_id(finding)
            if not root_cause_id:
                skipped_unmapped += 1
                continue
            if root_cause_id not in groups:
                groups[root_cause_id] = RootCauseGroup(root_cause_id=root_cause_id)
            groups[root_cause_id].add(finding)

    ordered_ids = [rid for rid in ORDERED_ROOT_CAUSE_IDS if rid in groups]
    unordered_ids = sorted(rid for rid in groups.keys() if rid not in ordered_ids)
    ordered_ids.extend(unordered_ids)

    backlog_items: list[dict[str, Any]] = []
    for idx, root_cause_id in enumerate(ordered_ids, start=1):
        group = groups[root_cause_id]
        meta = ROOT_CAUSE_META.get(root_cause_id, {})
        backlog_items.append(
            {
                "order": idx,
                "root_cause_id": root_cause_id,
                "title": meta.get("title", root_cause_id),
                "severity": group.max_severity,
                "why_now": meta.get("why_now", ""),
                "findings_count": len(group.findings),
                "unique_evidence_paths": len(group.evidence_paths),
                "canonical_findings_count": sum(
                    1
                    for f in group.findings
                    if normalize_path(str(f.get("evidence_path", ""))).startswith(
                        "Alpha_Zol0-lvl_5-main/"
                    )
                ),
                "canonical_unique_paths": len(group.canonical_evidence_paths),
                "representative_findings": pick_examples(group.findings, limit=5),
                "fix_steps": meta.get("fix_steps", []),
                "acceptance_criteria": meta.get("acceptance_criteria", []),
            }
        )

    payload = {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_findings_jsonl": str(findings_path),
            "input_findings_total": total_in,
            "input_critical_high": filtered_in,
            "grouped_root_causes": len(backlog_items),
            "skipped_unmapped_critical_high": skipped_unmapped,
            "ordering_policy": ORDERED_ROOT_CAUSE_IDS,
        },
        "backlog": backlog_items,
    }

    json_path = output_dir / f"action_backlog_critical_high_{args.tag}.json"
    md_path = output_dir / f"action_backlog_critical_high_{args.tag}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    md_lines: list[str] = []
    md_lines.append(f"# Critical/High Action Backlog ({args.tag})")
    md_lines.append("")
    md_lines.append(f"- Source findings: `{findings_path}`")
    md_lines.append(f"- Input findings (all severities): **{total_in}**")
    md_lines.append(f"- Input findings (critical/high): **{filtered_in}**")
    md_lines.append(f"- Grouped root causes: **{len(backlog_items)}**")
    md_lines.append("")
    md_lines.append("## Exact Fix Order")
    for item in backlog_items:
        md_lines.append("")
        md_lines.append(
            f"### {item['order']}. {item['title']} (`{item['root_cause_id']}`) [{item['severity']}]"
        )
        md_lines.append(f"- Why now: {item['why_now']}")
        md_lines.append(
            f"- Impact footprint: findings={item['findings_count']}, "
            f"unique_paths={item['unique_evidence_paths']}, "
            f"canonical_findings={item['canonical_findings_count']}"
        )
        md_lines.append("- Fix steps:")
        for step in item["fix_steps"]:
            md_lines.append(f"  - {step}")
        md_lines.append("- Acceptance criteria:")
        for ac in item["acceptance_criteria"]:
            md_lines.append(f"  - {ac}")
        md_lines.append("- Representative evidence:")
        for ex in item["representative_findings"]:
            md_lines.append(
                f"  - `{ex['id']}` {ex['severity']} @ `{ex['evidence_path']}`: {ex['fact']}"
            )

    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"ACTION_BACKLOG_JSON={json_path}")
    print(f"ACTION_BACKLOG_MD={md_path}")
    print(f"GROUPS={len(backlog_items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
