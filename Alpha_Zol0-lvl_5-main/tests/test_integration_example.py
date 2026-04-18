from core.AIStrategyEngine import AIStrategyEngine
from core.MarketDataFetcher import MarketDataFetcher
from core.PositionManager import PositionManager
from strategies.SmaCrossStrategy import SmaCrossStrategy


class _RiskLimitManager:
    def check_drawdown(self, pnl_history, window=10):
        return True


def test_strategy_and_risk_manager(monkeypatch):
    engine = AIStrategyEngine(
        SmaCrossStrategy(),
        PositionManager(),
        MarketDataFetcher(),
    )
    monkeypatch.setattr(
        engine.fetcher,
        "fetch_data",
        lambda symbol, timeframe, limit=120, runtime_mode=None: [
            {"close": 100.0, "high": 101.0, "low": 99.0, "timestamp": "t"}
            for _ in range(20)
        ],
    )
    monkeypatch.setattr(engine.trend_model, "predict_trend", lambda df: "UP")
    monkeypatch.setattr(
        engine.vol_model,
        "forecast_volatility",
        lambda df: 1.0,
    )
    monkeypatch.setattr(engine.position_manager, "get_status", lambda: "none")

    result = engine.analyze(
        "BTCUSDT",
        "1m",
        strategy_name="demo",
        pnl_history=[100, 95, 90],
        risk_manager=_RiskLimitManager(),
    )

    assert result["decision"] == "risk_limit"
    assert result["risk_limited"] is True
    assert result["trend"] == "UP"
