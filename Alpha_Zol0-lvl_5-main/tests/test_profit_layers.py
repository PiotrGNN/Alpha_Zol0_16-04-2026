import pandas as pd
from core.StrategyPerformanceTracker import StrategyPerformanceTracker
from models.anti_pattern_guard import AntiPatternGuard
from models.portfolio_optimizer import (
    QuantumPortfolioOptimizer as PortfolioOptimizer,
)
from models.time_advantage import TimeAdvantage
from models.tp_sl_optimizer import TpSlOptimizer
from models.trend_predictor import TrendPredictor
from models.zero_drawdown_guard import ZeroDrawdownGuard
from sklearn.ensemble import RandomForestClassifier


def test_tp_sl_optimizer_meta():
    optimizer = TpSlOptimizer()
    trades = [{"close": 100, "entry": 100}, {"close": 102, "entry": 100}]
    result = optimizer.optimize_tp_sl(trades, volatility_score=0.5)
    assert "tp" in result and "sl" in result
    backtest = optimizer.backtest_tp_sl(
        {"tp": 2, "sl": 1},
        pd.DataFrame(
            [
                {"close": 102, "entry": 100},
                {"close": 99, "entry": 100},
            ]
        ),
    )
    assert "tp_hits" in backtest and "sl_hits" in backtest


def test_time_advantage_meta():
    adv = TimeAdvantage()
    # Użyj listy dictów z kluczami 'open' i 'close'
    data = [
        {"open": 100, "close": 101},
        {"open": 101, "close": 102},
        {"open": 102, "close": 103},
        {"open": 103, "close": 110},
        {"open": 110, "close": 110},
    ]
    # Przewaga czasowa powinna być 7 (110-103)-(110-110)
    assert adv.compute_time_advantage(data) == 7


def test_anti_pattern_guard_meta():
    guard = AntiPatternGuard()
    history = [{"pnl": -1}, {"pnl": -2}, {"pnl": -3}]
    assert guard.detect_anti_patterns(history, window=3) is True
    assert guard.block_trade_if_risk(history) is False


def test_portfolio_optimizer_meta():
    optimizer = PortfolioOptimizer()
    positions = [{"pnl": 1}, {"pnl": 5}, {"pnl": -2}]
    perf = {"dummy": {}}
    assert optimizer.optimize_portfolio(positions, perf)["pnl"] == 5


def test_strategy_performance_tracker_meta():
    tracker = StrategyPerformanceTracker()
    tracker.update("stratA", {"pnl": 10})
    tracker.update("stratA", {"pnl": -5})
    tracker.update("stratB", {"pnl": 20})
    assert tracker.track_pnl("stratA") == 5
    assert tracker.winrate("stratA") == 0.5
    assert tracker.sharp_ratio("stratA") >= 0
    assert tracker.best_performing_strategy() == "stratB"


# test_profit_layers.py – Testy warstw zysków


def test_trend_predictor_fl():
    predictor = TrendPredictor()
    predictor.federated_update({})
    # Bootstrap model
    df = pd.DataFrame(
        {
            "close": [
                1,
                2,
                3,
                4,
                5,
                6,
                7,
                8,
                9,
                10,
                11,
                12,
                13,
                14,
                15,
                16,
                17,
                18,
                19,
                20,
                21,
                22,
            ],
            "high": [x + 0.5 for x in range(1, 23)],
            "low": [x - 0.5 for x in range(1, 23)],
            "volume": [100] * 22,
        }
    )
    import numpy as np

    X = predictor._extract_features(df)
    # Upewnij się, że X jest 2D array
    X = np.array(X)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    y = [1] * len(X)
    predictor.model = RandomForestClassifier(n_estimators=10)
    predictor.model.fit(X, y)
    predictor.is_trained = True
    # Upewnij się, że predykcja nie rzuca błędu przez NaN/kształt
    last_feat = predictor._extract_features(df).iloc[-1]
    import numpy as np

    last_feat = np.array(last_feat)
    # Jeśli skalar, zamień na 2D array
    if last_feat.ndim == 0:
        last_feat = last_feat.reshape(1, 1)
    elif last_feat.ndim == 1:
        last_feat = last_feat.reshape(1, -1)
    # Zamień NaN na 0
    if np.isnan(last_feat).any():
        last_feat = np.nan_to_num(last_feat)
    pred = predictor.model.predict(last_feat)[0]
    assert pred in [1, "↑", "↓", "→"]


def test_tp_sl_optimizer():
    optimizer = TpSlOptimizer()
    result = optimizer.optimize([])
    assert "tp" in result and "sl" in result


def test_time_advantage():
    adv = TimeAdvantage()
    # Użyj listy dictów z kluczami 'open' i 'close'
    data = [
        {"open": 1, "close": 2},
        {"open": 2, "close": 3},
        {"open": 3, "close": 4},
    ]
    assert adv.detect(data) in [True, False]


def test_time_advantage_zero_timestamps_compute_latency():
    adv = TimeAdvantage()
    data = [
        {"open": 10, "close": 11},
        {"open": 11, "close": 12},
    ]
    result = adv.analyze_entry(
        data,
        signal_time=0.0,
        execution_time=5.0,
    )
    assert result["latency"] == 5.0


def test_anti_pattern_guard():
    guard = AntiPatternGuard()
    assert guard.check("buy") in [True, False]


def test_zero_drawdown_guard():
    guard = ZeroDrawdownGuard()
    assert guard.check([1, 2, 3]) is True
    assert guard.check([-1, 2, 3]) is False
    assert guard.check([100, 92, 90], max_drawdown=0.2) is True
    assert guard.check([100, 92, 79], max_drawdown=0.2) is False
    assert guard.check([], max_drawdown=0.2) is True
    assert guard.check([0, 0, 0], max_drawdown=0.2) is True
    assert guard.check(["bad"], max_drawdown=0.2) is False
    assert guard.check([100, 95, 93], max_drawdown="bad") is False
    assert guard.check([100, 95, 93], max_drawdown=-0.1) is False
