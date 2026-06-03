from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


CURRENT_ENTRY_MIN_NET_USDT = 0.12
LOWER_BUCKET_MAX = 0.12


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


def canonical_strategy(strategy: Any) -> str:
    raw = _norm(strategy)
    if raw.endswith("V2"):
        return raw[:-2]
    return raw


def profit_factor(pnls: list[float]) -> float:
    if not pnls:
        return 0.0
    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
    if gross_loss == 0.0:
        return math.inf if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _extract_expected_net(payload: dict[str, Any]) -> float | None:
    return (
        _safe_float(payload.get("expected_net_after_full_cost"))
        or _safe_float(_dig(payload, ("meta", "expected_net_after_full_cost")))
        or _safe_float(_dig(payload, ("risk_block_fields", "sizing_trace", "expected_net_after_full_cost")))
        or _safe_float(_dig(payload, ("sizing_trace", "expected_net_after_full_cost")))
    )


def _extract_cost_breakdown(open_payload: dict[str, Any], close_payload: dict[str, Any]) -> dict[str, Any]:
    cost = {}
    for source in (
        open_payload.get("cost_breakdown"),
        _dig(close_payload, ("meta", "cost_breakdown")),
        close_payload.get("cost_breakdown"),
    ):
        if isinstance(source, dict):
            cost.update(source)
    return cost


def _trade_key(payload: dict[str, Any]) -> str:
    position = payload.get("position") if isinstance(payload.get("position"), dict) else {}
    position_id = payload.get("position_id") or position.get("id") or position.get("position_id")
    if position_id:
        return str(position_id)
    return "|".join(
        [
            _norm(payload.get("symbol")).upper(),
            _norm(payload.get("strategy")),
            _norm(payload.get("side")).lower(),
        ]
    )


def _effective_min_net_from_report(run_report: dict[str, Any]) -> float | None:
    after = run_report.get("after") if isinstance(run_report.get("after"), dict) else {}
    effective = after.get("effective_env_values") if isinstance(after.get("effective_env_values"), dict) else {}
    for key in ("ENTRY_MIN_NET_USDT", "ENTRY_MIN_EXPECTED_NET_USDT", "V2_ENTRY_MIN_NET_USDT"):
        value = _safe_float(effective.get(key))
        if value is not None:
            return value
    return None


def _min_net_guard_enabled(run_report: dict[str, Any]) -> bool | None:
    after = run_report.get("after") if isinstance(run_report.get("after"), dict) else {}
    diag = after.get("diagnostic_env_flags") if isinstance(after.get("diagnostic_env_flags"), dict) else {}
    if diag.get("DIAG_DISABLE_NET_TARGET_GUARD") not in (None, "", "0", 0, False):
        return False
    effective = after.get("effective_env_values") if isinstance(after.get("effective_env_values"), dict) else {}
    if any(key in effective for key in ("ENTRY_MIN_NET_USDT", "ENTRY_MIN_EXPECTED_NET_USDT", "V2_ENTRY_MIN_NET_USDT")):
        return True
    return None


def _diagnostic_or_assisted(run_report: dict[str, Any], payload: dict[str, Any]) -> bool:
    after = run_report.get("after") if isinstance(run_report.get("after"), dict) else {}
    diag = after.get("diagnostic_env_flags") if isinstance(after.get("diagnostic_env_flags"), dict) else {}
    if str(diag.get("DIAGNOSTIC_MODE") or "0") not in {"", "0", "None"}:
        return True
    if payload.get("override_reason") or payload.get("paper_gate_override"):
        return True
    selection_source = _norm(payload.get("selection_source")).lower()
    return any(token in selection_source for token in ("fallback", "seed", "diagnostic", "forced"))


def classify_admission_provenance(trade: dict[str, Any], *, current_threshold: float = CURRENT_ENTRY_MIN_NET_USDT) -> str:
    expected = _safe_float(trade.get("expected_net_after_full_cost"))
    effective_min = _safe_float(trade.get("effective_entry_min_net_usdt"))
    guard_enabled = trade.get("min_net_guard_enabled")
    if bool(trade.get("diagnostic_or_assisted")):
        return "OPENED_WITH_DIAGNOSTIC_OR_ASSISTED_PATH"
    if guard_enabled is False:
        return "OPENED_WITH_MIN_NET_GUARD_DISABLED"
    if expected is None:
        return "OPEN_PROVENANCE_INCONCLUSIVE"
    if effective_min is None:
        return "OPENED_UNDER_LEGACY_THRESHOLD"
    if expected >= effective_min:
        return "OPENED_NATURALLY_UNDER_CURRENT_THRESHOLD"
    if effective_min >= current_threshold and guard_enabled is True and expected < current_threshold:
        return "OPENED_DUE_TO_GATE_ENFORCEMENT_GAP"
    if effective_min < current_threshold:
        return "OPENED_UNDER_LEGACY_THRESHOLD"
    return "OPENED_BECAUSE_EXPECTED_NET_AT_ENTRY_DIFFERED_FROM_BUCKET_VALUE"


def _run_is_clean(report: dict[str, Any], db_path: Path) -> tuple[bool, list[str]]:
    after = report.get("after") if isinstance(report.get("after"), dict) else {}
    params = report.get("params") if isinstance(report.get("params"), dict) else {}
    effective = after.get("effective_env_values") if isinstance(after.get("effective_env_values"), dict) else {}
    diag = after.get("diagnostic_env_flags") if isinstance(after.get("diagnostic_env_flags"), dict) else {}
    event_counts = after.get("event_counts") if isinstance(after.get("event_counts"), dict) else {}
    reasons: list[str] = []
    if _safe_int(after.get("process_returncode"), -999) != 0:
        reasons.append("nonzero_process_returncode")
    if str(after.get("shutdown_classification") or "") != "close_flush_done_pending_positions_zero":
        reasons.append("dirty_or_unknown_shutdown")
    if bool(params.get("use_mock")):
        reasons.append("use_mock_param")
    if str(diag.get("LIVE") or "0") != "0":
        reasons.append("live_env")
    if str(effective.get("SEED_TRADES_ENABLE") or "0") != "0":
        reasons.append("seed_trades_enabled")
    if str(effective.get("ALPHA_WHITELIST_FALLBACK_ENABLE") or "0") != "0":
        reasons.append("fallback_enabled")
    for event_name in ("seed_trade_open", "fallback_open", "mock_quote", "forced_cycle_exit", "cycle_end_liquidation"):
        if _safe_int(event_counts.get(event_name)):
            reasons.append(event_name)
    if not db_path.exists():
        reasons.append("missing_db")
    return not reasons, sorted(set(reasons))


def load_clean_lower_bucket_trades(
    *,
    run_id: str,
    db_path: Path,
    run_report: dict[str, Any],
    current_threshold: float = CURRENT_ENTRY_MIN_NET_USDT,
) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id, timestamp, event, details FROM logs ORDER BY id ASC").fetchall()
    finally:
        conn.close()

    active_by_key: dict[str, dict[str, Any]] = {}
    active_by_symbol: dict[str, dict[str, Any]] = {}
    paths_by_symbol: dict[str, list[tuple[int, float]]] = defaultdict(list)
    out: list[dict[str, Any]] = []
    effective_min = _effective_min_net_from_report(run_report)
    guard_enabled = _min_net_guard_enabled(run_report)
    for row in rows:
        event_name = str(row["event"] or "")
        payload = _json_loads(row["details"])
        symbol = _norm(payload.get("symbol")).upper()
        if event_name == "position_open_v2":
            active_by_key[_trade_key(payload)] = payload
            if symbol:
                active_by_symbol[symbol] = payload
                paths_by_symbol[symbol] = []
            continue
        if event_name == "exit_eval_v2":
            pnl = _safe_float(payload.get("unrealized_net_pnl"))
            if symbol and pnl is not None and symbol in active_by_symbol:
                paths_by_symbol[symbol].append((int(row["id"]), pnl))
            continue
        if event_name != "position_close_v2":
            continue
        open_payload = active_by_key.pop(_trade_key(payload), {})
        if not open_payload and symbol:
            open_payload = active_by_symbol.pop(symbol, {})
        merged = dict(open_payload)
        merged.update({key: value for key, value in payload.items() if value is not None})
        expected = _extract_expected_net(merged)
        realized = _safe_float(payload.get("realized_pnl"))
        if expected is None or realized is None or expected >= current_threshold:
            continue
        path = [value for _, value in paths_by_symbol.pop(symbol, [])]
        mfe = max(path) if path else None
        mae = min(path) if path else None
        first_peak_index = None
        time_from_peak_to_close = None
        if path and mfe is not None:
            first_peak_index = path.index(mfe)
            time_from_peak_to_close = max(0, len(path) - first_peak_index - 1)
        cost = _extract_cost_breakdown(open_payload, payload)
        actual_fees = (float(payload.get("entry_fee_usdt") or 0.0) + float(payload.get("exit_fee_usdt") or 0.0))
        expected_cost_usdt = _safe_float(_dig(payload, ("meta", "expected_cost_usdt")))
        if expected_cost_usdt is None:
            expected_cost_ratio = _safe_float(cost.get("total_cost_ratio"))
            notional = _safe_float(payload.get("notional_usdt")) or _safe_float(open_payload.get("notional_usdt"))
            expected_cost_usdt = (expected_cost_ratio * notional) if expected_cost_ratio is not None and notional is not None else None
        opened_ts = _safe_float(payload.get("opened_ts"))
        close_ts = _safe_float(payload.get("close_timestamp"))
        hold_duration = (close_ts - opened_ts) if opened_ts is not None and close_ts is not None else None
        trade = {
            "run_id": run_id,
            "open_event_id": int(row["id"]),
            "close_event_id": int(row["id"]),
            "symbol": symbol,
            "strategy": _norm(merged.get("strategy")),
            "canonical_strategy": canonical_strategy(merged.get("strategy")),
            "side": _norm(merged.get("side")).lower(),
            "entry_timestamp": opened_ts,
            "close_timestamp": close_ts,
            "expected_net_after_full_cost": expected,
            "gross_expected_move": _safe_float(merged.get("expected_gross_before_cost")),
            "fee_estimate": _safe_float(cost.get("fee_round_trip_ratio")),
            "spread_estimate": _safe_float(cost.get("spread_ratio")),
            "slippage_estimate": _safe_float(cost.get("slippage_ratio")),
            "execution_cost_burden": _safe_float(cost.get("total_cost_ratio")),
            "notional_usdt": _safe_float(merged.get("notional_usdt")),
            "quantity_contracts": _safe_float(merged.get("quantity_contracts")) or _safe_float(_dig(payload, ("meta", "sizing_trace", "quantity_contracts"))),
            "realized_net_pnl": realized,
            "realized_pnl": realized,
            "realized_gross_pnl": _safe_float(payload.get("realized_gross")),
            "actual_fees": actual_fees,
            "expected_cost_usdt": expected_cost_usdt,
            "mfe": mfe,
            "mae": mae,
            "green_to_red": bool(mfe is not None and mfe > 0 and realized < 0),
            "fee_inversion": bool(_safe_float(payload.get("realized_gross")) is not None and float(payload.get("realized_gross")) > 0 and realized <= 0),
            "exit_reason": _norm(payload.get("exit_reason") or payload.get("close_reason")),
            "hold_duration": hold_duration,
            "time_from_peak_mfe_to_close_observations": time_from_peak_to_close,
            "admission_gate_status": _norm(open_payload.get("entry_reason") or open_payload.get("entry_open_truth_classification")),
            "entry_reason": _norm(open_payload.get("entry_reason")),
            "effective_entry_min_net_usdt": effective_min,
            "min_net_guard_enabled": guard_enabled,
            "entry_was_natural": not _diagnostic_or_assisted(run_report, open_payload),
            "diagnostic_or_assisted": _diagnostic_or_assisted(run_report, open_payload),
            "legacy_or_different_threshold_semantics": effective_min is None or effective_min < current_threshold,
            "calibration_gate_reason": _norm(_dig(payload, ("meta", "calibration_gate", "reason_code"))),
            "time_horizon_mismatch_ratio": _safe_float(_dig(payload, ("meta", "time_horizon_mismatch_ratio"))),
            "signal_horizon_sec_estimate": _safe_float(_dig(payload, ("meta", "signal_horizon_sec_estimate"))),
            "execution_horizon_sec": _safe_float(_dig(payload, ("meta", "execution_horizon_sec"))),
        }
        trade["admission_provenance"] = classify_admission_provenance(trade, current_threshold=current_threshold)
        out.append(trade)
    return out


def compute_calibration_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = [
        (float(trade["expected_net_after_full_cost"]), float(trade["realized_pnl"]))
        for trade in trades
        if _safe_float(trade.get("expected_net_after_full_cost")) is not None and _safe_float(trade.get("realized_pnl")) is not None
    ]
    if not pairs:
        return {
            "count": 0,
            "average_expected_net": None,
            "average_realized_pnl": None,
            "average_prediction_error": None,
            "correlation": None,
            "overestimation_ratio": None,
        }
    expected = [p[0] for p in pairs]
    realized = [p[1] for p in pairs]
    avg_expected = mean(expected)
    avg_realized = mean(realized)
    correlation = None
    if len(pairs) >= 3:
        mean_expected = mean(expected)
        mean_realized = mean(realized)
        numerator = sum((x - mean_expected) * (y - mean_realized) for x, y in pairs)
        denom_x = math.sqrt(sum((x - mean_expected) ** 2 for x in expected))
        denom_y = math.sqrt(sum((y - mean_realized) ** 2 for y in realized))
        if denom_x > 0 and denom_y > 0:
            correlation = numerator / (denom_x * denom_y)
    return {
        "count": len(pairs),
        "average_expected_net": float(avg_expected),
        "average_realized_pnl": float(avg_realized),
        "average_prediction_error": float(avg_expected - avg_realized),
        "correlation": correlation,
        "overestimation_ratio": (math.inf if avg_realized == 0 and avg_expected > 0 else (avg_expected / avg_realized if avg_realized else None)),
    }


def _group_stats(trades: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        groups[str(key_fn(trade) or "UNKNOWN")].append(trade)
    out: dict[str, dict[str, Any]] = {}
    for key, rows in groups.items():
        pnls = [float(row["realized_pnl"]) for row in rows]
        out[key] = {
            "count": len(rows),
            "net_pnl": float(sum(pnls)),
            "expectancy": float(sum(pnls) / len(pnls)) if pnls else 0.0,
            "winrate": sum(1 for pnl in pnls if pnl > 0) / len(pnls) if pnls else 0.0,
            "profit_factor": profit_factor(pnls),
        }
    return dict(sorted(out.items(), key=lambda item: item[1]["net_pnl"]))


def _hold_bucket(hold_duration: float | None) -> str:
    if hold_duration is None:
        return "missing_hold_duration"
    if hold_duration < 10:
        return "hold_lt_10s"
    if hold_duration < 20:
        return "hold_10_20s"
    if hold_duration < 45:
        return "hold_20_45s"
    return "hold_ge_45s"


def _cost_bucket(cost: float | None) -> str:
    if cost is None:
        return "missing_cost"
    if cost <= 0.00025:
        return "cost_lte_0.00025"
    if cost <= 0.00035:
        return "cost_0.00025_0.00035"
    return "cost_gt_0.00035"


def classify_final(trades: list[dict[str, Any]], calibration: dict[str, Any]) -> str:
    if not trades:
        return "EXPECTED_NET_CALIBRATION_BLOCKED_BY_INSUFFICIENT_FIELDS"
    provenance_counts = Counter(trade["admission_provenance"] for trade in trades)
    if provenance_counts.get("OPENED_DUE_TO_GATE_ENFORCEMENT_GAP", 0):
        return "LOWER_BUCKET_GATE_ENFORCEMENT_GAP_FOUND"
    legacy_count = provenance_counts.get("OPENED_UNDER_LEGACY_THRESHOLD", 0) + provenance_counts.get("OPENED_WITH_MIN_NET_GUARD_DISABLED", 0)
    if legacy_count >= max(1, len(trades) // 2):
        return "LOWER_BUCKET_TRADES_OPENED_UNDER_LEGACY_OR_DISABLED_GUARD"
    avg_expected = calibration.get("average_expected_net")
    avg_realized = calibration.get("average_realized_pnl")
    if avg_expected is not None and avg_realized is not None and avg_expected > 0 and avg_realized < 0:
        return "EXPECTED_NET_OVERESTIMATES_REALIZED_PNL_BELOW_MIN_NET"
    if sum(1 for trade in trades if trade.get("green_to_red")) >= max(1, len(trades) // 2):
        return "LOWER_BUCKET_LOSSES_DOMINATED_BY_EXIT_HOLD_DEGRADATION"
    if sum(1 for trade in trades if trade.get("fee_inversion")) >= max(1, len(trades) // 2):
        return "LOWER_BUCKET_LOSSES_DOMINATED_BY_COST_UNDERESTIMATION"
    return "EXPECTED_NET_CALIBRATION_INCONCLUSIVE"


def _final_verdict(classification: str) -> str:
    if classification == "EXPECTED_NET_OVERESTIMATES_REALIZED_PNL_BELOW_MIN_NET":
        return "EXPECTED_NET_ESTIMATOR_REPAIR_REQUIRED"
    if classification == "LOWER_BUCKET_LOSSES_DOMINATED_BY_EXIT_HOLD_DEGRADATION":
        return "EXIT_HOLD_ATTRIBUTION_AUDIT_REQUIRED"
    if classification == "LOWER_BUCKET_LOSSES_DOMINATED_BY_COST_UNDERESTIMATION":
        return "COST_MODEL_AUDIT_REQUIRED"
    if classification == "LOWER_BUCKET_GATE_ENFORCEMENT_GAP_FOUND":
        return "ADMISSION_ENFORCEMENT_PATCH_REQUIRED"
    if classification == "EXPECTED_NET_CALIBRATION_BLOCKED_BY_INSUFFICIENT_FIELDS":
        return "TELEMETRY_ONLY_PATCH_REQUIRED"
    if classification == "LOWER_BUCKET_TRADES_OPENED_UNDER_LEGACY_OR_DISABLED_GUARD":
        return "LOWER_BUCKET_EVIDENCE_NOT_CURRENT_SEMANTICS"
    return "EXPECTED_NET_CALIBRATION_INCONCLUSIVE"


def build_report(*, repo_root: Path) -> dict[str, Any]:
    threshold_path = repo_root / "analysis" / "entry_min_net_threshold_calibration_current.json"
    threshold = _json_loads(threshold_path.read_text(encoding="utf-8"))
    clean_run_refs = threshold.get("source_evidence", {}).get("clean_controlled_runs", [])
    trades: list[dict[str, Any]] = []
    rejected_runs: list[dict[str, Any]] = []
    for ref in clean_run_refs:
        if not isinstance(ref, dict):
            continue
        run_id = str(ref.get("run_id") or "")
        json_path = repo_root / "results" / f"controlled_kpi_{run_id}.json"
        db_path = Path(str(ref.get("db_path") or ""))
        if not db_path.is_absolute():
            db_path = repo_root / db_path
        report = _json_loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else {}
        clean, reasons = _run_is_clean(report, db_path)
        if not clean:
            rejected_runs.append({"run_id": run_id, "reasons": reasons})
            continue
        trades.extend(
            load_clean_lower_bucket_trades(
                run_id=run_id,
                db_path=db_path,
                run_report=report,
                current_threshold=CURRENT_ENTRY_MIN_NET_USDT,
            )
        )
    calibration = compute_calibration_stats(trades)
    classification = classify_final(trades, calibration)
    pnls = [float(trade["realized_pnl"]) for trade in trades]
    provenance_counts = Counter(trade["admission_provenance"] for trade in trades)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "kucoin_only": True,
            "paper_only": True,
            "live": False,
            "threshold_mutation": False,
            "strategy_mutation": False,
            "current_entry_min_net_usdt": CURRENT_ENTRY_MIN_NET_USDT,
        },
        "source_artifacts": {
            "threshold_calibration": str(threshold_path),
            "clean_run_ref_count": len(clean_run_refs),
            "rejected_runs": rejected_runs,
        },
        "clean_lower_bucket_trade_count": len(trades),
        "expected_vs_realized_calibration": calibration,
        "admission_provenance": {
            "counts": dict(sorted(provenance_counts.items())),
            "gate_enforcement_gap_events": [
                {
                    "run_id": trade["run_id"],
                    "open_event_id": trade["open_event_id"],
                    "close_event_id": trade["close_event_id"],
                    "expected_net_after_full_cost": trade["expected_net_after_full_cost"],
                    "effective_entry_min_net_usdt": trade["effective_entry_min_net_usdt"],
                }
                for trade in trades
                if trade["admission_provenance"] == "OPENED_DUE_TO_GATE_ENFORCEMENT_GAP"
            ],
        },
        "failure_decomposition": {
            "net_pnl": float(sum(pnls)),
            "expectancy": float(sum(pnls) / len(pnls)) if pnls else 0.0,
            "profit_factor": profit_factor(pnls),
            "green_to_red_count": sum(1 for trade in trades if trade.get("green_to_red")),
            "fee_inversion_count": sum(1 for trade in trades if trade.get("fee_inversion")),
            "protective_exit_count": sum(1 for trade in trades if trade.get("exit_reason") == "protective_exit"),
            "missing_calibration_profile_count": sum(1 for trade in trades if trade.get("calibration_gate_reason") == "missing_expected_move_calibration_profile"),
            "severe_time_horizon_mismatch_count": sum(1 for trade in trades if (trade.get("time_horizon_mismatch_ratio") or 0) >= 10),
        },
        "bucket_outcome": {
            "by_symbol_strategy_side": _group_stats(trades, lambda row: f"{row['symbol']}:{row['strategy']}:{row['side']}"),
            "by_exit_reason": _group_stats(trades, lambda row: row.get("exit_reason")),
            "by_cost_burden": _group_stats(trades, lambda row: _cost_bucket(row.get("execution_cost_burden"))),
            "by_hold_duration": _group_stats(trades, lambda row: _hold_bucket(row.get("hold_duration"))),
        },
        "trades": trades,
        "classification": classification,
        "patch_decision": "no_threshold_change",
        "final_verdict": _final_verdict(classification),
    }
    return report


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Expected-Net Calibration Provenance Audit",
        "",
        f"- Classification: `{report['classification']}`",
        f"- Final verdict: `{report['final_verdict']}`",
        f"- Lower-bucket clean trade count: `{report['clean_lower_bucket_trade_count']}`",
        f"- Net PnL: `{report['failure_decomposition']['net_pnl']}`",
        f"- Expectancy: `{report['failure_decomposition']['expectancy']}`",
        f"- Provenance counts: `{report['admission_provenance']['counts']}`",
        "",
        "## Calibration",
        "",
    ]
    for key, value in report["expected_vs_realized_calibration"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Decomposition", ""])
    for key, value in report["failure_decomposition"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Trade Sample", ""])
    lines.append("| run | symbol | strategy | side | expected | realized | exit | provenance |")
    lines.append("|---|---|---|---|---:|---:|---|---|")
    for trade in report["trades"][:50]:
        lines.append(
            f"| {trade['run_id']} | {trade['symbol']} | {trade['strategy']} | {trade['side']} | "
            f"{trade['expected_net_after_full_cost']:.10f} | {trade['realized_pnl']:.10f} | "
            f"{trade['exit_reason']} | {trade['admission_provenance']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-json", default="analysis/expected_net_calibration_provenance_current.json")
    parser.add_argument("--output-md", default="analysis/expected_net_calibration_provenance_current.md")
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    report = build_report(repo_root=repo_root)
    output_json = repo_root / args.output_json
    output_md = repo_root / args.output_md
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(report, output_md)
    print(json.dumps({"classification": report["classification"], "final_verdict": report["final_verdict"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
