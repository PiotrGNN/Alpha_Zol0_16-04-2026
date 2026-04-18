import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


def _build_report() -> dict:
    classification = "SHADOW_ONLY_PROTOTYPE_WORTH_IT"
    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "classification": classification,
            "method_version": "proxy_readiness_prototype_plan_v1",
            "scope": [
                "realized_only_baseline",
                "proxy_readiness_shadow_only",
                "proxy_readiness_gated_experiment",
            ],
            "code_refs": {
                "entry_live_edge_proxy": "core/BotCore.py:12992-13034",
                "entry_edge_over_fee": "core/BotCore.py:2470-2591",
                "proxy_ready_history": "core/BotCore.py:13358-13680",
                "history_write": "core/BotCore.py:2201-2591 and 8557-8573",
            },
        },
        "proxy_candidates": {
            "available_pre_close_signals": [
                "entry_live_edge_proxy",
                "entry_live_edge_status.live_edge_proxy",
                "entry_edge_over_fee_status.mean_fee_total",
                "entry_edge_over_fee_status.mean_spread_slippage_proxy",
                "entry_edge_over_fee_status.mean_edge_over_fee",
                "entry_expected_edge_after_fee",
                "candidate_expected_edge_after_fee",
            ],
            "proxy_exclusions": [
                "realized gross_fill_pnl_model",
                "realized fee_total",
                "realized spread_slippage_proxy",
            ],
        },
        "semantic_separation": {
            "realized_history": "post-close, close-time pnl_decompose persisted into edge bucket",
            "proxy_history": "pre-close or shadow-derived estimate from live edge / fee / spread inputs",
            "proxy_readiness": "research-only readiness signal that may fire before realized close data exists",
            "true_edge_performance_history": "bucketed realized observations used for trade_count and blocked readiness",
        },
        "prototype_design": {
            "realized_only_baseline": {
                "behavior": "current close-only model",
                "wiring": "no change",
                "observability": "existing edge-history and runtime summary only",
            },
            "proxy_readiness_shadow_only": {
                "behavior": "shadow metrics only",
                "wiring": "emit proxy readiness metrics alongside realized metrics, never used for admission",
                "artifact_rules": [
                    "separate JSON fields",
                    "separate log event namespace",
                    "no shared bucket with realized history",
                    "explicit shadow_only flag",
                ],
            },
            "proxy_readiness_gated_experiment": {
                "behavior": "research-only gated experiment",
                "wiring": "proxy readiness may influence paper-only shadow gating behind hard env guard",
                "guards": [
                    "PAPER only",
                    "explicit opt-in env flag",
                    "no LIVE path",
                    "no realized bucket mutation",
                ],
            },
        },
        "success_failure": {
            "success_if": [
                "shadow-only readiness becomes observable earlier than close-only history",
                "proxy metrics improve timing observability without changing realized counts",
                "proxy stats remain fully separated from realized stats",
            ],
            "failure_if": [
                "proxy stats leak into realized bucket",
                "proxy readiness increases admissions",
                "operator cannot distinguish proxy from realized history",
                "readiness timing gain requires semantic compromise",
            ],
        },
        "risk_review": {
            "leakage_risk": "low_to_medium",
            "pseudo_history_risk": "medium_to_high",
            "stats_contamination_risk": "medium",
            "admission_permissiveness_risk": "medium",
            "operator_confusion_risk": "medium",
        },
        "final_classification": classification,
        "recommendation": "Prototype shadow-only first; gated paper experiment is worth it only if shadow-only metrics remain clean and materially earlier than realized close-only history.",
    }


def _render_md(report: dict) -> str:
    meta = report["metadata"]
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "A proxy-based readiness prototype is worth testing in shadow-only form. The current close-only realized history is structurally late, but the code already exposes pre-close signals that can be used for research-only timing observability."
    )
    lines.append("")
    lines.append("## B. Scope")
    lines.append("- `REALIZED_ONLY_BASELINE`")
    lines.append("- `PROXY_READINESS_SHADOW_ONLY`")
    lines.append("- `PROXY_READINESS_GATED_EXPERIMENT`")
    lines.append("")
    lines.append("## C. Current Constraint")
    lines.append(
        "The realized-history path remains the only production-safe source of `trade_count`, and it is seeded after `position_close`. Any earlier readiness signal must remain explicitly proxy-based and research-only."
    )
    lines.append("")
    lines.append("## D. Proxy Candidates")
    for item in report["proxy_candidates"]["available_pre_close_signals"]:
        lines.append(f"- `{item}`")
    lines.append("")
    lines.append("## E. Semantic Separation Rules")
    lines.append("- realized-history: post-close, bucketed, mutable by close-time fills only")
    lines.append("- proxy-history: pre-close / shadow estimate only")
    lines.append("- proxy readiness: must never mutate realized bucket")
    lines.append("- true edge-performance history: remains the only production admission source")
    lines.append("")
    lines.append("## F. Minimal Prototype Design")
    lines.append("- baseline: unchanged")
    lines.append("- shadow-only: separate metrics namespace, no admission effect")
    lines.append("- gated experiment: PAPER-only, hard opt-in, no LIVE path")
    lines.append("")
    lines.append("## G. Success / Failure Criteria")
    lines.append("- success: earlier observability without shared buckets or admission drift")
    lines.append("- failure: leakage, pseudo-history, contamination, or operator ambiguity")
    lines.append("")
    lines.append("## H. Risk Review")
    for k, v in report["risk_review"].items():
        lines.append(f"- {k.replace('_', ' ')}: {v}")
    lines.append("")
    lines.append("## I. Final Classification")
    lines.append(meta["classification"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a research-only proxy readiness prototype plan.")
    args = parser.parse_args(argv)
    report = _build_report()
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"proxy_readiness_prototype_plan_{stamp}.json"
    md_path = DIAG_DIR / f"proxy_readiness_prototype_plan_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
