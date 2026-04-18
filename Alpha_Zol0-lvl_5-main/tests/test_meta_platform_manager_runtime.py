import logging

import pytest

from platforms.MetaPlatformManager import MetaPlatformManager


class _FakeKucoinApi:
    def get_balance(self):
        return {"balance": 42.0}

    def get_positions(self):
        return [{"symbol": "BTCUSDT", "side": "buy"}]

    def get_market_data(self, symbol):
        return {
            "symbol": symbol,
            "price": 123.45,
            "timestamp": "2026-04-18T00:00:00+00:00",
        }


class _FakeWebSocketAdapter:
    def __init__(self):
        self.connected = False
        self.market_type = "futures"
        self.handler = None
        self.connected_symbols = []
        self.latest_market = {
            "BTCUSDTM": {
                "symbol": "BTCUSDTM",
                "price": 222.22,
                "bestBidPrice": "222.2",
                "bestAskPrice": "222.24",
                "source": "kucoin_websocket",
            }
        }

    def set_event_handler(self, handler):
        self.handler = handler

    def connect(self, symbols):
        self.connected = True
        self.connected_symbols = list(symbols)
        if self.handler is not None:
            self.handler(
                {
                    "status": "connected",
                    "market": self.latest_market["BTCUSDTM"],
                }
            )

    def get_latest_market(self, symbol):
        return self.latest_market.get(symbol)

    def close(self):
        self.connected = False


def test_meta_platform_manager_syncs_registered_platform_state(caplog):
    caplog.set_level(logging.INFO)
    manager = MetaPlatformManager()
    manager.register_platform("kucoin", api=_FakeKucoinApi(), websocket=object())

    state = manager.sync_platform_state("kucoin", symbol="BTCUSDT")

    assert state["balance"]["balance"] == 42.0
    assert state["positions"][0]["symbol"] == "BTCUSDT"
    assert state["market"]["price"] == 123.45
    assert state["websocket_connected"] is True
    assert "platform_state name=kucoin source=api" in caplog.text


def test_meta_platform_manager_handles_websocket_event_merge():
    manager = MetaPlatformManager()
    manager.register_platform("kucoin", api=_FakeKucoinApi(), websocket=object())

    state = manager.handle_platform_event(
        "kucoin",
        {
            "market": {"symbol": "BTCUSDT", "price": 99.0},
            "status": "connected",
        },
    )

    assert state["market"]["price"] == 99.0
    assert state["status"] == "connected"
    assert state["last_sync_source"] == "websocket"


def test_meta_platform_manager_sync_requires_registered_platform():
    manager = MetaPlatformManager()

    with pytest.raises(KeyError, match="Platform not registered"):
        manager.sync_platform_state("kucoin")


def test_meta_platform_manager_auto_attaches_default_websocket(monkeypatch):
    manager = MetaPlatformManager()
    fake_websocket = _FakeWebSocketAdapter()
    monkeypatch.setattr(
        manager,
        "_build_default_websocket",
        lambda name, market_type=None: fake_websocket,
    )

    manager.register_platform("kucoin", api=_FakeKucoinApi())

    state = manager.get_platform_state("kucoin")
    assert state["websocket_adapter"] == "_FakeWebSocketAdapter"
    assert state["websocket_market_type"] == "futures"


def test_meta_platform_manager_starts_stream_and_prefers_websocket_market(monkeypatch):
    manager = MetaPlatformManager()
    fake_websocket = _FakeWebSocketAdapter()
    monkeypatch.setattr(
        manager,
        "_build_default_websocket",
        lambda name, market_type=None: fake_websocket,
    )
    manager.register_platform("kucoin", api=_FakeKucoinApi())

    state = manager.start_platform_stream("kucoin", ["BTCUSDTM"])
    market = manager.get_market_data("BTCUSDTM")

    assert state["websocket_symbols"] == ["BTCUSDTM"]
    assert market["price"] == 222.22
    assert manager.get_platform_state("kucoin")["last_market_source"] == "websocket"
    assert fake_websocket.connected_symbols == ["BTCUSDTM"]


def test_meta_platform_manager_stops_stream(monkeypatch):
    manager = MetaPlatformManager()
    fake_websocket = _FakeWebSocketAdapter()
    monkeypatch.setattr(
        manager,
        "_build_default_websocket",
        lambda name, market_type=None: fake_websocket,
    )
    manager.register_platform("kucoin", api=_FakeKucoinApi())
    manager.start_platform_stream("kucoin", ["BTCUSDTM"])

    state = manager.stop_platform_stream("kucoin")

    assert state["status"] == "disconnected"
    assert state["websocket_connected"] is False
