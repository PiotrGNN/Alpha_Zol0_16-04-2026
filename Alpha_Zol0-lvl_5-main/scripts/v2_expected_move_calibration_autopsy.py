from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

CALIBRATION_MIN_SAMPLE = 3
INSUFFICIENT_TELEMETRY_MIN_TRADES = 5


@dataclass(frozen=True)
class RunInput:
    run_id: str
    db_path: Path
    json_path: Path
    report: Dict[str, Any]


def _safe_json_loads(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str):
        return {}
    raw = raw.strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _dig(payload: Dict[str, Any], path: Sequence[str]) -> Any:
    cur: Any = payload
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _parse_ts_to_epoch(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except Exception:
        pass
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw).timestamp()
    except Exception:
        return None


def _iso_from_epoch(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _extract_run_id_from_db_path(path: Path) -> Optional[str]:
    match = re.search(r"controlled_kpi_after_(\d{8}_\d{6})\.db$", str(path.name))
    if match:
        return match.group(1)
    return None


def _pair_inputs(db_paths: List[Path], json_paths: List[Path]) -> List[RunInput]:
    reports_by_run_id: Dict[str, Tuple[Path, Dict[str, Any]]] = {}
    for path in json_paths:
        report = _safe_json_loads(path.read_text(encoding="utf-8"))
        run_id = str(report.get("run_id") or "").strip()
        if not run_id:
            raise RuntimeError(f"Report missing run_id: {path}")
        reports_by_run_id[run_id] = (path, report)

    out: List[RunInput] = []
    for db_path in db_paths:
        run_id = _extract_run_id_from_db_path(db_path)
        if not run_id:
            raise RuntimeError(f"Could not infer run_id from DB path: {db_path}")
        if run_id not in reports_by_run_id:
            raise RuntimeError(
                f"No matching report JSON for run_id={run_id} (db={db_path})"
            )
        json_path, report = reports_by_run_id[run_id]
        out.append(
            RunInput(
                run_id=run_id,
                db_path=db_path,
                json_path=json_path,
                report=report,
            )
        )
    return out


def _summarize_numeric(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
        }
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": float(sum(ordered) / len(ordered)),
        "median": _median(ordered),
    }


def _missing_fields_for_trade(record: Dict[str, Any]) -> List[str]:
    required = {
        "decision_or_gate_reason": record.get("decision_or_gate_reason"),
        "expected_net_after_full_cost": record.get("expected_net_after_full_cost"),
        "expected_gross_before_cost": record.get("expected_gross_before_cost"),
        "requested_notional_usdt": record.get("requested_notional_usdt"),
        "final_notional_usdt": record.get("final_notional_usdt"),
        "leverage": record.get("leverage"),
        "runtime_profile_key": record.get("runtime_profile_key"),
        "open_timestamp": record.get("open_timestamp"),
        "close_timestamp": record.get("close_timestamp"),
        "exit_reason": record.get("exit_reason"),
        "time_decay_exit_sec": record.get("time_decay_exit_sec"),
        "realized_pnl": record.get("realized_pnl"),
        "realized_gross": record.get("realized_gross"),
    }
    return [key for key, value in required.items() if value is None]


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _norm_symbol(value: Any) -> str:
    return _norm_text(value).upper()


def _norm_side(value: Any) -> str:
    side = _norm_text(value).lower()
    if side in {"buy", "sell"}:
        return side
    return ""


def _norm_strategy(value: Any) -> str:
    return _norm_text(value)


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return float(sum(values) / len(values))


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return float(median(values))


def _horizon_bucket(record: Dict[str, Any]) -> str:
    horizon = _safe_float(record.get("signal_horizon_sec_estimate"))
    if horizon is None:
        return "missing_horizon"
    if horizon < 5.0:
        return "signal_lt_5s"
    if horizon < 15.0:
        return "signal_5_15s"
    return "signal_ge_15s"


def _calibration_bucket_key(record: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (
        _norm_symbol(record.get("symbol")),
        _norm_strategy(record.get("strategy")),
        _norm_side(record.get("side")),
        _horizon_bucket(record),
    )


def analyze_run(run_input: RunInput) -> Dict[str, Any]:
    conn = sqlite3.connect(str(run_input.db_path))
    try:
        rows = conn.execute(
            "SELECT id, timestamp, event, details FROM logs ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()

    pending_gate_allow: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(
        list
    )
    pending_eval_allow: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(
        list
    )
    active_by_symbol: Dict[str, Dict[str, Any]] = {}
    admitted_trades: List[Dict[str, Any]] = []
    parser_anomalies: List[str] = []
    event_counts: Counter[str] = Counter()
    json_parse_fail_count = 0

    for row_id, row_ts, event, details in rows:
        event_name = str(event or "")
        event_counts[event_name] += 1
        payload = _safe_json_loads(details)
        if details and not payload:
            json_parse_fail_count += 1
        symbol = _norm_symbol(payload.get("symbol"))

        if event_name == "entry_gate_decision_summary":
            if bool(payload.get("final_allow")):
                key = (
                    symbol,
                    _norm_side(payload.get("side")),
                    _norm_strategy(payload.get("strategy")),
                )
                pending_gate_allow[key].append(payload)
            continue

        if event_name == "entry_eval_v2":
            if bool(payload.get("final_allow")):
                key = (
                    symbol,
                    _norm_side(payload.get("side")),
                    _norm_strategy(payload.get("strategy")),
                )
                pending_eval_allow[key].append(payload)
            continue

        if event_name == "exit_eval_v2":
            if symbol and symbol in active_by_symbol:
                net = _safe_float(payload.get("unrealized_net_pnl"))
                gross = _safe_float(payload.get("unrealized_gross_pnl"))
                if net is not None:
                    active_by_symbol[symbol]["_unrealized_net_path"].append(net)
                if gross is not None:
                    active_by_symbol[symbol]["_unrealized_gross_path"].append(gross)
            continue

        if event_name == "position_open_v2":
            side = _norm_side(payload.get("side"))
            strategy = _norm_strategy(payload.get("strategy"))
            key = (symbol, side, strategy)
            gate_payload = (
                pending_gate_allow[key].pop(0) if pending_gate_allow.get(key) else {}
            )
            eval_payload = (
                pending_eval_allow[key].pop(0) if pending_eval_allow.get(key) else {}
            )
            if symbol in active_by_symbol:
                parser_anomalies.append(
                    f"run={run_input.run_id} overlapping_open_symbol={symbol} row_id={row_id}"
                )

            position_obj = (
                payload.get("position") if isinstance(payload.get("position"), dict) else {}
            )
            open_meta = (
                position_obj.get("meta")
                if isinstance(position_obj.get("meta"), dict)
                else {}
            )
            open_ts = (
                _parse_ts_to_epoch(position_obj.get("opened_at"))
                or _parse_ts_to_epoch(position_obj.get("timestamp"))
                or _parse_ts_to_epoch(payload.get("ts"))
                or _parse_ts_to_epoch(row_ts)
            )
            cost_breakdown = (
                payload.get("cost_breakdown")
                if isinstance(payload.get("cost_breakdown"), dict)
                else {}
            )
            expected_move_raw = (
                _safe_float(payload.get("expected_move_raw"))
                or _safe_float(_dig(cost_breakdown, ("expected_move_raw",)))
                or _safe_float(open_meta.get("expected_move_raw"))
                or _safe_float(payload.get("expected_move"))
            )
            expected_move_scaled = (
                _safe_float(payload.get("expected_move_scaled"))
                or _safe_float(_dig(cost_breakdown, ("expected_move_scaled",)))
                or _safe_float(open_meta.get("expected_move_scaled"))
                or expected_move_raw
            )
            expected_gross_before_cost = (
                _safe_float(payload.get("expected_gross_before_cost"))
                or _safe_float(_dig(cost_breakdown, ("expected_gross_before_cost",)))
                or _safe_float(open_meta.get("expected_gross_before_cost"))
                or expected_move_scaled
            )
            expected_net_after_full_cost = _safe_float(
                payload.get("expected_net_after_full_cost")
            )
            entry_edge_after_execution = _safe_float(
                _dig(gate_payload, ("entry_edge_after_execution", "expected_net_after_cost"))
            )
            if entry_edge_after_execution is None:
                entry_edge_after_execution = _safe_float(
                    eval_payload.get("expected_net_after_cost")
                )
            entry_edge_over_fee = _safe_float(
                _dig(gate_payload, ("entry_edge_over_fee", "expected_edge_after_fee"))
            )
            if entry_edge_over_fee is None:
                entry_edge_over_fee = _safe_float(
                    eval_payload.get("expected_edge_after_fee")
                )
            runtime_profile_source = payload.get("runtime_profile_source")
            if runtime_profile_source is None and gate_payload:
                runtime_profile_source = "inferred_feature_profile_present"
            runtime_profile_key = payload.get("runtime_profile_key") or _dig(
                cost_breakdown,
                ("runtime_profile_key",),
            )

            active_by_symbol[symbol] = {
                "run_id": run_input.run_id,
                "event_open_row_id": int(row_id),
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "decision_or_gate_reason": str(
                    gate_payload.get("local_gate_reason")
                    or payload.get("entry_reason")
                    or ""
                ),
                "entry_reason": str(payload.get("entry_reason") or ""),
                "expected_net_after_full_cost": expected_net_after_full_cost,
                "entry_edge_after_execution": entry_edge_after_execution,
                "entry_edge_over_fee": entry_edge_over_fee,
                "cost_breakdown": cost_breakdown,
                "requested_notional_usdt": _safe_float(
                    payload.get("requested_notional_usdt")
                ),
                "final_notional_usdt": _safe_float(payload.get("notional_usdt"))
                or _safe_float(_dig(payload, ("sizing_trace", "final_notional_usdt"))),
                "leverage": _safe_float(payload.get("leverage")),
                "open_timestamp": open_ts,
                "open_timestamp_iso_utc": _iso_from_epoch(open_ts),
                "close_timestamp": None,
                "close_timestamp_iso_utc": None,
                "hold_seconds": None,
                "exit_reason": None,
                "realized_pnl": None,
                "realized_gross": None,
                "entry_fee_usdt": None,
                "exit_fee_usdt": None,
                "runtime_profile_source": runtime_profile_source,
                "runtime_profile_key": runtime_profile_key,
                "runtime_profile_age_sec": _safe_float(
                    payload.get("runtime_profile_age_sec")
                ),
                "runtime_profile_span_sec": _safe_float(
                    payload.get("runtime_profile_span_sec")
                ),
                "runtime_profile_sample_size": _safe_int(
                    payload.get("runtime_profile_sample_size"),
                    default=-1,
                ),
                "runtime_profile_source_missing": runtime_profile_source is None,
                "expected_move_raw": expected_move_raw,
                "expected_move_scaled": expected_move_scaled,
                "expected_gross_before_cost": expected_gross_before_cost,
                "signal_horizon_sec_estimate": _safe_float(
                    open_meta.get("signal_horizon_sec_estimate")
                ),
                "execution_horizon_sec": _safe_float(
                    open_meta.get("execution_horizon_sec")
                ),
                "time_decay_exit_sec": _safe_float(
                    open_meta.get("time_decay_exit_sec")
                ),
                "time_horizon_mismatch_sec": _safe_float(
                    open_meta.get("time_horizon_mismatch_sec")
                ),
                "time_horizon_mismatch_ratio": _safe_float(
                    open_meta.get("time_horizon_mismatch_ratio")
                ),
                "expected_cost_ratio": _safe_float(open_meta.get("expected_cost_ratio")),
                "expected_cost_usdt": _safe_float(open_meta.get("expected_cost_usdt")),
                "mfe_unrealized_net": None,
                "mae_unrealized_net": None,
                "mfe_unrealized_gross": None,
                "mae_unrealized_gross": None,
                "_unrealized_net_path": [],
                "_unrealized_gross_path": [],
            }
            continue

        if event_name == "position_close_v2":
            close_ts = (
                _parse_ts_to_epoch(payload.get("close_timestamp"))
                or _parse_ts_to_epoch(payload.get("ts"))
                or _parse_ts_to_epoch(row_ts)
            )
            record = active_by_symbol.pop(symbol, None)
            if record is None:
                parser_anomalies.append(
                    f"run={run_input.run_id} close_without_open symbol={symbol} row_id={row_id}"
                )
                continue

            record["close_timestamp"] = close_ts
            record["close_timestamp_iso_utc"] = _iso_from_epoch(close_ts)
            open_ts = _safe_float(record.get("open_timestamp"))
            record["hold_seconds"] = (
                float(close_ts - open_ts)
                if close_ts is not None and open_ts is not None
                else None
            )
            record["exit_reason"] = str(
                payload.get("exit_reason") or payload.get("close_reason") or ""
            )
            record["realized_pnl"] = _safe_float(payload.get("realized_pnl"))
            record["realized_gross"] = _safe_float(payload.get("realized_gross"))
            record["entry_fee_usdt"] = _safe_float(payload.get("entry_fee_usdt"))
            record["exit_fee_usdt"] = _safe_float(payload.get("exit_fee_usdt"))
            net_path = list(record.get("_unrealized_net_path") or [])
            gross_path = list(record.get("_unrealized_gross_path") or [])
            record["mfe_unrealized_net"] = max(net_path) if net_path else None
            record["mae_unrealized_net"] = min(net_path) if net_path else None
            record["mfe_unrealized_gross"] = max(gross_path) if gross_path else None
            record["mae_unrealized_gross"] = min(gross_path) if gross_path else None
            record["missing_telemetry_fields"] = _missing_fields_for_trade(record)
            record.pop("_unrealized_net_path", None)
            record.pop("_unrealized_gross_path", None)
            admitted_trades.append(record)
            continue

    for symbol, record in active_by_symbol.items():
        parser_anomalies.append(
            f"run={run_input.run_id} open_without_close symbol={symbol} open_row_id={record.get('event_open_row_id')}"
        )

    return {
        "run_id": run_input.run_id,
        "db_path": str(run_input.db_path),
        "json_path": str(run_input.json_path),
        "event_counts": dict(event_counts),
        "json_parse_fail_count": int(json_parse_fail_count),
        "parser_anomalies": parser_anomalies,
        "admitted_trade_count": len(admitted_trades),
        "admitted_trades": admitted_trades,
    }


def _is_clean_trade(record: Dict[str, Any]) -> bool:
    required_fields = (
        "symbol",
        "strategy",
        "side",
        "open_timestamp",
        "close_timestamp",
        "realized_pnl",
        "realized_gross",
        "expected_net_after_full_cost",
    )
    for field_name in required_fields:
        if record.get(field_name) in {None, ""}:
            return False
    if record.get("missing_telemetry_qualifier"):
        return False
    if record.get("missing_telemetry_fields"):
        return False
    if _norm_text(record.get("decision_or_gate_reason")) != "allow":
        return False
    if _norm_text(record.get("entry_reason")) != "decision_passed":
        return False
    if bool(record.get("runtime_profile_source_missing")):
        return False
    return True


def _bucket_calibration_stats(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[_calibration_bucket_key(record)].append(dict(record))

    buckets: List[Dict[str, Any]] = []
    for (symbol, strategy, side, horizon_bucket), rows in grouped.items():
        expected_gross_vals: List[float] = []
        realized_gross_vals: List[float] = []
        realized_net_vals: List[float] = []
        errors: List[float] = []
        calibration_values: List[float] = []
        mismatch_values: List[float] = []

        for row in rows:
            expected_gross = _safe_float(row.get("expected_gross_before_cost"))
            realized_gross = _safe_float(row.get("realized_gross"))
            realized_net = _safe_float(row.get("realized_pnl"))
            mismatch_ratio = _safe_float(row.get("time_horizon_mismatch_ratio"))
            if expected_gross is not None:
                expected_gross_vals.append(float(expected_gross))
            if realized_gross is not None:
                realized_gross_vals.append(float(realized_gross))
            if realized_net is not None:
                realized_net_vals.append(float(realized_net))
            if mismatch_ratio is not None:
                mismatch_values.append(float(mismatch_ratio))
            if expected_gross is not None and realized_gross is not None:
                errors.append(float(realized_gross - expected_gross))
                if abs(expected_gross) > 1e-12:
                    calibration_values.append(float(realized_gross / expected_gross))

        gross_profit = sum(value for value in realized_gross_vals if value > 0.0)
        gross_loss_abs = sum(abs(value) for value in realized_gross_vals if value < 0.0)
        net_profit = sum(value for value in realized_net_vals if value > 0.0)
        net_loss_abs = sum(abs(value) for value in realized_net_vals if value < 0.0)
        positive_realized_share = (
            sum(1 for value in realized_gross_vals if value > 0.0)
            / len(realized_gross_vals)
            if realized_gross_vals
            else 0.0
        )
        positive_net_share = (
            sum(1 for value in realized_net_vals if value > 0.0)
            / len(realized_net_vals)
            if realized_net_vals
            else 0.0
        )
        avg_expected_gross = _mean(expected_gross_vals) or 0.0
        avg_realized_gross = _mean(realized_gross_vals) or 0.0
        median_realized_gross = _median(realized_gross_vals) or 0.0
        avg_error = _mean(errors) or 0.0
        median_error = _median(errors) or 0.0
        expected_over_realized_ratio = 0.0
        if expected_gross_vals and realized_gross_vals:
            expected_over_realized_ratio = avg_expected_gross / max(
                abs(avg_realized_gross),
                1e-12,
            )
        calibration_factor = _median(calibration_values)
        if net_loss_abs > 0.0:
            profit_factor = float(net_profit / net_loss_abs)
        elif net_profit > 0.0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

        buckets.append(
            {
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "horizon_bucket": horizon_bucket,
                "n": len(rows),
                "avg_expected_gross": avg_expected_gross,
                "avg_realized_gross": avg_realized_gross,
                "median_realized_gross": median_realized_gross,
                "avg_error": avg_error,
                "median_error": median_error,
                "expected_over_realized_ratio": expected_over_realized_ratio,
                "calibration_factor": calibration_factor,
                "positive_realized_share": positive_realized_share,
                "positive_net_share": positive_net_share,
                "profit_factor": profit_factor,
                "expectancy": _mean(realized_net_vals) or 0.0,
                "gross_profit": float(gross_profit),
                "gross_loss_abs": float(gross_loss_abs),
                "avg_mismatch_ratio": _mean(mismatch_values),
                "median_mismatch_ratio": _median(mismatch_values),
            }
        )

    buckets.sort(
        key=lambda row: (
            row["symbol"],
            row["strategy"],
            row["side"],
            row["horizon_bucket"],
        )
    )
    return {"bucket_count": len(buckets), "buckets": buckets}


def _attach_calibration_fields(
    records: Sequence[Dict[str, Any]],
    bucket_stats: Dict[str, Any],
) -> List[Dict[str, Any]]:
    factor_lookup: Dict[Tuple[str, str, str, str], Optional[float]] = {}
    for bucket in bucket_stats.get("buckets") or []:
        key = (
            _norm_symbol(bucket.get("symbol")),
            _norm_strategy(bucket.get("strategy")),
            _norm_side(bucket.get("side")),
            _norm_text(bucket.get("horizon_bucket")),
        )
        factor_lookup[key] = bucket.get("calibration_factor")

    out: List[Dict[str, Any]] = []
    for record in records:
        key = _calibration_bucket_key(record)
        calibration_factor = factor_lookup.get(key)
        expected_gross = _safe_float(record.get("expected_gross_before_cost"))
        expected_cost = _safe_float(record.get("expected_cost_usdt"))
        calibrated_expected_gross = None
        calibrated_expected_net = None
        if calibration_factor is not None and expected_gross is not None:
            calibrated_expected_gross = float(
                expected_gross * float(calibration_factor)
            )
            if expected_cost is not None:
                calibrated_expected_net = float(
                    calibrated_expected_gross - expected_cost
                )
            else:
                calibrated_expected_net = float(calibrated_expected_gross)

        enriched = dict(record)
        enriched["calibration_bucket_key"] = ":".join(key)
        enriched["calibration_factor"] = calibration_factor
        enriched["calibrated_expected_gross"] = calibrated_expected_gross
        enriched["calibrated_expected_net"] = calibrated_expected_net
        enriched["clean_trade_eligible"] = _is_clean_trade(record)
        out.append(enriched)
    return out


def _calibration_summary(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    all_trades = [dict(row) for row in records]
    clean_trades = [dict(row) for row in all_trades if _is_clean_trade(row)]
    if not all_trades:
        return {
            "classification": "INSUFFICIENT_TELEMETRY",
            "clean_trade_count": 0,
            "all_trade_count": 0,
            "clean_trades": [],
            "all_trades": [],
            "bucket_stats": {"bucket_count": 0, "buckets": []},
        }

    bucket_stats = _bucket_calibration_stats(clean_trades)
    clean_enriched = _attach_calibration_fields(clean_trades, bucket_stats)
    all_enriched = _attach_calibration_fields(all_trades, bucket_stats)

    positive_ex_ante = [
        row
        for row in clean_enriched
        if (_safe_float(row.get("expected_net_after_full_cost")) or 0.0) > 0.0
    ]
    positive_ex_ante_closed_red = [
        row
        for row in positive_ex_ante
        if (_safe_float(row.get("realized_pnl")) or 0.0) <= 0.0
    ]
    losses = [
        row
        for row in clean_enriched
        if (_safe_float(row.get("realized_pnl")) or 0.0) <= 0.0
    ]
    time_decay_losses = [
        row
        for row in losses
        if _norm_text(row.get("exit_reason")) == "time_decay_exit"
    ]
    time_decay_positive_mfe = [
        row
        for row in time_decay_losses
        if (_safe_float(row.get("mfe_unrealized_net")) or 0.0) > 0.0
    ]

    bucket_rows = bucket_stats.get("buckets") or []
    strong_calibration_failure = any(
        row["n"] >= CALIBRATION_MIN_SAMPLE
        and row["avg_expected_gross"] > 0.0
        and row["median_realized_gross"] <= 0.0
        and row["positive_net_share"] < 0.50
        for row in bucket_rows
    )
    strong_horizon_mismatch = any(
        row["n"] >= CALIBRATION_MIN_SAMPLE
        and (row.get("median_mismatch_ratio") or 0.0) >= 2.0
        and row["positive_net_share"] < 0.50
        for row in bucket_rows
    )

    tuple_loss_counter: Counter[Tuple[str, str, str]] = Counter()
    total_loss_abs = 0.0
    for row in losses:
        pnl = _safe_float(row.get("realized_pnl")) or 0.0
        total_loss_abs += abs(pnl)
        tuple_key = (
            _norm_symbol(row.get("symbol")),
            _norm_strategy(row.get("strategy")),
            _norm_side(row.get("side")),
        )
        tuple_loss_counter[tuple_key] += abs(pnl)
    if tuple_loss_counter and total_loss_abs > 0.0:
        top_tuple_loss_share = max(tuple_loss_counter.values()) / total_loss_abs
    else:
        top_tuple_loss_share = 0.0

    expected_minus_realized: List[float] = []
    mismatch_values: List[float] = []
    calibration_factor_values: List[float] = []
    for row in clean_enriched:
        expected_value = _safe_float(row.get("expected_net_after_full_cost"))
        realized_value = _safe_float(row.get("realized_pnl"))
        mismatch_ratio = _safe_float(row.get("time_horizon_mismatch_ratio"))
        calibration_factor = _safe_float(row.get("calibration_factor"))
        if expected_value is not None and realized_value is not None:
            expected_minus_realized.append(float(realized_value - expected_value))
        if mismatch_ratio is not None:
            mismatch_values.append(float(mismatch_ratio))
        if calibration_factor is not None:
            calibration_factor_values.append(float(calibration_factor))

    total_clean = len(clean_enriched)
    positive_ex_ante_share = (
        len(positive_ex_ante) / total_clean if total_clean else 0.0
    )
    if positive_ex_ante:
        positive_ex_ante_closed_red_share = (
            len(positive_ex_ante_closed_red) / len(positive_ex_ante)
        )
    else:
        positive_ex_ante_closed_red_share = 0.0
    time_decay_loss_share = (len(time_decay_losses) / len(losses)) if losses else 0.0
    mean_expected_minus_realized = _summarize_numeric(
        expected_minus_realized
    ).get("mean")
    median_mismatch_ratio = _median(mismatch_values)
    median_calibration_factor = _median(calibration_factor_values)

    classification = "INSUFFICIENT_TELEMETRY"
    if total_clean >= INSUFFICIENT_TELEMETRY_MIN_TRADES:
        if strong_calibration_failure and strong_horizon_mismatch:
            classification = "MIXED_CALIBRATION_AND_HORIZON_FAILURE"
        elif strong_calibration_failure and top_tuple_loss_share >= 0.60:
            classification = "TUPLE_SPECIFIC_CALIBRATION_FAILURE"
        elif strong_calibration_failure:
            classification = "EXPECTED_MOVE_OVEROPTIMISTIC_DOMINANT"
        elif strong_horizon_mismatch and time_decay_loss_share >= 0.60:
            classification = "HORIZON_MISMATCH_DOMINANT"
        elif (
            time_decay_loss_share >= 0.60
            and positive_ex_ante_closed_red_share >= 0.50
        ):
            classification = "TIME_DECAY_EXIT_DOMINANT_AFTER_CALIBRATION"

    return {
        "classification": classification,
        "clean_trade_count": total_clean,
        "all_trade_count": len(all_enriched),
        "clean_positive_ex_ante_count": len(positive_ex_ante),
        "clean_positive_ex_ante_closed_red_count": len(positive_ex_ante_closed_red),
        "clean_losses_count": len(losses),
        "time_decay_loss_count": len(time_decay_losses),
        "time_decay_loss_share": time_decay_loss_share,
        "time_decay_positive_mfe_count": len(time_decay_positive_mfe),
        "positive_ex_ante_share": positive_ex_ante_share,
        "positive_ex_ante_closed_red_share": positive_ex_ante_closed_red_share,
        "median_mismatch_ratio": median_mismatch_ratio,
        "mean_expected_minus_realized": mean_expected_minus_realized,
        "median_calibration_factor": median_calibration_factor,
        "bucket_stats": bucket_stats,
        "clean_trades": clean_enriched,
        "all_trades": all_enriched,
    }


def build_expected_move_calibration_corpus(
    run_inputs: Sequence[RunInput],
) -> Dict[str, Any]:
    run_results = [analyze_run(run_input) for run_input in run_inputs]
    run_results.sort(key=lambda item: str(item.get("run_id")))

    all_trades: List[Dict[str, Any]] = []
    for run in run_results:
        all_trades.extend(run.get("admitted_trades", []))

    summary = _calibration_summary(all_trades)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "paper_only": True,
            "live": 0,
            "use_mock": 0,
            "source_runs": [run_input.run_id for run_input in run_inputs],
        },
        "inputs": [
            {
                "run_id": run_input.run_id,
                "db_path": str(run_input.db_path),
                "json_path": str(run_input.json_path),
            }
            for run_input in run_inputs
        ],
        "runs": run_results,
        "summary": summary,
        "combined_verdict": summary.get("classification"),
        "clean_trade_count": summary.get("clean_trade_count", 0),
        "bucket_stats": summary.get("bucket_stats") or {
            "bucket_count": 0,
            "buckets": [],
        },
        "clean_trades": summary.get("clean_trades") or [],
    }


def _render_markdown(audit: Dict[str, Any]) -> str:
    summary = audit.get("summary") or {}
    bucket_stats = summary.get("bucket_stats") or {"bucket_count": 0, "buckets": []}
    lines = ["# V2 Expected Move Calibration Autopsy", ""]
    lines.append(f"Generated UTC: {audit.get('generated_at_utc')}")
    lines.append("")
    lines.append("## Verdict")
    lines.append(f"- combined_verdict: `{audit.get('combined_verdict')}`")
    lines.append(f"- clean_trade_count: `{audit.get('clean_trade_count')}`")
    lines.append(f"- bucket_count: `{bucket_stats.get('bucket_count')}`")
    lines.append(
        f"- positive_ex_ante_closed_red_share: "
        f"`{summary.get('positive_ex_ante_closed_red_share')}`"
    )
    lines.append(f"- time_decay_loss_share: `{summary.get('time_decay_loss_share')}`")
    lines.append(
        f"- median_calibration_factor: `{summary.get('median_calibration_factor')}`"
    )
    lines.append("")
    lines.append("## Bucket Highlights")
    for row in (bucket_stats.get("buckets") or [])[:20]:
        bucket_label = (
            f"{row.get('symbol')}|{row.get('strategy')}|"
            f"{row.get('side')}|{row.get('horizon_bucket')}"
        )
        line = (
            f"- `{bucket_label}` n={row.get('n')} "
            f"calib={row.get('calibration_factor')} "
            f"pf={row.get('profit_factor')} "
            f"expectancy={row.get('expectancy')}"
        )
        lines.append(line)
    lines.append("")
    lines.append("## Clean Trade Count By Run")
    clean_trades = summary.get("clean_trades") or []
    for run in audit.get("runs", []):
        run_id = run.get("run_id")
        clean_count = sum(1 for row in clean_trades if row.get("run_id") == run_id)
        lines.append(
            f"- {run_id}: admitted={run.get('admitted_trade_count')} "
            f"clean={clean_count}"
        )
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="V2 expected-move calibration autopsy"
    )
    parser.add_argument(
        "--db",
        action="append",
        required=True,
        help="Path to controlled_kpi_after_<run_id>.db",
    )
    parser.add_argument(
        "--json",
        action="append",
        required=True,
        help="Path to controlled_kpi_<run_id>.json",
    )
    parser.add_argument(
        "--out-json",
        required=True,
        help="Output JSON artifact path",
    )
    parser.add_argument(
        "--out-md",
        required=True,
        help="Output Markdown artifact path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_paths = [Path(path).resolve() for path in args.db]
    json_paths = [Path(path).resolve() for path in args.json]
    out_json = Path(args.out_json).resolve()
    out_md = Path(args.out_md).resolve()

    run_inputs = _pair_inputs(db_paths, json_paths)
    audit_payload = build_expected_move_calibration_corpus(run_inputs)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(audit_payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    out_md.write_text(_render_markdown(audit_payload), encoding="utf-8")

    print(f"AUDIT_JSON={out_json}")
    print(f"AUDIT_MD={out_md}")
    print(f"COMBINED_VERDICT={audit_payload.get('combined_verdict')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
