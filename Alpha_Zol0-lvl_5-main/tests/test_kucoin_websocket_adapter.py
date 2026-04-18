import json

import pytest

from platforms.kucoin_websocket_adapter import KucoinWebSocketAdapter


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, timeout):
        self.calls.append({"url": url, "timeout": timeout})
        return _FakeResponse(self.payload)


class _FakeWebSocketApp:
    def __init__(
        self,
        url,
        on_open=None,
        on_message=None,
        on_error=None,
        on_close=None,
    ):
        self.url = url
        self.on_open = on_open
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def run_forever(self):
        if self.on_open is not None:
            self.on_open(self)

    def close(self):
        self.closed = True


def test_kucoin_websocket_adapter_connects_and_subscribes_to_futures_ticker_v2():
    payload = {
        "code": "200000",
        "data": {
            "token": "token-123",
            "instanceServers": [
                {
                    "endpoint": "wss://ws-api-futures.kucoin.com/",
                    "pingInterval": 18000,
                    "pingTimeout": 10000,
                }
            ],
        },
    }
    session = _FakeSession(payload)
    events = []

    adapter = KucoinWebSocketAdapter(
        session=session,
        websocket_app_factory=_FakeWebSocketApp,
        connect_id_factory=lambda: "cid-1",
        event_handler=events.append,
    )

    state = adapter.connect(["BTCUSDTM"], start_background=False)
    assert state["market_type"] == "futures"
    assert (
        session.calls[0]["url"]
        == "https://api-futures.kucoin.com/api/v1/bullet-public"
    )
    assert (
        adapter._ws_app.url
        == "wss://ws-api-futures.kucoin.com?token=token-123&connectId=cid-1"
    )

    adapter._on_message(adapter._ws_app, json.dumps({"type": "welcome"}))

    assert adapter.connected is True
    assert adapter._ws_app.sent[0]["topic"] == "/contractMarket/tickerV2:XBTUSDTM"
    assert events[0]["status"] == "connected"

    adapter._on_message(
        adapter._ws_app,
        json.dumps(
            {
                "type": "message",
                "topic": "/contractMarket/tickerV2:XBTUSDTM",
                "subject": "tickerV2",
                "data": {
                    "symbol": "XBTUSDTM",
                    "bestBidPrice": "100.1",
                    "bestAskPrice": "100.3",
                    "bestBidSize": 5,
                    "bestAskSize": 7,
                    "ts": 1740641976241000000,
                },
            }
        ),
    )

    market = adapter.get_latest_market("BTCUSDTM")
    assert market["symbol"] == "BTCUSDTM"
    assert market["exchange_symbol"] == "XBTUSDTM"
    assert market["price"] == pytest.approx(100.2)
    assert events[-1]["market"]["source"] == "kucoin_websocket"
    adapter.close()


def test_kucoin_websocket_adapter_supports_spot_topics():
    payload = {
        "code": "200000",
        "data": {
            "token": "token-spot",
            "instanceServers": [
                {
                    "endpoint": "wss://ws-api-spot.kucoin.com/",
                    "pingInterval": 18000,
                    "pingTimeout": 10000,
                }
            ],
        },
    }
    session = _FakeSession(payload)
    adapter = KucoinWebSocketAdapter(
        market_type="spot",
        session=session,
        websocket_app_factory=_FakeWebSocketApp,
        connect_id_factory=lambda: "cid-spot",
    )

    adapter.connect(["BTC-USDT"], start_background=False)
    adapter._on_message(adapter._ws_app, json.dumps({"type": "welcome"}))

    assert adapter._ws_app.sent[0]["topic"] == "/market/ticker:BTC-USDT"
    adapter.close()
