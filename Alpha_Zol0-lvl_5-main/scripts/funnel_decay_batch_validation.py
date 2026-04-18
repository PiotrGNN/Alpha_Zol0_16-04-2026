import argparse
import json
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


def _load_funnel_decay_module():
    path = WORKDIR / "scripts" / "entry_funnel_decay.py"
    spec = importlib.util.spec_from_file_location("entry_funnel_decay_batch_dep", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


funnel_decay = _load_funnel_decay_module()


def _scenario_label(name: str) -> str:
    for scenario in funnel_decay.SCENARIOS:
        if scenario["name"] == name:
            return scenario["label"]
    return name


def _scenario_env(name: str) -> dict:
    for scenario in funnel_decay.SCENARIOS:
        if scenario["name"] == name:
            return dict(scenario.get("env") or {})
    return {}


def _run_batch(symbols: list[str], duration_min: int, scenarios: list[str]) -> dict:
    selected = [scenario for scenario in funnel_decay.SCENARIOS if scenario["name"] in scenarios]
    results = []
    for symbol in symbols:
        symbol_runs = []
        for scenario in selected:
            run = funnel_decay._run_scenario(symbol, duration_min, scenario)
            symbol_runs.append(run)
            results.append(
                {
                    "symbol": symbol,
                    "scenario": scenario["name"],
                    "label": scenario["label"],
                    "run": run,
                }
            )

    per_symbol = []
    by_symbol = {symbol: [] for symbol in symbols}
    for row in results:
        by_symbol[row["symbol"]].append(row["run"])

    for symbol, symbol_runs in by_symbol.items():
        report = funnel_decay.build_report(symbol_runs, symbol, duration_min)
        per_symbol.append(
            {
                "symbol": symbol,
                "report": report,
                "final_classification": report.get("final_classification"),
                "scenario_count": len(symbol_runs),
            }
        )

    scenario_rollup = []
    for scenario_name in scenarios:
        scen_runs = [row["run"] for row in results if row["scenario"] == scenario_name]
        if not scen_runs:
            continue
        report = funnel_decay.build_report(scen_runs, symbols[0], duration_min)
        scenario_rollup.append(
            {
                "scenario": scenario_name,
                "label": _scenario_label(scenario_name),
                "env": _scenario_env(scenario_name),
                "symbol_count": len(scen_runs),
                "rows": [
                    {
                        "symbol": row["symbol"],
                        "summary_rows": int((row["run"].get("summary") or {}).get("rows") or 0),
                        "admitted_rows": int(
                            (row["run"].get("summary") or {}).get("admitted_vs_blocked", {}).get("admitted")
                            or 0
                        ),
                        "blocked_rows": int(
                            (row["run"].get("summary") or {}).get("admitted_vs_blocked", {}).get("blocked")
                            or 0
                        ),
                        "final_classification": report.get("final_classification"),
                    }
                    for row in results
                    if row["scenario"] == scenario_name
                ],
            }
        )

    aggregate_counts = {}
    for item in per_symbol:
        cls = str(item.get("final_classification") or "INSUFFICIENT_EVIDENCE")
        aggregate_counts[cls] = aggregate_counts.get(cls, 0) + 1

    if aggregate_counts:
        final_classification = max(aggregate_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
    else:
        final_classification = "INSUFFICIENT_EVIDENCE"

    return {
        "run_metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "mode": "PAPER",
            "scenario_count": len(scenarios),
            "symbol_count": len(symbols),
            "symbols": symbols,
            "scenarios": scenarios,
            "duration_min": duration_min,
        },
        "per_symbol": per_symbol,
        "per_scenario": scenario_rollup,
        "aggregate_classification_counts": aggregate_counts,
        "final_classification": (
            "UPSTREAM_SIGNAL_SCARCITY_REPEATED_ACROSS_SMALL_BATCH"
            if aggregate_counts.get("UPSTREAM_SIGNAL_SCARCITY_DOMINATES", 0) == len(per_symbol)
            else (
                "MIXED_RESULTS_ACROSS_SMALL_BATCH"
                if len(aggregate_counts) > 1
                else final_classification
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="BTCUSDTM,ETHUSDTM")
    parser.add_argument("--duration-min", type=int, default=1)
    parser.add_argument(
        "--scenarios",
        default="baseline,disable_current_side,disable_net_target_guard",
        help="Comma-separated scenario names to run.",
    )
    args = parser.parse_args()

    symbols = [s.strip() for s in str(args.symbols or "").split(",") if s.strip()]
    scenarios = [s.strip() for s in str(args.scenarios or "").split(",") if s.strip()]
    report = _run_batch(symbols, int(args.duration_min), scenarios)

    stamp = report["run_metadata"]["stamp"]
    json_path = DIAG_DIR / f"funnel_decay_batch_validation_{stamp}.json"
    md_path = DIAG_DIR / f"funnel_decay_batch_validation_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(
        "# Funnel Decay Batch Validation\n\n" + json.dumps(report, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    print(f"FUNNEL_BATCH_JSON={json_path}")
    print(f"FUNNEL_BATCH_MD={md_path}")
    print(json.dumps(report.get("final_classification"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
