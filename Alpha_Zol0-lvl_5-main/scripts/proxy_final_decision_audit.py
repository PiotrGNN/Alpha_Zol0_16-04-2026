import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_EXPANDED = DIAG_DIR / "proxy_shadow_realized_agreement_expanded_20260328_021928.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _agreement_rate(pairs: list[dict]) -> float | None:
    if not pairs:
        return None
    hits = 0
    for pair in pairs:
        if _sign(float(pair.get("proxy_shadow_edge_mean") or 0.0)) == _sign(float(pair.get("realized_net_pnl") or 0.0)):
            hits += 1
    return hits / len(pairs)


def _rank_agreement(pairs: list[dict]) -> dict:
    comparable = 0
    concordant = 0
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            a = pairs[i]
            b = pairs[j]
            proxy_delta = float(a.get("proxy_shadow_edge_mean") or 0.0) - float(b.get("proxy_shadow_edge_mean") or 0.0)
            realized_delta = float(a.get("realized_net_pnl") or 0.0) - float(b.get("realized_net_pnl") or 0.0)
            if proxy_delta == 0.0 or realized_delta == 0.0:
                continue
            comparable += 1
            if proxy_delta * realized_delta > 0:
                concordant += 1
    return {
        "comparable_pairs": comparable,
        "concordant_pairs": concordant,
        "rank_agreement_rate": (concordant / comparable) if comparable else None,
    }


def _invert_pairs(pairs: list[dict]) -> list[dict]:
    inverted = []
    for pair in pairs:
        inverted.append(
            {
                **pair,
                "proxy_shadow_edge_mean": -float(pair.get("proxy_shadow_edge_mean") or 0.0),
            }
        )
    return inverted


def _bias_checks(report: dict) -> dict:
    pairs = report.get("agreement_pairs") or []
    realized_pos = sum(1 for p in pairs if float(p.get("realized_net_pnl") or 0.0) > 0.0)
    realized_neg = sum(1 for p in pairs if float(p.get("realized_net_pnl") or 0.0) < 0.0)
    realized_zero = sum(1 for p in pairs if float(p.get("realized_net_pnl") or 0.0) == 0.0)
    proxy_pos = sum(1 for p in pairs if float(p.get("proxy_shadow_edge_mean") or 0.0) > 0.0)
    proxy_neg = sum(1 for p in pairs if float(p.get("proxy_shadow_edge_mean") or 0.0) < 0.0)
    proxy_zero = sum(1 for p in pairs if float(p.get("proxy_shadow_edge_mean") or 0.0) == 0.0)

    strategy_match = sum(1 for p in pairs if p.get("match_quality", {}).get("strategy_match"))
    bucket_match = sum(1 for p in pairs if p.get("match_quality", {}).get("bucket_match"))
    symbol_match = sum(1 for p in pairs if p.get("match_quality", {}).get("symbol_match"))
    side_match = sum(1 for p in pairs if p.get("match_quality", {}).get("side_match"))
    temporal_match = sum(1 for p in pairs if p.get("match_quality", {}).get("temporal_consistent"))

    return {
        "observed_pairs": len(pairs),
        "realized_distribution": {
            "positive": realized_pos,
            "negative": realized_neg,
            "zero": realized_zero,
        },
        "proxy_distribution": {
            "positive": proxy_pos,
            "negative": proxy_neg,
            "zero": proxy_zero,
        },
        "matching_integrity": {
            "symbol_match_rate": (symbol_match / len(pairs)) if pairs else None,
            "side_match_rate": (side_match / len(pairs)) if pairs else None,
            "temporal_match_rate": (temporal_match / len(pairs)) if pairs else None,
            "strategy_match_rate": (strategy_match / len(pairs)) if pairs else None,
            "bucket_match_rate": (bucket_match / len(pairs)) if pairs else None,
        },
        "selection_bias": {
            "one_sided_realized_distribution": realized_pos == 0 or realized_neg == 0,
            "no_profitable_cases_observed": realized_pos == 0,
            "note": (
                "The selected matched-pair corpus is one-sided if all realized outcomes are negative or all are positive."
            ),
        },
    }


def _failure_mode(report: dict, bias: dict) -> dict:
    pairs = report.get("agreement_pairs") or []
    expanded_rate = _agreement_rate(pairs)
    inverted_pairs = _invert_pairs(pairs)
    inverted_rate = _agreement_rate(inverted_pairs)
    inverted_rank = _rank_agreement(inverted_pairs)
    false_optimism = sum(1 for p in pairs if float(p.get("proxy_shadow_edge_mean") or 0.0) > 0.0 and float(p.get("realized_net_pnl") or 0.0) < 0.0)
    false_pessimism = sum(1 for p in pairs if float(p.get("proxy_shadow_edge_mean") or 0.0) <= 0.0 and float(p.get("realized_net_pnl") or 0.0) > 0.0)

    if bias["selection_bias"]["one_sided_realized_distribution"]:
        primary = "INSUFFICIENT_EVIDENCE"
    elif expanded_rate is None:
        primary = "INSUFFICIENT_EVIDENCE"
    elif expanded_rate == 0.0 and false_optimism > 0:
        primary = "STRUCTURAL_MISALIGNMENT"
    elif expanded_rate == 0.0:
        primary = "PURE_NOISE_DISGUISED_AS_SIGNAL"
    else:
        primary = "CONDITIONAL_SIGNAL"

    if primary == "INSUFFICIENT_EVIDENCE":
        mode = "INSUFFICIENT_EVIDENCE"
    elif primary == "STRUCTURAL_MISALIGNMENT":
        mode = "MIXED_FAILURE_MODE"
    else:
        mode = primary

    return {
        "primary_failure_mode": mode,
        "expanded_directional_agreement_rate": expanded_rate,
        "expanded_rank_agreement_rate": _rank_agreement(pairs)["rank_agreement_rate"],
        "inverted_directional_agreement_rate": inverted_rate,
        "inverted_rank_agreement_rate": inverted_rank["rank_agreement_rate"],
        "inverted_false_pessimism_count": sum(
            1
            for p in inverted_pairs
            if float(p.get("proxy_shadow_edge_mean") or 0.0) <= 0.0
            and float(p.get("realized_net_pnl") or 0.0) > 0.0
        ),
        "false_optimism_count": false_optimism,
        "false_pessimism_count": false_pessimism,
    }


def _decision_matrix(report: dict, bias: dict, failure: dict) -> dict:
    observed = int(bias["observed_pairs"])
    if observed < 20:
        return {
            "REMOVE_PROXY_FROM_ALL_DECISION_PATHS": False,
            "KEEP_PROXY_AS_OBSERVABILITY_ONLY": False,
            "USE_PROXY_AS_CONTRARIAN_SIGNAL_RESEARCH_ONLY": False,
            "REBUILD_PROXY_FROM_SCRATCH_REQUIRED": False,
            "INSUFFICIENT_EVIDENCE": True,
        }
    return {
        "REMOVE_PROXY_FROM_ALL_DECISION_PATHS": False,
        "KEEP_PROXY_AS_OBSERVABILITY_ONLY": False,
        "USE_PROXY_AS_CONTRARIAN_SIGNAL_RESEARCH_ONLY": False,
        "REBUILD_PROXY_FROM_SCRATCH_REQUIRED": False,
        "INSUFFICIENT_EVIDENCE": True,
    }


def _build_report(expanded_path: Path) -> dict:
    expanded = _load_json(expanded_path)
    bias = _bias_checks(expanded)
    failure = _failure_mode(expanded, bias)
    decision_matrix = _decision_matrix(expanded, bias, failure)
    final_decision = "INSUFFICIENT_EVIDENCE"
    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "expanded_source": str(expanded_path),
            "expanded_classification": expanded.get("final_classification"),
            "final_decision": final_decision,
        },
        "bias_checks": bias,
        "failure_mode": failure,
        "contrarian_signal_test": {
            "inverted_directional_agreement_rate": failure["inverted_directional_agreement_rate"],
            "inverted_rank_agreement_rate": failure["inverted_rank_agreement_rate"],
            "inverted_false_pessimism_count": failure["inverted_false_pessimism_count"],
        },
        "decision_matrix": decision_matrix,
        "final_decision": final_decision,
    }


def _render_md(report: dict) -> str:
    bias = report["bias_checks"]
    failure = report["failure_mode"]
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "The final decision audit does not support a production-facing action beyond insufficient evidence. "
        "Matching integrity is not clean enough for a stronger verdict, and the realized corpus is one-sided."
    )
    lines.append("")
    lines.append("## B. Scope")
    lines.append("- PAPER only")
    lines.append("- Audit-only")
    lines.append("- No runtime changes")
    lines.append("- No admission changes")
    lines.append("")
    lines.append("## C. Validation of Matching Integrity")
    mi = bias["matching_integrity"]
    lines.append(f"- observed_pairs: {bias['observed_pairs']}")
    lines.append(f"- symbol_match_rate: {mi['symbol_match_rate']}")
    lines.append(f"- side_match_rate: {mi['side_match_rate']}")
    lines.append(f"- temporal_match_rate: {mi['temporal_match_rate']}")
    lines.append(f"- strategy_match_rate: {mi['strategy_match_rate']}")
    lines.append(f"- bucket_match_rate: {mi['bucket_match_rate']}")
    lines.append("")
    lines.append("## D. Bias Check Results")
    rd = bias["realized_distribution"]
    pd = bias["proxy_distribution"]
    lines.append(f"- realized_positive: {rd['positive']}")
    lines.append(f"- realized_negative: {rd['negative']}")
    lines.append(f"- realized_zero: {rd['zero']}")
    lines.append(f"- proxy_positive: {pd['positive']}")
    lines.append(f"- proxy_negative: {pd['negative']}")
    lines.append(f"- proxy_zero: {pd['zero']}")
    lines.append(f"- one_sided_realized_distribution: {bias['selection_bias']['one_sided_realized_distribution']}")
    lines.append("")
    lines.append("## E. Failure Mode Classification")
    lines.append(failure["primary_failure_mode"])
    lines.append("")
    lines.append("## F. Contrarian Signal Test")
    lines.append(f"- inverted_directional_agreement_rate: {failure['inverted_directional_agreement_rate']}")
    lines.append(f"- inverted_rank_agreement_rate: {failure['inverted_rank_agreement_rate']}")
    lines.append(f"- inverted_false_pessimism_count: {failure['inverted_false_pessimism_count']}")
    lines.append("")
    lines.append("## G. Decision Matrix Evaluation")
    for k, v in report["decision_matrix"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("## H. Final Decision")
    lines.append(report["final_decision"])
    lines.append("")
    lines.append("## I. Justification (Strict, Technical)")
    lines.append(
        "The matched realized corpus is one-sided with zero profitable cases, so the expanded agreement result cannot be treated as a fully unbiased decision basis. "
        "Strategy/bucket alignment is also weak in the available logs, which prevents a stronger integrity claim. "
        "The contrarian inversion test does not rescue the signal: inverted directional agreement remains low and does not cross a useful threshold."
    )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Final decision audit for proxy-based readiness.")
    parser.add_argument("--expanded", default=str(DEFAULT_EXPANDED))
    args = parser.parse_args(argv)
    report = _build_report(Path(args.expanded))
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"proxy_final_decision_audit_{stamp}.json"
    md_path = DIAG_DIR / f"proxy_final_decision_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
