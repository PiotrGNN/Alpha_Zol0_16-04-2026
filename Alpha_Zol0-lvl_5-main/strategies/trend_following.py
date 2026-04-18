"""
Trend following strategy implementation.
"""

from typing import Any, Dict, List, Optional

import pandas as pd
from .base import Strategy
from utils.logger import setup_logger
import logging

# Logger setup (wstawiony po wszystkich importach)
setup_logger()
logger = logging.getLogger(__name__)


class TrendFollowingStrategy(Strategy):

    def calculate_position_size(self, balance, price, **kwargs):
        """
        Risk management: np. 1% kapitału na transakcję
        (możesz dynamicznie zmieniać przez AI)
        """
        risk_per_trade = self.parameters.get("risk_per_trade", 0.01)
        risk_amount = balance * risk_per_trade
        return risk_amount / max(price, 1e-8)

    """
    Multi-timeframe trend following strategy with robust validation
    and error handling.
    """

    def __init__(
        self,
        timeframes: Optional[List[str]] = None,
        indicators: Optional[List[str]] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> None:
        if indicators is None:
            indicators = ["close"]
        if timeframes is None:
            timeframes = ["1h"]
        if parameters is None:
            parameters = {
                "min_periods": 100,
                "ema_fast": 12,
                "ema_slow": 26,
                "rsi_period": 14,
                "rsi_overbought": 70,
                "rsi_oversold": 30,
                "adx_period": 14,
                "adx_threshold": 25,
                "atr_period": 14,
                "risk_per_trade": 0.02,
                "profit_target_atr": 3.0,
                "stop_loss_atr": 2.0,
            }
        required_indicators = [
            "ema_fast",
            "ema_slow",
            "rsi",
            "adx",
            "atr",
        ]
        indicators = list(set(indicators + required_indicators))
        super().__init__(name="TrendFollowing", timeframes=timeframes)
        self.parameters = parameters
        self.indicators = indicators
        self.position = None
        self.last_signal = None

    def analyze(
        self,
        symbol: str,
        klines: pd.DataFrame,
        indicators: Dict[str, pd.Series],
        timeframe: str,
        sentiment_data: Optional[List[Dict[str, Any]]] = None,
        sentiment_signal: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Analyze market and (optionally) sentiment data for hybrid signals.
        """
        results = {"signals": [], "metrics": {}, "analysis": {}}
        try:
            current = {name: series.iloc[-1] for name, series in indicators.items()}
            previous = {name: series.iloc[-2] for name, series in indicators.items()}
            trend_strength = self._calculate_trend_strength(current, previous)
            risk_metrics = self._calculate_risk_metrics(current, klines.iloc[-1])
            signals = self._generate_signals(
                trend_strength=trend_strength,
                risk_metrics=risk_metrics,
                current=current,
                previous=previous,
            )
            self.last_signal = signals[0]["type"] if signals else None
            results["signals"] = signals
            results["metrics"] = {
                "trend_strength": trend_strength,
                "risk_score": risk_metrics["risk_score"],
                "volatility": risk_metrics["volatility"],
            }
            results["analysis"] = {
                "trend": {
                    "direction": trend_strength["direction"],
                    "strength": trend_strength["strength"],
                    "momentum": trend_strength["momentum"],
                },
                "risk": risk_metrics,
            }
            # Sentiment fusion: if strong sentiment, boost/trump technicals
            if sentiment_signal and sentiment_signal.get("type") == "entry":
                if (
                    sentiment_signal.get("side") == "buy"
                    and trend_strength["direction"] == "up"
                ):
                    signals.insert(
                        0,
                        {
                            "type": "entry",
                            "side": "buy",
                            "reason": "sentiment+trend",
                        },
                    )
                elif (
                    sentiment_signal.get("side") == "sell"
                    and trend_strength["direction"] == "down"
                ):
                    signals.insert(
                        0,
                        {
                            "type": "entry",
                            "side": "sell",
                            "reason": "sentiment+trend",
                        },
                    )
            # Bias vote for routing when no entry/exit signal was produced
            if not signals:
                try:
                    import os

                    bias_enable = os.environ.get("STRATEGY_BIAS_VOTES", "1") == "1"
                except Exception:
                    bias_enable = True
                if bias_enable and trend_strength.get("strength") == "strong":
                    direction = trend_strength.get("direction")
                    if direction in (1, "up", "UP"):
                        signals.append(
                            {
                                "type": "bias",
                                "side": "buy",
                                "reason": "trend_strength",
                            }
                        )
                    elif direction in (-1, "down", "DOWN"):
                        signals.append(
                            {
                                "type": "bias",
                                "side": "sell",
                                "reason": "trend_strength",
                            }
                        )
        except Exception as e:
            logger.error(f"TrendFollowingStrategy error: {e}")
        return results

    def validate(self) -> List[str]:
        """
        Validate strategy configuration and parameters.
        Returns:
            List[str]: List of validation error messages.
        """
        errors = super().validate()
        if self.parameters.get("ema_fast", 0) >= self.parameters.get("ema_slow", 1):
            errors.append(
                f"{self.__class__.__name__}: Fast EMA period must be less "
                f"than slow EMA"
            )
        if not 0 < self.parameters.get("risk_per_trade", 0) <= 0.05:
            errors.append(
                f"{self.__class__.__name__}: risk_per_trade must be between 0 "
                f"and 0.05"
            )
        return errors

    def _calculate_trend_strength(
        self,
        current: Dict[str, float],
        previous: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        Calculate trend strength metrics.
        Returns:
            Dict[str, Any]: Trend strength metrics.
        """
        ema_trend = (
            1
            if current["ema_fast"] > current["ema_slow"]
            else -1 if current["ema_fast"] < current["ema_slow"] else 0
        )
        rsi = current["rsi"]
        rsi_momentum = (
            1
            if rsi > 50 and rsi < self.parameters["rsi_overbought"]
            else (-1 if rsi < 50 and rsi > self.parameters["rsi_oversold"] else 0)
        )
        adx = current["adx"]
        trend_strength = "strong" if adx > self.parameters["adx_threshold"] else "weak"
        return {
            "direction": ema_trend,
            "momentum": rsi_momentum,
            "strength": trend_strength,
            "score": abs(ema_trend)
            + abs(rsi_momentum)
            + (1 if trend_strength == "strong" else 0),
        }

    def _calculate_risk_metrics(
        self,
        current: Dict[str, float],
        candle: pd.Series,
    ) -> Dict[str, Any]:
        """
        Calculate risk and volatility metrics.
        Returns:
            Dict[str, Any]: Risk and volatility metrics.
        """
        atr = current.get("atr", 0.0)
        try:
            atr = float(atr)
        except Exception:
            atr = 0.0
        stop_distance = atr * self.parameters["stop_loss_atr"]
        target_distance = atr * self.parameters["profit_target_atr"]
        close = candle.get("close", 0)
        try:
            close = float(close)
        except Exception:
            close = 0.0
        if close <= 0:
            volatility = 0.0
        else:
            volatility = atr / close
        if target_distance <= 0:
            risk_score = 1e9
        else:
            risk_score = stop_distance / target_distance
        return {
            "volatility": volatility,
            "risk_score": risk_score,
            "stop_distance": stop_distance,
            "target_distance": target_distance,
        }

    def _generate_signals(
        self,
        trend_strength: Dict[str, Any],
        risk_metrics: Dict[str, Any],
        current: Dict[str, float],
        previous: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        """
        Generate trading signals based on analysis.
        Returns:
            List[Dict[str, Any]]: List of signal dicts.
        """
        signals = []
        # Entry conditions
        if (
            trend_strength["score"] >= 2
            and risk_metrics["volatility"] < 0.05
            and risk_metrics["risk_score"] < 0.7
        ):
            # Long entry
            if (
                trend_strength["direction"] > 0
                and trend_strength["momentum"] > 0
                and previous["ema_fast"] <= previous["ema_slow"]
                and current["ema_fast"] > current["ema_slow"]
            ):
                signals.append({"type": "entry", "side": "buy"})
            # Short entry
            elif (
                trend_strength["direction"] < 0
                and trend_strength["momentum"] < 0
                and previous["ema_fast"] >= previous["ema_slow"]
                and current["ema_fast"] < current["ema_slow"]
            ):
                signals.append({"type": "entry", "side": "sell"})
        # Exit conditions
        elif (
            (
                trend_strength["direction"] > 0
                and current["rsi"] > self.parameters["rsi_overbought"]
            )
            or (
                trend_strength["direction"] < 0
                and current["rsi"] < self.parameters["rsi_oversold"]
            )
            or (trend_strength["strength"] == "weak" and trend_strength["score"] < 2)
        ):
            signals.append({"type": "exit", "reason": "trend_reversal"})
        return signals
