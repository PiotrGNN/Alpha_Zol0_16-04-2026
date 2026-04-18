"""
test_backtester.py – test backtestów na danych OHLCV
"""

import pandas as pd
from strategies.UniversalStrategy import UniversalStrategy
from utils.backtesting import backtest_strategy, run_backtest


class _AlwaysBuyStrategy:
    def generate_signal(self, data):
        return "buy"


class _TrackingPositionManager:
    def __init__(self):
        self.positions = []
        self.closed = []
        self.open_calls = 0
        self.close_calls = 0

    def get_status(self):
        return "long" if self.positions else "none"

    def open_position(self, position):
        self.open_calls += 1
        self.positions.append(dict(position))

    def close_position(self, position):
        self.close_calls += 1
        if self.positions:
            self.closed.append(dict(position))
            self.positions.pop()


class _TrackingRiskManager:
    def apply_risk(self, signal, price, balance, position_status):
        return True, 0.0, 0.0, 1.0

    def check_drawdown(self, pnl_history):
        return False


def test_backtest_strategy():
    # Fake OHLCV: 25 świec, ostatnie 5 świec powodują wyraźne przecięcie SMA
    # fast/slow
    data = pd.DataFrame(
        {
            "close": [1] * 20 + [10, 10, 10, 10, 10],
            "open": [1] * 25,
            "timestamp": [f"2025-07-28T12:{i:02d}:00" for i in range(25)],
        }
    )
    strategy = UniversalStrategy(name="TestUniversal")
    trades, balance, drawdown = backtest_strategy(strategy, data)
    assert isinstance(trades, list)
    assert isinstance(balance, (int, float))
    assert isinstance(drawdown, (int, float))
    assert len(trades) >= 0


def test_run_backtest():
    import pandas as pd

    strategy = UniversalStrategy(name="TestUniversal")
    # Provide minimal DataFrame with required columns
    data = pd.DataFrame({"close": [], "open": [], "timestamp": []})
    result = run_backtest(strategy, data)
    assert isinstance(result, dict)


def test_backtest_strategy_close_path_uses_close_position(monkeypatch):
    import utils.backtesting as bt

    created_position_managers = []

    def _position_manager_factory():
        manager = _TrackingPositionManager()
        created_position_managers.append(manager)
        return manager

    monkeypatch.setattr(bt, "PositionManager", _position_manager_factory)
    monkeypatch.setattr(bt, "RiskManager", _TrackingRiskManager)

    data = pd.DataFrame(
        {
            "close": [1.0, 2.0],
            "open": [1.0, 2.0],
            "timestamp": ["2025-07-28T12:00:00", "2025-07-28T12:01:00"],
        }
    )

    trades, balance, drawdown = bt.backtest_strategy(_AlwaysBuyStrategy(), data)

    assert created_position_managers[0].open_calls == 1
    assert created_position_managers[0].close_calls == 1
    assert any(trade["action"] == "sell" for trade in trades)
    assert isinstance(balance, (int, float))
    assert isinstance(drawdown, (int, float))


def test_run_backtest_close_path_uses_close_position_and_latency(monkeypatch):
    import utils.backtesting as bt

    created_position_managers = []

    def _position_manager_factory():
        manager = _TrackingPositionManager()
        created_position_managers.append(manager)
        return manager

    monkeypatch.setattr(bt, "PositionManager", _position_manager_factory)
    monkeypatch.setattr(bt, "RiskManager", _TrackingRiskManager)

    data = pd.DataFrame(
        {
            "close": [1.0, 2.0],
            "open": [1.0, 2.0],
            "timestamp": ["2025-07-28T12:00:00", "2025-07-28T12:01:00"],
        }
    )

    result = bt.run_backtest(_AlwaysBuyStrategy(), data)

    assert created_position_managers[0].open_calls == 1
    assert created_position_managers[0].close_calls == 1
    assert result["n_trades"] == 1
    assert result["avg_latency"] > 0


def test_run_backtest_reports_peak_to_trough_drawdown(monkeypatch):
    import utils.backtesting as bt

    class _TwoTradeStrategy:
        def generate_signal(self, data):
            return "buy"

    class _TwoTradeRiskManager:
        def apply_risk(self, signal, price, balance, position_status):
            return True, 900.0, 1100.0, 1.0

        def check_drawdown(self, pnl_history):
            return False

    class _TwoTradePositionManager:
        def __init__(self):
            self.positions = []

        def get_status(self):
            return "long" if self.positions else "none"

        def open_position(self, position):
            self.positions.append(dict(position))

        def close_position(self, position):
            if self.positions:
                self.positions.pop()

    monkeypatch.setattr(bt, "PositionManager", _TwoTradePositionManager)
    monkeypatch.setattr(bt, "RiskManager", _TwoTradeRiskManager)

    data = pd.DataFrame(
        {
            "close": [1000.0, 800.0, 1000.0, 1400.0],
            "open": [1000.0, 800.0, 1000.0, 1400.0],
            "timestamp": [
                "2025-07-28T12:00:00",
                "2025-07-28T12:01:00",
                "2025-07-28T12:02:00",
                "2025-07-28T12:03:00",
            ],
        }
    )

    result = bt.run_backtest(_TwoTradeStrategy(), data)

    assert result["final_balance"] == 1200.0
    assert result["drawdown"] == 200.0
    assert result["n_trades"] == 2
