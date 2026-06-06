from __future__ import annotations

import os
import statistics
from collections import defaultdict, deque
from typing import Deque, Dict, List

from core.runtime_v2.contracts import FeatureFrame, QuoteTick
from core.runtime_v2.admission_reachability import (
    effective_v2_min_profile_samples,
)


class FeatureEngine:
    def __init__(self, history_size: int = 120):
        try:
            min_profile_samples = int(
                os.environ.get("V2_MIN_PROFILE_SAMPLES", "8")
            )
        except Exception:
            min_profile_samples = 8
        self._default_min_profile_samples = max(2, int(min_profile_samples))
        self._min_profile_samples = max(
            2,
            int(effective_v2_min_profile_samples(self._default_min_profile_samples)),
        )
        self._history: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=max(4, int(history_size)))
        )
        self._ts_history: Dict[str, Deque[int]] = defaultdict(
            lambda: deque(maxlen=max(4, int(history_size)))
        )
        self._first_ts_ms: Dict[str, int] = {}

    def ingest(self, tick: QuoteTick) -> FeatureFrame:
        history = self._history[tick.symbol]
        ts_history = self._ts_history[tick.symbol]
        history.append(float(tick.mid))
        ts_history.append(int(tick.ts_ms))
        if tick.symbol not in self._first_ts_ms:
            self._first_ts_ms[tick.symbol] = int(tick.ts_ms)
        prices: List[float] = list(history)
        ts_values: List[int] = list(ts_history)
        sample_count = len(prices)
        ret_1 = 0.0
        ret_3 = 0.0
        if sample_count >= 2 and prices[-2] > 0:
            ret_1 = (prices[-1] / prices[-2]) - 1.0
        if sample_count >= 4 and prices[-4] > 0:
            ret_3 = (prices[-1] / prices[-4]) - 1.0
        returns: List[float] = []
        for idx in range(1, sample_count):
            prev = prices[idx - 1]
            cur = prices[idx]
            if prev > 0:
                returns.append((cur / prev) - 1.0)
        vol = statistics.pstdev(returns[-20:]) if len(returns) >= 2 else 0.0
        first_ts_ms = int(self._first_ts_ms.get(tick.symbol, int(tick.ts_ms)))
        profile_age_sec = max(0.0, float(int(tick.ts_ms) - first_ts_ms) / 1000.0)
        profile_span_sec = 0.0
        if len(ts_values) >= 2:
            profile_span_sec = max(
                0.0, float(int(ts_values[-1]) - int(ts_values[0])) / 1000.0
            )
        return FeatureFrame(
            symbol=tick.symbol,
            ts_ms=tick.ts_ms,
            mid=tick.mid,
            ret_1=ret_1,
            ret_3=ret_3,
            volatility=float(vol),
            spread_bps=float(tick.spread_bps),
            has_profile=sample_count >= self._min_profile_samples,
            sample_count=sample_count,
            profile_source="rolling_quote_window",
            profile_age_sec=profile_age_sec,
            profile_span_sec=profile_span_sec,
        )
