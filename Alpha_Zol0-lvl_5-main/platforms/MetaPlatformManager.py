# MetaPlatformManager.py – integracja z zewnętrznymi giełdami
import logging
from datetime import datetime, timezone
from typing import Any, Dict

import requests


class SimulatedPortfolio:
    def __init__(self):
        self.balance = 10000.0  # USD, start value
        self.positions = (
            []
        )  # list of dicts: {symbol, side, qty, entry_price, timestamp}

    def open_position(self, symbol, side, qty, price):
        pos = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry_price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.positions.append(pos)
        return pos

    def close_position(self, symbol, side, price):
        closed = []
        for pos in self.positions:
            if pos["symbol"] == symbol and pos["side"] == side:
                pos["close_price"] = price
                pos["close_timestamp"] = datetime.now(timezone.utc).isoformat()
                closed.append(pos)
        self.positions = [p for p in self.positions if p not in closed]
        return closed

    def get_balance(self):
        return {"balance": self.balance}

    def get_positions(self):
        return self.positions


class TradeLog:
    def __init__(self):
        self.trades = []

    def log(self, trade):
        self.trades.append(trade)
        logging.info(f"TradeLog: {trade}")

    def get_all(self):
        return self.trades


class MetaPlatformManager:
    """
    MetaPlatformManager (live-paper):
    - mode: 'live-paper' (default, real data, simulated orders),
      'mock', 'real' (future)
    - fetches real market/account data, simulates order execution,
      logs all actions
    """

    def __init__(self, mode="live-paper"):
        self.mode = mode
        self.platforms: Dict[str, Any] = {}
        self.portfolio = SimulatedPortfolio()
        self.trade_log = TradeLog()
        logging.info(f"MetaPlatformManager initialized in mode: {self.mode}")
        if self.mode == "mock":
            logging.warning("MetaPlatformManager running in MOCK mode!")
        elif self.mode == "real":
            logging.warning(
                "REAL mode not implemented! Only live-paper " "and mock supported."
            )

    def register_platform(self, name: str, api: Any = None):
        if str(name).lower() != "kucoin":
            raise ValueError("MetaPlatformManager: non-KuCoin platform blocked (NO-GO)")
        self.platforms[name] = api
        logging.info(f"MetaPlatformManager: registered platform {name}")

    def get_platform(self, name: str):
        return self.platforms.get(name, None)

    def list_platforms(self):
        return list(self.platforms.keys())

    def get_market_data(self, symbol: str):
        if self.mode == "mock":
            # Return fake data
            return {
                "symbol": symbol,
                "price": 100.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logging.error(f"get_market_data error: {e}")
            return None

    def get_balance(self):
        # In live-paper, return simulated balance
        return self.portfolio.get_balance()

    def get_positions(self):
        return self.portfolio.get_positions()

    def simulate_order(self, side: str, symbol: str, qty: float):
        if self.mode == "mock":
            price = 100.0
        else:
            md = self.get_market_data(symbol)
            price = md["price"] if md else 0.0
        order = {
            "side": side,
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
        }
        if side.lower() in ["buy", "long"]:
            pos = self.portfolio.open_position(symbol, side, qty, price)
            order["position"] = pos
        elif side.lower() in ["sell", "close", "short"]:
            closed = self.portfolio.close_position(symbol, side, price)
            order["closed"] = closed
        self.trade_log.log(order)
        logging.info(f"Simulated order: {order}")
        return order

    def execute_trade(self, name: str, trade: Dict[str, Any]):
        # Simulate only, never send real order
        symbol = trade.get("symbol")
        side = trade.get("side")
        qty = trade.get("qty", trade.get("amount", 0))
        result = self.simulate_order(side, symbol, qty)
        logging.info(f"MetaPlatformManager: simulated trade on {name}: {result}")
        return result
