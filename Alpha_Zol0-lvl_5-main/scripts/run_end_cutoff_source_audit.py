import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import importlib.util


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


def _load_entry_funnel_decay():
    path = WORKDIR / "scripts" / "entry_funnel_decay.py"
    spec = importlib.util.spec_from_file_location("entry_funnel_decay_run_end_dep", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


funnel_decay = _load_entry_funnel_decay()


TARGET_GATES = {"net_target_guard", "current_side"}


def _load_logs(db_path: Path) -> list[dict]:
    import sqlite3

    try:
        db_path = Path(db_path)
    except Exception:
        return []
    if not db_path.exists() or db_path.is_dir():
        return []

    try:
        conn = sqlite3.connect(str(db_path))
    except Exception:
        return []
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                "select id, timestamp, event, details from logs order by id asc"
            ).fetchall()
        except Exception:
            return []
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


def _run_scenario(symbol: str, duration_min: int, scenario: dict) -> dict:
    run = funnel_decay._run_scenario(symbol, duration_min, scenario)
    db_path = Path((run.get("report") or {}).get("before", {}).get("db_path") or "")
    logs = _load_logs(db_path) if db_path.exists() else []
    return {"run": run, "logs": logs, "db_path": str(db_path) if db_path.exists() else None}


def _pockets_from_logs(logs: list[dict]) -> list[list[dict]]:
    pockets = []
    current = []
    for row in logs:
        current.append(row)
        if row["event"] == "entry_gate_decision_summary":
            pockets.append(current)
            current = []
    return pockets


def _classify_pocket(rows: list[dict]) -> dict:
    named_blockers = []
    diagnostic_markers = []
    terminal_symptom = False
    summary = None
    for row in rows:
        payload = row["payload"]
        if row["event"] == "run_end_entry_cutoff":
            terminal_symptom = True
        if row["event"] == "diagnostic_gate_trace":
            gate_name = str(payload.get("gate_name") or "").strip()
            if gate_name in TARGET_GATES:
                diagnostic_markers.append(
                    {
                        "gate_name": gate_name,
                        "gate_blocked": bool(payload.get("gate_blocked")),
                        "gate_skipped": bool(payload.get("gate_skipped")),
                        "skip_reason": payload.get("skip_reason"),
                        "entry_state_classification": payload.get("entry_state_classification"),
                    }
                )
                if payload.get("gate_blocked") and not payload.get("gate_skipped"):
                    named_blockers.append(gate_name)
        elif row["event"] == "entry_gate_decision_summary":
            summary = payload
    top_reason = None
    if summary and summary.get("top_local_gate_reason"):
        top_reason = (summary.get("top_local_gate_reason") or [[None, 0]])[0][0]
    return {
        "summary_top_reason": top_reason,
        "summary_rows": int(summary.get("rows") or 0) if summary else 0,
        "admitted": int((summary or {}).get("admitted_vs_blocked", {}).get("admitted") or 0),
        "blocked": int((summary or {}).get("admitted_vs_blocked", {}).get("blocked") or 0),
        "diagnostic_markers": diagnostic_markers,
        "named_blockers": named_blockers,
        "terminal_symptom": terminal_symptom or top_reason == "run_end_cutoff",
        "summary_cutoff_label": top_reason == "run_end_cutoff",
    }


def _scenario_local_classification(run_end_cutoff_pockets: int, effective_blocker_counts: dict, presence_only_counts: dict) -> str:
    if run_end_cutoff_pockets <= 0:
        return "NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR"
    if effective_blocker_counts.get("net_target_guard", 0) and effective_blocker_counts.get("current_side", 0):
        return "RUN_END_CUTOFF_MIXED_SOURCES"
    if effective_blocker_counts.get("net_target_guard", 0) or effective_blocker_counts.get("current_side", 0):
        return "RUN_END_CUTOFF_MOSTLY_POST_BLOCKER_TERMINAL"
    if presence_only_counts.get("current_side", 0) or presence_only_counts.get("net_target_guard", 0):
        return "RUN_END_CUTOFF_MOSTLY_SIGNAL_SCARCITY"
    return "INSUFFICIENT_EVIDENCE"


def _interpret_visibility(run_end_cutoff_pockets: int, terminal_symptom_events: int, pocket_count: int) -> str:
    if run_end_cutoff_pockets > 0:
        return "OBSERVABLE"
    if terminal_symptom_events > 0 and pocket_count > 0:
        return "POCKET_SEGMENTATION_PREVENTS_CUTOFF_VISIBILITY"
    if pocket_count > 0:
        return "SIGNAL_SCARCITY_NO_TERMINAL_POCKET_FORMATION"
    return "INSUFFICIENT_EVIDENCE"


def _audit_symbol(symbol: str, duration_min: int, scenario_names: list[str]) -> dict:
    scenario_defs = []
    for scenario in funnel_decay.SCENARIOS:
        if scenario["name"] in scenario_names:
            scenario_defs.append(scenario)
    per_scenario = []
    classification_counter = Counter()
    for scenario in scenario_defs:
        run = _run_scenario(symbol, duration_min, scenario)
        logs = run["logs"]
        pockets = _pockets_from_logs(logs)
        pocket_stats = [_classify_pocket(pocket) for pocket in pockets]
        terminal_symptom_events = sum(1 for row in logs if row["event"] == "run_end_entry_cutoff")
        run_end_cutoff_pockets = [p for p in pocket_stats if p["terminal_symptom"]]
        diagnostic_presence_counts = {
            "net_target_guard": sum(
                1
                for p in pocket_stats
                for m in p["diagnostic_markers"]
                if m["gate_name"] == "net_target_guard"
            ),
            "current_side": sum(
                1
                for p in pocket_stats
                for m in p["diagnostic_markers"]
                if m["gate_name"] == "current_side"
            ),
        }
        effective_blocker_counts = {
            "net_target_guard": sum(
                1
                for p in run_end_cutoff_pockets
                if "net_target_guard" in p["named_blockers"]
            ),
            "current_side": sum(
                1
                for p in run_end_cutoff_pockets
                if "current_side" in p["named_blockers"]
            ),
            "other_named_blocker": sum(
                1
                for p in run_end_cutoff_pockets
                if p["named_blockers"] and not set(p["named_blockers"]).intersection(TARGET_GATES)
            ),
            "unknown": sum(1 for p in run_end_cutoff_pockets if not p["named_blockers"]),
        }
        presence_only_counts = {
            "net_target_guard": max(
                0, diagnostic_presence_counts["net_target_guard"] - effective_blocker_counts["net_target_guard"]
            ),
            "current_side": max(
                0, diagnostic_presence_counts["current_side"] - effective_blocker_counts["current_side"]
            ),
        }
        source_attribution_observable = bool(run_end_cutoff_pockets) and bool(
            effective_blocker_counts["net_target_guard"]
            or effective_blocker_counts["current_side"]
            or effective_blocker_counts["other_named_blocker"]
            or effective_blocker_counts["unknown"]
        )
        if not run_end_cutoff_pockets:
            cls = "NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR"
        else:
            cls = _scenario_local_classification(
                len(run_end_cutoff_pockets), effective_blocker_counts, presence_only_counts
            )
        classification_counter[cls] += 1
        per_scenario.append(
            {
                "scenario": scenario["name"],
                "label": scenario["label"],
                "rows": int((run.get("run").get("summary") or {}).get("rows") or 0),
                "admitted": int((run.get("run").get("summary") or {}).get("admitted_vs_blocked", {}).get("admitted") or 0),
                "blocked": int((run.get("run").get("summary") or {}).get("admitted_vs_blocked", {}).get("blocked") or 0),
                "pockets_total": len(pockets),
                "run_end_cutoff_pockets": len(run_end_cutoff_pockets),
                "terminal_symptom_events": terminal_symptom_events,
                "diagnostic_presence_counts": diagnostic_presence_counts,
                "effective_blocker_counts": effective_blocker_counts,
                "presence_only_counts": presence_only_counts,
                "source_attribution_observable": bool(source_attribution_observable),
                "lifecycle_profile": {
                    "pocket_count": len(pockets),
                    "median_pocket_length": int(
                        sorted(len(p) for p in pockets)[len(pockets)//2]
                    ) if pockets else 0,
                    "max_pocket_length": max((len(p) for p in pockets), default=0),
                    "median_events_per_pocket": int(
                        sorted(len(p) for p in pockets)[len(pockets)//2]
                    ) if pockets else 0,
                    "pockets_ending_on_summary": sum(1 for p in pockets if p and p[-1]["event"] == "entry_gate_decision_summary"),
                },
                "classification": cls,
                "local_observability_classification": cls,
                "top_local_gate_reason": [["run_end_cutoff", len(run_end_cutoff_pockets)]] if run_end_cutoff_pockets else [],
                "observability_notes": (
                    "terminal symptom observed in pocket" if run_end_cutoff_pockets else
                    ("terminal symptom event exists outside pocket visibility" if terminal_symptom_events > 0 else "no terminal symptom observed")
                ),
                "notes": (
                    "run_end_cutoff not observed in this corridor; source attribution is not available"
                    if not run_end_cutoff_pockets
                    else "source attribution derived only from observed run_end_cutoff pockets"
                ),
            }
        )
    aggregate_classification = "INSUFFICIENT_EVIDENCE"
    if any(item["classification"] == "RUN_END_CUTOFF_MOSTLY_SIGNAL_SCARCITY" for item in per_scenario):
        aggregate_classification = "RUN_END_CUTOFF_MOSTLY_SIGNAL_SCARCITY"
    elif any(item["classification"] == "RUN_END_CUTOFF_MOSTLY_POST_BLOCKER_TERMINAL" for item in per_scenario):
        aggregate_classification = "RUN_END_CUTOFF_MOSTLY_POST_BLOCKER_TERMINAL"
    elif any(item["classification"] == "RUN_END_CUTOFF_MIXED_SOURCES" for item in per_scenario):
        aggregate_classification = "RUN_END_CUTOFF_MIXED_SOURCES"
    return {
        "symbol": symbol,
        "scenario_results": per_scenario,
        "classification_counter": dict(classification_counter),
        "final_classification": aggregate_classification,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="BTCUSDTM,ETHUSDTM")
    parser.add_argument("--duration-min", type=int, default=1)
    parser.add_argument("--scenarios", default="baseline,disable_net_target_guard,disable_current_side")
    args = parser.parse_args()
    symbols = [s.strip() for s in str(args.symbols or "").split(",") if s.strip()]
    scenario_names = [s.strip() for s in str(args.scenarios or "").split(",") if s.strip()]
    report = {
        "run_metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbols": symbols,
            "scenarios": scenario_names,
            "duration_min": int(args.duration_min),
            "method_version": "observability_v2",
        },
        "per_symbol": [_audit_symbol(symbol, int(args.duration_min), scenario_names) for symbol in symbols],
    }
    aggregate = Counter(item["final_classification"] for item in report["per_symbol"])
    report["aggregate"] = {
        "total_pockets": sum(
            sum(scen["pockets_total"] for scen in symbol_report["scenario_results"])
            for symbol_report in report["per_symbol"]
        ),
        "total_run_end_cutoff_pockets": sum(
            sum(scen["run_end_cutoff_pockets"] for scen in symbol_report["scenario_results"])
            for symbol_report in report["per_symbol"]
        ),
        "named_blocker_dominance_summary": {
            "net_target_guard": sum(
                sum(scen["effective_blocker_counts"]["net_target_guard"] for scen in symbol_report["scenario_results"])
                for symbol_report in report["per_symbol"]
            ),
            "current_side": sum(
                sum(scen["effective_blocker_counts"]["current_side"] for scen in symbol_report["scenario_results"])
                for symbol_report in report["per_symbol"]
            ),
        },
        "segmentation_findings": {
            "pockets_ending_on_summary": sum(
                sum(scen["lifecycle_profile"]["pockets_ending_on_summary"] for scen in symbol_report["scenario_results"])
                for symbol_report in report["per_symbol"]
            ),
        },
        "signal_scarcity_findings": {
            "scenario_classifications": dict(aggregate),
        },
    }
    report["aggregate_classification_counts"] = dict(aggregate)
    report["final_classification"] = (
        "RUN_END_CUTOFF_MOSTLY_POST_BLOCKER_TERMINAL"
        if report["aggregate"]["total_run_end_cutoff_pockets"] > 0
        else "INSUFFICIENT_EVIDENCE"
    )

    stamp = report["run_metadata"]["stamp"]
    json_path = DIAG_DIR / f"run_end_cutoff_source_audit_{stamp}.json"
    md_path = DIAG_DIR / f"run_end_cutoff_source_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text("# Run End Cutoff Source Audit\n\n" + json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"RUN_END_CUTOFF_AUDIT_JSON={json_path}")
    print(f"RUN_END_CUTOFF_AUDIT_MD={md_path}")
    print(json.dumps(report.get("final_classification"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
