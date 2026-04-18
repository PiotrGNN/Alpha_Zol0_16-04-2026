import argparse
import csv
import json
import math
import random
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


WORKDIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = WORKDIR / "results"
TMP_DIR = WORKDIR / "tmp"
RESULTS_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)


def _parse_env_overrides(items):
    out = {}
    for raw in items or []:
        txt = str(raw or "").strip()
        if not txt:
            continue
        if "=" not in txt:
            raise SystemExit(f"Invalid override '{txt}', expected KEY=VALUE")
        key, value = txt.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SystemExit(f"Invalid override key: {txt}")
        out[key] = value
    return out


def _parse_num_list(raw, cast=float):
    out = []
    for part in str(raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        out.append(cast(token))
    return out


def _fmt_value(val):
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        txt = f"{val:.8f}".rstrip("0").rstrip(".")
        return txt if txt else "0"
    return str(val)


def _candidate_key(overrides):
    keys = sorted(overrides.keys())
    return tuple((k, str(overrides.get(k))) for k in keys)


def _build_candidates(args):
    rng = random.Random(args.seed)
    candidates = []
    seen = set()

    baseline = {}
    candidates.append(
        {
            "id": "baseline",
            "overrides": baseline,
            "origin": "baseline_after_defaults",
        }
    )
    seen.add(_candidate_key(baseline))

    grid = {
        "ENTRY_SIGNAL_SCORE_MIN": _parse_num_list(args.grid_entry_signal_score_min, float),
        "ENTRY_SIGNAL_SCORE_MIN_BUY": _parse_num_list(
            args.grid_entry_signal_score_min_buy, float
        ),
        "ENTRY_BUY_MIN_SIGNAL_SCORE": _parse_num_list(
            args.grid_entry_buy_min_signal_score, float
        ),
        "ENTRY_SIGNAL_MIN_VOTES": _parse_num_list(args.grid_entry_signal_min_votes, int),
        "ENTRY_VOLATILITY_MIN": _parse_num_list(args.grid_entry_volatility_min, float),
        "ENTRY_BUY_MIN_VOLATILITY": _parse_num_list(
            args.grid_entry_buy_min_volatility, float
        ),
        "ENTRY_REQUIRE_TREND_AND_VOL": _parse_num_list(
            args.grid_entry_require_trend_and_vol, int
        ),
        "ENTRY_ALPHA_SELECTOR_MIN_EXPECTANCY": _parse_num_list(
            args.grid_alpha_min_expectancy, float
        ),
        "ENTRY_ALPHA_SELECTOR_MIN_WINRATE": _parse_num_list(
            args.grid_alpha_min_winrate, float
        ),
        "ENTRY_ALPHA_SELECTOR_BAD_WEIGHT_SCALE": _parse_num_list(
            args.grid_alpha_bad_weight_scale, float
        ),
        "ENTRY_ALPHA_SELECTOR_GOOD_WEIGHT_SCALE": _parse_num_list(
            args.grid_alpha_good_weight_scale, float
        ),
        "ENTRY_ALPHA_SELECTOR_KEEP_MIN_SIGNALS": _parse_num_list(
            args.grid_alpha_keep_min_signals, int
        ),
        "ENTRY_MIN_ACTIVE_STRATEGIES": _parse_num_list(
            args.grid_entry_min_active_strategies, int
        ),
        "ENTRY_BUY_REQUIRE_TREND": _parse_num_list(args.grid_entry_buy_require_trend, int),
        "ENTRY_SELL_REQUIRE_TREND": _parse_num_list(
            args.grid_entry_sell_require_trend, int
        ),
        "SYMBOL_STRATEGY_GUARD_MIN_WINRATE": _parse_num_list(
            args.grid_symbol_strategy_guard_min_winrate, float
        ),
        "SYMBOL_STRATEGY_GUARD_MAX_EXPECTANCY": _parse_num_list(
            args.grid_symbol_strategy_guard_max_expectancy, float
        ),
        "SIDE_GUARD_MIN_WINRATE": _parse_num_list(
            args.grid_side_guard_min_winrate, float
        ),
        "SIDE_GUARD_MAX_EXPECTANCY": _parse_num_list(
            args.grid_side_guard_max_expectancy, float
        ),
        "ALPHA_MICRO_EXPLORATION_ALLOC_SCALE": _parse_num_list(
            args.grid_alpha_micro_alloc_scale, float
        ),
        "ALPHA_MICRO_EXPLORATION_ENABLE": _parse_num_list(
            args.grid_alpha_micro_enable, int
        ),
        "ALPHA_REQUIRE_POSITIVE_UNIVERSE": _parse_num_list(
            args.grid_alpha_require_positive_universe, int
        ),
        "ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_TRADES": _parse_num_list(
            args.grid_alpha_require_positive_universe_min_trades, int
        ),
        "ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_WINRATE": _parse_num_list(
            args.grid_alpha_require_positive_universe_min_winrate, float
        ),
        "ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_EXPECTANCY": _parse_num_list(
            args.grid_alpha_require_positive_universe_min_expectancy, float
        ),
        "STRATEGY_BIAS_VOTES": _parse_num_list(args.grid_strategy_bias_votes, int),
        "MOMENTUM_BIAS_ENABLE": _parse_num_list(
            args.grid_momentum_bias_enable, int
        ),
        "ALPHA_MICRO_EXPLORATION_WEIGHT_SCALE": _parse_num_list(
            args.grid_alpha_micro_weight_scale, float
        ),
        "ALPHA_MICRO_EXPLORATION_NET_TARGET_SCALE": _parse_num_list(
            args.grid_alpha_micro_net_target_scale, float
        ),
        "ALPHA_MICRO_EXPLORATION_MIN_EXPECTANCY": _parse_num_list(
            args.grid_alpha_micro_min_expectancy, float
        ),
        "ALPHA_MICRO_EXPLORATION_MAX_ALLOC_USDT": _parse_num_list(
            args.grid_alpha_micro_max_alloc_usdt, float
        ),
        "ALPHA_MICRO_EXPLORATION_IDLE_RELAX_SEC": _parse_num_list(
            args.grid_alpha_micro_idle_relax_sec, int
        ),
        "ALPHA_MICRO_EXPLORATION_IDLE_MIN_EXPECTANCY": _parse_num_list(
            args.grid_alpha_micro_idle_min_expectancy, float
        ),
        "ALPHA_MICRO_EXPLORATION_ENTRY_SCORE_MULT": _parse_num_list(
            args.grid_alpha_micro_entry_score_mult, float
        ),
        "ALPHA_MICRO_EXPLORATION_ENTRY_VOL_MULT": _parse_num_list(
            args.grid_alpha_micro_entry_vol_mult, float
        ),
        "ALPHA_MICRO_EXPLORATION_ENTRY_VOTE_MIN": _parse_num_list(
            args.grid_alpha_micro_entry_vote_min, int
        ),
        "ALPHA_MICRO_EXPLORATION_DISABLE_TREND": _parse_num_list(
            args.grid_alpha_micro_disable_trend, int
        ),
        "ALPHA_MICRO_EXPLORATION_DISABLE_RANGE_BLOCK": _parse_num_list(
            args.grid_alpha_micro_disable_range_block, int
        ),
        "ALPHA_MICRO_EXPLORATION_EXIT_STOP_LOSS_USDT": _parse_num_list(
            args.grid_alpha_micro_exit_stop_loss_usdt, float
        ),
        "ALPHA_MICRO_EXPLORATION_EXIT_TAKE_PROFIT_USDT": _parse_num_list(
            args.grid_alpha_micro_exit_take_profit_usdt, float
        ),
        "allocation_pct": _parse_num_list(args.grid_allocation_pct, float),
        "EXIT_STOP_LOSS_USDT": _parse_num_list(args.grid_exit_stop_loss_usdt, float),
        "EXIT_TAKE_PROFIT_USDT": _parse_num_list(
            args.grid_exit_take_profit_usdt, float
        ),
    }
    for key, vals in grid.items():
        if not vals:
            raise SystemExit(f"Grid for {key} is empty")

    # Two deterministic anchor candidates before random sampling.
    anchors = [
        {
            "ENTRY_ALPHA_SELECTOR_MIN_EXPECTANCY": -0.20,
            "ENTRY_ALPHA_SELECTOR_MIN_WINRATE": 0.30,
            "ENTRY_ALPHA_SELECTOR_BAD_WEIGHT_SCALE": 0.22,
            "ENTRY_ALPHA_SELECTOR_GOOD_WEIGHT_SCALE": 1.08,
            "ENTRY_ALPHA_SELECTOR_KEEP_MIN_SIGNALS": 1,
            "SYMBOL_STRATEGY_GUARD_MIN_WINRATE": 0.25,
            "SYMBOL_STRATEGY_GUARD_MAX_EXPECTANCY": -0.60,
            "SIDE_GUARD_MIN_WINRATE": 0.25,
            "SIDE_GUARD_MAX_EXPECTANCY": -0.60,
            "ALPHA_MICRO_EXPLORATION_ENABLE": 1,
            "ALPHA_MICRO_EXPLORATION_ALLOC_SCALE": 0.10,
            "ALPHA_MICRO_EXPLORATION_WEIGHT_SCALE": 0.20,
            "ALPHA_MICRO_EXPLORATION_NET_TARGET_SCALE": 0.30,
            "ALPHA_MICRO_EXPLORATION_MIN_EXPECTANCY": -0.05,
            "ALPHA_MICRO_EXPLORATION_MAX_ALLOC_USDT": 20,
            "ALPHA_MICRO_EXPLORATION_IDLE_RELAX_SEC": 420,
            "ALPHA_MICRO_EXPLORATION_IDLE_MIN_EXPECTANCY": -0.20,
            "ALPHA_MICRO_EXPLORATION_ENTRY_SCORE_MULT": 0.80,
            "ALPHA_MICRO_EXPLORATION_ENTRY_VOL_MULT": 0.85,
            "ALPHA_MICRO_EXPLORATION_ENTRY_VOTE_MIN": 1,
            "ALPHA_MICRO_EXPLORATION_DISABLE_TREND": 1,
            "ALPHA_MICRO_EXPLORATION_DISABLE_RANGE_BLOCK": 1,
            "ALPHA_MICRO_EXPLORATION_EXIT_STOP_LOSS_USDT": 0.16,
            "ALPHA_MICRO_EXPLORATION_EXIT_TAKE_PROFIT_USDT": 0.50,
            "allocation_pct": 0.008,
            "EXIT_STOP_LOSS_USDT": 0.30,
            "EXIT_TAKE_PROFIT_USDT": 0.95,
        },
        {
            "ENTRY_SIGNAL_SCORE_MIN": 0.18,
            "ENTRY_SIGNAL_SCORE_MIN_BUY": 0.22,
            "ENTRY_BUY_MIN_SIGNAL_SCORE": 0.22,
            "ENTRY_SIGNAL_MIN_VOTES": 2,
            "ENTRY_VOLATILITY_MIN": 0.020,
            "ENTRY_BUY_MIN_VOLATILITY": 0.020,
            "ENTRY_REQUIRE_TREND_AND_VOL": 1,
            "ENTRY_ALPHA_SELECTOR_MIN_EXPECTANCY": -0.85,
            "ENTRY_ALPHA_SELECTOR_MIN_WINRATE": 0.30,
            "ENTRY_ALPHA_SELECTOR_BAD_WEIGHT_SCALE": 0.22,
            "ENTRY_ALPHA_SELECTOR_GOOD_WEIGHT_SCALE": 1.12,
            "ENTRY_ALPHA_SELECTOR_KEEP_MIN_SIGNALS": 1,
            "ENTRY_MIN_ACTIVE_STRATEGIES": 2,
            "ENTRY_BUY_REQUIRE_TREND": 1,
            "ENTRY_SELL_REQUIRE_TREND": 1,
            "SYMBOL_STRATEGY_GUARD_MIN_WINRATE": 0.30,
            "SYMBOL_STRATEGY_GUARD_MAX_EXPECTANCY": -0.60,
            "SIDE_GUARD_MIN_WINRATE": 0.30,
            "SIDE_GUARD_MAX_EXPECTANCY": -0.60,
            "ALPHA_MICRO_EXPLORATION_ENABLE": 1,
            "ALPHA_REQUIRE_POSITIVE_UNIVERSE": 0,
            "ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_TRADES": 2,
            "ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_WINRATE": 0.35,
            "ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_EXPECTANCY": 0.00,
            "STRATEGY_BIAS_VOTES": 0,
            "MOMENTUM_BIAS_ENABLE": 0,
            "ALPHA_MICRO_EXPLORATION_ALLOC_SCALE": 0.20,
            "ALPHA_MICRO_EXPLORATION_WEIGHT_SCALE": 0.25,
            "ALPHA_MICRO_EXPLORATION_NET_TARGET_SCALE": 0.20,
            "ALPHA_MICRO_EXPLORATION_MIN_EXPECTANCY": 0.00,
            "ALPHA_MICRO_EXPLORATION_MAX_ALLOC_USDT": 45,
            "ALPHA_MICRO_EXPLORATION_IDLE_RELAX_SEC": 420,
            "ALPHA_MICRO_EXPLORATION_IDLE_MIN_EXPECTANCY": -0.30,
            "ALPHA_MICRO_EXPLORATION_ENTRY_SCORE_MULT": 0.65,
            "ALPHA_MICRO_EXPLORATION_ENTRY_VOL_MULT": 0.70,
            "ALPHA_MICRO_EXPLORATION_ENTRY_VOTE_MIN": 1,
            "ALPHA_MICRO_EXPLORATION_DISABLE_TREND": 1,
            "ALPHA_MICRO_EXPLORATION_DISABLE_RANGE_BLOCK": 1,
            "ALPHA_MICRO_EXPLORATION_EXIT_STOP_LOSS_USDT": 0.22,
            "ALPHA_MICRO_EXPLORATION_EXIT_TAKE_PROFIT_USDT": 0.70,
            "allocation_pct": 0.010,
            "EXIT_STOP_LOSS_USDT": 0.45,
            "EXIT_TAKE_PROFIT_USDT": 0.70,
        },
        {
            "ENTRY_SIGNAL_SCORE_MIN": 0.12,
            "ENTRY_SIGNAL_SCORE_MIN_BUY": 0.16,
            "ENTRY_BUY_MIN_SIGNAL_SCORE": 0.16,
            "ENTRY_SIGNAL_MIN_VOTES": 1,
            "ENTRY_VOLATILITY_MIN": 0.015,
            "ENTRY_BUY_MIN_VOLATILITY": 0.015,
            "ENTRY_REQUIRE_TREND_AND_VOL": 0,
            "ENTRY_ALPHA_SELECTOR_MIN_EXPECTANCY": 0.00,
            "ENTRY_ALPHA_SELECTOR_MIN_WINRATE": 0.40,
            "ENTRY_ALPHA_SELECTOR_BAD_WEIGHT_SCALE": 0.20,
            "ENTRY_ALPHA_SELECTOR_GOOD_WEIGHT_SCALE": 1.08,
            "ENTRY_ALPHA_SELECTOR_KEEP_MIN_SIGNALS": 0,
            "ENTRY_MIN_ACTIVE_STRATEGIES": 1,
            "ENTRY_BUY_REQUIRE_TREND": 0,
            "ENTRY_SELL_REQUIRE_TREND": 0,
            "SYMBOL_STRATEGY_GUARD_MIN_WINRATE": 0.35,
            "SYMBOL_STRATEGY_GUARD_MAX_EXPECTANCY": -0.20,
            "SIDE_GUARD_MIN_WINRATE": 0.35,
            "SIDE_GUARD_MAX_EXPECTANCY": -0.20,
            "ALPHA_MICRO_EXPLORATION_ENABLE": 0,
            "ALPHA_REQUIRE_POSITIVE_UNIVERSE": 1,
            "ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_TRADES": 2,
            "ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_WINRATE": 0.35,
            "ALPHA_REQUIRE_POSITIVE_UNIVERSE_MIN_EXPECTANCY": 0.00,
            "STRATEGY_BIAS_VOTES": 0,
            "MOMENTUM_BIAS_ENABLE": 0,
            "ALPHA_MICRO_EXPLORATION_ALLOC_SCALE": 0.12,
            "ALPHA_MICRO_EXPLORATION_WEIGHT_SCALE": 0.20,
            "ALPHA_MICRO_EXPLORATION_NET_TARGET_SCALE": 0.35,
            "ALPHA_MICRO_EXPLORATION_MIN_EXPECTANCY": 0.00,
            "ALPHA_MICRO_EXPLORATION_MAX_ALLOC_USDT": 60,
            "ALPHA_MICRO_EXPLORATION_IDLE_RELAX_SEC": 300,
            "ALPHA_MICRO_EXPLORATION_IDLE_MIN_EXPECTANCY": -0.20,
            "ALPHA_MICRO_EXPLORATION_ENTRY_SCORE_MULT": 0.70,
            "ALPHA_MICRO_EXPLORATION_ENTRY_VOL_MULT": 0.75,
            "ALPHA_MICRO_EXPLORATION_ENTRY_VOTE_MIN": 1,
            "ALPHA_MICRO_EXPLORATION_DISABLE_TREND": 1,
            "ALPHA_MICRO_EXPLORATION_DISABLE_RANGE_BLOCK": 1,
            "ALPHA_MICRO_EXPLORATION_EXIT_STOP_LOSS_USDT": 0.18,
            "ALPHA_MICRO_EXPLORATION_EXIT_TAKE_PROFIT_USDT": 0.55,
            "allocation_pct": 0.008,
            "EXIT_STOP_LOSS_USDT": 0.30,
            "EXIT_TAKE_PROFIT_USDT": 1.10,
        },
    ]
    for idx, anchor in enumerate(anchors, start=1):
        if len(candidates) >= args.max_candidates:
            break
        normalized = {k: _fmt_value(v) for k, v in anchor.items()}
        ckey = _candidate_key(normalized)
        if ckey in seen:
            continue
        seen.add(ckey)
        candidates.append(
            {
                "id": f"anchor_{idx:02d}",
                "overrides": normalized,
                "origin": "anchor",
            }
        )

    keys = list(grid.keys())
    max_attempts = max(200, args.max_candidates * 80)
    attempts = 0
    while len(candidates) < args.max_candidates and attempts < max_attempts:
        attempts += 1
        cand = {}
        for key in keys:
            cand[key] = _fmt_value(rng.choice(grid[key]))
        ckey = _candidate_key(cand)
        if ckey in seen:
            continue
        seen.add(ckey)
        candidates.append(
            {
                "id": f"rand_{len(candidates):03d}",
                "overrides": cand,
                "origin": "random",
            }
        )
    return candidates


def _extract_report_json_path(stdout_text):
    match = re.search(r"(?m)^REPORT_JSON=(.+)$", stdout_text or "")
    if not match:
        return None
    txt = match.group(1).strip()
    if not txt:
        return None
    return Path(txt)


def _run_after_window(args, overrides, window_idx, candidate_id):
    cmd = [
        sys.executable,
        "scripts/controlled_kpi_run.py",
    ]
    if args.compare_before:
        cmd.extend(
            [
                "--before-min",
                str(int(args.window_min)),
                "--after-min",
                str(int(args.window_min)),
            ]
        )
    else:
        cmd.extend(
            [
                "--variant-only",
                "after",
                "--after-min",
                str(int(args.window_min)),
            ]
        )
    cmd.extend(
        [
        "--symbols",
        str(args.symbols),
        "--market-type",
        str(args.market_type),
        "--timeframe",
        str(args.timeframe),
        "--paper-auto-close-sec",
        str(int(args.paper_auto_close_sec)),
        "--equity-snapshot-sec",
        str(int(args.equity_snapshot_sec)),
        "--alpha-bootstrap-source-db-url",
        str(args.alpha_bootstrap_source_db_url),
        "--alpha-bootstrap-source-db-glob",
        str(args.alpha_bootstrap_source_db_glob),
        ]
    )
    if args.quality_profile:
        cmd.append("--quality-profile")
    if args.use_mock:
        cmd.append("--use-mock")
    if args.paper_auto_open:
        cmd.append("--paper-auto-open")

    merged = {}
    if args.compare_before:
        merged_before = _parse_env_overrides(args.base_before_env)
        for key in sorted(merged_before.keys()):
            cmd.extend(["--before-env", f"{key}={merged_before[key]}"])
    merged.update(_parse_env_overrides(args.base_after_env))
    merged.update(overrides or {})
    for key in sorted(merged.keys()):
        cmd.extend(["--after-env", f"{key}={merged[key]}"])

    started = datetime.now(timezone.utc).isoformat()
    print(
        f"[tuner] candidate={candidate_id} window={window_idx + 1}/{args.windows} "
        f"start={started}"
    )
    proc = subprocess.run(
        cmd,
        cwd=str(WORKDIR),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": f"controlled_kpi_run failed rc={proc.returncode}",
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
        }
    report_path = _extract_report_json_path(proc.stdout)
    if report_path is None:
        return {
            "ok": False,
            "error": "REPORT_JSON not found in output",
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
        }
    if not report_path.is_absolute():
        report_path = (WORKDIR / report_path).resolve()
    if not report_path.exists():
        return {
            "ok": False,
            "error": f"report json missing: {report_path}",
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
        }
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "error": f"cannot load report json: {exc}",
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
        }
    metrics = report.get("after")
    if not isinstance(metrics, dict):
        return {
            "ok": False,
            "error": "after metrics missing in report",
            "report_path": str(report_path),
        }
    before_metrics = report.get("before")
    if args.compare_before and not isinstance(before_metrics, dict):
        return {
            "ok": False,
            "error": "before metrics missing in compare_before mode",
            "report_path": str(report_path),
        }
    delta_obj = report.get("delta")
    if args.compare_before:
        if not isinstance(delta_obj, dict):
            try:
                delta_obj = {
                    "net_pnl_delta": float(metrics.get("net_pnl") or 0.0)
                    - float(before_metrics.get("net_pnl") or 0.0),
                    "winrate_delta_pct_points": (
                        float(metrics.get("winrate") or 0.0)
                        - float(before_metrics.get("winrate") or 0.0)
                    )
                    * 100.0,
                    "max_drawdown_delta_pct_points": (
                        float(metrics.get("max_drawdown") or 0.0)
                        - float(before_metrics.get("max_drawdown") or 0.0)
                    )
                    * 100.0,
                }
            except Exception:
                delta_obj = {}
    return {
        "ok": True,
        "report_path": str(report_path),
        "metrics": metrics,
        "before_metrics": before_metrics if isinstance(before_metrics, dict) else None,
        "delta": delta_obj if isinstance(delta_obj, dict) else None,
    }


def _candidate_summary(window_results, args):
    valid = [r for r in window_results if r.get("ok") and isinstance(r.get("metrics"), dict)]
    metrics = [r["metrics"] for r in valid]
    windows = len(window_results)
    failures = windows - len(valid)
    if not metrics:
        return {
            "windows": windows,
            "windows_ok": 0,
            "windows_failed": failures,
            "total_trades": 0,
            "total_net_pnl": 0.0,
            "mean_net_pnl": -999.0,
            "median_net_pnl": -999.0,
            "worst_window_net_pnl": -999.0,
            "mean_winrate": 0.0,
            "median_profit_factor": 0.0,
            "zero_trade_windows": windows,
            "loss_windows": windows,
            "non_negative_windows": 0,
            "positive_after_windows": 0,
            "profit_factor_windows": 0,
            "delta_windows": 0,
            "missing_delta_windows": 0,
            "positive_delta_windows": 0,
            "non_negative_delta_windows": 0,
            "mean_delta_net_pnl": -999.0,
            "median_delta_net_pnl": -999.0,
            "worst_delta_net_pnl": -999.0,
            "pass": False,
            "score": -9999.0,
            "criteria": {"metrics_present": False},
        }

    net_arr = [float(m.get("net_pnl") or 0.0) for m in metrics]
    trades_arr = [int(m.get("trade_count") or 0) for m in metrics]
    winrate_arr = [float(m.get("winrate") or 0.0) for m in metrics]
    pf_arr = []
    pf_windows = 0
    pf_window_threshold = float(args.profit_factor_window_threshold)
    for m in metrics:
        pf = m.get("profit_factor")
        try:
            pf = float(pf)
        except Exception:
            pf = 0.0
        pf_val = 0.0
        if math.isfinite(pf):
            pf_val = float(pf)
        elif pf == float("inf"):
            pf_val = float(args.inf_profit_factor_cap)
        pf_arr.append(pf_val)
        if pf_val >= pf_window_threshold:
            pf_windows += 1

    total_trades = sum(trades_arr)
    total_net = float(sum(net_arr))
    mean_net = float(sum(net_arr) / len(net_arr))
    median_net = float(statistics.median(net_arr))
    worst_net = float(min(net_arr))
    mean_winrate = float(sum(winrate_arr) / len(winrate_arr))
    median_pf = float(statistics.median(pf_arr)) if pf_arr else 0.0
    zero_trade_windows = sum(1 for x in trades_arr if x <= 0)
    loss_windows = sum(1 for x in net_arr if x < 0)
    non_negative_windows = sum(1 for x in net_arr if x >= 0)
    positive_after_windows = sum(1 for x in net_arr if x > 0)
    delta_arr = []
    missing_delta_windows = 0
    if args.compare_before:
        for row in valid:
            delta_obj = row.get("delta")
            if not isinstance(delta_obj, dict):
                missing_delta_windows += 1
                continue
            try:
                delta_val = float(delta_obj.get("net_pnl_delta") or 0.0)
            except Exception:
                delta_val = 0.0
            if not math.isfinite(delta_val):
                delta_val = 0.0
            delta_arr.append(delta_val)

    if delta_arr:
        mean_delta = float(sum(delta_arr) / len(delta_arr))
        median_delta = float(statistics.median(delta_arr))
        worst_delta = float(min(delta_arr))
        positive_delta_windows = sum(1 for x in delta_arr if x > 0)
        non_negative_delta_windows = sum(1 for x in delta_arr if x >= 0)
    else:
        mean_delta = 0.0
        median_delta = 0.0
        worst_delta = 0.0
        positive_delta_windows = 0
        non_negative_delta_windows = 0

    criteria = {
        "windows_ok": len(metrics) >= max(1, int(args.min_windows_ok)),
        "total_trades": total_trades >= int(args.min_total_trades),
        "zero_trade_windows": zero_trade_windows <= int(args.max_zero_trade_windows),
        "loss_windows": loss_windows <= int(args.max_loss_windows),
        "non_negative_windows": non_negative_windows >= int(args.min_non_negative_windows),
        "positive_after_windows": positive_after_windows
        >= int(args.min_positive_after_windows),
        "mean_net_pnl": mean_net >= float(args.min_mean_net_pnl),
        "median_profit_factor": median_pf >= float(args.min_median_profit_factor),
        "profit_factor_windows": pf_windows >= int(args.min_profit_factor_windows),
        "worst_window_net_pnl": worst_net >= float(args.min_worst_window_net_pnl),
    }
    if args.compare_before:
        criteria.update(
            {
                "delta_present": len(delta_arr) >= len(metrics),
                "positive_delta_windows": positive_delta_windows
                >= int(args.min_positive_delta_windows),
                "mean_delta_net_pnl": mean_delta >= float(args.min_mean_delta_net_pnl),
                "median_delta_net_pnl": median_delta
                >= float(args.min_median_delta_net_pnl),
                "worst_delta_net_pnl": worst_delta
                >= float(args.min_worst_delta_net_pnl),
            }
        )
    passed = all(criteria.values())

    score = (
        mean_net * float(args.score_w_mean_net)
        + median_net * float(args.score_w_median_net)
        + median_pf * float(args.score_w_median_pf)
        + (min(float(total_trades), float(windows) * 4.0) * float(args.score_w_total_trades))
        + (non_negative_windows * float(args.score_w_non_negative_windows))
        - (zero_trade_windows * float(args.score_w_zero_trade_windows))
        - (loss_windows * float(args.score_w_loss_windows))
        - (max(0.0, -worst_net) * float(args.score_w_worst_net_penalty))
        - (
            max(0.0, float(args.min_total_trades) - float(total_trades))
            * float(args.score_w_trade_deficit_penalty)
        )
    )
    if args.compare_before:
        score += (
            mean_delta * float(args.score_w_mean_delta_net)
            + median_delta * float(args.score_w_median_delta_net)
            + (positive_delta_windows * float(args.score_w_positive_delta_windows))
            - (
                max(0.0, -worst_delta)
                * float(args.score_w_worst_delta_net_penalty)
            )
        )

    return {
        "windows": windows,
        "windows_ok": len(metrics),
        "windows_failed": failures,
        "total_trades": int(total_trades),
        "total_net_pnl": total_net,
        "mean_net_pnl": mean_net,
        "median_net_pnl": median_net,
        "worst_window_net_pnl": worst_net,
        "mean_winrate": mean_winrate,
        "median_profit_factor": median_pf,
        "zero_trade_windows": int(zero_trade_windows),
        "loss_windows": int(loss_windows),
        "non_negative_windows": int(non_negative_windows),
        "positive_after_windows": int(positive_after_windows),
        "profit_factor_windows": int(pf_windows),
        "delta_windows": int(len(delta_arr)),
        "missing_delta_windows": int(missing_delta_windows),
        "positive_delta_windows": int(positive_delta_windows),
        "non_negative_delta_windows": int(non_negative_delta_windows),
        "mean_delta_net_pnl": float(mean_delta),
        "median_delta_net_pnl": float(median_delta),
        "worst_delta_net_pnl": float(worst_delta),
        "pass": bool(passed),
        "score": float(score),
        "criteria": criteria,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows", type=int, default=6)
    parser.add_argument("--window-min", type=int, default=16)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--symbols", type=str, default="ETHUSDTM,BTCUSDTM,SOLUSDTM,XRPUSDTM")
    parser.add_argument("--market-type", type=str, default="futures")
    parser.add_argument("--timeframe", type=str, default="1")
    parser.add_argument("--quality-profile", dest="quality_profile", action="store_true")
    parser.add_argument("--no-quality-profile", dest="quality_profile", action="store_false")
    parser.set_defaults(quality_profile=True)
    parser.add_argument("--use-mock", action="store_true")
    parser.add_argument("--paper-auto-open", action="store_true")
    parser.add_argument("--paper-auto-close-sec", type=int, default=60)
    parser.add_argument("--equity-snapshot-sec", type=int, default=10)
    parser.add_argument(
        "--alpha-bootstrap-source-db-url",
        type=str,
        default="sqlite:///tmp/alpha_history_auto_recent.db",
    )
    parser.add_argument(
        "--alpha-bootstrap-source-db-glob",
        type=str,
        default="tmp/alpha_history_auto_recent.db",
    )
    parser.add_argument(
        "--compare-before",
        action="store_true",
        help="Run BEFORE+AFTER per window and score by AFTER-vs-BEFORE deltas.",
    )
    parser.add_argument(
        "--base-before-env",
        action="append",
        default=[],
        help="Additional fixed BEFORE env override (KEY=VALUE), repeatable",
    )
    parser.add_argument(
        "--base-after-env",
        action="append",
        default=[],
        help="Additional fixed AFTER env override (KEY=VALUE), repeatable",
    )

    parser.add_argument("--min-windows-ok", type=int, default=6)
    parser.add_argument("--min-total-trades", type=int, default=6)
    parser.add_argument("--max-zero-trade-windows", type=int, default=2)
    parser.add_argument("--max-loss-windows", type=int, default=4)
    parser.add_argument("--min-non-negative-windows", type=int, default=2)
    parser.add_argument("--min-positive-after-windows", type=int, default=0)
    parser.add_argument("--min-mean-net-pnl", type=float, default=0.0)
    parser.add_argument("--min-median-profit-factor", type=float, default=0.95)
    parser.add_argument("--min-profit-factor-windows", type=int, default=0)
    parser.add_argument("--profit-factor-window-threshold", type=float, default=1.0)
    parser.add_argument("--min-worst-window-net-pnl", type=float, default=-1.8)
    parser.add_argument("--min-positive-delta-windows", type=int, default=2)
    parser.add_argument("--min-mean-delta-net-pnl", type=float, default=0.0)
    parser.add_argument("--min-median-delta-net-pnl", type=float, default=0.0)
    parser.add_argument("--min-worst-delta-net-pnl", type=float, default=-1.2)
    parser.add_argument("--inf-profit-factor-cap", type=float, default=5.0)

    parser.add_argument("--score-w-mean-net", type=float, default=1.0)
    parser.add_argument("--score-w-median-net", type=float, default=0.6)
    parser.add_argument("--score-w-median-pf", type=float, default=0.25)
    parser.add_argument("--score-w-non-negative-windows", type=float, default=0.08)
    parser.add_argument("--score-w-zero-trade-windows", type=float, default=0.25)
    parser.add_argument("--score-w-loss-windows", type=float, default=0.05)
    parser.add_argument("--score-w-worst-net-penalty", type=float, default=0.2)
    parser.add_argument("--score-w-total-trades", type=float, default=0.03)
    parser.add_argument("--score-w-trade-deficit-penalty", type=float, default=0.50)
    parser.add_argument("--score-w-mean-delta-net", type=float, default=1.0)
    parser.add_argument("--score-w-median-delta-net", type=float, default=0.5)
    parser.add_argument("--score-w-positive-delta-windows", type=float, default=0.1)
    parser.add_argument("--score-w-worst-delta-net-penalty", type=float, default=0.25)

    parser.add_argument("--grid-entry-signal-score-min", type=str, default="0.12,0.16,0.20")
    parser.add_argument("--grid-entry-signal-score-min-buy", type=str, default="0.16,0.20,0.24")
    parser.add_argument("--grid-entry-buy-min-signal-score", type=str, default="0.16,0.20,0.24")
    parser.add_argument("--grid-entry-signal-min-votes", type=str, default="1,2")
    parser.add_argument("--grid-entry-volatility-min", type=str, default="0.015,0.018,0.022")
    parser.add_argument("--grid-entry-buy-min-volatility", type=str, default="0.015,0.018,0.022")
    parser.add_argument("--grid-entry-require-trend-and-vol", type=str, default="0,1")
    parser.add_argument("--grid-entry-min-active-strategies", type=str, default="1,2")
    parser.add_argument("--grid-entry-buy-require-trend", type=str, default="0,1")
    parser.add_argument("--grid-entry-sell-require-trend", type=str, default="0,1")
    parser.add_argument("--grid-allocation-pct", type=str, default="0.006,0.008,0.010")
    parser.add_argument("--grid-exit-stop-loss-usdt", type=str, default="0.35,0.50,0.65")
    parser.add_argument("--grid-exit-take-profit-usdt", type=str, default="0.70,0.90,1.10")
    parser.add_argument("--grid-alpha-min-expectancy", type=str, default="-0.85,-0.50,-0.20,0.00")
    parser.add_argument("--grid-alpha-min-winrate", type=str, default="0.25,0.35,0.45")
    parser.add_argument("--grid-alpha-bad-weight-scale", type=str, default="0.18,0.25,0.35")
    parser.add_argument("--grid-alpha-good-weight-scale", type=str, default="1.00,1.08,1.16")
    parser.add_argument("--grid-alpha-keep-min-signals", type=str, default="0,1")
    parser.add_argument(
        "--grid-symbol-strategy-guard-min-winrate", type=str, default="0.20,0.30,0.35"
    )
    parser.add_argument(
        "--grid-symbol-strategy-guard-max-expectancy",
        type=str,
        default="-0.80,-0.50,-0.20",
    )
    parser.add_argument("--grid-side-guard-min-winrate", type=str, default="0.20,0.30,0.35")
    parser.add_argument(
        "--grid-side-guard-max-expectancy", type=str, default="-0.80,-0.50,-0.20"
    )
    parser.add_argument(
        "--grid-alpha-micro-alloc-scale", type=str, default="0.12,0.20,0.30"
    )
    parser.add_argument(
        "--grid-alpha-micro-enable", type=str, default="0,1"
    )
    parser.add_argument(
        "--grid-alpha-require-positive-universe", type=str, default="0,1"
    )
    parser.add_argument(
        "--grid-alpha-require-positive-universe-min-trades", type=str, default="2,3"
    )
    parser.add_argument(
        "--grid-alpha-require-positive-universe-min-winrate", type=str, default="0.30,0.35,0.40"
    )
    parser.add_argument(
        "--grid-alpha-require-positive-universe-min-expectancy", type=str, default="-0.05,0.00"
    )
    parser.add_argument("--grid-strategy-bias-votes", type=str, default="0,1")
    parser.add_argument("--grid-momentum-bias-enable", type=str, default="0,1")
    parser.add_argument(
        "--grid-alpha-micro-weight-scale", type=str, default="0.20,0.25,0.35"
    )
    parser.add_argument(
        "--grid-alpha-micro-net-target-scale", type=str, default="0.20,0.35,0.45,0.60"
    )
    parser.add_argument(
        "--grid-alpha-micro-min-expectancy", type=str, default="-0.20,-0.10,0.00"
    )
    parser.add_argument(
        "--grid-alpha-micro-max-alloc-usdt", type=str, default="30,45,60,90,120"
    )
    parser.add_argument(
        "--grid-alpha-micro-idle-relax-sec", type=str, default="300,420,600"
    )
    parser.add_argument(
        "--grid-alpha-micro-idle-min-expectancy", type=str, default="-0.35,-0.30,-0.20"
    )
    parser.add_argument(
        "--grid-alpha-micro-entry-score-mult", type=str, default="0.65,0.75,0.85"
    )
    parser.add_argument(
        "--grid-alpha-micro-entry-vol-mult", type=str, default="0.70,0.80,0.90"
    )
    parser.add_argument(
        "--grid-alpha-micro-entry-vote-min", type=str, default="1"
    )
    parser.add_argument(
        "--grid-alpha-micro-disable-trend", type=str, default="1"
    )
    parser.add_argument(
        "--grid-alpha-micro-disable-range-block", type=str, default="1"
    )
    parser.add_argument(
        "--grid-alpha-micro-exit-stop-loss-usdt", type=str, default="0.18,0.22,0.30"
    )
    parser.add_argument(
        "--grid-alpha-micro-exit-take-profit-usdt", type=str, default="0.55,0.70,1.00"
    )
    args = parser.parse_args()

    if args.windows <= 0 or args.window_min <= 0:
        raise SystemExit("windows and window-min must be > 0")
    if args.max_candidates <= 0:
        raise SystemExit("max-candidates must be > 0")
    if args.compare_before and args.min_positive_delta_windows <= 0:
        raise SystemExit("min-positive-delta-windows must be > 0 in compare-before mode")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candidates = _build_candidates(args)
    variant_factor = 2 if args.compare_before else 1
    est_minutes = len(candidates) * int(args.windows) * int(args.window_min) * variant_factor
    est_hours = est_minutes / 60.0
    print(
        f"[tuner] run_id={run_id} candidates={len(candidates)} "
        f"windows={args.windows} window_min={args.window_min} "
        f"compare_before={int(bool(args.compare_before))} "
        f"est_runtime_min={est_minutes} (~{est_hours:.2f}h)"
    )

    results = []
    for idx, cand in enumerate(candidates, start=1):
        cid = cand.get("id") or f"cand_{idx:03d}"
        overrides = dict(cand.get("overrides") or {})
        print(f"[tuner] candidate {idx}/{len(candidates)} id={cid} overrides={overrides}")
        window_results = []
        for w in range(args.windows):
            out = _run_after_window(args, overrides, w, cid)
            window_results.append(out)
            if out.get("ok"):
                m = out.get("metrics") or {}
                d = out.get("delta") or {}
                delta_txt = ""
                if args.compare_before and isinstance(d, dict):
                    delta_txt = f" delta_net={d.get('net_pnl_delta')}"
                print(
                    f"[tuner] candidate={cid} window={w + 1}/{args.windows} "
                    f"trades={m.get('trade_count')} net_pnl={m.get('net_pnl')} "
                    f"pf={m.get('profit_factor')}{delta_txt}"
                )
            else:
                print(
                    f"[tuner] candidate={cid} window={w + 1}/{args.windows} "
                    f"FAILED error={out.get('error')}"
                )
        summary = _candidate_summary(window_results, args)
        print(
            f"[tuner] candidate={cid} pass={summary.get('pass')} "
            f"score={summary.get('score'):.6f} total_net={summary.get('total_net_pnl'):.6f} "
            f"total_trades={summary.get('total_trades')} zero_windows={summary.get('zero_trade_windows')}"
        )
        results.append(
            {
                "id": cid,
                "origin": cand.get("origin"),
                "overrides": overrides,
                "summary": summary,
                "windows": window_results,
            }
        )

    ranked = sorted(
        results,
        key=lambda r: (
            1 if (r.get("summary") or {}).get("pass") else 0,
            int((r.get("summary") or {}).get("positive_after_windows") or 0),
            int((r.get("summary") or {}).get("profit_factor_windows") or 0),
            int((r.get("summary") or {}).get("positive_delta_windows") or 0)
            if args.compare_before
            else int((r.get("summary") or {}).get("total_trades") or 0),
            float((r.get("summary") or {}).get("mean_delta_net_pnl") or -9999.0)
            if args.compare_before
            else float((r.get("summary") or {}).get("score") or -9999.0),
            int((r.get("summary") or {}).get("total_trades") or 0),
            float((r.get("summary") or {}).get("score") or -9999.0),
            float((r.get("summary") or {}).get("mean_net_pnl") or -9999.0),
        ),
        reverse=True,
    )
    best = ranked[0] if ranked else None
    best_passed = next((r for r in ranked if (r.get("summary") or {}).get("pass")), None)
    selected = best_passed
    selected_overrides = dict((selected or {}).get("overrides") or {})

    selection_path = TMP_DIR / "wf_entry_tuner_selected_after_env.json"
    selection_payload = {
        "selected_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "selected_id": (selected or {}).get("id"),
        "selected_passed": bool((selected or {}).get("summary", {}).get("pass")),
        "overrides": selected_overrides,
        "alpha_bootstrap_source_db_url": args.alpha_bootstrap_source_db_url,
        "alpha_bootstrap_source_db_glob": args.alpha_bootstrap_source_db_glob,
    }
    selection_path.write_text(
        json.dumps(selection_payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    report = {
        "run_id": run_id,
        "params": {
            "windows": args.windows,
            "window_min": args.window_min,
            "max_candidates": args.max_candidates,
            "seed": args.seed,
            "symbols": args.symbols,
            "market_type": args.market_type,
            "timeframe": args.timeframe,
            "quality_profile": args.quality_profile,
            "use_mock": args.use_mock,
            "paper_auto_open": args.paper_auto_open,
            "paper_auto_close_sec": args.paper_auto_close_sec,
            "equity_snapshot_sec": args.equity_snapshot_sec,
            "alpha_bootstrap_source_db_url": args.alpha_bootstrap_source_db_url,
            "alpha_bootstrap_source_db_glob": args.alpha_bootstrap_source_db_glob,
            "compare_before": bool(args.compare_before),
            "base_before_env": _parse_env_overrides(args.base_before_env),
            "base_after_env": _parse_env_overrides(args.base_after_env),
            "criteria": {
                "min_windows_ok": args.min_windows_ok,
                "min_total_trades": args.min_total_trades,
                "max_zero_trade_windows": args.max_zero_trade_windows,
                "max_loss_windows": args.max_loss_windows,
                "min_non_negative_windows": args.min_non_negative_windows,
                "min_positive_after_windows": args.min_positive_after_windows,
                "min_mean_net_pnl": args.min_mean_net_pnl,
                "min_median_profit_factor": args.min_median_profit_factor,
                "min_profit_factor_windows": args.min_profit_factor_windows,
                "profit_factor_window_threshold": args.profit_factor_window_threshold,
                "min_worst_window_net_pnl": args.min_worst_window_net_pnl,
                "min_positive_delta_windows": args.min_positive_delta_windows,
                "min_mean_delta_net_pnl": args.min_mean_delta_net_pnl,
                "min_median_delta_net_pnl": args.min_median_delta_net_pnl,
                "min_worst_delta_net_pnl": args.min_worst_delta_net_pnl,
            },
            "score_weights": {
                "score_w_mean_net": args.score_w_mean_net,
                "score_w_median_net": args.score_w_median_net,
                "score_w_median_pf": args.score_w_median_pf,
                "score_w_non_negative_windows": args.score_w_non_negative_windows,
                "score_w_zero_trade_windows": args.score_w_zero_trade_windows,
                "score_w_loss_windows": args.score_w_loss_windows,
                "score_w_worst_net_penalty": args.score_w_worst_net_penalty,
                "score_w_total_trades": args.score_w_total_trades,
                "score_w_trade_deficit_penalty": args.score_w_trade_deficit_penalty,
                "score_w_mean_delta_net": args.score_w_mean_delta_net,
                "score_w_median_delta_net": args.score_w_median_delta_net,
                "score_w_positive_delta_windows": args.score_w_positive_delta_windows,
                "score_w_worst_delta_net_penalty": args.score_w_worst_delta_net_penalty,
            },
        },
        "ranking": [
            {
                "id": r.get("id"),
                "origin": r.get("origin"),
                "overrides": r.get("overrides"),
                "summary": r.get("summary"),
            }
            for r in ranked
        ],
        "selected": {
            "id": (selected or {}).get("id"),
            "origin": (selected or {}).get("origin"),
            "passed": bool((selected or {}).get("summary", {}).get("pass")),
            "overrides": selected_overrides,
            "summary": (selected or {}).get("summary") or {},
            "selection_file": str(selection_path),
        },
        "results": results,
    }

    json_path = RESULTS_DIR / f"wf_entry_tuner_{run_id}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    csv_path = RESULTS_DIR / f"wf_entry_tuner_{run_id}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "rank",
                "id",
                "origin",
                "pass",
                "score",
                "windows_ok",
                "windows_failed",
                "total_trades",
                "total_net_pnl",
                "mean_net_pnl",
                "median_net_pnl",
                "worst_window_net_pnl",
                "mean_winrate",
                "median_profit_factor",
                "zero_trade_windows",
                "loss_windows",
                "non_negative_windows",
                "positive_after_windows",
                "profit_factor_windows",
                "delta_windows",
                "missing_delta_windows",
                "positive_delta_windows",
                "non_negative_delta_windows",
                "mean_delta_net_pnl",
                "median_delta_net_pnl",
                "worst_delta_net_pnl",
                "overrides_json",
            ]
        )
        for i, r in enumerate(ranked, start=1):
            s = r.get("summary") or {}
            writer.writerow(
                [
                    i,
                    r.get("id"),
                    r.get("origin"),
                    bool(s.get("pass")),
                    s.get("score"),
                    s.get("windows_ok"),
                    s.get("windows_failed"),
                    s.get("total_trades"),
                    s.get("total_net_pnl"),
                    s.get("mean_net_pnl"),
                    s.get("median_net_pnl"),
                    s.get("worst_window_net_pnl"),
                    s.get("mean_winrate"),
                    s.get("median_profit_factor"),
                    s.get("zero_trade_windows"),
                    s.get("loss_windows"),
                    s.get("non_negative_windows"),
                    s.get("positive_after_windows"),
                    s.get("profit_factor_windows"),
                    s.get("delta_windows"),
                    s.get("missing_delta_windows"),
                    s.get("positive_delta_windows"),
                    s.get("non_negative_delta_windows"),
                    s.get("mean_delta_net_pnl"),
                    s.get("median_delta_net_pnl"),
                    s.get("worst_delta_net_pnl"),
                    json.dumps(r.get("overrides") or {}, ensure_ascii=True),
                ]
            )

    print("WF_TUNER_DONE")
    if selected is not None:
        print(
            "WF_TUNER_SELECTED "
            f"id={selected.get('id')} pass={bool((selected.get('summary') or {}).get('pass'))} "
            f"score={(selected.get('summary') or {}).get('score')}"
        )
    print(f"WF_TUNER_REPORT_JSON={json_path}")
    print(f"WF_TUNER_REPORT_CSV={csv_path}")
    print(f"WF_TUNER_SELECTED_ENV_JSON={selection_path}")


if __name__ == "__main__":
    main()
