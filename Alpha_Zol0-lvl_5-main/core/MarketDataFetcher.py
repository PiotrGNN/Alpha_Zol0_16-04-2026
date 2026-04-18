# ZoL0 LEVEL 0
# ✅ LEVEL-API done: KuCoin REST API integration, throttling, retry, logging,
# multi-symbol/timeframe
# MarketDataFetcher.py – Pobieranie danych OHLCV (mock)

import copy
import logging
import time
import threading

import requests


class MarketDataFetcher:
    """
    Fetcher pobierający dane OHLCV z KuCoin REST API dla podanego symbolu
    i interwału.
    """

    def __init__(
        self,
        api_url="https://api.kucoin.com/api/v1/market/candles",
        throttle_sec=1,
        max_retries=3,
        market_type=None,
    ):
        import os

        self.api_url = api_url
        if "kucoin.com" not in str(self.api_url).lower():
            raise ValueError("MarketDataFetcher: non-KuCoin api_url blocked (NO-GO)")
        self.throttle_sec = throttle_sec
        self.max_retries = max_retries
        self.market_type = market_type or os.environ.get("MARKET_TYPE")
        self.last_call = 0
        self._fetch_cache = {}
        self._fetch_cache_lock = threading.RLock()
        self._fetch_cache_sec = self._resolve_fetch_cache_sec()

    def _resolve_fetch_cache_sec(self) -> float:
        import os

        try:
            return max(0.0, float(os.environ.get("MARKET_DATA_FETCH_CACHE_SEC", "1")))
        except Exception as exc:
            logging.debug("MarketDataFetcher: fetch cache ttl parse failed: %s", exc)
            return 1.0

    def _resolve_ohlcv_request(self, symbol, interval, limit):
        import os
        from core.kucoin_client import normalize_symbol

        try:
            resolved_limit = int(limit)
        except Exception:
            resolved_limit = 120
        try:
            env_limit = os.environ.get("OHLCV_LIMIT")
            if env_limit is not None and str(env_limit).strip() != "":
                resolved_limit = int(env_limit)
        except Exception as exc:
            logging.debug("MarketDataFetcher: OHLCV_LIMIT parse failed: %s", exc)
        interval_str = str(interval).strip()
        if interval_str.isdigit():
            interval_str = f"{interval_str}min"
        symbol_norm = normalize_symbol(symbol)
        return symbol_norm, interval_str, resolved_limit

    def _fetch_data_cache_key(self, symbol, interval, limit, runtime_mode=None):
        import os

        return (
            str(symbol),
            str(interval),
            int(limit),
            str(runtime_mode or "").strip().lower(),
            str(self.market_type or "").strip().lower(),
            os.environ.get("USE_MOCK", "0"),
            os.environ.get("ZOL0_ALLOW_MOCK", "0"),
            os.environ.get("LIVE", "0"),
            os.environ.get("BOT_MODE", "").strip().lower(),
        )

    @staticmethod
    def _clone_candles(candles):
        return copy.deepcopy(candles or [])

    @staticmethod
    def _coerce_candle_row(item, *, layout: str):
        if not isinstance(item, (list, tuple)):
            return None
        try:
            if layout == "result":
                if len(item) < 6:
                    return None
                return {
                    "timestamp": item[0],
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                }
            if layout == "data":
                if len(item) < 6:
                    return None
                return {
                    "timestamp": item[0],
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5]),
                }
        except Exception as exc:
            logging.debug(
                (
                    "MarketDataFetcher: skipped malformed candle row "
                    "layout=%s error=%s row=%s"
                ),
                layout,
                exc,
                item,
            )
            return None
        return None

    def _is_futures(self, symbol: str) -> bool:
        if self.market_type and str(self.market_type).lower() == "futures":
            return True
        return bool(symbol) and str(symbol).upper().endswith("USDTM")

    def _is_paper_runtime(self, runtime_mode=None) -> bool:
        import os

        runtime_mode_norm = str(runtime_mode or "").strip().lower()
        if runtime_mode_norm == "paper":
            return True

        bot_mode = str(os.environ.get("BOT_MODE", "")).strip().lower()
        if bot_mode == "paper":
            return True
        if os.environ.get("PAPER_RUN_ONCE", "0") == "1":
            return True
        if os.environ.get("PAPER_AUTO_OPEN", "0") == "1":
            return True
        try:
            if int(os.environ.get("PAPER_AUTO_CLOSE_SEC", "0") or 0) > 0:
                return os.environ.get("LIVE", "0") != "1"
        except Exception as exc:
            logging.debug(
                "MarketDataFetcher: PAPER_AUTO_CLOSE_SEC parse failed: %s",
                exc,
            )
        return False

    def _mock_ohlcv_block_reason(
        self,
        *,
        runtime_mode=None,
        symbol=None,
        interval=None,
    ):
        import os

        if os.environ.get("USE_MOCK", "0") != "1":
            return None
        if not self._is_paper_runtime(runtime_mode=runtime_mode):
            return None
        # PAPER mock candles require a second explicit opt-in so that
        # USE_MOCK=1 alone cannot activate synthetic quotes in PAPER.
        if os.environ.get("ZOL0_ALLOW_MOCK", "0") == "1":
            return None

        symbol_txt = str(symbol or "").strip() or "<unknown>"
        interval_txt = str(interval or "").strip() or "<unknown>"
        market_type_txt = str(self.market_type or "").strip() or "<unset>"
        return (
            "MOCK_OHLCV_BLOCKED_KUCOIN_PAPER: KuCoin PAPER runtime blocked "
            "because USE_MOCK=1 would activate "
            "MarketDataFetcher.get_ohlcv() deterministic "
            "mock candles (close=100+i+0.1, volume=1000), "
            "which feed _quote_snapshot(...) as tick_stream_synth/static "
            "synthetic pricing. ZOL0_ALLOW_MOCK=1 is required to opt in "
            "explicitly. "
            f"api_url={self.api_url} market_type={market_type_txt} "
            f"symbol={symbol_txt} interval={interval_txt} "
            "blocked_source=MarketDataFetcher.get_ohlcv.mock_branch"
        )

    def assert_mock_ohlcv_allowed(
        self,
        *,
        runtime_mode=None,
        symbol=None,
        interval=None,
    ):
        reason = self._mock_ohlcv_block_reason(
            runtime_mode=runtime_mode,
            symbol=symbol,
            interval=interval,
        )
        if reason:
            logging.critical(reason)
            raise RuntimeError(reason)

    def _use_mock_enabled(self) -> bool:
        import os

        use_mock = os.environ.get("USE_MOCK", "0") == "1"
        if not use_mock:
            return False

        bot_mode = str(os.environ.get("BOT_MODE", "")).strip().lower()
        live_mode = os.environ.get("LIVE", "0") == "1" or bot_mode == "live"
        pytest_mode = "PYTEST_CURRENT_TEST" in os.environ
        paper_mode = self._is_paper_runtime()

        if live_mode:
            logging.warning(
                "MarketDataFetcher: USE_MOCK blocked in live mode "
                "(LIVE=1 or BOT_MODE=live)"
            )
            raise RuntimeError("USE_MOCK is not allowed in live mode")

        if paper_mode and os.environ.get("ZOL0_ALLOW_MOCK", "0") != "1":
            reason = self._mock_ohlcv_block_reason(runtime_mode="paper")
            logging.warning(
                "MarketDataFetcher: paper mock OHLCV requires explicit opt-in "
                "(ZOL0_ALLOW_MOCK=1)"
            )
            raise RuntimeError(reason or "MOCK_OHLCV_BLOCKED_KUCOIN_PAPER")

        if pytest_mode:
            logging.info("MarketDataFetcher: USE_MOCK enabled in test mode")
        elif paper_mode:
            logging.info("MarketDataFetcher: USE_MOCK enabled in paper mode")
        else:
            logging.info("MarketDataFetcher: USE_MOCK enabled in offline mode")

        return True

    def get_ohlcv(self, symbol, interval, limit=120):
        # ⬆️ optimized for performance: use list comprehension for candles
        from core.kucoin_futures_client import KucoinFuturesClient

        symbol_norm, interval_str, limit = self._resolve_ohlcv_request(
            symbol, interval, limit
        )
        params = {"symbol": symbol_norm, "type": interval_str, "limit": limit}
        self.assert_mock_ohlcv_allowed(symbol=symbol_norm, interval=interval_str)
        use_mock = self._use_mock_enabled()
        if self._is_futures(symbol) and not use_mock:
            logging.info(
                "MarketDataFetcher: futures OHLCV (KucoinFuturesClient) "
                "symbol=%s type=%s limit=%s",
                str(symbol),
                str(interval_str),
                str(limit),
            )
            futures_client = KucoinFuturesClient()
            return futures_client.get_klines(symbol, interval_str, limit=limit)
        logging.info(
            f"MarketDataFetcher: Requesting OHLCV with params: {params} | "
            f"URL: {self.api_url}"
        )
        if use_mock:
            # Deterministic offline mock data for PAPER mode
            candles = []
            ts = int(time.time())
            for i in range(limit):
                candles.append(
                    {
                        "timestamp": ts - (limit - i) * 60,
                        "open": float(100 + i),
                        "high": float(100 + i + 0.5),
                        "low": float(100 + i - 0.5),
                        "close": float(100 + i + 0.1),
                        "volume": float(1000),
                    }
                )
            return candles
        for attempt in range(1, self.max_retries + 1):
            now = time.time()
            if now - self.last_call < self.throttle_sec:
                time.sleep(self.throttle_sec - (now - self.last_call))
            self.last_call = time.time()
            try:
                response = requests.get(
                    self.api_url,
                    params=params,
                    timeout=10,
                )
                logging.info(
                    (
                        "MarketDataFetcher: Raw API response (status "
                        f"{response.status_code}): "
                        f"{response.text}"
                    )
                )
                response.raise_for_status()
                data = response.json()
                if "result" in data and "list" in data["result"]:
                    candles = []
                    skipped_rows = 0
                    for item in data["result"]["list"]:
                        candle = self._coerce_candle_row(item, layout="result")
                        if candle is None:
                            skipped_rows += 1
                            continue
                        candles.append(candle)
                    if skipped_rows:
                        logging.warning(
                            (
                                "MarketDataFetcher: skipped %s malformed KuCoin "
                                "candle rows from result.list"
                            ),
                            skipped_rows,
                        )
                    return candles
                if "data" in data and isinstance(data["data"], list):
                    candles = []
                    skipped_rows = 0
                    for item in data["data"]:
                        candle = self._coerce_candle_row(item, layout="data")
                        if candle is None:
                            skipped_rows += 1
                            continue
                        candles.append(candle)
                    if skipped_rows:
                        logging.warning(
                            (
                                "MarketDataFetcher: skipped %s malformed KuCoin "
                                "candle rows from data"
                            ),
                            skipped_rows,
                        )
                    return candles
                logging.error(f"Exchange response missing result/list or data: {data}")
                return []
            except Exception as e:
                logging.error(
                    "MarketDataFetcher: Exception for %s at %s: %s"
                    % (
                        symbol,
                        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                        str(e),
                    )
                )
        logging.error(f"MarketDataFetcher: All attempts failed for {symbol} {interval}")
        return []

    def fetch_data(self, symbol, interval, limit=120, runtime_mode=None):
        symbol_norm, interval_str, resolved_limit = self._resolve_ohlcv_request(
            symbol, interval, limit
        )
        cache_ttl = float(self._fetch_cache_sec or 0.0)
        if cache_ttl <= 0:
            return self.get_ohlcv(symbol, interval, limit=resolved_limit)

        cache_key = self._fetch_data_cache_key(
            symbol_norm,
            interval_str,
            resolved_limit,
            runtime_mode=runtime_mode,
        )
        now = time.time()
        with self._fetch_cache_lock:
            cached = self._fetch_cache.get(cache_key)
            if cached is not None:
                cached_ts, cached_candles = cached
                if now - cached_ts <= cache_ttl:
                    return self._clone_candles(cached_candles)

        candles = self.get_ohlcv(symbol, interval, limit=resolved_limit)
        cloned = self._clone_candles(candles)
        with self._fetch_cache_lock:
            self._fetch_cache[cache_key] = (time.time(), cloned)
        return self._clone_candles(cloned)
