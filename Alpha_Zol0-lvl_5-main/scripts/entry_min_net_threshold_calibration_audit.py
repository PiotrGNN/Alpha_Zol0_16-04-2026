from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable


BUCKET_LABELS = ["<0.03", "0.03-0.05", "0.05-0.08", "0.08-0.10", "0.10-0.12", "0.12-0.15", ">0.15"]
HYPOTHETICAL_THRESHOLDS = [0.05, 0.08, 0.10, 0.12]
DEFAULT_MIN_CLEAN_SAMPLE = 3


@dataclass(frozen=True)
class ControlledRun:
    run_id: str
    json_path: Path
    db_path: Path
    report: dict[str, Any]
    clean: bool
    rejection_reasons: tuple[str, ...]


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_loads(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dig(payload: dict[str, Any], path: Iterable[str]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _norm(value: Any) -> str:
    return str(value or "").strip()


def bucket_for_expected_net(value: float | None) -> str:
    if value is None or value < 0.03:
        return "<0.03"
    if value < 0.05:
        return "0.03-0.05"
    if value < 0.08:
        return "0.05-0.08"
    if value < 0.10:
        return "0.08-0.10"
    if value < 0.12:
        return "0.10-0.12"
    if value < 0.15:
        return "0.12-0.15"
    return ">0.15"


def profit_factor(pnls: list[float]) -> float:
    if not pnls:
        return 0.0
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    if gross_loss == 0.0:
        return math.inf if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def sufficient_sample(count: int, *, min_clean_sample: int = DEFAULT_MIN_CLEAN_SAMPLE) -> bool:
    return count >= min_clean_sample


def _numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": float(mean(ordered)),
        "median": float(median(ordered)),
    }


def _ratio_to_full_cost(payload: dict[str, Any], ratio: float | None) -> float | None:
    if ratio is None:
        return None
    notional = (
        _safe_float(payload.get("final_notional_usdt"))
        or _safe_float(payload.get("notional_usdt"))
        or _safe_float(_dig(payload, ("risk_block_fields", "sizing_trace", "final_notional_usdt")))
        or _safe_float(_dig(payload, ("sizing_trace", "final_notional_usdt")))
    )
    if notional is None:
        return None
    return ratio * notional


def extract_expected_net_after_full_cost(payload: dict[str, Any]) -> float | None:
    direct = _safe_float(payload.get("expected_net_after_full_cost"))
    if direct is not None:
        return direct
    nested = _safe_float(_dig(payload, ("risk_block_fields", "sizing_trace", "expected_net_after_full_cost")))
    if nested is not None:
        return nested
    sizing = _safe_float(_dig(payload, ("sizing_trace", "expected_net_after_full_cost")))
    if sizing is not None:
        return sizing
    return _ratio_to_full_cost(payload, _safe_float(payload.get("expected_net_after_cost")))


def _extract_cost_ratio(payload: dict[str, Any]) -> float | None:
    return (
        _safe_float(payload.get("total_cost_ratio"))
        or _safe_float(_dig(payload, ("cost_breakdown", "total_cost_ratio")))
        or _safe_float(_dig(payload, ("meta", "total_cost_ratio")))
    )


def _extract_fee_usdt(payload: dict[str, Any]) -> float | None:
    entry_fee = _safe_float(payload.get("entry_fee_usdt"))
    exit_fee = _safe_float(payload.get("exit_fee_usdt"))
    if entry_fee is not None or exit_fee is not None:
        return float(entry_fee or 0.0) + float(exit_fee or 0.0)
    fee_ratio = (
        _safe_float(_dig(payload, ("cost_breakdown", "fee_round_trip_ratio")))
        or _safe_float(payload.get("fee_estimate"))
    )
    return _ratio_to_full_cost(payload, fee_ratio)


def _extract_spread_or_cost(payload: dict[str, Any]) -> float | None:
    spread = _safe_float(_dig(payload, ("spread", "spread_ratio")))
    if spread is not None:
        return spread
    return _extract_cost_ratio(payload)


def _run_contamination_reasons(report: dict[str, Any], db_path: Path) -> list[str]:
    after = report.get("after") if isinstance(report.get("after"), dict) else {}
    params = report.get("params") if isinstance(report.get("params"), dict) else {}
    effective_env = after.get("effective_env_values") if isinstance(after.get("effective_env_values"), dict) else {}
    diag_env = after.get("diagnostic_env_flags") if isinstance(after.get("diagnostic_env_flags"), dict) else {}
    event_counts = after.get("event_counts") if isinstance(after.get("event_counts"), dict) else {}
    reasons: list[str] = []
    if _safe_int(after.get("process_returncode"), -999) != 0:
        reasons.append("nonzero_process_returncode")
    if str(after.get("shutdown_classification") or "") != "close_flush_done_pending_positions_zero":
        reasons.append("dirty_or_unknown_shutdown")
    pending = (
        _safe_int(after.get("pending_positions_count"))
        or _safe_int(_dig(after, ("final_close_drain_snapshot", "pending_positions_count")))
        or _safe_int(_dig(after, ("final_close_drain_snapshot", "open_positions_count")))
    )
    if pending:
        reasons.append("pending_positions")
    if bool(params.get("use_mock")):
        reasons.append("use_mock_param")
    if str(diag_env.get("LIVE") or "0") != "0":
        reasons.append("live_env")
    if str(diag_env.get("DIAGNOSTIC_MODE") or "0") not in {"0", "", "None"}:
        reasons.append("diagnostic_mode")
    for key in ("DIAG_DISABLE_NET_TARGET_GUARD", "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION", "DIAG_DISABLE_SIDE_GUARD", "DIAG_DISABLE_SIDE_EXPECTANCY"):
        if diag_env.get(key) not in (None, "", "0", 0, False):
            reasons.append(key.lower())
    if str(effective_env.get("SEED_TRADES_ENABLE") or "0") != "0":
        reasons.append("seed_trades_enabled")
    if str(effective_env.get("ALPHA_WHITELIST_FALLBACK_ENABLE") or "0") != "0":
        reasons.append("fallback_enabled")
    for event_name in ("seed_trade_open", "fallback_open", "mock_quote", "forced_cycle_exit", "cycle_end_liquidation"):
        if _safe_int(event_counts.get(event_name)):
            reasons.append(event_name)
    if not db_path.exists():
        reasons.append("missing_db")
    else:
        try:
            conn = sqlite3.connect(str(db_path))
            try:
                has_logs = bool(
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='logs'"
                    ).fetchone()
                )
            finally:
                conn.close()
            if not has_logs:
                reasons.append("missing_logs_table")
        except sqlite3.Error:
            reasons.append("unreadable_db")
    return sorted(set(reasons))


def discover_controlled_runs(results_dir: Path, *, max_runs: int = 30) -> list[ControlledRun]:
    runs: list[ControlledRun] = []
    json_paths = [
        path
        for path in results_dir.glob("controlled_kpi_*.json")
        if not path.name.endswith("_after_summary.json")
    ]
    json_paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for json_path in json_paths[:max_runs]:
        report = _json_loads(json_path.read_text(encoding="utf-8"))
        run_id = str(report.get("run_id") or json_path.stem.replace("controlled_kpi_", ""))
        after = report.get("after") if isinstance(report.get("after"), dict) else {}
        db_path = Path(str(after.get("db_path") or f"tmp/controlled_kpi_after_{run_id}.db"))
        if not db_path.is_absolute():
            db_path = results_dir.parent / db_path
        reasons = _run_contamination_reasons(report, db_path)
        runs.append(
            ControlledRun(
                run_id=run_id,
                json_path=json_path,
                db_path=db_path,
                report=report,
                clean=not reasons,
                rejection_reasons=tuple(reasons),
            )
        )
    return runs


def _trade_key(payload: dict[str, Any]) -> str:
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    position_id = payload.get("position_id") or position.get("id") or position.get("position_id")
    if position_id:
        return str(position_id)
    return "|".join([_norm(payload.get("symbol")).upper(), _norm(payload.get("strategy")), _norm(payload.get("side")).lower()])


def _event_record(
    *,
    run: ControlledRun,
    event_name: str,
    row_id: int,
    payload: dict[str, Any],
    clean_completed_trade: bool = False,
    realized_pnl: float | None = None,
    exit_reason: str | None = None,
) -> dict[str, Any]:
    expected = extract_expected_net_after_full_cost(payload)
    return {
        "run_id": run.run_id,
        "row_id": row_id,
        "event": event_name,
        "symbol": _norm(payload.get("symbol")).upper(),
        "strategy": _norm(payload.get("strategy")),
        "side": _norm(payload.get("side")).lower(),
        "reason": _norm(payload.get("reason_code") or payload.get("local_gate_reason") or payload.get("entry_reason")),
        "expected_net_after_full_cost": expected,
        "expected_net_after_cost": _safe_float(payload.get("expected_net_after_cost")),
        "cost_ratio": _extract_cost_ratio(payload),
        "fee_usdt": _extract_fee_usdt(payload),
        "spread_or_cost_burden": _extract_spread_or_cost(payload),
        "position_open": event_name == "position_open_v2",
        "completed_trade": event_name == "position_close_v2",
        "clean_completed_trade": clean_completed_trade,
        "realized_pnl": realized_pnl,
        "exit_reason": exit_reason,
        "contaminated": not run.clean,
        "contamination_reasons": list(run.rejection_reasons),
    }


def load_runtime_records(run: ControlledRun) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(run.db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id, timestamp, event, details FROM logs ORDER BY id ASC").fetchall()
    finally:
        conn.close()

    records: list[dict[str, Any]] = []
    active: dict[str, dict[str, Any]] = {}
    active_by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_name = str(row["event"] or "")
        payload = _json_loads(row["details"])
        if event_name in {"entry_eval_v2", "entry_reject_v2", "entry_gate_decision_summary"}:
            if extract_expected_net_after_full_cost(payload) is not None:
                records.append(_event_record(run=run, event_name=event_name, row_id=int(row["id"]), payload=payload))
            continue
        if event_name == "position_open_v2":
            active[_trade_key(payload)] = payload
            symbol = _norm(payload.get("symbol")).upper()
            if symbol:
                active_by_symbol[symbol] = payload
            records.append(_event_record(run=run, event_name=event_name, row_id=int(row["id"]), payload=payload))
            continue
        if event_name == "position_close_v2":
            symbol = _norm(payload.get("symbol")).upper()
            open_payload = active.pop(_trade_key(payload), {})
            if not open_payload and symbol:
                open_payload = active_by_symbol.pop(symbol, {})
            merged = dict(open_payload)
            merged.update({k: v for k, v in payload.items() if v is not None})
            if "expected_net_after_full_cost" not in merged and "expected_net_after_full_cost" in open_payload:
                merged["expected_net_after_full_cost"] = open_payload["expected_net_after_full_cost"]
            realized = _safe_float(payload.get("realized_pnl"))
            records.append(
                _event_record(
                    run=run,
                    event_name=event_name,
                    row_id=int(row["id"]),
                    payload=merged,
                    clean_completed_trade=run.clean and realized is not None,
                    realized_pnl=realized,
                    exit_reason=_norm(payload.get("exit_reason") or payload.get("close_reason")),
                )
            )
    return [record for record in records if record.get("expected_net_after_full_cost") is not None]


def _counter_to_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def bucket_summary(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {label: [] for label in BUCKET_LABELS}
    for record in records:
        grouped[bucket_for_expected_net(_safe_float(record.get("expected_net_after_full_cost")))].append(record)

    out: dict[str, dict[str, Any]] = {}
    for label in BUCKET_LABELS:
        rows = grouped[label]
        clean_trade_rows = [row for row in rows if row.get("clean_completed_trade")]
        pnls = [float(row["realized_pnl"]) for row in clean_trade_rows if _safe_float(row.get("realized_pnl")) is not None]
        wins = [pnl for pnl in pnls if pnl > 0]
        fees = [float(row["fee_usdt"]) for row in rows if _safe_float(row.get("fee_usdt")) is not None]
        burdens = [float(row["spread_or_cost_burden"]) for row in rows if _safe_float(row.get("spread_or_cost_burden")) is not None]
        candidates = {
            (row.get("symbol"), row.get("strategy"), row.get("side"))
            for row in rows
            if row.get("symbol") or row.get("strategy") or row.get("side")
        }
        out[label] = {
            "candidate_count": len(candidates),
            "runtime_event_count": len(rows),
            "position_open_count": sum(1 for row in rows if row.get("position_open")),
            "completed_trade_count": sum(1 for row in rows if row.get("completed_trade")),
            "accepted_clean_trade_count": len(clean_trade_rows),
            "rejected_or_contaminated_count": sum(1 for row in rows if (not row.get("clean_completed_trade"))),
            "cumulative_net_pnl": float(sum(pnls)),
            "winrate": (len(wins) / len(pnls)) if pnls else 0.0,
            "profit_factor": profit_factor(pnls),
            "expectancy": (sum(pnls) / len(pnls)) if pnls else 0.0,
            "average_fee": float(mean(fees)) if fees else None,
            "average_spread_or_cost_burden": float(mean(burdens)) if burdens else None,
            "green_to_red_share": None,
            "fee_inversion_share": None,
            "exit_reason_distribution": _counter_to_dict(Counter(str(row.get("exit_reason") or "UNKNOWN") for row in clean_trade_rows)),
            "no_entry_reason_distribution": _counter_to_dict(Counter(str(row.get("reason") or "UNKNOWN") for row in rows if not row.get("position_open") and not row.get("completed_trade"))),
            "dominant_rejection_reasons": _counter_to_dict(Counter(str(row.get("reason") or "UNKNOWN") for row in rows if not row.get("clean_completed_trade"))),
        }
    return out


def threshold_simulation(
    records: list[dict[str, Any]],
    thresholds: list[float],
    *,
    min_clean_sample: int = DEFAULT_MIN_CLEAN_SAMPLE,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for threshold in thresholds:
        admitted = [
            row
            for row in records
            if (_safe_float(row.get("expected_net_after_full_cost")) is not None and float(row["expected_net_after_full_cost"]) >= threshold)
        ]
        clean_trades = [
            row
            for row in admitted
            if row.get("clean_completed_trade") and not row.get("contaminated")
        ]
        pnls = [float(row["realized_pnl"]) for row in clean_trades if _safe_float(row.get("realized_pnl")) is not None]
        out[f"{threshold:.2f}"] = {
            "admitted_event_count": len(admitted),
            "candidate_count": len({(row.get("symbol"), row.get("strategy"), row.get("side")) for row in admitted}),
            "clean_completed_trade_count": len(clean_trades),
            "net_pnl": float(sum(pnls)),
            "expectancy": (sum(pnls) / len(pnls)) if pnls else 0.0,
            "profit_factor": profit_factor(pnls),
            "contamination_rate": (sum(1 for row in admitted if row.get("contaminated")) / len(admitted)) if admitted else 0.0,
            "sample_sufficient": sufficient_sample(len(clean_trades), min_clean_sample=min_clean_sample),
        }
    return out


def _aggregate_lower_buckets(summary: dict[str, dict[str, Any]]) -> dict[str, Any]:
    lower_labels = ["<0.03", "0.03-0.05", "0.05-0.08", "0.08-0.10", "0.10-0.12"]
    clean_count = sum(_safe_int(summary[label]["accepted_clean_trade_count"]) for label in lower_labels)
    net_pnl = sum(float(summary[label]["cumulative_net_pnl"]) for label in lower_labels)
    return {
        "clean_completed_trade_count": clean_count,
        "net_pnl": float(net_pnl),
        "expectancy": (net_pnl / clean_count) if clean_count else 0.0,
    }


def classify_calibration(
    *,
    lower_bucket_aggregate: dict[str, Any],
    below_threshold_positive_bucket_count: int,
    below_threshold_clean_trade_count: int,
    min_clean_sample: int = DEFAULT_MIN_CLEAN_SAMPLE,
) -> str:
    if not sufficient_sample(below_threshold_clean_trade_count, min_clean_sample=min_clean_sample):
        return "ENTRY_MIN_NET_CALIBRATION_BLOCKED_BY_INSUFFICIENT_CLEAN_SAMPLE"
    expectancy = float(lower_bucket_aggregate.get("expectancy") or 0.0)
    net_pnl = float(lower_bucket_aggregate.get("net_pnl") or 0.0)
    if expectancy < 0.0 and net_pnl < 0.0:
        return "ENTRY_MIN_NET_0_12_SUPPORTED_BY_NEGATIVE_LOWER_BUCKETS"
    if below_threshold_positive_bucket_count > 0 and expectancy > 0.0 and net_pnl > 0.0:
        return "ENTRY_MIN_NET_0_12_TOO_HIGH_SUPPORTED_BY_CLEAN_LOWER_BUCKET_PROFIT"
    if expectancy > 0.0 or below_threshold_positive_bucket_count > 0:
        return "ENTRY_MIN_NET_0_12_POSSIBLY_TOO_HIGH_NEEDS_CONTROLLED_EXPERIMENT"
    return "ENTRY_MIN_NET_CALIBRATION_INCONCLUSIVE"


def _final_verdict(classification: str) -> str:
    if classification == "ENTRY_MIN_NET_0_12_SUPPORTED_BY_NEGATIVE_LOWER_BUCKETS":
        return "ENTRY_MIN_NET_THRESHOLD_CHANGE_NOT_JUSTIFIED"
    if classification == "ENTRY_MIN_NET_0_12_TOO_HIGH_SUPPORTED_BY_CLEAN_LOWER_BUCKET_PROFIT":
        return "PAPER_ONLY_THRESHOLD_EXPERIMENT_JUSTIFIED"
    if classification == "ENTRY_MIN_NET_0_12_POSSIBLY_TOO_HIGH_NEEDS_CONTROLLED_EXPERIMENT":
        return "PAPER_ONLY_THRESHOLD_EXPERIMENT_JUSTIFIED"
    if classification == "ENTRY_MIN_NET_CALIBRATION_BLOCKED_BY_INSUFFICIENT_CLEAN_SAMPLE":
        return "THRESHOLD_CALIBRATION_BLOCKED_BY_INSUFFICIENT_SAMPLE"
    return "ENTRY_MIN_NET_CALIBRATION_INCONCLUSIVE"


def _load_research_expected(analysis_dir: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in [
        analysis_dir / "new_alpha_research_validation_current.json",
        analysis_dir / "new_alpha_search_space_inventory_current.json",
        analysis_dir / "v2_economic_candidate_discovery_current.json",
    ]:
        if not path.exists():
            continue
        payload = _json_loads(path.read_text(encoding="utf-8"))
        items: list[Any] = []
        for key in ("selected_hypothesis", "single_best_hypothesis"):
            if isinstance(payload.get(key), dict):
                items.append(payload[key])
        for key in ("candidate_rank", "selected_hypotheses", "ranked_candidates", "qualified_candidates"):
            if isinstance(payload.get(key), list):
                items.extend(payload[key])
        for item in items:
            if not isinstance(item, dict):
                continue
            expected = _safe_float(item.get("expected_net_after_full_cost"))
            if expected is None:
                continue
            candidates.append(
                {
                    "source_artifact": str(path),
                    "symbol": _norm(item.get("symbol")).upper(),
                    "strategy": _norm(item.get("strategy")),
                    "side": _norm(item.get("side")).lower(),
                    "expected_net_after_full_cost": expected,
                    "accepted": item.get("accepted"),
                    "decision_reason": item.get("decision_reason") or item.get("reason"),
                }
            )
    unique: dict[tuple[str, str, str, float], dict[str, Any]] = {}
    for row in candidates:
        unique[(row["symbol"], row["strategy"], row["side"], row["expected_net_after_full_cost"])] = row
    return list(unique.values())


def build_report(
    *,
    repo_root: Path,
    min_clean_sample: int = DEFAULT_MIN_CLEAN_SAMPLE,
    max_runs: int = 30,
) -> dict[str, Any]:
    results_dir = repo_root / "results"
    analysis_dir = repo_root / "analysis"
    runs = discover_controlled_runs(results_dir, max_runs=max_runs)
    clean_runs = [run for run in runs if run.clean]
    records: list[dict[str, Any]] = []
    rejected_runs: list[dict[str, Any]] = []
    for run in runs:
        if not run.clean:
            rejected_runs.append(
                {
                    "run_id": run.run_id,
                    "json_path": str(run.json_path),
                    "db_path": str(run.db_path),
                    "reasons": list(run.rejection_reasons),
                }
            )
            continue
        records.extend(load_runtime_records(run))

    buckets = bucket_summary(records)
    lower_aggregate = _aggregate_lower_buckets(buckets)
    positive_lower_bucket_count = sum(
        1
        for label in ["<0.03", "0.03-0.05", "0.05-0.08", "0.08-0.10", "0.10-0.12"]
        if buckets[label]["accepted_clean_trade_count"] > 0 and buckets[label]["expectancy"] > 0.0
    )
    classification = classify_calibration(
        lower_bucket_aggregate=lower_aggregate,
        below_threshold_positive_bucket_count=positive_lower_bucket_count,
        below_threshold_clean_trade_count=int(lower_aggregate["clean_completed_trade_count"]),
        min_clean_sample=min_clean_sample,
    )
    near_miss = [
        row
        for row in records
        if 0.05 <= float(row["expected_net_after_full_cost"]) < 0.12
        and str(row.get("reason")) == "entry_min_net_guard"
    ]
    research_candidates = _load_research_expected(analysis_dir)
    runtime_values = [float(row["expected_net_after_full_cost"]) for row in records]
    trade_records = [row for row in records if row.get("clean_completed_trade")]
    trade_pairs = [
        {
            "run_id": row["run_id"],
            "symbol": row["symbol"],
            "strategy": row["strategy"],
            "side": row["side"],
            "expected_net_after_full_cost": row["expected_net_after_full_cost"],
            "realized_pnl": row["realized_pnl"],
            "bucket": bucket_for_expected_net(float(row["expected_net_after_full_cost"])),
            "exit_reason": row.get("exit_reason"),
        }
        for row in trade_records
    ]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "repo_root": str(repo_root),
            "kucoin_only": True,
            "paper_only": True,
            "live": False,
            "threshold_mutation": False,
            "strategy_mutation": False,
        },
        "source_evidence": {
            "controlled_run_count": len(runs),
            "max_recent_controlled_runs_considered": max_runs,
            "clean_controlled_run_count": len(clean_runs),
            "rejected_controlled_runs": rejected_runs,
            "clean_controlled_runs": [
                {"run_id": run.run_id, "json_path": str(run.json_path), "db_path": str(run.db_path)}
                for run in clean_runs
            ],
            "research_candidate_count": len(research_candidates),
        },
        "contamination_policy": {
            "rejected_if": [
                "nonzero_process_returncode",
                "dirty_or_unknown_shutdown",
                "pending_positions",
                "use_mock_param",
                "live_env",
                "diagnostic_mode_or_diag_disable_flags",
                "seed_trades_enabled",
                "fallback_enabled",
                "seed/fallback/mock/forced-cycle/cycle-end events",
                "missing_db",
            ]
        },
        "research_vs_runtime": {
            "research_expected_net_after_full_cost_stats": _numeric_summary(
                [float(row["expected_net_after_full_cost"]) for row in research_candidates]
            ),
            "runtime_expected_net_after_full_cost_stats": _numeric_summary(runtime_values),
            "research_candidates": research_candidates[:30],
        },
        "runtime_expected_net_vs_realized_pnl": {
            "clean_completed_trade_count": len(trade_records),
            "pairs": trade_pairs[:100],
        },
        "near_miss_min_net_guard": {
            "definition": "0.05 <= expected_net_after_full_cost < 0.12 and reason == entry_min_net_guard",
            "count": len(near_miss),
            "by_candidate": _counter_to_dict(Counter(f"{row['symbol']}:{row['strategy']}:{row['side']}" for row in near_miss)),
        },
        "bucket_level_economics": buckets,
        "lower_bucket_aggregate_below_0_12": lower_aggregate,
        "hypothetical_threshold_simulation": threshold_simulation(
            records,
            HYPOTHETICAL_THRESHOLDS,
            min_clean_sample=min_clean_sample,
        ),
        "classification": classification,
        "patch_decision": "no_threshold_change",
        "final_verdict": _final_verdict(classification),
    }
    return report


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Entry Min Net Threshold Calibration Audit",
        "",
        f"- Classification: `{report['classification']}`",
        f"- Final verdict: `{report['final_verdict']}`",
        f"- Patch decision: `{report['patch_decision']}`",
        f"- Clean controlled runs: `{report['source_evidence']['clean_controlled_run_count']}` / `{report['source_evidence']['controlled_run_count']}`",
        f"- Near-miss min-net guard count: `{report['near_miss_min_net_guard']['count']}`",
        "",
        "## Bucket-Level Economics",
        "",
        "| bucket | runtime_events | opens | clean_trades | net_pnl | expectancy | profit_factor | dominant_rejections |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for label in BUCKET_LABELS:
        row = report["bucket_level_economics"][label]
        dominant = ", ".join(f"{k}:{v}" for k, v in list(row["dominant_rejection_reasons"].items())[:3])
        lines.append(
            f"| {label} | {row['runtime_event_count']} | {row['position_open_count']} | "
            f"{row['accepted_clean_trade_count']} | {row['cumulative_net_pnl']:.10f} | "
            f"{row['expectancy']:.10f} | {row['profit_factor']} | {dominant} |"
        )
    lines.extend(["", "## Hypothetical Threshold Simulation", ""])
    lines.append("| threshold | admitted_events | clean_trades | net_pnl | expectancy | sample_sufficient |")
    lines.append("|---:|---:|---:|---:|---:|---|")
    for threshold, row in report["hypothetical_threshold_simulation"].items():
        lines.append(
            f"| {threshold} | {row['admitted_event_count']} | {row['clean_completed_trade_count']} | "
            f"{row['net_pnl']:.10f} | {row['expectancy']:.10f} | {row['sample_sufficient']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-json", default="analysis/entry_min_net_threshold_calibration_current.json")
    parser.add_argument("--output-md", default="analysis/entry_min_net_threshold_calibration_current.md")
    parser.add_argument("--min-clean-sample", type=int, default=DEFAULT_MIN_CLEAN_SAMPLE)
    parser.add_argument("--max-runs", type=int, default=30)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    report = build_report(
        repo_root=repo_root,
        min_clean_sample=args.min_clean_sample,
        max_runs=args.max_runs,
    )
    output_json = repo_root / args.output_json
    output_md = repo_root / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(report, output_md)
    print(json.dumps({"classification": report["classification"], "final_verdict": report["final_verdict"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
