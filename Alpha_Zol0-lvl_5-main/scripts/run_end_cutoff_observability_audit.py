import argparse
import importlib.util
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


def _load_source_audit():
    path = WORKDIR / "scripts" / "run_end_cutoff_source_audit.py"
    spec = importlib.util.spec_from_file_location("run_end_cutoff_source_audit_dep", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


source_audit = _load_source_audit()


def build_report(symbols: list[str], duration_min: int, scenarios: list[str]) -> dict:
    per_symbol = [
        source_audit._audit_symbol(symbol, int(duration_min), scenarios)
        for symbol in symbols
    ]
    aggregate = Counter(item["final_classification"] for item in per_symbol)
    observable_symbol_count = sum(
        1
        for symbol_report in per_symbol
        if any(
            scen["source_attribution_observable"]
            for scen in symbol_report["scenario_results"]
        )
    )
    non_observable_symbol_count = len(per_symbol) - observable_symbol_count
    total_pockets = sum(
        sum(scen["pockets_total"] for scen in symbol_report["scenario_results"])
        for symbol_report in per_symbol
    )
    total_run_end_cutoff_pockets = sum(
        sum(scen["run_end_cutoff_pockets"] for scen in symbol_report["scenario_results"])
        for symbol_report in per_symbol
    )
    report = {
        "run_metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbols": symbols,
            "scenarios": scenarios,
            "duration_min": int(duration_min),
            "method_version": "observability_v2",
        },
        "per_symbol": per_symbol,
        "aggregate": {
            "total_pockets": total_pockets,
            "total_run_end_cutoff_pockets": total_run_end_cutoff_pockets,
            "named_blocker_dominance_summary": {
                "net_target_guard": sum(
                    sum(scen["effective_blocker_counts"]["net_target_guard"] for scen in symbol_report["scenario_results"])
                    for symbol_report in per_symbol
                ),
                "current_side": sum(
                    sum(scen["effective_blocker_counts"]["current_side"] for scen in symbol_report["scenario_results"])
                    for symbol_report in per_symbol
                ),
            },
            "segmentation_findings": {
                "pockets_ending_on_summary": sum(
                    sum(scen["lifecycle_profile"]["pockets_ending_on_summary"] for scen in symbol_report["scenario_results"])
                    for symbol_report in per_symbol
                ),
            },
            "signal_scarcity_findings": {
                "scenario_classifications": dict(aggregate),
            },
            "final_classification": (
                "MIXED_OBSERVABILITY_LIMITS"
                if observable_symbol_count > 0 and non_observable_symbol_count > 0
                else (
                    "UPSTREAM_BLOCKER_DOMINANCE_BEFORE_CUTOFF"
                    if total_run_end_cutoff_pockets > 0 and non_observable_symbol_count == 0
                    else "INSUFFICIENT_EVIDENCE"
                )
            ),
        },
        "aggregate_classification_counts": dict(aggregate),
        "final_classification": (
            "MIXED_OBSERVABILITY_LIMITS"
            if observable_symbol_count > 0 and non_observable_symbol_count > 0
            else (
                "UPSTREAM_BLOCKER_DOMINANCE_BEFORE_CUTOFF"
                if total_run_end_cutoff_pockets > 0 and non_observable_symbol_count == 0
                else "INSUFFICIENT_EVIDENCE"
            )
        ),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="BTCUSDTM,ETHUSDTM")
    parser.add_argument("--duration-min", type=int, default=1)
    parser.add_argument("--scenarios", default="baseline,disable_net_target_guard,disable_current_side")
    args = parser.parse_args()
    symbols = [s.strip() for s in str(args.symbols or "").split(",") if s.strip()]
    scenarios = [s.strip() for s in str(args.scenarios or "").split(",") if s.strip()]
    report = build_report(symbols, int(args.duration_min), scenarios)
    stamp = report["run_metadata"]["stamp"]
    json_path = DIAG_DIR / f"run_end_cutoff_observability_audit_{stamp}.json"
    md_path = DIAG_DIR / f"run_end_cutoff_observability_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text("# Run End Cutoff Observability Audit\n\n" + json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"RUN_END_CUTOFF_OBSERVABILITY_JSON={json_path}")
    print(f"RUN_END_CUTOFF_OBSERVABILITY_MD={md_path}")
    print(json.dumps(report.get("final_classification"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
