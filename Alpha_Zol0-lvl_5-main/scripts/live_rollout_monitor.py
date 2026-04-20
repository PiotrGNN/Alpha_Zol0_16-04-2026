#!/usr/bin/env python3
"""
ZoL0 Live Rollout Monitor — real-time hard-stop guard.

Polls the live run DB every N seconds and checks four hard-stop conditions:
  1. abnormal_exit_delay   – post_green_bnr_time_forced_exit_sec > threshold
  2. loss_clustering       – >= N consecutive losing trades
  3. contract_inconsistency – position_close with triggered post_green but
     missing attribution fields
  4. max_drawdown          – cumulative realized PnL drawdown exceeds threshold

Also logs milestone events (30 closed trades, 24h elapsed) to the console.

Usage:
  python scripts/live_rollout_monitor.py [--db-path PATH] [--poll-sec 30]
                                         [--stop-on-hard-stop]

Hard stop output is written to tmp/live_hard_stop.json.
Console output is written to tmp/live_rollout_monitor.log (and stdout).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = ROOT / "tmp"
HARD_STOP_FILE = TMP_DIR / "live_hard_stop.json"
MONITOR_LOG_FILE = TMP_DIR / "live_rollout_monitor.log"

# --- Hard stop thresholds (env override supported) ---
ABNORMAL_EXIT_DELAY_SEC: int = int(
    os.getenv("LIVE_ROLLOUT_ABNORMAL_EXIT_DELAY_SEC", "120")
)
MAX_CONSECUTIVE_LOSSES: int = int(
    os.getenv("LIVE_ROLLOUT_MAX_CONSECUTIVE_LOSSES", "3")
)
MAX_DRAWDOWN_PCT: float = float(
    os.getenv("LIVE_ROLLOUT_MAX_DRAWDOWN_PCT", "0.02")
)

# Milestone thresholds (informational, not hard stops)
TARGET_CLOSED_TRADES: int = int(
    os.getenv("LIVE_ROLLOUT_TARGET_CLOSED_TRADES", "30")
)

# Post-green attribution fields required on every post-green close
_POST_GREEN_REQUIRED = (
    "post_green_attempt_seq",
    "post_green_branch_seq",
    "post_green_trigger_mode",
    "post_green_trigger_reason_detail",
    "post_green_peak_to_burden_ratio",
    "post_green_bnr_time_forced_exit_sec",
)


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("live_monitor")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(MONITOR_LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def _discover_latest_db() -> Path | None:
    """Auto-discover the most recently written live run DB in tmp/."""
    candidates = sorted(
        TMP_DIR.glob("controlled_kpi_after_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _load_closes(cur) -> list[dict]:
    """Load all position_close events ordered by id."""
    cur.execute(
        "SELECT id, timestamp, details FROM logs "
        "WHERE event='position_close' ORDER BY id"
    )
    result = []
    for id_, ts, det in cur.fetchall():
        try:
            d = json.loads(det) if det else {}
        except Exception:
            d = {}
        d["_id"] = id_
        d["_ts"] = ts
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Hard stop checks
# ---------------------------------------------------------------------------

def _check_abnormal_exit_delay(closes: list[dict]) -> dict | None:
    for c in closes:
        delay = c.get("post_green_bnr_time_forced_exit_sec")
        if delay is None:
            continue
        try:
            delay_f = float(delay)
        except (TypeError, ValueError):
            continue
        if delay_f > ABNORMAL_EXIT_DELAY_SEC:
            return {
                "condition": "abnormal_exit_delay",
                "trade_id": c.get("trade_id"),
                "symbol": c.get("symbol"),
                "delay_sec": round(delay_f, 2),
                "threshold_sec": ABNORMAL_EXIT_DELAY_SEC,
                "ts": c.get("_ts"),
            }
    return None


def _check_loss_clustering(closes: list[dict]) -> dict | None:
    streak = 0
    max_streak = 0
    streak_start_ts = None
    for c in closes:
        pnl = c.get("realized_pnl")
        if pnl is None:
            continue
        try:
            pnl_f = float(pnl)
        except (TypeError, ValueError):
            continue
        if pnl_f < 0:
            if streak == 0:
                streak_start_ts = c.get("_ts")
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
            streak_start_ts = None
    if max_streak >= MAX_CONSECUTIVE_LOSSES:
        return {
            "condition": "loss_clustering",
            "max_consecutive_losses": max_streak,
            "threshold": MAX_CONSECUTIVE_LOSSES,
            "streak_start_ts": streak_start_ts,
        }
    return None


def _check_contract_inconsistency(closes: list[dict]) -> dict | None:
    for c in closes:
        trigger_mode = c.get("post_green_trigger_mode")
        if trigger_mode is None:
            # Not a post-green exit – skip
            continue
        missing = [f for f in _POST_GREEN_REQUIRED if c.get(f) is None]
        if missing:
            return {
                "condition": "contract_inconsistency",
                "trade_id": c.get("trade_id"),
                "symbol": c.get("symbol"),
                "missing_fields": missing,
                "ts": c.get("_ts"),
            }
    return None


def _check_max_drawdown(closes: list[dict]) -> dict | None:
    cum_pnl = 0.0
    peak = 0.0
    max_dd = 0.0
    for c in closes:
        pnl = c.get("realized_pnl")
        if pnl is None:
            continue
        try:
            cum_pnl += float(pnl)
        except (TypeError, ValueError):
            continue
        peak = max(peak, cum_pnl)
        dd = (peak - cum_pnl) / abs(peak) if abs(peak) > 1e-10 else 0.0
        max_dd = max(max_dd, dd)
    if max_dd > MAX_DRAWDOWN_PCT:
        return {
            "condition": "max_drawdown",
            "max_drawdown_pct": round(max_dd * 100, 3),
            "threshold_pct": round(MAX_DRAWDOWN_PCT * 100, 3),
        }
    return None


def _run_all_checks(closes: list[dict]) -> list[dict]:
    triggered = []
    for fn in (
        _check_abnormal_exit_delay,
        _check_loss_clustering,
        _check_contract_inconsistency,
        _check_max_drawdown,
    ):
        result = fn(closes)
        if result:
            triggered.append(result)
    return triggered


# ---------------------------------------------------------------------------
# Main monitor loop
# ---------------------------------------------------------------------------

def monitor_loop(
    *,
    db_path: Path,
    poll_sec: int,
    stop_on_hard_stop: bool,
    log: logging.Logger,
) -> None:
    import sqlite3

    log.info("=" * 70)
    log.info("ZoL0 LIVE ROLLOUT MONITOR — starting")
    log.info("  DB:          %s", db_path)
    log.info("  Poll:        %ds", poll_sec)
    log.info("  Hard stop file: %s", HARD_STOP_FILE)
    log.info(
        "  Thresholds: exit_delay>%ds | consec_losses>=%d | drawdown>%.1f%%",
        ABNORMAL_EXIT_DELAY_SEC,
        MAX_CONSECUTIVE_LOSSES,
        MAX_DRAWDOWN_PCT * 100,
    )
    log.info("  Target closed trades: %d", TARGET_CLOSED_TRADES)
    log.info("=" * 70)

    hard_stopped = False
    milestone_30_logged = False
    start_ts = time.time()
    prev_opens = -1
    prev_closes = -1

    while True:
        try:
            con = sqlite3.connect(
                f"file:{db_path}?mode=ro", uri=True, timeout=3
            )
            cur = con.cursor()

            cur.execute(
                "SELECT COUNT(*) FROM logs WHERE event='position_open'"
            )
            opens = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM logs WHERE event='position_close'"
            )
            total_closes = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM logs WHERE event='post_green_trigger'"
            )
            pg_triggers = cur.fetchone()[0]

            closes = _load_closes(cur)
            con.close()

            elapsed_h = (time.time() - start_ts) / 3600.0

            if opens != prev_opens or total_closes != prev_closes:
                log.info(
                    "STATUS  opens=%d  closes=%d  pg_triggers=%d  elapsed=%.1fh",
                    opens,
                    total_closes,
                    pg_triggers,
                    elapsed_h,
                )
                prev_opens = opens
                prev_closes = total_closes

            # Milestone: 30 closed trades
            if total_closes >= TARGET_CLOSED_TRADES and not milestone_30_logged:
                milestone_30_logged = True
                log.info(
                    "MILESTONE  %d closed trades reached. "
                    "You may now stop the run and run live_cohort_analysis.py.",
                    TARGET_CLOSED_TRADES,
                )

            # Hard stop checks
            if not hard_stopped:
                triggered = _run_all_checks(closes)
                if triggered:
                    hard_stopped = True
                    payload = {
                        "triggered_at": datetime.now(timezone.utc).isoformat(),
                        "db_path": str(db_path),
                        "conditions": triggered,
                        "total_opens": opens,
                        "total_closes": total_closes,
                        "elapsed_hours": round(elapsed_h, 2),
                    }
                    HARD_STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
                    HARD_STOP_FILE.write_text(
                        json.dumps(payload, indent=2), encoding="utf-8"
                    )
                    log.error("=" * 70)
                    log.error("*** HARD STOP TRIGGERED ***")
                    for cond in triggered:
                        log.error("  CONDITION: %s", cond)
                    log.error("  Hard stop file: %s", HARD_STOP_FILE)
                    log.error(
                        "  ACTION REQUIRED: Manually halt the live bot process."
                    )
                    log.error("=" * 70)
                    if stop_on_hard_stop:
                        sys.exit(2)

        except Exception as exc:  # noqa: BLE001
            log.warning("DB query error: %s", exc)

        time.sleep(poll_sec)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="ZoL0 live rollout hard-stop monitor",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to live run DB (auto-discovers latest in tmp/ if omitted)",
    )
    ap.add_argument(
        "--poll-sec",
        type=int,
        default=30,
        help="Poll interval in seconds",
    )
    ap.add_argument(
        "--stop-on-hard-stop",
        action="store_true",
        help="Exit with code 2 on hard stop (useful for CI / wrapper scripts)",
    )
    args = ap.parse_args()

    log = _setup_logging()

    db_path = args.db_path
    if db_path is None:
        db_path = _discover_latest_db()
        if db_path is None:
            log.error(
                "No DB found in %s. Pass --db-path explicitly or wait for "
                "the run to create a DB.",
                TMP_DIR,
            )
            sys.exit(1)
        log.info("Auto-discovered DB: %s", db_path)

    # Wait for DB to appear (up to 5 minutes)
    if not db_path.exists():
        log.info("Waiting for DB to appear: %s", db_path)
        for _ in range(60):
            time.sleep(5)
            if db_path.exists():
                log.info("DB found.")
                break
        else:
            log.error("DB never appeared after 5 minutes. Aborting.")
            sys.exit(1)

    monitor_loop(
        db_path=db_path,
        poll_sec=args.poll_sec,
        stop_on_hard_stop=args.stop_on_hard_stop,
        log=log,
    )


if __name__ == "__main__":
    main()
