# ZoL0 LEVEL 0
# test_marketdata_fetcher.py – pytest do get_ohlcv
import logging

import pytest

from core.MarketDataFetcher import MarketDataFetcher


def test_get_ohlcv(monkeypatch):
    """Testuje mockową funkcję get_ohlcv."""
    monkeypatch.setenv("USE_MOCK", "True")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    fetcher = MarketDataFetcher()
    data = fetcher.get_ohlcv("BTCUSDT", "1m")
    assert isinstance(data, list)
    assert len(data) > 0
    for candle in data:
        assert "open" in candle and "close" in candle


def test_paper_mock_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.delenv("ZOL0_ALLOW_MOCK", raising=False)
    fetcher = MarketDataFetcher()

    with pytest.raises(RuntimeError, match="MOCK_OHLCV_BLOCKED_KUCOIN_PAPER"):
        fetcher.get_ohlcv("BTCUSDTM", "1m")


def test_use_mock_blocked_in_live_mode(monkeypatch, caplog):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("LIVE", "1")
    fetcher = MarketDataFetcher()

    with pytest.raises(RuntimeError, match="USE_MOCK is not allowed in live mode"):
        fetcher.get_ohlcv("BTCUSDT", "1m")

    assert "USE_MOCK blocked in live mode" in caplog.text


def test_use_mock_blocked_in_live_bot_mode(monkeypatch, caplog):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("BOT_MODE", "live")
    fetcher = MarketDataFetcher()

    with pytest.raises(RuntimeError, match="USE_MOCK is not allowed in live mode"):
        fetcher.get_ohlcv("BTCUSDT", "1m")

    assert "USE_MOCK blocked in live mode" in caplog.text


def test_use_mock_allowed_in_paper_mode(monkeypatch, caplog):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("BOT_MODE", "paper")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    caplog.set_level(logging.INFO)
    fetcher = MarketDataFetcher()

    data = fetcher.get_ohlcv("BTCUSDT", "1m", limit=3)

    assert len(data) == 3
    assert (
        "USE_MOCK enabled in test mode" in caplog.text
        or "USE_MOCK enabled in paper mode" in caplog.text
    )


def test_fetch_data_reuses_recent_result(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_FETCH_CACHE_SEC", "10")
    fetcher = MarketDataFetcher()
    calls = {"count": 0}

    def fake_get_ohlcv(symbol, interval, limit=120):
        calls["count"] += 1
        return [
            {
                "timestamp": 1,
                "open": 1,
                "close": 1,
                "high": 1,
                "low": 1,
                "volume": 1,
            }
        ]

    monkeypatch.setattr(fetcher, "get_ohlcv", fake_get_ohlcv)

    first = fetcher.fetch_data("BTCUSDT", "1m", limit=2)
    second = fetcher.fetch_data("BTCUSDT", "1m", limit=2)

    assert calls["count"] == 1
    assert first == second
    assert first is not second


def test_fetch_data_respects_mock_opt_in_cache_key(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_FETCH_CACHE_SEC", "10")
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("PAPER_RUN_ONCE", "1")
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")
    fetcher = MarketDataFetcher()

    first = fetcher.fetch_data("BTCUSDTM", "1m", limit=2)
    monkeypatch.delenv("ZOL0_ALLOW_MOCK", raising=False)

    with pytest.raises(RuntimeError, match="MOCK_OHLCV_BLOCKED_KUCOIN_PAPER"):
        fetcher.fetch_data("BTCUSDTM", "1m", limit=2)

    assert len(first) == 2


def test_use_mock_warns_outside_pytest(monkeypatch, caplog):
    monkeypatch.setenv("USE_MOCK", "True")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    caplog.set_level(logging.WARNING)

    fetcher = MarketDataFetcher()
    data = fetcher.get_ohlcv("BTCUSDT", "1m", limit=2)

    assert len(data) == 2
    assert "USE_MOCK enabled outside pytest runtime=offline" in caplog.text
