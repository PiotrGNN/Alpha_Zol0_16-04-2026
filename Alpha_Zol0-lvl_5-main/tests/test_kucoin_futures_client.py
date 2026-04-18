import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.kucoin_futures_client import KucoinFuturesClient


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class DummySession:
    def __init__(self, payload):
        self.payload = payload
        self.last_request = None

    def request(self, method, url, params=None, data=None, headers=None, timeout=None):
        self.last_request = {
            "method": method,
            "url": url,
            "params": params,
            "data": data,
            "headers": headers,
            "timeout": timeout,
        }
        return DummyResponse(self.payload)


def test_futures_ticker_uses_futures_base_url():
    payload = {"code": "200000", "data": {"price": "100"}}
    session = DummySession(payload)
    client = KucoinFuturesClient(
        api_key="k",
        api_secret="s",
        api_passphrase="p",
        session=session,
    )
    client.get_ticker("BTCUSDTM")
    assert session.last_request["url"].startswith("https://api-futures.kucoin.com")
    assert session.last_request["url"].endswith("/api/v1/ticker")
    assert session.last_request["params"]["symbol"] == "XBTUSDTM"


def test_futures_klines_uses_kline_endpoint_and_granularity():
    payload = {"code": "200000", "data": [[1, "1", "2", "3", "4", "5", "6"]]}
    session = DummySession(payload)
    client = KucoinFuturesClient(
        api_key="k",
        api_secret="s",
        api_passphrase="p",
        session=session,
    )
    client.get_klines("BTCUSDTM", "1min", limit=2)
    assert session.last_request["url"].startswith("https://api-futures.kucoin.com")
    assert session.last_request["url"].endswith("/api/v1/kline/query")
    assert session.last_request["params"]["symbol"] == "XBTUSDTM"
    assert session.last_request["params"]["granularity"] == 1
    assert "from" in session.last_request["params"]
    assert "to" in session.last_request["params"]


def test_futures_kline_field_order_parsing():
    # Example order: [time, open, high, low, close, volume, turnover]
    payload = {
        "code": "200000",
        "data": [
            [
                1757659080000,
                "115328.4",
                "115328.5",
                "115328.3",
                "115328.5",
                "10",
                "9999",
            ]
        ],
    }
    session = DummySession(payload)
    client = KucoinFuturesClient(
        api_key="k",
        api_secret="s",
        api_passphrase="p",
        session=session,
    )
    candles = client.get_klines("BTCUSDTM", "1min", limit=1)
    assert candles[0]["timestamp"] == 1757659080000
    assert candles[0]["open"] == 115328.4
    assert candles[0]["high"] == 115328.5
    assert candles[0]["low"] == 115328.3
    assert candles[0]["close"] == 115328.5
    assert candles[0]["volume"] == 10.0
    assert candles[0]["turnover"] == 9999.0


def test_futures_account_overview_uses_futures_endpoint():
    payload = {"code": "200000", "data": {"availableBalance": "1", "frozenFunds": "0"}}
    session = DummySession(payload)
    client = KucoinFuturesClient(
        api_key="k",
        api_secret="s",
        api_passphrase="p",
        session=session,
    )
    client.get_account_overview(currency="USDT")
    assert session.last_request["url"].startswith("https://api-futures.kucoin.com")
    assert session.last_request["url"].endswith("/api/v1/account-overview")
    assert session.last_request["params"]["currency"] == "USDT"
