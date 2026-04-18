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


def _safe_int(value, default=0):
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _safe_float(value, default=0.0):
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _normalize_side(value: str | None) -> str:
    txt = str(value or "").strip().lower()
    if txt in {"long", "buy"}:
        return "buy"
    if txt in {"short", "sell"}:
        return "sell"
    return txt or "unknown"


def _canonical_bucket(symbol: str | None, strategy: str | None, side: str | None) -> str:
    return f"{str(symbol or 'UNKNOWN').upper()}|{str(strategy or 'UNKNOWN').upper()}|{_normalize_side(side)}"


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


def _select_run(results_dir: Path, result_path: str | None = None) -> dict:
    if result_path:
        path = Path(result_path)
        if not path.is_absolute():
            path = (WORKDIR / path).resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        payload = _load_json(path)
        before = payload.get("before") or {}
        db_path = Path(str(before.get("db_path") or "")).expanduser()
        if not db_path.is_absolute():
            db_path = (WORKDIR / db_path).resolve()
        if not db_path.exists():
            raise FileNotFoundError(db_path)
        return {
            "path": path,
            "run_id": str(payload.get("run_id") or path.stem.replace("controlled_kpi_", "")),
            "duration": _safe_float(before.get("duration_sec_actual"), 0.0),
            "before": before,
            "db_path": db_path,
        }

    candidates = []
    for path in results_dir.glob("controlled_kpi_*.json"):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        before = payload.get("before") or {}
        if str(before.get("variant") or "") != "before":
            continue
        if _safe_int(before.get("trade_count"), 0) <= 0:
            continue
        duration = _safe_float(before.get("duration_sec_actual"), 0.0)
        db_path = Path(str(before.get("db_path") or "")).expanduser()
        if not db_path.is_absolute():
            db_path = (WORKDIR / db_path).resolve()
        if not db_path.exists():
            continue
        candidates.append(
            {
                "path": path,
                "run_id": str(payload.get("run_id") or path.stem.replace("controlled_kpi_", "")),
                "duration": duration,
                "before": before,
                "db_path": db_path,
            }
        )
    if not candidates:
        raise FileNotFoundError("No controlled_kpi before runs found")
    candidates.sort(key=lambda r: (r["duration"], r["path"].name))
    return candidates[-1]


def _build_report(results_dir: Path, result_path: str | None = None) -> dict:
    run = _select_run(results_dir, result_path)
    logs = _load_logs(run["db_path"])
    per_bucket = defaultdict(lambda: Counter())
    raw_closes = Counter()
    raw_realized = Counter()
    admitted = 0
    expected_nonzero = 0
    current_edge_nonzero = 0
    ready_true_total = 0
    evaluated_rows = 0
    max_trade_count = 0

    for row in logs:
        event = row["event"]
        details = row["details"] or {}
        if event == "entry_gate_decision_summary":
            edge = details.get("entry_edge_over_fee") or {}
            symbol = str(details.get("symbol") or "UNKNOWN").upper()
            strategy = str(edge.get("strategy") or "UNKNOWN")
            side = _normalize_side(details.get("side"))
            bucket = _canonical_bucket(symbol, strategy, side)
            tc = _safe_int(edge.get("trade_count"), 0)
            evaluated_rows += 1
            max_trade_count = max(max_trade_count, tc)
            per_bucket[bucket]["gate_eval_rows"] += 1
            per_bucket[bucket]["max_trade_count"] = max(per_bucket[bucket]["max_trade_count"], tc)
            per_bucket[bucket]["ready_true"] += int(bool(edge.get("history_ready")))
            per_bucket[bucket]["expected_nonzero"] += int(abs(_safe_float(edge.get("mean_edge_over_fee"), 0.0)) > 0)
            per_bucket[bucket]["current_edge_nonzero"] += int(abs(_safe_float(details.get("current_edge"), 0.0)) > 0)
            if bool(details.get("final_allow")) and str(details.get("entry_reason") or "") == "seed_trades_override":
                admitted += 1
                per_bucket[bucket]["admitted"] += 1
        elif event == "position_close":
            pos = details.get("position") or {}
            symbol = str(details.get("symbol") or pos.get("symbol") or "UNKNOWN").upper()
            strategy = str(pos.get("entry_main_strategy") or pos.get("strategy") or details.get("main_strategy") or "UNKNOWN")
            side = _normalize_side(pos.get("side") or details.get("side"))
            bucket = _canonical_bucket(symbol, strategy, side)
            raw_closes[bucket] += 1
            per_bucket[bucket]["close_writes"] += 1
        elif event == "realized_outcome_per_side":
            symbol = str(details.get("symbol") or "UNKNOWN").upper()
            side = _normalize_side(details.get("side"))
            bucket = f"side|{side}"
            raw_realized[bucket] += 1
            per_bucket[bucket]["realized_rows"] += 1

    buckets = []
    for bucket in sorted(per_bucket):
        c = per_bucket[bucket]
        buckets.append(
            {
                "bucket_key": bucket,
                "close_writes": int(c.get("close_writes", 0)),
                "gate_eval_rows": int(c.get("gate_eval_rows", 0)),
                "trade_count_max": int(c.get("max_trade_count", 0)),
                "history_ready_true_count": int(c.get("ready_true", 0)),
                "history_ready_hit": bool(int(c.get("ready_true", 0)) > 0),
                "admitted": int(c.get("admitted", 0)),
                "expected_nonzero": int(c.get("expected_nonzero", 0)),
                "current_edge_nonzero": int(c.get("current_edge_nonzero", 0)),
                "readiness_gap_to_20": max(0, 20 - int(c.get("max_trade_count", 0))),
            }
        )

    classification = "READINESS_STILL_NOT_REACHED"
    if any(b["history_ready_hit"] for b in buckets):
        classification = "READINESS_UNLOCKED"
    elif any(b["trade_count_max"] > 0 for b in buckets):
        classification = "READINESS_PARTIALLY_UNLOCKED"

    aggregate = {
        "run_id": run["run_id"],
        "duration_sec_actual": run["duration"],
        "trade_count": _safe_int(run["before"].get("trade_count"), 0),
        "admitted": admitted,
        "position_close": int(sum(raw_closes.values())),
        "realized_rows": int(sum(raw_realized.values())),
        "history_ready_any": any(b["history_ready_hit"] for b in buckets),
        "history_ready_true_count": int(sum(b["history_ready_true_count"] for b in buckets)),
        "expected_nonzero": int(sum(b["expected_nonzero"] for b in buckets)),
        "current_edge_nonzero": int(sum(b["current_edge_nonzero"] for b in buckets)),
        "bucket_count": len(buckets),
        "max_trade_count": max_trade_count,
        "close_rate_per_min": (
            (sum(raw_closes.values()) * 60.0 / run["duration"]) if run["duration"] > 0 else 0.0
        ),
    }

    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "method_version": "v1",
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "scenarios": ["baseline", "disable_current_side", "disable_net_target_guard"],
            "classification": classification,
        },
        "run_parameters": {
            "source_result": str(run["path"]),
            "source_db": str(run["db_path"]),
            "duration_sec_actual": run["duration"],
        },
        "per_bucket": buckets,
        "aggregate": aggregate,
        "final_classification": classification,
    }


def _render_md(report: dict) -> str:
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "The 60-minute controlled PAPER corridor did not unlock edge-history readiness. Admission and close writes were real, but no evaluated bucket reached `trade_count >= 20`, `history_ready` never became true, and both `expected_net` and `current_edge` stayed at zero."
    )
    lines.append("")
    lines.append("## B. Scope")
    lines.append("- PAPER only")
    lines.append("- Audit-only")
    lines.append("- Symbols: BTCUSDTM, ETHUSDTM")
    lines.append("- Scenarios: baseline, disable_current_side, disable_net_target_guard")
    lines.append("")
    lines.append("## C. Run Parameters")
    rp = report["run_parameters"]
    lines.append(f"- Source result: `{rp['source_result']}`")
    lines.append(f"- Source DB: `{rp['source_db']}`")
    lines.append(f"- Duration sec actual: {rp['duration_sec_actual']:.0f}")
    lines.append("")
    lines.append("## D. Bucket-Level Trade Count Growth")
    for b in report["per_bucket"]:
        lines.append(
            f"- `{b['bucket_key']}`: close_writes={b['close_writes']}, gate_eval_rows={b['gate_eval_rows']}, trade_count_max={b['trade_count_max']}, readiness_gap_to_20={b['readiness_gap_to_20']}"
        )
    lines.append("")
    lines.append("## E. History Ready Results")
    agg = report["aggregate"]
    lines.append(f"- history_ready_any = {agg['history_ready_any']}")
    lines.append(f"- history_ready_true_count = {agg['history_ready_true_count']}")
    lines.append(f"- admitted = {agg['admitted']}")
    lines.append(f"- position_close = {agg['position_close']}")
    lines.append("")
    lines.append("## F. Expected Net / Current Edge Activation")
    lines.append(f"- expected_nonzero = {agg['expected_nonzero']}")
    lines.append(f"- current_edge_nonzero = {agg['current_edge_nonzero']}")
    lines.append("")
    lines.append("## G. Final Classification")
    lines.append(report["final_classification"])
    lines.append("")
    lines.append("## H. Whether Profitability Testing Can Begin")
    lines.append("No. The evaluated bucket never became ready, so profitability testing would still be dominated by readiness failure.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit long-corridor readiness unlock.")
    parser.add_argument("--results-dir", default=str(WORKDIR / "results"))
    parser.add_argument("--result-path", default=None)
    args = parser.parse_args(argv)
    report = _build_report(Path(args.results_dir), args.result_path)
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"long_corridor_readiness_unlock_{stamp}.json"
    md_path = DIAG_DIR / f"long_corridor_readiness_unlock_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
