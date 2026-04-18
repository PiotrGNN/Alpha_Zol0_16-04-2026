# MetaPlatformManager.py – integracja z zewnętrznymi giełdami
import logging
import os
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict

import requests


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SimulatedPortfolio:
    def __init__(self):
        self.balance = 10000.0  # USD, start value
        self.positions = []

    def open_position(self, symbol, side, qty, price):
        pos = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry_price": price,
            "timestamp": _now_iso(),
        }
        self.positions.append(pos)
        return pos

    def close_position(self, symbol, side, price):
        closed = []
        for pos in self.positions:
            if pos["symbol"] == symbol and pos["side"] == side:
                pos["close_price"] = price
                pos["close_timestamp"] = _now_iso()
                closed.append(pos)
        self.positions = [p for p in self.positions if p not in closed]
        return closed

    def get_balance(self):
        return {"balance": self.balance}

    def get_positions(self):
        return list(self.positions)


class TradeLog:
    def __init__(self):
        self.trades = []

    def log(self, trade):
        self.trades.append(trade)
        logging.info("TradeLog: %s", trade)

    def get_all(self):
        return list(self.trades)


class MetaPlatformManager:
    """
    MetaPlatformManager (live-paper, KuCoin-only).

    REST state sync is intended for runtime monitoring.
    WebSocket event ingestion is adapter-driven and remains experimental.
    """

    def __init__(self, mode="live-paper"):
        self.mode = mode
        self.platforms: Dict[str, Dict[str, Any]] = {}
        self.platform_states: Dict[str, Dict[str, Any]] = {}
        self.portfolio = SimulatedPortfolio()
        self.trade_log = TradeLog()
        self.experimental = self.mode == "mock"
        logging.info("MetaPlatformManager initialized in mode: %s", self.mode)
        if self.mode == "mock":
            logging.warning(
                "MetaPlatformManager running in MOCK mode; websocket "
                "ingestion is experimental"
            )
        elif self.mode == "real":
            logging.warning(
                "REAL mode keeps order execution simulated; only state sync "
                "is supported."
            )

    @staticmethod
    def _clone(value):
        return deepcopy(value)

    def _platform_entry(self, name: str):
        return self.platforms.get(name)

    def _log_platform_state(self, name: str, source: str):
        logging.info(
            "MetaPlatformManager: platform_state name=%s source=%s state=%s",
            name,
            source,
            self.platform_states.get(name),
        )

    @staticmethod
    def _websocket_adapter_name(websocket):
        return type(websocket).__name__ if websocket is not None else None

    @staticmethod
    def _is_websocket_connected(websocket) -> bool:
        if websocket is None:
            return False
        if hasattr(websocket, "connected"):
            try:
                return bool(websocket.connected)
            except Exception:
                return True
        return True

    def _resolve_websocket_market_type(self, symbol: str | None = None) -> str:
        env_market_type = os.environ.get("MARKET_TYPE", "").strip().lower()
        if env_market_type in {"spot", "futures"}:
            return env_market_type
        if symbol and str(symbol).upper().endswith("USDTM"):
            return "futures"
        return "futures"

    def _build_default_websocket(self, name: str, market_type: str | None = None):
        if str(name).lower() != "kucoin":
            return None
        try:
            from platforms.kucoin_websocket_adapter import KucoinWebSocketAdapter

            return KucoinWebSocketAdapter(
                market_type=market_type or self._resolve_websocket_market_type()
            )
        except Exception as exc:
            logging.warning(
                "MetaPlatformManager: default websocket adapter init failed: %s",
                exc,
            )
            return None

    def _bind_websocket_handler(self, name: str, websocket):
        if websocket is None or not hasattr(websocket, "set_event_handler"):
            return
        websocket.set_event_handler(
            lambda event, platform_name=name: self.handle_platform_event(
                platform_name,
                event,
            )
        )

    def register_platform(self, name: str, api: Any = None, websocket: Any = None):
        if str(name).lower() != "kucoin":
            raise ValueError("MetaPlatformManager: non-KuCoin platform blocked (NO-GO)")
        websocket = (
            websocket
            if websocket is not None
            else self._build_default_websocket(name)
        )
        self.platforms[name] = {"api": api, "websocket": websocket}
        self._bind_websocket_handler(name, websocket)
        websocket_adapter = self._websocket_adapter_name(websocket)
        self.platform_states[name] = {
            "platform": name,
            "mode": self.mode,
            "experimental": (
                False
                if websocket_adapter == "KucoinWebSocketAdapter"
                else self.experimental
            ),
            "registered_at": _now_iso(),
            "api_connected": api is not None,
            "websocket_connected": self._is_websocket_connected(websocket),
            "websocket_adapter": websocket_adapter,
            "websocket_market_type": getattr(websocket, "market_type", None),
            "last_sync_source": "register",
        }
        logging.info("MetaPlatformManager: registered platform %s", name)
        self._log_platform_state(name, "register")

    def attach_kucoin_websocket(
        self,
        name: str = "kucoin",
        market_type: str | None = None,
    ):
        entry = self._platform_entry(name)
        if entry is None:
            self.register_platform(name)
            entry = self._platform_entry(name)

        websocket = entry.get("websocket")
        if websocket is None:
            websocket = self._build_default_websocket(name, market_type=market_type)
            entry["websocket"] = websocket
        self._bind_websocket_handler(name, websocket)

        state = self.platform_states.get(name, {})
        state.update(
            {
                "websocket_connected": self._is_websocket_connected(websocket),
                "websocket_adapter": self._websocket_adapter_name(websocket),
                "websocket_market_type": getattr(websocket, "market_type", market_type),
                "experimental": (
                    False
                    if self._websocket_adapter_name(websocket)
                    == "KucoinWebSocketAdapter"
                    else self.experimental
                ),
                "last_sync_source": "websocket_attach",
            }
        )
        self.platform_states[name] = state
        self._log_platform_state(name, "websocket_attach")
        return websocket

    def start_platform_stream(self, name: str, symbols, market_type: str | None = None):
        websocket = self.attach_kucoin_websocket(name, market_type=market_type)
        if websocket is None or not hasattr(websocket, "connect"):
            raise RuntimeError(
                "MetaPlatformManager: websocket adapter missing connect()"
            )
        websocket.connect(symbols)
        state = self.platform_states.get(name, {})
        state.update(
            {
                "status": "connecting",
                "websocket_symbols": list(symbols or []),
                "websocket_connected": self._is_websocket_connected(websocket),
                "last_sync_source": "websocket_start",
            }
        )
        self.platform_states[name] = state
        self._log_platform_state(name, "websocket_start")
        return self._clone(state)

    def stop_platform_stream(self, name: str):
        entry = self._platform_entry(name)
        if entry is None:
            raise KeyError(f"Platform not registered: {name}")
        websocket = entry.get("websocket")
        if websocket is not None and hasattr(websocket, "close"):
            websocket.close()
        state = self.platform_states.get(name, {})
        state.update(
            {
                "status": "disconnected",
                "websocket_connected": False,
                "last_sync_source": "websocket_stop",
            }
        )
        self.platform_states[name] = state
        self._log_platform_state(name, "websocket_stop")
        return self._clone(state)

    def get_platform(self, name: str):
        entry = self._platform_entry(name)
        return entry.get("api") if entry else None

    def get_platform_state(self, name: str):
        state = self.platform_states.get(name)
        return self._clone(state) if state is not None else None

    def get_all_platform_states(self):
        return self._clone(self.platform_states)

    def list_platforms(self):
        return list(self.platforms.keys())

    def _public_market_data(self, symbol: str):
        if self.mode == "mock":
            return {
                "symbol": symbol,
                "price": 100.0,
                "timestamp": _now_iso(),
            }
        try:
            url = (
                "https://api.kucoin.com/api/v1/market/orderbook/level1"
                f"?symbol={symbol}"
            )
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            price = float(data.get("data", {}).get("price", 0))
            return {
                "symbol": symbol,
                "price": price,
                "timestamp": _now_iso(),
            }
        except Exception as exc:
            logging.error("get_market_data error: %s", exc)
            return None

    def get_market_data(self, symbol: str, name: str = "kucoin"):
        entry = self._platform_entry(name)
        api = entry.get("api") if entry else None
        websocket = entry.get("websocket") if entry else None
        data = None
        market_source = None
        if websocket is not None and hasattr(websocket, "get_latest_market"):
            data = websocket.get_latest_market(symbol)
            if data is not None:
                market_source = "websocket"
        if data is None and api is not None and hasattr(api, "get_market_data"):
            data = api.get_market_data(symbol)
            market_source = "api"
        if data is None:
            data = self._public_market_data(symbol)
            market_source = "rest"

        if entry is not None:
            state = self.platform_states.get(name, {})
            state["market"] = self._clone(data)
            state["last_market_sync_at"] = _now_iso()
            state["last_market_source"] = market_source
            state["websocket_connected"] = self._is_websocket_connected(websocket)
            self.platform_states[name] = state
        return self._clone(data)

    def get_balance(self, name: str = "kucoin"):
        entry = self._platform_entry(name)
        api = entry.get("api") if entry else None
        if api is not None and hasattr(api, "get_balance"):
            return self._clone(api.get_balance())
        return self.portfolio.get_balance()

    def get_positions(self, name: str = "kucoin"):
        entry = self._platform_entry(name)
        api = entry.get("api") if entry else None
        if api is not None and hasattr(api, "get_positions"):
            return self._clone(api.get_positions())
        return self.portfolio.get_positions()

    def sync_platform_state(self, name: str, symbol: str | None = None):
        entry = self._platform_entry(name)
        if entry is None:
            raise KeyError(f"Platform not registered: {name}")

        api = entry.get("api")
        websocket = entry.get("websocket")
        if api is not None and hasattr(api, "sync_state"):
            state = api.sync_state(symbol=symbol)
            if not isinstance(state, dict):
                state = {"raw_state": self._clone(state)}
        else:
            state = {
                "balance": self.get_balance(name),
                "positions": self.get_positions(name),
            }
        if symbol and (not isinstance(state, dict) or state.get("market") is None):
            state["market"] = self.get_market_data(symbol, name=name)

        websocket_adapter = self._websocket_adapter_name(websocket)
        merged = {
            **self.platform_states.get(name, {}),
            **state,
            "platform": name,
            "mode": self.mode,
            "experimental": (
                False
                if websocket_adapter == "KucoinWebSocketAdapter"
                else self.experimental
            ),
            "api_connected": api is not None,
            "websocket_connected": self._is_websocket_connected(websocket),
            "websocket_adapter": websocket_adapter,
            "websocket_market_type": getattr(websocket, "market_type", None),
            "last_sync_at": _now_iso(),
            "last_sync_source": "api",
        }
        if symbol is not None:
            merged["symbol"] = symbol
        self.platform_states[name] = merged
        self._log_platform_state(name, "api")
        return self._clone(merged)

    def sync_all_platform_states(self, symbols=None):
        results = {}
        symbol_map = symbols if isinstance(symbols, dict) else {}
        for name in self.platforms:
            results[name] = self.sync_platform_state(name, symbol=symbol_map.get(name))
        return results

    def handle_platform_event(self, name: str, event: Dict[str, Any]):
        entry = self._platform_entry(name)
        if entry is None:
            raise KeyError(f"Platform not registered: {name}")

        websocket = entry.get("websocket")
        websocket_adapter = self._websocket_adapter_name(websocket)
        state = self._clone(self.platform_states.get(name, {}))
        state.update(
            {
                "platform": name,
                "mode": self.mode,
                "experimental": (
                    False
                    if websocket_adapter == "KucoinWebSocketAdapter"
                    else self.experimental
                ),
                "websocket_connected": self._is_websocket_connected(websocket),
                "websocket_adapter": websocket_adapter,
                "websocket_market_type": getattr(websocket, "market_type", None),
                "last_event": self._clone(event),
                "last_event_at": _now_iso(),
                "last_sync_source": "websocket",
            }
        )
        if isinstance(event, dict):
            for key in ("market", "balance", "positions", "status"):
                if key in event:
                    state[key] = self._clone(event[key])
        self.platform_states[name] = state
        self._log_platform_state(name, "websocket")
        return self._clone(state)

    def simulate_order(
        self,
        side: str,
        symbol: str,
        qty: float,
        platform_name: str = "kucoin",
    ):
        if self.mode == "mock":
            price = 100.0
        else:
            md = self.get_market_data(symbol, name=platform_name)
            price = md["price"] if md else 0.0
        order = {
            "side": side,
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "timestamp": _now_iso(),
            "mode": self.mode,
        }
        if side.lower() in ["buy", "long"]:
            pos = self.portfolio.open_position(symbol, side, qty, price)
            order["position"] = pos
        elif side.lower() in ["sell", "close", "short"]:
            closed = self.portfolio.close_position(symbol, side, price)
            order["closed"] = closed
        self.trade_log.log(order)
        if platform_name in self.platforms:
            state = self.platform_states.get(platform_name, {})
            state["last_order"] = self._clone(order)
            state["last_order_at"] = _now_iso()
            self.platform_states[platform_name] = state
        logging.info("Simulated order: %s", order)
        return self._clone(order)

    def execute_trade(self, name: str, trade: Dict[str, Any]):
        symbol = trade.get("symbol")
        side = trade.get("side")
        qty = trade.get("qty", trade.get("amount", 0))
        result = self.simulate_order(side, symbol, qty, platform_name=name)
        if name in self.platforms:
            self.sync_platform_state(name, symbol=symbol)
        logging.info("MetaPlatformManager: simulated trade on %s: %s", name, result)
        return result
