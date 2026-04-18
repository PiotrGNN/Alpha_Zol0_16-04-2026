# flake8: noqa: E501

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "Alpha_Zol0-lvl_5-main"
RUNNER = ROOT / "DataAnalysisExpert" / "run_11_paper_v2.py"
FEE_REPORTER = ROOT / "DataAnalysisExpert" / "report_fee_sanity.py"
RUNNER_RESULT_JSON = ROOT / "DataAnalysisExpert" / "paper_v2_results.json"
AUTOPSY = ROOT / "autopsy"

AUTOPSY.mkdir(parents=True, exist_ok=True)

SEEDS = (1337, 2024, 42)
IS_SEEDS = (1337, 2024)
OOS_SEEDS = (42,)
NA_UNRELIABLE = "N/A - cannot be reconstructed reliably from current logs"
HARD_REASONS = {"auto_close_hard", "auto_close_hard_near_zero"}
ECONOMIC_TIME_REASONS = {"auto_close_time_economics", "auto_close_time_fee_floor"}
COVERAGE_GATE_MIN_SHARE = 0.80
DIRECT_CLOSE_MFE_MIN_SHARE = 0.80

CASE_BASELINE = "BASELINE_H1_RUNTIME"
CASE_PATCH = "PATCH_REALIZED_QUALITY_SOFT_MIN3"
CASE_ORDER = (CASE_BASELINE, CASE_PATCH)

BASE_ENV = {
    "RUN_SYMBOLS": "ETHUSDTM,BTCUSDTM",
    "PAPER_V2_NUM_RUNS": "1",
    "PAPER_V2_TICKS_PER_RUN": "240",
    "PAPER_V2_TICK_SLEEP_SEC": "2",
    "FUNDING_RATE": "0",
    "PAPER_SPREAD_BPS": "3",
    "PAPER_SPREAD_USDT": "0",
    "allocation_pct": "0.01",
    "PAPER_EXECUTION_MODEL": "maker_sim",
    "PAPER_MAKER_FEE_RATE": "0.0002",
    "PAPER_MAKER_FILL_PROB": "0.72",
    "PAPER_MAKER_FALLBACK_TAKER": "0",
    "TRADE_FEE_RATE": "0.0006",
    "PAPER_AUTO_CLOSE_POLICY": "profit_or_hard",
    "PAPER_AUTO_CLOSE_MIN_PROFIT": "0.020",
    "PAPER_AUTO_CLOSE_SEC": "30",
    "PAPER_AUTO_CLOSE_HARD_SEC": "60",
    "PAPER_AUTO_CLOSE_NEAR_ZERO_USDT": "0.01",
    "PAPER_AUTO_CLOSE_MAX_LOSS": "0.05",
    "PAPER_AUTO_CLOSE_LOSS_CAP_ALWAYS": "1",
    "PAPER_RUN_ONCE": "0",
    "PAPER_FORCE_CLOSE_ON_EXIT": "0",
    "ENTRY_CUTOFF_BEFORE_END_SEC": "0",
    "ENTRY_PROFIT_GATE_ENABLE": "1",
    "ENTRY_MIN_EDGE_OVER_FEE_USDT": "0.0015",
    "ENTRY_MIN_EXPECTED_EDGE_AFTER_FEE": "0.0000",
    "ENTRY_EDGE_FEE_WINDOW": "6",
    "ENTRY_EDGE_FEE_MIN_TRADES": "3",
    "ENTRY_STRATEGY_BLOCKLIST": "Momentum",
    "ENTRY_SIDE_OVERRIDE": "",
    "ENTRY_INVERT_SIGNAL": "0",
    "OPPOSITE_SIGNAL_MIN_VOTES": "2",
    "OPPOSITE_SIGNAL_SCORE": "0.40",
    "OPPOSITE_SIGNAL_MIN_HOLD_SEC": "20",
    "EXIT_MIN_HOLD_SEC": "20",
    "EXIT_CLOSE_ATTEMPT_COOLDOWN_SEC": "60",
    "EXIT_CLOSE_ATTEMPT_FEE_GUARD_COOLDOWN_SEC": "300",
    "EXIT_LAYERED_SELECTION_ENABLE": "1",
    "EXIT_TIME_MIN_EXPECTED_NET": "0.0000",
    "ROUTER_MIN_LEAD": "0.0",
    "TF_TREND_ENTRY_FILTER_ENABLE": "0",
    "TF_TREND_SOFT_DIAGNOSTICS_ENABLE": "1",
    "ENTRY_REALIZED_QUALITY_SOFT_ENABLE": "0",
    "ENTRY_REALIZED_QUALITY_MIN_TRADES": "8",
    "ENTRY_REALIZED_QUALITY_MIN_SUM_NET": "0.0",
    "ENTRY_REALIZED_QUALITY_MIN_GROSS_FEE_RATIO": "1.0",
    "HARD_CLOSE_MISSED_ECON_AUDIT_ENABLE": "1",
    "PAPER_V2_DEBUG_DUMP": "0",
}

CASE_ENVS = {
    CASE_BASELINE: {
        "ENTRY_SIDE_OVERRIDE": "",
        "ENTRY_STRATEGY_BLOCKLIST": "Momentum",
        "ENTRY_REALIZED_QUALITY_SOFT_ENABLE": "0",
        "ENTRY_REALIZED_QUALITY_MIN_TRADES": "8",
        "ENTRY_REALIZED_QUALITY_MIN_SUM_NET": "0.0",
        "ENTRY_REALIZED_QUALITY_MIN_GROSS_FEE_RATIO": "1.0",
        "HARD_CLOSE_MISSED_ECON_AUDIT_ENABLE": "1",
    },
    CASE_PATCH: {
        "ENTRY_SIDE_OVERRIDE": "",
        "ENTRY_STRATEGY_BLOCKLIST": "Momentum",
        "ENTRY_REALIZED_QUALITY_SOFT_ENABLE": "1",
        "ENTRY_REALIZED_QUALITY_MIN_TRADES": "3",
        "ENTRY_REALIZED_QUALITY_MIN_SUM_NET": "0.0",
        "ENTRY_REALIZED_QUALITY_MIN_GROSS_FEE_RATIO": "1.0",
        "HARD_CLOSE_MISSED_ECON_AUDIT_ENABLE": "1",
    },
}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
        if not math.isfinite(out):
            return None
        return out
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _load_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, str):
            data = json.loads(data)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def _seconds_between(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    try:
        return max(0.0, (end - start).total_seconds())
    except Exception:
        return None


def _mean(values: list[float | None]) -> float | None:
    vals = [float(v) for v in values if isinstance(v, (int, float))]
    if not vals:
        return None
    return float(sum(vals)) / float(len(vals))


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y"):
        return True
    if text in ("0", "false", "no", "n"):
        return False
    return None


def _quantile(values: list[float | None], q: float) -> float | None:
    vals = sorted(float(v) for v in values if isinstance(v, (int, float)))
    if not vals:
        return None
    if len(vals) == 1:
        return float(vals[0])
    q = max(0.0, min(1.0, float(q)))
    pos = (len(vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(vals[lo])
    frac = pos - lo
    return float(vals[lo] * (1.0 - frac) + vals[hi] * frac)


def _normalize_side(raw: Any) -> str:
    side = str(raw or "").strip().lower()
    if side in ("buy", "long"):
        return "long"
    if side in ("sell", "short"):
        return "short"
    return "unknown"


def _normalize_regime(raw: Any) -> str:
    val = str(raw or "").strip().lower()
    return val if val else "unknown"


def _normalize_strategy(raw: Any) -> str:
    val = str(raw or "").strip()
    return val if val else "unknown"


def _arrival_to_fill_bps_open(
    side: str, arrival_mid: float | None, fill_price: float | None
) -> float | None:
    if arrival_mid is None or fill_price is None or arrival_mid == 0:
        return None
    if side == "long":
        return (float(fill_price) - float(arrival_mid)) / float(arrival_mid) * 10000.0
    if side == "short":
        return (float(arrival_mid) - float(fill_price)) / float(arrival_mid) * 10000.0
    return None


def _markout_bps(
    side: str, entry_ref: float | None, mark_price: float | None
) -> float | None:
    if entry_ref is None or mark_price is None or entry_ref == 0:
        return None
    if side == "long":
        return (float(mark_price) - float(entry_ref)) / float(entry_ref) * 10000.0
    if side == "short":
        return (float(entry_ref) - float(mark_price)) / float(entry_ref) * 10000.0
    return None


def _sum_nonnull(values: list[float | None]) -> float:
    return float(sum(float(v) for v in values if isinstance(v, (int, float))))


def _counter_to_dict(counter_obj: Counter) -> dict[str, int]:
    return {str(k): int(v) for k, v in counter_obj.items()}


def _pnl_concentration_top_5pct(net_values: list[float]) -> float | None:
    if not net_values:
        return None
    positives = sorted([v for v in net_values if v > 0.0], reverse=True)
    if not positives:
        return 0.0
    top_n = max(1, int(math.ceil(len(net_values) * 0.05)))
    top_sum = float(sum(positives[:top_n]))
    total_pos = float(sum(positives))
    if total_pos <= 0:
        return None
    return top_sum / total_pos


def _tail_loss_share(net_values: list[float]) -> float | None:
    losses = sorted([v for v in net_values if v < 0.0])
    if not losses:
        return 0.0
    worst_n = max(1, int(math.ceil(len(net_values) * 0.05)))
    tail_sum_abs = abs(float(sum(losses[:worst_n])))
    total_loss_abs = abs(float(sum(losses)))
    if total_loss_abs <= 0:
        return None
    return tail_sum_abs / total_loss_abs


def _group_summary(
    records: list[dict[str, Any]], field: str
) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        key_raw = rec.get(field)
        key = str(key_raw if key_raw not in (None, "") else "unknown")
        buckets[key].append(rec)
    out = {}
    for key, rows in buckets.items():
        net_vals = [r.get("net_pnl") for r in rows]
        gross_vals = [r.get("gross_fill_pnl_model") for r in rows]
        fee_vals = [r.get("fee_total") for r in rows]
        total_cost_vals = [r.get("total_cost") for r in rows]
        turnover_vals = [r.get("notional_turnover") for r in rows]
        sum_net = _sum_nonnull(net_vals)
        sum_gross = _sum_nonnull(gross_vals)
        sum_fee = _sum_nonnull(fee_vals)
        sum_total_cost = _sum_nonnull(total_cost_vals)
        sum_turnover = _sum_nonnull(turnover_vals)
        out[key] = {
            "trade_count": int(len(rows)),
            "sum_net_pnl": sum_net,
            "mean_net_pnl_per_trade": _mean(net_vals),
            "median_net_pnl_per_trade": _quantile(net_vals, 0.50),
            "win_rate": _mean(
                [
                    1.0 if isinstance(v, (int, float)) and v > 0 else 0.0
                    for v in net_vals
                ]
            ),
            "sum_gross_fill_pnl_model": sum_gross,
            "sum_fee_total": sum_fee,
            "gross_fee_ratio": (
                (sum_gross / sum_fee)
                if isinstance(sum_fee, (int, float)) and sum_fee > 0
                else None
            ),
            "sum_total_cost": sum_total_cost,
            "gross_total_cost_ratio": (
                (sum_gross / sum_total_cost)
                if isinstance(sum_total_cost, (int, float)) and sum_total_cost > 0
                else None
            ),
            "net_per_notional": (
                (sum_net / sum_turnover)
                if isinstance(sum_turnover, (int, float)) and sum_turnover > 0
                else None
            ),
        }
    return out


def _build_coverage_gate(close_records: list[dict[str, Any]]) -> dict[str, Any]:
    closes = len(close_records)
    hard_rows = [r for r in close_records if r.get("is_hard_close")]
    hard_closes = len(hard_rows)
    pre_all_nonnull = sum(
        1
        for row in close_records
        if row.get("pre_hard_close_best_feasible_net") is not None
    )
    cap_all_nonnull = sum(
        1 for row in close_records if row.get("capture_ratio_proxy") is not None
    )
    pre_hard_nonnull = sum(
        1
        for row in hard_rows
        if row.get("pre_hard_close_best_feasible_net") is not None
    )
    cap_hard_nonnull = sum(
        1 for row in hard_rows if row.get("capture_ratio_proxy") is not None
    )
    direct_close_mfe_count = sum(
        1
        for row in close_records
        if row.get("mfe_mae_source") == "position_close_direct"
    )
    pre_all_share = (pre_all_nonnull / closes) if closes else None
    cap_all_share = (cap_all_nonnull / closes) if closes else None
    pre_hard_share = (pre_hard_nonnull / hard_closes) if hard_closes else None
    cap_hard_share = (cap_hard_nonnull / hard_closes) if hard_closes else None
    direct_close_mfe_share = direct_close_mfe_count / closes if closes else None
    checks = {
        "pre_hard_close_best_feasible_net_hard_share_ge_min": (
            None
            if hard_closes == 0
            else bool(
                pre_hard_share is not None and pre_hard_share >= COVERAGE_GATE_MIN_SHARE
            )
        ),
        "capture_ratio_proxy_all_share_ge_min": (
            None
            if closes == 0
            else bool(
                cap_all_share is not None and cap_all_share >= COVERAGE_GATE_MIN_SHARE
            )
        ),
        "direct_position_close_mfe_source_share_ge_min": (
            None
            if closes == 0
            else bool(
                direct_close_mfe_share is not None
                and direct_close_mfe_share >= DIRECT_CLOSE_MFE_MIN_SHARE
            )
        ),
    }
    relevant_checks = [value for value in checks.values() if isinstance(value, bool)]
    if closes == 0:
        status = "insufficient_data"
        gate_pass = False
    elif relevant_checks and all(relevant_checks):
        status = "pass"
        gate_pass = True
    else:
        status = "fail"
        gate_pass = False
    return {
        "status": status,
        "gate_pass": gate_pass,
        "thresholds": {
            "coverage_min_share": COVERAGE_GATE_MIN_SHARE,
            "direct_close_mfe_min_share": DIRECT_CLOSE_MFE_MIN_SHARE,
        },
        "closes": int(closes),
        "hard_closes": int(hard_closes),
        "pre_hard_close_best_feasible_net_nonnull": int(pre_all_nonnull),
        "pre_hard_close_best_feasible_net_share_all": pre_all_share,
        "pre_hard_close_best_feasible_net_nonnull_hard": int(pre_hard_nonnull),
        "pre_hard_close_best_feasible_net_share_hard": pre_hard_share,
        "capture_ratio_proxy_nonnull": int(cap_all_nonnull),
        "capture_ratio_proxy_share_all": cap_all_share,
        "capture_ratio_proxy_nonnull_hard": int(cap_hard_nonnull),
        "capture_ratio_proxy_share_hard": cap_hard_share,
        "direct_position_close_mfe_source_count": int(direct_close_mfe_count),
        "direct_position_close_mfe_source_share": direct_close_mfe_share,
        "checks": checks,
    }


@dataclass
class RunArtifacts:
    case_name: str
    seed: int
    env: dict[str, str]
    db_path: str
    runner_json_path: str
    fee_json_path: str
    stdout_log_path: str
    stderr_log_path: str


def _run_case_seed(case_name: str, seed: int) -> RunArtifacts:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    case_slug = case_name.lower()
    db_name = f"paper_profitability_audit_{case_slug}_seed{seed}_{stamp}.db"
    db_path = PROJECT / db_name
    runner_json = (
        AUTOPSY
        / f"profitability_audit_{case_slug}_seed{seed}_{stamp}_paper_v2_results.json"
    )
    fee_json = (
        AUTOPSY / f"profitability_audit_{case_slug}_seed{seed}_{stamp}_fee_sanity.json"
    )
    stdout_log = AUTOPSY / f"profitability_audit_{case_slug}_seed{seed}_{stamp}.out.log"
    stderr_log = AUTOPSY / f"profitability_audit_{case_slug}_seed{seed}_{stamp}.err.log"

    for p in (db_path, runner_json, fee_json, stdout_log, stderr_log):
        if p.exists():
            p.unlink()

    env = os.environ.copy()
    env.update(BASE_ENV)
    env.update(CASE_ENVS.get(case_name) or {})
    env["AB_RANDOM_SEED"] = str(int(seed))
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    print(f"[RUN] case={case_name} seed={seed} db={db_name}", flush=True)
    proc = subprocess.run(
        [sys.executable, str(RUNNER)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60 * 120,
        check=False,
    )
    stdout_log.write_text(proc.stdout or "", encoding="utf-8")
    stderr_log.write_text(proc.stderr or "", encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(
            f"run_11_paper_v2 failed: case={case_name} seed={seed}; see {stderr_log}"
        )
    if not db_path.exists():
        raise RuntimeError(f"missing DB for case={case_name} seed={seed}: {db_path}")
    if not RUNNER_RESULT_JSON.exists():
        raise RuntimeError(f"missing runner JSON after case={case_name} seed={seed}")

    shutil.copyfile(RUNNER_RESULT_JSON, runner_json)

    fee_proc = subprocess.run(
        [
            sys.executable,
            str(FEE_REPORTER),
            "--db",
            str(db_path),
            "--out-json",
            str(fee_json),
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60 * 10,
        check=False,
    )
    if fee_proc.returncode != 0:
        raise RuntimeError(
            f"report_fee_sanity failed: case={case_name} seed={seed}; see {stderr_log}"
        )

    env_effective = dict(BASE_ENV)
    env_effective.update(CASE_ENVS.get(case_name) or {})
    env_effective["AB_RANDOM_SEED"] = str(int(seed))
    env_effective["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    return RunArtifacts(
        case_name=case_name,
        seed=int(seed),
        env=env_effective,
        db_path=str(db_path.resolve()),
        runner_json_path=str(runner_json.resolve()),
        fee_json_path=str(fee_json.resolve()),
        stdout_log_path=str(stdout_log.resolve()),
        stderr_log_path=str(stderr_log.resolve()),
    )


def _extract_run_metrics(db_path: Path) -> dict[str, Any]:
    events = (
        "position_open",
        "position_mark",
        "position_close",
        "close_execute_enter",
        "close_execute_exit",
        "close_candidates_evaluated",
        "tf_trend_entry_eval",
        "tf_trend_entry_filtered",
        "tf_trend_entry_soft_score",
        "entry_quality_passed",
        "entry_realized_quality_penalty",
        "hard_close_missed_economic_exit",
        "entry_runtime_isolation_policy",
        "entry_quality_bucket_open",
        "entry_quality_bucket_close",
        "order_simulated_unfilled",
        "realized_outcome_per_symbol",
        "realized_outcome_per_regime",
        "realized_outcome_per_strategy",
        "realized_outcome_per_side",
    )
    sql_event_list = ",".join(f"'{e}'" for e in events)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    log_rows = cur.execute(
        f"SELECT id, timestamp, event, details FROM logs WHERE event IN ({sql_event_list}) ORDER BY id"
    ).fetchall()
    try:
        decisions = cur.execute("SELECT details FROM decisions ORDER BY id").fetchall()
    except Exception:
        decisions = []
    conn.close()

    telemetry_counts = Counter()
    close_reason_breakdown = Counter()
    selected_reason_breakdown = Counter()
    missed_exit_reason_bucket = Counter()
    open_by_trade: dict[str, dict[str, Any]] = {}
    marks_by_trade: dict[str, list[dict[str, Any]]] = defaultdict(list)
    candidate_by_trade: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "events": 0,
            "selected_reason_last": None,
            "selected_expected_last": None,
            "economic_candidate_seen": False,
            "economic_feasible_positive": False,
            "best_economic_feasible_net": None,
        }
    )
    hard_audit_by_trade: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "event_count": 0,
            "positive_within_40": False,
            "positive_within_20_40": False,
            "max_positive_expected_net": None,
        }
    )
    runtime_isolation_bucket_status: dict[str, str] = {}
    runtime_isolation_status_counts = Counter()
    close_records: list[dict[str, Any]] = []
    close_execute_enter = 0
    close_execute_exit_success = 0
    close_execute_exit_mismatch_count = 0
    entry_count_total = 0

    for (raw_decision,) in decisions:
        payload = _load_json(raw_decision)
        decision_raw = str(payload.get("entry_decision_raw") or "").strip().lower()
        if decision_raw in ("buy", "sell"):
            entry_count_total += 1

    for log_id, log_ts_raw, event, raw in log_rows:
        payload = _load_json(raw)
        log_ts = _parse_dt(log_ts_raw)
        telemetry_counts[event] += 1
        if event == "position_open":
            pos = (
                payload.get("position")
                if isinstance(payload.get("position"), dict)
                else {}
            )
            trade_id = payload.get("trade_id") or pos.get("trade_id")
            if trade_id in (None, ""):
                continue
            trade_key = str(trade_id)
            open_snapshot = (
                pos.get("open_snapshot")
                if isinstance(pos.get("open_snapshot"), dict)
                else {}
            )
            open_by_trade[trade_key] = {
                "symbol": payload.get("symbol") or pos.get("symbol"),
                "entry_ts": _parse_dt(pos.get("timestamp")) or log_ts,
                "entry_fill_price": _safe_float(
                    pos.get("fill_price") or pos.get("entry_price")
                ),
                "open_mid": _safe_float(open_snapshot.get("mid")),
                "side": _normalize_side(pos.get("side") or pos.get("position_side")),
                "regime": _normalize_regime(pos.get("entry_regime")),
                "strategy": _normalize_strategy(
                    pos.get("entry_main_strategy") or pos.get("strategy")
                ),
            }
        elif event == "position_mark":
            pos = (
                payload.get("position")
                if isinstance(payload.get("position"), dict)
                else {}
            )
            trade_id = pos.get("trade_id")
            if trade_id in (None, ""):
                continue
            marks_by_trade[str(trade_id)].append(
                {
                    "ts": _parse_dt(log_ts_raw)
                    or _parse_dt(payload.get("timestamp"))
                    or log_ts,
                    "mark_price": _safe_float(payload.get("mark_price")),
                    "unrealized_pnl": _safe_float(payload.get("unrealized_pnl")),
                }
            )
        elif event == "close_candidates_evaluated":
            trade_id = payload.get("trade_id")
            if trade_id in (None, ""):
                continue
            trade_key = str(trade_id)
            st = candidate_by_trade[trade_key]
            st["events"] = int(st.get("events") or 0) + 1
            selected_reason = payload.get("selected_reason")
            selected_expected = _safe_float(
                payload.get("selected_expected_net_after_fee")
            )
            if selected_reason not in (None, ""):
                st["selected_reason_last"] = str(selected_reason)
                selected_reason_breakdown[str(selected_reason)] += 1
            st["selected_expected_last"] = selected_expected
            candidates = payload.get("candidates")
            if not isinstance(candidates, list):
                candidates = []
            for cand in candidates:
                if not isinstance(cand, dict):
                    continue
                reason = str(cand.get("reason") or "")
                if reason not in ECONOMIC_TIME_REASONS:
                    continue
                st["economic_candidate_seen"] = True
                expected_net = _safe_float(cand.get("expected_net_after_fee"))
                allowed = bool(cand.get("allowed"))
                if allowed and expected_net is not None and expected_net > 0.0:
                    st["economic_feasible_positive"] = True
                    best = _safe_float(st.get("best_economic_feasible_net"))
                    if best is None or expected_net > best:
                        st["best_economic_feasible_net"] = float(expected_net)
        elif event == "close_execute_enter":
            close_execute_enter += 1
        elif event == "close_execute_exit":
            result = str(payload.get("result") or "").strip().lower()
            if result == "success":
                close_execute_exit_success += 1
            close_reason = str(payload.get("reason") or "")
            if close_reason in (None, "", "unknown", "null"):
                close_execute_exit_mismatch_count += 1
        elif event == "hard_close_missed_economic_exit":
            trade_id = payload.get("trade_id")
            if trade_id in (None, ""):
                continue
            trade_key = str(trade_id)
            st = hard_audit_by_trade[trade_key]
            st["event_count"] = int(st.get("event_count") or 0) + 1
            st["positive_within_40"] = bool(
                st.get("positive_within_40")
                or bool(payload.get("positive_time_candidate_within_40_sec"))
            )
            st["positive_within_20_40"] = bool(
                st.get("positive_within_20_40")
                or bool(payload.get("positive_time_candidate_within_20_40_sec"))
            )
            for probe_key in ("time_economics_probe", "time_fee_floor_probe"):
                probe = payload.get(probe_key)
                if not isinstance(probe, dict):
                    continue
                expected_net = _safe_float(probe.get("expected_net_after_fee"))
                if expected_net is None or expected_net <= 0:
                    continue
                best = _safe_float(st.get("max_positive_expected_net"))
                if best is None or expected_net > best:
                    st["max_positive_expected_net"] = float(expected_net)
        elif event == "entry_runtime_isolation_policy":
            runtime_policy = (
                payload.get("runtime_policy")
                if isinstance(payload.get("runtime_policy"), dict)
                else {}
            )
            key_obj = (
                runtime_policy.get("key") if isinstance(runtime_policy, dict) else {}
            )
            if not isinstance(key_obj, dict):
                key_obj = {}
            symbol_key = (
                str(key_obj.get("symbol") or payload.get("symbol") or "unknown")
                .strip()
                .upper()
                or "UNKNOWN"
            )
            regime_key = _normalize_regime(
                key_obj.get("regime") or payload.get("regime")
            )
            strategy_key = _normalize_strategy(
                key_obj.get("strategy") or payload.get("main_strategy")
            )
            side_key = _normalize_side(
                key_obj.get("side") or payload.get("entry_decision_raw")
            )
            bucket_key = f"{symbol_key}|{regime_key}|{strategy_key}|{side_key}"
            status = (
                str(
                    runtime_policy.get("policy_status")
                    or payload.get("runtime_policy_status")
                    or "ALLOWED"
                )
                .strip()
                .upper()
                or "ALLOWED"
            )
            runtime_isolation_bucket_status[bucket_key] = status
            runtime_isolation_status_counts[status] += 1
        elif event == "position_close":
            pos = (
                payload.get("position")
                if isinstance(payload.get("position"), dict)
                else {}
            )
            trade_id = payload.get("trade_id") or pos.get("trade_id")
            trade_key = str(trade_id) if trade_id not in (None, "") else f"row_{log_id}"
            decomp = payload.get("pnl_decompose")
            if not isinstance(decomp, dict):
                decomp = (
                    pos.get("pnl_decompose")
                    if isinstance(pos.get("pnl_decompose"), dict)
                    else {}
                )
            if not isinstance(decomp, dict):
                decomp = {}
            direct_mfe = _safe_float(payload.get("mfe"))
            if direct_mfe is None:
                direct_mfe = _safe_float(pos.get("mfe"))
            if direct_mfe is None:
                direct_mfe = _safe_float(pos.get("max_unrealized_pnl"))
            direct_mae = _safe_float(payload.get("mae"))
            if direct_mae is None:
                direct_mae = _safe_float(pos.get("mae"))
            if direct_mae is None:
                direct_mae = _safe_float(pos.get("min_unrealized_pnl"))
            direct_pre_hard_close_best_feasible_net = _safe_float(
                payload.get("pre_hard_close_best_feasible_net")
            )
            if direct_pre_hard_close_best_feasible_net is None:
                direct_pre_hard_close_best_feasible_net = _safe_float(
                    payload.get("pre_hard_close_feasible_net")
                )
            if direct_pre_hard_close_best_feasible_net is None:
                direct_pre_hard_close_best_feasible_net = _safe_float(
                    pos.get("pre_hard_close_best_feasible_net")
                )
            if direct_pre_hard_close_best_feasible_net is None:
                direct_pre_hard_close_best_feasible_net = _safe_float(
                    pos.get("pre_hard_close_feasible_net")
                )
            direct_economic_exit_feasible = _coerce_optional_bool(
                payload.get("economic_exit_feasible")
            )
            if direct_economic_exit_feasible is None:
                direct_economic_exit_feasible = _coerce_optional_bool(
                    pos.get("economic_exit_feasible")
                )
            direct_economic_exit_captured = _coerce_optional_bool(
                payload.get("economic_exit_captured")
            )
            if direct_economic_exit_captured is None:
                direct_economic_exit_captured = _coerce_optional_bool(
                    pos.get("economic_exit_captured")
                )
            direct_capture_ratio_proxy = _safe_float(payload.get("capture_ratio_proxy"))
            if direct_capture_ratio_proxy is None:
                direct_capture_ratio_proxy = _safe_float(pos.get("capture_ratio_proxy"))
            direct_hard_close_positive40 = _coerce_optional_bool(
                payload.get("hard_close_missed_event_positive_within_40")
            )
            if direct_hard_close_positive40 is None:
                direct_hard_close_positive40 = _coerce_optional_bool(
                    pos.get("hard_close_missed_event_positive_within_40")
                )

            open_info = open_by_trade.get(trade_key, {})
            open_snapshot = (
                pos.get("open_snapshot")
                if isinstance(pos.get("open_snapshot"), dict)
                else {}
            )
            close_snapshot = payload.get("close_snapshot")
            if not isinstance(close_snapshot, dict):
                close_snapshot = (
                    pos.get("close_snapshot")
                    if isinstance(pos.get("close_snapshot"), dict)
                    else {}
                )

            side = _normalize_side(
                pos.get("side") or pos.get("position_side") or open_info.get("side")
            )
            symbol = str(
                payload.get("symbol")
                or pos.get("symbol")
                or open_info.get("symbol")
                or "unknown"
            )
            regime = _normalize_regime(
                pos.get("entry_regime") or open_info.get("regime")
            )
            strategy = _normalize_strategy(
                pos.get("entry_main_strategy")
                or pos.get("strategy")
                or open_info.get("strategy")
            )
            exit_reason = str(
                payload.get("exit_reason")
                or payload.get("reason")
                or pos.get("exit_reason")
                or "unknown"
            )
            close_reason = str(
                payload.get("close_reason") or pos.get("close_reason") or exit_reason
            )
            close_reason_breakdown[exit_reason] += 1

            entry_fill = _safe_float(
                pos.get("fill_price")
                or pos.get("entry_price")
                or open_info.get("entry_fill_price")
            )
            close_fill = _safe_float(
                pos.get("close_fill_price")
                or payload.get("close_price")
                or pos.get("close_price")
            )
            amount_abs = abs(_safe_float(pos.get("amount")) or 0.0)
            notional_open = (
                float(entry_fill) * float(amount_abs)
                if entry_fill is not None and amount_abs > 0
                else None
            )
            notional_close = (
                float(close_fill) * float(amount_abs)
                if close_fill is not None and amount_abs > 0
                else None
            )
            notional_turnover = None
            if notional_open is not None and notional_close is not None:
                notional_turnover = float(notional_open) + float(notional_close)
            elif notional_open is not None:
                notional_turnover = float(notional_open)
            elif notional_close is not None:
                notional_turnover = float(notional_close)

            open_mid = _safe_float(open_snapshot.get("mid"))
            if open_mid is None:
                open_mid = _safe_float(open_info.get("open_mid"))
            close_mid = _safe_float(close_snapshot.get("mid"))
            net_pnl = _safe_float(decomp.get("net_pnl"))
            if net_pnl is None:
                net_pnl = _safe_float(payload.get("realized_pnl"))
            gross_fill_pnl_model = _safe_float(decomp.get("gross_fill_pnl_model"))
            fee_total = _safe_float(decomp.get("fee_total"))
            spread_cost = _safe_float(decomp.get("spread_cost"))
            slippage_cost = _safe_float(decomp.get("slippage_cost"))
            slippage_signed = _safe_float(decomp.get("slippage_signed"))
            funding_total = _safe_float(decomp.get("funding_total"))
            funding_cost_component = (
                max(0.0, float(funding_total))
                if isinstance(funding_total, (int, float))
                else 0.0
            )
            total_cost = (
                (fee_total if fee_total is not None else 0.0)
                + (spread_cost if spread_cost is not None else 0.0)
                + (slippage_cost if slippage_cost is not None else 0.0)
                + funding_cost_component
            )

            entry_ts = _parse_dt(pos.get("timestamp")) or open_info.get("entry_ts")
            close_ts = _parse_dt(pos.get("close_timestamp")) or log_ts
            trade_duration = _seconds_between(entry_ts, close_ts)
            net_per_notional = None
            if (
                net_pnl is not None
                and notional_turnover is not None
                and notional_turnover > 0
            ):
                net_per_notional = float(net_pnl) / float(notional_turnover)

            arrival_to_fill_bps = _arrival_to_fill_bps_open(side, open_mid, entry_fill)
            signed_slippage_bps = None
            if (
                slippage_signed is not None
                and notional_turnover is not None
                and notional_turnover > 0
            ):
                signed_slippage_bps = (
                    float(slippage_signed) / float(notional_turnover) * 10000.0
                )

            marks = sorted(
                marks_by_trade.get(trade_key, []),
                key=lambda x: x.get("ts") or datetime.now(timezone.utc),
            )
            if direct_mfe is not None or direct_mae is not None:
                mfe = direct_mfe
                mae = direct_mae
                mfe_mae_source = "position_close_direct"
            else:
                unrealized_samples = [
                    _safe_float(m.get("unrealized_pnl"))
                    for m in marks
                    if _safe_float(m.get("unrealized_pnl")) is not None
                ]
                mfe = max(unrealized_samples) if unrealized_samples else None
                mae = min(unrealized_samples) if unrealized_samples else None
                mfe_mae_source = (
                    "position_mark_fallback" if unrealized_samples else "unavailable"
                )

            entry_ref_for_markout = open_mid if open_mid is not None else entry_fill
            markout_1 = None
            markout_5 = None
            markout_60 = None
            if entry_ts is not None and entry_ref_for_markout is not None:
                for threshold_sec, target in (
                    (1.0, "markout_1"),
                    (5.0, "markout_5"),
                    (60.0, "markout_60"),
                ):
                    hit = None
                    for sample in marks:
                        sample_ts = sample.get("ts")
                        if sample_ts is None:
                            continue
                        age = _seconds_between(entry_ts, sample_ts)
                        if age is not None and age >= threshold_sec:
                            hit = _safe_float(sample.get("mark_price"))
                            break
                    val = _markout_bps(side, entry_ref_for_markout, hit)
                    if target == "markout_1":
                        markout_1 = val
                    elif target == "markout_5":
                        markout_5 = val
                    else:
                        markout_60 = val

            candidate_state = candidate_by_trade.get(trade_key) or {}
            hard_audit_state = hard_audit_by_trade.get(trade_key) or {}
            best_economic_feasible_net = direct_pre_hard_close_best_feasible_net
            if best_economic_feasible_net is None:
                best_economic_feasible_net = _safe_float(
                    candidate_state.get("best_economic_feasible_net")
                )
            if best_economic_feasible_net is None:
                best_economic_feasible_net = _safe_float(
                    hard_audit_state.get("max_positive_expected_net")
                )
            economic_feasible = direct_economic_exit_feasible
            if economic_feasible is None:
                economic_feasible = bool(
                    candidate_state.get("economic_feasible_positive")
                )
                if (
                    not economic_feasible
                    and best_economic_feasible_net is not None
                    and best_economic_feasible_net > 0.0
                ):
                    economic_feasible = True
            economic_captured = direct_economic_exit_captured
            if economic_captured is None:
                economic_captured = bool(
                    exit_reason in ECONOMIC_TIME_REASONS and economic_feasible
                )

            is_hard = exit_reason in HARD_REASONS
            hard_audit_positive40 = (
                bool(direct_hard_close_positive40)
                if direct_hard_close_positive40 is not None
                else bool(hard_audit_state.get("positive_within_40"))
            )
            capture_ratio_proxy = direct_capture_ratio_proxy
            if capture_ratio_proxy is None:
                if (
                    net_pnl is not None
                    and best_economic_feasible_net is not None
                    and best_economic_feasible_net > 0.0
                ):
                    capture_ratio_proxy = float(net_pnl) / float(
                        best_economic_feasible_net
                    )
                elif net_pnl is not None and mfe is not None and mfe > 0.0:
                    capture_ratio_proxy = float(net_pnl) / float(mfe)
            if is_hard:
                if (
                    best_economic_feasible_net is not None
                    and best_economic_feasible_net > 0
                ):
                    missed_exit_reason_bucket[
                        "hard_selected_despite_positive_economic_candidate"
                    ] += 1
                elif hard_audit_positive40:
                    missed_exit_reason_bucket[
                        "hard_close_missed_event_positive_within_40"
                    ] += 1
                elif candidate_state.get("economic_candidate_seen"):
                    missed_exit_reason_bucket[
                        "economic_candidate_seen_but_nonpositive"
                    ] += 1
                else:
                    missed_exit_reason_bucket["no_economic_candidate_seen"] += 1

            close_records.append(
                {
                    "log_id": int(log_id),
                    "trade_id": trade_key,
                    "symbol": symbol,
                    "regime": regime,
                    "strategy": strategy,
                    "side": side,
                    "entry_ts": (
                        entry_ts.isoformat() if isinstance(entry_ts, datetime) else None
                    ),
                    "close_ts": (
                        close_ts.isoformat() if isinstance(close_ts, datetime) else None
                    ),
                    "trade_duration_sec": trade_duration,
                    "mfe": mfe,
                    "mae": mae,
                    "mfe_mae_source": mfe_mae_source,
                    "exit_reason": exit_reason,
                    "close_reason": close_reason,
                    "mismatch_close_exit_reason": bool(close_reason != exit_reason),
                    "is_hard_close": bool(is_hard),
                    "net_pnl": net_pnl,
                    "gross_fill_pnl_model": gross_fill_pnl_model,
                    "gross_mid_pnl": _safe_float(decomp.get("gross_mid_pnl")),
                    "fee_total": fee_total,
                    "spread_cost": spread_cost,
                    "slippage_cost": slippage_cost,
                    "slippage_signed": slippage_signed,
                    "funding_total": funding_total,
                    "total_cost": total_cost,
                    "notional_open": notional_open,
                    "notional_close": notional_close,
                    "notional_turnover": notional_turnover,
                    "net_per_notional": net_per_notional,
                    "open_mid": open_mid,
                    "close_mid": close_mid,
                    "entry_fill_price": entry_fill,
                    "close_fill_price": close_fill,
                    "arrival_to_fill_bps_open": arrival_to_fill_bps,
                    "signed_slippage_bps": signed_slippage_bps,
                    "markout_1_bps": markout_1,
                    "markout_5_bps": markout_5,
                    "markout_60_bps": markout_60,
                    "economic_exit_feasible": economic_feasible,
                    "economic_exit_captured": economic_captured,
                    "pre_hard_close_best_feasible_net": best_economic_feasible_net,
                    "capture_ratio_proxy": capture_ratio_proxy,
                    "hard_close_missed_event_positive_within_40": hard_audit_positive40,
                }
            )

    closes = len(close_records)
    net_vals = [r.get("net_pnl") for r in close_records]
    gross_vals = [r.get("gross_fill_pnl_model") for r in close_records]
    fee_vals = [r.get("fee_total") for r in close_records]
    spread_vals = [r.get("spread_cost") for r in close_records]
    slip_vals = [r.get("slippage_cost") for r in close_records]
    funding_vals = [r.get("funding_total") for r in close_records]
    total_cost_vals = [r.get("total_cost") for r in close_records]
    turnover_vals = [r.get("notional_turnover") for r in close_records]
    hard_rows = [r for r in close_records if r.get("is_hard_close")]
    econ_rows = [
        r for r in close_records if r.get("exit_reason") in ECONOMIC_TIME_REASONS
    ]
    long_rows = [r for r in close_records if r.get("side") == "long"]
    short_rows = [r for r in close_records if r.get("side") == "short"]

    sum_net = _sum_nonnull(net_vals)
    sum_gross = _sum_nonnull(gross_vals)
    sum_fee = _sum_nonnull(fee_vals)
    sum_total_cost = _sum_nonnull(total_cost_vals)
    sum_turnover = _sum_nonnull(turnover_vals)
    hard_count = len(hard_rows)
    mismatch_count = sum(
        1 for r in close_records if r.get("mismatch_close_exit_reason")
    )
    win_rate = _mean(
        [1.0 if isinstance(v, (int, float)) and v > 0 else 0.0 for v in net_vals]
    )
    loss_rate = _mean(
        [1.0 if isinstance(v, (int, float)) and v < 0 else 0.0 for v in net_vals]
    )
    net_vals_nonnull = [float(v) for v in net_vals if isinstance(v, (int, float))]

    short_cost_metric = [
        (
            float(r.get("total_cost")) / float(r.get("notional_turnover"))
            if isinstance(r.get("total_cost"), (int, float))
            and isinstance(r.get("notional_turnover"), (int, float))
            and float(r.get("notional_turnover")) > 0
            else None
        )
        for r in short_rows
    ]
    short_liq_metric = [
        (
            float(r.get("spread_cost")) / float(r.get("notional_turnover"))
            if isinstance(r.get("spread_cost"), (int, float))
            and isinstance(r.get("notional_turnover"), (int, float))
            and float(r.get("notional_turnover")) > 0
            else None
        )
        for r in short_rows
    ]
    cost_q33 = _quantile(short_cost_metric, 0.33)
    cost_q66 = _quantile(short_cost_metric, 0.66)
    liq_q33 = _quantile(short_liq_metric, 0.33)
    liq_q66 = _quantile(short_liq_metric, 0.66)
    short_pnl_by_cost_bucket = Counter()
    short_pnl_by_liquidity_bucket = Counter()
    for idx, row in enumerate(short_rows):
        net_val = _safe_float(row.get("net_pnl"))
        cval = (
            _safe_float(short_cost_metric[idx])
            if idx < len(short_cost_metric)
            else None
        )
        lval = (
            _safe_float(short_liq_metric[idx]) if idx < len(short_liq_metric) else None
        )
        if cval is None or cost_q33 is None or cost_q66 is None:
            cost_bucket = "unknown"
        elif cval <= cost_q33:
            cost_bucket = "low_cost"
        elif cval <= cost_q66:
            cost_bucket = "mid_cost"
        else:
            cost_bucket = "high_cost"
        if lval is None or liq_q33 is None or liq_q66 is None:
            liq_bucket = "unknown"
        elif lval <= liq_q33:
            liq_bucket = "low_spread"
        elif lval <= liq_q66:
            liq_bucket = "mid_spread"
        else:
            liq_bucket = "high_spread"
        if isinstance(net_val, (int, float)):
            short_pnl_by_cost_bucket[cost_bucket] += float(net_val)
            short_pnl_by_liquidity_bucket[liq_bucket] += float(net_val)

    return {
        "closes": int(closes),
        "trade_count": int(closes),
        "open_count": int(telemetry_counts.get("position_open", 0)),
        "close_count": int(telemetry_counts.get("position_close", 0)),
        "close_execute_enter": int(close_execute_enter),
        "close_execute_exit_success": int(close_execute_exit_success),
        "close_execute_exit_mismatch_count": int(close_execute_exit_mismatch_count),
        "mismatch_count": int(mismatch_count),
        "entry_count_total": int(entry_count_total),
        "entry_quality_passed_count": int(
            telemetry_counts.get("entry_quality_passed", 0)
        ),
        "tf_trend_entry_eval_count": int(
            telemetry_counts.get("tf_trend_entry_eval", 0)
        ),
        "tf_trend_entry_filtered_count": int(
            telemetry_counts.get("tf_trend_entry_filtered", 0)
        ),
        "tf_trend_entry_soft_score_count": int(
            telemetry_counts.get("tf_trend_entry_soft_score", 0)
        ),
        "entry_realized_quality_penalty_count": int(
            telemetry_counts.get("entry_realized_quality_penalty", 0)
        ),
        "hard_close_missed_economic_exit": int(
            telemetry_counts.get("hard_close_missed_economic_exit", 0)
        ),
        "economic_exit_feasible_count": int(
            sum(1 for r in close_records if r.get("economic_exit_feasible"))
        ),
        "economic_exit_captured_count": int(
            sum(1 for r in close_records if r.get("economic_exit_captured"))
        ),
        "hard_close_count": int(hard_count),
        "hard_close_share": (float(hard_count) / float(closes)) if closes > 0 else 0.0,
        "hard_close_net_pnl": _sum_nonnull([r.get("net_pnl") for r in hard_rows]),
        "economic_exit_net_pnl": _sum_nonnull([r.get("net_pnl") for r in econ_rows]),
        "pre_hard_close_best_feasible_net": _mean(
            [r.get("pre_hard_close_best_feasible_net") for r in hard_rows]
        ),
        "mean_capture_ratio_proxy": _mean(
            [r.get("capture_ratio_proxy") for r in close_records]
        ),
        "missed_exit_reason_bucket": _counter_to_dict(missed_exit_reason_bucket),
        "close_reason_breakdown": _counter_to_dict(close_reason_breakdown),
        "selected_reason_breakdown": _counter_to_dict(selected_reason_breakdown),
        "mean_gross_fill_pnl_model": _mean(gross_vals),
        "mean_fee_total": _mean(fee_vals),
        "mean_spread_cost": _mean(spread_vals),
        "mean_slippage_cost": _mean(slip_vals),
        "mean_funding_total": _mean(funding_vals),
        "mean_total_cost": _mean(total_cost_vals),
        "sum_gross_fill_pnl_model": sum_gross,
        "sum_fee_total": sum_fee,
        "sum_total_cost": sum_total_cost,
        "gross_fee_ratio": (sum_gross / sum_fee) if sum_fee > 0 else None,
        "gross_total_cost_ratio": (
            (sum_gross / sum_total_cost) if sum_total_cost > 0 else None
        ),
        "mean_net_pnl_per_trade": _mean(net_vals),
        "median_net_pnl_per_trade": _quantile(net_vals, 0.50),
        "p25_net_pnl_per_trade": _quantile(net_vals, 0.25),
        "p75_net_pnl_per_trade": _quantile(net_vals, 0.75),
        "p05_net_pnl_per_trade": _quantile(net_vals, 0.05),
        "sum_net_pnl": sum_net,
        "net_per_trade": _mean(net_vals),
        "turnover_notional_traded": sum_turnover,
        "net_per_notional": (sum_net / sum_turnover) if sum_turnover > 0 else None,
        "net_gross_ratio": (sum_net / sum_gross) if sum_gross != 0 else None,
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "pnl_concentration_top_5pct_trades": _pnl_concentration_top_5pct(
            net_vals_nonnull
        ),
        "tail_loss_share": _tail_loss_share(net_vals_nonnull),
        "long_count": int(len(long_rows)),
        "short_count": int(len(short_rows)),
        "mean_net_pnl_long": _mean([r.get("net_pnl") for r in long_rows]),
        "mean_net_pnl_short": _mean([r.get("net_pnl") for r in short_rows]),
        "median_net_pnl_long": _quantile([r.get("net_pnl") for r in long_rows], 0.50),
        "median_net_pnl_short": _quantile([r.get("net_pnl") for r in short_rows], 0.50),
        "gross_total_cost_ratio_long": (
            _sum_nonnull([r.get("gross_fill_pnl_model") for r in long_rows])
            / _sum_nonnull([r.get("total_cost") for r in long_rows])
            if _sum_nonnull([r.get("total_cost") for r in long_rows]) > 0
            else None
        ),
        "gross_total_cost_ratio_short": (
            _sum_nonnull([r.get("gross_fill_pnl_model") for r in short_rows])
            / _sum_nonnull([r.get("total_cost") for r in short_rows])
            if _sum_nonnull([r.get("total_cost") for r in short_rows]) > 0
            else None
        ),
        "borrow_or_funding_cost_short": _sum_nonnull(
            [r.get("funding_total") for r in short_rows]
        ),
        "short_pnl_by_cost_bucket": _counter_to_dict(short_pnl_by_cost_bucket),
        "short_pnl_by_liquidity_bucket": _counter_to_dict(
            short_pnl_by_liquidity_bucket
        ),
        "mean_trade_duration_sec": _mean(
            [r.get("trade_duration_sec") for r in close_records]
        ),
        "mean_mfe": _mean([r.get("mfe") for r in close_records]),
        "mean_mae": _mean([r.get("mae") for r in close_records]),
        "arrival_to_fill_bps": _mean(
            [r.get("arrival_to_fill_bps_open") for r in close_records]
        ),
        "signed_slippage_bps": _mean(
            [r.get("signed_slippage_bps") for r in close_records]
        ),
        "fill_to_mid_markout_1": _mean([r.get("markout_1_bps") for r in close_records]),
        "fill_to_mid_markout_5": _mean([r.get("markout_5_bps") for r in close_records]),
        "fill_to_mid_markout_60": _mean(
            [r.get("markout_60_bps") for r in close_records]
        ),
        "execution_side_bias": {
            "arrival_to_fill_bps_long": _mean(
                [r.get("arrival_to_fill_bps_open") for r in long_rows]
            ),
            "arrival_to_fill_bps_short": _mean(
                [r.get("arrival_to_fill_bps_open") for r in short_rows]
            ),
        },
        "coverage_gate": _build_coverage_gate(close_records),
        "entry_runtime_isolation_policy_count": int(
            telemetry_counts.get("entry_runtime_isolation_policy", 0)
        ),
        "runtime_isolation_status_counts": _counter_to_dict(
            runtime_isolation_status_counts
        ),
        "runtime_isolation_bucket_status": dict(runtime_isolation_bucket_status),
        "runtime_isolation_buckets_allowed": sorted(
            [
                k
                for k, v in runtime_isolation_bucket_status.items()
                if str(v).upper() == "ALLOWED"
            ]
        ),
        "runtime_isolation_buckets_degraded": sorted(
            [
                k
                for k, v in runtime_isolation_bucket_status.items()
                if str(v).upper() == "DEGRADED"
            ]
        ),
        "runtime_isolation_buckets_disabled": sorted(
            [
                k
                for k, v in runtime_isolation_bucket_status.items()
                if str(v).upper() == "DISABLED"
            ]
        ),
        "telemetry_counts": {k: int(v) for k, v in telemetry_counts.items()},
        "group_symbol": _group_summary(close_records, "symbol"),
        "group_regime": _group_summary(close_records, "regime"),
        "group_strategy": _group_summary(close_records, "strategy"),
        "group_side": _group_summary(close_records, "side"),
        "unavailable_components": {
            "impact_proxy_cost": {
                "unavailable_component": True,
                "reason": "No L2 order-book depth/queue telemetry per fill in current logs.",
                "fallback_used": "0.0 in total_cost; not a full TCA component.",
            },
            "opportunity_cost_unfilled": {
                "unavailable_component": True,
                "reason": "Unfilled events exist without counterfactual executable price path.",
                "fallback_used": {
                    "order_simulated_unfilled_count": int(
                        telemetry_counts.get("order_simulated_unfilled", 0)
                    )
                },
            },
            "arrival_mid_fill_markouts_precision": {
                "unavailable_component": True,
                "reason": "No guaranteed 1s/5s/60s quote snapshots tied to each fill.",
                "fallback_used": "position_mark-based coarse markouts.",
            },
        },
        "close_records": close_records,
    }


def _extract_run_metrics_from_records(
    close_records: list[dict[str, Any]],
    agg_counts: Counter,
    close_reason: Counter,
    selected_reason: Counter,
    missed_reason: Counter,
) -> dict[str, Any]:
    closes = len(close_records)
    net_vals = [r.get("net_pnl") for r in close_records]
    gross_vals = [r.get("gross_fill_pnl_model") for r in close_records]
    fee_vals = [r.get("fee_total") for r in close_records]
    spread_vals = [r.get("spread_cost") for r in close_records]
    slip_vals = [r.get("slippage_cost") for r in close_records]
    funding_vals = [r.get("funding_total") for r in close_records]
    total_cost_vals = [r.get("total_cost") for r in close_records]
    turnover_vals = [r.get("notional_turnover") for r in close_records]
    hard_rows = [r for r in close_records if r.get("is_hard_close")]
    econ_rows = [
        r for r in close_records if r.get("exit_reason") in ECONOMIC_TIME_REASONS
    ]
    long_rows = [r for r in close_records if r.get("side") == "long"]
    short_rows = [r for r in close_records if r.get("side") == "short"]
    sum_net = _sum_nonnull(net_vals)
    sum_gross = _sum_nonnull(gross_vals)
    sum_fee = _sum_nonnull(fee_vals)
    sum_total_cost = _sum_nonnull(total_cost_vals)
    sum_turnover = _sum_nonnull(turnover_vals)
    hard_count = len(hard_rows)
    mismatch_count = sum(
        1 for r in close_records if r.get("mismatch_close_exit_reason")
    )
    net_vals_nonnull = [float(v) for v in net_vals if isinstance(v, (int, float))]

    return {
        "closes": int(closes),
        "trade_count": int(closes),
        "open_count": int(agg_counts.get("open_count", 0)),
        "close_count": int(agg_counts.get("close_count", 0)),
        "close_execute_enter": int(agg_counts.get("close_execute_enter", 0)),
        "close_execute_exit_success": int(
            agg_counts.get("close_execute_exit_success", 0)
        ),
        "mismatch_count": int(mismatch_count),
        "entry_count_total": int(agg_counts.get("entry_count_total", 0)),
        "entry_quality_passed_count": int(
            agg_counts.get("entry_quality_passed_count", 0)
        ),
        "tf_trend_entry_eval_count": int(
            agg_counts.get("tf_trend_entry_eval_count", 0)
        ),
        "tf_trend_entry_filtered_count": int(
            agg_counts.get("tf_trend_entry_filtered_count", 0)
        ),
        "tf_trend_entry_soft_score_count": int(
            agg_counts.get("tf_trend_entry_soft_score_count", 0)
        ),
        "entry_realized_quality_penalty_count": int(
            agg_counts.get("entry_realized_quality_penalty_count", 0)
        ),
        "entry_runtime_isolation_policy_count": int(
            agg_counts.get("entry_runtime_isolation_policy_count", 0)
        ),
        "hard_close_missed_economic_exit": int(
            agg_counts.get("hard_close_missed_economic_exit", 0)
        ),
        "economic_exit_feasible_count": int(
            sum(1 for r in close_records if r.get("economic_exit_feasible"))
        ),
        "economic_exit_captured_count": int(
            sum(1 for r in close_records if r.get("economic_exit_captured"))
        ),
        "hard_close_count": int(hard_count),
        "hard_close_share": (float(hard_count) / float(closes)) if closes > 0 else 0.0,
        "hard_close_net_pnl": _sum_nonnull([r.get("net_pnl") for r in hard_rows]),
        "economic_exit_net_pnl": _sum_nonnull([r.get("net_pnl") for r in econ_rows]),
        "pre_hard_close_best_feasible_net": _mean(
            [r.get("pre_hard_close_best_feasible_net") for r in hard_rows]
        ),
        "mean_capture_ratio_proxy": _mean(
            [r.get("capture_ratio_proxy") for r in close_records]
        ),
        "close_reason_breakdown": _counter_to_dict(close_reason),
        "selected_reason_breakdown": _counter_to_dict(selected_reason),
        "missed_exit_reason_bucket": _counter_to_dict(missed_reason),
        "mean_gross_fill_pnl_model": _mean(gross_vals),
        "mean_fee_total": _mean(fee_vals),
        "mean_spread_cost": _mean(spread_vals),
        "mean_slippage_cost": _mean(slip_vals),
        "mean_funding_total": _mean(funding_vals),
        "mean_total_cost": _mean(total_cost_vals),
        "sum_gross_fill_pnl_model": sum_gross,
        "sum_fee_total": sum_fee,
        "sum_total_cost": sum_total_cost,
        "gross_fee_ratio": (sum_gross / sum_fee) if sum_fee > 0 else None,
        "gross_total_cost_ratio": (
            (sum_gross / sum_total_cost) if sum_total_cost > 0 else None
        ),
        "mean_net_pnl_per_trade": _mean(net_vals),
        "median_net_pnl_per_trade": _quantile(net_vals, 0.50),
        "p25_net_pnl_per_trade": _quantile(net_vals, 0.25),
        "p75_net_pnl_per_trade": _quantile(net_vals, 0.75),
        "p05_net_pnl_per_trade": _quantile(net_vals, 0.05),
        "sum_net_pnl": sum_net,
        "net_per_trade": _mean(net_vals),
        "turnover_notional_traded": sum_turnover,
        "net_per_notional": (sum_net / sum_turnover) if sum_turnover > 0 else None,
        "net_gross_ratio": (sum_net / sum_gross) if sum_gross != 0 else None,
        "win_rate": _mean(
            [1.0 if isinstance(v, (int, float)) and v > 0 else 0.0 for v in net_vals]
        ),
        "loss_rate": _mean(
            [1.0 if isinstance(v, (int, float)) and v < 0 else 0.0 for v in net_vals]
        ),
        "pnl_concentration_top_5pct_trades": _pnl_concentration_top_5pct(
            net_vals_nonnull
        ),
        "tail_loss_share": _tail_loss_share(net_vals_nonnull),
        "long_count": int(len(long_rows)),
        "short_count": int(len(short_rows)),
        "mean_net_pnl_long": _mean([r.get("net_pnl") for r in long_rows]),
        "mean_net_pnl_short": _mean([r.get("net_pnl") for r in short_rows]),
        "median_net_pnl_long": _quantile([r.get("net_pnl") for r in long_rows], 0.50),
        "median_net_pnl_short": _quantile([r.get("net_pnl") for r in short_rows], 0.50),
        "gross_total_cost_ratio_long": (
            _sum_nonnull([r.get("gross_fill_pnl_model") for r in long_rows])
            / _sum_nonnull([r.get("total_cost") for r in long_rows])
            if _sum_nonnull([r.get("total_cost") for r in long_rows]) > 0
            else None
        ),
        "gross_total_cost_ratio_short": (
            _sum_nonnull([r.get("gross_fill_pnl_model") for r in short_rows])
            / _sum_nonnull([r.get("total_cost") for r in short_rows])
            if _sum_nonnull([r.get("total_cost") for r in short_rows]) > 0
            else None
        ),
        "borrow_or_funding_cost_short": _sum_nonnull(
            [r.get("funding_total") for r in short_rows]
        ),
        "mean_trade_duration_sec": _mean(
            [r.get("trade_duration_sec") for r in close_records]
        ),
        "mean_mfe": _mean([r.get("mfe") for r in close_records]),
        "mean_mae": _mean([r.get("mae") for r in close_records]),
        "arrival_to_fill_bps": _mean(
            [r.get("arrival_to_fill_bps_open") for r in close_records]
        ),
        "signed_slippage_bps": _mean(
            [r.get("signed_slippage_bps") for r in close_records]
        ),
        "fill_to_mid_markout_1": _mean([r.get("markout_1_bps") for r in close_records]),
        "fill_to_mid_markout_5": _mean([r.get("markout_5_bps") for r in close_records]),
        "fill_to_mid_markout_60": _mean(
            [r.get("markout_60_bps") for r in close_records]
        ),
        "execution_side_bias": {
            "arrival_to_fill_bps_long": _mean(
                [r.get("arrival_to_fill_bps_open") for r in long_rows]
            ),
            "arrival_to_fill_bps_short": _mean(
                [r.get("arrival_to_fill_bps_open") for r in short_rows]
            ),
        },
        "coverage_gate": _build_coverage_gate(close_records),
        "group_symbol": _group_summary(close_records, "symbol"),
        "group_regime": _group_summary(close_records, "regime"),
        "group_strategy": _group_summary(close_records, "strategy"),
        "group_side": _group_summary(close_records, "side"),
    }


def _aggregate_case(case_runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    all_records: list[dict[str, Any]] = []
    agg_counts = Counter()
    close_reason = Counter()
    selected_reason = Counter()
    missed_reason = Counter()
    runtime_status_counts = Counter()
    runtime_bucket_status: dict[str, str] = {}
    per_seed = {}
    for seed, run in case_runs.items():
        metrics = run["metrics"]
        per_seed[seed] = metrics
        records = metrics.get("close_records") or []
        for rec in records:
            rec_copy = dict(rec)
            rec_copy["seed"] = int(seed)
            all_records.append(rec_copy)
        agg_counts["closes"] += int(metrics.get("closes") or 0)
        agg_counts["open_count"] += int(metrics.get("open_count") or 0)
        agg_counts["close_count"] += int(metrics.get("close_count") or 0)
        agg_counts["close_execute_enter"] += int(
            metrics.get("close_execute_enter") or 0
        )
        agg_counts["close_execute_exit_success"] += int(
            metrics.get("close_execute_exit_success") or 0
        )
        agg_counts["entry_count_total"] += int(metrics.get("entry_count_total") or 0)
        agg_counts["entry_quality_passed_count"] += int(
            metrics.get("entry_quality_passed_count") or 0
        )
        agg_counts["tf_trend_entry_eval_count"] += int(
            metrics.get("tf_trend_entry_eval_count") or 0
        )
        agg_counts["tf_trend_entry_filtered_count"] += int(
            metrics.get("tf_trend_entry_filtered_count") or 0
        )
        agg_counts["tf_trend_entry_soft_score_count"] += int(
            metrics.get("tf_trend_entry_soft_score_count") or 0
        )
        agg_counts["entry_realized_quality_penalty_count"] += int(
            metrics.get("entry_realized_quality_penalty_count") or 0
        )
        agg_counts["entry_runtime_isolation_policy_count"] += int(
            metrics.get("entry_runtime_isolation_policy_count") or 0
        )
        agg_counts["hard_close_missed_economic_exit"] += int(
            metrics.get("hard_close_missed_economic_exit") or 0
        )
        runtime_status_counts.update(
            metrics.get("runtime_isolation_status_counts") or {}
        )
        if isinstance(metrics.get("runtime_isolation_bucket_status"), dict):
            for k, v in (metrics.get("runtime_isolation_bucket_status") or {}).items():
                runtime_bucket_status[str(k)] = str(v)
        close_reason.update(metrics.get("close_reason_breakdown") or {})
        selected_reason.update(metrics.get("selected_reason_breakdown") or {})
        missed_reason.update(metrics.get("missed_exit_reason_bucket") or {})

    global_metrics = _extract_run_metrics_from_records(
        all_records, agg_counts, close_reason, selected_reason, missed_reason
    )
    global_metrics["runtime_isolation_status_counts"] = _counter_to_dict(
        runtime_status_counts
    )
    global_metrics["runtime_isolation_bucket_status"] = dict(runtime_bucket_status)
    global_metrics["runtime_isolation_buckets_allowed"] = sorted(
        [k for k, v in runtime_bucket_status.items() if str(v).upper() == "ALLOWED"]
    )
    global_metrics["runtime_isolation_buckets_degraded"] = sorted(
        [k for k, v in runtime_bucket_status.items() if str(v).upper() == "DEGRADED"]
    )
    global_metrics["runtime_isolation_buckets_disabled"] = sorted(
        [k for k, v in runtime_bucket_status.items() if str(v).upper() == "DISABLED"]
    )
    global_metrics["per_seed"] = per_seed
    return global_metrics


def _build_single_db_summary(db_path: Path) -> dict[str, Any]:
    metrics = _extract_run_metrics(db_path)
    close_records = metrics.get("close_records") or []
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "db_path": str(db_path.resolve()),
        "closes": int(metrics.get("closes") or 0),
        "hard_closes": int(metrics.get("hard_close_count") or 0),
        "coverage_gate": metrics.get("coverage_gate") or {},
        "mean_capture_ratio_proxy": metrics.get("mean_capture_ratio_proxy"),
        "mean_pre_hard_close_best_feasible_net": metrics.get(
            "pre_hard_close_best_feasible_net"
        ),
        "economic_exit_feasible_count": metrics.get("economic_exit_feasible_count"),
        "economic_exit_captured_count": metrics.get("economic_exit_captured_count"),
        "sample_close_records": close_records[:5],
    }


def _single_db_report_lines(summary: dict[str, Any]) -> list[str]:
    coverage = summary.get("coverage_gate") or {}
    return [
        "# Single DB Coverage Gate",
        "",
        f"- generated_at_utc: {summary.get('generated_at_utc')}",
        f"- db_path: {summary.get('db_path')}",
        f"- closes: {summary.get('closes')}",
        f"- hard_closes: {summary.get('hard_closes')}",
        f"- coverage_gate_status: {coverage.get('status')}",
        f"- coverage_gate_pass: {coverage.get('gate_pass')}",
        f"- pre_hard_close_best_feasible_net_share_hard: {coverage.get('pre_hard_close_best_feasible_net_share_hard')}",
        f"- capture_ratio_proxy_share_all: {coverage.get('capture_ratio_proxy_share_all')}",
        f"- direct_position_close_mfe_source_share: {coverage.get('direct_position_close_mfe_source_share')}",
        f"- mean_capture_ratio_proxy: {summary.get('mean_capture_ratio_proxy')}",
        f"- mean_pre_hard_close_best_feasible_net: {summary.get('mean_pre_hard_close_best_feasible_net')}",
        f"- economic_exit_feasible_count: {summary.get('economic_exit_feasible_count')}",
        f"- economic_exit_captured_count: {summary.get('economic_exit_captured_count')}",
    ]


def _run_single_db_cli(args: argparse.Namespace) -> None:
    db_path = Path(args.db)
    summary = _build_single_db_summary(db_path)
    if args.out_json:
        out_json = Path(args.out_json)
        out_json.write_text(
            json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8"
        )
    if args.out_md:
        out_md = Path(args.out_md)
        out_md.write_text("\n".join(_single_db_report_lines(summary)), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", help="Path to a single sqlite DB to audit")
    parser.add_argument("--out-json", help="Optional JSON output path")
    parser.add_argument("--out-md", help="Optional Markdown output path")
    return parser.parse_args()


def _build_trial_accounting(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = {
        "trial_count": int(len(CASE_ORDER) * len(SEEDS)),
        "config_count_tested": int(len(CASE_ORDER)),
        "seed_count": int(len(SEEDS)),
        "is_seeds": [int(s) for s in IS_SEEDS],
        "oos_seeds": [int(s) for s in OOS_SEEDS],
        "in_sample_result": {},
        "out_of_sample_result": {},
        "degradation_is_to_oos": None,
        "best_seed_vs_median_seed_gap": {},
    }
    for case_name in CASE_ORDER:
        case = cases.get(case_name) or {}
        runs = case.get("runs") or {}
        is_sum_net = 0.0
        oos_sum_net = 0.0
        seed_means = []
        for seed in SEEDS:
            seed_key = str(seed)
            metrics = (runs.get(seed_key) or {}).get("metrics") or {}
            sum_net = _safe_float(metrics.get("sum_net_pnl")) or 0.0
            if seed in IS_SEEDS:
                is_sum_net += sum_net
            if seed in OOS_SEEDS:
                oos_sum_net += sum_net
            mean_net = _safe_float(metrics.get("mean_net_pnl_per_trade"))
            if mean_net is not None:
                seed_means.append(float(mean_net))
        out["in_sample_result"][case_name] = {"sum_net_pnl": is_sum_net}
        out["out_of_sample_result"][case_name] = {"sum_net_pnl": oos_sum_net}
        if seed_means:
            best_seed = max(seed_means)
            med_seed = _quantile(seed_means, 0.50)
            gap = None
            if med_seed is not None:
                gap = float(best_seed) - float(med_seed)
            out["best_seed_vs_median_seed_gap"][case_name] = gap
        else:
            out["best_seed_vs_median_seed_gap"][case_name] = None

    baseline_is = out["in_sample_result"].get(CASE_BASELINE, {}).get("sum_net_pnl")
    baseline_oos = out["out_of_sample_result"].get(CASE_BASELINE, {}).get("sum_net_pnl")
    patch_is = out["in_sample_result"].get(CASE_PATCH, {}).get("sum_net_pnl")
    patch_oos = out["out_of_sample_result"].get(CASE_PATCH, {}).get("sum_net_pnl")
    if all(
        isinstance(v, (int, float))
        for v in (baseline_is, baseline_oos, patch_is, patch_oos)
    ):
        out["degradation_is_to_oos"] = bool(
            patch_is > baseline_is and patch_oos < baseline_oos
        )
    return out


def _evaluate_patch(
    cases: dict[str, dict[str, Any]], trial_accounting: dict[str, Any]
) -> dict[str, Any]:
    baseline = (cases.get(CASE_BASELINE) or {}).get("global_metrics") or {}
    patch = (cases.get(CASE_PATCH) or {}).get("global_metrics") or {}
    patch_runs = (cases.get(CASE_PATCH) or {}).get("runs") or {}
    baseline_runs = (cases.get(CASE_BASELINE) or {}).get("runs") or {}

    seed_checks = []
    seed_nonworse_count = 0
    for seed in SEEDS:
        s = str(seed)
        patch_m = (patch_runs.get(s) or {}).get("metrics") or {}
        base_m = (baseline_runs.get(s) or {}).get("metrics") or {}
        patch_mean = _safe_float(patch_m.get("mean_net_pnl_per_trade"))
        base_mean = _safe_float(base_m.get("mean_net_pnl_per_trade"))
        if patch_mean is not None and base_mean is not None and patch_mean >= base_mean:
            seed_nonworse_count += 1
        seed_checks.append(
            {
                "seed": int(seed),
                "closes_gt_0": bool((_safe_int(patch_m.get("closes")) or 0) > 0),
                "mismatch_eq_0": bool(
                    (_safe_int(patch_m.get("mismatch_count")) or 0) == 0
                ),
                "close_execute_exit_success_gt_0": bool(
                    (_safe_int(patch_m.get("close_execute_exit_success")) or 0) > 0
                ),
                "mean_net_nonworse_vs_baseline": (
                    bool(patch_mean >= base_mean)
                    if patch_mean is not None and base_mean is not None
                    else None
                ),
            }
        )

    baseline_trade_count = _safe_int(baseline.get("trade_count")) or 0
    patch_trade_count = _safe_int(patch.get("trade_count")) or 0
    baseline_turnover = _safe_float(baseline.get("turnover_notional_traded")) or 0.0
    patch_turnover = _safe_float(patch.get("turnover_notional_traded")) or 0.0
    baseline_net_per_trade = _safe_float(baseline.get("net_per_trade"))
    patch_net_per_trade = _safe_float(patch.get("net_per_trade"))
    baseline_net_per_notional = _safe_float(baseline.get("net_per_notional"))
    patch_net_per_notional = _safe_float(patch.get("net_per_notional"))
    trade_count_up_net_per_trade_down = bool(
        patch_trade_count > baseline_trade_count
        and baseline_net_per_trade is not None
        and patch_net_per_trade is not None
        and patch_net_per_trade < baseline_net_per_trade
    )
    turnover_up_net_per_notional_down = bool(
        patch_turnover > baseline_turnover
        and baseline_net_per_notional is not None
        and patch_net_per_notional is not None
        and patch_net_per_notional < baseline_net_per_notional
    )
    anti_throughput_reject_triggered = bool(
        trade_count_up_net_per_trade_down or turnover_up_net_per_notional_down
    )

    criteria = {
        "all_seeds_closes_gt_0": all(c["closes_gt_0"] for c in seed_checks),
        "all_seeds_mismatch_eq_0": all(c["mismatch_eq_0"] for c in seed_checks),
        "all_seeds_close_execute_exit_success_gt_0": all(
            c["close_execute_exit_success_gt_0"] for c in seed_checks
        ),
        "global_sum_net_pnl_gt_baseline": bool(
            (_safe_float(patch.get("sum_net_pnl")) or -1e18)
            > (_safe_float(baseline.get("sum_net_pnl")) or -1e18)
        ),
        "global_gross_total_cost_ratio_ge_baseline": (
            (_safe_float(patch.get("gross_total_cost_ratio")) is not None)
            and (_safe_float(baseline.get("gross_total_cost_ratio")) is not None)
            and (
                float(_safe_float(patch.get("gross_total_cost_ratio")))
                >= float(_safe_float(baseline.get("gross_total_cost_ratio")))
            )
        ),
        "hard_close_share_not_forced_to_1": (
            not (
                (_safe_float(baseline.get("hard_close_share")) or 0.0) < 1.0
                and (_safe_float(patch.get("hard_close_share")) or 0.0) >= 1.0
            )
        ),
        "no_net_per_trade_drop_if_trade_count_up": (
            not trade_count_up_net_per_trade_down
        ),
        "no_net_per_notional_drop_if_turnover_up": (
            not turnover_up_net_per_notional_down
        ),
        "anti_throughput_guard_pass": (not anti_throughput_reject_triggered),
        "cross_seed_nonworse_in_at_least_2_of_3": bool(seed_nonworse_count >= 2),
        "no_is_to_oos_degradation_flag": not bool(
            trial_accounting.get("degradation_is_to_oos")
        ),
    }

    all_real_improvement = all(bool(v) for v in criteria.values())
    if all_real_improvement:
        verdict = "REAL IMPROVEMENT"
    else:
        patch_sum = _safe_float(patch.get("sum_net_pnl"))
        base_sum = _safe_float(baseline.get("sum_net_pnl"))
        patch_ratio = _safe_float(patch.get("gross_total_cost_ratio"))
        base_ratio = _safe_float(baseline.get("gross_total_cost_ratio"))
        if (
            patch_sum is not None
            and base_sum is not None
            and patch_sum > base_sum
            and (patch_ratio is None or base_ratio is None or patch_ratio < base_ratio)
        ):
            verdict = "LESS BAD ONLY"
        elif (
            patch_sum is not None
            and base_sum is not None
            and abs(patch_sum - base_sum) <= 1e-9
        ):
            verdict = "NO IMPROVEMENT"
        elif patch_sum is not None and base_sum is not None and patch_sum < base_sum:
            verdict = "REGRESSION"
        else:
            verdict = "NO IMPROVEMENT"

    return {
        "seed_checks": seed_checks,
        "criteria": criteria,
        "anti_throughput_reject_triggered": anti_throughput_reject_triggered,
        "anti_throughput_reasons": {
            "trade_count_up_net_per_trade_down": trade_count_up_net_per_trade_down,
            "turnover_up_net_per_notional_down": turnover_up_net_per_notional_down,
        },
        "verdict_class": verdict,
        "safe_patch_found": verdict == "REAL IMPROVEMENT",
    }


def _largest_profitability_limiter(global_metrics: dict[str, Any]) -> str:
    gross_total_cost_ratio = _safe_float(global_metrics.get("gross_total_cost_ratio"))
    hard_share = _safe_float(global_metrics.get("hard_close_share")) or 0.0
    hard_net = _safe_float(global_metrics.get("hard_close_net_pnl")) or 0.0
    tail_loss_share = _safe_float(global_metrics.get("tail_loss_share"))
    net_per_notional = _safe_float(global_metrics.get("net_per_notional"))
    if gross_total_cost_ratio is not None and gross_total_cost_ratio < 1.0:
        return "gross_fill does not cover modeled total transaction costs"
    if hard_share >= 0.6 and hard_net < 0.0:
        return "hard-close dominance with negative hard-close net pnl"
    if tail_loss_share is not None and tail_loss_share >= 0.6:
        return "pnl concentration in left tail losses"
    if net_per_notional is not None and net_per_notional <= 0.0:
        return "negative net per notional turnover"
    return "no single dominant limiter isolated with current telemetry"


def main() -> None:
    args = _parse_args()
    if args.db:
        _run_single_db_cli(args)
        return

    case_data: dict[str, dict[str, Any]] = {}
    for case_name in CASE_ORDER:
        case_runs: dict[str, dict[str, Any]] = {}
        for seed in SEEDS:
            artifacts = _run_case_seed(case_name, seed)
            metrics = _extract_run_metrics(Path(artifacts.db_path))
            case_runs[str(seed)] = {
                "seed": int(seed),
                "env": artifacts.env,
                "db_path": artifacts.db_path,
                "paper_v2_results_json": artifacts.runner_json_path,
                "fee_sanity_json": artifacts.fee_json_path,
                "stdout_log": artifacts.stdout_log_path,
                "stderr_log": artifacts.stderr_log_path,
                "metrics": metrics,
            }
        global_metrics = _aggregate_case(case_runs)
        case_data[case_name] = {
            "env": CASE_ENVS.get(case_name) or {},
            "runs": case_runs,
            "global_metrics": global_metrics,
        }

    trial_accounting = _build_trial_accounting(case_data)
    decision = _evaluate_patch(case_data, trial_accounting)

    baseline_global = (case_data.get(CASE_BASELINE) or {}).get("global_metrics") or {}
    patch_global = (case_data.get(CASE_PATCH) or {}).get("global_metrics") or {}
    limiter = _largest_profitability_limiter(baseline_global)

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "na_marker": NA_UNRELIABLE,
        "seed_order": [int(s) for s in SEEDS],
        "is_seeds": [int(s) for s in IS_SEEDS],
        "oos_seeds": [int(s) for s in OOS_SEEDS],
        "base_env": BASE_ENV,
        "cases": case_data,
        "trial_accounting": trial_accounting,
        "decision_matrix": decision,
        "largest_profitability_limiter": limiter,
        "safe_patch_found": bool(decision.get("safe_patch_found")),
        "selected_patch_case": CASE_PATCH if decision.get("safe_patch_found") else None,
        "final_verdict_class": decision.get("verdict_class"),
        "baseline_sum_net_pnl": baseline_global.get("sum_net_pnl"),
        "patch_sum_net_pnl": patch_global.get("sum_net_pnl"),
        "coverage_gate_by_case": {
            case_name: (
                ((case_data.get(case_name) or {}).get("global_metrics") or {}).get(
                    "coverage_gate"
                )
            )
            for case_name in CASE_ORDER
        },
    }

    out_json = AUTOPSY / "profitability_total_cost_summary.json"
    out_csv = AUTOPSY / "profitability_total_cost_summary.csv"
    out_report_md = AUTOPSY / "profitability_total_cost_report.md"
    out_decision_md = AUTOPSY / "profitability_total_cost_decision_matrix.md"
    out_no_safe_patch = AUTOPSY / "NO_SAFE_PATCH.md"

    out_json.write_text(
        json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8"
    )

    csv_rows = []
    for case_name in CASE_ORDER:
        case = case_data.get(case_name) or {}
        g = case.get("global_metrics") or {}
        csv_rows.append(
            {
                "scope": "global",
                "case": case_name,
                "seed": "all",
                "closes": g.get("closes"),
                "sum_net_pnl": g.get("sum_net_pnl"),
                "mean_net_pnl_per_trade": g.get("mean_net_pnl_per_trade"),
                "net_per_notional": g.get("net_per_notional"),
                "mean_gross_fill_pnl_model": g.get("mean_gross_fill_pnl_model"),
                "mean_fee_total": g.get("mean_fee_total"),
                "mean_total_cost": g.get("mean_total_cost"),
                "gross_fee_ratio": g.get("gross_fee_ratio"),
                "gross_total_cost_ratio": g.get("gross_total_cost_ratio"),
                "net_gross_ratio": g.get("net_gross_ratio"),
                "hard_close_share": g.get("hard_close_share"),
                "hard_close_net_pnl": g.get("hard_close_net_pnl"),
                "economic_exit_net_pnl": g.get("economic_exit_net_pnl"),
                "long_count": g.get("long_count"),
                "short_count": g.get("short_count"),
                "mean_net_pnl_long": g.get("mean_net_pnl_long"),
                "mean_net_pnl_short": g.get("mean_net_pnl_short"),
                "median_net_pnl_long": g.get("median_net_pnl_long"),
                "median_net_pnl_short": g.get("median_net_pnl_short"),
                "arrival_to_fill_bps": g.get("arrival_to_fill_bps"),
                "fill_to_mid_markout_1": g.get("fill_to_mid_markout_1"),
                "fill_to_mid_markout_5": g.get("fill_to_mid_markout_5"),
                "fill_to_mid_markout_60": g.get("fill_to_mid_markout_60"),
                "coverage_gate_status": (g.get("coverage_gate") or {}).get("status"),
                "pre_hard_close_share_hard": (
                    (g.get("coverage_gate") or {}).get(
                        "pre_hard_close_best_feasible_net_share_hard"
                    )
                ),
                "capture_ratio_share_all": (
                    (g.get("coverage_gate") or {}).get("capture_ratio_proxy_share_all")
                ),
                "direct_close_mfe_share": (
                    (g.get("coverage_gate") or {}).get(
                        "direct_position_close_mfe_source_share"
                    )
                ),
                "trial_count": summary.get("trial_accounting", {}).get("trial_count"),
                "seed_count": summary.get("trial_accounting", {}).get("seed_count"),
            }
        )
        runs = case.get("runs") or {}
        for seed in SEEDS:
            run = runs.get(str(seed)) or {}
            m = run.get("metrics") or {}
            csv_rows.append(
                {
                    "scope": "seed",
                    "case": case_name,
                    "seed": seed,
                    "closes": m.get("closes"),
                    "sum_net_pnl": m.get("sum_net_pnl"),
                    "mean_net_pnl_per_trade": m.get("mean_net_pnl_per_trade"),
                    "net_per_notional": m.get("net_per_notional"),
                    "mean_gross_fill_pnl_model": m.get("mean_gross_fill_pnl_model"),
                    "mean_fee_total": m.get("mean_fee_total"),
                    "mean_total_cost": m.get("mean_total_cost"),
                    "gross_fee_ratio": m.get("gross_fee_ratio"),
                    "gross_total_cost_ratio": m.get("gross_total_cost_ratio"),
                    "net_gross_ratio": m.get("net_gross_ratio"),
                    "hard_close_share": m.get("hard_close_share"),
                    "hard_close_net_pnl": m.get("hard_close_net_pnl"),
                    "economic_exit_net_pnl": m.get("economic_exit_net_pnl"),
                    "long_count": m.get("long_count"),
                    "short_count": m.get("short_count"),
                    "mean_net_pnl_long": m.get("mean_net_pnl_long"),
                    "mean_net_pnl_short": m.get("mean_net_pnl_short"),
                    "median_net_pnl_long": m.get("median_net_pnl_long"),
                    "median_net_pnl_short": m.get("median_net_pnl_short"),
                    "arrival_to_fill_bps": m.get("arrival_to_fill_bps"),
                    "fill_to_mid_markout_1": m.get("fill_to_mid_markout_1"),
                    "fill_to_mid_markout_5": m.get("fill_to_mid_markout_5"),
                    "fill_to_mid_markout_60": m.get("fill_to_mid_markout_60"),
                    "coverage_gate_status": (m.get("coverage_gate") or {}).get(
                        "status"
                    ),
                    "pre_hard_close_share_hard": (
                        (m.get("coverage_gate") or {}).get(
                            "pre_hard_close_best_feasible_net_share_hard"
                        )
                    ),
                    "capture_ratio_share_all": (
                        (m.get("coverage_gate") or {}).get(
                            "capture_ratio_proxy_share_all"
                        )
                    ),
                    "direct_close_mfe_share": (
                        (m.get("coverage_gate") or {}).get(
                            "direct_position_close_mfe_source_share"
                        )
                    ),
                    "trial_count": "",
                    "seed_count": "",
                }
            )

    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)

    report_lines = [
        "# Profitability Total-Cost Audit",
        "",
        f"- generated_at_utc: {summary.get('generated_at_utc')}",
        f"- final_verdict_class: {summary.get('final_verdict_class')}",
        f"- safe_patch_found: {summary.get('safe_patch_found')}",
        f"- largest_profitability_limiter: {summary.get('largest_profitability_limiter')}",
        f"- unavailable_marker: {NA_UNRELIABLE}",
        "",
        "## Baseline vs Patch (Global)",
    ]
    for case_name in CASE_ORDER:
        g = (case_data.get(case_name) or {}).get("global_metrics") or {}
        coverage_gate = g.get("coverage_gate") or {}
        report_lines.extend(
            [
                f"### {case_name}",
                f"- closes: {g.get('closes')}",
                f"- sum_net_pnl: {g.get('sum_net_pnl')}",
                f"- mean_net_pnl_per_trade: {g.get('mean_net_pnl_per_trade')}",
                f"- net_per_notional: {g.get('net_per_notional')}",
                f"- mean_gross_fill_pnl_model: {g.get('mean_gross_fill_pnl_model')}",
                f"- mean_fee_total: {g.get('mean_fee_total')}",
                f"- mean_total_cost: {g.get('mean_total_cost')}",
                f"- gross_fee_ratio: {g.get('gross_fee_ratio')}",
                f"- gross_total_cost_ratio: {g.get('gross_total_cost_ratio')}",
                f"- net_gross_ratio: {g.get('net_gross_ratio')}",
                f"- hard_close_share: {g.get('hard_close_share')}",
                f"- hard_close_net_pnl: {g.get('hard_close_net_pnl')}",
                f"- economic_exit_net_pnl: {g.get('economic_exit_net_pnl')}",
                f"- long_count/short_count: {g.get('long_count')}/{g.get('short_count')}",
                f"- mean_net_pnl_long/short: {g.get('mean_net_pnl_long')}/{g.get('mean_net_pnl_short')}",
                f"- entry_realized_quality_penalty_count: {g.get('entry_realized_quality_penalty_count')}",
                f"- hard_close_missed_economic_exit: {g.get('hard_close_missed_economic_exit')}",
                f"- coverage_gate_status: {coverage_gate.get('status')}",
                f"- coverage_gate_pass: {coverage_gate.get('gate_pass')}",
                f"- pre_hard_close_best_feasible_net_share_hard: {coverage_gate.get('pre_hard_close_best_feasible_net_share_hard')}",
                f"- capture_ratio_proxy_share_all: {coverage_gate.get('capture_ratio_proxy_share_all')}",
                f"- direct_position_close_mfe_source_share: {coverage_gate.get('direct_position_close_mfe_source_share')}",
                "",
            ]
        )

    report_lines.extend(
        [
            "## Trial Accounting",
            f"- trial_count: {trial_accounting.get('trial_count')}",
            f"- config_count_tested: {trial_accounting.get('config_count_tested')}",
            f"- seed_count: {trial_accounting.get('seed_count')}",
            f"- in_sample_result: {trial_accounting.get('in_sample_result')}",
            f"- out_of_sample_result: {trial_accounting.get('out_of_sample_result')}",
            f"- degradation_is_to_oos: {trial_accounting.get('degradation_is_to_oos')}",
            f"- best_seed_vs_median_seed_gap: {trial_accounting.get('best_seed_vs_median_seed_gap')}",
            "",
            "## Decision Matrix",
            f"- criteria: {decision.get('criteria')}",
            f"- verdict_class: {decision.get('verdict_class')}",
            f"- safe_patch_found: {decision.get('safe_patch_found')}",
            "",
            "## TCA Gaps",
            "- impact_proxy_cost: unavailable; no L2 depth/queue telemetry per fill.",
            "- opportunity_cost_unfilled: unavailable in USDT value; only event counts available.",
            "- markouts 1/5/60: coarse fallback from position_mark stream.",
        ]
    )
    out_report_md.write_text("\n".join(report_lines), encoding="utf-8")

    decision_lines = [
        "# Profitability Decision Matrix",
        "",
        f"- final_verdict_class: {decision.get('verdict_class')}",
        f"- safe_patch_found: {decision.get('safe_patch_found')}",
        "",
        "## Criteria",
    ]
    for k, v in (decision.get("criteria") or {}).items():
        decision_lines.append(f"- {k}: {v}")
    out_decision_md.write_text("\n".join(decision_lines), encoding="utf-8")

    if not decision.get("safe_patch_found"):
        no_safe_patch_lines = [
            "# NO SAFE PATCH",
            "",
            f"- generated_at_utc: {summary.get('generated_at_utc')}",
            f"- final_verdict_class: {summary.get('final_verdict_class')}",
            "- reason: patch candidate failed hard acceptance criteria.",
            f"- largest_profitability_limiter: {summary.get('largest_profitability_limiter')}",
            f"- baseline_case_kept: {CASE_BASELINE}",
            f"- patch_case_rejected: {CASE_PATCH}",
        ]
        out_no_safe_patch.write_text("\n".join(no_safe_patch_lines), encoding="utf-8")

    print(str(out_json.resolve()))
    print(str(out_csv.resolve()))
    print(str(out_report_md.resolve()))
    print(str(out_decision_md.resolve()))
    if not decision.get("safe_patch_found"):
        print(str(out_no_safe_patch.resolve()))


if __name__ == "__main__":
    main()
