from __future__ import annotations

import math
from typing import Any, Dict, Optional

from core.kucoin_client import KucoinClient
from core.kucoin_futures_client import KucoinFuturesClient, is_futures_symbol


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _safe_tick_ts(value: Any) -> Optional[int]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    out = abs(out)
    if out <= 0:
        return None
    if out >= 1e18:
        out = out / 1_000_000.0
    elif out >= 1e15:
        out = out / 1_000.0
    elif out < 1e11:
        out = out * 1_000.0
    try:
        return int(out)
    except Exception:
        return None


def paper_quote_upstream_source(symbol: str) -> str:
    return "kucoin_futures_ticker" if is_futures_symbol(symbol) else "kucoin_spot_level1"


def normalize_kucoin_paper_quote(symbol: str, payload: Any) -> Dict[str, Any]:
    upstream_source = paper_quote_upstream_source(symbol)
    if not isinstance(payload, dict):
        return {
            "upstream_source": upstream_source,
            "quote_path_classification": "synthetic_fallback",
            "fetch_status": "non_dict_payload",
            "synthetic_fallback_reason": "quote_payload_non_dict",
            "mid": None,
            "bid": None,
            "ask": None,
            "best_bid_size": None,
            "best_ask_size": None,
            "best_bid_size_source": None,
            "best_ask_size_source": None,
            "l1_quote_ts": None,
            "raw_has_bid_ask": False,
            "raw_has_measured_size": False,
        }

    bid = _safe_float(
        payload.get("bestBidPrice")
        or payload.get("bestBid")
        or payload.get("bid")
        or payload.get("best_bid")
    )
    ask = _safe_float(
        payload.get("bestAskPrice")
        or payload.get("bestAsk")
        or payload.get("ask")
        or payload.get("best_ask")
    )
    last_trade_price = _safe_float(
        payload.get("price")
        or payload.get("last")
        or payload.get("markPrice")
        or payload.get("mark_price")
    )
    mid = last_trade_price
    if bid is not None and ask is not None:
        mid = (float(bid) + float(ask)) * 0.5

    best_bid_size = _safe_float(
        payload.get("bestBidSize")
        or payload.get("bidSize")
        or payload.get("best_bid_size")
        or payload.get("bid_size")
    )
    best_ask_size = _safe_float(
        payload.get("bestAskSize")
        or payload.get("askSize")
        or payload.get("best_ask_size")
        or payload.get("ask_size")
    )
    l1_quote_ts = _safe_tick_ts(
        payload.get("ts")
        or payload.get("timestamp")
        or payload.get("time")
        or payload.get("T")
    )

    raw_has_bid_ask = bid is not None and ask is not None
    raw_has_measured_size = best_bid_size is not None and best_ask_size is not None
    classification = "real_exchange_quote" if raw_has_bid_ask else "synthetic_fallback"
    fetch_status = "ok" if raw_has_bid_ask else "missing_bid_ask"
    synthetic_fallback_reason = None
    if not raw_has_bid_ask:
        missing = []
        if bid is None:
            missing.append("bid")
        if ask is None:
            missing.append("ask")
        synthetic_fallback_reason = (
            "missing_" + "_".join(missing) + "_from_kucoin_quote"
        )

    return {
        "upstream_source": upstream_source,
        "quote_path_classification": classification,
        "fetch_status": fetch_status,
        "synthetic_fallback_reason": synthetic_fallback_reason,
        "mid": mid,
        "bid": bid,
        "ask": ask,
        "best_bid_size": best_bid_size,
        "best_ask_size": best_ask_size,
        "best_bid_size_source": "exchange_l1" if best_bid_size is not None else None,
        "best_ask_size_source": "exchange_l1" if best_ask_size is not None else None,
        "l1_quote_ts": l1_quote_ts,
        "last_trade_price": last_trade_price,
        "raw_has_bid_ask": raw_has_bid_ask,
        "raw_has_measured_size": raw_has_measured_size,
    }


def fetch_kucoin_paper_quote(
    symbol: str,
    *,
    futures_client: KucoinFuturesClient | None = None,
    spot_client: KucoinClient | None = None,
) -> Dict[str, Any]:
    upstream_source = paper_quote_upstream_source(symbol)
    try:
        if is_futures_symbol(symbol):
            client = futures_client if futures_client is not None else KucoinFuturesClient()
            payload = client.get_ticker(symbol)
        else:
            client = spot_client if spot_client is not None else KucoinClient()
            payload = client.get_level1_orderbook(symbol)
    except Exception as exc:
        return {
            "upstream_source": upstream_source,
            "quote_path_classification": "synthetic_fallback",
            "fetch_status": "exception",
            "synthetic_fallback_reason": f"quote_fetch_exception:{type(exc).__name__}",
            "mid": None,
            "bid": None,
            "ask": None,
            "best_bid_size": None,
            "best_ask_size": None,
            "best_bid_size_source": None,
            "best_ask_size_source": None,
            "l1_quote_ts": None,
            "raw_has_bid_ask": False,
            "raw_has_measured_size": False,
            "error": str(exc),
        }
    normalized = normalize_kucoin_paper_quote(symbol, payload)
    normalized["raw_payload_type"] = type(payload).__name__
    return normalized
