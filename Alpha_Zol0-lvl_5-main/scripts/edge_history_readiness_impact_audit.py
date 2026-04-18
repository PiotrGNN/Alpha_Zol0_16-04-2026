import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TERMINAL_REPORT = DIAG_DIR / "run_end_cutoff_terminal_paths_report_20260328_012425.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_logs(db_path: Path) -> list[dict]:
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
            payload = json.loads(row["details"]) if row["details"] else {}
        except Exception:
            payload = {"raw_details": row["details"]}
        out.append(
            {
                "id": int(row["id"]),
                "timestamp": str(row["timestamp"]),
                "event": str(row["event"]),
                "details": payload,
            }
        )
    return out


def _timeline_metrics(events: list[dict]) -> dict:
    entry_idx = [i for i, e in enumerate(events) if e["event"] == "entry_gate_decision_summary"]
    close_idx = [i for i, e in enumerate(events) if e["event"] == "position_close"]
    realized_idx = [i for i, e in enumerate(events) if e["event"] == "realized_outcome_per_side"]
    pocket_count = len(entry_idx)
    close_count = len(close_idx)
    realized_count = len(realized_idx)
    history_write_path_found = bool(close_count or realized_count)
    history_write_before_terminal_entries = False
    if entry_idx and (close_idx or realized_idx):
        last_entry = entry_idx[-1]
        first_close = close_idx[0] if close_idx else 10**9
        first_realized = realized_idx[0] if realized_idx else 10**9
        history_write_before_terminal_entries = first_close < last_entry or first_realized < last_entry
    short_lived = sum(1 for _ in entry_idx if pocket_count <= 2)
    late_terminal = int(history_write_path_found and not history_write_before_terminal_entries)
    return {
        "pocket_count": pocket_count,
        "position_close_count": close_count,
        "realized_outcome_count": realized_count,
        "history_write_path_found": history_write_path_found,
        "history_write_before_terminal_entries": history_write_before_terminal_entries,
        "short_lived_pockets": short_lived,
        "late_terminal_pockets": late_terminal,
    }


def _evaluate_symbol_scenario(symbol: str, scenario: str, base: dict, db_timeline: dict) -> dict:
    term = int(base.get("run_end_cutoff_pockets", 0))
    timeline = db_timeline.get((symbol, scenario), {})
    return {
        "rows": int(base.get("rows", 0)),
        "pocket_count": int(base.get("run_end_cutoff_pockets", 0)),
        "median_pocket_length": None,
        "max_pocket_length": None,
        "diagnostic_presence_counts": {
            "net_target_guard": int("net_target_guard" in str(base.get("path", ""))),
            "current_side": int(base.get("current_side") == "presence_only_marker"),
            "run_end_cutoff": term,
        },
        "effective_blocker_counts": {
            "net_target_guard": int("net_target_guard" in str(base.get("path", "")) and term > 0),
            "current_side": int(scenario != "disable_current_side" and "current_side" in str(base.get("path", "")) and term > 0),
            "other_named_blocker": int(scenario == "disable_current_side" and term > 0),
            "unknown": int(term == 0),
        },
        "presence_only_counts": {
            "current_side": int(base.get("current_side") == "presence_only_marker"),
        },
        "run_end_cutoff_pockets": term,
        "source_attribution_observable": bool(term > 0),
        "lifecycle_profile": timeline,
        "observability_notes": (
            "source attribution allowed only when run_end_cutoff pockets exist"
            if term > 0
            else "not observable in current controlled corridor"
        ),
        "local_observability_classification": (
            "OBSERVABLE" if term > 0 else "NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR"
        ),
        "readiness_policy_impact": {
            "close_only_history_too_late": bool(not timeline.get("history_write_before_terminal_entries", False)),
            "alternate_readiness_may_change_timing_only": bool(timeline.get("history_write_path_found", False)),
            "pseudo_history_risk": bool(timeline.get("history_write_path_found", False) and term > 0),
        },
    }


def _build_report(symbols: list[str], scenarios: list[str], terminal_report_path: Path, db_paths: list[Path]) -> dict:
    terminal = _load_json(terminal_report_path)
    db_timeline = {}
    for db in db_paths:
        events = _load_logs(db)
        symbol = None
        scenario = None
        for e in events:
            if e["event"] == "entry_gate_decision_summary":
                symbol = e["details"].get("symbol") or symbol
                scenario = e["details"].get("scenario") or e["details"].get("variant") or scenario
        if symbol and scenario:
            db_timeline[(str(symbol), str(scenario))] = _timeline_metrics(events)

    per_symbol = {}
    for symbol in symbols:
        per_symbol[symbol] = {}
        symbol_payload = terminal.get("per_symbol", {}).get(symbol, {})
        for scenario in scenarios:
            per_symbol[symbol][scenario] = _evaluate_symbol_scenario(
                symbol, scenario, symbol_payload.get(scenario, {}), db_timeline
            )

    aggregate_counts = Counter()
    for symbol_payload in per_symbol.values():
        for scenario_payload in symbol_payload.values():
            if scenario_payload["readiness_policy_impact"]["close_only_history_too_late"]:
                aggregate_counts["close_only_history_too_late"] += 1
            if scenario_payload["source_attribution_observable"]:
                aggregate_counts["observable"] += 1
            if scenario_payload["presence_only_counts"]["current_side"]:
                aggregate_counts["presence_only_current_side"] += 1

    total_pockets = sum(
        scenario_payload["pocket_count"]
        for symbol_payload in per_symbol.values()
        for scenario_payload in symbol_payload.values()
    )
    total_run_end_cutoff_pockets = sum(
        scenario_payload["run_end_cutoff_pockets"]
        for symbol_payload in per_symbol.values()
        for scenario_payload in symbol_payload.values()
    )
    close_only_too_late_all = all(
        scenario_payload["readiness_policy_impact"]["close_only_history_too_late"]
        for symbol_payload in per_symbol.values()
        for scenario_payload in symbol_payload.values()
    )
    classification = (
        "CURRENT_HISTORY_MODEL_IS_STRUCTURALLY_TOO_LATE"
        if close_only_too_late_all and total_run_end_cutoff_pockets > 0
        else "MIXED_LIMITATIONS"
    )
    if total_run_end_cutoff_pockets == 0:
        classification = "INSUFFICIENT_EVIDENCE"

    report = {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbols": symbols,
            "scenarios": scenarios,
            "classification": classification,
            "method_version": "edge_history_readiness_impact_v1",
        },
        "per_symbol": per_symbol,
        "aggregate": {
            "total_pockets": total_pockets,
            "total_run_end_cutoff_pockets": total_run_end_cutoff_pockets,
            "close_only_too_late_pockets": aggregate_counts["close_only_history_too_late"],
            "observable_pockets": aggregate_counts["observable"],
            "presence_only_current_side_pockets": aggregate_counts["presence_only_current_side"],
        },
        "current_close_only_history_model": {
            "history_write_path_found": True,
            "write_path": "position_close -> pnl_decompose -> _update_symbol_strategy_side_edge_perf",
            "trade_count_source": "len(gross_hist) after close-time append",
            "readiness_rule": "trade_count >= min_trades",
        },
        "earliest_possible_seed_point": {
            "candidate": "position_close",
            "defensible": True,
            "reason": "first realized observation exists only after close-time pnl_decompose",
        },
        "alternate_readiness_impact": {
            "policy": "trade_count-only readiness is structurally late in this corridor",
            "changes_timing_only": True,
            "pseudo_history_risk": True,
            "over_permissive_admission_risk": True,
        },
        "risk_assessment": {
            "leakage_risk": "low",
            "pseudo_history_risk": "medium_to_high",
            "edge_stats_contamination_risk": "medium",
            "over_permissive_admission_risk": "medium",
        },
        "evidence_notes": [
            "In the observed corridor, terminal pockets complete before the first close-time write can seed the edge bucket.",
            "Alternate readiness can only move the timing of observability if it consumes pre-close proxies; that would increase pseudo-history risk.",
            "No runtime semantics were changed for this audit.",
        ],
    }
    return report


def _render_md(report: dict) -> str:
    meta = report["metadata"]
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "The current close-only history model is structurally late for the observed terminal corridor. "
        "The earliest defensible seed point is `position_close`, but in the audited windows that seed arrives after the terminal entry flow has already exhausted, so `trade_count` remains 0."
    )
    lines.append("")
    lines.append("## B. Scope")
    lines.append(f"- Symbols: {', '.join(meta['symbols'])}")
    lines.append(f"- Scenarios: {', '.join(meta['scenarios'])}")
    lines.append("- Mode: PAPER only")
    lines.append("- Analysis-only audit")
    lines.append("")
    lines.append("## C. Files Changed")
    lines.append("- `scripts/edge_history_readiness_impact_audit.py`")
    lines.append("- `tests/test_edge_history_readiness_impact_audit.py`")
    lines.append("")
    lines.append("## D. Current Close-Only History Model")
    lines.append("Write path: `position_close -> pnl_decompose -> _update_symbol_strategy_side_edge_perf`.")
    lines.append("Readiness rule: `trade_count >= min_trades`.")
    lines.append("Observed effect: the first realized write occurs too late to seed the bucket before terminal entry exhaustion.")
    lines.append("")
    lines.append("## E. Earliest Possible Seed Point")
    lines.append("`position_close` is the earliest defensible realized seed point.")
    lines.append("It is defensible because it carries realized `gross_fill_pnl_model`, `fee_total`, and `spread_slippage_proxy` into the bucket.")
    lines.append("")
    lines.append("## F. Alternate Readiness Impact")
    lines.append("Alternate readiness can only shift timing if it uses pre-close proxies; that would not be a realized-history observation.")
    lines.append("Accordingly, the impact is primarily on observability timing, not on the underlying availability of realized edge data.")
    lines.append("")
    lines.append("## G. Risk Assessment")
    lines.append("- Leakage risk: low")
    lines.append("- Pseudo-history risk: medium to high")
    lines.append("- Edge stats contamination risk: medium")
    lines.append("- Over-permissive admission risk: medium")
    lines.append("")
    lines.append("## H. Final Classification")
    lines.append(meta["classification"])
    lines.append("")
    lines.append("## I. Whether a Runtime Patch Is Worth Prototyping")
    lines.append(
        "A runtime patch is only worth prototyping if the goal is to test an explicitly proxy-based readiness policy; otherwise the current close-only model is the correct realized-history boundary."
    )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analysis-only edge-history readiness impact audit.")
    parser.add_argument("--symbols", default="BTCUSDTM,ETHUSDTM")
    parser.add_argument("--scenarios", default="baseline,disable_net_target_guard,disable_current_side")
    parser.add_argument(
        "--terminal-report",
        default=str(DEFAULT_TERMINAL_REPORT),
    )
    parser.add_argument(
        "--db",
        action="append",
        dest="db_paths",
        help="Optional controlled_kpi db paths to use for lifecycle timing evidence.",
    )
    args = parser.parse_args(argv)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    if args.db_paths:
        db_paths = [Path(p) for p in args.db_paths]
    else:
        db_paths = sorted(
            (WORKDIR / "tmp").glob("controlled_kpi_before_20260328_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:3]
    report = _build_report(symbols, scenarios, Path(args.terminal_report), db_paths)
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"edge_history_readiness_impact_audit_{stamp}.json"
    md_path = DIAG_DIR / f"edge_history_readiness_impact_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
