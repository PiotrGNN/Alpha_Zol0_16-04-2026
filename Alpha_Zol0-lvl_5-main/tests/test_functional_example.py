from core.AIStrategyEngine import AIStrategyEngine
from core.MarketDataFetcher import MarketDataFetcher
from core.PositionManager import PositionManager
from strategies.SmaCrossStrategy import SmaCrossStrategy


def test_full_bot_workflow(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    engine = AIStrategyEngine(
        SmaCrossStrategy(),
        PositionManager(),
        MarketDataFetcher(),
    )
    monkeypatch.setattr(
        engine.fetcher,
        "fetch_data",
        lambda symbol, timeframe, limit=120, runtime_mode=None: [
            {
                "close": 1.0,
                "high": 1.5,
                "low": 0.5,
                "timestamp": f"2025-07-28T12:{idx:02d}:00",
            }
            for idx in range(20)
        ]
        + [
            {
                "close": 10.0,
                "high": 10.5,
                "low": 9.5,
                "timestamp": "2025-07-28T12:20:00",
            }
        ],
    )
    monkeypatch.setattr(engine.trend_model, "predict_trend", lambda df: "UP")
    monkeypatch.setattr(
        engine.vol_model,
        "forecast_volatility",
        lambda df: 1.0,
    )

    decision = engine.run("BTCUSDT", "1m")

    assert decision == "buy"
    assert engine.position_manager.get_status() == "long"
    assert len(engine.position_manager.positions) == 1
