#!/usr/bin/env python3
"""
ZoL0 Live Rollout Cohort Analysis — post-session trade analytics.

Reads a completed live run DB and produces a full 5-section report:
  A. Live rollout summary
  B. Trade cohort metrics
  C. Exit timing validation
  D. Risk anomalies
  E. Recommendation: EXTEND / SCALE / ROLLBACK

Usage:
  python scripts/live_cohort_analysis.py [--db-path PATH]
                                         [--out-json PATH]
                                         [--out-md PATH]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = ROOT / "tmp"
REPORTS_DIR = ROOT / "reports" / "live_rollout"

# Post-green attribution fields that must be present on every post-green close
_POST_GREEN_REQUIRED = (
    "post_green_attempt_seq",
    "post_green_branch_seq",
    "post_green_trigger_mode",
    "post_green_trigger_reason_detail",
    "post_green_peak_to_burden_ratio",
    "post_green_bnr_time_forced_exit_sec",
)

# Recommendation thresholds
_ROLLBACK_WIN_RATE = 0.40
_SCALE_WIN_RATE = 0.60
_SCALE_PROFIT_FACTOR = 1.5
_MIN_TRADES_FOR_SCALE = 30


def _discover_latest_db() -> Path | None:
    candidates = sorted(
        TMP_DIR.glob("controlled_kpi_after_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _safe_float(v, default=None):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _load_closes(cur) -> list[dict]:
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


def _load_opens(cur) -> list[dict]:
    cur.execute(
        "SELECT id, timestamp, details FROM logs "
        "WHERE event='position_open' ORDER BY id"
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


def _load_hard_stop() -> dict | None:
    if HARD_STOP_FILE := (TMP_DIR / "live_hard_stop.json"):
        if HARD_STOP_FILE.exists():
            try:
                return json.loads(HARD_STOP_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# Section A – Live rollout summary
# ---------------------------------------------------------------------------

def _section_a(closes: list[dict], opens: list[dict]) -> dict:
    n_closes = len(closes)
    n_opens = len(opens)
    pnl_values = [
        _safe_float(c.get("realized_pnl"))
        for c in closes
        if _safe_float(c.get("realized_pnl")) is not None
    ]
    cum_pnl = sum(pnl_values)
    win_count = sum(1 for p in pnl_values if p > 0)
    loss_count = sum(1 for p in pnl_values if p < 0)
    win_rate = win_count / n_closes if n_closes else 0.0
    avg_pnl = statistics.mean(pnl_values) if pnl_values else 0.0

    first_ts = closes[0].get("_ts") if closes else None
    last_ts = closes[-1].get("_ts") if closes else None

    fee_values = [
        _safe_float(c.get("fee_cost"))
        for c in closes
        if _safe_float(c.get("fee_cost")) is not None
    ]
    total_fees = sum(fee_values)

    return {
        "total_opens": n_opens,
        "total_closes": n_closes,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_rate, 4),
        "cum_realized_pnl": round(cum_pnl, 8),
        "avg_pnl_per_trade": round(avg_pnl, 8),
        "total_fees": round(total_fees, 8),
        "first_close_ts": first_ts,
        "last_close_ts": last_ts,
    }


# ---------------------------------------------------------------------------
# Section B – Trade cohort metrics
# ---------------------------------------------------------------------------

def _section_b(closes: list[dict]) -> dict:
    pnl_values = [
        _safe_float(c.get("realized_pnl"))
        for c in closes
        if _safe_float(c.get("realized_pnl")) is not None
    ]
    if not pnl_values:
        return {"error": "no_closes"}

    wins = [p for p in pnl_values if p > 0]
    losses = [p for p in pnl_values if p < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (
        gross_profit / gross_loss if gross_loss > 1e-12 else float("inf")
    )

    by_strategy: dict[str, list[float]] = defaultdict(list)
    by_regime: dict[str, list[float]] = defaultdict(list)
    by_side: dict[str, list[float]] = defaultdict(list)

    for c in closes:
        pnl = _safe_float(c.get("realized_pnl"))
        if pnl is None:
            continue
        strategy = str(c.get("strategy") or c.get("main_strategy") or "unknown")
        regime = str(c.get("regime") or "unknown")
        pos = c.get("position") or {}
        side = str(pos.get("side") or c.get("side") or "unknown")
        by_strategy[strategy].append(pnl)
        by_regime[regime].append(pnl)
        by_side[side].append(pnl)

    def _cohort_stats(bucket: dict[str, list[float]]) -> dict:
        return {
            k: {
                "count": len(v),
                "win_rate": round(sum(1 for x in v if x > 0) / len(v), 4),
                "avg_pnl": round(statistics.mean(v), 8),
                "cum_pnl": round(sum(v), 8),
            }
            for k, v in sorted(bucket.items())
        }

    return {
        "total_trades": len(pnl_values),
        "gross_profit": round(gross_profit, 8),
        "gross_loss": round(gross_loss, 8),
        "profit_factor": (
            round(profit_factor, 4)
            if profit_factor != float("inf")
            else "inf"
        ),
        "avg_win": round(statistics.mean(wins), 8) if wins else 0.0,
        "avg_loss": round(statistics.mean(losses), 8) if losses else 0.0,
        "max_win": round(max(wins), 8) if wins else 0.0,
        "max_loss": round(min(losses), 8) if losses else 0.0,
        "by_strategy": _cohort_stats(by_strategy),
        "by_regime": _cohort_stats(by_regime),
        "by_side": _cohort_stats(by_side),
    }


# ---------------------------------------------------------------------------
# Section C – Exit timing validation
# ---------------------------------------------------------------------------

def _section_c(closes: list[dict]) -> dict:
    post_green_closes = [
        c for c in closes if c.get("post_green_trigger_mode") is not None
    ]
    non_post_green = len(closes) - len(post_green_closes)

    delay_values = [
        _safe_float(c.get("post_green_bnr_time_forced_exit_sec"))
        for c in post_green_closes
        if _safe_float(c.get("post_green_bnr_time_forced_exit_sec")) is not None
    ]

    # Green→red: position went green (post_green triggered) but closed negative
    green_to_red = [
        c for c in post_green_closes
        if _safe_float(c.get("realized_pnl"), 0.0) < 0
    ]

    trigger_modes: dict[str, int] = defaultdict(int)
    for c in post_green_closes:
        mode = str(c.get("post_green_trigger_mode") or "unknown")
        trigger_modes[mode] += 1

    timing_stats: dict = {}
    if delay_values:
        timing_stats = {
            "count": len(delay_values),
            "min_sec": round(min(delay_values), 2),
            "max_sec": round(max(delay_values), 2),
            "mean_sec": round(statistics.mean(delay_values), 2),
            "median_sec": round(statistics.median(delay_values), 2),
            "p95_sec": round(
                sorted(delay_values)[int(len(delay_values) * 0.95)], 2
            ) if len(delay_values) >= 20 else None,
            "over_120s_count": sum(1 for d in delay_values if d > 120),
            "over_60s_count": sum(1 for d in delay_values if d > 60),
            "over_30s_count": sum(1 for d in delay_values if d > 30),
        }

    return {
        "total_closes": len(closes),
        "post_green_closes": len(post_green_closes),
        "non_post_green_closes": non_post_green,
        "green_to_red_count": len(green_to_red),
        "green_to_red_share": round(
            len(green_to_red) / len(post_green_closes), 4
        ) if post_green_closes else 0.0,
        "trigger_modes": dict(trigger_modes),
        "exit_timing_stats": timing_stats,
    }


# ---------------------------------------------------------------------------
# Section D – Risk anomalies
# ---------------------------------------------------------------------------

def _section_d(closes: list[dict], hard_stop: dict | None) -> dict:
    anomalies = []

    # Contract field violations
    violations = []
    for c in closes:
        trigger_mode = c.get("post_green_trigger_mode")
        if trigger_mode is None:
            continue
        missing = [f for f in _POST_GREEN_REQUIRED if c.get(f) is None]
        if missing:
            violations.append({
                "trade_id": c.get("trade_id"),
                "symbol": c.get("symbol"),
                "ts": c.get("_ts"),
                "missing_fields": missing,
            })
    if violations:
        anomalies.append({
            "type": "contract_field_violation",
            "count": len(violations),
            "details": violations[:5],  # cap to first 5
        })

    # Abnormal exit delays
    abnormal_delays = []
    for c in closes:
        delay = _safe_float(c.get("post_green_bnr_time_forced_exit_sec"))
        if delay is not None and delay > 120:
            abnormal_delays.append({
                "trade_id": c.get("trade_id"),
                "symbol": c.get("symbol"),
                "delay_sec": round(delay, 2),
                "ts": c.get("_ts"),
            })
    if abnormal_delays:
        anomalies.append({
            "type": "abnormal_exit_delay",
            "count": len(abnormal_delays),
            "details": abnormal_delays,
        })

    # Consecutive loss streaks >= 3
    streak = 0
    max_streak = 0
    for c in closes:
        pnl = _safe_float(c.get("realized_pnl"))
        if pnl is None:
            continue
        if pnl < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    if max_streak >= 3:
        anomalies.append({
            "type": "consecutive_loss_streak",
            "max_streak": max_streak,
        })

    return {
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "hard_stop_triggered": hard_stop is not None,
        "hard_stop_detail": hard_stop,
    }


# ---------------------------------------------------------------------------
# Section E – Recommendation
# ---------------------------------------------------------------------------

def _section_e(
    sec_a: dict,
    sec_b: dict,
    sec_c: dict,
    sec_d: dict,
) -> dict:
    n_trades = sec_a.get("total_closes", 0)
    win_rate = sec_a.get("win_rate", 0.0)
    pf_raw = sec_b.get("profit_factor", 0.0)
    profit_factor = 0.0 if pf_raw == "inf" else float(pf_raw)
    anomaly_count = sec_d.get("anomaly_count", 0)
    hard_stop = sec_d.get("hard_stop_triggered", False)
    green_to_red_share = sec_c.get("green_to_red_share", 0.0)
    delay_over_120 = (
        sec_c.get("exit_timing_stats", {}).get("over_120s_count", 0)
    )

    reasons = []
    verdict = "EXTEND"

    if hard_stop:
        verdict = "ROLLBACK"
        reasons.append("hard stop was triggered during the run")

    if anomaly_count > 0:
        verdict = "ROLLBACK"
        reasons.append(f"{anomaly_count} risk anomalies detected")

    if delay_over_120 > 0:
        verdict = "ROLLBACK"
        reasons.append(
            f"{delay_over_120} exit(s) took >120s (fee guard suppression issue)"
        )

    if verdict != "ROLLBACK":
        if win_rate < _ROLLBACK_WIN_RATE:
            verdict = "ROLLBACK"
            reasons.append(
                f"win rate {win_rate:.1%} below rollback threshold "
                f"{_ROLLBACK_WIN_RATE:.0%}"
            )
        elif n_trades < _MIN_TRADES_FOR_SCALE:
            verdict = "EXTEND"
            reasons.append(
                f"only {n_trades} closed trades; need {_MIN_TRADES_FOR_SCALE} "
                "for SCALE decision"
            )
        elif (
            win_rate >= _SCALE_WIN_RATE
            and profit_factor >= _SCALE_PROFIT_FACTOR
        ):
            verdict = "SCALE"
            reasons.append(
                f"win rate {win_rate:.1%} ≥ {_SCALE_WIN_RATE:.0%} and "
                f"profit factor {profit_factor:.2f} ≥ {_SCALE_PROFIT_FACTOR}"
            )
        else:
            verdict = "EXTEND"
            reasons.append(
                f"win rate {win_rate:.1%} and profit factor "
                f"{profit_factor:.2f} — within range but not yet SCALE-ready"
            )

    if green_to_red_share > 0.30:
        reasons.append(
            f"WARNING: {green_to_red_share:.1%} green→red share is elevated"
        )

    return {
        "verdict": verdict,
        "win_rate": win_rate,
        "profit_factor": pf_raw,
        "n_trades": n_trades,
        "green_to_red_share": green_to_red_share,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def _render_md(
    sec_a: dict,
    sec_b: dict,
    sec_c: dict,
    sec_d: dict,
    sec_e: dict,
    db_path: Path,
    generated_at: str,
) -> str:
    lines = [
        "# ZoL0 Guarded Live Rollout — Cohort Analysis",
        "",
        f"**Generated:** {generated_at}",
        f"**DB:** `{db_path}`",
        "",
        "---",
        "",
        "## A. Live Rollout Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total opens | {sec_a['total_opens']} |",
        f"| Total closes | {sec_a['total_closes']} |",
        f"| Wins | {sec_a['win_count']} |",
        f"| Losses | {sec_a['loss_count']} |",
        f"| Win rate | {sec_a['win_rate']:.2%} |",
        f"| Cumulative realized PnL | {sec_a['cum_realized_pnl']:.8f} |",
        f"| Avg PnL / trade | {sec_a['avg_pnl_per_trade']:.8f} |",
        f"| Total fees | {sec_a['total_fees']:.8f} |",
        f"| First close | {sec_a.get('first_close_ts', 'N/A')} |",
        f"| Last close | {sec_a.get('last_close_ts', 'N/A')} |",
        "",
        "---",
        "",
        "## B. Trade Cohort Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total trades | {sec_b.get('total_trades', 0)} |",
        f"| Gross profit | {sec_b.get('gross_profit', 0):.8f} |",
        f"| Gross loss | {sec_b.get('gross_loss', 0):.8f} |",
        f"| Profit factor | {sec_b.get('profit_factor', 0)} |",
        f"| Avg win | {sec_b.get('avg_win', 0):.8f} |",
        f"| Avg loss | {sec_b.get('avg_loss', 0):.8f} |",
        f"| Max win | {sec_b.get('max_win', 0):.8f} |",
        f"| Max loss | {sec_b.get('max_loss', 0):.8f} |",
        "",
        "**By Strategy:**",
        "",
        "| Strategy | Count | Win Rate | Avg PnL | Cum PnL |",
        "|----------|-------|----------|---------|---------|",
    ]
    for strat, stats in (sec_b.get("by_strategy") or {}).items():
        lines.append(
            f"| {strat} | {stats['count']} | {stats['win_rate']:.2%} "
            f"| {stats['avg_pnl']:.8f} | {stats['cum_pnl']:.8f} |"
        )

    lines += [
        "",
        "**By Side:**",
        "",
        "| Side | Count | Win Rate | Avg PnL | Cum PnL |",
        "|------|-------|----------|---------|---------|",
    ]
    for side, stats in (sec_b.get("by_side") or {}).items():
        lines.append(
            f"| {side} | {stats['count']} | {stats['win_rate']:.2%} "
            f"| {stats['avg_pnl']:.8f} | {stats['cum_pnl']:.8f} |"
        )

    timing = sec_c.get("exit_timing_stats") or {}
    lines += [
        "",
        "---",
        "",
        "## C. Exit Timing Validation",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total closes | {sec_c['total_closes']} |",
        f"| Post-green closes | {sec_c['post_green_closes']} |",
        f"| Non-post-green closes | {sec_c['non_post_green_closes']} |",
        f"| Green→red count | {sec_c['green_to_red_count']} |",
        f"| Green→red share | {sec_c['green_to_red_share']:.2%} |",
    ]
    if timing:
        lines += [
            f"| Exit delay min | {timing.get('min_sec', 'N/A')}s |",
            f"| Exit delay max | {timing.get('max_sec', 'N/A')}s |",
            f"| Exit delay mean | {timing.get('mean_sec', 'N/A')}s |",
            f"| Exit delay median | {timing.get('median_sec', 'N/A')}s |",
            f"| Exits >120s (abnormal) | {timing.get('over_120s_count', 0)} |",
            f"| Exits >60s | {timing.get('over_60s_count', 0)} |",
            f"| Exits >30s | {timing.get('over_30s_count', 0)} |",
        ]
    lines += [
        "",
        "**Trigger mode distribution:**",
        "",
        "| Mode | Count |",
        "|------|-------|",
    ]
    for mode, count in (sec_c.get("trigger_modes") or {}).items():
        lines.append(f"| {mode} | {count} |")

    lines += [
        "",
        "---",
        "",
        "## D. Risk Anomalies",
        "",
        f"**Anomaly count:** {sec_d['anomaly_count']}",
        f"**Hard stop triggered:** {sec_d['hard_stop_triggered']}",
        "",
    ]
    if sec_d["anomaly_count"] == 0:
        lines.append("No risk anomalies detected.")
    else:
        for anom in sec_d.get("anomalies", []):
            lines.append(f"- **{anom['type']}**: {anom}")

    verdict = sec_e["verdict"]
    verdict_badge = {
        "SCALE": "🟢 SCALE",
        "EXTEND": "🟡 EXTEND",
        "ROLLBACK": "🔴 ROLLBACK",
    }.get(verdict, verdict)

    lines += [
        "",
        "---",
        "",
        f"## E. Recommendation: {verdict_badge}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Verdict | **{verdict}** |",
        f"| Win rate | {sec_e['win_rate']:.2%} |",
        f"| Profit factor | {sec_e['profit_factor']} |",
        f"| Closed trades | {sec_e['n_trades']} |",
        f"| Green→red share | {sec_e['green_to_red_share']:.2%} |",
        "",
        "**Rationale:**",
        "",
    ]
    for reason in sec_e.get("reasons", []):
        lines.append(f"- {reason}")

    lines += [
        "",
        "---",
        "",
        "_Report generated by `scripts/live_cohort_analysis.py`_",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="ZoL0 live rollout cohort analysis",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--db-path",
        type=Path,
        default=None,
        help="Path to live run DB (auto-discovers latest in tmp/ if omitted)",
    )
    ap.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help=(
            "Output JSON path "
            "(default: reports/live_rollout/cohort_YYYYMMDD_HHMMSS.json)"
        ),
    )
    ap.add_argument(
        "--out-md",
        type=Path,
        default=None,
        help=(
            "Output Markdown path "
            "(default: reports/live_rollout/cohort_YYYYMMDD_HHMMSS.md)"
        ),
    )
    args = ap.parse_args()

    import sqlite3

    db_path = args.db_path
    if db_path is None:
        db_path = _discover_latest_db()
        if db_path is None:
            print("ERROR: No DB found. Pass --db-path.")
            sys.exit(1)
        print(f"Auto-discovered DB: {db_path}")

    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}")
        sys.exit(1)

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    cur = con.cursor()
    closes = _load_closes(cur)
    opens = _load_opens(cur)
    con.close()

    if not closes:
        print("WARNING: No position_close events found in DB.")

    hard_stop = _load_hard_stop()

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    sec_a = _section_a(closes, opens)
    sec_b = _section_b(closes)
    sec_c = _section_c(closes)
    sec_d = _section_d(closes, hard_stop)
    sec_e = _section_e(sec_a, sec_b, sec_c, sec_d)

    full_report = {
        "generated_at": generated_at,
        "db_path": str(db_path),
        "a_summary": sec_a,
        "b_cohort": sec_b,
        "c_exit_timing": sec_c,
        "d_risk_anomalies": sec_d,
        "e_recommendation": sec_e,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_json = args.out_json or (REPORTS_DIR / f"cohort_{ts_tag}.json")
    out_md = args.out_md or (REPORTS_DIR / f"cohort_{ts_tag}.md")

    out_json.write_text(
        json.dumps(full_report, indent=2, default=str), encoding="utf-8"
    )
    print(f"JSON report: {out_json}")

    md_text = _render_md(sec_a, sec_b, sec_c, sec_d, sec_e, db_path, generated_at)
    out_md.write_text(md_text, encoding="utf-8")
    print(f"Markdown report: {out_md}")

    print()
    print(f"=== VERDICT: {sec_e['verdict']} ===")
    print(
        f"  win_rate={sec_e['win_rate']:.2%}  "
        f"profit_factor={sec_e['profit_factor']}  "
        f"n_trades={sec_e['n_trades']}"
    )
    for reason in sec_e.get("reasons", []):
        print(f"  - {reason}")


if __name__ == "__main__":
    main()
