"""
ScalperStrategy — very short lookback scalper for rapid TP hits.
- Fast, supports scalar `last_row` fast-path.
- Uses short-period RSI + narrow BB check to trigger quick entries.
"""

from typing import Any, Dict
import pandas as pd
from strategies.base import Strategy


class ScalperStrategy(Strategy):
    supports_fast_analyze = True

    def __init__(
        self,
        name: str = "Scalper",
        parameters: Dict[str, Any] | None = None,
    ):
        if parameters is None:
            parameters = {
                "rsi_period": 6,
                "bb_period": 10,
                "bb_std": 1.5,
                "entry_rsi_low": 25,
                "entry_rsi_high": 75,
                "min_periods": 6,
            }
        super().__init__(name=name, timeframes=["1m"])
        self.parameters = parameters

    def _rsi_scalar(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-12)
        return 100 - (100 / (1 + rs))

    def calculate_position_size(self, balance: float, price: float, **kwargs) -> float:
        """Simple position sizing for scalper: small fixed-risk fraction.
        Returns base-asset amount (rounded). Keeps minimal floor to avoid zero.
        """
        # default risk: 0.5% of balance allocated to a scalper trade
        risk_frac = float(self.parameters.get("risk_per_trade", 0.005))
        target_notional = balance * risk_frac
        amount = target_notional / max(price, 1e-8)
        min_pos = float(self.parameters.get("min_position", 0.001))
        return round(max(amount, min_pos), 6)

    def analyze(
        self,
        symbol: str,
        klines,
        indicators: Dict[str, pd.Series],
        timeframe: str,
    ):
        """Fast scalar analyze supported. Returns quick `entry` signals only."""
        params = self.parameters
        rsi_p = int(params.get("rsi_period", 6))
        entry_low = float(params.get("entry_rsi_low", 25))
        entry_high = float(params.get("entry_rsi_high", 75))

        # Fast-path: caller provides last_indicators (scalar path)
        if isinstance(klines, dict) and "last_row" in klines:
            last_inds = klines.get("last_indicators", {}) or {}
            # Try to use cached indicators if present
            rsi_val = last_inds.get("rsi")
            if rsi_val is None:
                # fallback default when RSI not provided by caller
                rsi_val = 50.0
            # Entry logic: RSI exhaustion -> quick scalping entries
            signals = []
            if rsi_val <= entry_low:
                signals.append({"type": "entry", "side": "buy", "rsi": rsi_val})
            elif rsi_val >= entry_high:
                signals.append({"type": "entry", "side": "sell", "rsi": rsi_val})
            return {"signals": signals}

        # Fallback DataFrame path (slower)
        try:
            df = klines.copy()
            close = df["close"].astype(float)
            rsi = self._rsi_scalar(close, rsi_p)
            last = len(df) - 1
            rsi_val = float(rsi.iat[last]) if not rsi.empty else 50.0
            signals = []
            if rsi_val <= entry_low:
                signals.append({"type": "entry", "side": "buy", "rsi": rsi_val})
            elif rsi_val >= entry_high:
                signals.append({"type": "entry", "side": "sell", "rsi": rsi_val})
            return {"signals": signals}
        except Exception:
            return {"signals": []}
