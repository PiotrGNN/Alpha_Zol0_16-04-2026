"""
Breakout Strategy Implementation
"""

from typing import Any, Dict, List

import pandas as pd
import logging

from utils.logger import setup_logger
from strategies.base import Strategy

setup_logger()
logger = logging.getLogger(__name__)


class BreakoutStrategy(Strategy):
    def calculate_position_size(
        self, signal: Dict[str, Any], account_balance: float
    ) -> float:
        """
        Advanced position sizing based on risk management, volatility,
        and account balance.
        - Uses a fixed risk percentage per trade (default 1%).
        - Calculates stop-loss distance using recent price range or volatility.
        - Adjusts position size so risk per trade does not exceed the set
          percentage.
        - Handles both long and short signals.
        """
        risk_pct = self.parameters.get("risk_pct", 0.01)  # 1% risk per trade
        min_position = self.parameters.get("min_position", 1e-6)
        max_position = self.parameters.get("max_position", 1.0)
        lookback = self.parameters.get("lookback", 20)
        # Extract price info from signal or context
        price = signal.get("price")
        stop_loss = signal.get("stop_loss")
        klines = signal.get("klines")  # pd.DataFrame, if available
        # Fallback: use last known price or metrics
        if price is None and hasattr(self, "last_price"):
            price = self.last_price
        # Estimate stop-loss distance
        stop_distance = None
        if stop_loss is not None and price is not None:
            stop_distance = abs(price - stop_loss)
        elif klines is not None and len(klines) >= lookback:
            # Use ATR or high-low range as volatility proxy
            window = klines.iloc[-lookback:]
            high = window["high"] if "high" in window else window["close"]
            low = window["low"] if "low" in window else window["close"]
            stop_distance = (high - low).mean()
            price = window["close"].iloc[-1]
        else:
            # Fallback: use a small default stop distance
            stop_distance = price * 0.005 if price else 1.0
        # Calculate risk per unit
        if stop_distance == 0 or price is None:
            return min_position
        risk_amount = account_balance * risk_pct
        position_size = risk_amount / stop_distance
        # Adjust for leverage if present
        leverage = self.parameters.get("leverage", 1.0)
        position_size *= leverage
        # Cap position size to max_position
        position_size = max(min_position, min(position_size, max_position))
        return float(position_size)

    """
    Advanced breakout & momentum strategy:
    - Obsługa wolumenu
    - Trailing stop
    - Market/stop-market
    - Integracja z volatility_forecaster
    - Scalping
    """

    def __init__(
        self,
        name: str = "BreakoutStrategy",
        timeframes: List[str] = None,
        indicators: List[str] = None,
        parameters: Dict[str, Any] = None,
        vol_forecaster=None,
        **kwargs,
    ):
        if timeframes is None:
            timeframes = ["1m", "5m", "1h"]
        if indicators is None:
            indicators = ["close", "volume"]
        if parameters is None:
            parameters = {
                "lookback": 20,
                "breakout_threshold": 1.0,
                "min_periods": 20,
                "volume_mult": 2.0,
                "trailing_stop_pct": 0.8,
                "scalp_pct": 0.3,
                "use_scalping": True,
                "use_trailing": True,
                "use_market_order": True,
            }
        super().__init__(name=name, timeframes=timeframes)
        self.indicators = indicators
        self.parameters = parameters
        self.position = None
        self.last_signal = None
        self.trailing_stop = None
        self.vol_forecaster = vol_forecaster

    def analyze(
        self,
        symbol: str,
        klines: pd.DataFrame,
        indicators: Dict[str, pd.Series],
        timeframe: str,
    ) -> Dict[str, Any]:
        results = {"signals": [], "metrics": {}, "analysis": {}}
        try:
            lookback = self.parameters.get("lookback", 20)
            threshold = self.parameters.get("breakout_threshold", 1.0)
            volume_mult = self.parameters.get("volume_mult", 2.0)
            use_scalping = self.parameters.get("use_scalping", True)
            scalp_pct = self.parameters.get("scalp_pct", 0.3)
            use_trailing = self.parameters.get("use_trailing", True)
            trailing_stop_pct = self.parameters.get("trailing_stop_pct", 0.8)
            use_market_order = self.parameters.get("use_market_order", True)
            if len(klines) < lookback:
                logger.warning(f"{symbol}: Not enough data for breakout analysis.")
                return results
            window = klines.iloc[-lookback:]
            max_price = window["close"].max()
            min_price = window["close"].min()
            current_price = klines["close"].iloc[-1]
            current_vol = klines["volume"].iloc[-1] if "volume" in klines else 0
            avg_vol = window["volume"].mean() if "volume" in klines else 0
            # Integracja z volatility_forecaster
            predicted_vol = None
            if self.vol_forecaster:
                try:
                    predicted_vol = self.vol_forecaster.forecast_volatility(klines)
                except Exception as e:
                    logger.warning(f"Volatility forecaster error: {e}")
            signal = None
            # Breakout z potwierdzeniem wolumenu i zmienności
            breakout_long = (
                current_price > max_price * (1 + threshold / 100)
                and current_vol > avg_vol * volume_mult
                and (predicted_vol is None or predicted_vol > 0.01)
            )
            breakout_short = (
                current_price < min_price * (1 - threshold / 100)
                and current_vol > avg_vol * volume_mult
                and (predicted_vol is None or predicted_vol > 0.01)
            )
            if breakout_long:
                signal = {
                    "type": "entry",
                    "side": "buy",
                    "breakout": True,
                    "order_type": ("market" if use_market_order else "stop-market"),
                    "volume": current_vol,
                    "predicted_volatility": predicted_vol,
                }
                self.position = "long"
                # Trailing stop start
                if use_trailing:
                    self.trailing_stop = current_price * (1 - trailing_stop_pct / 100)
            elif breakout_short:
                signal = {
                    "type": "entry",
                    "side": "sell",
                    "breakout": True,
                    "order_type": ("market" if use_market_order else "stop-market"),
                    "volume": current_vol,
                    "predicted_volatility": predicted_vol,
                }
                self.position = "short"
                if use_trailing:
                    self.trailing_stop = current_price * (1 + trailing_stop_pct / 100)
            # Scalping/mikro-wybicia
            if use_scalping and signal is None:
                scalp_move = max_price * (scalp_pct / 100)
                if (
                    current_price > max_price
                    and current_price - max_price < scalp_move
                    and current_vol > avg_vol * volume_mult
                ):
                    signal = {
                        "type": "scalp",
                        "side": "buy",
                        "order_type": "market",
                        "volume": current_vol,
                        "scalp": True,
                    }
                elif (
                    current_price < min_price
                    and min_price - current_price < scalp_move
                    and current_vol > avg_vol * volume_mult
                ):
                    signal = {
                        "type": "scalp",
                        "side": "sell",
                        "order_type": "market",
                        "volume": current_vol,
                        "scalp": True,
                    }
            # Trailing stop logic
            if use_trailing and self.position == "long" and self.trailing_stop:
                if current_price < self.trailing_stop:
                    signal = {"type": "exit", "reason": "trailing_stop_hit"}
                    self.position = None
                    self.trailing_stop = None
            if use_trailing and self.position == "short" and self.trailing_stop:
                if current_price > self.trailing_stop:
                    signal = {"type": "exit", "reason": "trailing_stop_hit"}
                    self.position = None
                    self.trailing_stop = None
            if signal:
                self.last_signal = signal["type"]
                results["signals"].append(signal)
            results["metrics"] = {
                "max_price": max_price,
                "min_price": min_price,
                "current_price": current_price,
                "current_vol": current_vol,
                "avg_vol": avg_vol,
                "predicted_volatility": predicted_vol,
            }
            trend = (
                "up"
                if current_price > max_price
                else ("down" if current_price < min_price else "range")
            )
            results["analysis"] = {"trend": trend}
        except Exception as e:
            logger.error(f"BreakoutStrategy error: {e}")
        return results
        try:
            lookback = self.parameters.get("lookback", 20)
            threshold = self.parameters.get("breakout_threshold", 1.0)
            if len(klines) < lookback:
                logger.warning(f"{symbol}: Not enough data for breakout analysis.")
                return results
            window = klines["close"].iloc[-lookback:]
            max_price = window.max()
            min_price = window.min()
            current_price = klines["close"].iloc[-1]
            signal = None
            if current_price > max_price * (1 + threshold / 100):
                signal = {
                    "type": "entry",
                    "side": "buy",
                    "breakout": True,
                }
                self.position = "long"
            elif current_price < min_price * (1 - threshold / 100):
                signal = {
                    "type": "entry",
                    "side": "sell",
                    "breakout": True,
                }
                self.position = "short"
            elif current_price < max_price or current_price > min_price:
                signal = {
                    "type": "exit",
                    "reason": "breakout_reversal",
                }
                self.position = None
            if signal:
                self.last_signal = signal["type"]
                results["signals"].append(signal)
            results["metrics"] = {
                "max_price": max_price,
                "min_price": min_price,
                "current_price": current_price,
            }
            if current_price > max_price:
                trend = "up"
            elif current_price < min_price:
                trend = "down"
            else:
                trend = "range"
            results["analysis"] = {"trend": trend}
        except Exception as e:
            logger.error(f"BreakoutStrategy error: {e}")
        return results

    def validate(self) -> List[str]:
        """
        Validate strategy configuration and parameters.
        Returns:
            List[str]: List of validation error messages.
        """
        errors = super().validate()
        if self.parameters.get("lookback", 0) < 10:
            errors.append(f"{self.__class__.__name__}: lookback must be >= 10")
        if self.parameters.get("breakout_threshold", 0) <= 0:
            errors.append(f"{self.__class__.__name__}: breakout_threshold must be > 0")
        return errors

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize strategy state to a dictionary.
        Returns:
            Dict[str, Any]: State dict.
        """
        return {
            "symbol": getattr(self, "symbol", None),
            "lookback": self.parameters.get("lookback", None),
            "breakout_threshold": self.parameters.get("breakout_threshold", None),
            "position": getattr(self, "position", None),
            "last_signal": getattr(self, "last_signal", None),
        }
