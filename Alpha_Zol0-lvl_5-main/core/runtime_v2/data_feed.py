from __future__ import annotations

import time
from typing import Dict, List, Optional

from core.paper_quote_source import fetch_kucoin_paper_quote
from core.runtime_v2.contracts import QuoteTick


def _safe_float(value) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


class KucoinPaperDataFeed:
    def __init__(self, symbols: List[str], quote_stale_ms: int = 5000):
        self.symbols = [str(symbol or "").strip().upper() for symbol in symbols if symbol]
        self.quote_stale_ms = max(0, int(quote_stale_ms))
        self._last_tick_by_symbol: Dict[str, QuoteTick] = {}

    def fetch_tick(self, symbol: str) -> Optional[QuoteTick]:
        payload = fetch_kucoin_paper_quote(symbol)
        bid = _safe_float(payload.get("bid"))
        ask = _safe_float(payload.get("ask"))
        if bid is None or ask is None:
            return None
        if bid <= 0 or ask <= 0 or ask < bid:
            return None
        mid = (bid + ask) * 0.5
        spread_abs = ask - bid
        spread_bps = (spread_abs / mid) * 10_000.0 if mid > 0 else 0.0
        now_ms = int(time.time() * 1000.0)
        ts_ms = int(payload.get("l1_quote_ts") or now_ms)
        if self.quote_stale_ms > 0 and (now_ms - ts_ms) > self.quote_stale_ms:
            return None
        tick = QuoteTick(
            symbol=symbol,
            ts_ms=ts_ms,
            bid=bid,
            ask=ask,
            mid=mid,
            spread_abs=spread_abs,
            spread_bps=spread_bps,
            best_bid_size=_safe_float(payload.get("best_bid_size")),
            best_ask_size=_safe_float(payload.get("best_ask_size")),
            raw=payload,
        )
        self._last_tick_by_symbol[symbol] = tick
        return tick

    def fetch_ticks(self) -> Dict[str, Optional[QuoteTick]]:
        ticks: Dict[str, Optional[QuoteTick]] = {}
        now_ms = int(time.time() * 1000.0)
        for symbol in self.symbols:
            tick = self.fetch_tick(symbol)
            if tick is None:
                last_tick = self._last_tick_by_symbol.get(symbol)
                if last_tick is not None and self.quote_stale_ms > 0:
                    stale = now_ms - int(last_tick.ts_ms)
                    if stale <= self.quote_stale_ms:
                        ticks[symbol] = last_tick
                        continue
                ticks[symbol] = None
                continue
            ticks[symbol] = tick
        return ticks
