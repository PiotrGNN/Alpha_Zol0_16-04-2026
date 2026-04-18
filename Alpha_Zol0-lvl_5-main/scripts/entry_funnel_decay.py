import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


SCENARIOS = [
    {
        "name": "baseline",
        "diagnostic_mode": "0",
        "env": {},
        "label": "Scenario 0 — Baseline",
    },
    {
        "name": "disable_current_side",
        "diagnostic_mode": "1",
        "env": {"DIAG_ALLOW_REENTRY_WHILE_IN_POSITION": "1"},
        "label": "Scenario 2 — Disable current_side",
    },
    {
        "name": "disable_net_target_guard",
        "diagnostic_mode": "1",
        "env": {"DIAG_DISABLE_NET_TARGET_GUARD": "1"},
        "label": "Scenario 1 — Disable net_target_guard",
    },
]

FUNNEL_METRIC_DEFINITIONS = {
    "rows": {
        "source": "entry_gate_decision_summary",
        "meaning": "Number of entry gate decision summary rows emitted by the run.",
    },
    "candidate_entry_rows": {
        "source": "strategy_signals",
        "meaning": "Number of raw strategy signal emission events. This is an upstream event count and is not required to be <= rows.",
    },
    "rows_reaching_gate_chain": {
        "source": "entry_live_edge_eval",
        "meaning": "Number of entry live-edge evaluation events emitted in the run.",
    },
    "rows_surviving_prefilter_risk": {
        "source": "entry_edge_over_fee_eval",
        "meaning": "Number of entry edge-over-fee evaluation events emitted in the run.",
    },
    "admitted_rows": {
        "source": "entry_gate_decision_summary.admitted_vs_blocked.admitted",
        "meaning": "Number of admitted rows in the summary artifact.",
    },
    "blocked_rows": {
        "source": "entry_gate_decision_summary.admitted_vs_blocked.blocked",
        "meaning": "Number of blocked rows in the summary artifact.",
    },
    "run_end_cutoff_rows": {
        "source": "entry_gate_decision_summary.top_local_gate_reason",
        "meaning": "Top local gate reason count when that reason is run_end_cutoff.",
    },
}


def _parse_marker(stdout_text: str, marker: str) -> Path | None:
    for line in (stdout_text or "").splitlines():
        if line.startswith(marker):
            raw = line.split("=", 1)[1].strip()
            if not raw:
                return None
            path = Path(raw)
            if not path.is_absolute():
                path = (WORKDIR / path).resolve()
            return path
    return None


def _read_json(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _run_scenario(symbol: str, duration_min: int, scenario: dict) -> dict:
    cmd = [
        sys.executable,
        str((WORKDIR / "scripts" / "controlled_kpi_run.py").resolve()),
        "--variant-only",
        "before",
        "--before-min",
        str(int(duration_min)),
        "--symbols",
        symbol,
        "--market-type",
        "futures",
        "--timeframe",
        "1",
        "--use-mock",
        "--paper-auto-close-sec",
        "10",
        "--quality-profile",
        "--no-alpha-bootstrap-auto-refresh",
        "--alpha-bootstrap-source-db-url",
        "sqlite:///D:/Alpha_Zol0-lvl_5-main/zol0.db",
        "--alpha-bootstrap-source-db-glob",
        "D:/Alpha_Zol0-lvl_5-main/zol0.db",
    ]
    if scenario["name"] != "baseline":
        cmd.append("--paper-auto-open")
    before_env = {
        "DIAGNOSTIC_MODE": str(scenario["diagnostic_mode"]),
        "LIVE": "0",
        "ENTRY_MIN_NET_USDT": "0.12",
        "LOSS_COOLDOWN_SEC": "0",
        "RESEARCH_HOLD_TRANSITION_DEBUG": "1",
        "RESEARCH_TF_GATE_DEBUG": "1",
        "RESEARCH_EXPECTED_EDGE_DEBUG": "1",
        "RESEARCH_NET_TARGET_GUARD_DEBUG": "1",
    }
    before_env.update(scenario.get("env") or {})
    for key, value in sorted(before_env.items()):
        cmd.extend(["--before-env", f"{key}={value}"])

    proc = subprocess.run(
        cmd,
        cwd=str(WORKDIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    report_json = _parse_marker(proc.stdout, "REPORT_JSON=")
    report = _read_json(report_json)
    diag_json = _parse_marker(proc.stdout, "DIAGNOSTIC_REPORT_JSON=")
    diag_summary = _read_json(diag_json)
    summary_json = None
    db_path = Path(report.get("before", {}).get("db_path") or "")
    if db_path.exists():
        summary_proc = subprocess.run(
            [
                sys.executable,
                str((WORKDIR / "scripts" / "report_entry_gate_decision_summary.py").resolve()),
                "--db-path",
                str(db_path),
                "--hours",
                "0",
            ],
            cwd=str(WORKDIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if summary_proc.returncode == 0:
            try:
                summary_json = json.loads(summary_proc.stdout)
            except Exception:
                summary_json = {}
    return {
        "name": scenario["name"],
        "label": scenario["label"],
        "cmd": cmd,
        "returncode": proc.returncode,
        "report": report,
        "summary": summary_json or {},
        "diagnostic_summary": diag_summary or {},
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "artifacts": {
            "report_json": str(report_json) if report_json else None,
            "diag_json": str(diag_json) if diag_json else None,
        },
        "env": before_env,
    }


def _count_from_event_counts(report: dict, key: str) -> int:
    return int((report.get("before") or {}).get("event_counts", {}).get(key) or 0)


def _funnel_for_run(run: dict) -> dict:
    report = run.get("report") or {}
    summary = run.get("summary") or {}
    diag = run.get("diagnostic_summary") or {}
    event_counts = (report.get("before") or {}).get("event_counts", {}) or {}
    summary_rows = int(summary.get("rows") or 0)
    strategy_signal_rows = int(event_counts.get("strategy_signals") or 0)
    gate_chain_rows = int(event_counts.get("entry_live_edge_eval") or 0)
    surviving_prefilter_rows = int(event_counts.get("entry_edge_over_fee_eval") or 0)
    admitted = int(summary.get("admitted_vs_blocked", {}).get("admitted") or 0)
    blocked = int(summary.get("admitted_vs_blocked", {}).get("blocked") or 0)
    metric_alignment = {
        "rows_vs_strategy_signals": {
            "rows": summary_rows,
            "strategy_signal_rows": strategy_signal_rows,
            "delta": summary_rows - strategy_signal_rows,
            "same_source": False,
            "note": (
                "These counts come from different pipeline stages and are not expected "
                "to satisfy a subset invariant."
            ),
        },
        "gate_chain_vs_strategy_signals": {
            "strategy_signal_rows": strategy_signal_rows,
            "rows_reaching_gate_chain": gate_chain_rows,
            "delta": strategy_signal_rows - gate_chain_rows,
            "same_source": False,
            "note": "Upstream candidate signals vs live-edge evaluation events.",
        },
        "surviving_prefilter_vs_gate_chain": {
            "rows_reaching_gate_chain": gate_chain_rows,
            "rows_surviving_prefilter_risk": surviving_prefilter_rows,
            "delta": gate_chain_rows - surviving_prefilter_rows,
            "same_source": False,
            "note": "Live-edge vs edge-over-fee evaluation events.",
        },
    }
    return {
        "scenario": run["name"],
        "label": run["label"],
        "metric_definitions": FUNNEL_METRIC_DEFINITIONS,
        "metric_alignment": metric_alignment,
        "summary_rows": summary_rows,
        "strategy_signal_rows": strategy_signal_rows,
        "rows_reaching_gate_chain": gate_chain_rows,
        "rows_surviving_prefilter_risk": surviving_prefilter_rows,
        # Legacy aliases retained for compatibility with existing consumers.
        "rows": summary_rows,
        "candidate_entry_rows": strategy_signal_rows,
        "blocked_by_gate": {
            "current_side": int(
                next((g.get("blocked_count") for g in diag.get("gate_trace_by_gate", []) if g.get("gate_name") == "current_side"), 0) or 0
            ),
            "net_target_guard": int(
                next((g.get("blocked_count") for g in diag.get("gate_trace_by_gate", []) if g.get("gate_name") == "net_target_guard"), 0) or 0
            ),
            "side_guard": int(
                next((g.get("blocked_count") for g in diag.get("gate_trace_by_gate", []) if g.get("gate_name") == "side_guard"), 0) or 0
            ),
            "side_expectancy": int(
                next((g.get("blocked_count") for g in diag.get("gate_trace_by_gate", []) if g.get("gate_name") == "side_expectancy"), 0) or 0
            ),
        },
        "admitted_rows": admitted,
        "blocked_rows": blocked,
        "run_end_cutoff_rows": int((summary.get("top_local_gate_reason") or [[None, 0]])[0][1] or 0) if summary.get("top_local_gate_reason") else 0,
        "top_local_gate_reason": summary.get("top_local_gate_reason", []),
        "gate_trace_summary": diag.get("gate_trace_summary", {}),
        "gate_trace_by_gate": diag.get("gate_trace_by_gate", []),
        "event_counts": {
            "strategy_signals": strategy_signal_rows,
            "ensemble_signals": int(event_counts.get("ensemble_signals") or 0),
            "entry_live_edge_eval": gate_chain_rows,
            "entry_edge_over_fee_eval": surviving_prefilter_rows,
            "tf_trend_entry_eval": int(event_counts.get("tf_trend_entry_eval") or 0),
            "run_end_entry_cutoff": int(event_counts.get("run_end_entry_cutoff") or 0),
        },
    }


def build_report(runs: list[dict], symbol: str, duration_min: int) -> dict:
    funnels = [_funnel_for_run(run) for run in runs]
    baseline = funnels[0] if funnels else {}
    deltas = []
    for funnel in funnels[1:]:
        deltas.append(
            {
                "scenario": funnel["scenario"],
                "candidate_entry_rows_delta": funnel["candidate_entry_rows"] - baseline.get("candidate_entry_rows", 0),
                "rows_reaching_gate_chain_delta": funnel["rows_reaching_gate_chain"] - baseline.get("rows_reaching_gate_chain", 0),
                "rows_surviving_prefilter_risk_delta": funnel["rows_surviving_prefilter_risk"] - baseline.get("rows_surviving_prefilter_risk", 0),
                "admitted_rows_delta": funnel["admitted_rows"] - baseline.get("admitted_rows", 0),
                "blocked_rows_delta": funnel["blocked_rows"] - baseline.get("blocked_rows", 0),
            }
        )
    funnel_decay = []
    for funnel in funnels:
        candidates = max(0, int(funnel.get("strategy_signal_rows") or funnel.get("candidate_entry_rows") or 0))
        gate_chain = max(0, int(funnel.get("rows_reaching_gate_chain") or 0))
        surviving = max(0, int(funnel.get("rows_surviving_prefilter_risk") or 0))
        if candidates > 0:
            funnel_decay.append(
                {
                    "scenario": funnel["scenario"],
                    "max_abs_drop": candidates - gate_chain,
                    "max_pct_drop": round((candidates - gate_chain) / candidates, 4),
                    "dominant_stage": "entry_live_edge_eval" if gate_chain < candidates else "none",
                    "comment": "upstream signal scarcity dominates" if candidates <= gate_chain else "blocker chain trims funnel",
                }
            )
        else:
            funnel_decay.append(
                {
                    "scenario": funnel["scenario"],
                    "max_abs_drop": 0,
                    "max_pct_drop": None,
                    "dominant_stage": "none",
                    "comment": "no candidate entry rows observed",
                }
            )
    final_classification = "INSUFFICIENT_EVIDENCE"
    if funnels and all((f.get("strategy_signal_rows") or 0) <= (f.get("rows_reaching_gate_chain") or 0) for f in funnels):
        final_classification = "UPSTREAM_SIGNAL_SCARCITY_DOMINATES"
    elif any((f.get("blocked_by_gate", {}).get("current_side", 0) > 0) for f in funnels):
        final_classification = "MIXED_FUNNEL_DECAY"
    return {
        "run_metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbol": symbol,
            "duration_min": duration_min,
            "scenarios": [r["name"] for r in runs],
            "scenario_count": len(runs),
        },
        "metric_definitions": FUNNEL_METRIC_DEFINITIONS,
        "funnel_by_scenario": funnels,
        "decay_analysis": funnel_decay,
        "cross_scenario_comparison": deltas,
        "final_classification": final_classification,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDTM")
    parser.add_argument("--duration-min", type=int, default=2)
    parser.add_argument("--scenarios", default="baseline,disable_current_side,disable_net_target_guard")
    args = parser.parse_args()
    selected = {x.strip() for x in str(args.scenarios or "").split(",") if x.strip()}
    runs = []
    for scenario in SCENARIOS:
        if scenario["name"] not in selected:
            continue
        runs.append(
            _run_scenario(
                args.symbol,
                args.duration_min,
                scenario,
            )
        )
    report = build_report(runs, args.symbol, args.duration_min)
    stamp = report["run_metadata"]["stamp"]
    json_path = DIAG_DIR / f"entry_funnel_decay_{stamp}.json"
    md_path = DIAG_DIR / f"entry_funnel_decay_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(
        "# Entry Funnel Decay\n\n" + json.dumps(report, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    print(f"ENTRY_FUNNEL_DECAY_JSON={json_path}")
    print(f"ENTRY_FUNNEL_DECAY_MD={md_path}")
    print(json.dumps(report.get("final_classification"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
