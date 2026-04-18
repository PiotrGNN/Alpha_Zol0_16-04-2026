from fastapi import FastAPI
from contextlib import asynccontextmanager

# flake8: noqa: E501  # disable line-length warnings for this file (many long log strings)

import os
import re
import json
import math
import csv
import time
import threading
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import Query, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import desc

# Import run_bot lazily inside endpoint to avoid circular imports
# (will be imported only when /start-live is invoked)

from core.PositionManager import PositionManager
from core.DynamicStrategyRouter import DynamicStrategyRouter
from core.MarketDataFetcher import MarketDataFetcher
from core.kucoin_client import KucoinClient, normalize_balances, normalize_symbol
from core.kucoin_futures_client import KucoinFuturesClient, is_futures_symbol
from utils.time import to_ms
from utils.paper_gate import get_state as get_paper_gate_state
from utils.paper_gate import reset_state as reset_paper_gate
from core.db_models import (
    init_db,
    SessionLocal,
    Decision,
    LogEntry,
    Equity,
)
from utils.health_check import check_api, check_bot_status, check_ticks


def _extract_fill_items(resp):
    if not isinstance(resp, dict):
        return []
    data = resp.get("data")
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
    if isinstance(data, list):
        return data
    return []


def _summarize_fills(items):
    total_size = 0.0
    total_value = 0.0
    fee_total = 0.0
    for item in items or []:
        try:
            price = float(item.get("price"))
        except Exception:
            price = None
        try:
            size = float(item.get("size"))
        except Exception:
            size = None
        if price is not None and size is not None:
            total_size += size
            total_value += price * size
        try:
            fee = item.get("fee")
            if fee is None:
                fee = item.get("closeFeePay")
            if fee is None:
                fee = item.get("openFeePay")
            fee_total += float(fee) if fee is not None else 0.0
        except Exception:
            pass
    avg_price = (total_value / total_size) if total_size > 0 else None
    return (
        avg_price,
        fee_total if fee_total else None,
        total_size if total_size else None,
    )


def _report_output_dir():
    base = os.environ.get("AUTO_REPORT_DIR", "reports/auto")
    try:
        out_dir = Path(base)
        if not out_dir.is_absolute():
            out_dir = Path(__file__).resolve().parent / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir
    except Exception:
        return Path(__file__).resolve().parent


def _write_report_files(payload, prefix="trade_report"):
    out_dir = _report_output_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"{prefix}_{stamp}.json"
    csv_path = out_dir / f"{prefix}_{stamp}.csv"
    trades = payload.get("trades") if isinstance(payload, dict) else None
    if not isinstance(trades, list):
        trades = []
    try:
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logging.warning(f"auto_report json write failed: {e}")
    try:
        fieldnames = [
            "symbol",
            "side",
            "amount",
            "entry_price",
            "close_price",
            "entry_fill_price",
            "exit_fill_price",
            "entry_order_id",
            "close_order_id",
            "exit_reason",
            "realized_pnl",
            "exchange_pnl",
            "exchange_pnl_net",
            "fee_total",
            "delta",
            "timestamp",
            "close_timestamp",
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in trades:
                if isinstance(row, dict):
                    writer.writerow({k: row.get(k) for k in fieldnames})
    except Exception as e:
        logging.warning(f"auto_report csv write failed: {e}")


def _build_trades_vs_exchange_report(limit=50, use_fills=1, symbol=None):
    sym = symbol or _default_symbol()
    market_type = _resolve_market_type(sym)
    if market_type != "futures":
        raise ValueError("report supported only for futures in this API")
    db = SessionLocal()
    try:
        query = db.query(LogEntry).filter(LogEntry.event == "position_close")
        if os.environ.get("NEW_SESSION", "0") == "1":
            query = query.filter(LogEntry.timestamp >= _session_anchor())
        rows = query.order_by(desc(LogEntry.timestamp)).limit(limit).all()
        client = KucoinFuturesClient()
        report = []
        totals = {
            "trades": 0,
            "realized_pnl_total": 0.0,
            "exchange_pnl_total": 0.0,
            "exchange_pnl_net_total": 0.0,
            "delta_total": 0.0,
        }
        if isinstance(use_fills, int):
            use_fills_flag = bool(int(use_fills))
        else:
            use_fills_flag = bool(use_fills)
        for row in rows:
            try:
                details = json.loads(row.details) if row.details else {}
            except Exception:
                details = {}
            pos = details.get("position") if isinstance(details, dict) else None
            if not isinstance(pos, dict):
                pos = {}
            sym_row = details.get("symbol") or pos.get("symbol") or sym
            side = str(pos.get("side") or "").lower()
            amount = pos.get("amount")
            entry_price = pos.get("entry_price") or pos.get("price")
            close_price = details.get("close_price") or pos.get("close_price")
            realized_pnl = details.get("realized_pnl") or pos.get("realized_pnl")
            fee_cost = details.get("fee_cost") or pos.get("fee_cost")
            fee_open = pos.get("fee_cost_open") or details.get("fee_cost_open")
            fee_close = pos.get("fee_cost_close") or details.get("fee_cost_close")
            entry_order_id = pos.get("entry_order_id") or details.get("entry_order_id")
            close_order_id = pos.get("close_order_id") or details.get("close_order_id")
            entry_fill = pos.get("fill_price")
            exit_fill = details.get("close_fill_price") or details.get("fill_price")
            exit_reason = (
                details.get("reason")
                or details.get("exit_reason")
                or pos.get("exit_reason")
            )

            entry_fill_price = None
            entry_fee = None
            exit_fill_price = None
            exit_fee = None

            if use_fills_flag and entry_order_id:
                try:
                    resp = client.get_fills(order_id=entry_order_id, symbol=sym_row)
                    items = _extract_fill_items(resp)
                    entry_fill_price, entry_fee, _ = _summarize_fills(items)
                except Exception:
                    entry_fill_price = None
            if use_fills_flag and close_order_id:
                try:
                    resp = client.get_fills(order_id=close_order_id, symbol=sym_row)
                    items = _extract_fill_items(resp)
                    exit_fill_price, exit_fee, _ = _summarize_fills(items)
                except Exception:
                    exit_fill_price = None

            if entry_fill_price is None:
                entry_fill_price = entry_fill or entry_price
            if exit_fill_price is None:
                exit_fill_price = exit_fill or close_price

            exchange_pnl = None
            exchange_pnl_net = None
            delta = None
            try:
                if (
                    entry_fill_price is not None
                    and exit_fill_price is not None
                    and amount is not None
                ):
                    entry_fill_price = float(entry_fill_price)
                    exit_fill_price = float(exit_fill_price)
                    amount = float(amount)
                    if side in ("sell", "short"):
                        exchange_pnl = (entry_fill_price - exit_fill_price) * amount
                    else:
                        exchange_pnl = (exit_fill_price - entry_fill_price) * amount
            except Exception:
                exchange_pnl = None

            fee_total = None
            try:
                if fee_cost is not None:
                    fee_total = float(fee_cost)
                else:
                    fee_total = 0.0
                    if entry_fee is not None:
                        fee_total += float(entry_fee)
                    if exit_fee is not None:
                        fee_total += float(exit_fee)
                    if fee_total == 0.0 and (fee_open or fee_close):
                        fee_total = float(fee_open or 0.0) + float(fee_close or 0.0)
            except Exception:
                fee_total = fee_total

            if exchange_pnl is not None:
                if fee_total is not None:
                    exchange_pnl_net = exchange_pnl - float(fee_total)
                else:
                    exchange_pnl_net = exchange_pnl
            try:
                if realized_pnl is not None and exchange_pnl_net is not None:
                    delta = float(exchange_pnl_net) - float(realized_pnl)
            except Exception:
                delta = None

            ts_val = pos.get("timestamp") or row.timestamp.isoformat()
            close_ts_val = pos.get("close_timestamp") or row.timestamp.isoformat()
            report.append(
                {
                    "symbol": sym_row,
                    "side": side,
                    "amount": amount,
                    "entry_price": entry_price,
                    "close_price": close_price,
                    "entry_fill_price": entry_fill_price,
                    "exit_fill_price": exit_fill_price,
                    "entry_order_id": entry_order_id,
                    "close_order_id": close_order_id,
                    "exit_reason": exit_reason,
                    "realized_pnl": realized_pnl,
                    "exchange_pnl": exchange_pnl,
                    "exchange_pnl_net": exchange_pnl_net,
                    "fee_total": fee_total,
                    "delta": delta,
                    "timestamp": ts_val,
                    "close_timestamp": close_ts_val,
                }
            )
            totals["trades"] += 1
            try:
                if realized_pnl is not None:
                    totals["realized_pnl_total"] += float(realized_pnl)
            except Exception:
                pass
            try:
                if exchange_pnl is not None:
                    totals["exchange_pnl_total"] += float(exchange_pnl)
            except Exception:
                pass
            try:
                if exchange_pnl_net is not None:
                    totals["exchange_pnl_net_total"] += float(exchange_pnl_net)
            except Exception:
                pass
            try:
                if delta is not None:
                    totals["delta_total"] += float(delta)
            except Exception:
                pass
        return {"summary": totals, "trades": report}
    finally:
        db.close()


def _auto_report_loop():
    logging.info("auto_report loop started")
    while True:
        try:
            enabled = os.environ.get("AUTO_REPORT_ENABLE", "0") == "1"
            if not enabled:
                time.sleep(5)
                continue
            limit = int(os.environ.get("AUTO_REPORT_LIMIT", "50"))
            use_fills = int(os.environ.get("AUTO_REPORT_USE_FILLS", "1"))
            symbol = os.environ.get("AUTO_REPORT_SYMBOL") or None
            payload = _build_trades_vs_exchange_report(
                limit=limit,
                use_fills=use_fills,
                symbol=symbol,
            )
            _write_report_files(payload, prefix="trade_report")
        except Exception as e:
            logging.warning(f"auto_report failed: {e}")
        try:
            sleep_sec = max(60, int(os.environ.get("AUTO_REPORT_INTERVAL_SEC", "900")))
        except Exception:
            sleep_sec = 900
        time.sleep(sleep_sec)


def _auto_monitor_loop():
    """Background monitor: checks `net_pnl_15m` every interval and applies
    conservative corrective actions (soft reductions) or emergency `panic`
    when thresholds are exceeded. Controlled via AUTO_MONITOR_* env vars.

    Supports two autoscaler modes (configurable via AUTO_MONITOR_MODE):
      - 'pnl' (default): proportional control on smoothed net_pnl_15m (original)
      - 'hitrate': maintain a rolling hit-rate of scaled_pnl >= target
    """
    logging.info("auto_monitor loop started")
    consecutive_fail = 0
    # history for hit-rate mode (stored in app.state)
    if getattr(app.state, "autoscaler_history", None) is None:
        try:
            from collections import deque

            app.state.autoscaler_history = deque(
                maxlen=int(os.environ.get("AUTO_MONITOR_HITRATE_WINDOW", "10"))
            )
        except Exception:
            app.state.autoscaler_history = []

    while True:
        try:
            enabled = os.environ.get("AUTO_MONITOR_ENABLE", "0") == "1"
            if not enabled:
                time.sleep(5)
                continue
            interval_sec = max(
                60, int(os.environ.get("AUTO_MONITOR_INTERVAL_SEC", "900"))
            )
            target = float(os.environ.get("AUTO_MONITOR_NET_PNL_TARGET", "0.5"))
            fail_limit = int(os.environ.get("AUTO_MONITOR_FAIL_LIMIT", "3"))
            panic_threshold = float(
                os.environ.get("AUTO_MONITOR_PANIC_THRESHOLD", "-1.0")
            )
            stats = compute_stats()
            net_pnl_15m = stats.get("net_pnl_15m")

            # Update consecutive failure counter (basic check)
            if net_pnl_15m is None:
                consecutive_fail = 0
            elif net_pnl_15m >= target:
                consecutive_fail = 0
            else:
                consecutive_fail += 1
                logging.warning(
                    "auto_monitor: net_pnl_15m=%s below target=%s (count=%s)",
                    net_pnl_15m,
                    target,
                    consecutive_fail,
                )

            # Autoscaler: choose mode
            mode = os.environ.get("AUTO_MONITOR_MODE", "pnl").lower()

            if net_pnl_15m is not None:
                try:
                    base_alloc = float(os.environ.get("allocation_pct", "0.5"))
                except Exception:
                    base_alloc = 0.5
                # autoscaler state stored in app.state to survive loop iterations
                cur_scale = getattr(app.state, "autoscaler_scale", None)
                if cur_scale is None:
                    try:
                        cur_scale = float(os.environ.get("AUTO_MONITOR_SCALE", "1.0"))
                    except Exception:
                        cur_scale = 1.0
                max_scale = float(os.environ.get("AUTO_MONITOR_MAX_SCALE", "3.0"))
                min_scale = float(os.environ.get("AUTO_MONITOR_MIN_SCALE", "0.1"))
                kp = float(os.environ.get("AUTO_MONITOR_KP", "0.2"))
                ramp_pct = float(os.environ.get("AUTO_MONITOR_RAMP_PCT", "0.2"))
                alpha = float(os.environ.get("AUTO_MONITOR_SMOOTH_ALPHA", "0.4"))

                # Default smoothing preserved for 'pnl' mode
                prev_smooth = getattr(app.state, "autoscaler_smoothed_pnl", None)
                if prev_smooth is None:
                    smooth_pnl = float(net_pnl_15m)
                else:
                    smooth_pnl = alpha * float(net_pnl_15m) + (1 - alpha) * float(
                        prev_smooth
                    )

                # If hit-rate mode is requested, maintain a rolling history of
                # whether the *scaled* pnl met the numeric target; adjust scale
                # to drive the hit-rate toward AUTO_MONITOR_HITRATE_TARGET.
                if mode == "hitrate":
                    # ensure deque exists
                    history = getattr(app.state, "autoscaler_history", None)
                    try:
                        scaled_pnl = float(net_pnl_15m) * float(cur_scale)
                        current_success = scaled_pnl >= float(target)
                    except Exception:
                        current_success = False
                    # append to rolling history (support list fallback)
                    try:
                        if hasattr(history, "append"):
                            history.append(bool(current_success))
                        else:
                            history = (history or [])[-9:] + [bool(current_success)]
                            app.state.autoscaler_history = history
                    except Exception:
                        pass
                    # compute hit-rate
                    try:
                        hist_list = list(getattr(app.state, "autoscaler_history", []))
                        num_success = sum(1 for v in hist_list if v)
                        denom = max(1, len(hist_list))
                        current_hit_rate = num_success / denom
                    except Exception:
                        current_hit_rate = 0.0
                    desired_hit_rate = float(
                        os.environ.get("AUTO_MONITOR_HITRATE_TARGET", "0.10")
                    )
                    # proportional controller on hit-rate error
                    error = desired_hit_rate - current_hit_rate
                    # allow optional separate kp for hit-rate
                    try:
                        kp_hit = float(
                            os.environ.get("AUTO_MONITOR_KP_HITRATE", str(kp))
                        )
                    except Exception:
                        kp_hit = kp
                    delta_scale = kp_hit * error
                    logging.info(
                        "auto_monitor (hitrate): cur_hit=%.3f desired=%.3f "
                        "error=%.4f",
                        current_hit_rate,
                        desired_hit_rate,
                        error,
                    )
                else:
                    # default 'pnl' behaviour (proportional on smoothed pnl)
                    error = float(target) - float(smooth_pnl)
                    delta_scale = kp * error

                # limit change per step (ramp)
                max_delta = abs(ramp_pct * cur_scale)
                if delta_scale > max_delta:
                    delta_scale = max_delta
                elif delta_scale < -max_delta:
                    delta_scale = -max_delta

                new_scale = cur_scale + delta_scale
                # clamp within allowed bounds
                new_scale = max(min_scale, min(max_scale, round(new_scale, 4)))

                # compute new allocation (multiply base allocation)
                new_alloc = max(0.001, min(1.0, round(base_alloc * new_scale, 6)))

                # persist to environment and app.state
                os.environ["allocation_pct"] = str(new_alloc)
                app.state.autoscaler_scale = new_scale
                app.state.autoscaler_smoothed_pnl = smooth_pnl

                # optionally persist the scaling to config so restart
                # keeps conservative value
                try:
                    cfg_dir = Path(__file__).resolve().parent / "config"
                    cfg_path = cfg_dir / "config.yaml"
                    if cfg_path.exists():
                        txt = cfg_path.read_text(encoding="utf-8")
                        txt = re.sub(
                            r"allocation_pct:\s*\S+",
                            f"allocation_pct: {new_alloc}",
                            txt,
                        )
                        cfg_path.write_text(txt, encoding="utf-8")
                except Exception:
                    pass

                logging.info(
                    "auto_monitor: autoscaler scale=%.3f smooth_pnl=%.4f "
                    "alloc=%s (error=%.4f) mode=%s",
                    new_scale,
                    smooth_pnl,
                    new_alloc,
                    error,
                    mode,
                )

                # write runtime allocation to DB so other processes (bot) can pick it up
                try:
                    from core.db_utils import save_log_to_db

                    ok = save_log_to_db(
                        "runtime_allocation", {"allocation_pct": new_alloc}
                    )
                    if not ok:
                        logging.warning(
                            "auto_monitor: failed to persist runtime_allocation to DB (save_log_to_db returned False)"
                        )
                except Exception as e:
                    logging.exception(f"auto_monitor: save_log_to_db failed: {e}")

                # reset consecutive counter when improvement occurs
                if smooth_pnl >= target:
                    consecutive_fail = 0
                else:
                    consecutive_fail += 1
                max_scale = float(os.environ.get("AUTO_MONITOR_MAX_SCALE", "3.0"))
                min_scale = float(os.environ.get("AUTO_MONITOR_MIN_SCALE", "0.1"))
                kp = float(os.environ.get("AUTO_MONITOR_KP", "0.2"))
                ramp_pct = float(os.environ.get("AUTO_MONITOR_RAMP_PCT", "0.2"))
                alpha = float(os.environ.get("AUTO_MONITOR_SMOOTH_ALPHA", "0.4"))

                # smoothing for noisy pnl measurements
                prev_smooth = getattr(app.state, "autoscaler_smoothed_pnl", None)
                if prev_smooth is None:
                    smooth_pnl = float(net_pnl_15m)
                else:
                    smooth_pnl = alpha * float(net_pnl_15m) + (1 - alpha) * float(
                        prev_smooth
                    )

                # proportional adjustment: delta_scale = kp * (target - smooth_pnl)
                error = float(target) - float(smooth_pnl)
                delta_scale = kp * error

                # limit change per step (ramp)
                max_delta = abs(ramp_pct * cur_scale)
                if delta_scale > max_delta:
                    delta_scale = max_delta
                elif delta_scale < -max_delta:
                    delta_scale = -max_delta

                new_scale = cur_scale + delta_scale
                # clamp within allowed bounds
                new_scale = max(min_scale, min(max_scale, round(new_scale, 4)))

                # compute new allocation (multiply base allocation)
                new_alloc = max(0.001, min(1.0, round(base_alloc * new_scale, 6)))

                # persist to environment and app.state
                os.environ["allocation_pct"] = str(new_alloc)
                app.state.autoscaler_scale = new_scale
                app.state.autoscaler_smoothed_pnl = smooth_pnl
                # write runtime allocation to DB so other processes (bot) can pick it up
                try:
                    from core.db_utils import save_log_to_db

                    ok = save_log_to_db(
                        "runtime_allocation", {"allocation_pct": new_alloc}
                    )
                    if not ok:
                        logging.warning(
                            "auto_monitor: failed to persist runtime_allocation to DB (save_log_to_db returned False)"
                        )
                except Exception as e:
                    logging.exception(f"auto_monitor: save_log_to_db failed: {e}")

                # optionally persist the scaling to config so restart
                # keeps conservative value
                try:
                    cfg_dir = Path(__file__).resolve().parent / "config"
                    cfg_path = cfg_dir / "config.yaml"
                    if cfg_path.exists():
                        txt = cfg_path.read_text(encoding="utf-8")
                        txt = re.sub(
                            r"allocation_pct:\s*\S+",
                            f"allocation_pct: {new_alloc}",
                            txt,
                        )
                        cfg_path.write_text(txt, encoding="utf-8")
                except Exception:
                    pass

                logging.info(
                    "auto_monitor: autoscaler scale=%.3f smooth_pnl=%.4f "
                    "alloc=%s (error=%.4f)",
                    new_scale,
                    smooth_pnl,
                    new_alloc,
                    error,
                )

                # reset consecutive counter when improvement occurs
                if smooth_pnl >= target:
                    consecutive_fail = 0
                else:
                    consecutive_fail += 1

            # Severe-condition -> consider panic (with cooldown to avoid
            # repeated panic invocations during transient conditions)
            if net_pnl_15m is not None and (
                net_pnl_15m <= panic_threshold or consecutive_fail >= fail_limit
            ):
                logging.warning(
                    "auto_monitor: severe condition reached — considering panic"
                )
                try:
                    now_ts = time.time()
                    last_panic = getattr(app.state, "autoscaler_last_panic_ts", 0)
                    panic_cooldown = int(
                        os.environ.get("AUTO_MONITOR_PANIC_COOLDOWN_SEC", "1800")
                    )
                    if now_ts - last_panic >= panic_cooldown:
                        # call local panic handler directly (bypass HTTP auth)
                        api_panic(True)
                        try:
                            app.state.autoscaler_last_panic_ts = now_ts
                        except Exception:
                            pass
                    else:
                        remaining = panic_cooldown - (now_ts - last_panic)
                        logging.warning(
                            "auto_monitor: panic suppressed due to cooldown (%.0fs remaining)",
                            remaining,
                        )
                except Exception as e:
                    logging.exception(f"auto_monitor panic failed: {e}")
                consecutive_fail = 0
        except Exception as e:
            logging.warning(f"auto_monitor failed: {e}")
        time.sleep(interval_sec)


@asynccontextmanager
async def lifespan(app_instance):
    startup_event()
    yield


app = FastAPI(lifespan=lifespan)

# Session anchor for "NEW_SESSION" mode
SESSION_START = datetime.now(timezone.utc)


def _session_anchor():
    try:
        return getattr(app.state, "session_start", SESSION_START)
    except Exception:
        return SESSION_START


def _session_floor(ts):
    if os.environ.get("NEW_SESSION", "0") != "1":
        return ts
    anchor = _session_anchor()
    try:
        if anchor is not None and anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    if ts is None or ts < anchor:
        return anchor
    return ts


# Health check endpoint for root
@app.get("/")
def root_status():
    return {"status": "ok"}


position_manager = PositionManager()


# --- Control route auth (ZTA) ---
def _require_control_token(x_api_token: str = Header(default=None)):
    from security.zero_trust import authorize, log_event
    import os

    token = x_api_token
    if token is None or str(token).strip() == "":
        log_event("API control unauthorized: missing token header")
        raise HTTPException(status_code=403, detail="unauthorized")
    if not authorize(token):
        log_event("API control unauthorized")
        raise HTTPException(status_code=403, detail="unauthorized")
    # mirror validated control token into process env so in-process DB writes
    # (save_log_to_db) that rely on ZOL0_TOKEN succeed when endpoint
    # authenticated via header (dev / control usage).
    try:
        os.environ["ZOL0_TOKEN"] = str(token)
    except Exception:
        pass
    return True


@app.post("/api/session/reset")
def reset_session(auth=Depends(_require_control_token)):
    now = datetime.now(timezone.utc)
    try:
        app.state.session_start = now
    except Exception:
        pass
    try:

        reset_paper_gate()
    except Exception:
        pass
    try:
        if hasattr(position_manager, "closed_positions"):
            position_manager.closed_positions.clear()
        if hasattr(position_manager, "position_history"):
            position_manager.position_history.clear()
    except Exception:
        pass
    return {"status": "ok", "session_start": now.isoformat()}


def _positions_as_map():
    anchor = None
    try:
        if os.environ.get("NEW_SESSION", "0") == "1":
            anchor = _session_anchor()
    except Exception:
        anchor = None
    positions = getattr(position_manager, "_positions_map", None)
    if isinstance(positions, dict):
        if positions:
            try:
                client = KucoinFuturesClient()
                for sym, pos in positions.items():
                    if not isinstance(pos, dict):
                        continue
                    if (
                        pos.get("unrealized_pnl") is not None
                        and pos.get("mark_price") is not None
                    ):
                        continue
                    if not is_futures_symbol(sym):
                        continue
                    try:
                        ticker = client.get_ticker(sym)
                    except Exception:
                        continue
                    last_price = None
                    if isinstance(ticker, dict):
                        last_price = ticker.get("price") or ticker.get("last")
                    entry = pos.get("entry_price") or pos.get("price")
                    amount = pos.get("amount")
                    side = str(pos.get("side", "")).lower()
                    if last_price is None or entry is None or amount is None:
                        continue
                    try:
                        if side in ("sell", "short"):
                            unreal = (float(entry) - float(last_price)) * float(amount)
                        else:
                            unreal = (float(last_price) - float(entry)) * float(amount)
                        pos["mark_price"] = last_price
                        pos["unrealized_pnl"] = unreal
                    except Exception:
                        continue
            except Exception:
                pass
            return positions
    pos_list = getattr(position_manager, "positions", [])
    if isinstance(pos_list, dict):
        if pos_list:
            return pos_list
    if isinstance(pos_list, list):
        mapped = {
            p.get("symbol"): p
            for p in pos_list
            if isinstance(p, dict) and p.get("symbol")
        }
        if mapped:
            return mapped

    # Fallback: build positions map from bot logs (position_update events)
    try:
        db = SessionLocal()
        close_query = db.query(LogEntry).filter(
            LogEntry.event.in_(["position_close", "position_sync_clear"])
        )
        if anchor:
            close_query = close_query.filter(LogEntry.timestamp >= anchor)
        close_rows = close_query.order_by(desc(LogEntry.timestamp)).limit(200).all()
        closed_at = {}
        for row in close_rows:
            try:
                details = json.loads(row.details) if row.details else {}
            except Exception:
                details = {}
            if not isinstance(details, dict):
                continue
            pos = (
                details.get("position")
                if isinstance(details.get("position"), dict)
                else {}
            )
            sym = details.get("symbol") or (
                pos.get("symbol") if isinstance(pos, dict) else None
            )
            if not sym:
                continue
            if sym not in closed_at:
                closed_at[sym] = row.timestamp
        pos_query = db.query(LogEntry).filter(
            LogEntry.event.in_(["position_update", "position_mark", "position_sync"])
        )
        if anchor:
            pos_query = pos_query.filter(LogEntry.timestamp >= anchor)
        rows = pos_query.order_by(desc(LogEntry.timestamp)).limit(200).all()
        positions_from_logs = {}
        for row in rows:
            try:
                details = json.loads(row.details) if row.details else {}
            except Exception:
                details = {}
            pos = details.get("position")
            sym = details.get("symbol")
            if isinstance(pos, dict) and not sym:
                sym = pos.get("symbol")
            if not sym:
                continue
            closed_ts = closed_at.get(sym)
            if closed_ts and row.timestamp and closed_ts >= row.timestamp:
                continue
            if sym in positions_from_logs:
                continue
            if not isinstance(pos, dict):
                if row.event == "position_sync" and isinstance(details, dict):
                    pos = {
                        "symbol": sym,
                        "side": details.get("side"),
                        "amount": details.get("amount"),
                        "entry_price": (
                            details.get("entry_price") or details.get("price")
                        ),
                        "timestamp": details.get("timestamp")
                        or (row.timestamp.isoformat() if row.timestamp else None),
                        "contracts": details.get("contracts"),
                    }
                else:
                    continue
            if pos.get("side") is None and pos.get("amount") is None:
                continue
            enriched = dict(pos)
            if isinstance(details, dict):
                if details.get("mark_price") is not None:
                    enriched["mark_price"] = details.get("mark_price")
                if details.get("unrealized_pnl") is not None:
                    enriched["unrealized_pnl"] = details.get("unrealized_pnl")
            positions_from_logs[sym] = enriched
        return positions_from_logs
    except Exception:
        return {}
    finally:
        try:
            db.close()
        except Exception:
            pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_symbol() -> str:
    try:
        from utils.config_loader import load_config

        cfg = load_config("config/config.yaml")
        return cfg.get("symbol", "BTC-USDT")
    except Exception:
        return "BTC-USDT"


def _use_mock() -> bool:
    return os.environ.get("USE_MOCK", "0") == "1"


def _normalize_strategy_name(name):
    if not name:
        return None
    if str(name).lower() == "unknown":
        return "Universal"
    return name


def _normalize_ohlcv(candles):
    normalized = []
    for c in candles or []:
        if not isinstance(c, dict):
            continue
        normalized.append(
            {
                **c,
                "timestamp": to_ms(c.get("timestamp")),
                "open": float(c.get("open", 0)),
                "close": float(c.get("close", 0)),
                "high": float(c.get("high", 0)),
                "low": float(c.get("low", 0)),
                "volume": float(c.get("volume", 0)),
            }
        )
    return normalized


def _validate_ohlcv(candles):
    for idx, c in enumerate(candles or []):
        try:
            o = float(c.get("open", 0))
            cl = float(c.get("close", 0))
            h = float(c.get("high", 0))
            low = float(c.get("low", 0))
        except Exception:
            return False, idx
        if h < max(o, cl) or low > min(o, cl):
            return False, idx
    return True, None


def _equity_window_start():
    try:
        if os.environ.get("NEW_SESSION", "0") == "1":
            return _session_anchor()
        hours = os.environ.get("EQUITY_WINDOW_HOURS")
        if hours is None or str(hours).strip() == "":
            return None
        hours_f = float(hours)
        if hours_f <= 0:
            return None
        return datetime.now(timezone.utc) - timedelta(hours=hours_f)
    except Exception:
        return None


def _filter_equity_session(rows):
    if not rows:
        return [], None
    window_start = _equity_window_start()
    filtered = []
    eq_values = []
    for r in rows:
        try:
            ts = r.timestamp
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if window_start is None or (ts and ts >= window_start):
                eq_val = _sanitize_equity_value(r.equity)
                if eq_val is None:
                    continue
                filtered.append(r)
                eq_values.append(eq_val)
        except Exception:
            continue
    if not filtered:
        return [], window_start
    try:
        max_usdt = float(os.environ.get("EQUITY_MAX_USDT", "1000000"))
    except Exception:
        max_usdt = 1000000.0
    try:
        if eq_values:
            min_abs = min(abs(v) for v in eq_values if v is not None)
            if min_abs and math.isfinite(min_abs):
                dynamic_cap = min(max_usdt, max(min_abs * 50, 1.0))
            else:
                dynamic_cap = max_usdt
            if dynamic_cap < max_usdt:
                trimmed = []
                trimmed_vals = []
                for r, val in zip(filtered, eq_values):
                    if abs(val) <= dynamic_cap:
                        trimmed.append(r)
                        trimmed_vals.append(val)
                if trimmed:
                    filtered = trimmed
                    eq_values = trimmed_vals
                else:
                    return [], window_start
    except Exception:
        pass
    try:
        factor = float(os.environ.get("EQUITY_RESET_FACTOR", "5"))
    except Exception:
        factor = 5.0
    start_idx = 0
    for i in range(1, len(eq_values)):
        try:
            prev = float(eq_values[i - 1])
            cur = float(eq_values[i])
        except (ValueError, TypeError, IndexError):
            continue
        if prev == 0 or cur == 0:
            if prev != cur:
                start_idx = i
            continue
        ratio = cur / prev
        inv_ratio = prev / cur
        if ratio >= factor or inv_ratio >= factor:
            start_idx = i
    filtered = filtered[start_idx:]
    session_start = filtered[0].timestamp if filtered else window_start
    return filtered, session_start


def _sanitize_equity_value(val):
    try:
        eq = float(val)
    except Exception:
        return None
    try:
        max_usdt = float(os.environ.get("EQUITY_MAX_USDT", "1000000"))
    except Exception:
        max_usdt = 1000000.0
    if not math.isfinite(eq):
        return None
    if abs(eq) > max_usdt:
        return None
    return eq


def _resolve_market_type(symbol: str) -> str:
    env_type = os.environ.get("MARKET_TYPE")
    if env_type:
        return str(env_type).lower()
    try:
        from utils.config_loader import load_config

        cfg = load_config("config/config.yaml")
        cfg_type = cfg.get("market_type")
        if cfg_type:
            return str(cfg_type).lower()
    except Exception:
        pass
    if is_futures_symbol(symbol):
        return "futures"
    return "spot"


# --- /decisions endpoint ---
@app.get("/decisions")
def get_decisions(limit: int = Query(20, ge=1, le=500)):
    try:
        db = SessionLocal()
        query = db.query(Decision)
        if os.environ.get("NEW_SESSION", "0") == "1":
            query = query.filter(Decision.timestamp >= _session_anchor())
        decisions = (
            query.order_by(desc(Decision.timestamp)).limit(limit * 5).all()[::-1]
        )

        def _parse_details(details):
            try:
                if not details:
                    return {}
                parsed = json.loads(details) if isinstance(details, str) else details

                def _sanitize_json(value):
                    if isinstance(value, float) and not math.isfinite(value):
                        return None
                    if isinstance(value, dict):
                        return {k: _sanitize_json(v) for k, v in value.items()}
                    if isinstance(value, list):
                        return [_sanitize_json(v) for v in value]
                    return value

                return _sanitize_json(parsed)
            except Exception:
                return {}

        def _extract_strategy(payload):
            signals = payload.get("ensemble_signals")
            if isinstance(signals, list) and signals:
                # choose the highest allocation strategy if available
                best = max(signals, key=lambda s: s.get("allocation", 0))
                return best.get("strategy")
            return None

        out = []
        seen = set()
        for d in decisions:
            payload = _parse_details(d.details)
            trend = payload.get("trend")
            volatility = payload.get("volatility")
            strategy = _extract_strategy(payload)
            signal_votes = payload.get("signal_votes")
            signal_score = payload.get("signal_score")
            ts_key = d.timestamp.replace(microsecond=0).isoformat()
            key = (ts_key, d.decision, trend, volatility, strategy)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "timestamp": d.timestamp.isoformat(),
                    "decision": d.decision,
                    "details": payload,
                    "trend": trend,
                    "volatility": volatility,
                    "strategy": strategy,
                    "signal_votes": signal_votes,
                    "signal_score": signal_score,
                }
            )
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    finally:
        db.close()


# === CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DummyStrategy:
    name = "Dummy"

    def analyze(self, market_state=None):
        return {"signal": "hold"}


def startup_event():
    init_db()
    try:
        seed_flag = os.environ.get("SEED_DEV_ON_START", "0") == "1"
        seed_flag = seed_flag or (os.environ.get("SEED_DEV", "0") == "1")
        use_mock = os.environ.get("USE_MOCK", "0") == "1"
    except Exception:
        seed_flag = False
        use_mock = False
    if seed_flag:
        if use_mock:
            try:
                from scripts.seed_dev import seed as _seed_dev

                _seed_dev()
            except Exception as e:
                logging.warning(f"Dev seed failed: {e}")
        else:
            logging.info("Dev seed skipped: USE_MOCK=0")
    try:
        app.state.session_start = SESSION_START
    except Exception:
        pass
    app.state.current_strategy_router = DynamicStrategyRouter(
        strategies=[DummyStrategy()]
    )
    position_manager.closed_positions = position_manager.closed
    position_manager.closed_positions.clear()
    try:
        _load_count = 0
        db = SessionLocal()
        rows = (
            db.query(LogEntry)
            .filter(LogEntry.event == "position_close")
            .order_by(desc(LogEntry.timestamp))
            .limit(200)
            .all()
        )
        seen = set()
        for row in rows:
            try:
                details = json.loads(row.details) if row.details else {}
            except Exception:
                details = {}
            pos = details.get("position") if isinstance(details, dict) else None
            sym = details.get("symbol") if isinstance(details, dict) else None
            if isinstance(pos, dict) and not sym:
                sym = pos.get("symbol")
            if not sym:
                continue
            payload = dict(pos) if isinstance(pos, dict) else {}
            payload.setdefault("symbol", sym)
            if isinstance(details, dict):
                if details.get("close_price") is not None:
                    payload["close_price"] = details.get("close_price")
                if details.get("realized_pnl") is not None:
                    payload["realized_pnl"] = details.get("realized_pnl")
            payload.setdefault("close_timestamp", row.timestamp.isoformat())
            key = (
                payload.get("symbol"),
                payload.get("close_timestamp"),
                payload.get("entry_price"),
                payload.get("amount"),
            )
            if key in seen:
                continue
            seen.add(key)
            position_manager.closed_positions.append(payload)
            _load_count += 1
    except Exception:
        pass
    finally:
        try:
            db.close()
        except Exception:
            pass
    position_manager._lock = threading.Lock()

    # Start auto-report background thread (loop checks AUTO_REPORT_ENABLE)
    try:
        t = getattr(app.state, "auto_report_thread", None)
        if not t or not t.is_alive():
            _t = threading.Thread(target=_auto_report_loop, daemon=True)
            _t.start()
            app.state.auto_report_thread = _t
    except Exception as __e:
        logging.warning(f"auto_report thread start failed: {__e}")

    # Start auto-monitor background thread (loop checks AUTO_MONITOR_ENABLE)
    try:
        m = getattr(app.state, "auto_monitor_thread", None)
        if not m or not m.is_alive():
            _m = threading.Thread(target=_auto_monitor_loop, daemon=True)
            _m.start()
            app.state.auto_monitor_thread = _m
    except Exception as __e:
        logging.warning(f"auto_monitor thread start failed: {__e}")


if not hasattr(position_manager, "position_history"):
    position_manager.position_history = {}


def record_position_history(symbol, pos):
    h = position_manager.position_history.setdefault(symbol, [])
    ts = pos.get("timestamp")
    if ts is None:
        try:
            ts = datetime.now(timezone.utc).isoformat()
        except Exception:
            ts = None
    value = pos.get("unrealized_pnl")
    if value is None:
        value = pos.get("value", pos.get("amount", 0))
    h.append({"timestamp": ts, "value": value})
    if len(h) > 1000:
        del h[0]


orig_update = position_manager.update_position


def update_and_record(symbol, order):
    orig_update(symbol, order)
    pos = position_manager.get_position(symbol)
    if pos:
        record_position_history(symbol, pos)


position_manager.update_position = update_and_record


def close_position(symbol: str):
    lock = getattr(position_manager, "_lock", threading.Lock())
    with lock:
        pos = position_manager.get_position(symbol)
        if pos:
            close_price = None
            try:
                if is_futures_symbol(symbol):
                    ticker = KucoinFuturesClient().get_ticker(symbol)
                    if isinstance(ticker, dict):
                        close_price = ticker.get("price") or ticker.get("last")
            except Exception:
                close_price = None
            realized_pnl = None
            try:
                entry = pos.get("entry_price") or pos.get("price")
                amount = pos.get("amount")
                side = str(pos.get("side", "")).lower()
                if entry is not None and close_price is not None and amount is not None:
                    if side in ("sell", "short"):
                        realized_pnl = (float(entry) - float(close_price)) * float(
                            amount
                        )
                    else:
                        realized_pnl = (float(close_price) - float(entry)) * float(
                            amount
                        )
            except Exception:
                realized_pnl = None
            if close_price is not None:
                pos["exit_price"] = close_price
                pos["close_price"] = close_price
            pos["close_timestamp"] = _now_iso()
            if realized_pnl is not None:
                pos["realized_pnl"] = realized_pnl
            try:
                from core.db_utils import save_log_to_db
                import json

                save_log_to_db(
                    event="position_close",
                    details=json.dumps(
                        {
                            "symbol": symbol,
                            "position": pos,
                            "close_price": close_price,
                            "realized_pnl": realized_pnl,
                        }
                    ),
                )
            except Exception:
                pass
            position_manager.closed_positions.append({"symbol": symbol, **pos})
            if hasattr(position_manager, "_positions_map"):
                position_manager._positions_map.pop(symbol, None)
                if hasattr(position_manager, "_sync_list_from_map"):
                    position_manager._sync_list_from_map()
            return {"status": "closed", "symbol": symbol, "position": pos}
        try:
            from core.db_utils import save_log_to_db
            import json

            save_log_to_db(
                event="position_close_request",
                details=json.dumps(
                    {
                        "symbol": symbol,
                        "requested_at": _now_iso(),
                    }
                ),
            )
        except Exception:
            pass
        return {"status": "queued", "symbol": symbol, "error": "close_queued"}


@app.head("/")
def root():
    return PlainTextResponse("ZoL0 API is running. See /docs for available endpoints.")


@app.get("/positions")
def get_all_positions():
    return _positions_as_map()


@app.get("/positions/closed")
def get_closed_positions():
    closed_mem = getattr(position_manager, "closed_positions", []) or []
    normalized_mem = []
    for item in closed_mem:
        if isinstance(item, dict):
            payload = dict(item)
            payload["strategy"] = (
                _normalize_strategy_name(payload.get("strategy")) or "Universal"
            )
            normalized_mem.append(payload)
        else:
            normalized_mem.append(item)

    # Always include DB-backed close events. In docker, bot and API are
    # separate processes, so API memory can become stale.
    normalized_db = []
    try:
        db = SessionLocal()
        query = db.query(LogEntry).filter(LogEntry.event == "position_close")
        if os.environ.get("NEW_SESSION", "0") == "1":
            query = query.filter(LogEntry.timestamp >= _session_anchor())
        rows = query.order_by(desc(LogEntry.timestamp)).limit(200).all()
        out = []
        for row in rows:
            try:
                details = json.loads(row.details) if row.details else {}
            except Exception:
                details = {}
            pos = details.get("position") if isinstance(details, dict) else None
            sym = details.get("symbol") if isinstance(details, dict) else None
            if isinstance(pos, dict) and not sym:
                sym = pos.get("symbol")
            if not sym:
                continue
            payload = dict(pos) if isinstance(pos, dict) else {}
            payload.setdefault("symbol", sym)
            if isinstance(details, dict):
                if details.get("close_price") is not None:
                    payload["close_price"] = details.get("close_price")
                if details.get("realized_pnl") is not None:
                    payload["realized_pnl"] = details.get("realized_pnl")
                if details.get("close_fill_price") is not None:
                    payload["close_fill_price"] = details.get("close_fill_price")
                if details.get("reason") is not None:
                    payload["exit_reason"] = details.get("reason")
                if details.get("exit_reason") is not None:
                    payload["exit_reason"] = details.get("exit_reason")
                if details.get("strategy") is not None:
                    payload["strategy"] = details.get("strategy")
            payload["strategy"] = (
                _normalize_strategy_name(payload.get("strategy")) or "Universal"
            )
            payload.setdefault("timestamp", row.timestamp.isoformat())
            out.append(payload)
        normalized_db = out
    except Exception:
        normalized_db = []
    finally:
        try:
            db.close()
        except Exception:
            pass

    combined = []
    seen = set()
    # Prefer DB-first ordering so newest closes are visible quickly.
    for item in normalized_db + normalized_mem:
        if not isinstance(item, dict):
            continue
        key = (
            item.get("symbol"),
            item.get("close_timestamp") or item.get("timestamp"),
            item.get("entry_price"),
            item.get("amount"),
            item.get("side"),
        )
        if key in seen:
            continue
        seen.add(key)
        combined.append(item)

    def _close_sort_key(item):
        ts = item.get("close_timestamp") or item.get("timestamp")
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                dt = None
        elif isinstance(ts, datetime):
            dt = ts
        else:
            dt = None
        if dt is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    combined.sort(key=_close_sort_key, reverse=True)
    return combined[:200]


@app.get("/closed")
def get_closed_positions_alias():
    return get_closed_positions()


@app.get("/positions/{symbol}")
def get_position(symbol: str):
    pos = position_manager.get_position(symbol)
    return pos if pos else {"error": "Brak pozycji dla symbolu"}


@app.get("/positions/{symbol}/history")
def get_position_history(symbol: str):
    hist = position_manager.position_history.get(symbol, [])
    out = hist[:] if hist else []
    # Always extend with logs to get mark-to-market history
    try:
        db = SessionLocal()
        query = db.query(LogEntry).filter(
            LogEntry.event.in_(["position_update", "position_mark"])
        )
        if os.environ.get("NEW_SESSION", "0") == "1":
            query = query.filter(LogEntry.timestamp >= _session_anchor())
        rows = query.order_by(LogEntry.timestamp).limit(500).all()
        seen = set()
        for item in out:
            ts = item.get("timestamp") if isinstance(item, dict) else None
            if ts is not None:
                seen.add(ts)

        def _value_from_details(pos_obj, details_obj):
            mark_price = None
            if isinstance(details_obj, dict):
                if details_obj.get("unrealized_pnl") is not None:
                    try:
                        return float(details_obj.get("unrealized_pnl"))
                    except Exception:
                        pass
                mark_price = (
                    details_obj.get("mark_price")
                    or details_obj.get("price")
                    or details_obj.get("last")
                )
            if isinstance(pos_obj, dict):
                if pos_obj.get("unrealized_pnl") is not None:
                    try:
                        return float(pos_obj.get("unrealized_pnl"))
                    except Exception:
                        pass
                if mark_price is None:
                    mark_price = (
                        pos_obj.get("mark_price")
                        or pos_obj.get("price")
                        or pos_obj.get("last")
                    )
                entry = pos_obj.get("entry_price") or pos_obj.get("price")
                amount = pos_obj.get("amount", 0) or 0
                side = str(pos_obj.get("side", "")).lower()
                if mark_price is not None and entry is not None:
                    try:
                        if side in ("sell", "short"):
                            return (float(entry) - float(mark_price)) * float(amount)
                        return (float(mark_price) - float(entry)) * float(amount)
                    except Exception:
                        pass
                if pos_obj.get("value") is not None:
                    try:
                        return float(pos_obj.get("value"))
                    except Exception:
                        return pos_obj.get("value")
                if entry is not None:
                    try:
                        return float(amount) * float(entry)
                    except Exception:
                        return amount
            return None

        for row in rows:
            try:
                details = json.loads(row.details) if row.details else {}
            except Exception:
                details = {}
            pos = details.get("position") if isinstance(details, dict) else None
            sym = details.get("symbol") if isinstance(details, dict) else None
            if isinstance(pos, dict) and not sym:
                sym = pos.get("symbol")
            if sym != symbol or not isinstance(pos, dict):
                continue
            value = _value_from_details(pos, details)
            if value is None:
                continue
            ts = row.timestamp.isoformat()
            if ts in seen:
                continue
            seen.add(ts)
            out.append(
                {
                    "timestamp": ts,
                    "value": value,
                }
            )
    except Exception:
        pass
    finally:
        try:
            db.close()
        except Exception:
            pass
    try:

        def _ts_key(item):
            ts = item.get("timestamp")
            if isinstance(ts, (int, float)):
                return float(ts)
            try:
                return datetime.fromisoformat(ts).timestamp()
            except Exception:
                return 0

        out.sort(key=_ts_key)
        if len(out) > 500:
            out = out[-500:]
    except Exception:
        pass
    # Append live mark-to-market point (fresh price)
    try:
        positions = _positions_as_map()
        pos = positions.get(symbol)
        if pos and is_futures_symbol(symbol):
            ticker = KucoinFuturesClient().get_ticker(symbol)
            last_price = None
            if isinstance(ticker, dict):
                last_price = ticker.get("price") or ticker.get("last")
            if last_price is not None:
                amount = pos.get("amount") or 0
                entry = pos.get("entry_price") or pos.get("price")
                side = str(pos.get("side", "")).lower()
                if entry is not None:
                    if side in ("sell", "short"):
                        value = (float(entry) - float(last_price)) * float(amount)
                    else:
                        value = (float(last_price) - float(entry)) * float(amount)
                else:
                    value = float(last_price) * float(amount)
                out.append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "value": value,
                    }
                )
    except Exception:
        pass
    return out


@app.post("/positions/{symbol}/close")
def api_close_position(symbol: str, _: bool = Depends(_require_control_token)):
    return close_position(symbol)


# --- Live Trading Endpoint ---
@app.post("/start-live")
def start_live(_: bool = Depends(_require_control_token)):
    """
    Start the ZoL0 trading bot in live mode. This endpoint spawns
    the main bot loop in a background thread so the API remains responsive.
    Lazy-import `run_bot` to avoid circular import at module import time.
    """
    try:
        from security.live_guard import is_live_armed

        armed, reason = is_live_armed()
        if not armed:
            logging.warning(f"/start-live blocked: {reason}")
            return JSONResponse(
                content={"error": f"live_not_armed: {reason}"},
                status_code=409,
            )
        from core.BotCore import run_bot

        thread = threading.Thread(
            target=run_bot,
            kwargs={"simulate": False},
            daemon=True,
        )
        thread.start()
        return {"status": "started"}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/auto-report")
def api_auto_report_control(
    enable: bool = Query(default=True),
    interval_sec: int = Query(default=900),
    limit: int = Query(default=50),
    use_fills: int = Query(default=1),
    symbol: str = Query(default=None),
    _: bool = Depends(_require_control_token),
):
    """Enable/disable auto reports and set parameters (no restart needed)."""
    try:
        os.environ["AUTO_REPORT_ENABLE"] = "1" if enable else "0"
        os.environ["AUTO_REPORT_INTERVAL_SEC"] = str(max(60, int(interval_sec)))
        os.environ["AUTO_REPORT_LIMIT"] = str(int(limit))
        os.environ["AUTO_REPORT_USE_FILLS"] = str(int(use_fills))
        if symbol:
            os.environ["AUTO_REPORT_SYMBOL"] = symbol
        else:
            os.environ.pop("AUTO_REPORT_SYMBOL", None)
        # Ensure background thread is running
        t = getattr(app.state, "auto_report_thread", None)
        if not (t and t.is_alive()):
            th = threading.Thread(target=_auto_report_loop, daemon=True)
            th.start()
            app.state.auto_report_thread = th
        return {
            "status": "ok",
            "enabled": enable,
            "interval_sec": int(interval_sec),
            "limit": int(limit),
            "use_fills": int(use_fills),
            "symbol": symbol,
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/auto-report")
def api_auto_report_status(_: bool = Depends(_require_control_token)):
    enabled = os.environ.get("AUTO_REPORT_ENABLE", "0") == "1"
    try:
        interval = int(os.environ.get("AUTO_REPORT_INTERVAL_SEC", "900"))
    except Exception:
        interval = 900
    try:
        limit = int(os.environ.get("AUTO_REPORT_LIMIT", "50"))
    except Exception:
        limit = 50
    try:
        use_fills = int(os.environ.get("AUTO_REPORT_USE_FILLS", "1"))
    except Exception:
        use_fills = 1
    symbol = os.environ.get("AUTO_REPORT_SYMBOL") or None
    t = getattr(app.state, "auto_report_thread", None)
    thread_alive = bool(t and t.is_alive())
    return {
        "enabled": enabled,
        "interval_sec": interval,
        "limit": limit,
        "use_fills": use_fills,
        "symbol": symbol,
        "thread_alive": thread_alive,
    }


@app.post("/auto-monitor")
def api_auto_monitor_control(
    enable: bool = Query(default=True),
    interval_sec: int = Query(default=900),
    target: float = Query(default=0.5),
    fail_limit: int = Query(default=3),
    panic_threshold: float = Query(default=-1.0),
    kp: float | None = Query(default=None),
    max_scale: float | None = Query(default=None),
    min_scale: float | None = Query(default=None),
    ramp_pct: float | None = Query(default=None),
    alpha: float | None = Query(default=None),
    init_scale: float | None = Query(default=None),
    allocation_pct: float | None = Query(default=None),
    mode: str = Query(default="pnl"),
    _: bool = Depends(_require_control_token),
):
    """Enable/disable automatic monitoring, set corrective thresholds and optional
    autoscaler hyperparameters. Parameters provided here update process env and
    app.state so changes apply immediately in dev.
    """
    try:
        os.environ["AUTO_MONITOR_ENABLE"] = "1" if enable else "0"
        os.environ["AUTO_MONITOR_INTERVAL_SEC"] = str(max(60, int(interval_sec)))
        os.environ["AUTO_MONITOR_NET_PNL_TARGET"] = str(float(target))
        os.environ["AUTO_MONITOR_FAIL_LIMIT"] = str(int(fail_limit))
        os.environ["AUTO_MONITOR_PANIC_THRESHOLD"] = str(float(panic_threshold))

        # Optional autoscaler params (persist to env)
        if kp is not None:
            os.environ["AUTO_MONITOR_KP"] = str(float(kp))
        if max_scale is not None:
            os.environ["AUTO_MONITOR_MAX_SCALE"] = str(float(max_scale))
        if min_scale is not None:
            os.environ["AUTO_MONITOR_MIN_SCALE"] = str(float(min_scale))
        if ramp_pct is not None:
            os.environ["AUTO_MONITOR_RAMP_PCT"] = str(float(ramp_pct))
        if alpha is not None:
            os.environ["AUTO_MONITOR_SMOOTH_ALPHA"] = str(float(alpha))
        if init_scale is not None:
            os.environ["AUTO_MONITOR_SCALE"] = str(float(init_scale))
            # also set runtime state
            try:
                app.state.autoscaler_scale = float(init_scale)
            except Exception:
                pass
        # allow adjusting allocation_pct safely at runtime (dev only)
        if allocation_pct is not None:
            try:
                # Avoid leaking allocation env across sessions/tests.
                # Runtime pickup should use DB event `runtime_allocation`.
                if os.environ.get("AUTO_MONITOR_SET_ENV_ALLOCATION", "0") == "1":
                    os.environ["allocation_pct"] = str(float(allocation_pct))
                payload = {"allocation_pct": float(allocation_pct)}
                # Keep runtime allocation deterministic: keep a single newest row.
                ok = False
                db_alloc = None
                try:
                    db_alloc = SessionLocal()
                    db_alloc.query(LogEntry).filter(
                        LogEntry.event == "runtime_allocation"
                    ).delete(synchronize_session=False)
                    db_alloc.add(
                        LogEntry(
                            timestamp=datetime.now(timezone.utc),
                            event="runtime_allocation",
                            details=json.dumps(payload),
                        )
                    )
                    db_alloc.commit()
                    ok = True
                except Exception as write_e:
                    logging.warning(
                        f"api_auto_monitor_control: direct DB write failed: {write_e}"
                    )
                finally:
                    try:
                        if db_alloc is not None:
                            db_alloc.close()
                    except Exception:
                        pass
                if not ok:
                    try:
                        from core.db_utils import save_log_to_db

                        ok = save_log_to_db("runtime_allocation", payload)
                    except Exception as e:
                        logging.warning(
                            f"api_auto_monitor_control: save_log_to_db raised: {e}"  # noqa: E501
                        )
                if not ok:
                    logging.warning(
                        "api_auto_monitor_control: failed to persist runtime_allocation"
                    )
                # persist to config file as a convenience
                try:
                    cfg_dir = Path(__file__).resolve().parent / "config"
                    cfg_path = cfg_dir / "config.yaml"
                    if cfg_path.exists():
                        txt = cfg_path.read_text(encoding="utf-8")
                        pattern = r"allocation_pct:\s*\S+"
                        replacement = f"allocation_pct: {float(allocation_pct)}"
                        txt = re.sub(pattern, replacement, txt)
                        cfg_path.write_text(txt, encoding="utf-8")
                except Exception:
                    pass
            except Exception:
                pass

        # persist requested autoscaler mode and validate
        try:
            mode_l = str(mode).lower() if mode is not None else "pnl"
            if mode_l not in ("pnl", "hitrate"):
                msg = f"invalid mode '{mode}'"
                return JSONResponse(content={"error": msg}, status_code=400)
            os.environ["AUTO_MONITOR_MODE"] = mode_l
            # initialize hitrate history if switching to hitrate mode
            if mode_l == "hitrate":
                try:
                    from collections import deque

                    window = int(os.environ.get("AUTO_MONITOR_HITRATE_WINDOW", "10"))
                    app.state.autoscaler_history = deque(maxlen=window)
                except Exception:
                    app.state.autoscaler_history = []
        except Exception:
            pass

        # Ensure background thread is running
        t = getattr(app.state, "auto_monitor_thread", None)
        if not (t and t.is_alive()):
            th = threading.Thread(target=_auto_monitor_loop, daemon=True)
            th.start()
            app.state.auto_monitor_thread = th

        # reflect back current autoscaler-related env values
        resp = {
            "status": "ok",
            "enabled": enable,
            "interval_sec": int(interval_sec),
            "target": float(target),
            "fail_limit": int(fail_limit),
            "panic_threshold": float(panic_threshold),
            "mode": os.environ.get("AUTO_MONITOR_MODE", "pnl"),
            "autoscaler": {
                "kp": os.environ.get("AUTO_MONITOR_KP"),
                "max_scale": os.environ.get("AUTO_MONITOR_MAX_SCALE"),
                "min_scale": os.environ.get("AUTO_MONITOR_MIN_SCALE"),
                "ramp_pct": os.environ.get("AUTO_MONITOR_RAMP_PCT"),
                "alpha": os.environ.get("AUTO_MONITOR_SMOOTH_ALPHA"),
                "init_scale": os.environ.get("AUTO_MONITOR_SCALE"),
                "runtime_scale": getattr(app.state, "autoscaler_scale", None),
                "history_len": (
                    len(getattr(app.state, "autoscaler_history", []))
                    if getattr(app.state, "autoscaler_history", None) is not None
                    else None
                ),
            },
        }
        return resp
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/auto-monitor")
def api_auto_monitor_status(_: bool = Depends(_require_control_token)):
    enabled = os.environ.get("AUTO_MONITOR_ENABLE", "0") == "1"
    try:
        interval = int(os.environ.get("AUTO_MONITOR_INTERVAL_SEC", "900"))
    except Exception:
        interval = 900
    try:
        target = float(os.environ.get("AUTO_MONITOR_NET_PNL_TARGET", "0.5"))
    except Exception:
        target = 0.5
    try:
        fail_limit = int(os.environ.get("AUTO_MONITOR_FAIL_LIMIT", "3"))
    except Exception:
        fail_limit = 3
    try:
        panic_threshold = float(os.environ.get("AUTO_MONITOR_PANIC_THRESHOLD", "-1.0"))
    except Exception:
        panic_threshold = -1.0
    m = getattr(app.state, "auto_monitor_thread", None)
    thread_alive = bool(m and m.is_alive())
    return {
        "enabled": enabled,
        "interval_sec": interval,
        "target": target,
        "fail_limit": fail_limit,
        "panic_threshold": panic_threshold,
        "mode": os.environ.get("AUTO_MONITOR_MODE", "pnl"),
        "thread_alive": thread_alive,
    }


@app.post("/panic")
def api_panic(_: bool = Depends(_require_control_token)):
    """Emergency handler: close all open futures positions on-exchange
    (market reduceOnly), activate the paper-gate to block new entries,
    and apply safer runtime config overrides.
    Protected by control token.
    """
    closed = []
    orders = []
    try:
        # 1) Close all open positions (futures) via exchange orders
        positions = _positions_as_map()
        client = KucoinFuturesClient()
        for sym, pos in list(positions.items()):
            try:
                side = str(pos.get("side", "")).lower()
                amt = pos.get("amount")
                if amt is None:
                    continue
                close_side = "sell" if side in ("buy", "long") else "buy"
                # place market reduceOnly order to flatten
                try:
                    resp = client.create_order(
                        symbol=sym,
                        side=close_side,
                        size=float(amt),
                        order_type="market",
                        reduceOnly=True,
                    )
                except Exception as e:
                    resp = {"error": str(e)}
                orders.append({"symbol": sym, "response": resp})
                # mark internal state closed (best-effort)
                try:
                    position_manager.close_position(sym)
                except Exception:
                    pass
                closed.append(sym)
            except Exception as e:
                orders.append({"symbol": sym, "error": str(e)})
        # 2) Activate paper gate immediately (force-trigger)
        try:
            import utils.paper_gate as paper_gate

            paper_gate.update_gate(-1)
            paper_gate.update_gate(-1)
            gate_state = paper_gate.get_state()
        except Exception:
            gate_state = {"active": True}
        # 3) Apply safe runtime overrides (take effect immediately)
        try:
            os.environ["allocation_pct"] = "0.5"
            os.environ["futures_leverage"] = "1"
            os.environ["futures_max_contracts_per_trade"] = "1"
            os.environ["ENTRY_SIGNAL_SCORE_MIN"] = "0.6"
            os.environ["ENTRY_SIGNAL_SCORE_MIN_BUY"] = "0.6"
            os.environ["ENTRY_MIN_NET_USDT"] = "1.0"
            os.environ["EXECUTION_COOLDOWN_SEC"] = "60"
            os.environ["DECISION_CHANGE_COOLDOWN_SEC"] = "120"
            os.environ["ADAPTIVE_RISK_ENABLE"] = "1"
            os.environ["EXIT_TAKE_PROFIT_USDT"] = "0"
            os.environ["EXIT_MIN_HOLD_SEC"] = "300"
        except Exception:
            pass
        # 4) Persist safer defaults to config/config.yaml so restart keeps them
        try:
            cfg_path = Path(__file__).resolve().parent / "config" / "config.yaml"
            if cfg_path.exists():
                txt = cfg_path.read_text(encoding="utf-8")
                txt = re.sub(r"allocation_pct:\s*\S+", "allocation_pct: 0.5", txt)
                txt = re.sub(r"futures_leverage:\s*\S+", "futures_leverage: 1", txt)
                txt = re.sub(
                    r"futures_max_contracts_per_trade:\s*\S+",
                    "futures_max_contracts_per_trade: 1",
                    txt,
                )
                cfg_path.write_text(txt, encoding="utf-8")
        except Exception:
            pass
        return {
            "status": "panic_executed",
            "closed_symbols": closed,
            "orders": orders,
            "paper_gate": gate_state,
            "runtime_overrides": {
                "allocation_pct": os.environ.get("allocation_pct"),
                "futures_leverage": os.environ.get("futures_leverage"),
                "futures_max_contracts_per_trade": os.environ.get(
                    "futures_max_contracts_per_trade"
                ),
            },
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/strategy")
def get_current_strategy():
    log_anchor = (
        _session_anchor() if os.environ.get("NEW_SESSION", "0") == "1" else None
    )

    def _from_logs():
        try:
            db = SessionLocal()
            query = db.query(LogEntry).filter(LogEntry.event == "strategy_signals")
            if log_anchor:
                query = query.filter(LogEntry.timestamp >= log_anchor)
            last = query.order_by(desc(LogEntry.timestamp)).first()
            if not last:
                return None
            try:
                payload = json.loads(last.details) if last.details else {}
            except Exception:
                payload = {}
            raw = payload.get("raw_signals", [])
            names = [
                r.get("strategy")
                for r in raw
                if isinstance(r, dict) and r.get("strategy")
            ]
            if not names:
                return None
            return {
                "strategies": names,
                "strategy": names[0],
                "source": "logs",
                "timestamp": last.timestamp.isoformat(),
            }
        except Exception:
            return None
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _latest_allocations():
        try:
            db = SessionLocal()
            query = db.query(LogEntry).filter(LogEntry.event == "ensemble_signals")
            if log_anchor:
                query = query.filter(LogEntry.timestamp >= log_anchor)
            last = query.order_by(desc(LogEntry.timestamp)).first()
            if not last:
                return None
            try:
                payload = json.loads(last.details) if last.details else {}
            except Exception:
                payload = {}
            signals = payload.get("signals") or payload.get("ensemble_signals")
            if not isinstance(signals, list):
                return None
            out = []
            for s in signals:
                if not isinstance(s, dict):
                    continue
                name = _normalize_strategy_name(s.get("strategy"))
                if not name:
                    continue
                out.append(
                    {
                        "name": name,
                        "allocation": s.get("allocation"),
                    }
                )
            return out or None
        except Exception:
            return None
        finally:
            try:
                db.close()
            except Exception:
                pass

    def _strategy_metrics():
        try:
            db = SessionLocal()
            query = db.query(LogEntry).filter(LogEntry.event == "position_close")
            if log_anchor:
                query = query.filter(LogEntry.timestamp >= log_anchor)
            rows = query.order_by(desc(LogEntry.timestamp)).limit(500).all()
            perf = {}
            for row in rows:
                try:
                    details = json.loads(row.details) if row.details else {}
                except Exception:
                    details = {}
                if not isinstance(details, dict):
                    continue
                pos = (
                    details.get("position")
                    if isinstance(details.get("position"), dict)
                    else {}
                )
                strategy = details.get("strategy") or (
                    pos.get("strategy") if isinstance(pos, dict) else None
                )
                strategy = _normalize_strategy_name(strategy)
                if not strategy:
                    continue
                pnl_val = details.get("realized_pnl")
                if pnl_val is None and isinstance(pos, dict):
                    pnl_val = pos.get("realized_pnl")
                if pnl_val is None:
                    continue
                try:
                    pnl_val = float(pnl_val)
                except Exception:
                    continue
                perf.setdefault(strategy, []).append(pnl_val)
            if not perf:
                return None
            metrics = {}
            for name, pnls in perf.items():
                if not pnls:
                    continue
                mean = sum(pnls) / len(pnls)
                std = (
                    (sum((x - mean) ** 2 for x in pnls) / len(pnls)) ** 0.5
                    if len(pnls) > 1
                    else 1.0
                )
                sharpe = mean / std if std != 0 else 0.0
                metrics[name] = {
                    "pnl": float(sum(pnls)),
                    "sharpe": float(sharpe),
                }
            return metrics or None
        except Exception:
            return None
        finally:
            try:
                db.close()
            except Exception:
                pass

    router = getattr(app.state, "current_strategy_router", None)
    status = router.get_status() if (router and hasattr(router, "get_status")) else {}
    strategy_names = []
    if router:
        for s in getattr(router, "strategies", []):
            raw_name = s.name if hasattr(s, "name") else str(s)
            norm_name = _normalize_strategy_name(raw_name)
            if norm_name:
                strategy_names.append(norm_name)
    allocations = None
    metrics = None
    if not strategy_names or (
        len(strategy_names) == 1 and strategy_names[0] == "Dummy"
    ):
        from_logs = _from_logs()
        if from_logs:
            allocations = _latest_allocations()
            metrics = _strategy_metrics()
            alloc_map = {}
            if allocations:
                for item in allocations:
                    if isinstance(item, dict) and item.get("name"):
                        name = _normalize_strategy_name(item.get("name"))
                        if name:
                            alloc_map[name] = item.get("allocation")
            names = []
            for name in from_logs.get("strategies") or []:
                name = _normalize_strategy_name(name)
                if name and name not in names:
                    names.append(name)
            for name in alloc_map.keys():
                name = _normalize_strategy_name(name)
                if name and name not in names:
                    names.append(name)
            if metrics:
                for name in metrics.keys():
                    name = _normalize_strategy_name(name)
                    if name and name not in names:
                        names.append(name)
            combined = []
            for name in names:
                entry = {"name": name}
                if name in alloc_map:
                    entry["allocation"] = alloc_map.get(name)
                if metrics and name in metrics:
                    entry["pnl"] = metrics[name].get("pnl")
                    entry["sharpe"] = metrics[name].get("sharpe")
                combined.append(entry)
            if combined:
                from_logs["strategy_allocations"] = combined
            return from_logs
        allocations = _latest_allocations()
        metrics = _strategy_metrics()
        if allocations or metrics:
            alloc_map = {}
            if allocations:
                for item in allocations:
                    if isinstance(item, dict) and item.get("name"):
                        name = _normalize_strategy_name(item.get("name"))
                        if name:
                            alloc_map[name] = item.get("allocation")
            names = []
            for name in alloc_map.keys():
                name = _normalize_strategy_name(name)
                if name and name not in names:
                    names.append(name)
            if metrics:
                for name in metrics.keys():
                    name = _normalize_strategy_name(name)
                    if name and name not in names:
                        names.append(name)
            status = {
                "strategies": names,
                "strategy": names[0] if names else None,
            }
            combined = []
            for name in names:
                entry = {"name": name}
                if name in alloc_map:
                    entry["allocation"] = alloc_map.get(name)
                if metrics and name in metrics:
                    entry["pnl"] = metrics[name].get("pnl")
                    entry["sharpe"] = metrics[name].get("sharpe")
                combined.append(entry)
            status["strategy_allocations"] = combined
            return status
        if not strategy_names:
            return {"error": "Strategy router not initialized"}
    status.update(
        {
            "modes": getattr(router, "modes", None),
            "params": getattr(router, "params", None),
            "strategies": strategy_names,
            "strategy": strategy_names[0],
        }
    )
    if allocations is None:
        allocations = _latest_allocations()
    if metrics is None:
        metrics = _strategy_metrics()
    if allocations or metrics:
        alloc_map = {}
        if allocations:
            for item in allocations:
                if isinstance(item, dict) and item.get("name"):
                    name = _normalize_strategy_name(item.get("name"))
                    if name:
                        alloc_map[name] = item.get("allocation")
        names = []
        for name in strategy_names:
            name = _normalize_strategy_name(name)
            if name and name not in names:
                names.append(name)
        for name in alloc_map.keys():
            name = _normalize_strategy_name(name)
            if name and name not in names:
                names.append(name)
        if metrics:
            for name in metrics.keys():
                name = _normalize_strategy_name(name)
                if name and name not in names:
                    names.append(name)
        combined = []
        for name in names:
            entry = {"name": name}
            if name in alloc_map:
                entry["allocation"] = alloc_map.get(name)
            if metrics and name in metrics:
                entry["pnl"] = metrics[name].get("pnl")
                entry["sharpe"] = metrics[name].get("sharpe")
            combined.append(entry)
        status["strategy_allocations"] = combined
    return status


@app.get("/equity")
def get_equity(limit: int = Query(200, ge=1, le=1000)):
    try:
        db = SessionLocal()
        rows = (
            db.query(Equity)
            .order_by(desc(Equity.timestamp))
            .limit(min(max(limit * 5, 500), 2000))
            .all()[::-1]
        )
        rows, session_start = _filter_equity_session(rows)
        if len(rows) > limit:
            rows = rows[-limit:]
        out = []
        seen_ts = set()
        for e in rows:
            ts = e.timestamp.isoformat()
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            eq_val = _sanitize_equity_value(e.equity)
            if eq_val is None:
                continue
            out.append(
                {
                    "timestamp": ts,
                    "equity": eq_val,
                }
            )
        if os.environ.get("EQUITY_FROM_PNL", "1") == "1":
            base_equity = None
            if out:
                base_equity = out[0].get("equity")
            if base_equity is None:
                try:
                    sym = _default_symbol()
                    market_type = _resolve_market_type(sym)
                    if _use_mock():
                        base_equity = 1000.0
                    elif market_type == "futures":
                        client = KucoinFuturesClient()
                        overview = client.get_account_overview(currency="USDT")
                        margin_balance = overview.get("marginBalance", 0)
                        account_equity = overview.get("accountEquity", margin_balance)
                        base_equity = float(account_equity)
                    else:
                        client = KucoinClient()
                        accounts = client.get_accounts()
                        normalized = normalize_balances(accounts, timestamp=_now_iso())
                        if normalized:
                            base_equity = float(normalized[0].get("balance", 0))
                except Exception:
                    base_equity = base_equity
            if base_equity is not None:
                close_query = db.query(LogEntry).filter(
                    LogEntry.event == "position_close"
                )
                if session_start:
                    close_query = close_query.filter(
                        LogEntry.timestamp >= session_start
                    )
                close_rows = close_query.order_by(LogEntry.timestamp).all()
                series = []
                realized_total = 0.0
                for row in close_rows:
                    realized = None
                    try:
                        details = json.loads(row.details) if row.details else {}
                    except Exception:
                        details = {}
                    if isinstance(details, dict):
                        if details.get("realized_pnl") is not None:
                            realized = details.get("realized_pnl")
                        elif isinstance(details.get("position"), dict):
                            realized = details["position"].get("realized_pnl")
                    try:
                        if realized is not None:
                            realized = float(realized)
                    except Exception:
                        realized = None
                    if realized is None:
                        continue
                    realized_total += realized
                    ts = row.timestamp.isoformat()
                    series.append(
                        {
                            "timestamp": ts,
                            "equity": base_equity + realized_total,
                        }
                    )
                # Add current unrealized on top of realized curve
                unreal = 0.0
                try:
                    positions = _positions_as_map()
                    if isinstance(positions, dict):
                        for pos in positions.values():
                            try:
                                pnl_val = pos.get("unrealized_pnl")
                                if pnl_val is not None:
                                    unreal += float(pnl_val)
                            except Exception:
                                continue
                except Exception:
                    unreal = unreal
                series.append(
                    {
                        "timestamp": _now_iso(),
                        "equity": base_equity + realized_total + unreal,
                    }
                )
                if len(series) > limit:
                    series = series[-limit:]
                return series
        return out
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    finally:
        db.close()


@app.get("/metrics")
def get_metrics(limit: int = Query(30, ge=1, le=500)):
    try:
        db = SessionLocal()
        equity_rows = (
            db.query(Equity)
            .order_by(desc(Equity.timestamp))
            .limit(min(max(limit * 5, 500), 2000))
            .all()[::-1]
        )
        equity_rows, session_start = _filter_equity_session(equity_rows)
        equity_map = {}
        for e in equity_rows:
            eq_val = _sanitize_equity_value(e.equity)
            if eq_val is None:
                continue
            equity_map[e.timestamp.replace(second=0, microsecond=0)] = eq_val
        decision_query = db.query(Decision).order_by(desc(Decision.timestamp))
        if session_start:
            decision_query = decision_query.filter(Decision.timestamp >= session_start)
        decisions = decision_query.limit(limit * 5).all()
        result = []
        for d in decisions:
            trend = volatility = tick = None
            try:
                parsed = json.loads(d.details)
                trend = parsed.get("trend")
                volatility = parsed.get("volatility")
                tick = parsed.get("tick")
            except Exception:
                trend_match = re.search(r"trend=([A-Z_]+)", d.details)
                vol_match = re.search(r"volatility=([\d\.]+)", d.details)
                tick_match = re.search(r"tick=([\d]+)", d.details)
                if trend_match:
                    trend = trend_match.group(1)
                if vol_match:
                    volatility = float(vol_match.group(1))
                if tick_match:
                    tick = int(tick_match.group(1))
            equity_val = equity_map.get(d.timestamp.replace(second=0, microsecond=0))
            result.append(
                {
                    "timestamp": d.timestamp.isoformat(),
                    "trend": trend,
                    "volatility": volatility,
                    "tick": tick,
                    "equity": equity_val,
                }
            )
        # Deduplicate by timestamp + trend/volatility (prefer newest)
        deduped_desc = []
        seen = set()
        for item in result:
            ts_key = item.get("timestamp")
            if ts_key:
                ts_key = ts_key.split(".")[0]
            key = (ts_key, item.get("trend"), item.get("volatility"))
            if key in seen:
                continue
            seen.add(key)
            deduped_desc.append(item)
            if len(deduped_desc) >= limit:
                break
        deduped = list(reversed(deduped_desc))
        # Carry forward last known tick for smoother UI when missing
        last_tick = None
        for item in deduped:
            tick_val = item.get("tick")
            if tick_val is None and last_tick is not None:
                item["tick"] = last_tick
            elif tick_val is not None:
                last_tick = tick_val
        # If volatility is static/empty, compute a fallback from equity deltas
        vols = [i.get("volatility") for i in deduped if i.get("volatility") is not None]
        try:
            unique_vols = {round(float(v), 8) for v in vols}
        except Exception:
            unique_vols = set()
        if not unique_vols or len(unique_vols) <= 1:
            window = 5
            deltas = []
            prev_eq = None
            for item in deduped:
                eq = item.get("equity")
                if eq is None or prev_eq is None:
                    deltas.append(None)
                else:
                    deltas.append(float(eq) - float(prev_eq))
                prev_eq = eq if eq is not None else prev_eq
            for idx, item in enumerate(deduped):
                vals = [
                    d
                    for d in deltas[max(0, idx - window + 1) : idx + 1]
                    if d is not None
                ]
                if len(vals) >= 2:
                    mean = sum(vals) / len(vals)
                    var = sum((v - mean) ** 2 for v in vals) / len(vals)
                    item["volatility"] = var**0.5
        return deduped
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    finally:
        db.close()


@app.get("/logs")
@app.get("/logs/ai")
def get_logs(limit: int = Query(30, ge=1, le=500)):
    try:
        db = SessionLocal()
        logs = db.query(LogEntry).order_by(desc(LogEntry.timestamp)).limit(limit).all()
        return [
            {
                "timestamp": log.timestamp.isoformat(),
                "event": log.event,
                "details": log.details,
            }
            for log in logs
        ]
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    finally:
        db.close()


@app.get("/fl_events")
def get_fl_events(limit: int = Query(30, ge=1, le=500)):
    """Return recent federated learning (FL) events (event='fl_round')."""
    try:
        db = SessionLocal()
        logs = (
            db.query(LogEntry)
            .filter(LogEntry.event == "fl_round")
            .order_by(desc(LogEntry.timestamp))
            .limit(limit)
            .all()
        )
        return [
            {
                "timestamp": log.timestamp.isoformat(),
                "event": log.event,
                "details": log.details,
            }
            for log in logs
        ]
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    finally:
        db.close()


@app.get("/status")
def get_status():
    try:
        stats = compute_stats()
        return {
            "api": check_api(),
            "ticks": check_ticks(),
            "bot": check_bot_status(),
            "last_decision": get_last_decision(),
            **stats,
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/api/health")
def api_health():
    return {
        "status": "ok",
        "api": check_api(),
        "bot": check_bot_status(),
        "timestamp": _now_iso(),
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "timestamp": _now_iso(),
    }


@app.get("/api/market")
def api_market(
    symbol: str = Query(None),
    interval: str = Query("1min"),
    limit: int = Query(120, ge=1, le=500),
    depth: int = Query(20, ge=1, le=100),
):
    sym = symbol or _default_symbol()
    market_type = _resolve_market_type(sym)
    fetcher = MarketDataFetcher(market_type=market_type)
    if _use_mock():
        source = "mock"
    elif market_type == "futures":
        source = "kucoin-futures"
    else:
        source = "kucoin"
    ticker: dict = {}
    orderbook: dict = {}
    errors: dict = {}
    candles = []
    if _use_mock():
        candles = fetcher.get_ohlcv(sym, interval, limit=limit)
        candles = _normalize_ohlcv(candles)
        ok, idx = _validate_ohlcv(candles)
        if not ok:
            logging.error(f"OHLCV sanity failed at idx={idx} for {sym}")
            return JSONResponse(
                content={"error": "invalid_ohlcv_sanity", "symbol": sym},
                status_code=502,
            )
        last = candles[-1]["close"] if candles else None
        first = candles[0]["close"] if candles else None
        change_rate = None
        change_price = None
        if first and last:
            try:
                change_price = float(last) - float(first)
                change_rate = change_price / float(first) if float(first) else None
            except Exception:
                change_rate = None
        ticker = {"last": last, "changeRate": change_rate, "changePrice": change_price}
        orderbook = {"bestBid": None, "bestAsk": None, "bids": [], "asks": []}
    elif market_type == "futures":
        client = KucoinFuturesClient()
        try:
            ticker = client.get_ticker(sym)
        except Exception as e:
            errors["ticker"] = str(e)
        try:
            candles = _normalize_ohlcv(client.get_klines(sym, interval, limit=limit))
            ok, idx = _validate_ohlcv(candles)
            if not ok:
                logging.error(f"OHLCV sanity failed at idx={idx} for {sym}")
                return JSONResponse(
                    content={"error": "invalid_ohlcv_sanity", "symbol": sym},
                    status_code=502,
                )
        except Exception as e:
            errors["klines"] = str(e)
        orderbook = {
            "bestBid": ticker.get("bestBidPrice") if isinstance(ticker, dict) else None,
            "bestAsk": ticker.get("bestAskPrice") if isinstance(ticker, dict) else None,
            "bids": [],
            "asks": [],
        }
        # Normalize ticker keys to match dashboard expectations
        if isinstance(ticker, dict) and "price" in ticker and "last" not in ticker:
            ticker = {
                "last": ticker.get("price"),
                "changeRate": ticker.get("changeRate"),
                "changePrice": ticker.get("changePrice"),
                "bestBidPrice": ticker.get("bestBidPrice"),
                "bestAskPrice": ticker.get("bestAskPrice"),
            }
    else:
        sym_norm = normalize_symbol(sym)
        candles = _normalize_ohlcv(fetcher.get_ohlcv(sym_norm, interval, limit=limit))
        ok, idx = _validate_ohlcv(candles)
        if not ok:
            logging.error(f"OHLCV sanity failed at idx={idx} for {sym_norm}")
            return JSONResponse(
                content={"error": "invalid_ohlcv_sanity", "symbol": sym_norm},
                status_code=502,
            )
        client = KucoinClient()
        try:
            stats = client.get_market_stats(sym_norm)
            ticker = {
                "last": stats.get("last"),
                "changeRate": stats.get("changeRate"),
                "changePrice": stats.get("changePrice"),
                "high": stats.get("high"),
                "low": stats.get("low"),
                "vol": stats.get("vol"),
            }
        except Exception as e:
            errors["stats"] = str(e)
        try:
            level1 = client.get_level1_orderbook(sym_norm)
            orderbook.update(level1 if isinstance(level1, dict) else {})
        except Exception as e:
            errors["orderbook_level1"] = str(e)
        try:
            level2 = client.get_level2_orderbook(sym_norm, depth=depth)
            if isinstance(level2, dict):
                orderbook["bids"] = level2.get("bids", orderbook.get("bids", []))
                orderbook["asks"] = level2.get("asks", orderbook.get("asks", []))
        except Exception as e:
            errors["orderbook_level2"] = str(e)
    return {
        "symbol": sym,
        "as_of": _now_iso(),
        "source": source,
        "ticker": ticker,
        "orderbook": orderbook,
        "ohlcv": candles,
        "errors": errors or None,
    }


@app.get("/api/balance")
def api_balance(account_type: str = Query(None), symbol: str = Query(None)):
    sym = symbol or _default_symbol()
    market_type = _resolve_market_type(sym)
    if _use_mock():
        mock_balances = normalize_balances(
            [
                {
                    "type": "futures" if market_type == "futures" else "trade",
                    "currency": "USDT",
                    "available": "1000",
                    "holds": "0",
                    "balance": "1000",
                }
            ],
            timestamp=_now_iso(),
        )
        return {
            "source": "mock",
            "as_of": _now_iso(),
            "balances": mock_balances,
        }
    try:
        if market_type == "futures":
            client = KucoinFuturesClient()
            overview = client.get_account_overview(currency="USDT")
            total_balance = overview.get(
                "accountEquity", overview.get("marginBalance", 0)
            )
            balances = [
                {
                    "account_type": "futures",
                    "currency": "USDT",
                    "available": float(overview.get("availableBalance", 0)),
                    "holds": float(overview.get("frozenFunds", 0)),
                    "total": float(total_balance),
                    "timestamp": _now_iso(),
                }
            ]
            return {
                "source": "kucoin-futures",
                "as_of": _now_iso(),
                "balances": balances,
            }
        client = KucoinClient()
        accounts = client.get_accounts(account_type=account_type)
        normalized = normalize_balances(accounts, timestamp=_now_iso())
        return {
            "source": "kucoin",
            "as_of": _now_iso(),
            "balances": normalized,
        }
    except ValueError as e:
        msg = str(e)
        if "credentials missing" in msg.lower():
            return {
                "source": "kucoin-futures" if market_type == "futures" else "kucoin",
                "as_of": _now_iso(),
                "balances": [],
                "error": msg,
            }
        return JSONResponse(content={"error": msg}, status_code=400)
    except Exception as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg:
            return {
                "source": "kucoin-futures" if market_type == "futures" else "kucoin",
                "as_of": _now_iso(),
                "balances": [],
                "error": (
                    "KuCoin unauthorized: sprawdź poprawność kluczy "
                    "i uprawnienia Futures"
                ),
            }
        return JSONResponse(content={"error": msg}, status_code=502)


@app.get("/api/fills")
def api_fills(
    order_id: str = Query(...),
    symbol: str = Query(None),
    page: int = Query(1, ge=1, le=100),
    page_size: int = Query(50, ge=1, le=200),
):
    sym = symbol or _default_symbol()
    market_type = _resolve_market_type(sym)
    if market_type != "futures":
        return JSONResponse(
            content={"error": "fills supported only for futures in this API"},
            status_code=400,
        )
    try:
        client = KucoinFuturesClient()
        resp = client.get_fills(
            order_id=order_id,
            symbol=symbol,
            current_page=page,
            page_size=page_size,
        )
        items = _extract_fill_items(resp)
        avg_price, fee_total, size_total = _summarize_fills(items)
        return {
            "source": "kucoin-futures",
            "order_id": order_id,
            "symbol": symbol,
            "fills": items,
            "summary": {
                "avg_price": avg_price,
                "fee_total": fee_total,
                "size_total": size_total,
                "count": len(items),
            },
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=502)


@app.get("/api/report/trades_vs_exchange")
def report_trades_vs_exchange(
    limit: int = Query(50, ge=1, le=200),
    use_fills: int = Query(1, ge=0, le=1),
    symbol: str = Query(None),
):
    sym = symbol or _default_symbol()
    market_type = _resolve_market_type(sym)
    if market_type != "futures":
        return JSONResponse(
            content={"error": "report supported only for futures in this API"},
            status_code=400,
        )
    db = SessionLocal()
    try:
        query = db.query(LogEntry).filter(LogEntry.event == "position_close")
        if os.environ.get("NEW_SESSION", "0") == "1":
            query = query.filter(LogEntry.timestamp >= _session_anchor())
        rows = query.order_by(desc(LogEntry.timestamp)).limit(limit).all()
        client = KucoinFuturesClient()
        report = []
        totals = {
            "trades": 0,
            "realized_pnl_total": 0.0,
            "exchange_pnl_total": 0.0,
            "exchange_pnl_net_total": 0.0,
            "delta_total": 0.0,
        }
        for row in rows:
            try:
                details = json.loads(row.details) if row.details else {}
            except Exception:
                details = {}
            pos = details.get("position") if isinstance(details, dict) else None
            if not isinstance(pos, dict):
                pos = {}
            sym_row = details.get("symbol") or pos.get("symbol") or sym
            side = str(pos.get("side") or "").lower()
            amount = pos.get("amount")
            entry_price = pos.get("entry_price") or pos.get("price")
            close_price = details.get("close_price") or pos.get("close_price")
            realized_pnl = details.get("realized_pnl") or pos.get("realized_pnl")
            fee_cost = details.get("fee_cost") or pos.get("fee_cost")
            fee_open = pos.get("fee_cost_open") or details.get("fee_cost_open")
            fee_close = details.get("fee_cost_close") or details.get("fee_cost_close")
            entry_order_id = pos.get("entry_order_id") or details.get("entry_order_id")
            close_order_id = pos.get("close_order_id") or details.get("close_order_id")
            entry_fill = pos.get("fill_price")
            exit_fill = details.get("close_fill_price") or details.get("fill_price")
            exit_reason = (
                details.get("reason")
                or details.get("exit_reason")
                or pos.get("exit_reason")
            )

            entry_fill_price = None
            entry_fee = None
            exit_fill_price = None
            exit_fee = None

            if use_fills and entry_order_id:
                try:
                    resp = client.get_fills(order_id=entry_order_id, symbol=sym_row)
                    items = _extract_fill_items(resp)
                    entry_fill_price, entry_fee, _ = _summarize_fills(items)
                except Exception:
                    entry_fill_price = None
            if use_fills and close_order_id:
                try:
                    resp = client.get_fills(order_id=close_order_id, symbol=sym_row)
                    items = _extract_fill_items(resp)
                    exit_fill_price, exit_fee, _ = _summarize_fills(items)
                except Exception:
                    exit_fill_price = None

            if entry_fill_price is None:
                entry_fill_price = entry_fill or entry_price
            if exit_fill_price is None:
                exit_fill_price = exit_fill or close_price

            exchange_pnl = None
            exchange_pnl_net = None
            delta = None
            try:
                if (
                    entry_fill_price is not None
                    and exit_fill_price is not None
                    and amount is not None
                ):
                    entry_fill_price = float(entry_fill_price)
                    exit_fill_price = float(exit_fill_price)
                    amount = float(amount)
                    if side in ("sell", "short"):
                        exchange_pnl = (entry_fill_price - exit_fill_price) * amount
                    else:
                        exchange_pnl = (exit_fill_price - entry_fill_price) * amount
            except Exception:
                exchange_pnl = None

            fee_total = None
            try:
                if fee_cost is not None:
                    fee_total = float(fee_cost)
                else:
                    fee_total = 0.0
                    if entry_fee is not None:
                        fee_total += float(entry_fee)
                    if exit_fee is not None:
                        fee_total += float(exit_fee)
                    if fee_total == 0.0 and (fee_open or fee_close):
                        fee_total = float(fee_open or 0.0) + float(fee_close or 0.0)
            except Exception:
                fee_total = fee_total

            if exchange_pnl is not None:
                if fee_total is not None:
                    exchange_pnl_net = exchange_pnl - float(fee_total)
                else:
                    exchange_pnl_net = exchange_pnl
            try:
                if realized_pnl is not None and exchange_pnl_net is not None:
                    delta = float(exchange_pnl_net) - float(realized_pnl)
            except Exception:
                delta = None

            ts_val = pos.get("timestamp") or row.timestamp.isoformat()
            close_ts_val = pos.get("close_timestamp") or row.timestamp.isoformat()
            report.append(
                {
                    "symbol": sym_row,
                    "side": side,
                    "amount": amount,
                    "entry_price": entry_price,
                    "close_price": close_price,
                    "entry_fill_price": entry_fill_price,
                    "exit_fill_price": exit_fill_price,
                    "entry_order_id": entry_order_id,
                    "close_order_id": close_order_id,
                    "exit_reason": exit_reason,
                    "realized_pnl": realized_pnl,
                    "exchange_pnl": exchange_pnl,
                    "exchange_pnl_net": exchange_pnl_net,
                    "fee_total": fee_total,
                    "delta": delta,
                    "timestamp": ts_val,
                    "close_timestamp": close_ts_val,
                }
            )
            totals["trades"] += 1
            try:
                if realized_pnl is not None:
                    totals["realized_pnl_total"] += float(realized_pnl)
            except Exception:
                pass
            try:
                if exchange_pnl is not None:
                    totals["exchange_pnl_total"] += float(exchange_pnl)
            except Exception:
                pass
            try:
                if exchange_pnl_net is not None:
                    totals["exchange_pnl_net_total"] += float(exchange_pnl_net)
            except Exception:
                pass
            try:
                if delta is not None:
                    totals["delta_total"] += float(delta)
            except Exception:
                pass
        return {"summary": totals, "trades": report}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    finally:
        db.close()


@app.get("/api/paper_state")
def api_paper_state():
    # Return positions + lightweight runtime stats so monitoring tools can
    # observe net_pnl_15m and the autoscaler state without calling /performance.
    try:
        stats = compute_stats()
    except Exception:
        stats = {}
    autoscaler_state = {
        "enabled": os.environ.get("AUTO_MONITOR_ENABLE", "0") == "1",
        "mode": os.environ.get("AUTO_MONITOR_MODE", "pnl"),
        "kp": os.environ.get("AUTO_MONITOR_KP"),
        "ramp_pct": os.environ.get("AUTO_MONITOR_RAMP_PCT"),
        "max_scale": os.environ.get("AUTO_MONITOR_MAX_SCALE"),
        "runtime_scale": getattr(app.state, "autoscaler_scale", None),
        "smoothed_pnl": getattr(app.state, "autoscaler_smoothed_pnl", None),
        "history": getattr(app.state, "autoscaler_history", None),
    }
    # Prefer latest runtime_allocation persisted in DB (if present),
    # otherwise fall back to environment `allocation_pct`.
    runtime_alloc = os.environ.get("allocation_pct")
    try:
        db = SessionLocal()
        last = (
            db.query(LogEntry)
            .filter(LogEntry.event == "runtime_allocation")
            .order_by(desc(LogEntry.timestamp))
            .first()
        )
        if last and last.details:
            try:
                parsed = (
                    json.loads(last.details)
                    if isinstance(last.details, str)
                    else last.details
                )
                if (
                    isinstance(parsed, dict)
                    and parsed.get("allocation_pct") is not None
                ):
                    runtime_alloc = parsed.get("allocation_pct")
            except Exception:
                pass
    except Exception:
        pass
    finally:
        try:
            db.close()
        except Exception:
            pass

    return {
        "as_of": _now_iso(),
        "positions": _positions_as_map(),
        "closed_positions": get_closed_positions(),
        "position_history": getattr(position_manager, "position_history", {}),
        "stats": stats,
        "autoscaler": autoscaler_state,
        "runtime_allocation_pct": runtime_alloc,
    }


@app.get("/api/logs")
def api_logs(limit: int = Query(30, ge=1, le=500)):
    return get_logs(limit)


@app.get("/performance")
def get_performance():
    try:
        stats = compute_stats()
        open_trades = len(_positions_as_map())
        paper_unrealized = None
        realized_pnl_total = None
        closed_count = None
        entry_count = None
        session_start = None
        equity_has_data = False
        try:
            db_tmp = SessionLocal()
            eq_rows = (
                db_tmp.query(Equity)
                .order_by(desc(Equity.timestamp))
                .limit(1000)
                .all()[::-1]
            )
            filtered_rows, session_start = _filter_equity_session(eq_rows)
            session_start = _session_floor(session_start)
            log_anchor = (
                _session_anchor()
                if os.environ.get("NEW_SESSION", "0") == "1"
                else session_start
            )
            equity_has_data = bool(filtered_rows)
        except Exception:
            session_start = None
            equity_has_data = False
        finally:
            try:
                db_tmp.close()
            except Exception:
                pass
        try:
            if not equity_has_data:
                realized_pnl_total = 0.0
                rows = []
                db = None
            else:
                db = SessionLocal()
                log_query = db.query(LogEntry).filter(
                    LogEntry.event == "position_close"
                )
                if log_anchor:
                    log_query = log_query.filter(LogEntry.timestamp >= log_anchor)
                rows = log_query.order_by(desc(LogEntry.timestamp)).limit(500).all()
                closed_count = len(rows)
                # Count entry executions for trade count
                entry_query = db.query(LogEntry).filter(
                    LogEntry.event.in_(
                        ["order_simulated", "order_executed", "position_open"]
                    )
                )
                if log_anchor:
                    entry_query = entry_query.filter(LogEntry.timestamp >= log_anchor)
                try:
                    entry_count = entry_query.count()
                except Exception:
                    try:
                        entry_count = len(entry_query.all())
                    except Exception:
                        entry_count = None
            total = 0.0
            any_val = False
            for row in rows:
                try:
                    details = json.loads(row.details) if row.details else {}
                    val = details.get("realized_pnl")
                    if isinstance(val, (int, float)):
                        total += float(val)
                        any_val = True
                except Exception:
                    continue
            realized_pnl_total = total if any_val else 0.0
            if not rows or not any_val:
                try:
                    closed = getattr(position_manager, "closed_positions", None)
                    if closed:
                        fallback_total = 0.0
                        any_fallback = False
                        for pos in closed:
                            try:
                                val = pos.get("realized_pnl")
                                if isinstance(val, (int, float)):
                                    fallback_total += float(val)
                                    any_fallback = True
                            except Exception:
                                continue
                        if any_fallback:
                            realized_pnl_total = fallback_total
                            closed_count = len(closed)
                except Exception:
                    pass
        except Exception:
            realized_pnl_total = None
        finally:
            try:
                if db is not None:
                    db.close()
            except Exception:
                pass
        try:
            positions = _positions_as_map()
            if positions:
                total = 0.0
                client = KucoinFuturesClient()
                for sym, pos in positions.items():
                    if not is_futures_symbol(sym):
                        continue
                    try:
                        ticker = client.get_ticker(sym)
                        last_price = None
                        if isinstance(ticker, dict):
                            last_price = ticker.get("price") or ticker.get("last")
                        entry = pos.get("entry_price") or pos.get("price")
                        amount = pos.get("amount")
                        side = str(pos.get("side", "")).lower()
                        if last_price is None or entry is None or amount is None:
                            continue
                        if side in ("sell", "short"):
                            total += (float(entry) - float(last_price)) * float(amount)
                        else:
                            total += (float(last_price) - float(entry)) * float(amount)
                    except Exception:
                        continue
                paper_unrealized = total
        except Exception:
            paper_unrealized = None
        # If there is no equity data, mark has_data False and return null pnl
        if not stats.get("has_data", False) or stats.get("final_balance") is None:
            gate_state = get_paper_gate_state()
            trades_candidates = [
                v
                for v in (
                    entry_count,
                    closed_count,
                    stats.get("trades", 0),
                    open_trades,
                )
                if isinstance(v, int)
            ]
            trades_value = max(trades_candidates) if trades_candidates else 0
            return {
                "pnl": None,
                "has_data": False,
                "winrate": stats.get("winrate", 0),
                "drawdown": stats.get("drawdown", 0),
                "open_trades": open_trades,
                "decisions": stats.get("decisions", 0),
                "trades": trades_value,
                "realized_pnl_total": realized_pnl_total,
                "sharpe": None,
                "sortino": None,
                "net_pnl_15m": stats.get("net_pnl_15m"),
                "net_pnl_15m_target": 0.5,
                "net_pnl_15m_ok": False,
                "paper_gate": "ACTIVE" if gate_state.get("active") else "INACTIVE",
                "paper_gate_reason": gate_state.get("reason"),
                "paper_gate_until": gate_state.get("active_until"),
                "paper_gate_mode": gate_state.get("mode"),
                "paper_gate_trigger_count": gate_state.get("trigger_count"),
            }
        final_balance = stats.get("final_balance", 0)
        initial_balance = stats.get("initial_balance")
        baseline = initial_balance if initial_balance is not None else 10000
        pnl = final_balance - baseline
        if paper_unrealized is not None:
            pnl = paper_unrealized
        net_pnl_15m = stats.get("net_pnl_15m")
        target = 0.5
        net_ok = (
            net_pnl_15m is not None
            and isinstance(net_pnl_15m, (int, float))
            and net_pnl_15m >= target
        )
        gate_state = get_paper_gate_state()
        trades_candidates = [
            v
            for v in (entry_count, closed_count, stats.get("trades"), open_trades)
            if isinstance(v, int)
        ]
        trades_value = max(trades_candidates) if trades_candidates else 0
        return {
            "pnl": round(pnl, 2),
            "has_data": True,
            "winrate": stats.get("winrate"),
            "drawdown": stats.get("drawdown"),
            "open_trades": open_trades,
            "decisions": stats.get("decisions"),
            "trades": trades_value,
            "realized_pnl_total": realized_pnl_total,
            "sharpe": stats.get("sharpe"),
            "sortino": stats.get("sortino"),
            "net_pnl_15m": net_pnl_15m,
            "net_pnl_15m_target": target,
            "net_pnl_15m_ok": net_ok,
            "paper_gate": "ACTIVE" if gate_state.get("active") else "INACTIVE",
            "paper_gate_reason": gate_state.get("reason"),
            "paper_gate_until": gate_state.get("active_until"),
            "paper_gate_mode": gate_state.get("mode"),
            "paper_gate_trigger_count": gate_state.get("trigger_count"),
        }
    except Exception as e:
        return JSONResponse(
            content={"error": f"Błąd /performance: {str(e)}"}, status_code=500
        )


@app.get("/metrics/live")
def metrics_live():
    try:
        db = SessionLocal()
        decision = db.query(Decision).order_by(desc(Decision.timestamp)).first()
        if not decision:
            return JSONResponse(content={"error": "no_data"}, status_code=404)

        trend = volatility = tick = None
        try:
            parsed = json.loads(decision.details)
            trend = parsed.get("trend")
            volatility = parsed.get("volatility")
            tick = parsed.get("tick")
        except Exception:
            trend_match = re.search(r"trend=([A-Z_]+)", decision.details or "")
            vol_match = re.search(r"volatility=([\d\.]+)", decision.details or "")
            tick_match = re.search(r"tick=([\d]+)", decision.details or "")
            if trend_match:
                trend = trend_match.group(1)
            if vol_match:
                try:
                    volatility = float(vol_match.group(1))
                except Exception:
                    volatility = None
            if tick_match:
                try:
                    tick = int(tick_match.group(1))
                except Exception:
                    tick = None

        equity_val = None
        try:
            ts = decision.timestamp
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts is not None:
                ts_floor = ts.replace(second=0, microsecond=0)
                eq_row = (
                    db.query(Equity)
                    .filter(
                        Equity.timestamp >= ts_floor,
                        Equity.timestamp < (ts_floor + timedelta(minutes=1)),
                    )
                    .order_by(desc(Equity.timestamp))
                    .first()
                )
            else:
                eq_row = None
            if not eq_row:
                eq_row = db.query(Equity).order_by(desc(Equity.timestamp)).first()
            if eq_row:
                equity_val = _sanitize_equity_value(eq_row.equity)
        except Exception:
            equity_val = None

        if volatility is None:
            try:
                eq_rows = (
                    db.query(Equity)
                    .order_by(desc(Equity.timestamp))
                    .limit(6)
                    .all()[::-1]
                )
                eq_vals = [
                    _sanitize_equity_value(r.equity)
                    for r in eq_rows
                    if _sanitize_equity_value(r.equity) is not None
                ]
                if len(eq_vals) >= 3:
                    deltas = [
                        float(eq_vals[i]) - float(eq_vals[i - 1])
                        for i in range(1, len(eq_vals))
                    ]
                    if deltas:
                        mean = sum(deltas) / len(deltas)
                        var = sum((d - mean) ** 2 for d in deltas) / len(deltas)
                        volatility = var**0.5
            except Exception:
                pass

        return {
            "timestamp": decision.timestamp.isoformat(),
            "trend": trend,
            "volatility": volatility,
            "tick": tick,
            "equity": equity_val,
        }
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
    finally:
        db.close()


def compute_stats():
    # visible debug output for containerized tests (temporary)
    try:
        print(f"compute_stats invoked — file={__file__}, SessionLocal={SessionLocal}")
    except Exception:
        print(f"compute_stats invoked — file={__file__}")
    logging.info(f"compute_stats called from {__file__}")
    db = SessionLocal()
    try:
        try:
            open_trades = len(_positions_as_map())
        except Exception:
            open_trades = 0
        equity_rows = (
            db.query(Equity).order_by(desc(Equity.timestamp)).limit(1000).all()[::-1]
        )
        equity_rows, session_start = _filter_equity_session(equity_rows)
        session_start = _session_floor(session_start)
        decision_anchor = (
            _session_anchor()
            if os.environ.get("NEW_SESSION", "0") == "1"
            else session_start
        )
        if not equity_rows and session_start is None:
            session_start = _session_floor(datetime.now(timezone.utc))
        equity = []
        for e in equity_rows:
            eq_val = _sanitize_equity_value(e.equity)
            if eq_val is None:
                continue
            equity.append(eq_val)
        initial_balance = equity[0] if equity else None
        # Rolling 15m net PnL
        net_pnl_15m = None
        try:
            window_start = datetime.now(timezone.utc) - timedelta(minutes=15)
            if decision_anchor:
                try:
                    anchor_ts = decision_anchor
                    if anchor_ts.tzinfo is None:
                        anchor_ts = anchor_ts.replace(tzinfo=timezone.utc)
                    if anchor_ts > window_start:
                        window_start = anchor_ts
                except Exception:
                    pass
            # Normalize datetime for DB comparison: SQLAlchemy/SQLite stores
            # timestamps as tz-naive. Strip tzinfo from `window_start` so the
            # filter matches inserted Equity rows (which may be saved as naive).
            try:
                db_window_start = (
                    window_start.replace(tzinfo=None)
                    if getattr(window_start, "tzinfo", None) is not None
                    else window_start
                )
            except Exception:
                db_window_start = window_start
            # Pull candidate rows from DB (use db_window_start to avoid
            # fetching the whole table)
            # and perform Python-side timestamp comparisons
            # to avoid tz-naive / tz-aware mismatches
            all_rows = (
                db.query(Equity)
                .filter(Equity.timestamp >= db_window_start)
                .order_by(Equity.timestamp)
                .all()
            )
            eq_window = []
            for row in all_rows:
                try:
                    ts = row.timestamp
                    # normalize stored timestamp to timezone-aware UTC for
                    # comparison with `window_start`
                    if ts is not None and ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts is not None and ts >= window_start:
                        eq_window.append(row)
                except Exception:
                    continue

            eq_vals = []
            for row in eq_window:
                eq_val = _sanitize_equity_value(row.equity)
                if eq_val is not None:
                    eq_vals.append(eq_val)
            # debug info for failing tests: log counts / timestamps
            try:
                logging.debug(
                    "compute_stats: eq_window_count=%d, eq_vals_count=%d, "
                    "window_start=%s",
                    len(eq_window),
                    len(eq_vals),
                    window_start.isoformat(),
                )
                if eq_window:
                    ts_list = ", ".join(
                        str(getattr(r, "timestamp", None)) for r in eq_window  # noqa: E501
                    )
                    logging.debug("compute_stats: eq_window_ts=[%s]", ts_list)
            except Exception:
                pass
            if len(eq_vals) >= 2:
                net_pnl_15m = eq_vals[-1] - eq_vals[0]
            elif len(eq_vals) == 1:
                # single sample in window -> treat as zero net movement
                net_pnl_15m = 0.0
            else:
                # No samples in the 15m window. Fall back to recent equity
                # history (if available) so monitoring can make progress when
                # sampling is sparse. Use the last two sanitized equity values
                # from the overall `equity` list if present.
                try:
                    if len(equity) >= 2:
                        net_pnl_15m = equity[-1] - equity[-2]
                        logging.debug(
                            "compute_stats: fallback net_pnl_15m from last two equity rows"
                        )
                    elif len(equity) == 1:
                        net_pnl_15m = 0.0
                except Exception:
                    net_pnl_15m = None
            if net_pnl_15m is not None:
                logging.info(f"net_pnl_15m={net_pnl_15m}")
        except Exception as e:
            logging.warning(f"net_pnl_15m compute error: {e}")
        drawdown = 0.0
        final_balance = equity[-1] if equity else None
        peak = equity[0] if equity else 0.0
        for val in equity:
            if val > peak:
                peak = val
            dd = (peak - val) / peak if peak else 0.0
            drawdown = max(drawdown, dd)
        decision_query = db.query(Decision.id)
        if decision_anchor:
            decision_query = decision_query.filter(
                Decision.timestamp >= decision_anchor
            )
        decisions_total = decision_query.count()
        decision_wins_query = db.query(Decision.id).filter(
            Decision.decision.in_(["win", "tp", "take_profit"])
        )
        if decision_anchor:
            decision_wins_query = decision_wins_query.filter(
                Decision.timestamp >= decision_anchor
            )
        decision_wins = decision_wins_query.count()
        closed_count = None
        closed_wins = 0
        closed_with_pnl = 0
        try:
            close_query = db.query(LogEntry).filter(LogEntry.event == "position_close")
            if decision_anchor:
                close_query = close_query.filter(LogEntry.timestamp >= decision_anchor)
            close_rows = close_query.order_by(desc(LogEntry.timestamp)).limit(5000).all()
            closed_count = len(close_rows)
            for row in close_rows:
                try:
                    details = json.loads(row.details) if row.details else {}
                except Exception:
                    details = {}
                if not isinstance(details, dict):
                    continue
                realized = details.get("realized_pnl")
                if realized is None:
                    pos = details.get("position")
                    if isinstance(pos, dict):
                        realized = pos.get("realized_pnl")
                if isinstance(realized, (int, float)):
                    closed_with_pnl += 1
                    if float(realized) > 0:
                        closed_wins += 1
        except Exception:
            closed_count = None
        if closed_with_pnl > 0:
            winrate = closed_wins / closed_with_pnl
        else:
            winrate = decision_wins / decisions_total if decisions_total > 0 else 0.0
        returns = (
            [equity[i + 1] - equity[i] for i in range(len(equity) - 1)]
            if len(equity) > 1
            else []
        )
        sharpe = sortino = None
        if returns:
            mean_ret = sum(returns) / len(returns)
            std_ret = (
                (sum((r - mean_ret) ** 2 for r in returns) / len(returns)) ** 0.5
                if len(returns) > 1
                else 0
            )
            downside = [r for r in returns if r < 0]
            std_down = (
                (sum((r - mean_ret) ** 2 for r in downside) / len(downside)) ** 0.5
                if downside
                else 0
            )
            sharpe = round(mean_ret / std_ret, 2) if std_ret else None
            sortino = round(mean_ret / std_down, 2) if std_down else None
        return {
            "initial_balance": initial_balance,
            "final_balance": final_balance,
            "has_data": bool(equity),
            "drawdown": round(drawdown * 100, 2),
            "winrate": round(winrate * 100, 2),
            "open_trades": open_trades,
            "decisions": decisions_total,
            "trades": closed_count if closed_count is not None else decisions_total,
            "sharpe": sharpe,
            "sortino": sortino,
            "net_pnl_15m": net_pnl_15m,
        }
    finally:
        db.close()


def get_last_decision():
    try:
        db = SessionLocal()
        last = db.query(Decision).order_by(desc(Decision.timestamp)).first()
        if last:
            return {
                "timestamp": last.timestamp.isoformat(),
                "decision": last.decision,
                "details": last.details,
            }
        return None
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()


def parse_details(details: str):
    regexes = {
        "trend": r"trend=([A-Z_]+)",
        "volatility": r"volatility=([\d\.]+)",
        "symbol": r"symbol=([A-Z0-9]+)",
        "strategy": r"strategy=([a-zA-Z0-9_]+)",
        "status": r"status=([a-zA-Z0-9_]+)",
        "source": r"source=(LLM|metrics|manual)",
    }
    return {
        k: (re.search(rx, details).group(1) if re.search(rx, details) else None)
        for k, rx in regexes.items()
    }


def parse_decision_row(row):
    try:
        if not isinstance(row, list) or len(row) < 2:
            return {"error": "Invalid row format"}
        timestamp, decision = row[0], row[1]
        details = row[2] if len(row) > 2 else ""
        parsed = parse_details(details)
        return {
            "timestamp": timestamp,
            "decision": decision,
            **parsed,
            "details": details,
        }
    except Exception as e:
        return {"error": f"Error parsing row: {str(e)}"}
