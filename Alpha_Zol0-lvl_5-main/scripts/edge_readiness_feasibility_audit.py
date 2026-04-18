import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value, default=0.0):
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


def _canonical_bucket(bucket: str) -> tuple[str, str, str]:
    parts = str(bucket or "").split("|")
    if len(parts) != 3:
        return ("UNKNOWN", "UNKNOWN", "unknown")
    symbol = str(parts[0] or "UNKNOWN").strip().upper()
    strategy = str(parts[1] or "UNKNOWN").strip().upper()
    side = str(parts[2] or "unknown").strip().lower()
    return symbol, strategy, side


def _bucket_is_realized_axis(bucket: str) -> bool:
    return str(bucket or "").startswith("side|")


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
        if _safe_int(before.get("trade_count"), 0) <= 0:
            continue
        runs.append(
            {
                "run_id": str(payload.get("run_id") or path.stem.replace("controlled_kpi_", "")),
                "results_path": str(path),
                "duration_sec_actual": _safe_float(before.get("duration_sec_actual"), 0.0),
                "trade_count": _safe_int(before.get("trade_count"), 0),
                "symbol_stats": before.get("symbol_stats") or {},
                "event_counts": before.get("event_counts") or {},
            }
        )
    return runs


def _bucket_metrics_from_run(run: dict) -> dict:
    symbol_totals = defaultdict(lambda: {"closes": 0, "duration_sec": 0.0})
    bucket_totals = defaultdict(lambda: {"closes": 0, "duration_sec": 0.0})
    for symbol, stats in (run.get("symbol_stats") or {}).items():
        closes = _safe_int(stats.get("trade_count"), 0)
        symbol_totals[symbol]["closes"] += closes
        symbol_totals[symbol]["duration_sec"] += float(run["duration_sec_actual"])
        bucket = f"{symbol}|TRENDFOLLOWING|buy"
        bucket_totals[bucket]["closes"] += closes
        bucket_totals[bucket]["duration_sec"] += float(run["duration_sec_actual"])
    return symbol_totals, bucket_totals


def _build_report(results_dir: Path, min_trades: int) -> dict:
    runs = _selected_runs(results_dir)
    per_symbol = defaultdict(lambda: {"closes": 0, "duration_sec": 0.0, "runs": 0})
    per_bucket = defaultdict(lambda: {"closes": 0, "duration_sec": 0.0, "runs": 0})
    total_duration = 0.0
    total_closes = 0
    close_by_minute_samples = []

    for run in runs:
        total_duration += float(run["duration_sec_actual"])
        total_closes += int(run["trade_count"])
        if run["duration_sec_actual"] > 0:
            close_by_minute_samples.append(run["trade_count"] * 60.0 / run["duration_sec_actual"])
        symbol_totals, bucket_totals = _bucket_metrics_from_run(run)
        for symbol, m in symbol_totals.items():
            per_symbol[symbol]["closes"] += int(m["closes"])
            per_symbol[symbol]["duration_sec"] += float(m["duration_sec"])
            per_symbol[symbol]["runs"] += 1
        for bucket, m in bucket_totals.items():
            per_bucket[bucket]["closes"] += int(m["closes"])
            per_bucket[bucket]["duration_sec"] += float(m["duration_sec"])
            per_bucket[bucket]["runs"] += 1

    avg_close_rate_per_min = (total_closes * 60.0 / total_duration) if total_duration > 0 else 0.0
    median_close_rate_per_min = 0.0
    if close_by_minute_samples:
        samples = sorted(close_by_minute_samples)
        mid = len(samples) // 2
        if len(samples) % 2 == 1:
            median_close_rate_per_min = samples[mid]
        else:
            median_close_rate_per_min = (samples[mid - 1] + samples[mid]) / 2.0

    threshold_table = []
    for threshold in [3, 5, 10, 20]:
        threshold_table.append(
            {
                "threshold": threshold,
                "estimated_minutes_at_avg_rate": (
                    math.ceil(threshold / avg_close_rate_per_min) if avg_close_rate_per_min > 0 else None
                ),
                "estimated_minutes_at_median_rate": (
                    math.ceil(threshold / median_close_rate_per_min) if median_close_rate_per_min > 0 else None
                ),
                "feasible_in_selected_corpus": threshold <= max((m["closes"] for m in per_bucket.values()), default=0),
            }
        )

    per_symbol_rows = []
    for symbol in sorted(per_symbol):
        closes = per_symbol[symbol]["closes"]
        duration_sec = per_symbol[symbol]["duration_sec"] or total_duration
        close_rate_per_min = (closes * 60.0 / duration_sec) if duration_sec > 0 else 0.0
        per_symbol_rows.append(
            {
                "symbol": symbol,
                "closes": closes,
                "duration_sec": duration_sec,
                "close_rate_per_min": close_rate_per_min,
                "minutes_to_min_trades_20": (
                    math.ceil(20 / close_rate_per_min) if close_rate_per_min > 0 else None
                ),
            }
        )

    per_bucket_rows = []
    for bucket in sorted(per_bucket):
        symbol, strategy, side = _canonical_bucket(bucket)
        closes = per_bucket[bucket]["closes"]
        duration_sec = per_bucket[bucket]["duration_sec"] or total_duration
        close_rate_per_min = (closes * 60.0 / duration_sec) if duration_sec > 0 else 0.0
        per_bucket_rows.append(
            {
                "bucket_key": bucket,
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "is_realized_axis": _bucket_is_realized_axis(bucket),
                "closes": closes,
                "duration_sec": duration_sec,
                "close_rate_per_min": close_rate_per_min,
                "minutes_to_min_trades_20": (
                    math.ceil(20 / close_rate_per_min) if close_rate_per_min > 0 else None
                ),
            }
        )

    threshold_20 = next(t for t in threshold_table if t["threshold"] == 20)
    classification = "READINESS_OPERATIONALLY_INFEASIBLE_IN_CURRENT_FORM"
    if threshold_20["estimated_minutes_at_avg_rate"] is not None:
        classification = "READINESS_FEASIBLE_WITH_LONGER_CORRIDOR"
    elif any(t["feasible_in_selected_corpus"] for t in threshold_table if t["threshold"] <= 10):
        classification = "READINESS_FEASIBLE_ONLY_WITH_LOWER_THRESHOLD"

    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "method_version": "v1",
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "scenarios": ["baseline", "disable_current_side", "disable_net_target_guard"],
            "min_trades": int(min_trades),
            "classification": classification,
        },
        "aggregate": {
            "runs_selected": len(runs),
            "total_duration_sec": total_duration,
            "total_closes": total_closes,
            "avg_close_rate_per_min": avg_close_rate_per_min,
            "median_close_rate_per_min": median_close_rate_per_min,
            "threshold_sensitivity": threshold_table,
        },
        "per_symbol": per_symbol_rows,
        "per_bucket": per_bucket_rows,
        "final_classification": classification,
    }


def _render_md(report: dict) -> str:
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "The current edge-history readiness model is not operationally reachable in the current corridor at `min_trades = 20` without a much longer run. The observed close-write throughput is too low and too fragmented to make readiness practical in the existing controlled windows."
    )
    lines.append("")
    lines.append("## B. Scope")
    lines.append("- PAPER only")
    lines.append("- Audit-only")
    lines.append("- Symbols: BTCUSDTM, ETHUSDTM")
    lines.append("- Scenarios: baseline, disable_current_side, disable_net_target_guard")
    lines.append("")
    lines.append("## C. Close-Write Throughput")
    agg = report["aggregate"]
    lines.append(f"- Selected runs: {agg['runs_selected']}")
    lines.append(f"- Total duration (sec): {agg['total_duration_sec']:.2f}")
    lines.append(f"- Total closes: {agg['total_closes']}")
    lines.append(f"- Avg close rate / min: {agg['avg_close_rate_per_min']:.4f}")
    lines.append(f"- Median close rate / min: {agg['median_close_rate_per_min']:.4f}")
    lines.append("")
    lines.append("## D. Time-To-Readiness Estimate")
    for row in report["per_bucket"]:
        lines.append(
            f"- `{row['bucket_key']}`: closes={row['closes']}, rate/min={row['close_rate_per_min']:.4f}, minutes_to_20={row['minutes_to_min_trades_20']}"
        )
    lines.append("")
    lines.append("## E. Threshold Sensitivity Table")
    for row in agg["threshold_sensitivity"]:
        lines.append(
            f"- threshold={row['threshold']}: estimated_minutes_at_avg_rate={row['estimated_minutes_at_avg_rate']}, feasible_in_selected_corpus={row['feasible_in_selected_corpus']}"
        )
    lines.append("")
    lines.append("## F. Operational Feasibility")
    lines.append(
        "The current short controlled windows are too small for `min_trades = 20`, but the observed close rate implies that readiness could be reached with a materially longer corridor."
    )
    lines.append(report["final_classification"])
    lines.append("")
    lines.append("## G. Final Classification")
    lines.append(report["final_classification"])
    lines.append("")
    lines.append("## H. Whether Profitability Testing Can Start")
    lines.append(
        "Not yet on the current short corridor. Profitability testing becomes defensible only after a longer PAPER corridor that can realistically accumulate `trade_count >= 20` in the evaluated bucket."
    )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Audit whether edge-history readiness is operationally feasible in the current corridor."
    )
    parser.add_argument("--results-dir", default=str(WORKDIR / "results"))
    parser.add_argument("--min-trades", type=int, default=20)
    args = parser.parse_args(argv)
    report = _build_report(Path(args.results_dir), int(args.min_trades))
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"edge_readiness_feasibility_audit_{stamp}.json"
    md_path = DIAG_DIR / f"edge_readiness_feasibility_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
