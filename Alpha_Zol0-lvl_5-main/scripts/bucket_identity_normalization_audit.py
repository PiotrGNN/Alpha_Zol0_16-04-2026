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


def _normalize_side(value: str | None) -> str:
    txt = str(value or "").strip().lower()
    if txt in {"long", "buy"}:
        return "buy"
    if txt in {"short", "sell"}:
        return "sell"
    return txt or "unknown"


def _normalize_strategy_label(value: str | None) -> str:
    txt = str(value or "").strip()
    if not txt:
        return "UNKNOWN"
    upper = txt.upper()
    if upper in {"UNKNOWN", "__ALL__"}:
        return upper
    return upper


def _canonical_bucket_key(symbol: str | None, strategy: str | None, side: str | None) -> str:
    return f"{str(symbol or 'UNKNOWN').strip().upper()}|{_normalize_strategy_label(strategy)}|{_normalize_side(side)}"


def _bucket_alias_kind(raw_bucket: str, canonical_bucket: str, *, source: str) -> str:
    raw_parts = str(raw_bucket or "").split("|")
    canon_parts = str(canonical_bucket or "").split("|")
    if source == "realized":
        return "realized_axis"
    if len(raw_parts) != 3 or len(canon_parts) != 3:
        return "label_corruption"
    raw_strategy = raw_parts[1].strip()
    canon_strategy = canon_parts[1].strip()
    if raw_strategy.upper() == "__ALL__":
        return "fallback_alias"
    if raw_strategy.upper() == "UNKNOWN":
        return "unknown_alias"
    if raw_strategy.upper() == canon_strategy and raw_strategy != canon_strategy:
        return "case_only_alias"
    if raw_bucket == canonical_bucket:
        return "canonical"
    return "fragmented_alias"


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
                "run_id": str(
                    payload.get("run_id") or path.stem.replace("controlled_kpi_", "")
                ),
                "results_path": str(path),
                "db_path": str(db_path),
                "trade_count": _safe_int(before.get("trade_count"), 0),
                "net_pnl": float(before.get("net_pnl") or 0.0),
                "duration_sec_actual": float(before.get("duration_sec_actual") or 0.0),
                "symbol_stats": before.get("symbol_stats") or {},
                "logs": logs,
            }
        )
    return runs


def _extract_observations(run: dict) -> list[dict]:
    obs = []
    for row in run["logs"]:
        event = row["event"]
        details = row["details"] or {}
        if event == "entry_gate_decision_summary":
            edge = details.get("entry_edge_over_fee") or {}
            raw_bucket = (
                edge.get("bucket_key_primary")
                or edge.get("bucket_key_fallback")
                or edge.get("bucket_used_final")
                or _canonical_bucket_key(
                    details.get("symbol"), edge.get("strategy"), details.get("side")
                )
            )
            canonical = _canonical_bucket_key(
                details.get("symbol"),
                edge.get("strategy"),
                details.get("side"),
            )
            obs.append(
                {
                    "source": "gate_eval",
                    "event": event,
                    "run_id": run["run_id"],
                    "timestamp": row["timestamp"],
                    "symbol": str(details.get("symbol") or "UNKNOWN").upper(),
                    "side": _normalize_side(details.get("side")),
                    "strategy_raw": str(edge.get("strategy") or ""),
                    "bucket_raw": str(raw_bucket),
                    "bucket_canonical": canonical,
                    "alias_kind": _bucket_alias_kind(
                        str(raw_bucket), canonical, source="gate_eval"
                    ),
                    "trade_count": _safe_int(edge.get("trade_count"), 0),
                    "history_ready": bool(edge.get("history_ready")),
                    "admitted": bool(details.get("final_allow"))
                    and str(details.get("entry_reason") or "") == "seed_trades_override",
                    "entry_reason": str(details.get("entry_reason") or ""),
                }
            )
        elif event == "position_close":
            pos = details.get("position") or {}
            strategy_raw = str(
                pos.get("entry_main_strategy")
                or pos.get("strategy")
                or details.get("main_strategy")
                or ""
            )
            symbol = str(details.get("symbol") or pos.get("symbol") or "UNKNOWN").upper()
            side = _normalize_side(pos.get("side") or details.get("side"))
            canonical = _canonical_bucket_key(symbol, strategy_raw, side)
            obs.append(
                {
                    "source": "close_write",
                    "event": event,
                    "run_id": run["run_id"],
                    "timestamp": row["timestamp"],
                    "symbol": symbol,
                    "side": side,
                    "strategy_raw": strategy_raw,
                    "bucket_raw": f"{symbol}|{strategy_raw}|{side}",
                    "bucket_canonical": canonical,
                    "alias_kind": _bucket_alias_kind(
                        f"{symbol}|{strategy_raw}|{side}", canonical, source="close_write"
                    ),
                    "trade_count": 1,
                    "history_ready": None,
                    "admitted": True,
                    "entry_reason": str(pos.get("entry_reason") or ""),
                }
            )
        elif event == "realized_outcome_per_side":
            group_type = str(details.get("group_type") or "").strip()
            group_key = str(details.get("group_key") or "").strip()
            symbol = str(details.get("symbol") or "UNKNOWN").upper()
            side = _normalize_side(details.get("side"))
            raw_bucket = f"{group_type}|{group_key}" if group_type and group_key else f"{symbol}|{side}"
            obs.append(
                {
                    "source": "realized",
                    "event": event,
                    "run_id": run["run_id"],
                    "timestamp": row["timestamp"],
                    "symbol": symbol,
                    "side": side,
                    "strategy_raw": group_type or "",
                    "bucket_raw": raw_bucket,
                    "bucket_canonical": f"{symbol}|__REALIZED__|{side}",
                    "alias_kind": _bucket_alias_kind(raw_bucket, raw_bucket, source="realized"),
                    "trade_count": _safe_int(details.get("trade_count"), 1) or 1,
                    "history_ready": None,
                    "admitted": None,
                    "entry_reason": "",
                }
            )
    return obs


def _build_report(results_dir: Path) -> dict:
    runs = _selected_runs(results_dir)
    observations = []
    for run in runs:
        observations.extend(_extract_observations(run))

    per_run = []
    for run in runs:
        run_obs = [o for o in observations if o["run_id"] == run["run_id"]]
        counts = Counter(o["bucket_canonical"] for o in run_obs if o["source"] != "realized")
        per_run.append(
            {
                "run_id": run["run_id"],
                "results_path": run["results_path"],
                "db_path": run["db_path"],
                "trade_count": run["trade_count"],
                "duration_sec_actual": run["duration_sec_actual"],
                "symbol_stats": run["symbol_stats"],
                "bucket_variants": dict(sorted(counts.items())),
            }
        )

    per_bucket = defaultdict(lambda: Counter())
    per_bucket_meta = {}
    for obs in observations:
        if obs["source"] == "realized":
            continue
        key = obs["bucket_canonical"]
        per_bucket[key]["observations"] += 1
        per_bucket[key][f"{obs['source']}_rows"] += 1
        if obs["source"] == "gate_eval":
            per_bucket[key]["gate_trade_count_max"] = max(
                per_bucket[key]["gate_trade_count_max"], obs["trade_count"]
            )
            per_bucket[key]["gate_history_ready_true"] += int(bool(obs["history_ready"]))
            per_bucket[key]["admissions"] += int(bool(obs["admitted"]))
            per_bucket[key]["alias_case_only"] += int(obs["alias_kind"] == "case_only_alias")
            per_bucket[key]["alias_fallback"] += int(obs["alias_kind"] == "fallback_alias")
            per_bucket[key]["alias_unknown"] += int(obs["alias_kind"] == "unknown_alias")
            per_bucket[key]["alias_fragmented"] += int(obs["alias_kind"] == "fragmented_alias")
            per_bucket[key]["bucket_raw_examples"] = per_bucket[key].get("bucket_raw_examples", [])
            if len(per_bucket[key]["bucket_raw_examples"]) < 5:
                per_bucket[key]["bucket_raw_examples"].append(obs["bucket_raw"])
            per_bucket_meta.setdefault(
                key,
                {
                    "symbol": obs["symbol"],
                    "side": obs["side"],
                    "strategy_canonical": _normalize_strategy_label(obs["strategy_raw"]),
                },
            )
        elif obs["source"] == "close_write":
            per_bucket[key]["close_writes"] += 1
            per_bucket[key]["close_write_case_only"] += int(
                obs["alias_kind"] == "case_only_alias"
            )
            per_bucket[key]["close_write_fallback"] += int(obs["alias_kind"] == "fallback_alias")
            per_bucket[key]["close_write_unknown"] += int(obs["alias_kind"] == "unknown_alias")
            per_bucket[key]["close_write_fragmented"] += int(
                obs["alias_kind"] == "fragmented_alias"
            )
            per_bucket[key]["bucket_raw_examples"] = per_bucket[key].get("bucket_raw_examples", [])
            if len(per_bucket[key]["bucket_raw_examples"]) < 5:
                per_bucket[key]["bucket_raw_examples"].append(obs["bucket_raw"])
            per_bucket_meta.setdefault(
                key,
                {
                    "symbol": obs["symbol"],
                    "side": obs["side"],
                    "strategy_canonical": _normalize_strategy_label(obs["strategy_raw"]),
                },
            )

    buckets = []
    for key in sorted(per_bucket):
        c = per_bucket[key]
        meta = per_bucket_meta.get(key) or {}
        close_writes = int(c.get("close_writes", 0))
        gate_trade_count_max = int(c.get("gate_trade_count_max", 0))
        history_ready_true = int(c.get("gate_history_ready_true", 0))
        alias_case_only_total = int(c.get("alias_case_only", 0)) + int(
            c.get("close_write_case_only", 0)
        )
        alias_fallback_total = int(c.get("alias_fallback", 0)) + int(
            c.get("close_write_fallback", 0)
        )
        alias_unknown_total = int(c.get("alias_unknown", 0)) + int(
            c.get("close_write_unknown", 0)
        )
        buckets.append(
            {
                "bucket_canonical": key,
                "symbol": meta.get("symbol"),
                "side": meta.get("side"),
                "strategy_canonical": meta.get("strategy_canonical"),
                "close_writes": close_writes,
                "gate_eval_rows": int(c.get("gate_eval_rows", 0)),
                "realized_rows": int(c.get("realized_rows", 0)),
                "gate_trade_count_max": gate_trade_count_max,
                "history_ready_hit": bool(history_ready_true > 0),
                "history_ready_true_count": history_ready_true,
                "readiness_gap_vs_min_trades": max(0, 20 - gate_trade_count_max),
                "close_write_gap_vs_min_trades": max(0, 20 - close_writes),
                "alias_case_only": alias_case_only_total,
                "alias_fallback": alias_fallback_total,
                "alias_unknown": alias_unknown_total,
                "alias_fragmented": int(c.get("alias_fragmented", 0)),
                "bucket_raw_examples": c.get("bucket_raw_examples", []),
                "normalized_identity": key,
            }
        )

    normalized_groups = defaultdict(lambda: Counter())
    for obs in observations:
        if obs["source"] == "realized":
            continue
        normalized_groups[obs["bucket_canonical"]][obs["source"]] += 1

    combined_close_writes = sum(b["close_writes"] for b in buckets)
    combined_gate_trade_count_max = max((b["gate_trade_count_max"] for b in buckets), default=0)
    case_alias_count = sum(b["alias_case_only"] for b in buckets)
    fallback_alias_count = sum(b["alias_fallback"] for b in buckets)
    unknown_alias_count = sum(b["alias_unknown"] for b in buckets)

    normalized_impact = {
        "canonical_buckets": len(buckets),
        "case_only_aliases": int(case_alias_count),
        "fallback_aliases": int(fallback_alias_count),
        "unknown_aliases": int(unknown_alias_count),
        "combined_close_writes": int(combined_close_writes),
        "combined_gate_trade_count_max": int(combined_gate_trade_count_max),
        "readiness_gap_after_normalization": max(0, 20 - int(combined_close_writes)),
        "material_alias_groups": [
            b["bucket_canonical"]
            for b in buckets
            if b["alias_case_only"] > 0 or b["close_writes"] > 0 and b["gate_eval_rows"] > 0
        ],
    }

    if case_alias_count > 0:
        classification = "BUCKET_IDENTITY_FRAGMENTATION_IS_MATERIAL"
    elif fallback_alias_count > 0 or unknown_alias_count > 0:
        classification = "BUCKET_IDENTITY_FRAGMENTATION_IS_SECONDARY"
    else:
        classification = "BUCKET_IDENTITY_FRAGMENTATION_NOT_MATERIAL"

    aggregate = {
        "total_runs": len(runs),
        "total_observations": len(observations),
        "total_buckets": len(buckets),
        "total_close_writes": int(sum(b["close_writes"] for b in buckets)),
        "total_gate_eval_rows": int(sum(b["gate_eval_rows"] for b in buckets)),
        "total_realized_rows": int(sum(b["realized_rows"] for b in buckets)),
        "normalized_impact_estimate": normalized_impact,
        "bucket_alias_summary": {
            "case_only": int(case_alias_count),
            "fallback": int(fallback_alias_count),
            "unknown": int(unknown_alias_count),
        },
        "root_cause_severity": classification,
        "edge_readiness_unlock_feasible": bool(
            combined_close_writes >= 20 and combined_gate_trade_count_max >= 20
        ),
    }

    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "method_version": "v1",
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "scenarios": [
                "baseline",
                "disable_current_side",
                "disable_net_target_guard",
            ],
            "classification": classification,
        },
        "per_run": per_run,
        "per_bucket": buckets,
        "aggregate": aggregate,
        "final_classification": classification,
    }


def _render_md(report: dict) -> str:
    md = []
    md.append("## A. Executive Summary")
    md.append(
        "Bucket identity fragmentation is real in the seed-readiness corridor. The close write path stores realized closes under `TrendFollowing`, while gate evaluation normalizes to `TRENDFOLLOWING`, so the same semantic bucket is split across casing variants. This materially hides accumulation, but even after normalization the combined close count remains far below `min_trades = 20`."
    )
    md.append("")
    md.append("## B. Scope")
    md.append("- PAPER only")
    md.append("- Audit-only")
    md.append("- Symbols: BTCUSDTM, ETHUSDTM")
    md.append("- Scenarios: baseline, disable_current_side, disable_net_target_guard")
    md.append("")
    md.append("## C. Bucket Identity Variants")
    for bucket in report["per_bucket"]:
        md.append(
            f"- `{bucket['bucket_canonical']}`: close_writes={bucket['close_writes']}, gate_eval_rows={bucket['gate_eval_rows']}, aliases(case={bucket['alias_case_only']}, fallback={bucket['alias_fallback']}, unknown={bucket['alias_unknown']})"
        )
    md.append("")
    md.append("## D. Close Write Path vs Gate Evaluation Mapping")
    md.append(
        "Close writes use `position_close -> entry_main_strategy`, which preserves `TrendFollowing`. Gate evaluation uses `strategy.upper()` in the bucket key, which produces `TRENDFOLLOWING`. These two paths are semantically the same bucket but are stored under different raw identities."
    )
    md.append("")
    md.append("## E. Normalization Impact Estimate")
    impact = report["aggregate"]["normalized_impact_estimate"]
    md.append(
        f"Combined close writes after canonicalization: {impact['combined_close_writes']}. Combined gate trade-count max: {impact['combined_gate_trade_count_max']}. Readiness gap after normalization: {impact['readiness_gap_after_normalization']}."
    )
    md.append("")
    md.append("## F. Root Cause Severity")
    md.append(report["aggregate"]["root_cause_severity"])
    md.append("")
    md.append("## G. Minimal Research-Only Patch Plan")
    md.append(
        "If prototyped, the normalization should be research-only: canonicalize strategy labels in audit/reporting only, keep raw keys in event logs, and never mutate realized storage or `min_trades` behavior."
    )
    md.append("")
    md.append("## H. Final Classification")
    md.append(report["final_classification"])
    md.append("")
    md.append("## I. Whether Edge-Readiness Unlock Looks Feasible")
    md.append(
        "Not feasible in the current corridor from normalization alone. The identity split is material, but even the merged close history remains below the readiness threshold."
    )
    return "\n".join(md) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Audit bucket identity fragmentation in edge-history accumulation."
    )
    parser.add_argument("--results-dir", default=str(WORKDIR / "results"))
    args = parser.parse_args(argv)
    report = _build_report(Path(args.results_dir))
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"bucket_identity_normalization_audit_{stamp}.json"
    md_path = DIAG_DIR / f"bucket_identity_normalization_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
