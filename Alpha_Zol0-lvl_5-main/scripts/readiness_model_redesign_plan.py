import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict:
    candidate = Path(path)
    if not candidate.is_absolute():
        direct_candidate = candidate
        workdir_candidate = (WORKDIR / candidate).resolve()
        if direct_candidate.exists():
            candidate = direct_candidate
        elif workdir_candidate.exists():
            candidate = workdir_candidate
        else:
            candidate = _latest_mismatch_audit()
    elif not candidate.exists():
        candidate = _latest_mismatch_audit()
    return json.loads(candidate.read_text(encoding="utf-8"))


def _latest_mismatch_audit() -> Path:
    candidates = sorted(
        DIAG_DIR.glob("readiness_architecture_mismatch_audit_*.json"),
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    if not candidates:
        raise FileNotFoundError("No readiness_architecture_mismatch_audit artifacts found")
    return candidates[-1]


def _build_report(audit_path: Path) -> dict:
    audit = _load_json(audit_path)
    cov = audit.get("coverage") or {}

    canonical_bucket_identity = {
        "canonical_fields": [
            "symbol.upper()",
            "strategy_identity",
            "side.lower()",
        ],
        "shared_strategy_source": [
            "explicit strategy identity carried in both paths",
            "close path: position.entry_main_strategy",
            "evaluated path: entry_edge_over_fee.strategy when present",
        ],
        "canonical_strategy_rules": [
            "strategy must be explicit, not an implicit UNKNOWN bucket label",
            "unknown strategy becomes a separate unresolved status, not a canonical bucket",
            "fallback '__ALL__' is allowed only as an explicit unresolved marker, not as identity",
        ],
        "status_fields": [
            "bucket_identity_status",
            "bucket_identity_reason",
            "resolved_bucket_key",
        ],
    }

    fallback_rules = {
        "resolved": [
            "symbol is present",
            "side is present",
            "strategy_identity is explicitly present and normalized",
        ],
        "unresolved": [
            "strategy missing",
            "strategy set to '__ALL__' fallback bucket",
            "entry_edge_over_fee missing",
        ],
        "unresolved_handling": [
            "keep unresolved rows in a separate diagnostics pool",
            "do not collapse unresolved rows into the canonical readiness bucket",
            "do not hide missing strategy behind UNKNOWN as a canonical identity",
        ],
    }

    alignment = {
        "gate_rows_with_matching_close_path": cov.get("gate_rows_with_matching_close_path") or {},
        "gate_rows_without_matching_close_path": cov.get("gate_rows_without_matching_close_path") or {},
        "gate_rows_unknown_share": cov.get("gate_rows_unknown_share") or {},
        "close_rows_returning_to_evaluated_buckets": cov.get("close_rows_returning_to_evaluated_buckets") or {},
        "close_rows_not_returning_to_evaluated_buckets": cov.get("close_rows_not_returning_to_evaluated_buckets") or {},
        "normalized_alignment_share": cov.get("normalized_alignment_share"),
        "raw_alignment_share": cov.get("raw_alignment_share"),
    }

    risk_review = {
        "missing_strategy_risk": "high until strategy identity is carried explicitly in evaluated rows",
        "comparability_risk": "medium because unresolved rows must remain visible and separate",
        "implementation_drift_risk": "medium if the canonical key is computed differently across paths",
        "operational_risk": "medium because the research-only shadow path must not bleed into production readiness",
    }

    report = {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "method_version": "v1",
            "classification": "REDESIGN_REQUIRED_AND_FEASIBLE",
            "source_audit": str(audit_path),
        },
        "current_failure_recap": {
            "classification": audit.get("final_classification"),
            "gate_rows_with_matching_close_path": cov.get("gate_rows_with_matching_close_path"),
            "gate_rows_unknown_share": cov.get("gate_rows_unknown_share"),
            "close_rows_returning_to_evaluated_buckets": cov.get("close_rows_returning_to_evaluated_buckets"),
            "normalized_alignment_share": cov.get("normalized_alignment_share"),
            "raw_alignment_share": cov.get("raw_alignment_share"),
            "conclusion": (audit.get("conclusion") or {}).get("architectural_consequence"),
        },
        "canonical_bucket_identity_proposal": canonical_bucket_identity,
        "fallback_rules": fallback_rules,
        "readiness_flow_alignment": alignment,
        "risk_review": risk_review,
        "minimal_research_only_rollout_plan": [
            "Shadow-emit resolved_bucket_key in both evaluated and close-write paths without changing production admission semantics.",
            "Add bucket_identity_status and bucket_identity_reason so unresolved rows remain explicit instead of collapsing to UNKNOWN.",
            "Run a shadow coverage audit to confirm that evaluated and close-write paths now share the same canonical key when strategy identity is present.",
            "Keep raw keys, unresolved pools, and canonical keys side-by-side until coverage proves the redesign is stable.",
        ],
        "final_recommendation": "REDESIGN_REQUIRED_AND_FEASIBLE",
    }
    return report


def _render_md(report: dict) -> str:
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "The current readiness model is architecturally misaligned, but the redesign is feasible. A shared canonical bucket identity can be defined without hiding missing data, provided unresolved strategy identity is kept separate from canonical readiness buckets."
    )
    lines.append("")
    lines.append("## B. Current Failure Recap")
    recap = report["current_failure_recap"]
    lines.append(f"- evaluated/close mismatch classification: `{recap['classification']}`")
    lines.append(f"- gate rows with matching close path: `{recap['gate_rows_with_matching_close_path']}`")
    lines.append(f"- gate rows unknown share: `{recap['gate_rows_unknown_share']}`")
    lines.append(f"- close rows returning to evaluated buckets: `{recap['close_rows_returning_to_evaluated_buckets']}`")
    lines.append(f"- normalized alignment share: `{recap['normalized_alignment_share']}`")
    lines.append(f"- raw alignment share: `{recap['raw_alignment_share']}`")
    lines.append("")
    lines.append("## C. Canonical Bucket Identity Proposal")
    c = report["canonical_bucket_identity_proposal"]
    lines.append(f"- canonical fields: {', '.join(c['canonical_fields'])}")
    lines.append(f"- shared strategy source: {', '.join(c['shared_strategy_source'])}")
    lines.append(f"- canonical strategy rules: {', '.join(c['canonical_strategy_rules'])}")
    lines.append(f"- status fields: {', '.join(c['status_fields'])}")
    lines.append("")
    lines.append("## D. Fallback Rules")
    fb = report["fallback_rules"]
    lines.append(f"- resolved: {', '.join(fb['resolved'])}")
    lines.append(f"- unresolved: {', '.join(fb['unresolved'])}")
    lines.append(f"- unresolved handling: {', '.join(fb['unresolved_handling'])}")
    lines.append("")
    lines.append("## E. Readiness Flow Alignment")
    align = report["readiness_flow_alignment"]
    lines.append(f"- gate rows with matching close path: {align['gate_rows_with_matching_close_path']}")
    lines.append(f"- gate rows without matching close path: {align['gate_rows_without_matching_close_path']}")
    lines.append(f"- gate rows unknown share: {align['gate_rows_unknown_share']}")
    lines.append(f"- close rows returning to evaluated buckets: {align['close_rows_returning_to_evaluated_buckets']}")
    lines.append(f"- normalized alignment share: {align['normalized_alignment_share']}")
    lines.append(f"- raw alignment share: {align['raw_alignment_share']}")
    lines.append("")
    lines.append("## F. Risk Review")
    for k, v in report["risk_review"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## G. Minimal Research-Only Rollout Plan")
    for item in report["minimal_research_only_rollout_plan"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## H. Final Recommendation")
    lines.append(report["final_recommendation"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Produce a research-only readiness model redesign plan.")
    parser.add_argument("--audit-path", default=None)
    args = parser.parse_args(argv)
    audit_path = Path(args.audit_path) if args.audit_path else _latest_mismatch_audit()
    if not audit_path.is_absolute():
        audit_path = (WORKDIR / audit_path).resolve()
    report = _build_report(audit_path)
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"readiness_model_redesign_plan_{stamp}.json"
    md_path = DIAG_DIR / f"readiness_model_redesign_plan_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
