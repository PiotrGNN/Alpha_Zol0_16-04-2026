import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


SCENARIOS = {
    "baseline": {
        "diagnostic_mode": "0",
        "env": {},
        "label": "Scenario 0 — Baseline",
    },
    "disable_net_target_guard": {
        "diagnostic_mode": "1",
        "env": {"DIAG_DISABLE_NET_TARGET_GUARD": "1"},
        "label": "Scenario 1 — Disable net_target_guard",
    },
    "disable_current_side": {
        "diagnostic_mode": "1",
        "env": {"DIAG_ALLOW_REENTRY_WHILE_IN_POSITION": "1"},
        "label": "Scenario 2 — Disable current_side",
    },
}


def _load_module():
    spec = None
    path = WORKDIR / "scripts" / "entry_funnel_decay.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("entry_funnel_decay_audit_dep", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


funnel_decay = _load_module()


def _load_logs(db_path: Path) -> list[dict]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select id, timestamp, event, details from logs order by id asc"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        try:
            payload = json.loads(row["details"])
        except Exception:
            payload = {}
        out.append(
            {
                "id": int(row["id"]),
                "timestamp": row["timestamp"],
                "event": row["event"],
                "payload": payload if isinstance(payload, dict) else {},
            }
        )
    return out


def _run_scenario(symbol: str, duration_min: int, scenario_name: str) -> dict:
    scenario = SCENARIOS[scenario_name]
    result = funnel_decay._run_scenario(symbol, duration_min, {
        "name": scenario_name,
        "diagnostic_mode": scenario["diagnostic_mode"],
        "env": scenario["env"],
        "label": scenario["label"],
    })
    report = result.get("report") or {}
    db_path = Path(report.get("before", {}).get("db_path") or "")
    logs = _load_logs(db_path) if db_path.exists() else []
    return {
        "symbol": symbol,
        "scenario": scenario_name,
        "label": scenario["label"],
        "result": result,
        "logs": logs,
        "db_path": str(db_path) if db_path.exists() else None,
    }


def _build_pockets(logs: list[dict]) -> list[dict]:
    pockets = []
    current = {
        "summary": None,
        "trace_gates": [],
        "trace_payloads": [],
        "start_id": None,
        "end_id": None,
    }
    for row in logs:
        event = row["event"]
        payload = row["payload"]
        if current["start_id"] is None:
            current["start_id"] = row["id"]
        current["end_id"] = row["id"]
        if event == "diagnostic_gate_trace":
            gate_name = str(payload.get("gate_name") or "").strip()
            if gate_name:
                current["trace_gates"].append(gate_name)
                current["trace_payloads"].append(payload)
        elif event == "entry_gate_decision_summary":
            current["summary"] = payload
            pockets.append(current)
            current = {
                "summary": None,
                "trace_gates": [],
                "trace_payloads": [],
                "start_id": None,
                "end_id": None,
            }
    return [p for p in pockets if p.get("summary")]


def _classify_symbol(symbol_runs: list[dict]) -> dict:
    per_scenario = []
    gate_presence = Counter()
    pair_overlap = Counter()
    scenario_top = {}
    run_end_cutoff_count = Counter()
    for run in symbol_runs:
        pockets = _build_pockets(run["logs"])
        pocket_gate_sets = [set(p["trace_gates"]) for p in pockets]
        summary_reasons = Counter(
            str((p["summary"].get("top_local_gate_reason") or [["unknown", 0]])[0][0])
            for p in pockets
            if p.get("summary")
        )
        current_side_pockets = 0
        net_guard_pockets = 0
        run_end_pockets = 0
        both_pockets = 0
        for pocket in pockets:
            gates = set(pocket["trace_gates"])
            if "current_side" in gates:
                current_side_pockets += 1
            if "net_target_guard" in gates:
                net_guard_pockets += 1
            if "current_side" in gates and "net_target_guard" in gates:
                both_pockets += 1
            if pocket["summary"]:
                top_reason = (pocket["summary"].get("top_local_gate_reason") or [["unknown", 0]])[0][0]
                if top_reason == "run_end_cutoff":
                    run_end_pockets += 1
        scenario_top[run["scenario"]] = {
            "current_side_pockets": current_side_pockets,
            "net_target_guard_pockets": net_guard_pockets,
            "both_pockets": both_pockets,
            "run_end_cutoff_pockets": run_end_pockets,
            "pocket_count": len(pockets),
            "top_local_gate_reason": run["result"].get("summary", {}).get("top_local_gate_reason", []),
            "gate_trace_by_gate": run["result"].get("diagnostic_summary", {}).get("gate_trace_by_gate", []),
        }
        gate_presence["current_side"] += current_side_pockets
        gate_presence["net_target_guard"] += net_guard_pockets
        gate_presence["run_end_cutoff"] += run_end_pockets
        pair_overlap["both"] += both_pockets
        if run_end_pockets:
            run_end_cutoff_count[run["scenario"]] = run_end_pockets
        per_scenario.append(
            {
                "scenario": run["scenario"],
                "label": run["label"],
                "rows": int((run["result"].get("summary") or {}).get("rows") or 0),
                "admitted": int((run["result"].get("summary") or {}).get("admitted_vs_blocked", {}).get("admitted") or 0),
                "blocked": int((run["result"].get("summary") or {}).get("admitted_vs_blocked", {}).get("blocked") or 0),
                "pocket_count": len(pockets),
                "gate_presence": {
                    "current_side": current_side_pockets,
                    "net_target_guard": net_guard_pockets,
                    "both": both_pockets,
                    "run_end_cutoff": run_end_pockets,
                },
            }
        )
    classification = "INSUFFICIENT_EVIDENCE"
    if gate_presence["net_target_guard"] and gate_presence["current_side"] and pair_overlap["both"] == 0:
        classification = "PARALLEL_BLOCKER_POPULATIONS"
    elif gate_presence["net_target_guard"] and gate_presence["current_side"] and pair_overlap["both"] > 0:
        classification = "MIXED_INTERACTION"
    elif gate_presence["net_target_guard"] and gate_presence["current_side"]:
        classification = "DOWNSTREAM_CHAIN_RELATION"
    return {
        "per_scenario": per_scenario,
        "scenario_top": scenario_top,
        "interaction_classification": classification,
        "gate_presence": dict(gate_presence),
        "pair_overlap": dict(pair_overlap),
        "run_end_cutoff_count": dict(run_end_cutoff_count),
    }


def build_report(results_by_symbol: dict[str, list[dict]], symbols: list[str], duration_min: int, scenarios: list[str]) -> dict:
    per_symbol = []
    aggregate = Counter()
    for symbol in symbols:
        cls = _classify_symbol(results_by_symbol.get(symbol, []))
        aggregate[cls["interaction_classification"]] += 1
        per_symbol.append(
            {
                "symbol": symbol,
                **cls,
            }
        )
    if aggregate.get("MIXED_INTERACTION"):
        final_classification = "MIXED_BLOCKER_INTERACTION"
    elif aggregate.get("PARALLEL_BLOCKER_POPULATIONS"):
        final_classification = "PARALLEL_BLOCKER_POPULATIONS_DOMINATE"
    elif aggregate.get("DOWNSTREAM_CHAIN_RELATION"):
        final_classification = "CURRENT_SIDE_IS_PRIMARY_AFTER_NET_RELEASE"
    else:
        final_classification = "INSUFFICIENT_EVIDENCE"
    return {
        "run_metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbols": symbols,
            "scenarios": scenarios,
            "duration_min": duration_min,
            "artifact_sources": {
                "controlled_kpi_run": "scripts/controlled_kpi_run.py",
                "entry_summary": "scripts/report_entry_gate_decision_summary.py",
                "logs_db": "tmp/controlled_kpi_<variant>_<run_id>.db",
            },
        },
        "per_symbol": per_symbol,
        "aggregate_classification_counts": dict(aggregate),
        "final_classification": final_classification,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="BTCUSDTM,ETHUSDTM")
    parser.add_argument("--duration-min", type=int, default=1)
    parser.add_argument("--scenarios", default="baseline,disable_net_target_guard,disable_current_side")
    args = parser.parse_args()
    symbols = [s.strip() for s in str(args.symbols or "").split(",") if s.strip()]
    scenarios = [s.strip() for s in str(args.scenarios or "").split(",") if s.strip()]
    results_by_symbol = {symbol: [] for symbol in symbols}
    for symbol in symbols:
        for scenario in scenarios:
            results_by_symbol[symbol].append(_run_scenario(symbol, int(args.duration_min), scenario))
    report = build_report(results_by_symbol, symbols, int(args.duration_min), scenarios)
    stamp = report["run_metadata"]["stamp"]
    json_path = DIAG_DIR / f"blocker_interaction_audit_{stamp}.json"
    md_path = DIAG_DIR / f"blocker_interaction_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text("# Blocker Interaction Audit\n\n" + json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"BLOCKER_INTERACTION_JSON={json_path}")
    print(f"BLOCKER_INTERACTION_MD={md_path}")
    print(json.dumps(report.get("final_classification"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
