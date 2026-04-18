import json
import logging
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse


def _parse_json(raw):
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        obj = json.loads(raw)
    except Exception:
        return {}
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, str):
        try:
            obj2 = json.loads(obj)
            return obj2 if isinstance(obj2, dict) else {}
        except Exception:
            return {}
    return {}


def _parse_ts(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            if value > 1e12:
                return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
            if value > 1e10:
                return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return None
        try:
            dt = datetime.fromisoformat(txt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception as exc:
            logging.debug("prelive_gate: ISO timestamp parse failed: %s", exc)
        try:
            x = float(txt)
            return _parse_ts(x)
        except Exception:
            return None
    return None


def _resolve_sqlite_path(database_url: str):
    database_url = str(database_url or "").strip()
    if not database_url:
        return None
    if not database_url.startswith("sqlite"):
        return None
    raw = None
    if database_url.startswith("sqlite:///"):
        raw = database_url[len("sqlite:///") :]
    elif database_url.startswith("sqlite://"):
        raw = database_url[len("sqlite://") :]
    if raw is None:
        parsed = urlparse(database_url)
        raw = parsed.path or ""
    if raw.startswith("/./"):
        raw = raw[1:]
    if raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
        # Windows absolute path encoded as /C:/...
        raw = raw[1:]
    p = Path(raw)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def _max_drawdown(values):
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        denominator = abs(peak)
        if denominator <= 0:
            denominator = max((abs(item) for item in values), default=0.0)
        if denominator > 0:
            dd = (peak - v) / denominator
            if dd > max_dd:
                max_dd = dd
    return max_dd


def evaluate_live_readiness(
    database_url=None,
    lookback_hours=24,
    min_trades=20,
    min_profit_factor=1.05,
    min_winrate=0.45,
    max_drawdown=0.03,
):
    database_url = str(
        database_url or os.environ.get("DATABASE_URL", "sqlite:///./zol0.db")
    ).strip()
    db_path = _resolve_sqlite_path(database_url)
    if db_path is None:
        return {
            "passed": False,
            "reason": "non_sqlite_database_not_supported_by_prelive_gate",
            "database_url": database_url,
        }
    if not db_path.exists():
        return {
            "passed": False,
            "reason": "database_not_found",
            "database_path": str(db_path),
        }

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(hours=float(lookback_hours))

    realized = []
    equity = []
    panic_exit_count = 0
    query_errors = []

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    try:
        try:
            cur.execute("SELECT timestamp, event, details FROM logs")
            for ts_raw, event, details_raw in cur.fetchall():
                ts = _parse_ts(ts_raw)
                if ts is None or ts < start_dt:
                    continue
                ev = str(event or "")
                details = _parse_json(details_raw)
                if ev == "position_close":
                    pnl = details.get("realized_pnl")
                    if pnl is None and isinstance(details.get("position"), dict):
                        pnl = details["position"].get("realized_pnl")
                    try:
                        pnl_f = float(pnl)
                    except Exception:
                        continue
                    if math.isfinite(pnl_f):
                        realized.append(pnl_f)
                if ev == "panic_exit":
                    panic_exit_count += 1
        except Exception as exc:
            query_errors.append(
                {
                    "query": "logs",
                    "error": str(exc),
                    "error_class": type(exc).__name__,
                }
            )
            logging.warning("prelive_gate: logs query failed: %s", exc)
        try:
            cur.execute("SELECT timestamp, equity FROM equity")
            for ts_raw, eq_raw in cur.fetchall():
                ts = _parse_ts(ts_raw)
                if ts is None or ts < start_dt:
                    continue
                try:
                    eq_f = float(eq_raw)
                except Exception:
                    continue
                if math.isfinite(eq_f):
                    equity.append((ts, eq_f))
        except Exception as exc:
            query_errors.append(
                {
                    "query": "equity",
                    "error": str(exc),
                    "error_class": type(exc).__name__,
                }
            )
            logging.warning("prelive_gate: equity query failed: %s", exc)
    finally:
        con.close()

    realized = list(realized)
    wins = sum(1 for x in realized if x > 0)
    trade_count = len(realized)
    net_pnl = sum(realized)
    gross_profit = sum(x for x in realized if x > 0)
    gross_loss_abs = abs(sum(x for x in realized if x < 0))
    if gross_loss_abs > 0:
        profit_factor = gross_profit / gross_loss_abs
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0
    winrate = (wins / trade_count) if trade_count > 0 else 0.0
    equity_sorted = [x[1] for x in sorted(equity, key=lambda x: x[0])]
    dd = _max_drawdown(equity_sorted)

    checks = {
        "trade_count": trade_count >= min_trades,
        "profit_factor": profit_factor >= min_profit_factor,
        "winrate": winrate >= min_winrate,
        "max_drawdown": dd <= max_drawdown,
        "panic_exit": panic_exit_count == 0,
    }
    passed = all(checks.values())

    return {
        "passed": passed,
        "database_path": str(db_path),
        "lookback_hours": float(lookback_hours),
        "query_errors": query_errors,
        "kpi": {
            "trade_count": trade_count,
            "net_pnl": net_pnl,
            "winrate": winrate,
            "profit_factor": profit_factor,
            "max_drawdown": dd,
            "panic_exit_count": panic_exit_count,
        },
        "thresholds": {
            "min_trades": min_trades,
            "min_profit_factor": min_profit_factor,
            "min_winrate": min_winrate,
            "max_drawdown": max_drawdown,
            "panic_exit_count": 0,
        },
        "checks": checks,
    }
