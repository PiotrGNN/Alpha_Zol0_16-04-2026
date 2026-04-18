import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
TMP_DIR = WORKDIR / "tmp"
RESULTS_DIR = WORKDIR / "results"
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
PAPER_REPORT_DIR = WORKDIR / "reports" / "paper_readiness"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


SCENARIOS = [
    {
        "name": "baseline",
        "diagnostic_mode": "0",
        "env": {},
        "label": "Scenario 0 — Baseline",
    },
    {
        "name": "disable_net_target_guard",
        "diagnostic_mode": "1",
        "env": {"DIAG_DISABLE_NET_TARGET_GUARD": "1"},
        "label": "Scenario 1 — Disable net_target_guard",
    },
    {
        "name": "disable_current_side",
        "diagnostic_mode": "1",
        "env": {"DIAG_ALLOW_REENTRY_WHILE_IN_POSITION": "1"},
        "label": "Scenario 2 — Disable current_side",
    },
    {
        "name": "disable_side_guard",
        "diagnostic_mode": "1",
        "env": {"DIAG_DISABLE_SIDE_GUARD": "1"},
        "label": "Scenario 3 — Disable side_guard",
    },
    {
        "name": "disable_side_expectancy",
        "diagnostic_mode": "1",
        "env": {"DIAG_DISABLE_SIDE_EXPECTANCY": "1"},
        "label": "Scenario 4 — Disable side_expectancy",
    },
    {
        "name": "full_bypass",
        "diagnostic_mode": "1",
        "env": {
            "DIAG_DISABLE_NET_TARGET_GUARD": "1",
            "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION": "1",
            "DIAG_DISABLE_SIDE_GUARD": "1",
            "DIAG_DISABLE_SIDE_EXPECTANCY": "1",
        },
        "label": "Scenario 5 — Full diagnostic bypass",
    },
]


def _parse_summary_marker(stdout_text: str, marker: str) -> Path | None:
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


def _run_controlled_kpi(
    *,
    name: str,
    symbol: str,
    duration_min: int,
    diagnostic_mode: str,
    env: dict,
    paper_auto_open: bool,
    use_mock: bool,
    quality_profile: bool,
    entry_min_net_usdt: str,
    side_guard_enable: str | None = None,
    side_guard_cooldown_sec: str | None = None,
    side_expectancy_min: str | None = None,
    side_expectancy_min_trades: str | None = None,
) -> dict:
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
        "--use-mock" if use_mock else "--no-use-mock",
        "--paper-auto-close-sec",
        "10",
        "--quality-profile" if quality_profile else "--no-alpha-bootstrap-auto-refresh",
        "--no-alpha-bootstrap-auto-refresh",
        "--alpha-bootstrap-source-db-url",
        "sqlite:///D:/Alpha_Zol0-lvl_5-main/zol0.db",
        "--alpha-bootstrap-source-db-glob",
        "D:/Alpha_Zol0-lvl_5-main/zol0.db",
    ]
    if paper_auto_open:
        cmd.append("--paper-auto-open")
    else:
        pass

    before_env = {
        "ENTRY_MIN_NET_USDT": str(entry_min_net_usdt),
        "LOSS_COOLDOWN_SEC": "0",
        "RESEARCH_HOLD_TRANSITION_DEBUG": "1",
        "RESEARCH_TF_GATE_DEBUG": "1",
        "RESEARCH_EXPECTED_EDGE_DEBUG": "1",
        "RESEARCH_NET_TARGET_GUARD_DEBUG": "1",
        "DIAGNOSTIC_MODE": str(diagnostic_mode),
        "LIVE": "0",
    }
    if side_guard_enable is not None:
        before_env["SIDE_GUARD_ENABLE"] = str(side_guard_enable)
    if side_guard_cooldown_sec is not None:
        before_env["SIDE_GUARD_COOLDOWN_SEC"] = str(side_guard_cooldown_sec)
    if side_expectancy_min is not None:
        before_env["ENTRY_SIDE_EXPECTANCY_MIN"] = str(side_expectancy_min)
    if side_expectancy_min_trades is not None:
        before_env["ENTRY_SIDE_EXPECTANCY_MIN_TRADES"] = str(
            side_expectancy_min_trades
        )
    before_env.update({k: str(v) for k, v in (env or {}).items()})
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
    report_json = _parse_summary_marker(proc.stdout, "REPORT_JSON=")
    if report_json is None or not report_json.exists():
        raise RuntimeError(f"controlled_kpi_run did not emit usable REPORT_JSON for {name}")
    report = json.loads(report_json.read_text(encoding="utf-8"))
    report_run_id = str(report.get("run_id") or report_json.stem.replace("controlled_kpi_", ""))
    summary_path = PAPER_REPORT_DIR / f"{report_run_id}_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_proc = subprocess.run(
        [
            sys.executable,
            str((WORKDIR / "scripts" / "report_entry_gate_decision_summary.py").resolve()),
            "--db-path",
            str(Path(report["before"]["db_path"])),
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
    if summary_proc.returncode != 0:
        raise RuntimeError(
            f"report_entry_gate_decision_summary failed for {name} rc={summary_proc.returncode}"
        )
    summary_path.write_text(summary_proc.stdout, encoding="utf-8")
    diag_json = _parse_summary_marker(proc.stdout, "DIAGNOSTIC_REPORT_JSON=")
    diag_summary = None
    if diag_json is not None and diag_json.exists():
        try:
            diag_summary = json.loads(diag_json.read_text(encoding="utf-8"))
        except Exception:
            diag_summary = None
    return {
        "name": name,
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "report_json": str(report_json),
        "report": report,
        "summary_json": str(summary_path),
        "diagnostic_json": str(diag_json) if diag_json is not None else None,
        "diagnostic_summary": diag_summary,
        "scenario_env": before_env,
    }


def _collect_gate_trace(diag_summary: dict | None) -> dict[str, dict]:
    out = {}
    if not isinstance(diag_summary, dict):
        return out
    for row in diag_summary.get("gate_trace_by_gate") or []:
        gate_name = str(row.get("gate_name") or "").strip()
        if gate_name:
            out[gate_name] = dict(row)
    return out


def _load_summary_rows(report: dict) -> dict:
    if not isinstance(report, dict):
        return {}
    summary_path = report.get("summary_json")
    if summary_path:
        path = Path(summary_path)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
    return {}


def _build_report(run_results: list[dict], output_stamp: str) -> dict:
    scenario_reports = []
    baseline_summary = None
    baseline_traces = {}
    for item in run_results:
        summary = _load_summary_rows({"summary_json": item.get("summary_json")})
        diag_summary = item.get("diagnostic_summary") or {}
        gate_trace = _collect_gate_trace(diag_summary)
        scenario = {
            "name": item["name"],
            "label": next((s["label"] for s in SCENARIOS if s["name"] == item["name"]), item["name"]),
            "env_diagnostic_flags": {
                k: item["scenario_env"].get(k)
                for k in (
                    "DIAGNOSTIC_MODE",
                    "DIAG_DISABLE_NET_TARGET_GUARD",
                    "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION",
                    "DIAG_DISABLE_SIDE_GUARD",
                    "DIAG_DISABLE_SIDE_EXPECTANCY",
                )
            },
            "rows": summary.get("rows"),
            "admitted": summary.get("admitted_vs_blocked", {}).get("admitted"),
            "blocked": summary.get("admitted_vs_blocked", {}).get("blocked"),
            "trades": item.get("report", {}).get("before", {}).get("trade_count"),
            "top_local_gate_reason": summary.get("top_local_gate_reason", []),
            "gate_trace_summary": diag_summary.get("gate_trace_summary", {}),
            "gate_trace_by_gate": diag_summary.get("gate_trace_by_gate", []),
            "diagnostic_json": item.get("diagnostic_json"),
        }
        scenario_reports.append(scenario)
        if item["name"] == "baseline":
            baseline_summary = summary
            baseline_traces = gate_trace

    gate_names = sorted(
        set(baseline_traces.keys())
        | {
            row.get("gate_name")
            for scen in scenario_reports
            for row in scen.get("gate_trace_by_gate", [])
            if row.get("gate_name")
        }
    )
    attribution_rows = []
    for gate_name in gate_names:
        baseline_block_count = int(baseline_traces.get(gate_name, {}).get("blocked_count") or 0)
        skip_count = int(baseline_traces.get(gate_name, {}).get("skipped_count") or 0)
        disabled_counts = {}
        downstream_counts = {}
        for scen in scenario_reports:
            if scen["name"] == "baseline":
                continue
            scen_gate = {
                row.get("gate_name"): row
                for row in scen.get("gate_trace_by_gate", [])
                if row.get("gate_name")
            }
            scen_key = scen["name"]
            disabled_counts[scen_key] = int(
                scen_gate.get(gate_name, {}).get("blocked_count")
                or 0
            )
            downstream_counts[scen_key] = scen.get("top_local_gate_reason", [])[:3]
        attribution_rows.append(
            {
                "gate": gate_name,
                "baseline_block_count": baseline_block_count,
                "trace_count": baseline_block_count + skip_count,
                "skip_count": skip_count,
                "block_count_when_disabled": disabled_counts,
                "first_downstream_blocker_after_disable": downstream_counts,
                "qualitative_note": (
                    "baseline trace only" if gate_name in baseline_traces else "not seen in baseline"
                ),
            }
        )

    baseline_top = (baseline_summary or {}).get("top_local_gate_reason", [])
    downstream_shift = []
    for scen in scenario_reports:
        if scen["name"] == "baseline":
            continue
        top = scen.get("top_local_gate_reason", [])
        downstream_shift.append(
            {
                "scenario": scen["name"],
                "top_local_gate_reason": top[:3],
                "admitted_delta_vs_baseline": (scen.get("admitted") or 0)
                - int((baseline_summary or {}).get("admitted_vs_blocked", {}).get("admitted") or 0),
                "blocked_delta_vs_baseline": (scen.get("blocked") or 0)
                - int((baseline_summary or {}).get("admitted_vs_blocked", {}).get("blocked") or 0),
                "trades_delta_vs_baseline": (scen.get("trades") or 0)
                - int((run_results[0].get("report") or {}).get("before", {}).get("trade_count") or 0),
            }
        )

    final_classification = "NO_MEANINGFUL_PROGRESS_AFTER_DISABLE"
    if any(
        any(g.get("gate_name") == "net_target_guard" for g in row.get("gate_trace_by_gate", []))
        for row in scenario_reports
    ):
        final_classification = "MULTI_STAGE_BLOCKER_CHAIN_CONFIRMED"

    return {
        "run_metadata": {
            "stamp": output_stamp,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "scenario_count": len(run_results),
            "scenarios": [s["name"] for s in scenario_reports],
        },
        "scenario_summary": scenario_reports,
        "gate_attribution_matrix": attribution_rows,
        "downstream_blocker_shift": downstream_shift,
        "baseline_top_blocker": baseline_top,
        "final_classification": final_classification,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDTM")
    parser.add_argument("--duration-min", type=int, default=2)
    parser.add_argument(
        "--scenarios",
        type=str,
        default="baseline,disable_net_target_guard,disable_current_side,disable_side_guard,disable_side_expectancy,full_bypass",
        help="Comma-separated scenario names to run",
    )
    parser.add_argument("--run", action="store_true", default=True)
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_results = []
    selected = {x.strip() for x in str(args.scenarios or "").split(",") if x.strip()}
    for scenario in SCENARIOS:
        if scenario["name"] not in selected:
            continue
        run_results.append(
            _run_controlled_kpi(
                name=scenario["name"],
                symbol=args.symbol,
                duration_min=args.duration_min,
                diagnostic_mode=scenario["diagnostic_mode"],
                env=scenario["env"],
                paper_auto_open=(scenario["name"] != "baseline"),
                use_mock=True,
                quality_profile=True,
                entry_min_net_usdt="0.12",
                side_guard_enable=("0" if scenario["name"] in {"disable_side_guard", "full_bypass"} else None),
                side_guard_cooldown_sec=("0" if scenario["name"] in {"disable_side_guard", "full_bypass"} else None),
                side_expectancy_min=("0" if scenario["name"] in {"disable_side_expectancy", "full_bypass"} else None),
                side_expectancy_min_trades=("1" if scenario["name"] in {"disable_side_expectancy", "full_bypass"} else None),
            )
        )

    report = _build_report(run_results, stamp)
    json_path = DIAG_DIR / f"diagnostic_gate_attribution_{stamp}.json"
    md_path = DIAG_DIR / f"diagnostic_gate_attribution_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    md_path.write_text(
        "# Diagnostic Gate Attribution\n\n"
        + json.dumps(report, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    print(f"DIAGNOSTIC_ATTRIBUTION_JSON={json_path}")
    print(f"DIAGNOSTIC_ATTRIBUTION_MD={md_path}")
    print(json.dumps(report.get("final_classification"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
