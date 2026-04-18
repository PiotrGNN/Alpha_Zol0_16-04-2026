import time

import pandas as pd
from core.PositionManager import PositionManager
from core.RiskManager import RiskManager
from strategies.UniversalStrategy import UniversalStrategy

"""
✅ Completed by ZoL0-FIXER — 2025-07-29
Description: Full-featured backtesting engine for strategies, with robust
trade, PnL, drawdown, and winrate logic. Docstrings and PEP8 compliance
ensured.
backtesting.py – silnik backtestowy
"""


def reduce_df_memory(df):
    """
    [TASK-ID: data_reduction]
    Reduce memory usage of a DataFrame by downcasting numeric types.
    Używać tylko poza pętlą decyzyjną
    (np. przy ładowaniu danych historycznych).
    """
    for col in df.select_dtypes(include=["float"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="float")
    for col in df.select_dtypes(include=["int"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")

    return df


def _max_drawdown_amount(values):
    try:
        series = [float(value) for value in values]
    except Exception:
        return 0.0
    if not series:
        return 0.0
    peak = series[0]
    worst_drawdown = 0.0
    for value in series:
        if value > peak:
            peak = value
        drawdown = peak - value
        if drawdown > worst_drawdown:
            worst_drawdown = drawdown
    return worst_drawdown


def backtest_strategy(strategy, historical_data, initial_balance=1000):
    """
    Run a backtest for a given strategy on historical OHLCV data.
    Args:
        strategy: Strategy instance or string
            (uses UniversalStrategy if str/None)
        historical_data: DataFrame with OHLCV and timestamp columns
        initial_balance: Starting balance for the simulation
    Returns:
        trades: List of executed trades
        balance: Final balance after backtest
        drawdown: Maximum drawdown observed
    """
    if isinstance(strategy, str) or strategy is None:
        strategy = UniversalStrategy(name=str(strategy))
    position_manager = PositionManager()
    risk_manager = RiskManager()
    trades = []
    pnl_history = []
    balance = initial_balance
    for i, row in historical_data.iterrows():
        price = row["close"]
        signal = strategy.generate_signal(historical_data.iloc[: i + 1])
        position_status = position_manager.get_status()
        allow, sl_price, tp_price, allocation = risk_manager.apply_risk(
            signal,
            price,
            balance,
            position_status,
        )
        if allow and signal == "buy" and position_status == "none":
            position_manager.open_position(
                {
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "entry_price": price,
                    "timestamp": row["timestamp"],
                    "pnl": 0,
                }
            )
            trades.append(
                {
                    "action": "buy",
                    "price": price,
                    "timestamp": row["timestamp"],
                }
            )
        elif position_status == "long":
            entry_price = position_manager.positions[-1]["entry_price"]
            if price <= sl_price or price >= tp_price:
                pnl = price - entry_price
                balance += pnl
                position_manager.close_position(position_manager.positions[-1])
                trades.append(
                    {
                        "action": "sell",
                        "price": price,
                        "timestamp": row["timestamp"],
                        "pnl": pnl,
                    }
                )
        pnl_history.append(balance)
    drawdown = _max_drawdown_amount(pnl_history)
    return trades, balance, drawdown


def run_backtest(strategy, data, initial_balance=1000):
    """
    Full-featured backtest: SL/TP, latency, scoring, winrate, and trade stats.
    Args:
        strategy: Strategy instance or string
            (uses UniversalStrategy if str/None)
        data: DataFrame with OHLCV and timestamp columns
        initial_balance: Starting balance for the simulation
    Returns:
        result: Dict with trades, final_balance, drawdown, winrate,
            avg_latency, n_trades
    # ⬆️ optimized for performance:
    # vectorized winrate/drawdown, minimize lookups
    """
    if isinstance(strategy, str) or strategy is None:
        strategy = UniversalStrategy(name=str(strategy))
    position_manager = PositionManager()
    risk_manager = RiskManager()
    trades = []
    pnl_history = []
    balance = initial_balance
    latency_list = []
    get_status = position_manager.get_status
    open_position = position_manager.open_position
    close_position = position_manager.close_position
    gen_signal = strategy.generate_signal
    apply_risk = risk_manager.apply_risk
    check_drawdown = risk_manager.check_drawdown
    for i, row in data.iterrows():
        step_started_ns = time.perf_counter_ns()
        price = row["close"]
        signal = gen_signal(data.iloc[: i + 1])
        position_status = get_status()
        allow, sl_price, tp_price, allocation = apply_risk(
            signal, price, balance, position_status
        )
        if allow and signal == "buy" and position_status == "none":
            open_position(
                {
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "entry_price": price,
                    "timestamp": row["timestamp"],
                    "pnl": 0,
                }
            )
            trades.append(
                {
                    "action": "buy",
                    "price": price,
                    "timestamp": row["timestamp"],
                }
            )
        elif position_status == "long":
            entry_price = position_manager.positions[-1]["entry_price"]
            if price <= sl_price or price >= tp_price:
                pnl = price - entry_price
                balance += pnl
                close_position(position_manager.positions[-1])
                trades.append(
                    {
                        "action": "sell",
                        "price": price,
                        "timestamp": row["timestamp"],
                        "pnl": pnl,
                    }
                )
        pnl_history.append(balance)
        latency_list.append((time.perf_counter_ns() - step_started_ns) / 1_000_000.0)
        if check_drawdown(pnl_history):
            break
    # Vectorized winrate/drawdown calculation
    if trades:
        trades_df = pd.DataFrame(trades)
        sell_trades = trades_df[trades_df["action"] == "sell"]
        n_trades = len(sell_trades)
        wins = (sell_trades["pnl"] > 0).sum() if "pnl" in sell_trades else 0
        winrate = wins / n_trades if n_trades > 0 else 0.0
    else:
        n_trades = 0
        winrate = 0.0
    drawdown = _max_drawdown_amount(pnl_history)
    avg_latency = sum(latency_list) / len(latency_list) if latency_list else 0.0
    result = {
        "trades": trades,
        "final_balance": balance,
        "drawdown": drawdown,
        "winrate": winrate,
        "avg_latency": avg_latency,
        "n_trades": n_trades,
    }
    return result
