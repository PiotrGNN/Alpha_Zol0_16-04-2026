import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = WORKDIR / "results"
DIAG_DIR = WORKDIR / "artifacts" / "diagnostics"
DIAG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SCENARIOS = ("baseline", "disable_current_side", "disable_net_target_guard")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value, default=None):
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _parse_ts(value):
    if value is None:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except Exception:
        return None


def _normalize_side(value: str | None) -> str:
    txt = str(value or "").strip().lower()
    if txt in {"long", "buy"}:
        return "buy"
    if txt in {"short", "sell"}:
        return "sell"
    return txt or "unknown"


def _normalize_strategy(value: str | None) -> str:
    txt = str(value or "").strip()
    return txt or "unknown"


def _scenario_from_env(env: dict) -> str:
    if str((env or {}).get("DIAGNOSTIC_MODE") or "0") == "0":
        return "baseline"
    if str((env or {}).get("DIAG_DISABLE_NET_TARGET_GUARD") or "0") == "1":
        return "disable_net_target_guard"
    if str((env or {}).get("DIAG_ALLOW_REENTRY_WHILE_IN_POSITION") or "0") == "1":
        return "disable_current_side"
    return "other"


def _load_controlled_runs(results_dir: Path, scenarios: set[str] | None = None) -> list[dict]:
    runs = []
    for path in sorted(results_dir.glob("controlled_kpi_*.json")):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        before = payload.get("before") or {}
        if str(before.get("variant") or "") != "before":
            continue
        env = before.get("diagnostic_env_flags") or {}
        scenario = _scenario_from_env(env)
        if scenarios and scenario not in scenarios:
            continue
        db_path = Path(str(before.get("db_path") or "")).expanduser()
        if not db_path.is_absolute():
            db_path = (WORKDIR / db_path).resolve()
        if not db_path.exists():
            continue
        runs.append(
            {
                "run_id": str(payload.get("run_id") or path.stem.replace("controlled_kpi_", "")),
                "results_path": str(path),
                "scenario": scenario,
                "env": env,
                "trade_count": int(before.get("trade_count") or 0),
                "net_pnl": _safe_float(before.get("net_pnl"), 0.0) or 0.0,
                "decisions_count": int(before.get("decisions_count") or 0),
                "started_at_utc": str(before.get("started_at_utc") or ""),
                "ended_at_utc": str(before.get("ended_at_utc") or ""),
                "duration_sec_actual": _safe_float(before.get("duration_sec_actual"), 0.0) or 0.0,
                "db_path": db_path,
            }
        )
    return runs


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


def _entry_bucket_key(entry_details: dict) -> str:
    edge = entry_details.get("entry_edge_over_fee") or {}
    bucket = edge.get("bucket_key_primary") or edge.get("bucket_key_fallback") or edge.get("bucket_used_final")
    if bucket:
        return str(bucket)
    symbol = str(entry_details.get("symbol") or "unknown")
    side = _normalize_side(entry_details.get("side"))
    strategy = _normalize_strategy(edge.get("strategy"))
    return f"{symbol}|{strategy}|{side}"


def _realized_bucket_key(realized_details: dict) -> str:
    group_type = str(realized_details.get("group_type") or "").strip()
    group_key = str(realized_details.get("group_key") or "").strip()
    if group_type and group_key:
        return f"{group_type}|{group_key}"
    symbol = str(realized_details.get("symbol") or "unknown")
    side = _normalize_side(realized_details.get("side"))
    return f"{symbol}|{side}"


def _proxy_score(entry_details: dict) -> tuple[float, bool]:
    live_edge = entry_details.get("entry_live_edge") or {}
    edge_over_fee = entry_details.get("entry_edge_over_fee") or {}
    candidates = [
        _safe_float(live_edge.get("live_edge_proxy")),
        _safe_float(entry_details.get("entry_expected_edge_after_fee")),
        _safe_float(edge_over_fee.get("mean_edge_over_fee")),
    ]
    score = next((v for v in candidates if v is not None), 0.0)
    proxy_ready = any((v is not None and v > 0.0) for v in candidates)
    return float(score), bool(proxy_ready)


def _match_realized_rows(run_meta: dict) -> dict:
    if not Path(run_meta["db_path"]).exists():
        return {
            "matched": [],
            "unmatched": [],
            "realized_rows": 0,
            "entry_rows": 0,
        }
    events = _load_logs(run_meta["db_path"])
    entry_rows = [e for e in events if e["event"] == "entry_gate_decision_summary"]
    realized_rows = [e for e in events if e["event"] == "realized_outcome_per_side"]
    matched = []
    unmatched = []
    for realized in realized_rows:
        realized_ts = _parse_ts(realized["details"].get("ts") or realized["timestamp"])
        realized_symbol = str(realized["details"].get("symbol") or "unknown")
        realized_side = _normalize_side(realized["details"].get("side"))
        realized_net = _safe_float(realized["details"].get("realized_net_pnl"), 0.0) or 0.0
        realized_strategy = _normalize_strategy(realized["details"].get("main_strategy"))
        realized_bucket = _realized_bucket_key(realized["details"])
        candidates = []
        for entry in entry_rows:
            entry_ts = _parse_ts(entry["details"].get("ts") or entry["timestamp"])
            if entry_ts is None or realized_ts is None or entry_ts > realized_ts:
                continue
            if str(entry["details"].get("symbol") or "unknown") != realized_symbol:
                continue
            if _normalize_side(entry["details"].get("side")) != realized_side:
                continue
            proxy_score, proxy_ready = _proxy_score(entry["details"])
            entry_edge = entry["details"].get("entry_edge_over_fee") or {}
            entry_strategy = _normalize_strategy(entry_edge.get("strategy"))
            candidates.append(
                {
                    "entry_ts": entry_ts,
                    "proxy_score": proxy_score,
                    "proxy_ready": proxy_ready,
                    "entry_strategy": entry_strategy,
                    "entry_bucket_key": _entry_bucket_key(entry["details"]),
                    "lead_time_sec": (
                        (realized_ts - entry_ts).total_seconds() if realized_ts and entry_ts else None
                    ),
                    "strategy_match": entry_strategy == realized_strategy,
                    "bucket_match": _entry_bucket_key(entry["details"]) == realized_bucket,
                }
            )
        if not candidates:
            unmatched.append(
                {
                    "symbol": realized_symbol,
                    "side": realized_side,
                    "realized_net_pnl": float(realized_net),
                    "reason": "no_preceding_entry",
                }
            )
            continue
        candidates.sort(
            key=lambda item: (
                0 if item["proxy_ready"] else 1,
                abs(item["lead_time_sec"] or 0.0),
                item["entry_ts"],
            )
        )
        matched.append(
            {
                "symbol": realized_symbol,
                "side": realized_side,
                "realized_net_pnl": float(realized_net),
                "proxy_shadow_edge_mean": float(candidates[0]["proxy_score"] or 0.0),
                "strategy_match": bool(candidates[0]["strategy_match"]),
                "bucket_match": bool(candidates[0]["bucket_match"]),
                "lead_time_sec": candidates[0]["lead_time_sec"],
            }
        )
    return {
        "matched": matched,
        "unmatched": unmatched,
        "realized_rows": len(realized_rows),
        "entry_rows": len(entry_rows),
    }


def _summarize_corpus(runs: list[dict]) -> dict:
    scenario_counts = Counter()
    durations = []
    total_realized = Counter()
    matched_realized = Counter()
    unmatched_realized = Counter()
    positive_runs = []
    negative_runs = []
    matched_positive_pairs = 0
    matched_negative_pairs = 0
    matching_stats = Counter()
    for run in runs:
        scenario_counts[run["scenario"]] += 1
        durations.append(float(run["duration_sec_actual"] or 0.0))
        matched = _match_realized_rows(run)
        for p in matched["matched"]:
            pnl = float(p["realized_net_pnl"] or 0.0)
            total_realized["positive" if pnl > 0 else "negative" if pnl < 0 else "zero"] += 1
            if pnl > 0:
                matched_positive_pairs += 1
                matched_realized["positive"] += 1
            elif pnl < 0:
                matched_negative_pairs += 1
                matched_realized["negative"] += 1
            else:
                matched_realized["zero"] += 1
            if p["strategy_match"]:
                matching_stats["strategy_match"] += 1
            if p["bucket_match"]:
                matching_stats["bucket_match"] += 1
        for u in matched["unmatched"]:
            pnl = float(u["realized_net_pnl"] or 0.0)
            total_realized["positive" if pnl > 0 else "negative" if pnl < 0 else "zero"] += 1
            if pnl > 0:
                unmatched_realized["positive"] += 1
            elif pnl < 0:
                unmatched_realized["negative"] += 1
            else:
                unmatched_realized["zero"] += 1
        if matched["realized_rows"]:
            if any(float(p["realized_net_pnl"]) > 0 for p in matched["matched"]):
                positive_runs.append(run["run_id"])
            if any(float(p["realized_net_pnl"]) < 0 for p in matched["matched"]):
                negative_runs.append(run["run_id"])

    positive_matched_pct = (
        matched_positive_pairs / total_realized["positive"] if total_realized["positive"] else 0.0
    )
    negative_matched_pct = (
        matched_negative_pairs / total_realized["negative"] if total_realized["negative"] else 0.0
    )
    feasible = (
        total_realized["positive"] >= 20
        and total_realized["negative"] >= 20
        and matched_positive_pairs >= 20
        and matched_negative_pairs >= 20
    )

    if total_realized["positive"] == 0:
        root_cause = ["SCENARIO_SELECTION_BIAS", "INSUFFICIENT_RUNTIME_WINDOW"]
    elif matched_positive_pairs == 0 and total_realized["positive"] > 0:
        root_cause = ["MATCHING_LOGIC_FILTERING_POSITIVES"]
    elif total_realized["positive"] < 20 or matched_positive_pairs < 20:
        root_cause = ["INSUFFICIENT_RUNTIME_WINDOW"]
    else:
        root_cause = ["MIXED_CAUSES"]

    return {
        "metadata": {
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "scenarios": list(DEFAULT_SCENARIOS),
            "method_version": "v1",
        },
        "data_sources": {
            "results_dir": str(RESULTS_DIR),
            "runs_scanned": len(runs),
            "runs_selected": len(runs),
        },
        "realized_outcome_distribution": {
            "total_realized": int(total_realized["positive"] + total_realized["negative"] + total_realized["zero"]),
            "positive": int(total_realized["positive"]),
            "negative": int(total_realized["negative"]),
            "zero": int(total_realized["zero"]),
            "scenario_counts": dict(scenario_counts),
            "duration_sec_min": min(durations) if durations else None,
            "duration_sec_median": sorted(durations)[len(durations) // 2] if durations else None,
            "duration_sec_max": max(durations) if durations else None,
        },
        "matching_feasibility": {
            "positive_matched_pairs_count": int(matched_positive_pairs),
            "negative_matched_pairs_count": int(matched_negative_pairs),
            "positive_matched_pct": positive_matched_pct,
            "negative_matched_pct": negative_matched_pct,
            "matched_positive_runs": len(positive_runs),
            "matched_negative_runs": len(negative_runs),
            "matching_quality": {
                "strategy_match_rate": (
                    matching_stats["strategy_match"] / matched_negative_pairs if matched_negative_pairs else 0.0
                ),
                "bucket_match_rate": (
                    matching_stats["bucket_match"] / matched_negative_pairs if matched_negative_pairs else 0.0
                ),
            },
        },
        "root_cause": {
            "primary": root_cause[0],
            "all": root_cause,
            "note": (
                "No positive realized outcomes were found in the available controlled corpus, so the sample is one-sided."
                if total_realized["positive"] == 0
                else "Positive outcomes exist but do not yet satisfy the balanced-corpus threshold."
            ),
        },
        "balanced_corpus_feasibility": {
            "feasible_without_runtime_changes": bool(feasible),
            "reason": (
                "Positive outcomes are absent from the current corpus; without new runtime or broader scenario coverage, a balanced corpus cannot be built."
                if total_realized["positive"] == 0
                else "The current corpus does not satisfy the ≥20 positive and ≥20 negative matched-pair threshold."
            ),
        },
        "final_classification": "BALANCED_CORPUS_NOT_FEASIBLE" if not feasible else "BALANCED_CORPUS_FEASIBLE",
        "evidence_notes": {
            "matched_positive_pairs": int(matched_positive_pairs),
            "matched_negative_pairs": int(matched_negative_pairs),
            "unmatched_positive_pairs": int(unmatched_realized["positive"]),
            "unmatched_negative_pairs": int(unmatched_realized["negative"]),
            "selected_runs_with_positive_realized": len(positive_runs),
            "selected_runs_with_negative_realized": len(negative_runs),
        },
    }


def _render_md(report: dict) -> str:
    md = []
    md.append("## A. Executive Summary")
    md.append(
        "The available controlled corpus does not contain a balanced realized dataset. "
        "All observed realized outcomes in the selected before-runs are negative, so a fair proxy decision corpus cannot be constructed without changing runtime or broadening scope."
    )
    md.append("")
    md.append("## B. Scope")
    md.append("- PAPER only")
    md.append("- Audit-only")
    md.append("- Symbols: BTCUSDTM, ETHUSDTM")
    md.append("- Scenarios: baseline, disable_current_side, disable_net_target_guard")
    md.append("")
    md.append("## C. Data Sources")
    ds = report["data_sources"]
    md.append(f"- results_dir: {ds['results_dir']}")
    md.append(f"- runs_scanned: {ds['runs_scanned']}")
    md.append(f"- runs_selected: {ds['runs_selected']}")
    md.append("")
    md.append("## D. Realized Outcome Distribution")
    dist = report["realized_outcome_distribution"]
    md.append(f"- total_realized: {dist['total_realized']}")
    md.append(f"- positive: {dist['positive']}")
    md.append(f"- negative: {dist['negative']}")
    md.append(f"- zero: {dist['zero']}")
    md.append(f"- scenario_counts: {dist['scenario_counts']}")
    md.append("")
    md.append("## E. Matching Feasibility (Positive vs Negative)")
    mf = report["matching_feasibility"]
    md.append(f"- positive_matched_pairs_count: {mf['positive_matched_pairs_count']}")
    md.append(f"- negative_matched_pairs_count: {mf['negative_matched_pairs_count']}")
    md.append(f"- positive_matched_pct: {mf['positive_matched_pct']}")
    md.append(f"- negative_matched_pct: {mf['negative_matched_pct']}")
    md.append(f"- matching_quality.strategy_match_rate: {mf['matching_quality']['strategy_match_rate']}")
    md.append(f"- matching_quality.bucket_match_rate: {mf['matching_quality']['bucket_match_rate']}")
    md.append("")
    md.append("## F. Root Cause of One-Sided Corpus")
    rc = report["root_cause"]
    md.append(f"- primary: {rc['primary']}")
    md.append(f"- all: {rc['all']}")
    md.append(f"- note: {rc['note']}")
    md.append("")
    md.append("## G. Balanced Corpus Feasibility")
    bc = report["balanced_corpus_feasibility"]
    md.append(f"- feasible_without_runtime_changes: {bc['feasible_without_runtime_changes']}")
    md.append(f"- reason: {bc['reason']}")
    md.append("")
    md.append("## H. Final Classification")
    md.append(report["final_classification"])
    md.append("")
    md.append("## I. Implication for Proxy Decision")
    md.append(
        "A balanced corpus is not feasible from the current controlled dataset without changing runtime, broadening scope, or introducing new realized outcomes. "
        "That means the proxy decision is effectively closed on the current evidence: no production use, no contrarian use, and no further decision-grade rescue from the same corpus."
    )
    return "\n".join(md) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit whether a balanced realized corpus exists for proxy decisioning.")
    parser.add_argument("--results-dir", default=str(RESULTS_DIR))
    parser.add_argument("--scenarios", default=",".join(DEFAULT_SCENARIOS))
    args = parser.parse_args(argv)
    scenarios = {s.strip() for s in str(args.scenarios).split(",") if s.strip()}
    runs = _load_controlled_runs(Path(args.results_dir), scenarios=scenarios)
    report = _summarize_corpus(runs)
    stamp = report["metadata"]["stamp"]
    json_path = DIAG_DIR / f"proxy_corpus_balancing_audit_{stamp}.json"
    md_path = DIAG_DIR / f"proxy_corpus_balancing_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
