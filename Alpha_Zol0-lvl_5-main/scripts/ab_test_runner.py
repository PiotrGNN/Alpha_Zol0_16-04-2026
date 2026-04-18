import os
import sqlite3
import subprocess
import sys
import time
import json
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = WORKDIR / "config"
RESULTS_DIR = WORKDIR / "results"
CONFIG_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

# Default durations
DEFAULT_DURATION_SEC = 30 * 60  # 30 minutes


def write_config(
    mode: str,
    retrain_interval: int,
    balance: float,
    symbol: str = "BTC-USDT",
):
    cfg = {
        "symbol": symbol,
        "timeframe": 1,
        "sl_pct": 0.5,
        "tp_pct": 1.0,
        "api_key": None,
        "api_secret": None,
        "balance": balance,
        "retrain_interval": retrain_interval,
    }
    path = CONFIG_DIR / "config.yaml"
    import yaml

    with path.open("w") as f:
        yaml.safe_dump(cfg, f)
    return path


def start_bot(
    db_path: Path,
    duration: int,
    use_mock: bool = False,
    allow_db_writes: bool = False,
):
    env = os.environ.copy()
    env["LIVE"] = "0"
    env["USE_MOCK"] = "1" if use_mock else "0"
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    # Ensure PAPER_RUN_ONCE not set
    env.pop("PAPER_RUN_ONCE", None)
    # Optionally enable DB writes by setting a local token
    if allow_db_writes:
        env["ZOL0_TOKEN"] = "ab_test_runner"

    code = "from core.BotCore import run_bot; " "run_bot(simulate=True)"
    cmd = [sys.executable, "-u", "-c", code]
    p = subprocess.Popen(cmd, cwd=str(WORKDIR), env=env)
    print(f"Started bot pid={p.pid} with DB={db_path}")
    start = time.time()
    try:
        while True:
            elapsed = time.time() - start
            if elapsed >= duration:
                print("Duration reached, terminating bot")
                break
            time.sleep(5)
    finally:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def collect_metrics(db_path: Path):
    if not db_path.exists():
        return {
            "decisions_count": 0,
            "order_events": 0,
            "trainer_events": 0,
            "final_equity": None,
            "total_pnl": 0,
            "max_drawdown": None,
            "equity_timeseries_len": 0,
        }
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Decisions count
    try:
        cur.execute("SELECT COUNT(*) FROM decisions")
        decisions_count = cur.fetchone()[0]
    except Exception:
        decisions_count = 0

    # Equity timeseries
    equity_ts = []
    try:
        cur.execute("SELECT timestamp, equity, pnl FROM equity ORDER BY id ASC")
        rows = cur.fetchall()
        for r in rows:
            equity_ts.append({"timestamp": r[0], "equity": r[1], "pnl": r[2]})
    except Exception:
        equity_ts = []

    # Logs: count order events and trainer events
    order_events = 0
    trainer_events = 0
    try:
        cur.execute("SELECT event, details FROM logs")
        for ev, det in cur.fetchall():
            if ev and "order" in ev:
                order_events += 1
            if ev and "ai_retrain" in ev:
                trainer_events += 1
    except Exception:
        pass

    conn.close()

    # Compute final metrics
    final_equity = equity_ts[-1]["equity"] if equity_ts else None
    total_pnl = sum(x.get("pnl", 0) for x in equity_ts) if equity_ts else 0

    # Max drawdown from equity series
    max_drawdown = None
    if equity_ts:
        highs = []
        drawdowns = []
        for e in equity_ts:
            val = e["equity"]
            if not highs:
                highs.append(val)
            else:
                highs.append(max(highs[-1], val))
            drawdowns.append((highs[-1] - val) / highs[-1] if highs[-1] != 0 else 0)
        max_drawdown = max(drawdowns)

    return {
        "decisions_count": decisions_count,
        "order_events": order_events,
        "trainer_events": trainer_events,
        "final_equity": final_equity,
        "total_pnl": total_pnl,
        "max_drawdown": max_drawdown,
        "equity_timeseries_len": len(equity_ts),
    }


def run_ab(
    mode: str,
    duration: int = DEFAULT_DURATION_SEC,
    retrain_interval: int = 1000,
    balance: float = 10000.0,
    use_mock: bool = False,
    allow_db_writes: bool = False,
    symbol: str = "BTC-USDT",
):
    assert mode in ("A", "B")
    db_path = WORKDIR / f"ab_test_{mode}.db"
    if db_path.exists():
        db_path.unlink()
    # Write config for requested symbol and parameters
    write_config(mode, retrain_interval, balance, symbol=symbol)
    # Ensure parent dir exists (WORKDIR should exist already)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Initialize DB schema in a subprocess that respects the DATABASE_URL env
    print("Initializing DB schema...")
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    init_cmd = [
        sys.executable,
        "-c",
        "from core.db_models import init_db; init_db(); print('init_db done')",
    ]
    subprocess.run(init_cmd, cwd=str(WORKDIR), env=env, check=False)

    start_bot(db_path, duration, use_mock=use_mock, allow_db_writes=allow_db_writes)
    metrics = collect_metrics(db_path)
    out_path = RESULTS_DIR / f"ab_result_{mode}.json"
    with out_path.open("w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Experiment {mode} complete. Results: {metrics}")
    return metrics


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["A", "B"])  # A: trainer ON; B: trainer OFF
    p.add_argument("--duration", type=int, default=DEFAULT_DURATION_SEC)
    p.add_argument("--balance", type=float, default=10000.0)
    p.add_argument(
        "--symbol",
        type=str,
        default="BTC-USDT",
        help="Trading symbol to use (e.g., BTC-USDT or " "ETH-USDT)",
    )
    p.add_argument(
        "--retrain-interval",
        type=int,
        default=None,
        help="Override retrain interval for this run",
    )
    p.add_argument(
        "--use-mock",
        action="store_true",
        help="Use mocked market data (for quick dry runs)",
    )
    p.add_argument(
        "--trusted-runner",
        action="store_true",
        help="Enable DB writes by setting a local test token",
    )
    args = p.parse_args()

    if args.mode == "A":
        # Trainer ON: frequent retraining (default 10 unless overridden)
        ri = 10 if args.retrain_interval is None else args.retrain_interval
        run_ab(
            "A",
            duration=args.duration,
            retrain_interval=ri,
            balance=args.balance,
            use_mock=args.use_mock,
            allow_db_writes=args.trusted_runner,
            symbol=args.symbol,
        )
    else:
        # Trainer OFF: effectively disabled (default 10_000_000 unless overridden)
        ri = 10_000_000 if args.retrain_interval is None else args.retrain_interval
        run_ab(
            "B",
            duration=args.duration,
            retrain_interval=ri,
            balance=args.balance,
            use_mock=args.use_mock,
            allow_db_writes=args.trusted_runner,
            symbol=args.symbol,
        )
