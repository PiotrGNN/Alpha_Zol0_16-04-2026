"""
# ✅ Completed by ZoL0-FIXER — 2025-07-29
# Description: Completed TimeAdvantageEngine with robust entry analysis,
# docstrings, and type hints.
# time_advantage.py – TimeAdvantageEngine:
# analiza optymalnego wejścia w pozycję
"""

import logging
from typing import Dict, List


class TimeAdvantageEngine:
    """
    Engine for analyzing optimal entry timing and latency in trading.
    """

    def __init__(self):
        """
        Initialize the TimeAdvantageEngine.
        """
        self.logger = logging.getLogger(__name__)

    def analyze_entry(
        self,
        ohlcv_seq: List[Dict],
        entry_tick: int = 0,
        horizon: int = 3,
        signal_time: float = None,
        execution_time: float = None,
    ) -> Dict:
        """
        Compare entry effects at different ticks (t, t+1, t+2, ...).
        Measures latency between signal and execution.
        Args:
            ohlcv_seq: List of OHLCV dicts.
            entry_tick: Starting tick index.
            horizon: Number of ticks to consider.
            signal_time: Optional signal timestamp.
            execution_time: Optional execution timestamp.
        Returns:
            Dict with results, best entry, and latency.
        """
        results = []
        latency = None
        if signal_time is not None and execution_time is not None:
            latency = execution_time - signal_time
            self.logger.info(f"TimeAdvantage: latency={latency}")
        for offset in range(horizon):
            tick = entry_tick + offset
            if tick >= len(ohlcv_seq):
                continue
            entry_price = ohlcv_seq[tick]["open"]
            future_idx = min(tick + 1, len(ohlcv_seq) - 1)
            future_close = ohlcv_seq[future_idx]["close"]
            pnl = future_close - entry_price
            results.append(
                {
                    "tick": tick,
                    "entry_price": entry_price,
                    "future_close": future_close,
                    "pnl": pnl,
                    "latency": latency,
                }
            )
            self.logger.info(
                ("TimeAdvantage: tick=%s, entry=%s, close=%s, pnl=%s, " "latency=%s"),
                tick,
                entry_price,
                future_close,
                pnl,
                latency,
            )
        best = max(results, key=lambda r: r["pnl"], default=None)
        return {
            "results": results,
            "best_entry_tick": best["tick"] if best else None,
            "best_pnl": best["pnl"] if best else None,
            "latency": latency,
        }

    # Legacy test compatibility
    def compute_time_advantage(
        self, market_data, signal_time=None, execution_time=None
    ):
        """
        Oblicza przewagę czasową jako różnicę PnL między wejściem
        natychmiastowym a opóźnionym.
        Loguje latency i przewagę czasową.
        """
        if len(market_data) < 2:
            return 0.0
        entry_now = market_data[-2]["open"]
        close_now = market_data[-1]["close"]
        pnl_now = close_now - entry_now
        entry_delayed = market_data[-1]["open"]
        close_delayed = market_data[-1]["close"]
        pnl_delayed = close_delayed - entry_delayed
        advantage = pnl_now - pnl_delayed
        latency = None
        if signal_time is not None and execution_time is not None:
            latency = execution_time - signal_time
            logging.info(f"TimeAdvantage: latency={latency}")
        logging.info(
            (
                f"TimeAdvantage: advantage={advantage}, "
                f"pnl_now={pnl_now}, pnl_delayed={pnl_delayed}"
            )
        )
        return round(advantage, 4)

    def detect(self, data, threshold=0.0):
        """
        Detekcja przewagi czasowej: zwraca True jeśli przewaga przekracza próg.
        """
        if not isinstance(data, list) or len(data) < 2:
            return False
        advantage = self.compute_time_advantage(data)
        detected = advantage > threshold
        logging.info(
            f"TimeAdvantage: detect={detected}, "
            f"advantage={advantage}, threshold={threshold}"
        )
        return detected


# Alias dla testów legacy
TimeAdvantage = TimeAdvantageEngine
