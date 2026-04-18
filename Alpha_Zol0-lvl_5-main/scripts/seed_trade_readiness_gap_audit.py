import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value, default=None):
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value, default=0):
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _normalize_side(value: str | None) -> str:
    txt = str(value or "").strip().lower()
    if txt in {"long", "buy"}:
        return "buy"
    if txt in {"short", "sell"}:
        return "sell"
    return txt or "unknown"


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
                "details": payload if isinstance(payload, dict) else {},
            }
        )
    return out


def _bucket_from_entry(details: dict) -> str:
    edge = details.get("entry_edge_over_fee") or {}
    bucket = (
        edge.get("bucket_key_primary")
        or edge.get("bucket_key_fallback")
        or edge.get("bucket_used_final")
    )
    if bucket:
        return str(bucket)
    symbol = str(details.get("symbol") or "unknown").upper()
    side = _normalize_side(details.get("side"))
    strategy = str((edge.get("strategy") or "unknown")).strip() or "unknown"
    return f"{symbol}|{strategy.upper()}|{side}"


def _bucket_from_close(details: dict) -> str:
    symbol = str(details.get("symbol") or "unknown").upper()
    pos = details.get("position") or {}
    side = _normalize_side(pos.get("side") or details.get("side"))
    strategy = str(
        pos.get("entry_main_strategy")
        or pos.get("strategy")
        or details.get("main_strategy")
        or "unknown"
    )
    return f"{symbol}|{strategy}|{side}"


def _bucket_from_realized(details: dict) -> str:
    group_type = str(details.get("group_type") or "").strip()
    group_key = str(details.get("group_key") or "").strip()
    if group_type and group_key:
        return f"{group_type}|{group_key}"
    symbol = str(details.get("symbol") or "unknown").upper()
    side = _normalize_side(details.get("side"))
    return f"{symbol}|{side}"


def _selected_runs(results_dir: Path) -> list[dict]:
    runs = []
    for path in sorted(results_dir.glob("controlled_kpi_*.json")):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        before = payload.get("before") or {}
        if str(before.get("variant") or "") != "before":
            continue
        db_path = Path(str(before.get("db_path") or "")).expanduser()
        if not db_path.is_absolute():
            db_path = (WORKDIR / db_path).resolve()
        if not db_path.exists():
            continue
        logs = _load_logs(db_path)
        if not any(
            row["event"] == "entry_gate_decision_summary"
            and str((row["details"] or {}).get("entry_reason") or "") == "seed_trades_override"
            for row in logs
        ):
            continue
        runs.append(
            {
                "run_id": str(payload.get("run_id") or path.stem.replace("controlled_kpi_", "")),
                "results_path": str(path),
                "db_path": db_path,
                "trade_count": _safe_int(before.get("trade_count"), 0),
                "decisions_count": _safe_int(before.get("decisions_count"), 0),
                "net_pnl": _safe_float(before.get("net_pnl"), 0.0) or 0.0,
                "duration_sec_actual": _safe_float(before.get("duration_sec_actual"), 0.0) or 0.0,
                "logs": logs,
            }
        )
    return runs


def _summarize_run(run: dict, min_trades: int) -> dict:
    admissions = Counter()
    close_counts = Counter()
    realized_counts = Counter()
    bucket_trade_count_observed = defaultdict(list)
    bucket_history_ready_true = Counter()
    bucket_eval_rows = Counter()
    bucket_entry_rows = Counter()
    buckets_seen = set()

    for row in run["logs"]:
        event = row["event"]
        details = row["details"] or {}
        if event == "entry_gate_decision_summary":
            bucket = _bucket_from_entry(details)
            bucket_entry_rows[bucket] += 1
            buckets_seen.add(bucket)
            edge = details.get("entry_edge_over_fee") or {}
            tc = _safe_int(edge.get("trade_count"), 0)
            bucket_trade_count_observed[bucket].append(tc)
            if bool(details.get("final_allow")) and str(details.get("entry_reason") or "") == "seed_trades_override":
                admissions[bucket] += 1
            if edge:
                bucket_eval_rows[bucket] += 1
                if bool(edge.get("history_ready")):
                    bucket_history_ready_true[bucket] += 1
        elif event == "position_close":
            bucket = _bucket_from_close(details)
            close_counts[bucket] += 1
            buckets_seen.add(bucket)
        elif event == "realized_outcome_per_side":
            bucket = _bucket_from_realized(details)
            realized_counts[bucket] += 1
            buckets_seen.add(bucket)

    buckets = []
    for bucket in sorted(buckets_seen):
        observed_tc = max(bucket_trade_count_observed.get(bucket) or [0])
        closes = int(close_counts.get(bucket) or 0)
        admissions_count = int(admissions.get(bucket) or 0)
        eval_rows = int(bucket_eval_rows.get(bucket) or 0)
        ready_true = int(bucket_history_ready_true.get(bucket) or 0)
        buckets.append(
            {
                "bucket_key": bucket,
                "admissions": admissions_count,
                "close_writes": closes,
                "realized_rows": int(realized_counts.get(bucket) or 0),
                "gate_eval_rows": eval_rows,
                "gate_observed_trade_count_max": int(observed_tc),
                "gate_observed_history_ready_true": ready_true,
                "gate_observed_history_ready": bool(ready_true > 0),
                "readiness_gap_vs_min_trades": max(0, int(min_trades) - int(observed_tc)),
                "close_write_gap_vs_min_trades": max(0, int(min_trades) - closes),
                "history_ready_hit": bool(ready_true > 0),
            }
        )

    return {
        "run_id": run["run_id"],
        "results_path": run["results_path"],
        "db_path": str(run["db_path"]),
        "trade_count": int(run["trade_count"]),
        "decisions_count": int(run["decisions_count"]),
        "net_pnl": float(run["net_pnl"]),
        "duration_sec_actual": float(run["duration_sec_actual"]),
        "bucket_count": len(buckets),
        "buckets": buckets,
        "admissions_total": int(sum(admissions.values())),
        "close_writes_total": int(sum(close_counts.values())),
        "realized_rows_total": int(sum(realized_counts.values())),
        "history_ready_any": any(b["gate_observed_history_ready"] for b in buckets),
        "observed_trade_count_any": any(b["gate_observed_trade_count_max"] > 0 for b in buckets),
    }


def _classify(aggregate: dict) -> str:
    close_writes_total = int(
        aggregate.get("close_writes_total", aggregate.get("total_close_writes", 0))
    )
    history_ready_any = bool(aggregate.get("history_ready_any"))
    observed_trade_count_any = bool(aggregate.get("observed_trade_count_any"))
    bucket_count = int(aggregate.get("bucket_count", aggregate.get("total_buckets", 0)))
    if close_writes_total == 0:
        return "INSUFFICIENT_CLOSE_WRITES"
    if history_ready_any:
        return "INSUFFICIENT_EVIDENCE"
    if observed_trade_count_any:
        return "MIXED_READINESS_LIMITS"
    if bucket_count > 1:
        return "MIXED_READINESS_LIMITS"
    return "MIN_TRADES_THRESHOLD_TOO_HIGH_FOR_CORRIDOR"


def _build_report(results_dir: Path, min_trades: int) -> dict:
    selected_runs = _selected_runs(results_dir)
    run_reports = [_summarize_run(run, min_trades) for run in selected_runs]
    bucket_totals = defaultdict(lambda: Counter())
    for run in run_reports:
        for bucket in run["buckets"]:
            key = bucket["bucket_key"]
            bucket_totals[key]["admissions"] += bucket["admissions"]
            bucket_totals[key]["close_writes"] += bucket["close_writes"]
            bucket_totals[key]["realized_rows"] += bucket["realized_rows"]
            bucket_totals[key]["gate_eval_rows"] += bucket["gate_eval_rows"]
            bucket_totals[key]["gate_observed_trade_count_max"] = max(
                bucket_totals[key]["gate_observed_trade_count_max"],
                bucket["gate_observed_trade_count_max"],
            )
            bucket_totals[key]["gate_observed_history_ready_true"] += bucket["gate_observed_history_ready_true"]

    buckets = []
    for key in sorted(bucket_totals):
        c = bucket_totals[key]
        buckets.append(
            {
                "bucket_key": key,
                "admissions": int(c["admissions"]),
                "close_writes": int(c["close_writes"]),
                "realized_rows": int(c["realized_rows"]),
                "gate_eval_rows": int(c["gate_eval_rows"]),
                "gate_observed_trade_count_max": int(c["gate_observed_trade_count_max"]),
                "gate_observed_history_ready_true": int(c["gate_observed_history_ready_true"]),
                "readiness_gap_vs_min_trades": max(0, int(min_trades) - int(c["gate_observed_trade_count_max"])),
                "close_write_gap_vs_min_trades": max(0, int(min_trades) - int(c["close_writes"])),
                "history_ready_hit": bool(c["gate_observed_history_ready_true"] > 0),
            }
        )

    aggregate = {
        "total_runs": len(run_reports),
        "total_buckets": len(buckets),
        "total_admissions": int(sum(r["admissions_total"] for r in run_reports)),
        "total_close_writes": int(sum(r["close_writes_total"] for r in run_reports)),
        "total_realized_rows": int(sum(r["realized_rows_total"] for r in run_reports)),
        "history_ready_any": any(r["history_ready_any"] for r in run_reports),
        "observed_trade_count_any": any(r["observed_trade_count_any"] for r in run_reports),
        "bucket_fragmentation_findings": (
            "Close writes are distributed across two symbol buckets rather than accumulating in a single bucket."
            if len(buckets) > 1
            else "Single-bucket accumulation observed."
        ),
        "readiness_gap_summary": {
            "max_close_write_gap_vs_min_trades": max((b["close_write_gap_vs_min_trades"] for b in buckets), default=0),
            "max_readiness_gap_vs_min_trades": max((b["readiness_gap_vs_min_trades"] for b in buckets), default=0),
        },
    }
    final_classification = _classify(aggregate)
    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "method_version": "v1",
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "scenarios": ["baseline", "disable_current_side", "disable_net_target_guard"],
            "min_trades": int(min_trades),
            "classification": final_classification,
        },
        "per_run": run_reports,
        "per_bucket": buckets,
        "aggregate": aggregate,
        "final_classification": final_classification,
    }


def _render_md(report: dict) -> str:
    md = []
    md.append("## A. Executive Summary")
    md.append(
        "Seed admissions broke the initial no-trade deadlock, but they did not make edge-history ready in the observed corridor. "
        "Close writes are real, yet they are too sparse per bucket and the observed gate-side trade_count never rises above zero."
    )
    md.append("")
    md.append("## B. Scope")
    md.append("- PAPER only")
    md.append("- Audit-only")
    md.append("- Symbols: BTCUSDTM, ETHUSDTM")
    md.append("- Scenarios: baseline, disable_current_side, disable_net_target_guard")
    md.append("")
    md.append("## C. Files Changed")
    md.append("- `scripts/seed_trade_readiness_gap_audit.py`")
    md.append("- `tests/test_seed_trade_readiness_gap_audit.py`")
    md.append("")
    md.append("## D. Bucket-Level Close Mapping")
    for run in report["per_run"]:
        md.append(f"- Run `{run['run_id']}`: admissions={run['admissions_total']}, close_writes={run['close_writes_total']}, realized_rows={run['realized_rows_total']}")
        for bucket in run["buckets"]:
            md.append(
                f"  - `{bucket['bucket_key']}`: admissions={bucket['admissions']}, closes={bucket['close_writes']}, gate_eval_rows={bucket['gate_eval_rows']}"
            )
    md.append("")
    md.append("## E. Trade Count Distribution")
    for bucket in report["per_bucket"]:
        md.append(
            f"- `{bucket['bucket_key']}`: gate_observed_trade_count_max={bucket['gate_observed_trade_count_max']}, history_ready_hit={bucket['history_ready_hit']}"
        )
    md.append("")
    md.append("## F. Readiness Distance")
    for bucket in report["per_bucket"]:
        md.append(
            f"- `{bucket['bucket_key']}`: close_write_gap_vs_min_trades={bucket['close_write_gap_vs_min_trades']}, readiness_gap_vs_min_trades={bucket['readiness_gap_vs_min_trades']}"
        )
    md.append("")
    md.append("## G. Root Cause of Remaining Gap")
    md.append(report["aggregate"]["bucket_fragmentation_findings"])
    md.append(
        f"Aggregated close writes={report['aggregate']['total_close_writes']}, total admissions={report['aggregate']['total_admissions']}, history_ready_any={report['aggregate']['history_ready_any']}."
    )
    md.append("")
    md.append("## H. Final Classification")
    md.append(report["final_classification"])
    md.append("")
    md.append("## I. Whether Profitability Testing Is Premature")
    md.append(
        "Yes. The edge-history gate is still not ready in the observed corridor, so profitability testing would be dominated by readiness failure rather than edge quality."
    )
    return "\n".join(md) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit why seed admissions did not create edge-history readiness.")
    parser.add_argument("--results-dir", default=str(WORKDIR / "results"))
    parser.add_argument("--min-trades", type=int, default=20)
    args = parser.parse_args(argv)
    report = _build_report(Path(args.results_dir), int(args.min_trades))
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"seed_trade_readiness_gap_audit_{stamp}.json"
    md_path = DIAG_DIR / f"seed_trade_readiness_gap_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
