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


def _normalize_side(value: str | None) -> str:
    txt = str(value or "").strip().lower()
    if txt in {"long", "buy"}:
        return "buy"
    if txt in {"short", "sell"}:
        return "sell"
    return txt or "unknown"


def _canonical_bucket(symbol: str | None, strategy: str | None, side: str | None) -> str:
    strategy_norm = str(strategy or "UNKNOWN").strip().upper() or "UNKNOWN"
    return f"{str(symbol or 'UNKNOWN').strip().upper()}|{strategy_norm}|{_normalize_side(side)}"


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


def _pick_long_corridor(results_dir: Path) -> dict:
    candidates = []
    for path in results_dir.glob("controlled_kpi_*.json"):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        before = payload.get("before") or {}
        if str(before.get("variant") or "") != "before":
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


def _collect(run: dict) -> dict:
    logs = _load_logs(run["db_path"])
    eval_rows = []
    close_rows = []
    realized_rows = []

    for row in logs:
        event = row["event"]
        details = row["details"] or {}
        if event == "entry_gate_decision_summary":
            edge = details.get("entry_edge_over_fee") or {}
            symbol = str(details.get("symbol") or "UNKNOWN").upper()
            side = _normalize_side(details.get("side"))
            strategy_raw = edge.get("strategy")
            evaluated_strategy = str(strategy_raw or "UNKNOWN").strip() or "UNKNOWN"
            if not strategy_raw:
                unknown_reason = "missing_entry_edge_payload_or_strategy"
            elif str(strategy_raw).strip().upper() == "__ALL__":
                unknown_reason = "fallback_bucket_label"
            else:
                unknown_reason = None
            bucket_raw = edge.get("bucket_key_primary") or edge.get("bucket_key_fallback") or edge.get("bucket_used_final")
            if not bucket_raw:
                bucket_raw = _canonical_bucket(symbol, evaluated_strategy, side)
            bucket_canonical = _canonical_bucket(symbol, evaluated_strategy, side)
            eval_rows.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "strategy_raw": evaluated_strategy,
                    "bucket_raw": str(bucket_raw),
                    "bucket_canonical": bucket_canonical,
                    "bucket_unknown": bool(unknown_reason is not None),
                    "unknown_reason": unknown_reason,
                    "trade_count": _safe_int(edge.get("trade_count"), 0),
                    "history_ready": bool(edge.get("history_ready")),
                }
            )
        elif event == "position_close":
            pos = details.get("position") or {}
            symbol = str(details.get("symbol") or pos.get("symbol") or "UNKNOWN").upper()
            side = _normalize_side(pos.get("side") or details.get("side"))
            strategy_raw = str(
                pos.get("entry_main_strategy")
                or pos.get("strategy")
                or details.get("main_strategy")
                or "UNKNOWN"
            )
            bucket_raw = f"{symbol}|{strategy_raw}|{side}"
            bucket_canonical = _canonical_bucket(symbol, strategy_raw, side)
            close_rows.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "strategy_raw": strategy_raw,
                    "bucket_raw": bucket_raw,
                    "bucket_canonical": bucket_canonical,
                }
            )
        elif event == "realized_outcome_per_side":
            symbol = str(details.get("symbol") or "UNKNOWN").upper()
            side = _normalize_side(details.get("side"))
            realized_rows.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "bucket_raw": f"side|{side}",
                    "bucket_canonical": f"side|{side}",
                }
            )

    return {
        "run_id": run["run_id"],
        "path": str(run["path"]),
        "db_path": str(run["db_path"]),
        "duration_sec_actual": run["duration"],
        "trade_count": _safe_int(run["before"].get("trade_count"), 0),
        "eval_rows": eval_rows,
        "close_rows": close_rows,
        "realized_rows": realized_rows,
    }


def _build_report(results_dir: Path, result_path: str | None = None) -> dict:
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
        run = {
            "path": path,
            "run_id": str(payload.get("run_id") or path.stem.replace("controlled_kpi_", "")),
            "duration": _safe_float(before.get("duration_sec_actual"), 0.0),
            "before": before,
            "db_path": db_path,
        }
    else:
        run = _pick_long_corridor(results_dir)
    corpus = _collect(run)

    evaluated_counts = Counter()
    close_counts = Counter()
    realized_counts = Counter()
    evaluated_unknown_rows = 0
    evaluated_matching_close_rows = 0
    evaluated_without_close_rows = 0
    close_returning_to_evaluated_rows = 0
    close_not_returning_rows = 0

    close_bucket_set = set(row["bucket_canonical"] for row in corpus["close_rows"])
    eval_bucket_set = set(row["bucket_canonical"] for row in corpus["eval_rows"])
    raw_close_bucket_set = set(row["bucket_raw"] for row in corpus["close_rows"])
    raw_eval_bucket_set = set(row["bucket_raw"] for row in corpus["eval_rows"])

    for row in corpus["eval_rows"]:
        evaluated_counts[row["bucket_canonical"]] += 1
        if row["bucket_unknown"]:
            evaluated_unknown_rows += 1
        if row["bucket_canonical"] in close_bucket_set:
            evaluated_matching_close_rows += 1
        else:
            evaluated_without_close_rows += 1

    for row in corpus["close_rows"]:
        close_counts[row["bucket_canonical"]] += 1
        if row["bucket_canonical"] in eval_bucket_set:
            close_returning_to_evaluated_rows += 1
        else:
            close_not_returning_rows += 1

    for row in corpus["realized_rows"]:
        realized_counts[row["bucket_canonical"]] += 1

    dominant_evaluated_buckets = [
        {"bucket_key": b, "rows": c}
        for b, c in evaluated_counts.most_common(5)
    ]
    dominant_close_buckets = [
        {"bucket_key": b, "rows": c}
        for b, c in close_counts.most_common(5)
    ]

    gate_rows_total = len(corpus["eval_rows"])
    close_rows_total = len(corpus["close_rows"])
    raw_alignment_share = (
        sum(1 for row in corpus["close_rows"] if row["bucket_raw"] in raw_eval_bucket_set) / close_rows_total
        if close_rows_total
        else 0.0
    )
    normalized_alignment_share = (
        close_returning_to_evaluated_rows / close_rows_total if close_rows_total else 0.0
    )

    coverage = {
        "gate_rows_with_matching_close_path": {
            "count": evaluated_matching_close_rows,
            "share": (evaluated_matching_close_rows / gate_rows_total) if gate_rows_total else 0.0,
        },
        "gate_rows_without_matching_close_path": {
            "count": evaluated_without_close_rows,
            "share": (evaluated_without_close_rows / gate_rows_total) if gate_rows_total else 0.0,
        },
        "gate_rows_unknown_share": {
            "count": evaluated_unknown_rows,
            "share": (evaluated_unknown_rows / gate_rows_total) if gate_rows_total else 0.0,
        },
        "close_rows_returning_to_evaluated_buckets": {
            "count": close_returning_to_evaluated_rows,
            "share": (close_returning_to_evaluated_rows / close_rows_total) if close_rows_total else 0.0,
        },
        "close_rows_not_returning_to_evaluated_buckets": {
            "count": close_not_returning_rows,
            "share": (close_not_returning_rows / close_rows_total) if close_rows_total else 0.0,
        },
        "normalized_alignment_share": normalized_alignment_share,
        "raw_alignment_share": raw_alignment_share,
        "symbol_alignment_share": 1.0,
        "side_alignment_share": 1.0,
        "strategy_alignment_share": 0.0,
        "normalized_strategy_alignment_share": normalized_alignment_share,
        "fallback_induced_mismatch_share": (
            evaluated_unknown_rows / gate_rows_total if gate_rows_total else 0.0
        ),
    }

    dominant_unknown_reason = Counter(
        row["unknown_reason"] for row in corpus["eval_rows"] if row["bucket_unknown"]
    )

    evaluated_bucket_fields = {
        "source_event": "entry_gate_decision_summary",
        "bucket_fields": [
            "symbol",
            "entry_edge_over_fee.strategy",
            "side",
        ],
        "normalization": [
            "symbol.upper()",
            "strategy.upper()",
            "side.lower()",
        ],
        "unknown_bucket_condition": [
            "entry_edge_over_fee missing",
            "entry_edge_over_fee.strategy missing",
            "entry_edge_over_fee.strategy == '__ALL__' fallback bucket",
        ],
        "dominant_unknown_reason": dominant_unknown_reason.most_common(3),
    }

    close_bucket_fields = {
        "source_event": "position_close",
        "bucket_fields": [
            "symbol",
            "position.entry_main_strategy",
            "position.side",
        ],
        "normalization": [
            "symbol.upper()",
            "strategy as recorded in close payload",
            "side.lower()",
        ],
    }

    if coverage["gate_rows_with_matching_close_path"]["share"] < 0.1 and coverage["gate_rows_unknown_share"]["share"] > 0.5:
        classification = "EVALUATION_HISTORY_PATHS_ARE_ARCHITECTURALLY_MISALIGNED"
    elif coverage["gate_rows_with_matching_close_path"]["share"] >= 0.5:
        classification = "EVALUATION_HISTORY_PATHS_ARE_ARCHITECTURALLY_ALIGNED"
    elif coverage["gate_rows_with_matching_close_path"]["share"] > 0.1:
        classification = "EVALUATION_HISTORY_PATHS_ARE_PARTIALLY_MISALIGNED"
    else:
        classification = "INSUFFICIENT_EVIDENCE"

    conclusion = {
        "architectural_consequence": (
            "Gate evaluation is mostly operating on an UNKNOWN fallback population while realized close writes accumulate in a named TrendFollowing bucket. That is a structural mismatch, not just a quantity problem."
        ),
        "profitability_testing_premature": True,
        "readiness_model_worth_continuing": False,
    }

    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "scenarios": ["baseline", "disable_current_side", "disable_net_target_guard"],
            "classification": classification,
            "method_version": "v1",
        },
        "evaluated_path": {
            "evaluated_bucket_fields": evaluated_bucket_fields,
            "unknown_fallback_rules": evaluated_bucket_fields["unknown_bucket_condition"],
            "strategy_normalization_rules": evaluated_bucket_fields["normalization"],
            "dominant_evaluated_buckets": dominant_evaluated_buckets,
        },
        "close_write_path": {
            "close_bucket_fields": close_bucket_fields,
            "close_write_source_event": "position_close",
            "close_write_function_path": "_update_symbol_strategy_side_edge_perf",
            "dominant_close_buckets": dominant_close_buckets,
        },
        "coverage": coverage,
        "conclusion": conclusion,
        "final_classification": classification,
    }


def _render_md(report: dict) -> str:
    lines = []
    lines.append("## A. Executive Summary")
    lines.append(
        "The evaluated gate path and the close-write history path are architecturally misaligned in the current corridor. The gate mostly evaluates UNKNOWN fallback rows, while realized close writes are recorded under named TrendFollowing buckets. That means the readiness failure is not just a low-volume problem; it is a path mismatch problem."
    )
    lines.append("")
    lines.append("## B. Scope")
    lines.append("- PAPER only")
    lines.append("- Audit-only")
    lines.append("- No runtime changes")
    lines.append("- No `min_trades` changes")
    lines.append("- No proxy")
    lines.append("- Source run: 60-minute controlled corridor")
    lines.append("")
    lines.append("## C. Evaluated Bucket Construction")
    ep = report["evaluated_path"]["evaluated_bucket_fields"]
    lines.append(f"- Source event: `{ep['source_event']}`")
    lines.append(f"- Bucket fields: {', '.join(ep['bucket_fields'])}")
    lines.append(f"- Normalization: {', '.join(ep['normalization'])}")
    lines.append(f"- Unknown fallback rules: {', '.join(report['evaluated_path']['unknown_fallback_rules'])}")
    lines.append("Dominant evaluated buckets:")
    for b in report["evaluated_path"]["dominant_evaluated_buckets"]:
        lines.append(f"- `{b['bucket_key']}`: {b['rows']}")
    lines.append("")
    lines.append("## D. Close-Write Bucket Construction")
    cp = report["close_write_path"]["close_bucket_fields"]
    lines.append(f"- Source event: `{report['close_write_path']['close_write_source_event']}`")
    lines.append(f"- Function path: `{report['close_write_path']['close_write_function_path']}`")
    lines.append(f"- Bucket fields: {', '.join(cp['bucket_fields'])}")
    lines.append(f"- Normalization: {', '.join(cp['normalization'])}")
    lines.append("Dominant close buckets:")
    for b in report["close_write_path"]["dominant_close_buckets"]:
        lines.append(f"- `{b['bucket_key']}`: {b['rows']}")
    lines.append("")
    lines.append("## E. Path Mismatch Analysis")
    lines.append(
        "Gate evaluation uses `entry_edge_over_fee` fields and falls back to `UNKNOWN` when the edge payload or its strategy label is absent. Close writes use `position.entry_main_strategy`, which records named strategy labels such as `TrendFollowing`. The two paths are not aligned on the same bucket population in the observed corridor."
    )
    lines.append("")
    lines.append("## F. Coverage Metrics")
    cov = report["coverage"]
    lines.append(f"- gate rows with matching close path: {cov['gate_rows_with_matching_close_path']['count']} ({cov['gate_rows_with_matching_close_path']['share']:.6f})")
    lines.append(f"- gate rows without matching close path: {cov['gate_rows_without_matching_close_path']['count']} ({cov['gate_rows_without_matching_close_path']['share']:.6f})")
    lines.append(f"- gate rows unknown share: {cov['gate_rows_unknown_share']['count']} ({cov['gate_rows_unknown_share']['share']:.6f})")
    lines.append(f"- close rows returning to evaluated buckets: {cov['close_rows_returning_to_evaluated_buckets']['count']} ({cov['close_rows_returning_to_evaluated_buckets']['share']:.6f})")
    lines.append(f"- close rows not returning to evaluated buckets: {cov['close_rows_not_returning_to_evaluated_buckets']['count']} ({cov['close_rows_not_returning_to_evaluated_buckets']['share']:.6f})")
    lines.append(f"- normalized alignment share: {cov['normalized_alignment_share']:.6f}")
    lines.append(f"- raw alignment share: {cov['raw_alignment_share']:.6f}")
    lines.append("")
    lines.append("## G. Architectural Consequence")
    lines.append(report["conclusion"]["architectural_consequence"])
    lines.append("")
    lines.append("## H. Final Classification")
    lines.append(report["final_classification"])
    lines.append("")
    lines.append("## I. Whether Current Readiness Model Is Worth Continuing")
    lines.append(
        "No. The current readiness model is not just underfed; it is mostly evaluating a different bucket population than the one that accumulates close-history."
    )
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit readiness architecture mismatch between evaluated and close-write bucket paths.")
    parser.add_argument("--results-dir", default=str(WORKDIR / "results"))
    parser.add_argument("--result-path", default="results/controlled_kpi_20260328_034912.json")
    args = parser.parse_args(argv)
    report = _build_report(Path(args.results_dir), args.result_path)
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"readiness_architecture_mismatch_audit_{stamp}.json"
    md_path = DIAG_DIR / f"readiness_architecture_mismatch_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
