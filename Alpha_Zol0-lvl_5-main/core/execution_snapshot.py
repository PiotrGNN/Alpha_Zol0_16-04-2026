from __future__ import annotations

import math
from typing import Any


MEASURED_DEPTH_SOURCES = {"book_size_measured", "exchange_l1"}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _pick_float(payload: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        number = _safe_float(payload.get(key))
        if number is not None:
            return number
    return None


def _size_source_quality(source_value: Any) -> str:
    source = str(source_value or "").strip().lower()
    if source in MEASURED_DEPTH_SOURCES:
        return "top_of_book"
    return "proxy"


def build_execution_snapshot(
    side: str,
    expected_size_usdt: float | None,
    decision_quote: dict[str, Any] | None = None,
    fallback_price: float | None = None,
    maker_fee_rate: float | None = None,
    taker_fee_rate: float | None = None,
    mean_gross_fill_model: float | None = None,
) -> dict[str, Any] | None:
    side_norm = str(side or "").strip().lower()
    if side_norm not in {"buy", "sell"}:
        return None

    quote_obj = decision_quote if isinstance(decision_quote, dict) else {}
    bid = _pick_float(quote_obj, ["bid", "best_bid", "bestBid", "bestBidPrice"])
    ask = _pick_float(quote_obj, ["ask", "best_ask", "bestAsk", "bestAskPrice"])
    mid = _pick_float(quote_obj, ["mid", "markPrice", "last", "price"])
    fallback_mid = _safe_float(fallback_price)
    if mid is None and bid is not None and ask is not None:
        mid = (float(bid) + float(ask)) * 0.5
    if mid is None:
        mid = fallback_mid

    spread_abs = None
    spread_pct = None
    if bid is not None and ask is not None and ask >= bid:
        spread_abs = float(ask) - float(bid)
        if mid not in (None, 0.0):
            spread_pct = float(spread_abs) / float(mid)

    bid_size = _pick_float(
        quote_obj,
        ["bid_size", "best_bid_size", "bidSize", "bestBidSize"],
    )
    ask_size = _pick_float(
        quote_obj,
        ["ask_size", "best_ask_size", "askSize", "bestAskSize"],
    )
    depth_top5 = _pick_float(
        quote_obj,
        ["depth_top5", "aggregated_depth_top5", "depthTop5"],
    )
    size_source_quality = _size_source_quality(
        quote_obj.get("bid_size_source") or quote_obj.get("best_bid_size_source")
    )
    if side_norm == "buy":
        top_of_book_size = ask_size if ask_size is not None else bid_size
        expected_open_price = ask if ask is not None else mid
        expected_close_price = bid if bid is not None else mid
    else:
        top_of_book_size = bid_size if bid_size is not None else ask_size
        expected_open_price = bid if bid is not None else mid
        expected_close_price = ask if ask is not None else mid

    expected_notional = abs(_safe_float(expected_size_usdt) or 0.0)
    maker_fee = max(0.0, float(_safe_float(maker_fee_rate) or 0.0))
    taker_fee = max(0.0, float(_safe_float(taker_fee_rate) or 0.0))

    expected_fee_open = None
    expected_fee_close = None
    expected_fee_total = None
    if expected_notional > 0.0:
        expected_fee_open = expected_notional * taker_fee
        expected_fee_close = expected_notional * taker_fee
        expected_fee_total = expected_fee_open + expected_fee_close

    slippage_proxy_open = None
    slippage_proxy_close = None
    slippage_proxy_total = None
    if (
        expected_notional > 0.0
        and mid is not None
        and mid > 0.0
        and expected_open_price is not None
        and expected_close_price is not None
    ):
        slippage_proxy_open = (
            abs(float(expected_open_price) - float(mid)) / float(mid)
        ) * expected_notional
        slippage_proxy_close = (
            abs(float(expected_close_price) - float(mid)) / float(mid)
        ) * expected_notional
        slippage_proxy_total = float(slippage_proxy_open) + float(slippage_proxy_close)

    execution_cost_total_realtime = None
    if expected_fee_total is not None or slippage_proxy_total is not None:
        execution_cost_total_realtime = float(expected_fee_total or 0.0) + float(
            slippage_proxy_total or 0.0
        )

    edge_after_realtime_cost = None
    gross_value = _safe_float(mean_gross_fill_model)
    if gross_value is not None and execution_cost_total_realtime is not None:
        edge_after_realtime_cost = float(gross_value) - float(
            execution_cost_total_realtime
        )

    if depth_top5 is not None:
        source_quality = "full_depth"
    elif top_of_book_size is not None and size_source_quality == "top_of_book":
        source_quality = "top_of_book"
    else:
        source_quality = "proxy"

    return {
        "bid": bid,
        "ask": ask,
        "best_bid": bid,
        "best_ask": ask,
        "mid": mid,
        "spread_abs": _safe_float(spread_abs),
        "spread_pct": _safe_float(spread_pct),
        "depth_top5": _safe_float(depth_top5),
        "top_of_book_size": _safe_float(top_of_book_size),
        "maker_fee_rate": maker_fee,
        "taker_fee_rate": taker_fee,
        "expected_size_usdt": _safe_float(expected_notional),
        "expected_fee_open": _safe_float(expected_fee_open),
        "expected_fee_close": _safe_float(expected_fee_close),
        "expected_fee_total": _safe_float(expected_fee_total),
        "slippage_proxy_open": _safe_float(slippage_proxy_open),
        "slippage_proxy_close": _safe_float(slippage_proxy_close),
        "slippage_proxy_total": _safe_float(slippage_proxy_total),
        "execution_cost_total_realtime": _safe_float(
            execution_cost_total_realtime
        ),
        "edge_after_realtime_cost": _safe_float(edge_after_realtime_cost),
        "expected_open_price": _safe_float(expected_open_price),
        "expected_close_price": _safe_float(expected_close_price),
        "source_quality": source_quality,
        "snapshot_method": "decision_quote_round_trip_taker_touch",
        "diagnostic_only": True,
    }
