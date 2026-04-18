# AIStrategyEngine.py – Integracja danych i decyzji


import csv
import logging
import os

import pandas as pd
from models.trend_predictor import TrendPredictor
from models.volatility_forecaster import VolatilityForecaster


class AIStrategyEngine:
    def __init__(self, strategy, position_manager, fetcher):
        self.strategy = strategy
        self.position_manager = position_manager
        self.fetcher = fetcher
        # ⬆️ optimized for performance: instantiate models once
        self.trend_model = TrendPredictor()
        self.vol_model = VolatilityForecaster()

    def analyze(
        self,
        symbol,
        timeframe,
        strategy_name="default",
        pnl_history=None,
        tracker=None,
        risk_manager=None,
    ):
        logger = logging.getLogger("AIStrategyEngine")
        try:
            ohlcv_limit = int(os.environ.get("OHLCV_LIMIT", "120"))
        except Exception:
            ohlcv_limit = 120
        candles = self.fetcher.fetch_data(symbol, timeframe, limit=ohlcv_limit)
        df = pd.DataFrame(candles)
        trend = self.trend_model.predict_trend(df)
        volatility = self.vol_model.forecast_volatility(df)
        status = self.position_manager.get_status()
        decision = None
        risk_limited = False
        if risk_manager and pnl_history:
            if risk_manager.check_drawdown(pnl_history, window=10):
                logger.info(f"Rolling drawdown limit reached for {strategy_name}")
                decision = "risk_limit"
                risk_limited = True
        score = None
        if tracker:
            score = tracker.score(strategy_name)
            logger.info(f"Strategy {strategy_name} score: {score}")
        if decision is None:
            if trend == "UP" and status == "none":
                decision = "buy"
            elif trend == "DOWN" and status == "long":
                decision = "sell"
            else:
                decision = "wait"
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_name": strategy_name,
            "ohlcv_limit": ohlcv_limit,
            "candles": candles,
            "dataframe": df,
            "trend": trend,
            "volatility": volatility,
            "status": status,
            "decision": decision,
            "risk_limited": risk_limited,
            "score": score,
        }

    # [TASK-ID: logic_guard]
    # ⚠️ UWAGA: poniższa pętla jest krytyczna dla czasu decyzji –
    # żadnych operacji I/O, sleep, ani monitoringu!
    # @no_slow_path
    def run(
        self,
        symbol,
        timeframe,
        strategy_name="default",
        pnl_history=None,
        tracker=None,
        risk_manager=None,
    ):
        # ⬆️ optimized for performance:
        # reuse model objects, minimize object creation
        logger = logging.getLogger("AIStrategyEngine")
        analysis = self.analyze(
            symbol,
            timeframe,
            strategy_name=strategy_name,
            pnl_history=pnl_history,
            tracker=tracker,
            risk_manager=risk_manager,
        )
        df = analysis["dataframe"]
        trend = analysis["trend"]
        volatility = analysis["volatility"]
        status = analysis["status"]
        decision = analysis["decision"]
        if decision == "buy":
            self.position_manager.open_position(
                {
                    "symbol": symbol,
                    "side": "long",
                    "entry_price": df["close"].iloc[-1],
                    "timestamp": df["timestamp"].iloc[-1],
                    "pnl": 0,
                    "sl": df["close"].iloc[-1] - volatility,
                    "tp": df["close"].iloc[-1] + volatility,
                }
            )
        elif decision == "sell":
            self.position_manager.close_position(self.position_manager.positions[-1])
        if os.environ.get("LIVE", "0") != "1":
            log_path = os.path.join("autopsy", "decision_log.csv")
            try:
                with open(log_path, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(
                        [
                            pd.Timestamp.now().isoformat(),
                            decision,
                            f"symbol={symbol}, strategy={strategy_name}, "
                            f"trend={trend}, status={status}, "
                            f"volatility={volatility}",
                        ]
                    )
            except Exception as e:
                logger.warning(f"AI decision log error: {e}")
        else:
            logger.info("LIVE mode: CSV logging disabled for decisions")
        return decision
