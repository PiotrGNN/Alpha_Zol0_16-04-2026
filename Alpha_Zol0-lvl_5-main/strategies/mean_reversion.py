"""
Mean Reversion Strategy Implementation
"""

import os
from typing import Any, Dict, List, Optional

import pandas as pd
from strategies.base import Strategy
from utils.logger import setup_logger
import logging
import time

setup_logger()
logger = logging.getLogger(__name__)


class MeanReversionStrategy(Strategy):
    # opt-in flag used by backtest harness to enable fast scalar analyze path
    supports_fast_analyze = True

    @staticmethod
    def _clamp(lower: float, upper: float, value: float) -> float:
        return max(float(lower), min(float(upper), float(value)))

    def calculate_position_size(
        self,
        balance: float,
        price: float,
        risk_per_trade: float = 0.01,
        atr: Optional[float] = None,
        max_position_pct: float = 0.2,
        min_position: float = 0.001,
        **kwargs,
    ) -> float:
        """
        Advanced position sizing for mean reversion:
        - Uses risk per trade, ATR (if available), and max position size.
        - Ensures position is within min/max bounds.
        Args:
            balance (float): Account balance (quote currency).
            price (float): Current asset price.
            risk_per_trade (float): Fraction of balance to risk per trade.
            atr (float, optional):
                Average True Range for volatility-based sizing.
            atr (float, optional):
                Average True Range for volatility-based sizing.
            max_position_pct (float): Max % of balance to allocate.
            min_position (float): Minimal allowed position size.
        Returns:
            float: Calculated position size (in base currency).
        """
        # Risk-based sizing
        risk_amount = balance * risk_per_trade
        if atr is not None and atr > 0:
            # Volatility-based sizing (ATR stop)
            stop_loss = atr * 2  # e.g. 2x ATR stop
            position_size = risk_amount / stop_loss
        else:
            # Fallback: fixed % of balance
            position_size = risk_amount / max(price, 1e-8)
        # Max position cap
        max_position = balance * max_position_pct / max(price, 1e-8)
        position_size = min(position_size, max_position)
        # Min position floor
        position_size = max(position_size, min_position)
        return round(position_size, 6)

    # ...existing code...
    """
    Implements a robust mean reversion trading strategy with full validation
    and error handling.
    """

    def __init__(
        self,
        name: str = "MeanReversion",
        rsi_period: int = 14,
        bb_period: int = 20,
        bb_std: float = 2.0,
        trend_ema_fast: int = 50,
        trend_ema_slow: int = 200,
        risk_per_trade: float = 0.01,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> None:
        if parameters is None:
            parameters = {
                "lookback": 20,
                "entry_threshold": 2.0,
                "exit_threshold": 0.5,
                "min_periods": 20,
                "rsi_period": rsi_period,
                "bb_period": bb_period,
                "bb_std": bb_std,
                "trend_ema_fast": trend_ema_fast,
                "trend_ema_slow": trend_ema_slow,
                "risk_per_trade": risk_per_trade,
                "trigger_variant": "boundary",
                "bb_boundary_pct": 0.001,
                "rsi_boundary_buffer": 5.0,
            }
        indicators = ["close"]
        timeframes = ["1h"]
        super().__init__(name=name, timeframes=timeframes)
        self.indicators = indicators
        self.parameters = parameters
        self.position = None
        self.last_signal = None
        # caches for incremental / repeated indicator computations
        # keys: span or period -> (series_id, pandas.Series)
        self._ewm_cache = {}
        self._rsi_cache = {}

    def calculate_rsi(self, series, period):
        # Use Wilder's smoothing (EWMA) which is significantly faster than
        # rolling-window means for large series. Cache results by (id(series), period).
        sid = id(series)
        key = (sid, int(period))
        cached = self._rsi_cache.get(key)
        if cached is not None:
            return cached
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        # Wilder's RSI uses exponential smoothing (alpha = 1/period)
        # use adjust=False for recursive EMA (fast, stable)
        avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
        # avoid division by zero
        rs = avg_gain / avg_loss.replace(0, 1e-12)
        rsi = 100 - (100 / (1 + rs))
        try:
            self._rsi_cache[key] = rsi
        except Exception:
            pass
        return rsi

    def ewm_update(self, prev_ema: float, new_val: float, span: int) -> float:
        """Compute next EMA value from prev_ema and new sample using
        alpha = 2/(span+1). Returns scalar value (useful for streaming updates)."""
        alpha = 2.0 / (float(span) + 1.0)
        return alpha * float(new_val) + (1.0 - alpha) * float(prev_ema)

    def _trigger_variant(self) -> str:
        return str(self.parameters.get("trigger_variant", "boundary") or "boundary")

    def _bb_boundary_pct(self) -> float:
        env_value = os.environ.get("MR_BOUNDARY_BB_PCT_OVERRIDE")
        if env_value not in (None, ""):
            try:
                return max(0.0, float(env_value))
            except (TypeError, ValueError):
                pass
        try:
            value = float(self.parameters.get("bb_boundary_pct", 0.001) or 0.0)
        except (TypeError, ValueError):
            value = 0.001
        return max(0.0, value)

    def _rsi_boundary_buffer(self) -> float:
        env_value = os.environ.get("MR_BOUNDARY_RSI_BUFFER_OVERRIDE")
        if env_value not in (None, ""):
            try:
                return max(0.0, float(env_value))
            except (TypeError, ValueError):
                pass
        try:
            value = float(self.parameters.get("rsi_boundary_buffer", 5.0) or 0.0)
        except (TypeError, ValueError):
            value = 5.0
        return max(0.0, value)

    def _adaptive_boundary_context(
        self,
        close: float,
        bb_upper: float,
        bb_lower: float,
    ) -> Dict[str, float]:
        safe_close = abs(float(close))
        if safe_close <= 1e-12:
            vol_ratio = 0.0
        else:
            vol_ratio = max(
                0.0,
                (float(bb_upper) - float(bb_lower)) / safe_close,
            )
        bb_boundary_pct = self._clamp(0.001, 0.004, 0.3 * vol_ratio)
        rsi_buffer = self._clamp(5.0, 12.0, 5.0 + 5.0 * vol_ratio)
        return {
            "vol_ratio": float(vol_ratio),
            "bb_boundary_pct": float(bb_boundary_pct),
            "rsi_buffer": float(rsi_buffer),
        }

    def _boundary_snapshot(
        self,
        close: float,
        bb_upper: float,
        bb_lower: float,
    ) -> Dict[str, float]:
        boundary = self._adaptive_boundary_context(
            close=close,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
        )
        return {
            **boundary,
            "buy_price_boundary": float(bb_lower) * (1.0 + boundary["bb_boundary_pct"]),
            "sell_price_boundary": float(bb_upper)
            * (1.0 - boundary["bb_boundary_pct"]),
            "buy_rsi_threshold": 30.0 + boundary["rsi_buffer"],
            "sell_rsi_threshold": 70.0 - boundary["rsi_buffer"],
        }

    def _price_boundary_buy(
        self,
        close: float,
        bb_upper: float,
        bb_lower: float,
    ) -> float:
        boundary = self._boundary_snapshot(
            close=close,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
        )
        return boundary["buy_price_boundary"]

    def _price_boundary_sell(
        self,
        close: float,
        bb_upper: float,
        bb_lower: float,
    ) -> float:
        boundary = self._boundary_snapshot(
            close=close,
            bb_upper=bb_upper,
            bb_lower=bb_lower,
        )
        return boundary["sell_price_boundary"]

    def _buy_trigger(
        self,
        close: float,
        bb_lower: float,
        rsi: float,
        bb_upper: Optional[float] = None,
    ) -> bool:
        variant = self._trigger_variant()
        if variant == "strict_extreme":
            return float(close) < float(bb_lower) and float(rsi) < 30.0
        resolved_bb_upper = (
            float(bb_upper)
            if bb_upper is not None
            else (2.0 * float(close)) - float(bb_lower)
        )
        boundary = self._boundary_snapshot(
            close=close,
            bb_upper=resolved_bb_upper,
            bb_lower=bb_lower,
        )
        return (
            float(close)
            <= boundary["buy_price_boundary"]
            and float(rsi) <= boundary["buy_rsi_threshold"]
        )

    def _sell_trigger(
        self,
        close: float,
        bb_upper: float,
        rsi: float,
        bb_lower: Optional[float] = None,
    ) -> bool:
        variant = self._trigger_variant()
        if variant == "strict_extreme":
            return float(close) > float(bb_upper) and float(rsi) > 70.0
        resolved_bb_lower = (
            float(bb_lower)
            if bb_lower is not None
            else (2.0 * float(close)) - float(bb_upper)
        )
        boundary = self._boundary_snapshot(
            close=close,
            bb_upper=bb_upper,
            bb_lower=resolved_bb_lower,
        )
        return (
            float(close)
            >= boundary["sell_price_boundary"]
            and float(rsi) >= boundary["sell_rsi_threshold"]
        )

    def analyze(
        self,
        symbol: str,
        klines: pd.DataFrame,
        indicators: Dict[str, pd.Series],
        timeframe: str,
    ) -> Dict[str, Any]:
        """
        Analyze market data for mean reversion signals (Bollinger Bands, RSI,
        trend filter).
        Analyze market data for mean reversion signals (Bollinger Bands, RSI,
        trend filter).
        """
        results = {"signals": [], "metrics": {}, "analysis": {}}
        t0 = time.time()
        # Fast-path: caller provided scalar last-row + last-indicators payload to avoid
        # per-iteration DataFrame slicing in the backtester. Expect a dict with keys
        # 'last_row' and optionally 'last_indicators'. This path mirrors the full
        # analyze() logic but works on scalars and is significantly faster.
        try:
            params = self.parameters
            if isinstance(klines, dict) and "last_row" in klines:
                last_row = klines["last_row"]
                last_inds = klines.get("last_indicators", {}) or {}
                # prefer scalars from last_indicators
                # fall back to full-series indicators when needed

                def _get_scalar(name):
                    if name in last_inds:
                        return last_inds.get(name)
                    if (
                        indicators
                        and isinstance(indicators, dict)
                        and name in indicators
                    ):
                        s = indicators.get(name)
                        try:
                            return s.iat[klines.get("index", -1)]
                        except Exception:
                            return s.iloc[-1]
                    return None

                bb_mid_v = _get_scalar("bb_mid")
                bb_std_v = _get_scalar("bb_std")
                rsi_v = _get_scalar("rsi")
                ema_fast_v = _get_scalar("ema_fast")
                ema_slow_v = _get_scalar("ema_slow")

                # ensure we have scalar values to proceed
                last_close = float(last_row.get("close"))
                if bb_mid_v is None or bb_std_v is None or rsi_v is None:
                    # insufficient indicators on fast path — fall back to normal path
                    raise ValueError("missing fast-path indicators")

                bb_upper_v = bb_mid_v + params["bb_std"] * bb_std_v
                bb_lower_v = bb_mid_v - params["bb_std"] * bb_std_v
                bb_width_v = float(bb_upper_v) - float(bb_lower_v)
                price_dist_to_bb_lower_pct = None
                if float(bb_lower_v) != 0.0:
                    price_dist_to_bb_lower_pct = (
                        last_close - float(bb_lower_v)
                    ) / float(bb_lower_v)
                price_dist_to_bb_lower_std = None
                if bb_width_v != 0.0:
                    price_dist_to_bb_lower_std = (
                        last_close - float(bb_lower_v)
                    ) / float(bb_width_v)
                boundary = self._adaptive_boundary_context(
                    close=last_close,
                    bb_upper=float(bb_upper_v),
                    bb_lower=float(bb_lower_v),
                )

                # compute trend check using intermediate variables to avoid a long line
                ema_diff_v = abs(float(ema_fast_v) - float(ema_slow_v))
                ema_threshold_v = 3.0 * float(bb_std_v)
                trend_ok = ema_diff_v < ema_threshold_v
                buy_trigger = (
                    last_close
                    <= self._price_boundary_buy(
                        close=last_close,
                        bb_upper=float(bb_upper_v),
                        bb_lower=float(bb_lower_v),
                    )
                    and float(rsi_v) <= 30.0 + boundary["rsi_buffer"]
                )
                sell_trigger = (
                    last_close
                    >= self._price_boundary_sell(
                        close=last_close,
                        bb_upper=float(bb_upper_v),
                        bb_lower=float(bb_lower_v),
                    )
                    and float(rsi_v) >= 70.0 - boundary["rsi_buffer"]
                )

                signal = None
                if trend_ok and buy_trigger:
                    signal = {
                        "type": "entry",
                        "side": "buy",
                        "rsi": float(rsi_v),
                        "bb_lower": float(bb_lower_v),
                        "trigger_variant": self._trigger_variant(),
                    }
                    self.position = "long"
                elif trend_ok and sell_trigger:
                    signal = {
                        "type": "entry",
                        "side": "sell",
                        "rsi": float(rsi_v),
                        "bb_upper": float(bb_upper_v),
                        "trigger_variant": self._trigger_variant(),
                    }
                    self.position = "short"
                elif self.position and abs(last_close - float(bb_mid_v)) < float(
                    bb_std_v
                ):
                    signal = {
                        "type": "exit",
                        "reason": "mean_reversion",
                        "close": last_close,
                    }
                    self.position = None

                if signal:
                    self.last_signal = signal["type"]
                    results["signals"].append(signal)

                results["metrics"] = {
                    "rsi": float(rsi_v),
                    "bb_upper": float(bb_upper_v),
                    "bb_lower": float(bb_lower_v),
                    "bb_width": bb_width_v,
                    "price": last_close,
                    "price_dist_to_bb_lower_pct": price_dist_to_bb_lower_pct,
                    "price_dist_to_bb_lower_std": price_dist_to_bb_lower_std,
                    "ema_fast": float(ema_fast_v) if ema_fast_v is not None else None,
                    "ema_slow": float(ema_slow_v) if ema_slow_v is not None else None,
                    "trigger_variant": self._trigger_variant(),
                    "vol_ratio": boundary["vol_ratio"],
                    "bb_boundary_pct": boundary["bb_boundary_pct"],
                    "rsi_buffer": boundary["rsi_buffer"],
                    "rsi_boundary_buffer": boundary["rsi_buffer"],
                }
                results["analysis"] = {
                    "mean": float(bb_mid_v),
                    "std": float(bb_std_v),
                    "current_price": last_close,
                    "buy_price_boundary": self._price_boundary_buy(
                        close=last_close,
                        bb_upper=float(bb_upper_v),
                        bb_lower=float(bb_lower_v),
                    ),
                    "sell_price_boundary": self._price_boundary_sell(
                        close=last_close,
                        bb_upper=float(bb_upper_v),
                        bb_lower=float(bb_lower_v),
                    ),
                }
                return results

            # fallback: full DataFrame path (existing behavior)
            close = klines["close"]
            # use precomputed indicators when provided to avoid repeated rolling/ewm
            if indicators and isinstance(indicators, dict) and "bb_mid" in indicators:
                bb_mid = indicators.get("bb_mid")
                bb_std = indicators.get("bb_std")
                rsi = indicators.get("rsi")
                ema_fast = indicators.get("ema_fast")
                ema_slow = indicators.get("ema_slow")
            else:
                # Bollinger Bands (computed on the provided window)
                bb_mid = close.rolling(params["bb_period"]).mean()
                bb_std = close.rolling(params["bb_period"]).std()
                # RSI (cached when possible)
                rsi = self.calculate_rsi(close, params["rsi_period"])
                # Trend filter (EMA) — reuse cached EWM
                span_f = int(params.get("trend_ema_fast", 50))
                span_s = int(params.get("trend_ema_slow", 200))
                # helper to cache ewm by (id(series), span)

                def _ewm_cached(srs, span):
                    key = (id(srs), int(span))
                    cached = self._ewm_cache.get(key)
                    if cached is not None:
                        return cached
                    try:
                        # use recursive EMA (adjust=False) for speed
                        res = srs.ewm(span=span, adjust=False).mean()
                        self._ewm_cache[key] = res
                        return res
                    except Exception:
                        return srs.ewm(span=span, adjust=False).mean()

                ema_fast = _ewm_cached(close, span_f)
                ema_slow = _ewm_cached(close, span_s)

            bb_upper = bb_mid + params["bb_std"] * bb_std
            bb_lower = bb_mid - params["bb_std"] * bb_std

            # evaluate trend using the LAST available values only
            trend_ok = abs(ema_fast.iloc[-1] - ema_slow.iloc[-1]) < (
                3.0 * bb_std.iloc[-1]
            )  # Relaxed trend filter for scalping
            last = klines.iloc[-1]
            last_close = float(last["close"])
            last_bb_upper = float(bb_upper.iloc[-1])
            last_bb_lower = float(bb_lower.iloc[-1])
            bb_width_value = last_bb_upper - last_bb_lower
            price_dist_to_bb_lower_pct = None
            if last_bb_lower != 0.0:
                price_dist_to_bb_lower_pct = (
                    last_close - last_bb_lower
                ) / last_bb_lower
            price_dist_to_bb_lower_std = None
            if bb_width_value != 0.0:
                price_dist_to_bb_lower_std = (
                    last_close - last_bb_lower
                ) / bb_width_value
            boundary = self._adaptive_boundary_context(
                close=last_close,
                bb_upper=last_bb_upper,
                bb_lower=last_bb_lower,
            )
            buy_trigger = (
                last_close
                <= self._price_boundary_buy(
                    close=last_close,
                    bb_upper=last_bb_upper,
                    bb_lower=last_bb_lower,
                )
                and float(rsi.iloc[-1]) <= 30.0 + boundary["rsi_buffer"]
            )
            sell_trigger = (
                last_close
                >= self._price_boundary_sell(
                    close=last_close,
                    bb_upper=last_bb_upper,
                    bb_lower=last_bb_lower,
                )
                and float(rsi.iloc[-1]) >= 70.0 - boundary["rsi_buffer"]
            )
            signal = None
            # Sygnał long
            if trend_ok and buy_trigger:
                signal = {
                    "type": "entry",
                    "side": "buy",
                    "rsi": rsi.iloc[-1],
                    "bb_lower": bb_lower.iloc[-1],
                    "trigger_variant": self._trigger_variant(),
                }
                self.position = "long"
            # Sygnał short
            elif trend_ok and sell_trigger:
                signal = {
                    "type": "entry",
                    "side": "sell",
                    "rsi": rsi.iloc[-1],
                    "bb_upper": bb_upper.iloc[-1],
                    "trigger_variant": self._trigger_variant(),
                }
                self.position = "short"
            # Sygnał wyjścia (powrót do średniej)
            elif (
                self.position and abs(last["close"] - bb_mid.iloc[-1]) < bb_std.iloc[-1]
            ):
                signal = {
                    "type": "exit",
                    "reason": "mean_reversion",
                    "close": last["close"],
                }
                self.position = None
            if signal:
                self.last_signal = signal["type"]
                results["signals"].append(signal)
            results["metrics"] = {
                "rsi": rsi.iloc[-1],
                "bb_upper": bb_upper.iloc[-1],
                "bb_lower": bb_lower.iloc[-1],
                "bb_width": bb_width_value,
                "price": last_close,
                "price_dist_to_bb_lower_pct": price_dist_to_bb_lower_pct,
                "price_dist_to_bb_lower_std": price_dist_to_bb_lower_std,
                "ema_fast": ema_fast.iloc[-1],
                "ema_slow": ema_slow.iloc[-1],
                "trigger_variant": self._trigger_variant(),
                "vol_ratio": boundary["vol_ratio"],
                "bb_boundary_pct": boundary["bb_boundary_pct"],
                "rsi_buffer": boundary["rsi_buffer"],
                "rsi_boundary_buffer": boundary["rsi_buffer"],
            }
            results["analysis"] = {
                "mean": bb_mid.iloc[-1],
                "std": bb_std.iloc[-1],
                "current_price": last["close"],
                "buy_price_boundary": self._price_boundary_buy(
                    close=last_close,
                    bb_upper=last_bb_upper,
                    bb_lower=last_bb_lower
                ),
                "sell_price_boundary": self._price_boundary_sell(
                    close=last_close,
                    bb_upper=last_bb_upper,
                    bb_lower=last_bb_lower
                ),
            }
        except Exception as e:
            logger.error(f"MeanReversionStrategy error: {e}")
        finally:
            elapsed = time.time() - t0
            if elapsed > 0.01:
                logger.debug(
                    "MeanReversion.analyze elapsed=%.4fs rows=%d",
                    elapsed,
                    len(klines),
                )
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
        if self.parameters.get("entry_threshold", 0) <= 0:
            errors.append(f"{self.__class__.__name__}: entry_threshold must be > 0")
        if self.parameters.get("exit_threshold", 0) < 0:
            errors.append(f"{self.__class__.__name__}: exit_threshold must be >= 0")
        if self._trigger_variant() not in {"boundary", "strict_extreme"}:
            errors.append(
                (
                    f"{self.__class__.__name__}: trigger_variant must be "
                    "boundary or strict_extreme"
                )
            )
        if self._bb_boundary_pct() < 0:
            errors.append(f"{self.__class__.__name__}: bb_boundary_pct must be >= 0")
        if self._rsi_boundary_buffer() < 0:
            errors.append(
                f"{self.__class__.__name__}: rsi_boundary_buffer must be >= 0"
            )
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
            "entry_threshold": self.parameters.get("entry_threshold", None),
            "exit_threshold": self.parameters.get("exit_threshold", None),
            "trigger_variant": self._trigger_variant(),
            "bb_boundary_pct": self._bb_boundary_pct(),
            "rsi_boundary_buffer": self._rsi_boundary_buffer(),
            "position": getattr(self, "position", None),
            "last_signal": getattr(self, "last_signal", None),
        }
