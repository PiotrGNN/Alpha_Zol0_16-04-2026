import time as _time

import pytest

import core.BotCore as botcore
import core.InfinityLayerLogger as ill
import core.MarketDataFetcher as mdf
import core.kucoin_futures_client as kfc
from core.paper_quote_source import (
    _safe_float,
    _safe_tick_ts,
    fetch_kucoin_paper_quote,
    normalize_kucoin_paper_quote,
)


def _fake_config(_path):
    return {
        "api_key": None,
        "api_secret": None,
        "balance": 1000.0,
        "retrain_interval": 10000000,
        "sl_pct": 0.5,
        "tp_pct": 1.0,
        "symbol": "BTCUSDTM",
        "timeframe": 1,
        "market_type": "futures",
    }


def _fake_candles(limit=120):
    base_ts = 1_700_000_000
    out = []
    for i in range(limit):
        price = 66_900.0 + float(i) * 0.5
        out.append(
            {
                "timestamp": base_ts + (i * 60),
                "open": price - 1.0,
                "high": price + 2.0,
                "low": price - 2.0,
                "close": price,
                "volume": 100.0 + float(i),
            }
        )
    return out


def _run_paper_cycle(monkeypatch, *, ticker_payload=None, ticker_exception=None, require_real=False):
    import utils.news_social_scheduler as nss

    monkeypatch.setenv("USE_MOCK", "0")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("PAPER_SIM_BALANCE_FALLBACK_ONLY", "1")
    monkeypatch.setenv("RUN_SYMBOLS", "BTCUSDTM")
    monkeypatch.setenv("MARKET_TYPE", "futures")
    monkeypatch.setenv("BALANCE_CACHE_SEC", "0")
    monkeypatch.setenv("ZOL0_TOKEN", "test-token")
    if require_real:
        monkeypatch.setenv("PAPER_REQUIRE_REAL_QUOTE_PATH", "1")
    else:
        monkeypatch.delenv("PAPER_REQUIRE_REAL_QUOTE_PATH", raising=False)

    monkeypatch.setattr(botcore, "load_config", _fake_config)
    monkeypatch.setattr(botcore, "save_decision_to_db", lambda *a, **k: True)
    monkeypatch.setattr(botcore, "save_equity_to_db", lambda *a, **k: True)
    monkeypatch.setattr(nss.NewsSocialScheduler, "start", lambda self: None)
    monkeypatch.setattr(_time, "time", lambda: 1_700_000_000)
    monkeypatch.setattr(
        mdf.MarketDataFetcher,
        "get_ohlcv",
        lambda self, symbol, interval, limit=120: _fake_candles(limit=limit),
    )

    if ticker_exception is not None:
        def _raise_ticker(self, symbol):
            raise ticker_exception
        monkeypatch.setattr(kfc.KucoinFuturesClient, "get_ticker", _raise_ticker)
    else:
        monkeypatch.setattr(
            kfc.KucoinFuturesClient,
            "get_ticker",
            lambda self, symbol: dict(ticker_payload or {}),
        )

    captured = []

    def _capture_log(self, event, details=None):
        captured.append({"event": event, "details": details})

    monkeypatch.setattr(ill.InfinityLayerLogger, "log", _capture_log)

    botcore.run_bot(simulate=True)
    return captured


def test_paper_real_quote_path_selected(monkeypatch):
    captured = _run_paper_cycle(
        monkeypatch,
        ticker_payload={
            "price": "67000.0",
            "bestBidPrice": "66999.5",
            "bestAskPrice": "67000.5",
            "bestBidSize": "12.0",
            "bestAskSize": "9.0",
            "ts": 1_700_000_000_500,
        },
    )
    paper_quote_events = [
        item for item in captured if item.get("event") == "paper_quote_source"
    ]
    assert paper_quote_events
    details = paper_quote_events[-1]["details"] or {}
    assert details["upstream_source"] == "kucoin_futures_ticker"
    assert details["quote_path_classification"] == "real_exchange_quote"
    assert details["fetch_status"] == "ok"
    assert details["l1_quote_ts"] == 1_700_000_000_500
    assert details["bid"] == 66999.5
    assert details["ask"] == 67000.5
    assert details["best_bid_size_source"] == "exchange_l1"
    assert details["best_ask_size_source"] == "exchange_l1"


def test_paper_synthetic_fallback_explicitly_labeled(monkeypatch):
    captured = _run_paper_cycle(
        monkeypatch,
        ticker_payload={
            "price": "67000.0",
            "ts": 1_700_000_000_500,
        },
    )
    paper_quote_events = [
        item for item in captured if item.get("event") == "paper_quote_source"
    ]
    assert paper_quote_events
    details = paper_quote_events[-1]["details"] or {}
    assert details["upstream_source"] == "kucoin_futures_ticker"
    assert details["quote_path_classification"] == "synthetic_fallback"
    assert details["fetch_status"] == "missing_bid_ask"
    assert details["synthetic_fallback_reason"] == "missing_bid_ask_from_kucoin_quote"


def test_paper_spot_quote_path_selected():
    normalized = normalize_kucoin_paper_quote(
        "ETHUSDT",
        {
            "bestBidPrice": "3200.1",
            "bestAskPrice": "3200.9",
            "bestBidSize": "5.0",
            "bestAskSize": "4.0",
            "ts": 1_700_000_000_500,
        },
    )

    assert normalized["upstream_source"] == "kucoin_spot_level1"
    assert normalized["quote_path_classification"] == "real_exchange_quote"
    assert normalized["fetch_status"] == "ok"
    assert normalized["best_bid_size_source"] == "exchange_l1"
    assert normalized["best_ask_size_source"] == "exchange_l1"
    assert normalized["l1_quote_ts"] == 1_700_000_000_500


def test_paper_quote_non_dict_payload_is_explicitly_synthetic():
    normalized = normalize_kucoin_paper_quote("BTCUSDTM", ["not", "a", "dict"])

    assert normalized["quote_path_classification"] == "synthetic_fallback"
    assert normalized["fetch_status"] == "non_dict_payload"
    assert normalized["synthetic_fallback_reason"] == "quote_payload_non_dict"


def test_fetch_kucoin_paper_quote_exception_is_synthetic():
    class BoomFuturesClient:
        def get_ticker(self, symbol):
            raise RuntimeError("boom")

    result = fetch_kucoin_paper_quote("BTCUSDTM", futures_client=BoomFuturesClient())

    assert result["quote_path_classification"] == "synthetic_fallback"
    assert result["fetch_status"] == "exception"
    assert result["synthetic_fallback_reason"] == "quote_fetch_exception:RuntimeError"


def test_paper_quote_source_helper_edges():
    assert _safe_float("nan") is None
    assert _safe_float("12.5") == 12.5
    assert _safe_float("bad") is None
    assert _safe_tick_ts("1700000000") == 1_700_000_000_000
    assert _safe_tick_ts("1700000000000") == 1_700_000_000_000
    assert _safe_tick_ts("1700000000000000") == 1_700_000_000_000
    assert _safe_tick_ts("1700000000000000000") == 1_700_000_000_000
    assert _safe_tick_ts("-5") == 5_000
    assert _safe_tick_ts("0") is None


def test_paper_quote_source_helper_int_cast_failure(monkeypatch):
    import core.paper_quote_source as pqs

    monkeypatch.setattr(
        pqs,
        "int",
        lambda value: (_ for _ in ()).throw(RuntimeError("int boom")),
        raising=False,
    )
    assert _safe_tick_ts("1700000000") is None


def test_fetch_kucoin_paper_quote_sets_raw_payload_type():
    class DummyFuturesClient:
        def get_ticker(self, symbol):
            return {
                "bestBidPrice": "100.0",
                "bestAskPrice": "101.0",
                "bestBidSize": "2.0",
                "bestAskSize": "3.0",
                "ts": 1_700_000_000_500,
            }

    result = fetch_kucoin_paper_quote(
        "BTCUSDTM", futures_client=DummyFuturesClient()
    )

    assert result["raw_payload_type"] == "dict"
    assert result["quote_path_classification"] == "real_exchange_quote"


def test_fetch_kucoin_paper_quote_spot_path_uses_spot_client():
    class DummySpotClient:
        def get_level1_orderbook(self, symbol):
            return {
                "bestBidPrice": "3000.1",
                "bestAskPrice": "3000.9",
                "bestBidSize": "1.0",
                "bestAskSize": "2.0",
                "timestamp": 1_700_000_000_500,
            }

    result = fetch_kucoin_paper_quote("ETHUSDT", spot_client=DummySpotClient())

    assert result["upstream_source"] == "kucoin_spot_level1"
    assert result["quote_path_classification"] == "real_exchange_quote"
    assert result["fetch_status"] == "ok"
    assert result["raw_payload_type"] == "dict"


def test_fetch_kucoin_paper_quote_futures_path_uses_futures_client():
    class DummyFuturesClient:
        def get_ticker(self, symbol):
            return {
                "price": "100.0",
                "bestBidPrice": "99.5",
                "bestAskPrice": "100.5",
                "bestBidSize": "1.0",
                "bestAskSize": "2.0",
                "ts": 1_700_000_000_500,
            }

    result = fetch_kucoin_paper_quote(
        "BTCUSDTM", futures_client=DummyFuturesClient()
    )

    assert result["upstream_source"] == "kucoin_futures_ticker"
    assert result["quote_path_classification"] == "real_exchange_quote"
    assert result["fetch_status"] == "ok"
    assert result["raw_payload_type"] == "dict"


def test_paper_real_quote_required_hard_fails_when_only_fallback_available(monkeypatch):
    with pytest.raises(RuntimeError, match="PAPER_REAL_QUOTE_PATH_REQUIRED"):
        _run_paper_cycle(
            monkeypatch,
            ticker_payload={
                "price": "67000.0",
                "ts": 1_700_000_000_500,
            },
            require_real=True,
        )
