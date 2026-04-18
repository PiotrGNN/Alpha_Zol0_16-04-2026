from typing import Any, Dict, List, Optional

# flake8: noqa: E501  # long lines in strategy logic are fine

import os
import pandas as pd
from strategies.base import Strategy
from utils.logger import setup_logger
import logging

setup_logger()
logger = logging.getLogger(__name__)


class MomentumStrategy(Strategy):
    """
    Advanced momentum strategy: obsługa wolumenu, trailing stop,
    market/stop-market, integracja z volatility_forecaster, scalping.
    """

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        try:
            raw = os.environ.get(name)
            if raw is None:
                return bool(default)
            return str(raw).strip().lower() in ("1", "true", "yes", "on")
        except Exception:
            return bool(default)

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        try:
            raw = os.environ.get(name)
            if raw is None or str(raw).strip() == "":
                return float(default)
            return float(raw)
        except Exception:
            return float(default)

    def __init__(
        self,
        name: str = "Momentum",
        timeframes: Optional[List[str]] = None,
        indicators: Optional[List[str]] = None,
        parameters: Optional[Dict[str, Any]] = None,
        vol_forecaster: Optional[Any] = None,
    ):
        super().__init__(name=name, timeframes=timeframes)
        if indicators is None:
            indicators = ["close", "volume"]
        if timeframes is None:
            timeframes = ["1m", "5m", "1h"]
        if parameters is None:
            parameters = {
                "lookback": 20,
                "entry_threshold": 1.0,
                "exit_threshold": 0.5,
                "min_periods": 20,
                "volume_mult": 2.0,
                "trailing_stop_pct": 0.8,
                "scalp_pct": 0.3,
                "use_scalping": False,
                "use_trailing": True,
                "use_market_order": True,
                "require_trend_alignment": False,
                "min_z_momentum": 0.5,
                "min_vol_ratio": 0.7,
                "score_entry_requires_volume": True,
                "exhaustion_filter_enable": True,
                "exhaustion_z_extreme": 3.0,
                "exhaustion_max_ext_pct": 0.0025,
                "exhaustion_vol_spike_ratio": 3.0,
                "exhaustion_spike_min_z": 2.0,
            }
        try:
            parameters = dict(parameters or {})
        except Exception:
            parameters = {}
        parameters["signal_score_threshold"] = self._env_float(
            "MOMENTUM_SIGNAL_SCORE_THRESHOLD",
            float(parameters.get("signal_score_threshold", 0.45)),
        )
        parameters["min_z_momentum"] = self._env_float(
            "MOMENTUM_MIN_Z_MOMENTUM",
            float(parameters.get("min_z_momentum", 0.5)),
        )
        parameters["min_vol_ratio"] = self._env_float(
            "MOMENTUM_MIN_VOL_RATIO",
            float(parameters.get("min_vol_ratio", 0.7)),
        )
        parameters["require_trend_alignment"] = self._env_bool(
            "MOMENTUM_REQUIRE_TREND_ALIGNMENT",
            bool(parameters.get("require_trend_alignment", False)),
        )
        parameters["score_entry_requires_volume"] = self._env_bool(
            "MOMENTUM_SCORE_ENTRY_REQUIRES_VOLUME",
            bool(parameters.get("score_entry_requires_volume", True)),
        )
        parameters["use_scalping"] = self._env_bool(
            "MOMENTUM_USE_SCALPING",
            bool(parameters.get("use_scalping", False)),
        )
        parameters["exhaustion_filter_enable"] = self._env_bool(
            "MOMENTUM_EXHAUSTION_FILTER_ENABLE",
            bool(parameters.get("exhaustion_filter_enable", True)),
        )
        parameters["exhaustion_z_extreme"] = self._env_float(
            "MOMENTUM_EXHAUSTION_Z_EXTREME",
            float(parameters.get("exhaustion_z_extreme", 3.0)),
        )
        parameters["exhaustion_max_ext_pct"] = self._env_float(
            "MOMENTUM_EXHAUSTION_MAX_EXT_PCT",
            float(parameters.get("exhaustion_max_ext_pct", 0.0025)),
        )
        parameters["exhaustion_vol_spike_ratio"] = self._env_float(
            "MOMENTUM_EXHAUSTION_VOL_SPIKE_RATIO",
            float(parameters.get("exhaustion_vol_spike_ratio", 3.0)),
        )
        parameters["exhaustion_spike_min_z"] = self._env_float(
            "MOMENTUM_EXHAUSTION_SPIKE_MIN_Z",
            float(parameters.get("exhaustion_spike_min_z", 2.0)),
        )
        self.indicators = indicators
        self.parameters = parameters
        self.position = None
        self.last_signal = None
        self.trailing_stop = None
        self.vol_forecaster = vol_forecaster
        self.symbol = None  # for to_dict

    def calculate_position_size(self, signal, account_balance):
        risk_per_trade = self.parameters.get("risk_per_trade", 0.01)
        return account_balance * risk_per_trade

    def analyze(
        self,
        symbol: str,
        klines: pd.DataFrame,
        indicators: Dict[str, pd.Series],
        timeframe: str,
    ) -> Dict[str, Any]:
        # ⬆️ optimized for performance:
        # use local vars, vectorized ops, minimize object creation
        results = {"signals": [], "metrics": {}, "analysis": {}}
        try:
            params = self.parameters
            lookback = params.get("lookback", 20)
            entry_threshold = params.get("entry_threshold", 1.0)
            volume_mult = params.get("volume_mult", 2.0)
            use_scalping = params.get("use_scalping", True)
            use_trailing = params.get("use_trailing", True)
            trailing_stop_pct = params.get("trailing_stop_pct", 0.8)
            use_market_order = params.get("use_market_order", True)
            require_trend_alignment = bool(params.get("require_trend_alignment", True))
            min_z_momentum = float(params.get("min_z_momentum", 0.8))
            min_vol_ratio = float(params.get("min_vol_ratio", 0.9))
            score_entry_requires_volume = bool(
                params.get("score_entry_requires_volume", True)
            )
            exhaustion_filter_enable = bool(params.get("exhaustion_filter_enable", True))
            exhaustion_z_extreme = float(params.get("exhaustion_z_extreme", 3.0))
            exhaustion_max_ext_pct = max(
                0.0,
                float(params.get("exhaustion_max_ext_pct", 0.0025)),
            )
            exhaustion_vol_spike_ratio = max(
                0.0,
                float(params.get("exhaustion_vol_spike_ratio", 3.0)),
            )
            exhaustion_spike_min_z = max(
                0.0,
                float(params.get("exhaustion_spike_min_z", 2.0)),
            )
            self.symbol = symbol
            if klines is None or klines.shape[0] < lookback:
                logger.warning(f"{symbol}: Not enough data for momentum analysis.")
                return results
            window = klines.iloc[-lookback:]
            close = window["close"]
            volume = (
                window["volume"] if "volume" in window else pd.Series([0] * lookback)
            )
            momentum = close.iloc[-1] - close.iloc[0]
            current_price = close.iloc[-1]
            current_vol = klines["volume"].iloc[-1] if "volume" in klines else 0
            avg_vol = volume.mean() if "volume" in klines else 0
            predicted_vol = None
            if self.vol_forecaster:
                try:
                    predicted_vol = self.vol_forecaster.forecast_volatility(klines)
                except Exception as e:
                    logger.warning(f"Volatility forecaster error: {e}")

            # --- additional engineered features ---
            atr = None
            try:
                if "high" in window and "low" in window:
                    prev_close = window["close"].shift(1)
                    tr = pd.concat(
                        [
                            (window["high"] - window["low"]).abs(),
                            (window["high"] - prev_close).abs(),
                            (window["low"] - prev_close).abs(),
                        ],
                        axis=1,
                    ).max(axis=1)
                    atr = tr.rolling(window=min(14, len(tr))).mean().iloc[-1]
            except Exception:
                atr = None

            sma_short_p = int(params.get("sma_short", max(5, lookback // 2)))
            sma_long_p = int(params.get("sma_long", max(20, lookback)))
            sma_short = (
                window["close"].rolling(window=sma_short_p).mean().iloc[-1]
                if len(window) >= sma_short_p
                else None
            )
            sma_long = (
                window["close"].rolling(window=sma_long_p).mean().iloc[-1]
                if len(window) >= sma_long_p
                else None
            )

            std_close = window["close"].std() if len(window) > 1 else 0.0
            z_momentum = (momentum / std_close) if std_close and std_close > 0 else 0.0

            vol_ratio = (current_vol / avg_vol) if avg_vol and avg_vol > 0 else 0.0
            # normalize components (bounded contributions)
            z_norm = max(min(z_momentum / 3.0, 1.0), -1.0)
            vol_norm = max(min(vol_ratio / 2.0, 1.0), 0.0)
            atr_norm = 0.0
            if atr and current_price:
                atr_norm = min((atr / max(current_price, 1e-8)) / 0.01, 1.0)

            # composite, signed signal score (tunable via parameters)
            signal_score = z_norm * 0.6 + vol_norm * 0.25 + atr_norm * 0.15
            if momentum < 0:
                signal_score = -abs(signal_score)
            score_threshold = float(params.get("signal_score_threshold", 0.45))

            signal = None
            trend_up = (
                sma_short is not None and sma_long is not None and float(sma_short) > float(sma_long)
            )
            trend_down = (
                sma_short is not None and sma_long is not None and float(sma_short) < float(sma_long)
            )
            vol_ok = bool(vol_ratio >= max(0.0, float(min_vol_ratio)))
            z_buy_ok = bool(z_momentum >= abs(float(min_z_momentum)))
            z_sell_ok = bool(z_momentum <= -abs(float(min_z_momentum)))
            price_extension_pct = 0.0
            try:
                if sma_short and float(sma_short) != 0:
                    price_extension_pct = (
                        float(current_price) - float(sma_short)
                    ) / float(sma_short)
            except Exception:
                price_extension_pct = 0.0
            buy_exhausted = False
            sell_exhausted = False
            if exhaustion_filter_enable:
                try:
                    buy_exhausted = (
                        (
                            z_momentum >= float(exhaustion_z_extreme)
                            and price_extension_pct >= float(exhaustion_max_ext_pct)
                        )
                        or (
                            vol_ratio >= float(exhaustion_vol_spike_ratio)
                            and z_momentum <= float(exhaustion_spike_min_z)
                        )
                    )
                    sell_exhausted = (
                        (
                            z_momentum <= -float(exhaustion_z_extreme)
                            and price_extension_pct <= -float(exhaustion_max_ext_pct)
                        )
                        or (
                            vol_ratio >= float(exhaustion_vol_spike_ratio)
                            and z_momentum >= -float(exhaustion_spike_min_z)
                        )
                    )
                except Exception:
                    buy_exhausted = False
                    sell_exhausted = False
            buy_quality_ok = z_buy_ok and (
                (not require_trend_alignment) or trend_up
            ) and (vol_ok or (not score_entry_requires_volume)) and (not buy_exhausted)
            sell_quality_ok = z_sell_ok and (
                (not require_trend_alignment) or trend_down
            ) and (vol_ok or (not score_entry_requires_volume)) and (not sell_exhausted)

            buy_by_score = signal_score > score_threshold and buy_quality_ok
            sell_by_score = signal_score < -score_threshold and sell_quality_ok

            buy_by_core = (
                momentum > entry_threshold
                and current_vol > avg_vol * volume_mult
                and (predicted_vol is None or predicted_vol > 0.01)
                and buy_quality_ok
            )
            sell_by_core = (
                momentum < -entry_threshold
                and current_vol > avg_vol * volume_mult
                and (predicted_vol is None or predicted_vol > 0.01)
                and sell_quality_ok
            )

            if buy_by_core or buy_by_score:
                signal = {
                    "type": "entry",
                    "side": "buy",
                    "momentum": momentum,
                    "signal_score": signal_score,
                    "atr": atr,
                    "sma_short": sma_short,
                    "sma_long": sma_long,
                    "z_momentum": z_momentum,
                    "order_type": ("market" if use_market_order else "stop-market"),
                    "volume": current_vol,
                    "predicted_volatility": predicted_vol,
                }
                self.position = "long"
                if use_trailing:
                    self.trailing_stop = current_price * (1 - trailing_stop_pct / 100)
            elif sell_by_core or sell_by_score:
                signal = {
                    "type": "entry",
                    "side": "sell",
                    "momentum": momentum,
                    "signal_score": signal_score,
                    "atr": atr,
                    "sma_short": sma_short,
                    "sma_long": sma_long,
                    "z_momentum": z_momentum,
                    "order_type": ("market" if use_market_order else "stop-market"),
                    "volume": current_vol,
                    "predicted_volatility": predicted_vol,
                }
                self.position = "short"
                if use_trailing:
                    self.trailing_stop = current_price * (1 + trailing_stop_pct / 100)
            if use_scalping and signal is None:
                if (
                    momentum > 0
                    and momentum < entry_threshold
                    and current_vol > avg_vol * volume_mult
                ):
                    signal = {
                        "type": "scalp",
                        "side": "buy",
                        "order_type": "market",
                        "volume": current_vol,
                        "scalp": True,
                        "signal_score": signal_score,
                    }
                elif (
                    momentum < 0
                    and abs(momentum) < entry_threshold
                    and current_vol > avg_vol * volume_mult
                ):
                    signal = {
                        "type": "scalp",
                        "side": "sell",
                        "order_type": "market",
                        "volume": current_vol,
                        "scalp": True,
                        "signal_score": signal_score,
                    }
            if not signal:
                if use_trailing and self.position == "long" and self.trailing_stop:
                    if current_price < self.trailing_stop:
                        signal = {
                            "type": "exit",
                            "reason": "trailing_stop_hit",
                        }
                        self.position = None
                        self.trailing_stop = None
                if use_trailing and self.position == "short" and self.trailing_stop:
                    if current_price > self.trailing_stop:
                        signal = {
                            "type": "exit",
                            "reason": "trailing_stop_hit",
                        }
                        self.position = None
                        self.trailing_stop = None
            # Bias vote when no actionable signal (keeps vote stream alive)
            if not signal:
                try:
                    import os

                    bias_enable = os.environ.get("MOMENTUM_BIAS_ENABLE", "1") == "1"
                except Exception:
                    bias_enable = True
                try:
                    bias_threshold = float(
                        os.environ.get("MOMENTUM_BIAS_THRESHOLD", "0.5")
                    )
                except Exception:
                    bias_threshold = 0.5
                if bias_enable and abs(momentum) >= bias_threshold:
                    side = "buy" if momentum > 0 else "sell"
                    signal = {
                        "type": "bias",
                        "side": side,
                        "momentum": momentum,
                        "signal_score": signal_score,
                        "reason": "momentum_bias",
                    }
            if signal:
                self.last_signal = signal["type"]
                results["signals"].append(signal)
            results["metrics"] = {
                "momentum": momentum,
                "current_price": current_price,
                "current_vol": current_vol,
                "avg_vol": avg_vol,
                "predicted_volatility": predicted_vol,
                "atr": atr,
                "sma_short": sma_short,
                "sma_long": sma_long,
                "z_momentum": z_momentum,
                "vol_ratio": vol_ratio,
                "signal_score": signal_score,
                "price_extension_pct": price_extension_pct,
                "buy_exhausted": bool(buy_exhausted),
                "sell_exhausted": bool(sell_exhausted),
            }
            trend = "up" if momentum > 0 else ("down" if momentum < 0 else "range")
            results["analysis"] = {"trend": trend}
        except Exception as e:
            logger.error(f"MomentumStrategy error: {e}")
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
        # validate optional new params
        sma_short = self.parameters.get("sma_short")
        sma_long = self.parameters.get("sma_long")
        if sma_short is not None and int(sma_short) < 3:
            errors.append(f"{self.__class__.__name__}: sma_short must be >= 3")
        if sma_long is not None and int(sma_long) < 5:
            errors.append(f"{self.__class__.__name__}: sma_long must be >= 5")
        sst = self.parameters.get("signal_score_threshold")
        if sst is not None:
            try:
                sstf = float(sst)
                if sstf <= 0 or sstf >= 1.5:
                    errors.append(
                        f"{self.__class__.__name__}: signal_score_threshold out of range"  # noqa: E501
                    )
            except Exception:
                errors.append(
                    f"{self.__class__.__name__}: signal_score_threshold must be numeric"
                )
        min_z = self.parameters.get("min_z_momentum")
        if min_z is not None:
            try:
                min_z_f = float(min_z)
                if min_z_f < 0 or min_z_f > 5:
                    errors.append(
                        f"{self.__class__.__name__}: min_z_momentum out of range"
                    )
            except Exception:
                errors.append(
                    f"{self.__class__.__name__}: min_z_momentum must be numeric"
                )
        min_vol_ratio = self.parameters.get("min_vol_ratio")
        if min_vol_ratio is not None:
            try:
                min_vol_ratio_f = float(min_vol_ratio)
                if min_vol_ratio_f < 0 or min_vol_ratio_f > 5:
                    errors.append(
                        f"{self.__class__.__name__}: min_vol_ratio out of range"
                    )
            except Exception:
                errors.append(
                    f"{self.__class__.__name__}: min_vol_ratio must be numeric"
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
            "position": getattr(self, "position", None),
            "last_signal": getattr(self, "last_signal", None),
        }
