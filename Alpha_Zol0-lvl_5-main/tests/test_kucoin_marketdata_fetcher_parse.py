# KuCoin MarketDataFetcher parse (no real network)
from core.MarketDataFetcher import MarketDataFetcher


def test_kucoin_marketdata_fetcher_parse(monkeypatch):
    import requests

    class MockResp:
        status_code = 200
        text = "ok"

        def json(self):
            return {
                "code": "200000",
                "data": [
                    ["1700000000", "100", "101", "102", "99", "10", "1000"],
                    ["1700000060", "101", "102", "103", "100", "11", "1100"],
                ],
            }

        def raise_for_status(self):
            return None

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: MockResp())
    monkeypatch.setenv("USE_MOCK", "0")

    fetcher = MarketDataFetcher()
    data = fetcher.get_ohlcv("BTC-USDT", "1min", limit=2)
    assert isinstance(data, list) and len(data) == 2
    candle = data[0]
    for key in ("timestamp", "open", "high", "low", "close", "volume"):
        assert key in candle


def test_kucoin_marketdata_fetcher_skips_malformed_rows(monkeypatch):
    import requests

    class MockResp:
        status_code = 200
        text = "ok"

        def json(self):
            return {
                "code": "200000",
                "result": {
                    "list": [
                        ["1700000000", "100", "101", "102", "99", "10"],
                        ["bad-row"],
                    ]
                },
            }

        def raise_for_status(self):
            return None

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: MockResp())
    monkeypatch.setenv("USE_MOCK", "0")

    fetcher = MarketDataFetcher()
    data = fetcher.get_ohlcv("BTC-USDT", "1min", limit=2)

    assert isinstance(data, list)
    assert len(data) == 1
    candle = data[0]
    assert candle["timestamp"] == "1700000000"
    assert candle["open"] == 100.0
    assert candle["high"] == 101.0
    assert candle["low"] == 102.0
    assert candle["close"] == 99.0
    assert candle["volume"] == 10.0
