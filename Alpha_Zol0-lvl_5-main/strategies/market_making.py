"""
Market Making Strategy for ZoL0: dynamic spread, inventory/risk control,
AI integration.
"""

from typing import Any, Dict, Optional
from .base import Strategy
import logging

logger = logging.getLogger(__name__)


class MarketMakingStrategy(Strategy):
    def calculate_position_size(self, signal: dict, account_balance: float) -> float:
        """
        Calculate position size for market making.
        Uses order_size parameter or a default.
        """
        return float(self.parameters.get("order_size", 0.01))

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        name: str = "MarketMaking",
        spread_pct: float = 0.1,
        order_size: float = 0.01,
        max_inventory: float = 1.0,
        min_spread: float = 0.02,
        parameters: Optional[Dict[str, Any]] = None,
    ):
        if parameters is None:
            parameters = {
                "spread_pct": spread_pct,
                "order_size": order_size,
                "max_inventory": max_inventory,
                "min_spread": min_spread,
            }
        super().__init__(name=name, timeframes=["1m"])
        self.symbol = symbol
        self.parameters = parameters
        self.inventory = 0.0
        self.last_signal = None

    def analyze(
        self,
        orderbook: Dict[str, Any],
        mid_price: float,
        inventory: float,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Analyze orderbook and inventory to generate market making signals.
        Returns 'hold' if required data is missing or invalid.
        """
        # Validate required data
        if mid_price is None or not isinstance(mid_price, (int, float)):
            return {
                "signals": [],
                "metrics": {},
                "analysis": {"reason": "No mid_price"},
            }
        if inventory is None or not isinstance(inventory, (int, float)):
            return {
                "signals": [],
                "metrics": {},
                "analysis": {"reason": "No inventory"},
            }
        if orderbook is None:
            return {
                "signals": [],
                "metrics": {},
                "analysis": {"reason": "No orderbook"},
            }

        spread_pct = kwargs.get("spread_pct", 0.1)
        order_size = kwargs.get("order_size", 0.01)
        max_inventory = kwargs.get("max_inventory", 1.0)
        min_spread = kwargs.get("min_spread", 0.02)
        # Dynamic spread adjustment (AI/volatility integration possible)
        spread = max(mid_price * spread_pct / 100, min_spread)
        bid_price = mid_price - spread / 2
        ask_price = mid_price + spread / 2
        # Inventory/risk control
        signals = []
        if inventory < max_inventory:
            signals.append(
                {
                    "type": "place_bid",
                    "price": bid_price,
                    "size": order_size,
                }
            )
        if inventory > -max_inventory:
            signals.append(
                {
                    "type": "place_ask",
                    "price": ask_price,
                    "size": order_size,
                }
            )
        # Emergency risk control:
        # if inventory too high, stop quoting on that side
        if abs(inventory) >= max_inventory:
            signals.append(
                {
                    "type": "risk_pause",
                    "reason": "inventory_limit",
                }
            )
        return {
            "signals": signals,
            "metrics": {
                "bid_price": bid_price,
                "ask_price": ask_price,
                "inventory": inventory,
                "spread": spread,
            },
        }
