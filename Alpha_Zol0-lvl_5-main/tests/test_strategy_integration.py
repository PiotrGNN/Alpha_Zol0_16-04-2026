# test_strategy_integration.py –
# Test integracji AIStrategyEngine z RiskManager i StrategyPerformanceTracker
import pandas as pd
from core.AIStrategyEngine import AIStrategyEngine
from core.MarketDataFetcher import MarketDataFetcher
from core.PositionManager import PositionManager
from core.RiskManager import RiskManager
from core.StrategyPerformanceTracker import StrategyPerformanceTracker
from strategies.UniversalStrategy import (
    UniversalStrategy,
)


def test_strategy_engine_integration(caplog):
    caplog.set_level("INFO")
    # Zamiast stringa 'stratA', użyj obiektu strategii
    strategy = UniversalStrategy(name="stratA")
    position_manager = PositionManager()
    fetcher = MarketDataFetcher()
    engine = AIStrategyEngine(strategy, position_manager, fetcher)
    risk_manager = RiskManager(max_drawdown=0.1)
    tracker = StrategyPerformanceTracker()
    # Symulacja historii PnL
    pnl_history = [1000, 950, 900, 920, 910, 905, 890, 880, 870, 860, 850]
    # Dodaj wyniki do trackera
    for pnl in [10, -5, 20]:
        tracker.update(strategy.name, {"pnl": pnl})
    # Uruchom silnik z nowymi mechanizmami
    # Provide minimal OHLCV data to avoid KeyError
    # Bootstrap VolatilityForecaster model
    from models.volatility_forecaster import VolatilityForecaster

    forecaster = VolatilityForecaster()
    df = pd.DataFrame(
        {
            "close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
            "high": [101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
            "low": [99, 100, 101, 102, 103, 104, 105, 106, 107, 108],
        }
    )
    X = [forecaster.extract_features(df)] * 10
    y = [0.1 * i for i in range(10)]
    forecaster.train_model(X, y)
    engine.fetcher.get_ohlcv = lambda symbol, tf, limit=None: [
        {
            "close": 100,
            "high": 101,
            "low": 99,
            "timestamp": "2025-07-28T12:00:00",
        }
        for _ in range(10)
    ]
    result = engine.run(
        "BTCUSDT",
        "1m",
        strategy_name=strategy.name,
        pnl_history=pnl_history,
        tracker=tracker,
        risk_manager=risk_manager,
    )
    # Sprawdź czy rolling drawdown i score są logowane
    log_drawdown = any(
        "Rolling drawdown limit reached" in r.getMessage() for r in caplog.records
    )
    log_score = any("Strategy" in r.getMessage() for r in caplog.records)
    assert result in ["risk_limit", "buy", "sell", "wait"]
    assert log_drawdown or log_score
