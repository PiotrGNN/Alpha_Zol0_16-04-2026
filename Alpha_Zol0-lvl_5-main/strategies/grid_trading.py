"""Grid Trading Strategy for ZoL0."""

from .base import Strategy
from typing import Any, Dict, List


class GridTradingStrategy(Strategy):
    def __init__(
        self,
        name: str = "GridTrading",
        grid_size: int = 7,
        grid_spacing: float = 0.005,
        max_position: int = 1,
        timeframes: List[str] = None,
    ):
        super().__init__(name=name, timeframes=timeframes)
        self.grid_size = grid_size
        self.grid_spacing = grid_spacing  # e.g., 0.5%
        self.max_position = max_position
        self.active_grids = []  # Track open grid orders

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        price = market_data.get("close", None)
        if price is None:
            return {"signal": "hold", "reason": "No price data"}

        # Setup grid levels
        center_price = price
        grid_levels = [
            center_price * (1 + self.grid_spacing * (i - self.grid_size // 2))
            for i in range(self.grid_size)
        ]
        signals = []
        for level in grid_levels:
            if price <= level and not any(
                abs(level - g["level"]) < 1e-8 for g in self.active_grids
            ):
                signals.append({"action": "buy", "level": level})
            elif price >= level and not any(
                abs(level - g["level"]) < 1e-8 for g in self.active_grids
            ):
                signals.append({"action": "sell", "level": level})

        # Risk management: limit number of open positions
        if len(self.active_grids) >= self.max_position:
            return {"signal": "hold", "reason": "Max grid positions open"}

        # Return first actionable signal, or hold
        if signals:
            return {
                "signal": signals[0]["action"],
                "level": signals[0]["level"],
                "reason": "Grid trigger",
            }
        return {"signal": "hold", "reason": "No grid trigger"}

    def calculate_position_size(
        self, signal: Dict[str, Any], account_balance: float
    ) -> float:
        # Equal allocation per grid
        if signal.get("signal") in ("buy", "sell"):
            return account_balance / self.grid_size
        return 0.0

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "grid_size": self.grid_size,
            "grid_spacing": self.grid_spacing,
            "max_position": self.max_position,
            "active_grids": self.active_grids,
            "enabled": self.enabled,
        }
