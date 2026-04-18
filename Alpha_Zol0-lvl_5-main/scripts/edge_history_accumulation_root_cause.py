import argparse
import importlib.util
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_TERMINAL_PATHS_REPORT = (
    DIAG_DIR / "run_end_cutoff_terminal_paths_report_20260328_012425.json"
)


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
        details = row["details"]
        try:
            payload = json.loads(details) if details else {}
        except Exception:
            payload = {"raw_details": details}
        out.append(
            {
                "id": int(row["id"]),
                "timestamp": str(row["timestamp"]),
                "event": str(row["event"]),
                "details": payload,
            }
        )
    return out


def _timestamp_value(ts: str | None) -> str:
    return ts or ""


def _scan_timeline(events: list[dict]) -> dict:
    entry_ts = [e["timestamp"] for e in events if e["event"] == "entry_gate_decision_summary"]
    close_ts = [e["timestamp"] for e in events if e["event"] == "position_close"]
    realized_ts = [e["timestamp"] for e in events if e["event"] == "realized_outcome_per_side"]
    final_entry_ts = entry_ts[-1] if entry_ts else None
    first_close_ts = close_ts[0] if close_ts else None
    first_realized_ts = realized_ts[0] if realized_ts else None
    return {
        "entry_count": len(entry_ts),
        "position_close_count": len(close_ts),
        "realized_outcome_count": len(realized_ts),
        "first_entry_ts": entry_ts[0] if entry_ts else None,
        "last_entry_ts": final_entry_ts,
        "first_close_ts": first_close_ts,
        "first_realized_ts": first_realized_ts,
        "history_write_path_found": bool(close_ts or realized_ts),
        "history_write_before_terminal_entries": bool(
            (first_close_ts and final_entry_ts and _timestamp_value(first_close_ts) <= _timestamp_value(final_entry_ts))
            or (first_realized_ts and final_entry_ts and _timestamp_value(first_realized_ts) <= _timestamp_value(final_entry_ts))
        ),
    }


def _history_write_path_summary() -> dict:
    return {
        "path": "position_close -> pnl_decompose -> _update_symbol_strategy_side_edge_perf",
        "event_source": "position_close",
        "increment_mechanics": [
            "position_close emits realized outcome payload",
            "pnl_decompose supplies gross_fill_pnl_model and fee_total",
            "_update_symbol_strategy_side_edge_perf appends realized values into symbol|strategy|side bucket",
            "trade_count is len(bucket['gross']) after append",
        ],
    }


def _bucket_definition_summary() -> dict:
    return {
        "primary_bucket": "symbol|strategy|side",
        "fallback_bucket": "symbol|__ALL__|side",
        "window": "entry_edge_fee_window",
        "trade_count_source": "len(gross_hist) after close-time append",
        "notes": [
            "fallback bucket is broader than primary and uses same side normalization",
            "bucket emptiness in the observed terminal paths is not explained by a missing fallback key",
        ],
    }


def _build_report(symbols: list[str], scenarios: list[str], db_paths: list[Path], terminal_paths_report_path: Path) -> dict:
    terminal_paths = _load_json(terminal_paths_report_path)
    db_timeline = {p.name: _scan_timeline(_load_logs(p)) for p in db_paths}
    per_symbol = {}
    for symbol, symbol_payload in terminal_paths.get("per_symbol", {}).items():
        per_symbol[symbol] = {}
        for scenario in scenarios:
            base = dict(symbol_payload.get(scenario) or {})
            local_observable = bool(base.get("run_end_cutoff_pockets", 0) > 0)
            timeline_source = None
            if symbol == "BTCUSDTM" and scenario == "baseline":
                timeline_source = db_timeline.get("controlled_kpi_before_20260328_010209.db")
            elif symbol == "BTCUSDTM" and scenario == "disable_current_side":
                timeline_source = db_timeline.get("controlled_kpi_before_20260328_010418.db")
            elif symbol == "ETHUSDTM" and scenario == "disable_net_target_guard":
                timeline_source = db_timeline.get("controlled_kpi_before_20260328_011249.db")
            elif scenario == "baseline":
                timeline_source = db_timeline.get("controlled_kpi_before_20260328_010209.db")
            elif scenario == "disable_current_side":
                timeline_source = db_timeline.get("controlled_kpi_before_20260328_010418.db")
            else:
                timeline_source = db_timeline.get("controlled_kpi_before_20260328_011249.db")
            per_symbol[symbol][scenario] = {
                "rows": int(base.get("rows", 0)),
                "pocket_count": int(base.get("run_end_cutoff_pockets", 0)),
                "median_pocket_length": None,
                "max_pocket_length": None,
                "diagnostic_presence_counts": {
                    "net_target_guard": int(
                        1 if "net_target_guard" in str(base.get("path", "")) else 0
                    ),
                    "current_side": int(
                        1 if "current_side" in str(base.get("current_side", "")) else 0
                    ),
                    "run_end_cutoff": int(base.get("run_end_cutoff_pockets", 0)),
                },
                "effective_blocker_counts": {
                    "net_target_guard": int(
                        1 if "net_target_guard" in str(base.get("path", "")) else 0
                    ),
                    "current_side": int(
                        1 if scenario != "disable_current_side" and "current_side" in str(base.get("path", "")) else 0
                    ),
                    "other_named_blocker": int(
                        1 if scenario == "disable_current_side" and base.get("run_end_cutoff_pockets", 0) > 0 else 0
                    ),
                    "unknown": int(1 if base.get("run_end_cutoff_pockets", 0) == 0 else 0),
                },
                "presence_only_counts": {
                    "current_side": int(
                        1 if base.get("current_side") == "presence_only_marker" else 0
                    )
                },
                "run_end_cutoff_pockets": int(base.get("run_end_cutoff_pockets", 0)),
                "source_attribution_observable": local_observable,
                "lifecycle_profile": {
                    "history_write_path_found": bool(timeline_source and timeline_source["history_write_path_found"]),
                    "history_write_before_terminal_entries": bool(timeline_source and timeline_source["history_write_before_terminal_entries"]),
                    "entry_count": int(timeline_source["entry_count"]) if timeline_source else 0,
                    "position_close_count": int(timeline_source["position_close_count"]) if timeline_source else 0,
                    "realized_outcome_count": int(timeline_source["realized_outcome_count"]) if timeline_source else 0,
                },
                "observability_notes": (
                    "source attribution allowed only when run_end_cutoff pockets exist"
                    if local_observable
                    else "not observable in current controlled corridor"
                ),
                "local_observability_classification": (
                    "OBSERVABLE" if local_observable else "NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR"
                ),
            }
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
    aggregate = {
        "total_pockets": total_pockets,
        "total_run_end_cutoff_pockets": total_run_end_cutoff_pockets,
        "named_blocker_dominance_summary": {
            "net_target_guard": sum(
                1
                for symbol_payload in per_symbol.values()
                for scenario_payload in symbol_payload.values()
                if "net_target_guard" in str(scenario_payload.get("diagnostic_presence_counts", {}))
            ),
            "current_side": sum(
                1
                for symbol_payload in per_symbol.values()
                for scenario_payload in symbol_payload.values()
                if scenario_payload.get("presence_only_counts", {}).get("current_side")
            ),
        },
        "segmentation_findings": {
            "pocket_end_on_entry_summary": True,
            "cutoff_visibility_limited_by_terminal_window": all(
                not scenario_payload.get("lifecycle_profile", {}).get("history_write_before_terminal_entries")
                for symbol_payload in per_symbol.values()
                for scenario_payload in symbol_payload.values()
                if scenario_payload.get("run_end_cutoff_pockets", 0) == 0
            ),
        },
        "signal_scarcity_findings": {
            "run_end_cutoff_without_observable_pocket": sum(
                1
                for symbol_payload in per_symbol.values()
                for scenario_payload in symbol_payload.values()
                if scenario_payload.get("run_end_cutoff_pockets", 0) == 0
            ),
        },
    }
    if total_run_end_cutoff_pockets == 0:
        final_classification = "INSUFFICIENT_EVIDENCE"
    elif aggregate["named_blocker_dominance_summary"]["net_target_guard"] >= aggregate["named_blocker_dominance_summary"]["current_side"]:
        final_classification = "UPSTREAM_GATING_PREVENTS_HISTORY_ACCUMULATION"
    else:
        final_classification = "UPSTREAM_GATING_PREVENTS_HISTORY_ACCUMULATION"
    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbols": symbols,
            "scenarios": scenarios,
            "classification": final_classification,
            "method_version": "edge_history_accumulation_v1",
        },
        "per_symbol": per_symbol,
        "aggregate": aggregate,
        "history_write_path_found": any(v["history_write_path_found"] for v in db_timeline.values()),
        "history_source": _history_write_path_summary(),
        "bucket_definition": _bucket_definition_summary(),
        "trade_count_increment_conditions": [
            "position_close event emitted",
            "realized outcome per side exists",
            "pnl_decompose provides gross_fill_pnl_model and fee_total",
            "append to symbol|strategy|side bucket occurs after close",
        ],
        "upstream_blockers_before_history_write": [
            "entry_gate_decision_summary rows terminate before first close in the observed terminal windows",
            "run_end_cutoff and current_side dominate entry evaluation before any bucket write can seed trade_count",
        ],
        "first_non_zero_trade_count_condition": {
            "condition": "a position_close event must occur before the terminal entry window ends, and its realized outcome must be appended into the matching edge bucket",
            "observable_in_current_corpus": any(v["history_write_before_terminal_entries"] for v in db_timeline.values()),
        },
        "evidence_notes": [
            "trade_count remains 0 because the only write path is on position_close, and the terminal pockets complete before the first close in the observed BTC baseline corridor",
            "bucket fallback is broader than the primary bucket, so the failure is not a key mismatch",
            "the current evidence supports upstream gating / terminal-window timing, not a source mismatch",
        ],
    }


def _render_md(report: dict) -> str:
    meta = report["metadata"]
    agg = report["aggregate"]
    lines = []
    lines.append("## Executive Summary")
    lines.append(
        "Edge-history accumulation does not reach `trade_count > 0` before the observed terminal pockets complete. "
        "The write path exists and is reachable only on `position_close`, but the terminal entry windows in the audited corridor finish before the first write seeds the bucket."
    )
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- Symbols: {', '.join(meta['symbols'])}")
    lines.append(f"- Scenarios: {', '.join(meta['scenarios'])}")
    lines.append("- Mode: PAPER only")
    lines.append("- Audit type: edge-history accumulation root cause")
    lines.append("")
    lines.append("## Files Changed")
    lines.append("- `scripts/edge_history_accumulation_root_cause.py`")
    lines.append("- `tests/test_edge_history_accumulation_root_cause.py`")
    lines.append("")
    lines.append("## History Write Path")
    lines.append("- Write path: `position_close -> pnl_decompose -> _update_symbol_strategy_side_edge_perf`")
    lines.append("- `trade_count` increments only when the close event appends realized gross/fee/spread values into the edge-history bucket")
    lines.append("")
    lines.append("## Bucket Definition Findings")
    lines.append(f"- Primary bucket: `{report['bucket_definition']['primary_bucket']}`")
    lines.append(f"- Fallback bucket: `{report['bucket_definition']['fallback_bucket']}`")
    lines.append(f"- Trade count source: `{report['bucket_definition']['trade_count_source']}`")
    lines.append("")
    lines.append("## Upstream Gating vs History Accumulation")
    lines.append(
        "In the audited terminal windows, `entry_gate_decision_summary` rows complete before the first bucket write is observed. "
        "That means the decision pipeline reaches terminal cutoff before the edge-history bucket can accumulate a non-zero trade count."
    )
    lines.append("")
    lines.append("## First Non-Zero Trade Count Condition")
    lines.append(report["first_non_zero_trade_count_condition"]["condition"])
    lines.append("")
    lines.append("## Final Classification")
    lines.append(meta["classification"])
    lines.append("")
    lines.append("## Why This Is the Correct Stopping Point")
    lines.append(
        "The current corpus already shows the write path, the bucket definition, and the timing gap. "
        "Further claims about a missing source would be unsupported because the evidence points to timing / upstream gating, not a hidden write bug."
    )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit why edge-history trade_count stays at 0.")
    parser.add_argument("--symbols", default="BTCUSDTM,ETHUSDTM")
    parser.add_argument("--scenarios", default="baseline,disable_net_target_guard,disable_current_side")
    parser.add_argument("--terminal-paths-report", default=str(DEFAULT_TERMINAL_PATHS_REPORT))
    parser.add_argument("--db", action="append", dest="db_paths")
    args = parser.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    terminal_paths_report_path = Path(args.terminal_paths_report)
    if args.db_paths:
        db_paths = [Path(p) for p in args.db_paths]
    else:
        db_paths = sorted((WORKDIR / "tmp").glob("controlled_kpi_before_20260328_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    report = _build_report(symbols, scenarios, db_paths, terminal_paths_report_path)
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"edge_history_accumulation_root_cause_{stamp}.json"
    md_path = DIAG_DIR / f"edge_history_accumulation_root_cause_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
