from __future__ import annotations

import json
import logging
import threading
import uuid
from copy import deepcopy
from typing import Any, Callable, Iterable

import requests
import websocket

from core.kucoin_client import normalize_symbol
from core.kucoin_futures_client import is_futures_symbol, normalize_futures_symbol
from core.paper_quote_source import normalize_kucoin_paper_quote

SPOT_BULLET_PUBLIC_URL = "https://api.kucoin.com/api/v1/bullet-public"
FUTURES_BULLET_PUBLIC_URL = "https://api-futures.kucoin.com/api/v1/bullet-public"


class KucoinWebSocketAdapter:
    def __init__(
        self,
        *,
        market_type: str = "futures",
        session: requests.Session | None = None,
        websocket_app_factory: Callable[..., Any] | None = None,
        connect_id_factory: Callable[[], str] | None = None,
        event_handler: Callable[[dict[str, Any]], None] | None = None,
        timeout: float = 5.0,
    ):
        self.market_type = str(market_type or "futures").strip().lower() or "futures"
        self._session = session or requests.Session()
        self._websocket_app_factory = websocket_app_factory or websocket.WebSocketApp
        self._connect_id_factory = connect_id_factory or (lambda: uuid.uuid4().hex)
        self._event_handler = event_handler
        self.timeout = timeout

        self.connected = False
        self._ws_app = None
        self._runner_thread = None
        self._heartbeat_thread = None
        self._stop_event = threading.Event()
        self._state_lock = threading.RLock()
        self._connect_context: dict[str, Any] = {}
        self._symbols: list[str] = []
        self._symbol_aliases: dict[str, str] = {}
        self._latest_market: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _clone(value):
        return deepcopy(value)

    def set_event_handler(self, handler: Callable[[dict[str, Any]], None] | None):
        self._event_handler = handler

    def _emit(self, event: dict[str, Any]):
        if self._event_handler is None:
            return
        try:
            self._event_handler(self._clone(event))
        except Exception as exc:
            logging.warning(
                "KucoinWebSocketAdapter: event handler failed error=%s event=%s",
                exc,
                event,
            )

    def _uses_futures_market(self, symbol: str | None = None) -> bool:
        if self.market_type == "futures":
            return True
        if self.market_type == "spot":
            return False
        return bool(symbol) and is_futures_symbol(symbol)

    def _normalize_exchange_symbol(self, symbol: str) -> str:
        if self._uses_futures_market(symbol):
            return normalize_futures_symbol(symbol)
        return normalize_symbol(symbol)

    def _topic_for_symbol(self, symbol: str) -> str:
        exchange_symbol = self._normalize_exchange_symbol(symbol)
        if self._uses_futures_market(symbol):
            return f"/contractMarket/tickerV2:{exchange_symbol}"
        return f"/market/ticker:{exchange_symbol}"

    def _bullet_public_url(self) -> str:
        if self.market_type == "spot":
            return SPOT_BULLET_PUBLIC_URL
        return FUTURES_BULLET_PUBLIC_URL

    def _request_connect_context(self) -> dict[str, Any]:
        response = self._session.post(self._bullet_public_url(), timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("code") != "200000":
            raise RuntimeError(f"KuCoin websocket token request failed: {payload}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("KuCoin websocket token response missing data")
        servers = data.get("instanceServers")
        if not isinstance(servers, list) or not servers:
            raise RuntimeError(
                "KuCoin websocket token response missing instanceServers"
            )
        return {
            "token": data.get("token"),
            "server": servers[0],
            "connect_id": self._connect_id_factory(),
        }

    def _socket_url(self) -> str:
        server = self._connect_context.get("server") or {}
        endpoint = str(server.get("endpoint") or "").rstrip("/")
        token = self._connect_context.get("token")
        connect_id = self._connect_context.get("connect_id")
        if not endpoint or not token or not connect_id:
            raise RuntimeError("KuCoin websocket context is incomplete")
        return f"{endpoint}?token={token}&connectId={connect_id}"

    def _heartbeat_interval_sec(self) -> float:
        server = self._connect_context.get("server") or {}
        try:
            interval_ms = float(server.get("pingInterval") or 18000)
        except Exception:
            interval_ms = 18000.0
        return max(1.0, interval_ms / 1000.0)

    def _send_json(self, payload: dict[str, Any]):
        if self._ws_app is None:
            return
        self._ws_app.send(json.dumps(payload))

    def _subscription_message(self, symbol: str) -> dict[str, Any]:
        return {
            "id": self._connect_id_factory(),
            "type": "subscribe",
            "topic": self._topic_for_symbol(symbol),
            "privateChannel": False,
            "response": True,
        }

    def _start_heartbeat(self):
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        interval = self._heartbeat_interval_sec()

        def _loop():
            while not self._stop_event.wait(interval):
                if not self.connected:
                    continue
                try:
                    self._send_json({"id": self._connect_id_factory(), "type": "ping"})
                except Exception as exc:
                    logging.warning(
                        "KucoinWebSocketAdapter: heartbeat send failed error=%s",
                        exc,
                    )
                    return

        self._heartbeat_thread = threading.Thread(
            target=_loop,
            name=f"kucoin-websocket-heartbeat-{self.market_type}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _normalize_market_event(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        data = payload.get("data")
        if not isinstance(data, dict):
            return None

        exchange_symbol = str(data.get("symbol") or "").strip()
        if not exchange_symbol:
            topic = str(payload.get("topic") or "")
            exchange_symbol = topic.rsplit(":", 1)[-1].split(",", 1)[0].strip()
        requested_symbol = self._symbol_aliases.get(exchange_symbol, exchange_symbol)
        if not requested_symbol:
            return None

        market = normalize_kucoin_paper_quote(requested_symbol, data)
        market["symbol"] = requested_symbol
        market["exchange_symbol"] = exchange_symbol
        market["topic"] = payload.get("topic")
        market["subject"] = payload.get("subject")
        market["price"] = market.get("last_trade_price") or market.get("mid")
        market["timestamp"] = market.get("l1_quote_ts")
        market["source"] = "kucoin_websocket"

        with self._state_lock:
            self._latest_market[requested_symbol] = self._clone(market)
            self._latest_market[exchange_symbol] = self._clone(market)

        return {
            "status": "streaming",
            "market": market,
            "topic": payload.get("topic"),
            "subject": payload.get("subject"),
            "transport": "kucoin_websocket",
            "raw_event": payload,
        }

    def _on_open(self, ws_app):
        logging.info(
            "KucoinWebSocketAdapter: transport open market_type=%s symbols=%s",
            self.market_type,
            self._symbols,
        )

    def _on_message(self, ws_app, message):
        try:
            payload = json.loads(message)
        except Exception as exc:
            logging.warning(
                "KucoinWebSocketAdapter: invalid message error=%s message=%s",
                exc,
                message,
            )
            return

        message_type = str(payload.get("type") or "").lower()
        if message_type == "welcome":
            self.connected = True
            self._start_heartbeat()
            for symbol in self._symbols:
                self._send_json(self._subscription_message(symbol))
            self._emit(
                {
                    "status": "connected",
                    "transport": "kucoin_websocket",
                    "market_type": self.market_type,
                    "symbols": list(self._symbols),
                    "raw_event": payload,
                }
            )
            return

        if message_type == "ack":
            self._emit(
                {
                    "status": "subscribed",
                    "transport": "kucoin_websocket",
                    "raw_event": payload,
                }
            )
            return

        if message_type == "message":
            event = self._normalize_market_event(payload)
            if event is not None:
                self._emit(event)
            return

        if message_type == "pong":
            self._emit(
                {
                    "status": "heartbeat",
                    "transport": "kucoin_websocket",
                    "raw_event": payload,
                }
            )
            return

        if message_type == "error":
            self._emit(
                {
                    "status": "error",
                    "transport": "kucoin_websocket",
                    "raw_event": payload,
                }
            )

    def _on_error(self, ws_app, error):
        self._emit(
            {
                "status": "error",
                "transport": "kucoin_websocket",
                "error": str(error),
            }
        )

    def _on_close(self, ws_app, status_code, message):
        self.connected = False
        self._stop_event.set()
        self._emit(
            {
                "status": "disconnected",
                "transport": "kucoin_websocket",
                "close_status_code": status_code,
                "close_message": message,
            }
        )

    def _run_forever(self):
        if self._ws_app is None:
            return
        self._ws_app.run_forever()

    def connect(self, symbols: Iterable[str], start_background: bool = True):
        normalized_symbols = [
            str(symbol).strip()
            for symbol in symbols or []
            if str(symbol).strip()
        ]
        if not normalized_symbols:
            raise ValueError("KucoinWebSocketAdapter: symbols are required")

        with self._state_lock:
            self._symbols = normalized_symbols
            self._symbol_aliases = {
                self._normalize_exchange_symbol(symbol): symbol
                for symbol in normalized_symbols
            }
            self._stop_event.clear()

        self._connect_context = self._request_connect_context()
        self._ws_app = self._websocket_app_factory(
            self._socket_url(),
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        if start_background:
            self._runner_thread = threading.Thread(
                target=self._run_forever,
                name=f"kucoin-websocket-{self.market_type}",
                daemon=True,
            )
            self._runner_thread.start()
        else:
            self._run_forever()
        return self.snapshot_state()

    def close(self):
        self.connected = False
        self._stop_event.set()
        if self._ws_app is not None:
            try:
                self._ws_app.close()
            except Exception as exc:
                logging.warning("KucoinWebSocketAdapter: close failed error=%s", exc)

    def get_latest_market(self, symbol: str | None = None):
        with self._state_lock:
            if symbol is None:
                if not self._latest_market:
                    return None
                first_key = next(iter(self._latest_market))
                return self._clone(self._latest_market[first_key])
            exchange_symbol = self._normalize_exchange_symbol(symbol)
            market = self._latest_market.get(symbol) or self._latest_market.get(
                exchange_symbol
            )
            return self._clone(market) if market is not None else None

    def snapshot_state(self) -> dict[str, Any]:
        return {
            "market_type": self.market_type,
            "connected": self.connected,
            "symbols": list(self._symbols),
            "connect_id": self._connect_context.get("connect_id"),
            "latest_symbols": sorted(
                {
                    key
                    for key, value in self._latest_market.items()
                    if isinstance(value, dict) and value.get("symbol") == key
                }
            ),
        }
