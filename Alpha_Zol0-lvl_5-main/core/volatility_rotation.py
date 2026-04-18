from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from core.kucoin_futures_client import KucoinFuturesClient
except ModuleNotFoundError:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from core.kucoin_futures_client import KucoinFuturesClient


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data" / "top_scalping_pairs.json"
DEFAULT_DIAGNOSTIC_JSON = ROOT / "analysis" / "volatility_rotation_diagnostic.json"
DEFAULT_DIAGNOSTIC_MD = ROOT / "analysis" / "volatility_rotation_diagnostic.md"
DEFAULT_PHASE95_BASELINE_REPO_AUDIT_JSON = (
    ROOT
    / "analysis"
    / (
        "phase95_parallel_scanner_top100_top20_validation_medium_"
        "20260317_092846_edge_over_fee_shadow_promotion_readiness_audit.json"
    )
)
DEFAULT_REPO_AUDIT_JSON = (
    ROOT / "analysis" / "edge_over_fee_shadow_promotion_readiness_audit.json"
)
DEFAULT_PRIMARY_REPO_AUDIT_JSON = DEFAULT_PHASE95_BASELINE_REPO_AUDIT_JSON
DEFAULT_REPO_METRICS_JSON = ROOT / "analysis" / "repo_symbol_metrics.json"
DEFAULT_LATEST_DIAGNOSTICS_JSON = ROOT / "autopsy" / "latest_symbol_diagnostics.json"
DEFAULT_INTERVAL = "15min"
DEFAULT_LIMIT = 100
DEFAULT_TOP_N = 20
DEFAULT_LOOKBACK = 64
DEFAULT_ATR_PERIOD = 15
DEFAULT_MOVE_WINDOW = 15
DEFAULT_FEE_RATE = 0.0006
MIN_ATR_PCT = 0.002
MAX_SPREAD_TO_MOVE_RATIO = 0.35
MIN_TURNOVER_24H = 1_000_000.0
MAX_BLOCKED_RATE = 0.70
HIGH_BLOCKED_RATE = 0.55
MAX_WATCH_SYMBOLS = 2
EPSILON = 1e-9


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


def _looks_like_futures_symbol(value: str) -> bool:
    normalized = str(value or "").upper()
    if not normalized.endswith("USDTM"):
        return False
    return normalized[:-5].isalnum()


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / float(len(values))


def _first_float(payload: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        if key in payload:
            number = _safe_float(payload.get(key))
            if number is not None:
                return number
    return None


def _is_active_usdt_contract(contract: dict[str, Any]) -> bool:
    symbol = str(contract.get("symbol") or "").upper()
    if not symbol.endswith("USDTM"):
        return False
    quote_currency = str(contract.get("quoteCurrency") or "").upper()
    if quote_currency and quote_currency != "USDT":
        return False
    status = str(contract.get("status") or contract.get("statusCode") or "").lower()
    if status and status not in {"open", "online", "active"}:
        return False
    if contract.get("isOpen") is False:
        return False
    if contract.get("enableTrading") is False:
        return False
    return True


def _contract_rank_key(contract: dict[str, Any]) -> tuple[float, float, str]:
    turnover_24h = _safe_float(
        contract.get("turnoverOf24h")
        or contract.get("turnover24h")
        or contract.get("turnoverOf24Hr")
    ) or 0.0
    volume_24h = _safe_float(
        contract.get("volumeOf24h")
        or contract.get("volume24h")
        or contract.get("volumeOf24Hr")
    ) or 0.0
    symbol = str(contract.get("symbol") or "")
    return (turnover_24h, volume_24h, symbol)


def _mid_and_spread(
    ticker: dict[str, Any],
) -> tuple[float | None, float | None, float | None]:
    bid = _first_float(
        ticker,
        ["bestBidPrice", "bestBid", "bidPrice", "buy", "bid"],
    )
    ask = _first_float(
        ticker,
        ["bestAskPrice", "bestAsk", "askPrice", "sell", "ask"],
    )
    last = _first_float(ticker, ["price", "lastTradePrice", "last", "markPrice"])
    mid = None
    if bid is not None and ask is not None and bid > 0.0 and ask > 0.0:
        mid = (bid + ask) * 0.5
        spread_abs = max(0.0, ask - bid)
        spread_pct = (spread_abs / mid) if mid > 0.0 else None
        return mid, spread_abs, spread_pct
    if last is not None and last > 0.0:
        return last, None, None
    return None, None, None


def _true_range(current: dict[str, Any], previous_close: float | None) -> float | None:
    high = _safe_float(current.get("high"))
    low = _safe_float(current.get("low"))
    if high is None or low is None:
        return None
    if previous_close is None:
        return max(0.0, high - low)
    return max(
        high - low,
        abs(high - previous_close),
        abs(low - previous_close),
    )


def _calculate_atr(candles: list[dict[str, Any]], period: int) -> float | None:
    if len(candles) < max(2, period):
        return None
    ranges: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        tr = _true_range(candle, previous_close)
        close = _safe_float(candle.get("close"))
        if tr is not None:
            ranges.append(tr)
        previous_close = close
    if len(ranges) < period:
        return None
    window = ranges[-period:]
    return sum(window) / float(period)


def _average_abs_move_pct(candles: list[dict[str, Any]], window: int) -> float | None:
    if len(candles) < window:
        return None
    moves: list[float] = []
    for candle in candles[-window:]:
        open_price = _safe_float(candle.get("open"))
        close_price = _safe_float(candle.get("close"))
        if open_price is None or close_price is None or open_price <= 0.0:
            continue
        moves.append(abs(close_price - open_price) / open_price)
    if len(moves) < window:
        return None
    return sum(moves) / float(len(moves))


def _fetch_top_contracts(
    client: KucoinFuturesClient,
    limit: int,
) -> list[dict[str, Any]]:
    contracts = client.get_contracts() or []
    filtered = [
        contract
        for contract in contracts
        if isinstance(contract, dict) and _is_active_usdt_contract(contract)
    ]
    ranked = sorted(filtered, key=_contract_rank_key, reverse=True)
    return ranked[:limit]


def _ticker_map(client: KucoinFuturesClient) -> dict[str, dict[str, Any]]:
    rows = client.get_all_tickers() or []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        out[symbol] = row
    return out


def _repo_overlay_candidates(explicit_path: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_path is not None:
        candidates.append(explicit_path)
    for path in (
        DEFAULT_PHASE95_BASELINE_REPO_AUDIT_JSON,
        DEFAULT_REPO_METRICS_JSON,
        DEFAULT_LATEST_DIAGNOSTICS_JSON,
        DEFAULT_REPO_AUDIT_JSON,
    ):
        if path not in candidates:
            candidates.append(path)
    return candidates


def _load_direct_repo_metrics(payload: dict[str, Any]) -> dict[str, dict[str, float]]:
    metrics = (
        payload.get("symbols")
        if isinstance(payload.get("symbols"), dict)
        else payload
    )
    if not isinstance(metrics, dict):
        return {}
    out: dict[str, dict[str, float]] = {}
    for symbol, values in metrics.items():
        if not isinstance(values, dict):
            continue
        normalized = str(symbol or "").upper()
        if not _looks_like_futures_symbol(normalized):
            continue
        if not any(
            key in values
            for key in (
                "repo_mean_net",
                "repo_total_net",
                "repo_winrate",
                "blocked_rate",
                "shadow_edge_after_execution_cost_mean",
            )
        ):
            continue
        out[normalized] = {
            "repo_mean_net": float(_safe_float(values.get("repo_mean_net")) or 0.0),
            "repo_total_net": float(_safe_float(values.get("repo_total_net")) or 0.0),
            "repo_winrate": float(_safe_float(values.get("repo_winrate")) or 0.0),
            "blocked_rate": float(_safe_float(values.get("blocked_rate")) or 0.0),
            "shadow_edge_after_execution_cost_mean": float(
                _safe_float(values.get("shadow_edge_after_execution_cost_mean")) or 0.0
            ),
        }
    return out


def _load_repo_symbol_stats(repo_audit_path: Path) -> dict[str, dict[str, float]]:
    if not repo_audit_path.exists():
        return {}
    payload = json.loads(repo_audit_path.read_text(encoding="utf-8"))
    rows = (((payload.get("shadow_audit") or {}).get("row_level_audit")) or [])
    if not isinstance(rows, list):
        return {}
    accum: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("strategy") or "") != "TrendFollowing":
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        bucket = accum.setdefault(
            symbol,
            {
                "row_count": 0,
                "blocked_count": 0,
                "shadow_values": [],
                "linked_nets": [],
                "win_count": 0,
            },
        )
        bucket["row_count"] += 1
        if bool(row.get("current_gate_blocked")):
            bucket["blocked_count"] += 1
        shadow_value = _safe_float(row.get("shadow_edge_after_execution_cost"))
        if shadow_value is not None:
            bucket["shadow_values"].append(shadow_value)
        linked_close = row.get("linked_close")
        if isinstance(linked_close, dict):
            net_pnl = _safe_float(linked_close.get("net_pnl"))
            if net_pnl is not None:
                bucket["linked_nets"].append(net_pnl)
                if net_pnl > 0.0:
                    bucket["win_count"] += 1
    stats: dict[str, dict[str, float]] = {}
    for symbol, bucket in accum.items():
        row_count = int(bucket["row_count"])
        linked_nets = [float(value) for value in bucket["linked_nets"]]
        shadow_values = [float(value) for value in bucket["shadow_values"]]
        linked_count = len(linked_nets)
        stats[symbol] = {
            "repo_mean_net": float(_mean(linked_nets) or 0.0),
            "repo_total_net": float(sum(linked_nets)) if linked_nets else 0.0,
            "repo_winrate": (
                float(bucket["win_count"]) / float(linked_count)
                if linked_count
                else 0.0
            ),
            "blocked_rate": (
                float(bucket["blocked_count"]) / float(row_count)
                if row_count
                else 0.0
            ),
            "shadow_edge_after_execution_cost_mean": float(
                _mean(shadow_values) or 0.0
            ),
            "repo_linked_close_count": float(linked_count),
            "repo_row_count": float(row_count),
        }
    return stats


def _load_repo_overlay(
    repo_overlay_path: Path | None,
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    for candidate in _repo_overlay_candidates(repo_overlay_path):
        if not candidate.exists():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        direct = _load_direct_repo_metrics(payload)
        if direct:
            return direct, {
                "repo_overlay_available": True,
                "repo_overlay_path": str(candidate),
                "repo_overlay_type": "direct_metrics",
            }
        audit = _load_repo_symbol_stats(candidate)
        if audit:
            return audit, {
                "repo_overlay_available": True,
                "repo_overlay_path": str(candidate),
                "repo_overlay_type": "audit_row_level",
            }
    return {}, {
        "repo_overlay_available": False,
        "repo_overlay_path": None,
        "repo_overlay_type": "none",
    }


def _normalized_volume_scores(rows: list[dict[str, Any]]) -> dict[str, float]:
    by_symbol: dict[str, float] = {}
    values: list[float] = []
    for row in rows:
        symbol = str(row.get("symbol") or "")
        volume = _safe_float(row.get("turnover_24h") or row.get("volume_24h"))
        if not symbol or volume is None or volume <= 0.0:
            continue
        score_input = math.log10(volume)
        by_symbol[symbol] = score_input
        values.append(score_input)
    if not values:
        return {}
    lower = min(values)
    upper = max(values)
    if upper <= lower:
        return {symbol: 1.0 for symbol in by_symbol}
    return {
        symbol: (value - lower) / (upper - lower)
        for symbol, value in by_symbol.items()
    }


def _negative_shadow_edge_penalty(shadow_edge_mean: float) -> float:
    return 1.0 if shadow_edge_mean < 0.0 else 0.0


def _fee_pct(contract: dict[str, Any], fallback_fee_pct: float) -> tuple[float, str]:
    taker_fee = _safe_float(
        contract.get("takerFeeRate")
        or contract.get("takerFee")
        or contract.get("feeRate")
    )
    maker_fee = _safe_float(
        contract.get("makerFeeRate")
        or contract.get("makerFee")
        or contract.get("feeRate")
    )
    if taker_fee is not None and taker_fee >= 0.0:
        return float(taker_fee), "contract_taker_fee_rate"
    if maker_fee is not None and maker_fee >= 0.0:
        return float(maker_fee), "contract_maker_fee_rate_fallback"
    return float(fallback_fee_pct), "configured_default_futures_fee"


def _liquidity_rank_key(
    contract: dict[str, Any],
    ticker: dict[str, Any],
) -> tuple[float, float, float, int, str]:
    turnover = _safe_float(
        ticker.get("turnoverOf24h")
        or ticker.get("turnover24h")
        or contract.get("turnoverOf24h")
        or contract.get("turnover24h")
        or contract.get("turnoverOf24Hr")
    ) or 0.0
    volume = _safe_float(
        ticker.get("volumeOf24h")
        or ticker.get("volume24h")
        or contract.get("volumeOf24h")
        or contract.get("volume24h")
        or contract.get("volumeOf24Hr")
    ) or 0.0
    price = _safe_float(
        ticker.get("price") or ticker.get("last") or ticker.get("lastTradePrice")
    ) or 0.0
    bid = _first_float(ticker, ["bestBidPrice", "bestBid", "bidPrice", "buy", "bid"])
    ask = _first_float(ticker, ["bestAskPrice", "bestAsk", "askPrice", "sell", "ask"])
    quote_ready = (
        1
        if bid is not None and ask is not None and bid > 0.0 and ask > 0.0
        else 0
    )
    return (turnover, volume, price, quote_ready, str(contract.get("symbol") or ""))


def _build_top_100_universe(
    client: KucoinFuturesClient,
    limit: int,
) -> tuple[list[dict[str, Any]], int, int, list[dict[str, Any]]]:
    contracts = client.get_contracts() or []
    ticker_map = _ticker_map(client)
    active_usdtm = [
        contract
        for contract in contracts
        if isinstance(contract, dict) and _is_active_usdt_contract(contract)
    ]
    excluded: list[dict[str, Any]] = []
    liquid: list[dict[str, Any]] = []
    for contract in active_usdtm:
        symbol = str(contract.get("symbol") or "").upper()
        ticker = ticker_map.get(symbol) or {}
        bid = _first_float(
            ticker,
            ["bestBidPrice", "bestBid", "bidPrice", "buy", "bid"],
        )
        ask = _first_float(
            ticker,
            ["bestAskPrice", "bestAsk", "askPrice", "sell", "ask"],
        )
        turnover = _safe_float(
            ticker.get("turnoverOf24h")
            or ticker.get("turnover24h")
            or contract.get("turnoverOf24h")
            or contract.get("turnover24h")
            or contract.get("turnoverOf24Hr")
        )
        volume = _safe_float(
            ticker.get("volumeOf24h")
            or ticker.get("volume24h")
            or contract.get("volumeOf24h")
            or contract.get("volume24h")
            or contract.get("volumeOf24Hr")
        )
        if bid is None or ask is None or bid <= 0.0 or ask <= 0.0:
            excluded.append({"symbol": symbol, "reason": "missing_best_bid_or_ask"})
            continue
        if (turnover or 0.0) <= 0.0 and (volume or 0.0) <= 0.0:
            excluded.append(
                {"symbol": symbol, "reason": "nonzero_quote_activity_missing"}
            )
            continue
        liquid.append({"contract": contract, "ticker": ticker})
    liquid.sort(
        key=lambda row: _liquidity_rank_key(row["contract"], row["ticker"]),
        reverse=True,
    )
    top_universe = liquid[:limit]
    return top_universe, len(active_usdtm), len(top_universe), excluded


def _classify_symbol(
    repo_mean_net: float,
    repo_total_net: float,
    blocked_rate: float,
) -> str:
    if repo_mean_net > 0.0 and repo_total_net > 0.0 and blocked_rate < 0.45:
        return "KEEP"
    if repo_mean_net > -0.001 and blocked_rate < 0.75:
        return "WATCH"
    if repo_mean_net < 0.0 and blocked_rate > 0.55:
        return "DROP"
    return "DROP"


def _hard_filter_reason(
    repo_mean_net: float,
    repo_total_net: float,
    blocked_rate: float,
    shadow_edge_mean: float,
) -> str | None:
    if blocked_rate > MAX_BLOCKED_RATE:
        return "blocked_rate_above_hard_max"
    if shadow_edge_mean < 0.0 and blocked_rate > HIGH_BLOCKED_RATE:
        return "negative_shadow_edge_with_high_blocked_rate"
    if repo_mean_net < 0.0 and repo_total_net < 0.0:
        return "persistently_negative_repo_mean_net"
    return None


def _analyze_contract(
    client: KucoinFuturesClient,
    contract: dict[str, Any],
    ticker: dict[str, Any],
    interval: str,
    lookback: int,
    atr_period: int,
    move_window: int,
    fallback_fee_rate: float,
) -> dict[str, Any] | None:
    symbol = str(contract.get("symbol") or "").upper()
    candles = client.get_klines(symbol, interval, limit=lookback)
    if not candles or len(candles) < max(atr_period, move_window):
        return None
    last_close = _safe_float(candles[-1].get("close"))
    if last_close is None or last_close <= 0.0:
        return None
    atr_abs = _calculate_atr(candles, atr_period)
    avg_move_pct = _average_abs_move_pct(candles, move_window)
    mid_price, spread_abs, spread_pct = _mid_and_spread(ticker or {})
    if spread_pct is None and spread_abs is not None and last_close > 0.0:
        spread_pct = spread_abs / last_close
    fee_pct, fee_source = _fee_pct(contract, fallback_fee_rate)
    execution_cost_pct = (spread_pct or 0.0) + float(fee_pct)
    market_edge_score = None
    if avg_move_pct is not None:
        market_edge_score = avg_move_pct / max(execution_cost_pct, EPSILON)
    turnover_24h = _safe_float(
        ticker.get("turnoverOf24h")
        or ticker.get("turnover24h")
        or contract.get("turnoverOf24h")
        or contract.get("turnover24h")
        or contract.get("turnoverOf24Hr")
    )
    volume_24h = _safe_float(
        ticker.get("volumeOf24h")
        or ticker.get("volume24h")
        or contract.get("volumeOf24h")
        or contract.get("volume24h")
        or contract.get("volumeOf24Hr")
    )
    return {
        "symbol": symbol,
        "base_currency": contract.get("baseCurrency"),
        "quote_currency": contract.get("quoteCurrency"),
        "last_price": last_close,
        "mid_price": mid_price,
        "spread_abs": spread_abs,
        "spread_pct": spread_pct,
        "fee_pct": fee_pct,
        "fee_source": fee_source,
        "execution_cost_pct": execution_cost_pct,
        "atr_15_abs": atr_abs,
        "atr_15_pct": (atr_abs / last_close) if atr_abs is not None else None,
        "avg_15m_move_pct": avg_move_pct,
        "volume_24h": volume_24h,
        "turnover_24h": turnover_24h,
        "market_edge_score": market_edge_score,
        "candle_count": len(candles),
    }


def build_top_scalping_pairs(
    limit: int = DEFAULT_LIMIT,
    top_n: int = DEFAULT_TOP_N,
    output_path: Path = DEFAULT_OUTPUT,
    diagnostic_json_path: Path = DEFAULT_DIAGNOSTIC_JSON,
    diagnostic_md_path: Path = DEFAULT_DIAGNOSTIC_MD,
    repo_audit_path: Path = DEFAULT_PRIMARY_REPO_AUDIT_JSON,
    interval: str = DEFAULT_INTERVAL,
    lookback: int = DEFAULT_LOOKBACK,
    atr_period: int = DEFAULT_ATR_PERIOD,
    move_window: int = DEFAULT_MOVE_WINDOW,
    fee_rate: float = DEFAULT_FEE_RATE,
) -> dict[str, Any]:
    client = KucoinFuturesClient()
    universe, universe_size_raw, universe_size_filtered, universe_excluded = (
        _build_top_100_universe(client, limit)
    )
    market_rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = list(universe_excluded)
    repo_stats, repo_meta = _load_repo_overlay(repo_audit_path)
    for item in universe:
        contract = item["contract"]
        ticker = item["ticker"]
        symbol = str(contract.get("symbol") or "").upper()
        try:
            analyzed = _analyze_contract(
                client=client,
                contract=contract,
                ticker=ticker,
                interval=interval,
                lookback=lookback,
                atr_period=atr_period,
                move_window=move_window,
                fallback_fee_rate=fee_rate,
            )
            if analyzed is None:
                excluded.append(
                    {"symbol": symbol, "reason": "insufficient_market_data"}
                )
                continue
            atr_pct = _safe_float(analyzed.get("atr_15_pct"))
            avg_move_pct = _safe_float(analyzed.get("avg_15m_move_pct"))
            spread_pct = _safe_float(analyzed.get("spread_pct"))
            turnover_24h = _safe_float(analyzed.get("turnover_24h"))
            if atr_pct is None or atr_pct < MIN_ATR_PCT:
                excluded.append(
                    {"symbol": symbol, "reason": "atr_15_below_minimum"}
                )
                continue
            if (
                spread_pct is None
                or avg_move_pct is None
                or avg_move_pct <= 0.0
                or spread_pct > (avg_move_pct * MAX_SPREAD_TO_MOVE_RATIO)
            ):
                excluded.append(
                    {"symbol": symbol, "reason": "spread_too_wide_for_move"}
                )
                continue
            if turnover_24h is None or turnover_24h < MIN_TURNOVER_24H:
                excluded.append(
                    {"symbol": symbol, "reason": "turnover_24h_below_minimum"}
                )
                continue
            market_rows.append(analyzed)
        except Exception as exc:
            excluded.append({"symbol": symbol, "reason": str(exc)})
    volume_scores = _normalized_volume_scores(market_rows)
    ranked_rows: list[dict[str, Any]] = []
    dropped_rows: list[dict[str, Any]] = []
    for row in market_rows:
        symbol = str(row.get("symbol") or "").upper()
        repo = repo_stats.get(symbol, {})
        avg_move_pct = float(_safe_float(row.get("avg_15m_move_pct")) or 0.0)
        atr_pct = float(_safe_float(row.get("atr_15_pct")) or 0.0)
        spread_pct = float(_safe_float(row.get("spread_pct")) or 0.0)
        execution_cost_pct = float(
            _safe_float(row.get("execution_cost_pct")) or 0.0
        )
        fee_pct = float(_safe_float(row.get("fee_pct")) or 0.0)
        repo_mean_net = float(_safe_float(repo.get("repo_mean_net")) or 0.0)
        repo_total_net = float(_safe_float(repo.get("repo_total_net")) or 0.0)
        repo_winrate = float(_safe_float(repo.get("repo_winrate")) or 0.0)
        blocked_rate = float(_safe_float(repo.get("blocked_rate")) or 0.0)
        shadow_edge_mean = float(
            _safe_float(repo.get("shadow_edge_after_execution_cost_mean")) or 0.0
        )
        volume_score = float(volume_scores.get(symbol, 0.0))
        negative_penalty = _negative_shadow_edge_penalty(shadow_edge_mean)
        repo_edge_score = (
            avg_move_pct * 0.35
            + atr_pct * 0.20
            + repo_mean_net * 0.20
            + repo_winrate * 0.10
            + volume_score * 0.15
            - (
                spread_pct * 0.25
                + execution_cost_pct * 0.25
                + blocked_rate * 0.30
                + negative_penalty * 0.20
            )
        )
        classification = _classify_symbol(
            repo_mean_net=repo_mean_net,
            repo_total_net=repo_total_net,
            blocked_rate=blocked_rate,
        )
        hard_filter_reason = _hard_filter_reason(
            repo_mean_net=repo_mean_net,
            repo_total_net=repo_total_net,
            blocked_rate=blocked_rate,
            shadow_edge_mean=shadow_edge_mean,
        )
        enriched = {
            "symbol": symbol,
            "repo_edge_score": repo_edge_score,
            "market_edge_score": float(
                _safe_float(row.get("market_edge_score")) or 0.0
            ),
            "avg_move_15m_pct": avg_move_pct,
            "atr_15m_pct": atr_pct,
            "spread_pct": spread_pct,
            "fee_pct": fee_pct,
            "volume": float(
                _safe_float(row.get("turnover_24h") or row.get("volume_24h")) or 0.0
            ),
            "execution_cost_pct": execution_cost_pct,
            "repo_mean_net": repo_mean_net,
            "repo_total_net": repo_total_net,
            "repo_winrate": repo_winrate,
            "blocked_rate": blocked_rate,
            "shadow_edge_after_execution_cost_mean": shadow_edge_mean,
            "volume_score": volume_score,
            "negative_shadow_edge_penalty": negative_penalty,
            "classification": classification,
            "hard_filter_reason": hard_filter_reason,
            "fee_source": row.get("fee_source"),
            "repo_linked_close_count": int(repo.get("repo_linked_close_count") or 0),
            "repo_row_count": int(repo.get("repo_row_count") or 0),
        }
        if hard_filter_reason:
            dropped_rows.append(enriched)
            excluded.append({"symbol": symbol, "reason": hard_filter_reason})
            continue
        ranked_rows.append(enriched)
    score_key = (
        "repo_edge_score"
        if repo_meta["repo_overlay_available"]
        else "market_edge_score"
    )
    ranked_rows.sort(
        key=lambda row: (
            float(row.get(score_key) or -1.0),
            float(row.get("market_edge_score") or 0.0),
            float(row.get("volume") or 0.0),
            str(row.get("symbol") or ""),
        ),
        reverse=True,
    )
    for index, row in enumerate(ranked_rows, start=1):
        row["rank"] = index
    timestamp = datetime_utc_now()
    keep_symbols = [
        row["symbol"] for row in ranked_rows if row.get("classification") == "KEEP"
    ]
    watch_symbols = [
        row["symbol"] for row in ranked_rows if row.get("classification") == "WATCH"
    ]
    drop_symbols = [
        row["symbol"]
        for row in ranked_rows
        if row.get("classification") == "DROP"
    ] + [row["symbol"] for row in dropped_rows]
    top_scalping_pairs = [
        {
            "symbol": row.get("symbol"),
            "repo_edge_score": row.get("repo_edge_score"),
            "market_edge_score": row.get("market_edge_score"),
            "avg_move_15m_pct": row.get("avg_move_15m_pct"),
            "atr_15m_pct": row.get("atr_15m_pct"),
            "spread_pct": row.get("spread_pct"),
            "fee_pct": row.get("fee_pct"),
            "volume": row.get("volume"),
            "execution_cost_pct": row.get("execution_cost_pct"),
            "volume_score": row.get("volume_score"),
            "repo_mean_net": row.get("repo_mean_net"),
            "repo_total_net": row.get("repo_total_net"),
            "repo_winrate": row.get("repo_winrate"),
            "blocked_rate": row.get("blocked_rate"),
            "shadow_edge_after_execution_cost_mean": (
                row.get("shadow_edge_after_execution_cost_mean")
            ),
            "classification": row.get("classification"),
            "rank": row.get("rank"),
        }
        for row in ranked_rows[:top_n]
    ]
    diagnostic_payload = {
        "timestamp": timestamp,
        "source": "kucoin-futures-public",
        "market_source": "kucoin-futures-public",
        "universe_size_raw": universe_size_raw,
        "universe_size_filtered": universe_size_filtered,
        "repo_overlay_available": repo_meta["repo_overlay_available"],
        "repo_overlay_path": repo_meta["repo_overlay_path"],
        "repo_overlay_type": repo_meta["repo_overlay_type"],
        "scanner_top_n": len(top_scalping_pairs),
        "scan_limit": limit,
        "selection": {
            "top_contracts_considered": limit,
            "interval": interval,
            "lookback_candles": lookback,
            "atr_period": atr_period,
            "avg_move_window": move_window,
            "fee_rate_assumed": float(fee_rate),
            "repo_edge_score_formula": (
                "avg_move_15m_pct*0.35 + atr_15m_pct*0.20 + repo_mean_net*0.20 + "
                "repo_winrate*0.10 + volume_score*0.15 - (spread_pct*0.25 + "
                "execution_cost_pct*0.25 + blocked_rate*0.30 + "
                "negative_shadow_edge_penalty*0.20)"
            ),
            "filters": {
                "min_atr_pct": MIN_ATR_PCT,
                "max_spread_to_move_ratio": MAX_SPREAD_TO_MOVE_RATIO,
                "min_turnover_24h": MIN_TURNOVER_24H,
                "max_blocked_rate": MAX_BLOCKED_RATE,
                "high_blocked_rate": HIGH_BLOCKED_RATE,
                "max_watch_symbols": MAX_WATCH_SYMBOLS,
            },
        },
        "keep": keep_symbols,
        "watch": watch_symbols,
        "drop": drop_symbols,
        "top_scalping_pairs": top_scalping_pairs,
        "excluded_symbols": excluded,
        "ranked_snapshot": ranked_rows[:top_n],
        "hard_filtered_snapshot": dropped_rows,
        "fee_assumption": {
            "default_fee_pct": float(fee_rate),
            "mode": "contract_or_default_fallback",
        },
    }
    output = {
        "timestamp": timestamp,
        "generated_at": timestamp,
        "source": "kucoin-futures-public",
        "market_source": "kucoin-futures-public",
        "universe_size_raw": universe_size_raw,
        "universe_size_filtered": universe_size_filtered,
        "repo_overlay_available": repo_meta["repo_overlay_available"],
        "scanner_top_n": len(top_scalping_pairs),
        "pair_count": len(ranked_rows),
        "keep": keep_symbols,
        "watch": watch_symbols,
        "drop": drop_symbols,
        "top_scalping_pairs": top_scalping_pairs,
        "pairs": ranked_rows,
        "excluded_symbols": excluded,
        "skipped": excluded,
        "selection": diagnostic_payload["selection"],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    diagnostic_json_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_md_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_json_path.write_text(
        json.dumps(diagnostic_payload, indent=2),
        encoding="utf-8",
    )
    diagnostic_md_lines = [
        "VOLATILITY_ROTATION_DIAGNOSTIC",
        "",
        f"timestamp: {timestamp}",
        f"scan_limit: {limit}",
        f"universe_size_raw: {universe_size_raw}",
        f"universe_size_filtered: {universe_size_filtered}",
        f"repo_overlay_available: {repo_meta['repo_overlay_available']}",
        f"repo_overlay_path: {repo_meta['repo_overlay_path']}",
        f"selected_count: {len(top_scalping_pairs)}",
        f"excluded_count: {len(excluded)}",
        f"score_sort_key: {score_key}",
        "",
        "FILTERS",
        f"min_atr_pct: {MIN_ATR_PCT}",
        f"max_spread_to_move_ratio: {MAX_SPREAD_TO_MOVE_RATIO}",
        f"min_turnover_24h: {MIN_TURNOVER_24H}",
        f"max_blocked_rate: {MAX_BLOCKED_RATE}",
        f"high_blocked_rate: {HIGH_BLOCKED_RATE}",
        "",
        "KEEP",
        ",".join(keep_symbols),
        "",
        "WATCH",
        ",".join(watch_symbols),
        "",
        "DROP",
        ",".join(drop_symbols),
        "",
        "TOP_20",
        (
            "symbol | classification | avg_move_15m_pct | atr_15m_pct | spread_pct "
            "| fee_pct | execution_cost_pct | volume_score | market_edge_score "
            "| repo_edge_score"
        ),
        "--- | --- | --- | --- | --- | --- | --- | --- | --- | ---",
        "",
    ]
    for row in top_scalping_pairs:
        diagnostic_md_lines.append(
            " | ".join(
                [
                    str(row.get("symbol") or ""),
                    str(row.get("classification") or ""),
                    str(row.get("avg_move_15m_pct") or 0.0),
                    str(row.get("atr_15m_pct") or 0.0),
                    str(row.get("spread_pct") or 0.0),
                    str(row.get("fee_pct") or 0.0),
                    str(row.get("execution_cost_pct") or 0.0),
                    str(row.get("volume_score") or 0.0),
                    str(row.get("market_edge_score") or 0.0),
                    str(row.get("repo_edge_score") or 0.0),
                ]
            )
        )
    diagnostic_md_path.write_text("\n".join(diagnostic_md_lines), encoding="utf-8")
    return {
        "output_path": str(output_path),
        "pair_count": len(ranked_rows),
        "top_symbols": [row["symbol"] for row in top_scalping_pairs],
        "keep": keep_symbols,
        "watch": watch_symbols,
        "drop": drop_symbols,
        "excluded_count": len(excluded),
        "diagnostic_json_path": str(diagnostic_json_path),
        "diagnostic_md_path": str(diagnostic_md_path),
    }


def datetime_utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--repo-audit", default=str(DEFAULT_PRIMARY_REPO_AUDIT_JSON))
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK)
    parser.add_argument("--atr-period", type=int, default=DEFAULT_ATR_PERIOD)
    parser.add_argument("--move-window", type=int, default=DEFAULT_MOVE_WINDOW)
    parser.add_argument("--fee-rate", type=float, default=DEFAULT_FEE_RATE)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = build_top_scalping_pairs(
        limit=max(1, int(args.limit)),
        top_n=max(1, int(args.top_n)),
        output_path=Path(args.output),
        repo_audit_path=Path(args.repo_audit),
        interval=args.interval,
        lookback=max(16, int(args.lookback)),
        atr_period=max(2, int(args.atr_period)),
        move_window=max(2, int(args.move_window)),
        fee_rate=max(0.0, float(args.fee_rate)),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
