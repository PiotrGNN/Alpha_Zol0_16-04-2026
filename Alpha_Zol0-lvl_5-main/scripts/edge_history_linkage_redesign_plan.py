from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _default_canonical_audit_path() -> Path:
    candidates = sorted(DIAG_DIR.glob("canonical_bucket_alignment_*.json"))
    if not candidates:
        raise FileNotFoundError("No canonical_bucket_alignment_*.json artifact found")
    return candidates[-1]


def _default_readiness_path() -> Path:
    candidates = sorted(DIAG_DIR.glob("long_canonical_readiness_unlock_*.json"))
    if not candidates:
        raise FileNotFoundError("No long_canonical_readiness_unlock_*.json artifact found")
    return candidates[-1]


def _build_report(canonical_audit_path: Path, readiness_path: Path) -> dict:
    if not canonical_audit_path.is_absolute():
        canonical_audit_path = (WORKDIR / canonical_audit_path).resolve()
    if not readiness_path.is_absolute():
        readiness_path = (WORKDIR / readiness_path).resolve()
    canonical = _load_json(canonical_audit_path)
    readiness = _load_json(readiness_path)
    readiness_source = {}
    source_result = (readiness.get("run_parameters") or {}).get("source_result")
    if source_result:
        source_result_path = Path(source_result)
        if not source_result_path.is_absolute():
            source_result_path = (WORKDIR / source_result_path).resolve()
        if source_result_path.exists():
            readiness_source = _load_json(source_result_path)
    coverage = canonical.get("coverage") or {}
    alignment = canonical.get("alignment") or {}
    readiness_history = readiness.get("history_ready") or {}
    canonical_growth = readiness.get("canonical_bucket_trade_count_growth") or []
    gate_trade_count_max = max(
        (int(b.get("trade_count_max") or 0) for b in canonical_growth),
        default=0,
    )
    gate_close_writes = sum(int(b.get("close_writes") or 0) for b in canonical_growth)
    source_before = readiness_source.get("before") or {}

    current_failure_recap = {
        "canonical_alignment_rate": float(alignment.get("resolved_alignment_rate") or 0.0),
        "canonical_evaluated_resolved_share": float(
            alignment.get("evaluated_resolved_share") or 0.0
        ),
        "canonical_close_resolved_share": float(
            alignment.get("close_resolved_share") or 0.0
        ),
        "canonical_alignment_improved": bool(
            canonical.get("conclusion", {}).get("readiness_alignment_improved")
        ),
        "readiness_still_not_reached": bool(
            not bool(readiness_history.get("history_ready_any"))
        ),
        "expected_nonzero": int(readiness_history.get("expected_nonzero") or 0),
        "gate_trade_count_max": int(gate_trade_count_max),
    }

    write_path = {
        "function": "_update_symbol_strategy_side_edge_perf",
        "source_event": "position_close",
        "storage_container": "symbol_strategy_side_edge_perf[symbol][strategy][side]",
        "promotes": [
            "gross",
            "fee",
            "spread_slippage_proxy",
            "trade_count = len(gross_hist)",
        ],
    }

    read_path = {
        "function": "_entry_edge_over_fee_check",
        "snapshot_functions": [
            "_symbol_strategy_side_edge_perf_snapshot",
            "_symbol_side_edge_perf_snapshot",
        ],
        "reads": [
            "trade_count",
            "mean_gross_fill_model",
            "mean_fee_total",
            "mean_spread_slippage_proxy",
            "history_ready = trade_count >= min_trades",
        ],
    }

    missing_link = {
        "description": "There is no explicit promotion layer between realized close history and evaluated edge-history readiness state.",
        "root_gap": "close writes update realized storage, but the gate only sees readiness through a later snapshot/read step that still depends on accumulated closes in the same bucket.",
        "timing_gap": "the audited corridor completes evaluation rows before enough close-time appends accumulate trade_count in the evaluated canonical bucket.",
        "state_gap": "the system lacks a dedicated canonical edge-history promotion object that can be shadow-read by the gate immediately after close writes.",
    }

    redesign = {
        "model": "research_only_canonical_edge_history_linkage",
        "components": [
            {
                "name": "canonical_edge_history_state",
                "role": "shadow-only promotion target shared by close and evaluated paths",
            },
            {
                "name": "close_promotion_hook",
                "role": "on position_close, append realized outcome into the canonical state using the same canonical bucket key",
            },
            {
                "name": "evaluated_shadow_read",
                "role": "gate reads canonical shadow state for diagnostics without mutating production readiness",
            },
            {
                "name": "explicit_unresolved_pool",
                "role": "rows that cannot resolve canonical identity remain separate and are not merged into readiness buckets",
            },
        ],
        "minimal_changes": [
            "add a research-only canonical shadow state object",
            "emit resolved/unresolved bucket identity on both paths",
            "shadow-read canonical state in audit mode only",
            "keep production trade_count/history_ready semantics unchanged",
        ],
    }

    validation = {
        "shadow_alignment_rate_target": "> 0.7 on resolved rows",
        "readiness_unlock_target": "at least one canonical bucket reaches trade_count >= min_trades in the long corridor",
        "non_regression_rules": [
            "production admission semantics unchanged",
            "min_trades unchanged",
            "unresolved rows remain explicit",
            "no proxy path introduced",
        ],
        "acceptance_checks": [
            "canonical read/write keys match exactly for resolved rows",
            "gate-side trade_count increases after close promotions in the shadow state",
            "history_ready becomes true only when the canonical shadow bucket genuinely accumulates enough closes",
        ],
    }

    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "scenarios": ["baseline", "disable_current_side", "disable_net_target_guard"],
            "method_version": "edge_history_linkage_redesign_v1",
        },
        "current_failure_recap": current_failure_recap,
        "write_path": write_path,
        "read_path": read_path,
        "missing_link": missing_link,
        "redesign": redesign,
        "validation": validation,
        "evidence": {
            "canonical_alignment": {
                "evaluated_total": int(coverage.get("evaluated_total") or 0),
                "evaluated_resolved": int(coverage.get("evaluated_resolved") or 0),
                "close_total": int(coverage.get("close_total") or 0),
                "close_resolved": int(coverage.get("close_resolved") or 0),
                "resolved_alignment_rate": float(
                    alignment.get("resolved_alignment_rate") or 0.0
                ),
            },
            "readiness": {
                "gate_trade_count_max": int(gate_trade_count_max),
                "gate_close_writes": int(gate_close_writes),
                "trade_count": int(source_before.get("trade_count") or 0),
                "position_close": int((source_before.get("event_counts") or {}).get("position_close") or 0),
                "history_ready_any": bool(readiness_history.get("history_ready_any")),
                "history_ready_true_count": int(
                    readiness_history.get("history_ready_true_count") or 0
                ),
                "expected_nonzero": int(readiness_history.get("expected_nonzero") or 0),
                "current_edge_nonzero": int(
                    readiness_history.get("current_edge_nonzero") or 0
                ),
            },
        },
        "conclusion": {
            "architectural_consequence": "close writes and evaluated readiness still need an explicit research-only promotion bridge",
            "readiness_unlock_feasible": True,
            "profitability_testing_premature": True,
        },
        "final_classification": "LINKAGE_REDESIGN_REQUIRED_AND_FEASIBLE",
    }


def _render_md(report: dict) -> str:
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "Canonical bucket identity is aligned, but close-history still does not become usable edge-history state because there is no explicit promotion bridge from close writes into the evaluated readiness read path."
    )
    lines.append("")
    lines.append("## B. Current Linkage Failure")
    lines.append(
        "The write path persists realized close history, while the gate only reads readiness later through bucket snapshots. In the audited corridor, that linkage is still too late to produce `trade_count > 0` before evaluation exhaustion."
    )
    lines.append("")
    lines.append("## C. Write Path")
    lines.append(f"- function: `{report['write_path']['function']}`")
    lines.append(f"- source event: `{report['write_path']['source_event']}`")
    lines.append(f"- storage container: `{report['write_path']['storage_container']}`")
    lines.append("")
    lines.append("## D. Read Path")
    lines.append(f"- function: `{report['read_path']['function']}`")
    lines.append(
        f"- snapshot functions: {', '.join(report['read_path']['snapshot_functions'])}"
    )
    lines.append(f"- readiness rule: `{' / '.join(report['read_path']['reads'])}`")
    lines.append("")
    lines.append("## E. Missing Link / Promotion Gap")
    lines.append(report["missing_link"]["description"])
    lines.append(report["missing_link"]["root_gap"])
    lines.append(report["missing_link"]["timing_gap"])
    lines.append(report["missing_link"]["state_gap"])
    lines.append("")
    lines.append("## F. Minimal Research-Only Redesign")
    for item in report["redesign"]["components"]:
        lines.append(f"- `{item['name']}`: {item['role']}")
    lines.append("")
    lines.append("## G. Validation Plan")
    for rule in report["validation"]["non_regression_rules"]:
        lines.append(f"- {rule}")
    for check in report["validation"]["acceptance_checks"]:
        lines.append(f"- {check}")
    lines.append("")
    lines.append("## H. Final Recommendation")
    lines.append(report["final_classification"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create a research-only linkage redesign plan.")
    parser.add_argument("--canonical-audit-result", default=None)
    parser.add_argument("--readiness-result", default=None)
    args = parser.parse_args(argv)

    canonical_path = Path(args.canonical_audit_result) if args.canonical_audit_result else _default_canonical_audit_path()
    if not canonical_path.is_absolute():
        canonical_path = (WORKDIR / canonical_path).resolve()
    readiness_path = Path(args.readiness_result) if args.readiness_result else _default_readiness_path()
    if not readiness_path.is_absolute():
        readiness_path = (WORKDIR / readiness_path).resolve()

    report = _build_report(canonical_path, readiness_path)
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"edge_history_linkage_redesign_plan_{stamp}.json"
    md_path = DIAG_DIR / f"edge_history_linkage_redesign_plan_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
