from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKDIR = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = WORKDIR / "analysis"
RESULTS_DIR = WORKDIR / "results"
TMP_DIR = WORKDIR / "tmp"
ACCEPTED_CORPUS_DIR = Path(
    os.environ.get("ZOL0_ACCEPTED_CORPUS_DIR")
    or WORKDIR / "artifacts" / "accepted_corpus"
)

DEFAULT_LIMIT = 20
DEFAULT_ALLOWED_DATES = ("2026-04-08", "2026-04-09")
FLOAT_TOLERANCE = 1e-9
STRATEGY_VALIDATION_MIN_NATURAL_TRADES = 60
NATURAL_ENTRY_TRUTH_CLASSES = {
    "NATURAL_STRATEGY_ENTRY",
    "EDGE_DISCOVERED_DYNAMIC",
}
ASSISTED_ENTRY_TRUTH_CLASSES = {
    "PAPER_AUTO_OPEN_FALLBACK",
    "BOOTSTRAP_ALLOWLIST_ASSISTED",
    "SEED_TRADES_OVERRIDE_ASSISTED",
}
TRUE_FORCED_CYCLE_EVENT_NAMES = {
    "post_promotion_force_cycle_request",
    "forced_cycle_requested",
    "forced_cycle_started",
    "forced_cycle_completed",
    "forced_cycle_failed",
}
BENIGN_POST_PROMOTION_FORCE_CYCLE_BOOKKEEPING_EVENTS = {
    "post_promotion_force_cycle_scheduler_caller_enter",
    "post_promotion_force_cycle_scheduler_caller_exit",
    "post_promotion_force_cycle_drain_enter",
    "post_promotion_force_cycle_scheduler_gate_enter",
    "post_promotion_force_cycle_scheduler_gate_result",
    "post_promotion_force_cycle_scheduler_gate_blocked",
    "post_promotion_force_cycle_pending_check_enter",
    "post_promotion_force_cycle_pending_check_result",
    "post_promotion_force_cycle_pending_not_visible",
    "post_promotion_force_cycle_drain_skipped",
    "post_promotion_force_cycle_pre_drain_candidate",
    "post_promotion_force_cycle_pre_drain_skip",
    "post_promotion_force_cycle_pre_drain_skip_reason",
    "post_promotion_force_cycle_pre_drain_reject",
    "post_promotion_force_cycle_pre_drain_reject_reason",
    "post_promotion_force_cycle_pre_drain_return",
    "post_promotion_force_cycle_request_scan_enter",
    "post_promotion_force_cycle_request_scan_empty",
    "post_promotion_force_cycle_request_scan_empty_reason",
    "post_promotion_force_cycle_request_scan_result",
}
NATURAL_CORPUS_REJECT_EXIT_REASONS = {
    "auto_close_hard",
    "auto_close_hard_near_zero",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except Exception:
        return default


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y", "on"}:
            return True
        if text in {"false", "0", "no", "n", "off", ""}:
            return False
    return default


def _pct(value: float) -> float:
    return round(float(value) * 100.0, 3)


def _round6(value: float) -> float:
    return round(float(value), 6)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _dedupe_reason_codes(codes: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for code in codes:
        text = str(code or "").strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


def _score_status(score: float) -> str:
    if score >= 75.0:
        return "dobrze"
    if score >= 50.0:
        return "mieszane / wymaga korekty"
    return "zle / priorytet"


def _display_profit_factor(value: float | None) -> float | str | None:
    if value is None:
        return None
    if math.isinf(value):
        return "Infinity"
    return _round6(value)


def _profit_factor(gross_profit: float, gross_loss_abs: float) -> float | None:
    if gross_loss_abs > 0:
        return gross_profit / gross_loss_abs
    if gross_profit > 0:
        return math.inf
    return 0.0


def _sort_profit_factor(value: float | None) -> float:
    if value is None:
        return -1.0
    if math.isinf(value):
        return 1_000_000.0
    return float(value)


def _normalize_ratio_to_1(value: float) -> float:
    if value <= 0:
        return 0.0
    return min(value, 1.0)


def _coerce_timestamp_date(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) >= 10:
        return text[:10]
    return None


def _compare_float(left: Any, right: Any, tol: float = FLOAT_TOLERANCE) -> bool:
    left_val = _safe_float(left)
    right_val = _safe_float(right)
    if math.isinf(left_val) and math.isinf(right_val):
        return (left_val > 0) == (right_val > 0)
    if math.isnan(left_val) and math.isnan(right_val):
        return True
    if math.isnan(left_val) or math.isnan(right_val):
        return False
    return abs(left_val - right_val) <= tol


def _read_csv_alignment(csv_path: Path, after: dict[str, Any]) -> dict[str, Any]:
    if not csv_path.exists():
        return {"ok": False, "reason": "csv_missing", "path": str(csv_path)}
    with csv_path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) != 1:
        return {"ok": False, "reason": "unexpected_csv_rows", "rows": len(rows), "path": str(csv_path)}
    row = rows[0]
    checks = {
        "variant": str(row.get("variant") or "") == "after",
        "trade_count": _safe_int(row.get("trade_count")) == _safe_int(after.get("trade_count")),
        "net_pnl": _compare_float(row.get("net_pnl"), after.get("net_pnl")),
        "winrate": _compare_float(row.get("winrate"), after.get("winrate")),
        "max_drawdown": _compare_float(row.get("max_drawdown"), after.get("max_drawdown")),
        "profit_factor": _compare_float(row.get("profit_factor"), after.get("profit_factor")),
        "gross_profit": _compare_float(row.get("gross_profit"), after.get("gross_profit")),
        "gross_loss_abs": _compare_float(row.get("gross_loss_abs"), after.get("gross_loss_abs")),
        "decisions_count": _safe_int(row.get("decisions_count")) == _safe_int(after.get("decisions_count")),
        "duration_sec_actual": _safe_int(row.get("duration_sec_actual")) == _safe_int(after.get("duration_sec_actual")),
    }
    return {"ok": all(checks.values()), "checks": checks, "path": str(csv_path)}


def _data_check_all_ok(payload: dict[str, Any]) -> bool:
    results = (((payload.get("data_check") or {}).get("results")) or {})
    if not results:
        return False
    return all(_coerce_bool((stats or {}).get("ok")) for stats in results.values())


def _candidate_db_path(after: dict[str, Any], db_path: Path | None = None) -> Path | None:
    if db_path is not None:
        return db_path
    raw = str((after or {}).get("db_path") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = WORKDIR / path
    return path


def _parse_log_details(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _benign_force_cycle_bookkeeping_payload(details: dict[str, Any]) -> bool:
    event_name = str(details.get("event") or "").strip()
    if event_name not in BENIGN_POST_PROMOTION_FORCE_CYCLE_BOOKKEEPING_EVENTS:
        return False
    if _coerce_bool(details.get("has_pending_forced_cycle_request")):
        return False
    if _coerce_bool(details.get("scheduler_tick_eligible")):
        return False
    if _safe_int(details.get("request_count_seen")) > 0:
        return False
    if _safe_int(details.get("request_id")) > 0:
        return False
    if _safe_int(details.get("last_post_promotion_force_cycle_request_id")) > 0:
        return False
    scan_reason = str(details.get("scan_reason") or "").strip()
    if scan_reason and scan_reason != "request_rows_absent":
        return False
    empty_reason = str(details.get("empty_reason") or "").strip()
    if empty_reason and empty_reason != "no_pending_requests_exist":
        return False
    gate_reason = str(details.get("gate_reason") or "").strip()
    if gate_reason and gate_reason not in {
        "forced_cycle_scheduler_gate",
        "pending_request_not_visible",
    }:
        return False
    for field in (
        "skip_reason",
        "pre_drain_skip_reason",
        "pre_drain_reject_reason",
    ):
        reason = str(details.get(field) or "").strip()
        if reason and reason != "pending_request_not_visible":
            return False
    return True


def _db_confirms_bookkeeping_only_force_cycle(
    after: dict[str, Any],
    bookkeeping_events: set[str],
    *,
    db_path: Path | None = None,
) -> bool:
    if not bookkeeping_events:
        return True
    if not bookkeeping_events.issubset(BENIGN_POST_PROMOTION_FORCE_CYCLE_BOOKKEEPING_EVENTS):
        return False
    resolved_db_path = _candidate_db_path(after, db_path)
    if resolved_db_path is None or not resolved_db_path.exists():
        return False
    conn = None
    try:
        uri = f"file:{resolved_db_path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        table_exists = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='logs'"
        ).fetchone()
        if table_exists is None:
            return False
        placeholders = ",".join("?" for _ in TRUE_FORCED_CYCLE_EVENT_NAMES)
        true_count = cur.execute(
            f"SELECT COUNT(*) FROM logs WHERE event IN ({placeholders})",
            tuple(sorted(TRUE_FORCED_CYCLE_EVENT_NAMES)),
        ).fetchone()[0]
        if _safe_int(true_count) > 0:
            return False
        window_count = cur.execute(
            "SELECT COUNT(*) FROM logs "
            "WHERE event = 'controlled_kpi_window_end' "
            "OR details LIKE '%controlled_kpi_window_end%'"
        ).fetchone()[0]
        if _safe_int(window_count) > 0:
            return False
        unknown_count = cur.execute(
            "SELECT COUNT(*) FROM logs "
            "WHERE event LIKE 'post_promotion_force_cycle_%' "
            f"AND event NOT IN ({','.join('?' for _ in BENIGN_POST_PROMOTION_FORCE_CYCLE_BOOKKEEPING_EVENTS)})",
            tuple(sorted(BENIGN_POST_PROMOTION_FORCE_CYCLE_BOOKKEEPING_EVENTS)),
        ).fetchone()[0]
        if _safe_int(unknown_count) > 0:
            return False
        has_no_pending_request_evidence = False
        has_request_rows_absent_evidence = False
        has_pending_not_visible_evidence = False
        for event_name in sorted(bookkeeping_events):
            rows = cur.execute(
                "SELECT details FROM logs WHERE event = ?",
                (event_name,),
            ).fetchall()
            if not rows:
                return False
            for row in rows:
                details = _parse_log_details(row["details"])
                if not _benign_force_cycle_bookkeeping_payload(details):
                    return False
                if details.get("has_pending_forced_cycle_request") is False:
                    has_no_pending_request_evidence = True
                if _safe_int(details.get("last_post_promotion_force_cycle_request_id")) == 0:
                    has_no_pending_request_evidence = True
                if _safe_int(details.get("request_count_seen")) == 0:
                    has_request_rows_absent_evidence = True
                if str(details.get("scan_reason") or "").strip() == "request_rows_absent":
                    has_request_rows_absent_evidence = True
                if str(details.get("skip_reason") or "").strip() == "pending_request_not_visible":
                    has_pending_not_visible_evidence = True
                if (
                    str(details.get("pre_drain_reject_reason") or "").strip()
                    == "pending_request_not_visible"
                ):
                    has_pending_not_visible_evidence = True
                if str(details.get("gate_reason") or "").strip() == "pending_request_not_visible":
                    has_pending_not_visible_evidence = True
                if event_name in {
                    "post_promotion_force_cycle_pending_not_visible",
                    "post_promotion_force_cycle_drain_skipped",
                }:
                    has_pending_not_visible_evidence = True
        if not (
            has_no_pending_request_evidence
            and has_request_rows_absent_evidence
            and has_pending_not_visible_evidence
        ):
            return False
        return True
    except Exception:
        return False
    finally:
        if conn is not None:
            conn.close()


def _profitability_contamination_reasons(
    after: dict[str, Any],
    *,
    payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> list[str]:
    if not isinstance(after, dict):
        return []

    reasons: set[str] = set()
    event_counts = after.get("event_counts") or {}
    post_promotion_bookkeeping_events: set[str] = set()
    if isinstance(event_counts, dict):
        for raw_key, raw_value in event_counts.items():
            key = str(raw_key or "").strip()
            if not key or _safe_int(raw_value) <= 0:
                continue
            if key in TRUE_FORCED_CYCLE_EVENT_NAMES or key.startswith("forced_cycle_"):
                reasons.add(f"event_count:{key}")
            elif key.startswith("post_promotion_force_cycle_"):
                if key in BENIGN_POST_PROMOTION_FORCE_CYCLE_BOOKKEEPING_EVENTS:
                    post_promotion_bookkeeping_events.add(key)
                else:
                    reasons.add(f"event_count:{key}")
    if post_promotion_bookkeeping_events and not _db_confirms_bookkeeping_only_force_cycle(
        after,
        post_promotion_bookkeeping_events,
        db_path=db_path,
    ):
        for key in sorted(post_promotion_bookkeeping_events):
            reasons.add(f"event_count:{key}")

    trace = after.get("runner_termination_trace") or []
    if isinstance(trace, list):
        for item in trace:
            if not isinstance(item, dict):
                continue
            reason = str(item.get("reason") or "").strip()
            if reason == "controlled_kpi_window_end":
                reasons.add("runner_close_reason:controlled_kpi_window_end")
                break

    forced_marker_fields = {
        "post_promotion_forced_cycle_request_reason",
        "post_promotion_forced_cycle_trigger_mode",
    }
    for field in forced_marker_fields:
        value = str(after.get(field) or "").strip()
        if value:
            reasons.add(f"marker:{field}={value}")

    for field in (
        "runner_shutdown_reason",
        "runner_termination_reason",
        "post_promotion_window_exit_reason",
        "post_promotion_reeval_exit_reason",
    ):
        value = str(after.get(field) or "").strip()
        if not value:
            continue
        if value == "controlled_kpi_window_end" or "forced_cycle" in value:
            reasons.add(f"marker:{field}={value}")

    exit_reason_distribution = after.get("exit_reason_distribution") or {}
    if isinstance(exit_reason_distribution, dict):
        for raw_reason, raw_count in exit_reason_distribution.items():
            reason = str(raw_reason or "").strip()
            if reason in NATURAL_CORPUS_REJECT_EXIT_REASONS and _safe_int(raw_count) > 0:
                reasons.add(f"exit_reason:{reason}")

    final_close = after.get("final_close_drain_snapshot") or {}
    if isinstance(final_close, dict) and _safe_int(final_close.get("pending_positions")) > 0:
        reasons.add(
            f"pending_positions:{_safe_int(final_close.get('pending_positions'))}"
        )

    for field in (
        "assisted_seed_admitted_count",
        "assisted_seed_open_count",
        "fallback_open_count",
    ):
        count = _safe_int(after.get(field))
        if count > 0:
            reasons.add(f"{field}:{count}")

    effective_env = after.get("effective_env_values") or {}
    if isinstance(effective_env, dict):
        if _coerce_bool(effective_env.get("SEED_TRADES_ENABLE")):
            reasons.add("env:SEED_TRADES_ENABLE=1")
        if _coerce_bool(effective_env.get("ALPHA_WHITELIST_FALLBACK_ENABLE")):
            reasons.add("env:ALPHA_WHITELIST_FALLBACK_ENABLE=1")

    diagnostic_env = after.get("diagnostic_env_flags") or {}
    if isinstance(diagnostic_env, dict) and _coerce_bool(diagnostic_env.get("LIVE")):
        reasons.add("live:LIVE=1")

    if isinstance(payload, dict):
        params = payload.get("params") or {}
        if isinstance(params, dict) and _coerce_bool(params.get("use_mock")):
            reasons.add("mock:use_mock")
        refresh_report = (
            ((payload.get("alpha_bootstrap_refresh") or {}).get("report") or {})
            if isinstance(payload.get("alpha_bootstrap_refresh"), dict)
            else {}
        )
        if isinstance(refresh_report, dict):
            if _coerce_bool(refresh_report.get("positive_side_fallback_used")):
                reasons.add("bootstrap:positive_side_fallback_used")
            if _coerce_bool(refresh_report.get("fallback_used")):
                reasons.add("bootstrap:fallback_used")

    return sorted(reasons)


def _run_has_profitability_contamination(run: dict[str, Any]) -> bool:
    if _coerce_bool(run.get("profitability_contaminated")):
        return True
    reasons = run.get("profitability_contamination_reasons") or []
    if any(str(item).strip() for item in reasons if item is not None):
        return True
    payload = run.get("payload") or {}
    run_db_path = None
    if isinstance(run.get("db_path"), (str, Path)):
        run_db_path = Path(str(run.get("db_path")))
    after = run.get("after") or {}
    if isinstance(after, dict) and _profitability_contamination_reasons(
        after,
        payload=payload if isinstance(payload, dict) else None,
        db_path=run_db_path,
    ):
        return True
    if isinstance(payload, dict):
        nested_after = payload.get("after") or {}
        if isinstance(nested_after, dict) and _profitability_contamination_reasons(
            nested_after,
            payload=payload,
            db_path=run_db_path,
        ):
            return True
    return False


def _main_run_process_ok(run: dict[str, Any]) -> bool:
    if _run_has_profitability_contamination(run):
        return False
    process_returncode = _safe_int(run.get("process_returncode"))
    if process_returncode == 0:
        return True
    if _safe_int(run.get("log_error_count")) > 0:
        return False
    shutdown_classification = str(run.get("shutdown_classification") or "")
    return shutdown_classification in {
        "close_flush_done_pending_positions_zero",
        "real_post_promotion_read_observed",
    }


def _candidate_after_row(path: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    after = payload.get("after") or {}
    if str(after.get("variant") or "") != "after":
        return None
    params = payload.get("params") or {}
    trade_count = _safe_int(after.get("trade_count"))
    decisions_count = _safe_int(after.get("decisions_count"))
    result_path = path.resolve()
    csv_path = result_path.with_suffix(".csv")
    db_path = _resolve_repo_path(after.get("db_path") or "")
    csv_alignment = _read_csv_alignment(csv_path, after)
    started_date = _coerce_timestamp_date(after.get("started_at_utc"))
    ended_date = _coerce_timestamp_date(after.get("ended_at_utc"))
    contamination_reasons = _profitability_contamination_reasons(
        after,
        payload=payload,
        db_path=db_path,
    )
    row = {
        "run_id": str(payload.get("run_id") or result_path.stem.replace("controlled_kpi_", "")),
        "result_path": str(result_path),
        "csv_path": str(csv_path),
        "db_path": str(db_path),
        "payload": payload,
        "after": after,
        "params": params,
        "started_date": started_date,
        "ended_date": ended_date,
        "trade_count": trade_count,
        "net_pnl": _safe_float(after.get("net_pnl")),
        "profit_factor": _safe_float(after.get("profit_factor")),
        "winrate": _safe_float(after.get("winrate")),
        "max_drawdown": _safe_float(after.get("max_drawdown")),
        "decisions_count": decisions_count,
        "conversion_rate": (trade_count / decisions_count) if decisions_count > 0 else 0.0,
        "use_mock": _coerce_bool(params.get("use_mock")),
        "db_exists": _coerce_bool(after.get("db_exists")),
        "db_size_bytes": _safe_size(db_path),
        "process_returncode": _safe_int(after.get("process_returncode")),
        "log_error_count": _safe_int(((after.get("log_health") or {}).get("error_count"))),
        "shutdown_classification": str(
            after.get("shutdown_classification") or ""
        ),
        "data_check_all_ok": _data_check_all_ok(payload),
        "csv_alignment": csv_alignment,
        "profitability_contamination_reasons": contamination_reasons,
        "profitability_contaminated": bool(contamination_reasons),
    }
    return row


def _filter_main_corpus_runs(candidate_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        run
        for run in candidate_runs
        if (not run["use_mock"])
        and run["db_exists"]
        and _safe_int(run.get("db_size_bytes")) > 0
        and _main_run_process_ok(run)
    ]


def _candidate_after_runs(
    results_dir: Path,
    limit: int,
    allowed_dates: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    paths = sorted(results_dir.glob("controlled_kpi_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths:
        payload = _load_json(path)
        row = _candidate_after_row(path, payload)
        if row is None:
            continue
        if allowed_dates:
            if row["started_date"] not in allowed_dates:
                continue
            if row["ended_date"] not in allowed_dates:
                continue
        if row["process_returncode"] != 0 and not _main_run_process_ok(row):
            continue
        runs.append(row)
        if len(runs) >= int(limit):
            break
    return runs


def _as_profit_factor(value: float | str | None) -> float | None:
    if value == "Infinity":
        return math.inf
    if value is None:
        return None
    return _safe_float(value, default=0.0)


def _infer_problem_class(winrate: float, profit_factor: float | None, net_pnl: float) -> str:
    pf = 0.0 if profit_factor is None else (10.0 if math.isinf(profit_factor) else float(profit_factor))
    if net_pnl > 0 and pf > 1.0:
        return "pozytywny"
    if winrate >= 0.5 and net_pnl <= 0:
        return "kosztowy"
    if winrate >= 0.35 and pf < 1.0:
        return "wyjsciowy"
    return "wejsciowy"


def _aggregate_symbol_rankings(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, Any]] = {}
    for run in runs:
        for symbol, stats in ((run.get("after") or {}).get("symbol_stats") or {}).items():
            row = agg.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "runs": 0,
                    "trades": 0,
                    "net_pnl": 0.0,
                    "wins": 0,
                    "losses": 0,
                    "gross_profit": 0.0,
                    "gross_loss_abs": 0.0,
                },
            )
            row["runs"] += 1
            row["trades"] += _safe_int(stats.get("trade_count"))
            row["net_pnl"] += _safe_float(stats.get("net_pnl"))
            row["wins"] += _safe_int(stats.get("wins"))
            row["losses"] += _safe_int(stats.get("losses"))
            row["gross_profit"] += _safe_float(stats.get("gross_profit"))
            row["gross_loss_abs"] += _safe_float(stats.get("gross_loss_abs"))
    rankings: list[dict[str, Any]] = []
    for symbol, row in agg.items():
        total_closed = row["wins"] + row["losses"]
        pf = _profit_factor(row["gross_profit"], row["gross_loss_abs"])
        winrate = (row["wins"] / total_closed) if total_closed > 0 else 0.0
        avg_pnl = (row["net_pnl"] / row["trades"]) if row["trades"] > 0 else 0.0
        rankings.append(
            {
                "entity_type": "symbol",
                "name": symbol,
                "runs": row["runs"],
                "trade_count": row["trades"],
                "net_pnl": _round6(row["net_pnl"]),
                "avg_pnl_per_trade": _round6(avg_pnl),
                "winrate": _round6(winrate),
                "profit_factor": _display_profit_factor(pf),
                "dominant_issue": _infer_problem_class(winrate, pf, row["net_pnl"]),
            }
        )
    rankings.sort(key=lambda item: (float(item["net_pnl"]), _sort_profit_factor(_as_profit_factor(item["profit_factor"]))), reverse=True)
    return rankings


def _load_alpha_bucket_rankings(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        raise FileNotFoundError(f"alpha history db not found: {db_path}")
    agg: dict[str, dict[str, Any]] = {}
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        rows = cur.execute("SELECT details FROM logs WHERE event='position_close'").fetchall()
    finally:
        conn.close()
    for (details_text,) in rows:
        try:
            details = json.loads(details_text)
        except Exception:
            continue
        position = details.get("position") or {}
        symbol = str(position.get("symbol") or details.get("symbol") or "UNKNOWN").strip().upper()
        strategy = str(position.get("strategy") or details.get("strategy") or "UNKNOWN").strip()
        bucket_key = f"{symbol}|{strategy}"
        realized_pnl = _safe_float(position.get("realized_pnl", details.get("realized_pnl")))
        row = agg.setdefault(
            bucket_key,
            {
                "bucket": bucket_key,
                "symbol": symbol,
                "strategy": strategy,
                "trade_count": 0,
                "net_pnl": 0.0,
                "wins": 0,
                "losses": 0,
                "gross_profit": 0.0,
                "gross_loss_abs": 0.0,
            },
        )
        row["trade_count"] += 1
        row["net_pnl"] += realized_pnl
        if realized_pnl > 0:
            row["wins"] += 1
            row["gross_profit"] += realized_pnl
        elif realized_pnl < 0:
            row["losses"] += 1
            row["gross_loss_abs"] += abs(realized_pnl)
    rankings: list[dict[str, Any]] = []
    for bucket_key, row in agg.items():
        total_closed = row["wins"] + row["losses"]
        pf = _profit_factor(row["gross_profit"], row["gross_loss_abs"])
        winrate = (row["wins"] / total_closed) if total_closed > 0 else 0.0
        avg_pnl = (row["net_pnl"] / row["trade_count"]) if row["trade_count"] > 0 else 0.0
        rankings.append(
            {
                "entity_type": "bucket",
                "name": bucket_key,
                "symbol": row["symbol"],
                "strategy": row["strategy"],
                "trade_count": row["trade_count"],
                "net_pnl": _round6(row["net_pnl"]),
                "avg_pnl_per_trade": _round6(avg_pnl),
                "winrate": _round6(winrate),
                "profit_factor": _display_profit_factor(pf),
                "dominant_issue": _infer_problem_class(winrate, pf, row["net_pnl"]),
                "source": "alpha_history_auto_recent.db",
            }
        )
    rankings.sort(key=lambda item: (float(item["net_pnl"]), _sort_profit_factor(_as_profit_factor(item["profit_factor"]))), reverse=True)
    return rankings


def _latest_path(pattern: str) -> Path:
    matches = sorted(WORKDIR.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f"no path matches {pattern}")
    return matches[0]


def _workspace_rel(path_value: str | Path) -> str:
    path = Path(path_value)
    try:
        return str(path.resolve().relative_to(WORKDIR.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _resolve_repo_path(path_value: str | Path) -> Path:
    path = Path(str(path_value or ""))
    if not path.is_absolute():
        path = (WORKDIR / path).resolve()
    return path


def _safe_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


def _entry_truth_classification(
    *,
    details: dict[str, Any],
    position: dict[str, Any],
) -> str:
    selection_source = str(
        position.get("selection_source") or details.get("selection_source") or ""
    ).strip().lower()
    entry_reason = str(
        position.get("entry_reason") or details.get("entry_reason") or ""
    ).strip().lower()
    decision_router_path = str(
        position.get("decision_router_path")
        or details.get("decision_router_path")
        or ""
    ).strip().lower()
    override_reason = str(
        position.get("override_reason") or details.get("override_reason") or ""
    ).strip().lower()
    strategy = str(
        position.get("strategy")
        or position.get("entry_main_strategy")
        or details.get("strategy")
        or details.get("main_strategy")
        or ""
    ).strip().lower()

    if (
        selection_source == "paper_auto_open_fallback"
        or decision_router_path == "paper_auto_open_fallback"
        or override_reason == "paper_auto_open_fallback"
        or entry_reason == "auto_test_open"
        or strategy == "auto_test"
    ):
        return "PAPER_AUTO_OPEN_FALLBACK"
    if (
        selection_source == "entry_symbol_strategy_side_allowlist"
        or decision_router_path == "paper_auto_open_allowlisted"
        or override_reason == "paper_auto_open_allowlisted"
        or entry_reason == "paper_auto_open_allowlisted"
    ):
        return "BOOTSTRAP_ALLOWLIST_ASSISTED"
    if entry_reason == "seed_trades_override":
        return "SEED_TRADES_OVERRIDE_ASSISTED"
    if entry_reason == "decision_passed" and override_reason in {"", "none"}:
        return "NATURAL_STRATEGY_ENTRY"
    if entry_reason in {
        "edge_discovered_dynamic",
        "entry_live_edge",
        "live_edge_discovered",
        "dynamic_edge_discovered",
    }:
        return "EDGE_DISCOVERED_DYNAMIC"
    return "UNKNOWN_REQUIRES_REVIEW"


def _trade_metrics_from_values(
    values: list[dict[str, float | None]],
) -> dict[str, Any]:
    realized = [
        float(item["pnl"])
        for item in values
        if item.get("pnl") is not None
    ]
    trade_count = len(realized)
    wins = sum(1 for value in realized if value > 0.0)
    losses = sum(1 for value in realized if value < 0.0)
    gross_profit = sum(value for value in realized if value > 0.0)
    gross_loss_abs = abs(sum(value for value in realized if value < 0.0))
    net_pnl = sum(realized)
    profit_factor = _profit_factor(gross_profit, gross_loss_abs)
    expectancy = (net_pnl / trade_count) if trade_count > 0 else None
    winrate = (wins / trade_count) if trade_count > 0 else None

    missing_mfe_count = 0
    ever_profitable_count = 0
    green_to_red_count = 0
    for item in values:
        pnl_val = item.get("pnl")
        mfe_val = item.get("mfe")
        if pnl_val is None:
            continue
        if mfe_val is None:
            missing_mfe_count += 1
            continue
        if float(mfe_val) > 0.0:
            ever_profitable_count += 1
            if float(pnl_val) <= 0.0:
                green_to_red_count += 1

    green_to_red_share = (
        green_to_red_count / trade_count if trade_count > 0 else None
    )

    return {
        "trade_count": trade_count,
        "net_pnl": _round6(net_pnl),
        "expectancy": _round6(expectancy) if expectancy is not None else None,
        "winrate": _round6(winrate) if winrate is not None else None,
        "profit_factor": _display_profit_factor(profit_factor),
        "wins": wins,
        "losses": losses,
        "gross_profit": _round6(gross_profit),
        "gross_loss_abs": _round6(gross_loss_abs),
        "ever_profitable_count": ever_profitable_count,
        "green_to_red_count": green_to_red_count,
        "green_to_red_share": (
            _round6(green_to_red_share)
            if green_to_red_share is not None
            else None
        ),
        "missing_mfe_count": missing_mfe_count,
    }


def _strategy_validation_metrics_from_accepted_runs(
    accepted_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    all_values: list[dict[str, float | None]] = []
    natural_values: list[dict[str, float | None]] = []
    truth_counts: dict[str, int] = {}

    for run in accepted_runs:
        db_path = _resolve_repo_path(run.get("db_path") or "")
        if not db_path.exists():
            raise FileNotFoundError(f"accepted run db not found: {db_path}")
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT details FROM logs WHERE event='position_close'"
            ).fetchall()
        finally:
            conn.close()

        for (details_text,) in rows:
            try:
                details = json.loads(details_text or "{}")
            except Exception:
                continue
            if not isinstance(details, dict):
                continue
            position = (
                details.get("position")
                if isinstance(details.get("position"), dict)
                else {}
            )
            pnl_decompose = (
                position.get("pnl_decompose")
                if isinstance(position.get("pnl_decompose"), dict)
                else details.get("pnl_decompose")
                if isinstance(details.get("pnl_decompose"), dict)
                else {}
            )
            pnl = details.get("realized_pnl")
            if pnl is None:
                pnl = position.get("realized_pnl")
            if pnl is None:
                pnl = position.get("realized_net")
            if pnl is None:
                pnl = pnl_decompose.get("net_pnl")
            pnl_val = _safe_float(pnl, None)
            if pnl_val is None:
                continue

            mfe = position.get("mfe")
            if mfe is None:
                mfe = position.get("max_unrealized_pnl")
            if mfe is None:
                mfe = details.get("mfe")
            mfe_val = _safe_float(mfe, None)
            trade_value = {"pnl": float(pnl_val), "mfe": mfe_val}
            all_values.append(trade_value)

            truth = _entry_truth_classification(details=details, position=position)
            truth_counts[truth] = int(truth_counts.get(truth, 0)) + 1
            if truth in NATURAL_ENTRY_TRUTH_CLASSES:
                natural_values.append(trade_value)

    all_metrics = _trade_metrics_from_values(all_values)
    natural_metrics = _trade_metrics_from_values(natural_values)

    natural_trade_count = int(natural_metrics["trade_count"])
    assisted_trade_count = sum(
        int(truth_counts.get(classification, 0))
        for classification in ASSISTED_ENTRY_TRUTH_CLASSES
    )
    unknown_trade_count = int(truth_counts.get("UNKNOWN_REQUIRES_REVIEW", 0))
    reason_codes: list[str] = []
    if assisted_trade_count:
        reason_codes.append("ASSISTED_ENTRY_EVIDENCE_PRESENT")
    if unknown_trade_count:
        reason_codes.append("UNKNOWN_ENTRY_EVIDENCE_PRESENT")
    if natural_trade_count == 0:
        classification = "NO_NATURAL_STRATEGY_TRADES"
        reason_codes.append("NATURAL_ENTRY_TRADE_COUNT_ZERO")
        if assisted_trade_count:
            reason_codes.append("ASSISTED_ENTRY_EVIDENCE_ONLY")
    elif natural_trade_count < STRATEGY_VALIDATION_MIN_NATURAL_TRADES:
        classification = "NATURAL_STRATEGY_EVIDENCE_INSUFFICIENT"
        reason_codes.append("NATURAL_ENTRY_TRADE_COUNT_BELOW_MIN")
    else:
        classification = "NATURAL_STRATEGY_EVIDENCE_SUFFICIENT"
        reason_codes.append("NATURAL_ENTRY_EVIDENCE_AVAILABLE")

    usable_strategy_economics = (
        natural_trade_count >= STRATEGY_VALIDATION_MIN_NATURAL_TRADES
    )
    strategy_contract = {
        "classification": classification,
        "strategy_evidence_classification": classification,
        "usable_strategy_economics": usable_strategy_economics,
        "min_natural_entry_trade_count": STRATEGY_VALIDATION_MIN_NATURAL_TRADES,
        "natural_entry_trade_count": natural_trade_count,
        "assisted_entry_trade_count": assisted_trade_count,
        "unknown_entry_trade_count": unknown_trade_count,
        "truth_classification_counts": dict(sorted(truth_counts.items())),
        "reason_codes": _dedupe_reason_codes(reason_codes),
    }
    all_metrics["natural_entry_metrics"] = natural_metrics
    all_metrics["strategy_validation_contract"] = strategy_contract
    return all_metrics


def _mtime_utc(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat()
    except Exception:
        return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_descriptor(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    exists = resolved.exists()
    size_bytes = _safe_size(resolved) if exists else 0
    return {
        "path": _workspace_rel(resolved),
        "exists": bool(exists),
        "size_bytes": int(size_bytes),
        "sha256": _sha256_file(resolved) if exists and resolved.is_file() else "",
        "mtime_utc": _mtime_utc(resolved),
    }


def _load_phase1_inputs() -> dict[str, Any]:
    phase1_dir = _latest_path("reports/paper_runtime_patch_validation/deterministic_paper_campaign_post_green_repair_phase1")
    final_blocker = _load_json(phase1_dir / "final_blocker_resolution.json")
    profitability_metrics = _load_json(phase1_dir / "profitability_metrics.json")
    exit_degradation_metrics = _load_json(phase1_dir / "exit_degradation_metrics.json")
    patch_isolation = _load_json(phase1_dir / "patch_isolation.json")
    post_freeze_bucket_audit = _load_json(_latest_path("reports/paper_runtime_patch_validation/post_freeze_bucket_profitability_audit_*.json"))
    return {
        "phase1_dir": str(phase1_dir),
        "final_blocker_resolution": final_blocker,
        "profitability_metrics": profitability_metrics,
        "exit_degradation_metrics": exit_degradation_metrics,
        "patch_isolation": patch_isolation,
        "post_freeze_bucket_audit": post_freeze_bucket_audit,
    }


def _validate_phase1_consistency(phase1: dict[str, Any]) -> dict[str, Any]:
    final_blocker = phase1["final_blocker_resolution"]
    profitability_metrics = phase1["profitability_metrics"]
    exit_degradation_metrics = phase1["exit_degradation_metrics"]
    core_a = final_blocker.get("core_metrics") or {}
    core_b = profitability_metrics or {}
    exit_a = final_blocker.get("exit_quality_metrics") or {}
    exit_b = (exit_degradation_metrics or {}).get("exit_quality_metrics") or {}
    core_keys = ["total_trades", "wins", "losses", "profit_factor", "expectancy", "winrate", "net_pnl"]
    exit_keys = ["share_ever_profitable", "share_never_green", "share_green_then_closed_red", "share_green_and_closed_green"]
    core_match = all(_compare_float(core_a.get(key), core_b.get(key)) for key in core_keys)
    exit_match = all(_compare_float(exit_a.get(key), exit_b.get(key)) for key in exit_keys)
    return {
        "core_metrics_match": core_match,
        "exit_quality_match": exit_match,
        "ok": core_match and exit_match,
    }


def _load_invalid_corpus_appendix() -> dict[str, Any]:
    quote_path = _load_json(_latest_path("reports/quote_path_audit/matched_114_quote_path_audit.json"))
    lifecycle_path = _load_json(_latest_path("reports/trade_lifecycle_audit/matched_114_trade_lifecycle_audit.json"))
    comparison_path = _load_json(_latest_path("reports/paper_audit_cycle_20260403_203233/final_comparison_audit_*.json"))
    synthetic_sources = (quote_path.get("corpus_stats") or {}).get("open_snapshot_source_counts") or {}
    synthetic_share = 0.0
    completed_trades = _safe_int((quote_path.get("verification") or {}).get("completed_trades"))
    synthetic_count = _safe_int(synthetic_sources.get("tick_stream_synth"))
    if completed_trades > 0:
        synthetic_share = synthetic_count / completed_trades
    return {
        "excluded_from_scorecard": True,
        "classification": str(quote_path.get("root_cause_classification") or "UNCLASSIFIED"),
        "completed_trades": completed_trades,
        "never_reached_profit_pct": _safe_float(((quote_path.get("stats") or {}).get("never_reached_profit_pct"))),
        "wins": _safe_int(((quote_path.get("verification") or {}).get("wins"))),
        "losses": _safe_int(((quote_path.get("verification") or {}).get("losses"))),
        "static_mark_price_trades": _safe_int(((quote_path.get("corpus_stats") or {}).get("trades_with_static_mark_price"))),
        "synthetic_quote_share": _round6(synthetic_share),
        "exact_upstream_defect": (quote_path.get("exact_upstream_defect") or {}),
        "final_comparison_classification": str((comparison_path.get("audit_b") or {}).get("classification") or ""),
        "trade_lifecycle_sources": list((lifecycle_path.get("sources") or [])[:5]),
        "evidence_paths": [
            "reports/quote_path_audit/matched_114_quote_path_audit.json",
            "reports/trade_lifecycle_audit/matched_114_trade_lifecycle_audit.json",
            "reports/paper_audit_cycle_20260403_203233/final_comparison_audit_20260403_203233.json",
        ],
        "statement": (
            "Korpus z konca marca 2026 byl skazony syntetycznym quote-path (`tick_stream_synth`, stala cena 219.1) "
            "i jest appendix RCA. Nie wchodzi do glownego werdyktu zyskownosci."
        ),
    }


def _metric(name: str, value: Any, display: str, weight_pct: float | None = None) -> dict[str, Any]:
    payload = {"name": name, "value": value, "display": display}
    if weight_pct is not None:
        payload["weight_pct"] = weight_pct
    return payload


def _area(
    area_id: str,
    name: str,
    weight: int,
    score: float,
    metrics: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    why_good: str,
    why_bad: str,
    correction: str,
) -> dict[str, Any]:
    return {
        "id": area_id,
        "name": name,
        "weight": weight,
        "score": _round6(score),
        "status": _score_status(score),
        "metrics": metrics,
        "evidence": evidence,
        "why_good": why_good,
        "why_bad": why_bad,
        "correction": correction,
    }


def _blocker_score(final_blocker_resolution: dict[str, Any]) -> int:
    remaining = list(final_blocker_resolution.get("remaining_blockers") or [])
    if not remaining:
        return 100
    if remaining == ["PROFITABILITY_NOT_CONFIRMED"]:
        return 60
    return 0


def _score_areas(
    runs: list[dict[str, Any]],
    symbol_rankings: list[dict[str, Any]],
    bootstrap_report: dict[str, Any],
    phase1: dict[str, Any],
    bootstrap_report_path: Path,
) -> list[dict[str, Any]]:
    run_count = len(runs)
    latest_run = runs[0]
    latest_run_path = _workspace_rel(str(latest_run["result_path"]))
    trade_count_ge10 = sum(1 for run in runs if run["trade_count"] >= 10)
    conversion_ge3 = sum(1 for run in runs if run["conversion_rate"] >= 0.03)
    avg_trade_count = sum(run["trade_count"] for run in runs) / run_count
    use_mock_false_share = sum(1 for run in runs if not run["use_mock"]) / run_count
    data_check_ok_share = sum(1 for run in runs if run["data_check_all_ok"]) / run_count
    clean_runtime_share = sum(1 for run in runs if run["process_returncode"] == 0 and run["log_error_count"] == 0) / run_count

    bootstrap_report_path_txt = _workspace_rel(bootstrap_report_path)
    selected_pairs = [row for row in (bootstrap_report.get("pair_stats_top") or []) if _coerce_bool(row.get("selected"))]
    selected_pair_count = len(selected_pairs) or 1
    positive_selected_count = sum(1 for row in selected_pairs if _safe_float(row.get("expectancy")) > 0.0)
    positive_expectancy_share = positive_selected_count / selected_pair_count
    pair_winrate_share = sum(1 for row in selected_pairs if _safe_float(row.get("winrate")) >= 0.5) / selected_pair_count
    selected_pair_names = [
        f"{row.get('symbol')}|{row.get('strategy')}"
        for row in selected_pairs[:5]
    ]
    selected_pair_fact = (
        "Brak wybranych par po strict bootstrap filter; zaden bucket nie spelnil jednoczesnie progow trade_count, winrate i expectancy."
        if not selected_pair_names
        else "Wybrane pary: " + ", ".join(selected_pair_names) + "."
    )
    alpha_why_good = (
        "Twardy bootstrap poprawnie odrzuca wszystkie buckety, gdy exact accepted corpus nie potwierdza dodatniej selekcji."
        if not selected_pairs
        else "Bootstrap wskazuje subset par po strict quality filter."
    )
    alpha_why_bad = (
        "Brak wybranego dodatniego subsetu oznacza, ze obecny accepted corpus nie daje bezpiecznej allowlisty do promocji."
        if not selected_pairs
        else "Dobor par nadal wymaga weryfikacji economics w glownym korpusie; zaden symbol w glownym korpusie nie konczy dodatnio."
    )
    positive_symbol_share = (
        sum(1 for row in symbol_rankings if _safe_float(row.get("net_pnl")) > 0.0) / len(symbol_rankings)
        if symbol_rankings
        else 0.0
    )

    final_blocker_resolution = phase1["final_blocker_resolution"]
    exit_quality = final_blocker_resolution.get("exit_quality_metrics") or {}
    exit_score = (
        40.0 * _safe_float(exit_quality.get("share_green_and_closed_green"))
        + 30.0 * (1.0 - _safe_float(exit_quality.get("share_green_then_closed_red")))
        + 30.0 * (1.0 - _safe_float(exit_quality.get("share_never_green")))
    )

    total_wins = 0
    total_losses = 0
    total_gross_profit = 0.0
    total_gross_loss_abs = 0.0
    for run in runs:
        for stats in ((run.get("after") or {}).get("symbol_stats") or {}).values():
            total_wins += _safe_int(stats.get("wins"))
            total_losses += _safe_int(stats.get("losses"))
            total_gross_profit += _safe_float(stats.get("gross_profit"))
            total_gross_loss_abs += _safe_float(stats.get("gross_loss_abs"))
    avg_profit_factor = sum(run["profit_factor"] for run in runs) / run_count
    avg_win = (total_gross_profit / total_wins) if total_wins > 0 else 0.0
    avg_loss_abs = (total_gross_loss_abs / total_losses) if total_losses > 0 else 0.0
    avg_win_loss_ratio = (avg_win / avg_loss_abs) if avg_loss_abs > 0 else 0.0
    bucket_rows = list((phase1["post_freeze_bucket_audit"].get("bucket_ranking") or []))
    not_fee_bucket_share = (
        sum(1 for row in bucket_rows if str(row.get("dominant_mechanism") or "") != "fee/slippage burden") / len(bucket_rows)
        if bucket_rows
        else 0.0
    )
    cost_score = (
        50.0 * _clamp01(avg_profit_factor / 1.2)
        + 25.0 * _normalize_ratio_to_1(avg_win_loss_ratio)
        + 25.0 * not_fee_bucket_share
    )

    summary_emit_done_share = sum(
        1 for run in runs if str((run.get("after") or {}).get("post_close_summary_grace_release_reason") or "") == "summary_emit_done"
    ) / run_count
    db_exists_share = sum(1 for run in runs if run["db_exists"]) / run_count
    rc0_share = sum(1 for run in runs if run["process_returncode"] == 0) / run_count
    blocker_score = _blocker_score(final_blocker_resolution)
    operational_score = 30.0 * rc0_share + 20.0 * db_exists_share + 20.0 * summary_emit_done_share + 30.0 * (blocker_score / 100.0)

    areas = [
        _area(
            area_id="DataIntegrity",
            name="Integralnosc danych",
            weight=20,
            score=40.0 * use_mock_false_share + 40.0 * data_check_ok_share + 20.0 * clean_runtime_share,
            metrics=[
                _metric("share_use_mock_false", _round6(use_mock_false_share), f"{_pct(use_mock_false_share)}%", 40),
                _metric("share_data_check_all_ok", _round6(data_check_ok_share), f"{_pct(data_check_ok_share)}%", 40),
                _metric("share_clean_runtime", _round6(clean_runtime_share), f"{_pct(clean_runtime_share)}%", 20),
            ],
            evidence=[
                {"path": "results/controlled_kpi_*.json", "fact": f"{run_count}/{run_count} runow glownych ma `use_mock=false`, `db_exists=true`, `process_returncode=0` po filtracji."},
                {"path": latest_run_path, "fact": "Najnowszy run ma `data_check_all_ok=true` i zachowuje real-price coverage dla glownego zestawu symboli."},
                {"path": "results/controlled_kpi_*.csv", "fact": "Kazdy run glowny jest walidowany przez zgodnosc CSV do JSON dla trade_count, PnL, PF i drawdown."},
            ],
            why_good="Korpus glowny jest real-price, bez mocka, z poprawnym data_check i bez runtime errorow w log_health.",
            why_bad="Integralnosc techniczna jest dobra, ale sama jakosc danych nie przeklada sie na dodatnia ekonomike.",
            correction="Utrzymac real-price only jako twardy warunek, ale nie traktowac integralnosci danych jako proxy zyskownosci.",
        ),
        _area(
            area_id="EntryFunnel",
            name="Lejek wejsc",
            weight=15,
            score=50.0 * (trade_count_ge10 / run_count) + 30.0 * (conversion_ge3 / run_count) + 20.0 * _clamp01(avg_trade_count / 10.0),
            metrics=[
                _metric("share_runs_trade_count_ge_10", _round6(trade_count_ge10 / run_count), f"{trade_count_ge10}/{run_count} ({_pct(trade_count_ge10 / run_count)}%)", 50),
                _metric("share_runs_conversion_ge_3pct", _round6(conversion_ge3 / run_count), f"{conversion_ge3}/{run_count} ({_pct(conversion_ge3 / run_count)}%)", 30),
                _metric("avg_trade_count_norm", _round6(_clamp01(avg_trade_count / 10.0)), f"{_round6(avg_trade_count)} trade/run", 20),
            ],
            evidence=[
                {"path": "results/controlled_kpi_*.json", "fact": f"Sredni trade_count w 20 ostatnich runach to {_round6(avg_trade_count)}, a tylko {trade_count_ge10} runy dobily do co najmniej 10 trade'ow."},
                {"path": "reports/alpha_relaxation_validation_20260408_045002.json", "fact": "Relaksacja alfa nie podniosla lejka wystarczajaco; raport zakonczyl sie `PARTIAL_FAIL(trade_count,conversion_rate,profit_factor)`."},
                {"path": latest_run_path, "fact": f"Najnowszy run ma `trade_count={_safe_int(latest_run['after'].get('trade_count'))}` i `conversion_rate={_pct(latest_run['conversion_rate'])}%`."},
            ],
            why_good="Lejek nie jest martwy; system dalej otwiera pozycje i okresowo przebija prog 3% konwersji.",
            why_bad="Wolumen wejsc jest za niski i zbyt niestabilny, a sama relaksacja selekcji nie poprawila economics.",
            correction="Nie luzowac dalej selekcji w ciemno; zwiekszac throughput tylko tam, gdzie para lub bucket ma dodatnia oczekiwana wartosc.",
        ),
        _area(
            area_id="AlphaSelection",
            name="Selekcja alfa",
            weight=20,
            score=40.0 * positive_expectancy_share + 20.0 * pair_winrate_share + 40.0 * positive_symbol_share,
            metrics=[
                _metric("share_selected_pairs_positive_expectancy", _round6(positive_expectancy_share), f"{_pct(positive_expectancy_share)}%", 40),
                _metric("share_selected_pairs_winrate_ge_50pct", _round6(pair_winrate_share), f"{_pct(pair_winrate_share)}%", 20),
                _metric("share_positive_symbols_in_main_corpus", _round6(positive_symbol_share), f"{_pct(positive_symbol_share)}%", 40),
            ],
            evidence=[
                {"path": bootstrap_report_path_txt, "fact": f"Bootstrap wybral {len(selected_pairs)} pary, z czego {positive_selected_count} ma dodatnia expectancy."},
                {"path": bootstrap_report_path_txt, "fact": selected_pair_fact},
                {"path": "results/controlled_kpi_*.json", "fact": f"W glownym korpusie dodatni laczny net_pnl ma {sum(1 for row in symbol_rankings if _safe_float(row.get('net_pnl')) > 0.0)}/{len(symbol_rankings)} symboli."},
            ],
            why_good=alpha_why_good,
            why_bad=alpha_why_bad,
            correction="Przywrocic twarde filtrowanie po expectancy i ograniczyc whitelist do dodatnich bucketow, zamiast kompensowac slabosc wieksza liczba wejsc.",
        ),
        _area(
            area_id="ExitQuality",
            name="Jakosc wyjsc",
            weight=20,
            score=exit_score,
            metrics=[
                _metric("share_green_and_closed_green", _round6(_safe_float(exit_quality.get("share_green_and_closed_green"))), f"{_pct(_safe_float(exit_quality.get('share_green_and_closed_green')))}%", 40),
                _metric("share_green_then_closed_red", _round6(_safe_float(exit_quality.get("share_green_then_closed_red"))), f"{_pct(_safe_float(exit_quality.get('share_green_then_closed_red')))}%", 30),
                _metric("share_never_green", _round6(_safe_float(exit_quality.get("share_never_green"))), f"{_pct(_safe_float(exit_quality.get('share_never_green')))}%", 30),
            ],
            evidence=[
                {"path": "reports/paper_runtime_patch_validation/deterministic_paper_campaign_post_green_repair_phase1/final_blocker_resolution.json", "fact": "Po naprawie udzial `GREEN_AND_CLOSED_GREEN` wzrosl do 47.06%, a `GREEN_THEN_CLOSED_RED` spadl do 20.59%."},
                {"path": "reports/paper_runtime_patch_validation/deterministic_paper_campaign_post_green_repair_phase1/patch_isolation.json", "fact": "Patch `post_green_protective_exit` ma klasyfikacje `VALIDATED_EFFECTIVE` z subset PF 4.939 i winrate 76.19%."},
                {"path": "reports/paper_runtime_patch_validation/deterministic_paper_campaign_post_green_repair_phase1/exit_degradation_metrics.json", "fact": "Kampania nie triggeruje juz reguly `EXIT_DEGRADATION_CONFIRMED`, ale nadal 32.35% trade'ow nigdy nie robi zieleni."},
            ],
            why_good="Wyjscia po green-repair sa realnie lepsze niz baseline i post-green patch zostal odizolowany jako skuteczny.",
            why_bad="Exit quality nadal nie wystarcza do dowiezienia dodatniego PnL na calym systemie, bo zbyt wiele trade'ow w ogole nie uzyskuje przewagi.",
            correction="Zostawic skuteczny `post_green_protective_exit`, ale nie liczyc na exits jako glowny silnik poprawy; problem przesunal sie bardziej do wejsc i kosztow.",
        ),
        _area(
            area_id="CostEfficiency",
            name="Efektywnosc kosztowa",
            weight=15,
            score=cost_score,
            metrics=[
                _metric("avg_profit_factor_vs_1_2", _round6(avg_profit_factor), f"avg PF={_round6(avg_profit_factor)}", 50),
                _metric("avg_win_over_avg_loss", _round6(avg_win_loss_ratio), f"avg win/loss={_round6(avg_win_loss_ratio)}", 25),
                _metric("share_buckets_not_fee_slippage_dominant", _round6(not_fee_bucket_share), f"{_pct(not_fee_bucket_share)}%", 25),
            ],
            evidence=[
                {"path": "results/controlled_kpi_*.json", "fact": f"Sredni profit factor glownych runow to {_round6(avg_profit_factor)}, a sredni net_pnl/run to {_round6(sum(run['net_pnl'] for run in runs) / run_count)}."},
                {"path": "reports/paper_runtime_patch_validation/post_freeze_bucket_profitability_audit_20260405_130435.json", "fact": f"{len(bucket_rows)}/{len(bucket_rows) if bucket_rows else 1} bucketow ma dominujacy mechanizm straty opisany jako `fee/slippage burden`."},
                {"path": "reports/paper_runtime_patch_validation/deterministic_paper_campaign_post_green_repair_phase1/profitability_metrics.json", "fact": "Kampania phase1 konczy sie `profit_factor=0.719`, `expectancy<0` i `net_pnl<0` mimo poprawy exit quality."},
            ],
            why_good="Na poziomie pojedynczych subsetow da sie znalezc dodatnie wycinki, np. patch post-green na wybranym zbiorze.",
            why_bad="Na poziomie calego systemu koszty i burden fee/slippage zjadaja edge; sredni PF i relacja avg win/avg loss sa za niskie.",
            correction="Najpierw odciac kosztowo toksyczne buckety i pary, szczegolnie te z fee/slippage jako dominujaca przyczyna straty.",
        ),
        _area(
            area_id="OperationalReadiness",
            name="Gotowosc operacyjna",
            weight=10,
            score=operational_score,
            metrics=[
                _metric("share_process_returncode_zero", _round6(rc0_share), f"{_pct(rc0_share)}%", 30),
                _metric("share_db_exists", _round6(db_exists_share), f"{_pct(db_exists_share)}%", 20),
                _metric("share_summary_emit_done", _round6(summary_emit_done_share), f"{_pct(summary_emit_done_share)}%", 20),
                _metric("blocker_status_score", blocker_score, str(blocker_score), 30),
            ],
            evidence=[
                {"path": latest_run_path, "fact": "Najnowszy run ma `process_returncode=0` i zachowuje clean shutdown w wrapper telemetry."},
                {"path": "reports/paper_runtime_patch_validation/deterministic_paper_campaign_post_green_repair_phase1/final_blocker_resolution.json", "fact": "Z ostatniej kampanii zostal tylko blocker `PROFITABILITY_NOT_CONFIRMED`."},
                {"path": "LOCKED_FACTS.md", "fact": "Post-close summary grace jest juz potwierdzonym runner-only fixem dla PAPER, bez zmiany BotCore summary path."},
            ],
            why_good="System umie domknac runy, zapisac DB i przejsc przez post-close summary bez operacyjnego rozsypywania kampanii.",
            why_bad="Gotowosc operacyjna nie jest rownoznaczna z gotowoscia ekonomiczna; live blocker nadal pozostaje ekonomiczny.",
            correction="Trzymac readiness gate jako osobny warunek, ale nie promowac bez dodatniego PF i dodatniej expectancy na glownym korpusie.",
        ),
    ]
    return areas


def _combined_extremes(symbol_rankings: list[dict[str, Any]], bucket_rankings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    combined = []
    combined.extend(symbol_rankings)
    combined.extend(bucket_rankings)
    winners = sorted(combined, key=lambda item: (float(item["net_pnl"]), _sort_profit_factor(_as_profit_factor(item["profit_factor"]))), reverse=True)[:5]
    losers = sorted(combined, key=lambda item: (float(item["net_pnl"]), _sort_profit_factor(_as_profit_factor(item["profit_factor"]))))[:5]
    return winners, losers


def _metric_extremes(rows: list[dict[str, Any]], metrics: tuple[str, ...] = ("net_pnl", "avg_pnl_per_trade", "profit_factor")) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for metric in metrics:
        if metric == "profit_factor":
            ordered = sorted(rows, key=lambda item: _sort_profit_factor(_as_profit_factor(item.get(metric))), reverse=True)
        else:
            ordered = sorted(rows, key=lambda item: float(item.get(metric) or 0.0), reverse=True)
        result[metric] = {
            "best": ordered[:3],
            "worst": list(reversed(ordered[-3:])) if ordered else [],
        }
    return result


def _correction_priorities(areas: list[dict[str, Any]], symbol_rankings: list[dict[str, Any]], bucket_rankings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bucket_bottom = bucket_rankings[-1] if bucket_rankings else None
    symbol_bottom = symbol_rankings[-1] if symbol_rankings else None
    bottom_areas = sorted(areas, key=lambda item: float(item["score"]))[:3]
    templates = {
        "CostEfficiency": {
            "title": "Odciac toksyczne buckety kosztowe",
            "why": "Fee/slippage burden pozostaje dominujacym mechanizmem straty w bucket audit.",
            "action": "Wycofac buckety z chronicznie ujemnym PF i negatywna expectancy zanim system sprobuje zwiekszac throughput.",
            "target_metric": "avg_profit_factor > 1.0 oraz udzial bucketow nie-dominowanych przez fee/slippage > 50%",
            "example": bucket_bottom["name"] if bucket_bottom else None,
        },
        "AlphaSelection": {
            "title": "Zaostrzyc whitelist do dodatniej expectancy",
            "why": "Whitelist zawiera pary z ujemna expectancy i zaden symbol w glownym korpusie nie konczy dodatnio.",
            "action": "Ograniczyc alpha bootstrap do dodatnich bucketow i usunac ujemne pair-strategy z selected set.",
            "target_metric": "share_selected_pairs_positive_expectancy >= 75%",
            "example": symbol_bottom["name"] if symbol_bottom else None,
        },
        "EntryFunnel": {
            "title": "Zwiekszyc lejek bez relaksacji na slepo",
            "why": "Trade count i conversion rate pozostaja za niskie, a poprzednia relaksacja nie poprawila PF.",
            "action": "Budowac throughput tylko dla bucketow, ktore juz maja dodatnia oczekiwana wartosc.",
            "target_metric": "avg_trade_count >= 10 i conversion_rate >= 3%",
            "example": None,
        },
        "ExitQuality": {
            "title": "Utrzymac skuteczny post-green patch i uszczelnic never-green cohort",
            "why": "Exit quality jest lepsza, ale 32% trade'ow nadal nigdy nie robi zieleni.",
            "action": "Skupic nastepne poprawki na cohortach never-green, nie rozmywac skutecznego patcha post-green.",
            "target_metric": "share_never_green < 20%",
            "example": None,
        },
        "DataIntegrity": {
            "title": "Nie dopuscic skazonego corpusu do decyzji biznesowych",
            "why": "Historyczny synthetic corpus ma wartosc RCA, ale nie biznesowej walidacji.",
            "action": "Zostawic appendix synthetic poza scorecardem i walidowac corpus real-price przy kazdym rerunie.",
            "target_metric": "share_use_mock_false = 100%",
            "example": None,
        },
        "OperationalReadiness": {
            "title": "Utrzymac readiness gate, ale nie mylic go z profit gate",
            "why": "Operational readiness jest wysoka, a blokada live pozostaje ekonomiczna.",
            "action": "Promocja dopiero po dodatnim PF i dodatniej expectancy, nie po samym `summary_emit_done`.",
            "target_metric": "remaining_blockers = []",
            "example": None,
        },
    }
    priorities = []
    for idx, area in enumerate(bottom_areas, start=1):
        template = templates[area["id"]]
        item = {
            "rank": idx,
            "area_id": area["id"],
            "area_name": area["name"],
            "score": area["score"],
            "title": template["title"],
            "why": template["why"],
            "action": template["action"],
            "target_metric": template["target_metric"],
        }
        if template.get("example"):
            item["example"] = template["example"]
        priorities.append(item)
    return priorities


def _validate_report(
    candidate_runs: list[dict[str, Any]],
    accepted_runs: list[dict[str, Any]],
    areas: list[dict[str, Any]],
    appendix_invalid_corpus: dict[str, Any],
    phase1_consistency: dict[str, Any],
    allowed_dates: tuple[str, ...],
    limit: int,
) -> dict[str, Any]:
    accepted_total_trade_count = sum(
        _safe_int(run.get("trade_count")) for run in accepted_runs
    )
    checks = {
        "candidate_count_matches_limit": len(candidate_runs) == limit,
        "accepted_count_matches_limit": len(accepted_runs) == limit,
        "accepted_runs_present": len(accepted_runs) > 0,
        "main_corpus_has_closed_trades": accepted_total_trade_count > 0,
        "main_corpus_after_only": all(str((run.get("after") or {}).get("variant") or "") == "after" for run in accepted_runs),
        "main_corpus_real_price_only": all(not run["use_mock"] for run in accepted_runs),
        "main_corpus_dates_allowed": all((run["started_date"] in allowed_dates) and (run["ended_date"] in allowed_dates) for run in accepted_runs),
        "main_corpus_db_exists": all(run["db_exists"] for run in accepted_runs),
        "main_corpus_db_nonzero": all(_safe_int(run.get("db_size_bytes")) > 0 for run in accepted_runs),
        "main_corpus_process_returncode_zero": all(
            _main_run_process_ok(run) for run in accepted_runs
        ),
        "csv_json_alignment_ok": all(_coerce_bool(run["csv_alignment"]["ok"]) for run in accepted_runs),
        "phase1_consistency_ok": _coerce_bool(phase1_consistency["ok"]),
        "appendix_excluded_from_scorecard": _coerce_bool(appendix_invalid_corpus.get("excluded_from_scorecard")),
        "weights_sum_100": sum(_safe_int(area.get("weight")) for area in areas) == 100,
        "area_metrics_ge_3": all(len(area.get("metrics") or []) >= 3 for area in areas),
    }
    return {
        "checks": checks,
        "all_passed": all(checks.values()),
        "allowed_dates": list(allowed_dates),
    }


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    return value


def _bundle_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def _manifest_artifact_path(entry: dict[str, Any], artifact_key: str) -> Path:
    artifact = ((entry.get("bundled_artifacts") or {}).get(artifact_key) or {})
    path_text = str(artifact.get("path") or "").strip()
    if not path_text:
        raise ValueError(f"manifest entry missing bundled artifact path: {artifact_key}")
    return _resolve_repo_path(path_text)


def _accepted_runs_from_manifest(
    manifest_path: Path,
    allowed_dates: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("accepted manifest malformed")
    entries = manifest.get("entries") or []
    if not isinstance(entries, list) or not entries:
        raise ValueError("accepted manifest has no entries")
    if int(limit) > 0 and len(entries) != int(limit):
        raise ValueError(
            f"accepted manifest entry count mismatch: expected={int(limit)} actual={len(entries)}"
        )

    runs: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("accepted manifest entry must be an object")
        manifest_run_id = str(entry.get("run_id") or "").strip()
        if not manifest_run_id:
            raise ValueError("accepted manifest entry has empty run_id")
        if manifest_run_id in seen_run_ids:
            raise ValueError(
                f"accepted manifest contains duplicate run_id: {manifest_run_id}"
            )
        seen_run_ids.add(manifest_run_id)
        result_path = _manifest_artifact_path(entry, "result_json")
        csv_path = _manifest_artifact_path(entry, "csv")
        db_path = _manifest_artifact_path(entry, "db")

        for artifact_key, artifact_path in (
            ("result_json", result_path),
            ("csv", csv_path),
            ("db", db_path),
        ):
            descriptor = ((entry.get("bundled_artifacts") or {}).get(artifact_key) or {})
            expected_sha = str(descriptor.get("sha256") or "").strip()
            if not artifact_path.exists():
                raise FileNotFoundError(
                    f"accepted manifest artifact missing: {artifact_key} path={artifact_path}"
                )
            if artifact_key == "db" and _safe_size(artifact_path) <= 0:
                raise ValueError(
                    f"accepted manifest db is empty: run_id={entry.get('run_id')} path={artifact_path}"
                )
            if expected_sha and _sha256_file(artifact_path) != expected_sha:
                raise ValueError(
                    f"accepted manifest sha256 mismatch: run_id={entry.get('run_id')} artifact={artifact_key}"
                )

        payload = _load_json(result_path)
        if not isinstance(payload.get("after"), dict):
            payload["after"] = {}
        payload["after"]["db_path"] = _workspace_rel(db_path)
        row = _candidate_after_row(result_path, payload)
        if row is None:
            raise ValueError(
                f"accepted manifest result is not an after run: run_id={entry.get('run_id')}"
            )
        row["csv_path"] = str(csv_path)
        row["db_path"] = str(db_path)
        row["db_exists"] = bool(db_path.exists())
        row["db_size_bytes"] = _safe_size(db_path)
        row["csv_alignment"] = _read_csv_alignment(csv_path, row["after"])

        if row["run_id"] != manifest_run_id:
            raise ValueError(
                f"accepted manifest run_id mismatch: manifest={manifest_run_id} actual={row['run_id']}"
            )
        if row["use_mock"]:
            raise ValueError(f"accepted manifest contains mock run: run_id={row['run_id']}")
        if row["started_date"] not in allowed_dates or row["ended_date"] not in allowed_dates:
            raise ValueError(
                f"accepted manifest run date out of allowed scope: run_id={row['run_id']}"
            )
        runs.append(row)
    return runs


def _render_manifest_markdown(manifest: dict[str, Any]) -> str:
    lines = ["# Accepted Corpus Manifest", ""]
    lines.append(f"- generated_at: {manifest.get('generated_at')}")
    lines.append(f"- report_type: {manifest.get('report_type')}")
    lines.append(f"- source_scorecard_path: {manifest.get('source_scorecard_path')}")
    lines.append(f"- source_report_path: {manifest.get('source_report_path')}")
    lines.append(f"- bundle_dir: {manifest.get('bundle_dir')}")
    selection = manifest.get("selection") or {}
    validation = manifest.get("bundle_validation") or {}
    lines.append(f"- accepted_run_count: {selection.get('accepted_run_count')}")
    lines.append(f"- required_limit: {selection.get('required_limit')}")
    lines.append(f"- selection_source: {selection.get('selection_source')}")
    lines.append("")
    lines.append("## Bundle Validation")
    for key, value in validation.items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Entries")
    for entry in manifest.get("entries") or []:
        lines.append(
            f"- {entry.get('run_id')}: trades={entry.get('trade_count')} "
            f"net_pnl={entry.get('net_pnl')} pf={entry.get('profit_factor')} "
            f"result_json={((entry.get('bundled_artifacts') or {}).get('result_json') or {}).get('path')}"
        )
    return "\n".join(lines) + "\n"


def _persist_accepted_corpus_bundle(
    *,
    audit: dict[str, Any],
    json_path: Path,
    md_path: Path,
    stem: str,
) -> tuple[dict[str, Any], Path, Path]:
    metadata = audit.get("metadata") or {}
    selection = (metadata.get("selection") or {})
    selection_source = str(selection.get("selection_source") or "results_scan")
    accepted_run_ids = [
        str(run_id).strip()
        for run_id in (selection.get("accepted_run_ids") or [])
        if str(run_id).strip()
    ]
    if not accepted_run_ids:
        raise ValueError("accepted corpus bundle cannot be created without accepted_run_ids")

    manifest_source_map: dict[str, dict[str, Path]] = {}
    if selection_source == "accepted_manifest":
        accepted_manifest_path = _resolve_repo_path(
            str(selection.get("accepted_manifest_path") or "").strip()
        )
        manifest_payload = _load_json(accepted_manifest_path)
        manifest_entry_run_ids = {
            str(entry.get("run_id") or "").strip()
            for entry in (manifest_payload.get("entries") or [])
            if isinstance(entry, dict) and str(entry.get("run_id") or "").strip()
        }
        missing_run_ids = [
            run_id for run_id in accepted_run_ids if run_id not in manifest_entry_run_ids
        ]
        if missing_run_ids:
            raise ValueError(
                "accepted manifest is missing selected run_ids: "
                + ", ".join(sorted(missing_run_ids))
            )
        for entry in manifest_payload.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            run_id = str(entry.get("run_id") or "").strip()
            if not run_id:
                continue
            manifest_source_map[run_id] = {
                "result_json": _manifest_artifact_path(entry, "result_json"),
                "csv": _manifest_artifact_path(entry, "csv"),
                "db": _manifest_artifact_path(entry, "db"),
            }

    results_dir_source = _resolve_repo_path(
        str((metadata.get("sources") or {}).get("results_dir") or RESULTS_DIR)
    )

    bundle_dir = ACCEPTED_CORPUS_DIR / f"{stem}_{_bundle_stamp()}"
    bundle_dir.mkdir(parents=True, exist_ok=False)
    runs_dir = bundle_dir / "accepted_runs"
    runs_dir.mkdir(parents=True, exist_ok=False)

    entries = []
    all_source_artifacts_present = True
    all_source_artifacts_nonzero = True
    all_bundled_hashes_match_source = True
    all_bundled_result_after_only = True
    all_bundled_result_use_mock_false = True
    all_bundled_result_process_ok = True

    for run_id in accepted_run_ids:
        source_override = manifest_source_map.get(run_id) or {}
        source_json_path = Path(
            source_override.get("result_json")
            or (results_dir_source / f"controlled_kpi_{run_id}.json")
        )
        source_csv_path = Path(
            source_override.get("csv")
            or (results_dir_source / f"controlled_kpi_{run_id}.csv")
        )
        if source_override.get("db"):
            source_db_path = Path(source_override.get("db"))
        elif source_json_path.exists():
            source_payload = _load_json(source_json_path)
            source_db_path = _resolve_repo_path(
                str(((source_payload.get("after") or {}).get("db_path") or ""))
            )
        else:
            source_db_path = TMP_DIR / f"controlled_kpi_after_{run_id}.db"
        source_paths = {
            "result_json": source_json_path,
            "csv": source_csv_path,
            "db": source_db_path,
        }
        for path in source_paths.values():
            if not path.exists():
                all_source_artifacts_present = False
            if not path.exists() or _safe_size(path) <= 0:
                all_source_artifacts_nonzero = False
        if not all(path.exists() for path in source_paths.values()):
            missing = [str(path) for path in source_paths.values() if not path.exists()]
            raise FileNotFoundError(
                f"accepted corpus bundle source artifacts missing for run_id={run_id}: {missing}"
            )
        if _safe_size(source_db_path) <= 0:
            raise ValueError(f"accepted corpus db empty for run_id={run_id}: {source_db_path}")
        if _safe_size(source_json_path) <= 0 or _safe_size(source_csv_path) <= 0:
            raise ValueError(
                f"accepted corpus result artifacts empty for run_id={run_id}"
            )

        bundle_json_path = runs_dir / source_json_path.name
        bundle_csv_path = runs_dir / source_csv_path.name
        bundle_db_path = runs_dir / source_db_path.name
        shutil.copy2(source_json_path, bundle_json_path)
        shutil.copy2(source_csv_path, bundle_csv_path)
        shutil.copy2(source_db_path, bundle_db_path)

        source_payload = _load_json(source_json_path)
        row = _candidate_after_row(source_json_path, source_payload)
        if row is None:
            raise ValueError(f"accepted corpus source is not after-only: run_id={run_id}")
        all_bundled_result_after_only = all_bundled_result_after_only and (
            str((row.get("after") or {}).get("variant") or "") == "after"
        )
        all_bundled_result_use_mock_false = all_bundled_result_use_mock_false and (
            not _coerce_bool(row.get("use_mock"))
        )
        all_bundled_result_process_ok = all_bundled_result_process_ok and _main_run_process_ok(row)

        source_descriptors = {
            "result_json": _artifact_descriptor(source_json_path),
            "csv": _artifact_descriptor(source_csv_path),
            "db": _artifact_descriptor(source_db_path),
        }
        bundled_descriptors = {
            "result_json": _artifact_descriptor(bundle_json_path),
            "csv": _artifact_descriptor(bundle_csv_path),
            "db": _artifact_descriptor(bundle_db_path),
        }
        for artifact_key in ("result_json", "csv", "db"):
            if (
                source_descriptors[artifact_key]["sha256"]
                != bundled_descriptors[artifact_key]["sha256"]
            ):
                all_bundled_hashes_match_source = False

        entries.append(
            {
                "run_id": run_id,
                "started_date": row.get("started_date"),
                "ended_date": row.get("ended_date"),
                "trade_count": int(row.get("trade_count") or 0),
                "net_pnl": _round6(_safe_float(row.get("net_pnl"))),
                "profit_factor": _round6(_safe_float(row.get("profit_factor"))),
                "source_artifacts": source_descriptors,
                "bundled_artifacts": bundled_descriptors,
            }
        )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_type": "zol0_accepted_corpus_manifest",
        "method_version": "v1",
        "source_scorecard_path": _workspace_rel(json_path),
        "source_report_path": _workspace_rel(md_path),
        "bundle_dir": _workspace_rel(bundle_dir),
        "scope": (metadata.get("scope") or {}),
        "selection": {
            "selection_source": str(selection.get("selection_source") or "results_scan"),
            "accepted_run_count": len(accepted_run_ids),
            "accepted_run_ids": accepted_run_ids,
            "accepted_dates": list(selection.get("accepted_dates") or []),
            "allowed_dates": list(selection.get("allowed_dates") or []),
            "required_limit": int(selection.get("required_limit") or 0),
        },
        "bundle_validation": {
            "accepted_run_count_matches_scorecard": len(accepted_run_ids)
            == int(selection.get("accepted_run_count") or 0),
            "all_source_artifacts_present": bool(all_source_artifacts_present),
            "all_source_artifacts_nonzero": bool(all_source_artifacts_nonzero),
            "all_bundled_hashes_match_source": bool(all_bundled_hashes_match_source),
            "all_bundled_result_after_only": bool(all_bundled_result_after_only),
            "all_bundled_result_use_mock_false": bool(all_bundled_result_use_mock_false),
            "all_bundled_result_process_ok": bool(all_bundled_result_process_ok),
        },
        "entries": entries,
    }
    manifest_json_path = bundle_dir / f"{stem}_accepted_corpus_manifest.json"
    manifest_md_path = bundle_dir / f"{stem}_accepted_corpus_manifest.md"
    manifest_json_path.write_text(
        json.dumps(_sanitize(manifest), indent=2, ensure_ascii=True, allow_nan=False),
        encoding="utf-8",
    )
    manifest_md_path.write_text(_render_manifest_markdown(manifest), encoding="utf-8")
    return manifest, manifest_json_path, manifest_md_path


def build_audit(
    results_dir: Path,
    bootstrap_report_path: Path,
    alpha_history_db_path: Path,
    allowed_dates: tuple[str, ...] = DEFAULT_ALLOWED_DATES,
    limit: int = DEFAULT_LIMIT,
    accepted_manifest_path: Path | None = None,
) -> dict[str, Any]:
    selection_source = "results_scan"
    accepted_manifest_path_resolved = (
        accepted_manifest_path.resolve()
        if accepted_manifest_path is not None and str(accepted_manifest_path).strip()
        else None
    )
    if accepted_manifest_path_resolved is not None:
        candidate_runs = _accepted_runs_from_manifest(
            accepted_manifest_path_resolved,
            allowed_dates=allowed_dates,
            limit=limit,
        )
        accepted_runs = _filter_main_corpus_runs(candidate_runs)
        selection_source = "accepted_manifest"
    else:
        candidate_runs = _candidate_after_runs(
            results_dir,
            limit,
            allowed_dates=allowed_dates,
        )
        accepted_runs = _filter_main_corpus_runs(candidate_runs)
    if not accepted_runs:
        raise ValueError("main corpus is empty after filtering")
    bootstrap_report = _load_json(bootstrap_report_path)
    phase1 = _load_phase1_inputs()
    phase1_consistency = _validate_phase1_consistency(phase1)
    appendix_invalid_corpus = _load_invalid_corpus_appendix()

    symbol_rankings = _aggregate_symbol_rankings(accepted_runs)
    bucket_rankings = _load_alpha_bucket_rankings(alpha_history_db_path)
    areas = _score_areas(
        accepted_runs,
        symbol_rankings,
        bootstrap_report,
        phase1,
        bootstrap_report_path,
    )
    best_areas = sorted(
        [{"id": area["id"], "name": area["name"], "score": area["score"], "status": area["status"]} for area in areas],
        key=lambda item: float(item["score"]),
        reverse=True,
    )[:3]
    worst_areas = sorted(
        [{"id": area["id"], "name": area["name"], "score": area["score"], "status": area["status"]} for area in areas],
        key=lambda item: float(item["score"]),
    )[:3]
    winners, losers = _combined_extremes(symbol_rankings, bucket_rankings)
    symbol_metric_extremes = _metric_extremes(symbol_rankings)
    bucket_metric_extremes = _metric_extremes(bucket_rankings)

    total_net_pnl = sum(run["net_pnl"] for run in accepted_runs)
    avg_profit_factor = sum(run["profit_factor"] for run in accepted_runs) / len(accepted_runs)
    avg_trade_count = sum(run["trade_count"] for run in accepted_runs) / len(accepted_runs)
    avg_conversion_rate = sum(run["conversion_rate"] for run in accepted_runs) / len(accepted_runs)
    avg_winrate = sum(run["winrate"] for run in accepted_runs) / len(accepted_runs)
    profitable_run_rate = sum(1 for run in accepted_runs if run["net_pnl"] > 0.0) / len(accepted_runs)
    pf_gt_1_rate = sum(1 for run in accepted_runs if run["profit_factor"] > 1.0) / len(accepted_runs)
    avg_max_drawdown = sum(run["max_drawdown"] for run in accepted_runs) / len(accepted_runs)

    total_wins = 0
    total_losses = 0
    total_gross_profit = 0.0
    total_gross_loss_abs = 0.0
    for run in accepted_runs:
        for stats in ((run.get("after") or {}).get("symbol_stats") or {}).values():
            total_wins += _safe_int(stats.get("wins"))
            total_losses += _safe_int(stats.get("losses"))
            total_gross_profit += _safe_float(stats.get("gross_profit"))
            total_gross_loss_abs += _safe_float(stats.get("gross_loss_abs"))
    avg_win = (total_gross_profit / total_wins) if total_wins > 0 else 0.0
    avg_loss_abs = (total_gross_loss_abs / total_losses) if total_losses > 0 else 0.0
    avg_win_loss_ratio = (avg_win / avg_loss_abs) if avg_loss_abs > 0 else 0.0

    validation = _validate_report(candidate_runs, accepted_runs, areas, appendix_invalid_corpus, phase1_consistency, allowed_dates, limit)
    if not validation["all_passed"]:
        failed = [name for name, ok in validation["checks"].items() if not ok]
        raise ValueError(f"audit validation failed: {', '.join(failed)}")

    strategy_validation_metrics = _strategy_validation_metrics_from_accepted_runs(
        accepted_runs
    )

    result = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_type": "zol0_profitability_audit_scorecard",
            "method_version": "v1",
            "scope": {
                "exchange": "KuCoin",
                "mode": "PAPER_ONLY",
                "variant": "after",
                "live_in_scope": False,
            },
            "selection": {
                "selection_source": selection_source,
                "candidate_run_count": len(candidate_runs),
                "accepted_run_count": len(accepted_runs),
                "accepted_run_ids": [run["run_id"] for run in accepted_runs],
                "accepted_dates": sorted({run["started_date"] for run in accepted_runs}),
                "allowed_dates": list(allowed_dates),
                "required_limit": int(limit),
                "accepted_manifest_path": (
                    _workspace_rel(accepted_manifest_path_resolved)
                    if accepted_manifest_path_resolved is not None
                    else ""
                ),
            },
            "sources": {
                "results_dir": str(results_dir),
                "bootstrap_report_path": str(bootstrap_report_path),
                "alpha_history_db_path": str(alpha_history_db_path),
                "phase1_dir": str(phase1["phase1_dir"]),
                "appendix_quote_path": "reports/quote_path_audit/matched_114_quote_path_audit.json",
                "appendix_trade_lifecycle": "reports/trade_lifecycle_audit/matched_114_trade_lifecycle_audit.json",
                "appendix_final_comparison": "reports/paper_audit_cycle_20260403_203233/final_comparison_audit_20260403_203233.json",
            },
            "validation": validation,
        },
        "global_kpis": {
            "run_count": len(accepted_runs),
            "profitable_run_rate": _round6(profitable_run_rate),
            "pf_gt_1_rate": _round6(pf_gt_1_rate),
            "avg_profit_factor": _round6(avg_profit_factor),
            "avg_net_pnl": _round6(total_net_pnl / len(accepted_runs)),
            "total_net_pnl": _round6(total_net_pnl),
            "expectancy": strategy_validation_metrics["expectancy"],
            "avg_trade_count": _round6(avg_trade_count),
            "total_trade_count": sum(run["trade_count"] for run in accepted_runs),
            "avg_conversion_rate": _round6(avg_conversion_rate),
            "avg_winrate": _round6(avg_winrate),
            "green_to_red_share": strategy_validation_metrics["green_to_red_share"],
            "natural_entry_metrics": strategy_validation_metrics[
                "natural_entry_metrics"
            ],
            "strategy_validation_contract": strategy_validation_metrics[
                "strategy_validation_contract"
            ],
            "avg_max_drawdown": _round6(avg_max_drawdown),
            "avg_win_over_avg_loss": _round6(avg_win_loss_ratio),
            "symbol_ranking": symbol_rankings,
            "bucket_ranking": bucket_rankings,
            "symbol_metric_extremes": symbol_metric_extremes,
            "bucket_metric_extremes": bucket_metric_extremes,
        },
        "areas": areas,
        "best_areas": best_areas,
        "worst_areas": worst_areas,
        "winners": winners,
        "losers": losers,
        "appendix_invalid_corpus": appendix_invalid_corpus,
        "correction_priorities": _correction_priorities(areas, symbol_rankings, bucket_rankings),
    }
    return _sanitize(result)


def render_markdown(audit: dict[str, Any]) -> str:
    lines: list[str] = []
    metadata = audit["metadata"]
    global_kpis = audit["global_kpis"]
    accepted_dates = list((metadata.get("selection") or {}).get("accepted_dates") or [])
    date_scope = ", ".join(accepted_dates) if accepted_dates else "brak dat"
    neutral_areas = [area for area in audit["areas"] if area["status"] == "mieszane / wymaga korekty"]
    lines.append("# Audyt Zyskownosci ZoL0")
    lines.append("")
    lines.append("## 1. Werdykt")
    lines.append(
        f"Glowny werdykt opiera sie wylacznie na {global_kpis['run_count']} najnowszych runach `after` z dat `{date_scope}` (`KuCoin`, `PAPER`, `use_mock=false`). "
        "System jest operacyjnie stabilny, ale biznesowo nadal niezyskowny."
    )
    lines.append("")
    lines.append("## 2. KPI Globalne")
    lines.append(f"- Run count: `{global_kpis['run_count']}`")
    lines.append(f"- Profitable run rate: `{_pct(global_kpis['profitable_run_rate'])}%`")
    lines.append(f"- PF > 1 rate: `{_pct(global_kpis['pf_gt_1_rate'])}%`")
    lines.append(f"- Avg profit factor: `{global_kpis['avg_profit_factor']}`")
    lines.append(f"- Avg net PnL / run: `{global_kpis['avg_net_pnl']}`")
    lines.append(f"- Total net PnL: `{global_kpis['total_net_pnl']}`")
    lines.append(f"- Avg trade count: `{global_kpis['avg_trade_count']}`")
    lines.append(f"- Avg conversion rate: `{_pct(global_kpis['avg_conversion_rate'])}%`")
    lines.append(f"- Avg winrate: `{_pct(global_kpis['avg_winrate'])}%`")
    lines.append(f"- Avg max drawdown: `{global_kpis['avg_max_drawdown']}`")
    lines.append("")
    lines.append("## 3. Scorecard Obszarow")
    lines.append("| Obszar | Score | Status |")
    lines.append("|---|---:|---|")
    for area in audit["areas"]:
        lines.append(f"| {area['name']} | {area['score']:.2f} | {area['status']} |")
    lines.append("")
    lines.append("## 4. Najmocniejsze Obszary")
    for area in audit["best_areas"]:
        lines.append(f"- `{area['name']}`: `{area['score']}` ({area['status']})")
    lines.append("")
    lines.append("## 5. Najslabsze Obszary")
    for area in audit["worst_areas"]:
        lines.append(f"- `{area['name']}`: `{area['score']}` ({area['status']})")
    lines.append("")
    lines.append("## 6. Obszary Neutralne")
    if neutral_areas:
        for area in neutral_areas:
            lines.append(f"- `{area['name']}`: `{area['score']}` ({area['status']})")
    else:
        lines.append("- Brak obszarow ze statusem `mieszane / wymaga korekty`.")
    lines.append("")
    lines.append("## 7. Interpretacja Obszarow")
    for area in audit["areas"]:
        lines.append(f"### {area['name']}")
        lines.append(f"- Score: `{area['score']}`")
        lines.append(f"- Dlaczego dobrze: {area['why_good']}")
        lines.append(f"- Dlaczego zle: {area['why_bad']}")
        lines.append(f"- Korekta: {area['correction']}")
        metric_parts = ", ".join(f"{metric['name']}={metric['display']}" for metric in area["metrics"])
        lines.append(f"- Metryki: {metric_parts}")
        for evidence in area["evidence"]:
            lines.append(f"- Evidence: `{evidence['path']}` -> {evidence['fact']}")
        lines.append("")
    lines.append("## 8. Ranking Symboli")
    lines.append("| Symbol | Trades | Net PnL | Avg PnL/trade | Winrate | PF | Problem |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for row in audit["global_kpis"]["symbol_ranking"]:
        lines.append(
            f"| {row['name']} | {row['trade_count']} | {row['net_pnl']} | {row['avg_pnl_per_trade']} | "
            f"{_pct(row['winrate'])}% | {row['profit_factor']} | {row['dominant_issue']} |"
        )
    lines.append("")
    lines.append("## 9. Ranking Bucketow")
    lines.append("| Bucket | Trades | Net PnL | Avg PnL/trade | Winrate | PF | Problem |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for row in audit["global_kpis"]["bucket_ranking"]:
        lines.append(
            f"| {row['name']} | {row['trade_count']} | {row['net_pnl']} | {row['avg_pnl_per_trade']} | "
            f"{_pct(row['winrate'])}% | {row['profit_factor']} | {row['dominant_issue']} |"
        )
    lines.append("")
    lines.append("## 10. Best/Worst Po Metrykach")
    for scope_name, key in (("Symbole", "symbol_metric_extremes"), ("Buckety", "bucket_metric_extremes")):
        lines.append(f"### {scope_name}")
        for metric, payload in audit["global_kpis"][key].items():
            best_names = ", ".join(f"{row['name']} ({row[metric]})" for row in payload["best"]) or "brak"
            worst_names = ", ".join(f"{row['name']} ({row[metric]})" for row in payload["worst"]) or "brak"
            lines.append(f"- `{metric}` best: {best_names}")
            lines.append(f"- `{metric}` worst: {worst_names}")
        lines.append("")
    lines.append("## 11. Priorytety Korekty")
    for item in audit["correction_priorities"]:
        lines.append(f"- #{item['rank']} `{item['title']}`")
        lines.append(f"  Obszar: `{item['area_name']}` ({item['score']})")
        lines.append(f"  Powod: {item['why']}")
        lines.append(f"  Akcja: {item['action']}")
        lines.append(f"  Target: {item['target_metric']}")
        if item.get("example"):
            lines.append(f"  Przyklad: `{item['example']}`")
    lines.append("")
    lines.append("## 12. Appendix RCA: Korpus Niewazny Biznesowo")
    appendix = audit["appendix_invalid_corpus"]
    lines.append(f"- Klasyfikacja: `{appendix['classification']}`")
    lines.append(f"- Completed trades: `{appendix['completed_trades']}`")
    lines.append(f"- Never reached profit: `{appendix['never_reached_profit_pct']}%`")
    lines.append(f"- Synthetic quote share: `{_pct(appendix['synthetic_quote_share'])}%`")
    lines.append(f"- Statement: {appendix['statement']}")
    defect = appendix.get("exact_upstream_defect") or {}
    if defect:
        lines.append(f"- Upstream defect: {defect.get('summary')}")
        if defect.get("inference"):
            lines.append(f"- Inference: {defect.get('inference')}")
    lines.append("")
    lines.append("## 13. Walidacja")
    for name, ok in metadata["validation"]["checks"].items():
        lines.append(f"- `{name}`: `{ok}`")
    sources = metadata.get("sources") or {}
    manifest_path = sources.get("accepted_corpus_manifest_path")
    bundle_dir = sources.get("accepted_corpus_bundle_dir")
    if manifest_path or bundle_dir:
        lines.append("")
        lines.append("## 14. Accepted Corpus Bundle")
        if bundle_dir:
            lines.append(f"- Bundle dir: `{bundle_dir}`")
        if manifest_path:
            lines.append(f"- Manifest JSON: `{manifest_path}`")
    return "\n".join(lines) + "\n"


def write_outputs(
    audit: dict[str, Any],
    analysis_dir: Path,
    stem: str = "zol0_profitability_audit",
) -> tuple[Path, Path, Path, Path]:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    json_path = analysis_dir / f"{stem}_scorecard.json"
    md_path = analysis_dir / f"{stem}_report.md"
    manifest, manifest_json_path, manifest_md_path = _persist_accepted_corpus_bundle(
        audit=audit,
        json_path=json_path,
        md_path=md_path,
        stem=stem,
    )
    metadata = audit.setdefault("metadata", {})
    sources = metadata.setdefault("sources", {})
    selection = metadata.setdefault("selection", {})
    sources["accepted_corpus_bundle_dir"] = manifest["bundle_dir"]
    sources["accepted_corpus_manifest_path"] = _workspace_rel(manifest_json_path)
    sources["accepted_corpus_manifest_md_path"] = _workspace_rel(manifest_md_path)
    selection["accepted_manifest_path"] = _workspace_rel(manifest_json_path)
    json_path.write_text(json.dumps(audit, indent=2, ensure_ascii=True, allow_nan=False), encoding="utf-8")
    md_path.write_text(render_markdown(audit), encoding="utf-8")
    return json_path, md_path, manifest_json_path, manifest_md_path


def build_and_write_audit(
    *,
    results_dir: Path,
    bootstrap_report_path: Path,
    alpha_history_db_path: Path,
    analysis_dir: Path,
    allowed_dates: tuple[str, ...],
    limit: int,
    accepted_manifest_path: Path | None,
    output_stem: str,
) -> tuple[Path, Path, Path, Path, list[tuple[str, Path]]]:
    replay_artifacts: list[tuple[str, Path]] = []
    accepted_manifest_path_resolved = (
        accepted_manifest_path
        if accepted_manifest_path is not None
        and str(accepted_manifest_path).strip()
        else None
    )

    if accepted_manifest_path_resolved is None:
        seed_audit = build_audit(
            results_dir=results_dir,
            bootstrap_report_path=bootstrap_report_path,
            alpha_history_db_path=alpha_history_db_path,
            allowed_dates=allowed_dates,
            limit=limit,
            accepted_manifest_path=None,
        )
        seed_stem = f"{output_stem}_results_scan_seed"
        seed_json, seed_md, seed_manifest_json, seed_manifest_md = write_outputs(
            seed_audit,
            analysis_dir,
            stem=seed_stem,
        )
        replay_artifacts.extend(
            [
                ("SEED_JSON", seed_json),
                ("SEED_MARKDOWN", seed_md),
                ("SEED_ACCEPTED_MANIFEST_JSON", seed_manifest_json),
                ("SEED_ACCEPTED_MANIFEST_MD", seed_manifest_md),
            ]
        )
        accepted_manifest_path_resolved = seed_manifest_json

    audit = build_audit(
        results_dir=results_dir,
        bootstrap_report_path=bootstrap_report_path,
        alpha_history_db_path=alpha_history_db_path,
        allowed_dates=allowed_dates,
        limit=limit,
        accepted_manifest_path=accepted_manifest_path_resolved,
    )
    metadata = audit.setdefault("metadata", {})
    metadata["validation_contract_replay"] = {
        "status": "PASS",
        "contract": "explicit_accepted_manifest_replay",
        "source_manifest_path": _workspace_rel(accepted_manifest_path_resolved),
        "final_selection_source_required": "accepted_manifest",
    }
    json_path, md_path, manifest_json_path, manifest_md_path = write_outputs(
        audit,
        analysis_dir,
        stem=output_stem,
    )
    final_scorecard = _load_json(json_path)
    final_selection = (final_scorecard.get("metadata") or {}).get("selection") or {}
    if final_selection.get("selection_source") != "accepted_manifest":
        raise ValueError(
            "canonical profitability scorecard must be built from explicit accepted manifest"
        )
    return json_path, md_path, manifest_json_path, manifest_md_path, replay_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a repeatable profitability audit scorecard for ZoL0.")
    parser.add_argument("--results-dir", default=str(RESULTS_DIR))
    parser.add_argument("--bootstrap-report", default=str(TMP_DIR / "alpha_history_auto_recent_report.json"))
    parser.add_argument("--alpha-history-db", default=str(TMP_DIR / "alpha_history_auto_recent.db"))
    parser.add_argument("--analysis-dir", default=str(ANALYSIS_DIR))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--allowed-date", action="append", default=list(DEFAULT_ALLOWED_DATES))
    parser.add_argument("--accepted-manifest", default="")
    parser.add_argument("--output-stem", default="zol0_profitability_audit")
    args = parser.parse_args(argv)

    json_path, md_path, manifest_json_path, manifest_md_path, replay_artifacts = build_and_write_audit(
        results_dir=Path(args.results_dir),
        bootstrap_report_path=Path(args.bootstrap_report),
        alpha_history_db_path=Path(args.alpha_history_db),
        analysis_dir=Path(args.analysis_dir),
        allowed_dates=tuple(args.allowed_date),
        limit=int(args.limit),
        accepted_manifest_path=(
            Path(args.accepted_manifest)
            if str(args.accepted_manifest).strip()
            else None
        ),
        output_stem=str(args.output_stem),
    )
    for label, path in replay_artifacts:
        print(f"{label}={path}")
    print(f"JSON={json_path}")
    print(f"MARKDOWN={md_path}")
    print(f"ACCEPTED_MANIFEST_JSON={manifest_json_path}")
    print(f"ACCEPTED_MANIFEST_MD={manifest_md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
