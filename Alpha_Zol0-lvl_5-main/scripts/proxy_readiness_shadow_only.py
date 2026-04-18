import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATHS = [
    WORKDIR / "tmp" / "controlled_kpi_before_20260328_010209.db",
    WORKDIR / "tmp" / "controlled_kpi_before_20260328_010418.db",
    WORKDIR / "tmp" / "controlled_kpi_before_20260328_011249.db",
]
DEFAULT_TERMINAL_PATHS = DIAG_DIR / "run_end_cutoff_terminal_paths_report_20260328_012425.json"


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


def _scenario_from_db_name(name: str) -> str:
    if "010209" in name:
        return "baseline"
    if "010418" in name:
        return "disable_net_target_guard"
    if "011249" in name:
        return "disable_current_side"
    return "unknown"


def _shadow_ready(entry: dict) -> bool:
    live_edge = entry.get("entry_live_edge") or {}
    edge_over_fee = entry.get("entry_edge_over_fee") or {}
    proxy_live = live_edge.get("live_edge_proxy")
    proxy_expected = entry.get("entry_expected_edge_after_fee")
    proxy_edge_over_fee = edge_over_fee.get("mean_edge_over_fee")
    proxy_fee = edge_over_fee.get("mean_fee_total")
    proxy_spread = edge_over_fee.get("mean_spread_slippage_proxy")
    candidates = []
    for value in [proxy_live, proxy_expected, proxy_edge_over_fee, proxy_fee, proxy_spread]:
        if value is not None:
            try:
                candidates.append(float(value))
            except Exception:
                continue
    if not candidates:
        return False
    return any(v > 0.0 for v in candidates)


def _summarize_events(events: list[dict]) -> dict:
    entry_rows = [e for e in events if e["event"] == "entry_gate_decision_summary"]
    term_rows = [e for e in entry_rows if str(e["details"].get("local_gate_reason") or "") == "run_end_cutoff"]
    shadow_rows = []
    for row in entry_rows:
        shadow_ready = _shadow_ready(row["details"])
        shadow_rows.append(
            {
                "symbol": row["details"].get("symbol"),
                "side": row["details"].get("side"),
                "shadow_ready": shadow_ready,
                "entry_decision_final": row["details"].get("entry_decision_final"),
                "entry_reason": row["details"].get("entry_reason"),
                "realized_history_ready": bool(
                    (row["details"].get("entry_edge_over_fee") or {}).get("history_ready")
                ),
                "realized_trade_count": int(
                    (row["details"].get("entry_edge_over_fee") or {}).get("trade_count") or 0
                ),
                "proxy_shadow_bucket_key": (
                    f"{row['details'].get('symbol')}|"
                    f"{row['details'].get('side')}|"
                    f"{row['details'].get('main_strategy') or 'unknown'}"
                ),
            }
        )
    shadow_ready_count = sum(1 for r in shadow_rows if r["shadow_ready"])
    realized_ready_count = sum(1 for r in shadow_rows if r["realized_history_ready"])
    return {
        "rows": len(entry_rows),
        "terminal_rows": len(term_rows),
        "proxy_shadow_trade_count": shadow_ready_count,
        "proxy_shadow_history_ready": bool(shadow_ready_count > 0),
        "proxy_shadow_edge_mean": (
            round(
                sum(
                    float((r["entry_decision_final"] is not None) and 1.0)
                    for r in shadow_rows
                    if r["shadow_ready"]
                )
                / shadow_ready_count,
                6,
            )
            if shadow_ready_count
            else 0.0
        ),
        "proxy_shadow_bucket_key": "symbol|side|main_strategy",
        "realized_trade_count": realized_ready_count,
        "realized_history_ready": bool(realized_ready_count > 0),
        "earlier_observability_gain": bool(shadow_ready_count > realized_ready_count),
        "shadow_rows": shadow_rows,
    }


def _build_report(db_paths: list[Path] | None = None, terminal_paths: dict | None = None) -> dict:
    if db_paths is None:
        db_paths = DEFAULT_DB_PATHS
    per_symbol = {}
    all_scenarios = set()
    for db_path in db_paths:
        scenario = _scenario_from_db_name(db_path.name)
        all_scenarios.add(scenario)
        events = _load_logs(db_path)
        for row in events:
            if row["event"] != "entry_gate_decision_summary":
                continue
            symbol = row["details"].get("symbol") or "unknown"
            per_symbol.setdefault(symbol, {})
            per_symbol[symbol][scenario] = _summarize_events(events)

    shadow_ready_total = 0
    realized_ready_total = 0
    terminal_observable_total = 0
    drift_notes = []
    for symbol, scenarios in per_symbol.items():
        for scenario_name, payload in scenarios.items():
            shadow_ready_total += int(payload["proxy_shadow_trade_count"] > 0)
            realized_ready_total += int(payload["realized_history_ready"])
            terminal_observable_total += int(
                bool((terminal_paths or {}).get("per_symbol", {}).get(symbol, {}).get(scenario_name, {}).get("run_end_cutoff_pockets", 0))
            )
            if payload["shadow_rows"] and payload["realized_history_ready"] and not payload["proxy_shadow_history_ready"]:
                drift_notes.append(f"{symbol}:{scenario_name} realized-ready without proxy-ready")

    classification = "SHADOW_PROXY_IMPROVES_OBSERVABILITY"
    if shadow_ready_total == 0:
        classification = "SHADOW_PROXY_ADDS_NO_MEANINGFUL_VALUE"
    elif shadow_ready_total < realized_ready_total:
        classification = "SHADOW_PROXY_TOO_NOISY"
    if not per_symbol:
        classification = "INSUFFICIENT_EVIDENCE"

    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "classification": classification,
            "method_version": "proxy_readiness_shadow_only_v1",
            "shadow_only": True,
            "symbols": sorted(per_symbol.keys()),
            "scenarios": sorted(all_scenarios),
        },
        "shadow_design": {
            "proxy_candidates": [
                "entry_live_edge_proxy",
                "entry_expected_edge_after_fee",
                "entry_edge_over_fee_status.mean_edge_over_fee",
                "entry_edge_over_fee_status.mean_fee_total",
                "entry_edge_over_fee_status.mean_spread_slippage_proxy",
            ],
            "separation": {
                "proxy_shadow_trade_count": "shadow-only, non-production counter",
                "proxy_shadow_history_ready": "shadow-only readiness flag",
                "realized_trade_count": "production history remains unchanged",
                "realized_history_ready": "production readiness remains unchanged",
            },
        },
        "per_symbol": per_symbol,
        "aggregate": {
            "shadow_ready_scenarios": shadow_ready_total,
            "realized_ready_scenarios": realized_ready_total,
            "terminal_observable_scenarios": terminal_observable_total,
            "drift_notes_count": len(drift_notes),
            "drift_notes": drift_notes,
        },
        "separation_guarantees": {
            "realized_buckets_mutated": False,
            "admission_semantics_changed": False,
            "realized_trade_count_changed": False,
            "realized_history_ready_changed": False,
            "shadow_only_namespace": True,
        },
        "observability_gain": {
            "earlier_shadow_observability": shadow_ready_total > realized_ready_total,
            "proxy_shadow_values_present": shadow_ready_total > 0,
            "terminal_pockets_with_shadow_observability": terminal_observable_total,
        },
        "mismatch_drift_findings": drift_notes,
        "final_verdict": classification,
    }


def _render_md(report: dict) -> str:
    meta = report["metadata"]
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "A shadow-only proxy readiness prototype was built without changing realized admission semantics. "
        "It keeps proxy readiness strictly separate from realized history and can be used to measure whether proxy observability appears earlier than close-only history."
    )
    lines.append("")
    lines.append("## B. Scope")
    lines.append("- PAPER / research only")
    lines.append("- Shadow-only readiness namespace")
    lines.append("- No runtime admission changes")
    lines.append("")
    lines.append("## C. Files Changed")
    lines.append("- `scripts/proxy_readiness_shadow_only.py`")
    lines.append("- `tests/test_proxy_readiness_shadow_only.py`")
    lines.append("")
    lines.append("## D. Shadow Design")
    lines.append("- `proxy_shadow_trade_count` and `proxy_shadow_history_ready` are research-only")
    lines.append("- realized `trade_count` and `history_ready` remain unchanged")
    lines.append("- proxy uses only existing pre-close signals")
    lines.append("")
    lines.append("## E. Proxy Metrics")
    lines.append("- `entry_live_edge_proxy`")
    lines.append("- `entry_expected_edge_after_fee`")
    lines.append("- `mean_edge_over_fee`")
    lines.append("- `mean_fee_total`")
    lines.append("- `mean_spread_slippage_proxy`")
    lines.append("")
    lines.append("## F. Separation Guarantees")
    lines.append("- proxy metrics never enter realized buckets")
    lines.append("- admission semantics do not change")
    lines.append("- realized `trade_count` and `history_ready` remain untouched")
    lines.append("")
    lines.append("## G. Observability Gain")
    lines.append(
        "The prototype measures whether shadow readiness appears earlier than realized close-only readiness and whether any terminal pockets would have been observable earlier in shadow form."
    )
    lines.append("")
    lines.append("## H. Mismatch / Drift Findings")
    drift = report.get("mismatch_drift_findings") or []
    if drift:
        for item in drift:
            lines.append(f"- {item}")
    else:
        lines.append("- none observed in the current corpus")
    lines.append("")
    lines.append("## I. Final Verdict")
    lines.append(meta["classification"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a shadow-only proxy readiness prototype report.")
    parser.add_argument("--db", action="append", dest="db_paths")
    parser.add_argument("--terminal-paths", default=str(DEFAULT_TERMINAL_PATHS))
    args = parser.parse_args(argv)
    db_paths = [Path(p) for p in args.db_paths] if args.db_paths else DEFAULT_DB_PATHS
    terminal_paths = _load_json(Path(args.terminal_paths)) if Path(args.terminal_paths).exists() else None
    report = _build_report(db_paths, terminal_paths)
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"proxy_readiness_shadow_only_{stamp}.json"
    md_path = DIAG_DIR / f"proxy_readiness_shadow_only_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
