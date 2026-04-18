# Rebalancer.py – automatyczne dostosowanie portfela co N minut
import logging
from typing import Dict


class Rebalancer:
    def __init__(self, assets: Dict[str, float], target_weights: Dict[str, float]):
        self.assets = assets
        self.target_weights = target_weights

    def rebalance(self):
        total_value = sum(self.assets.values())
        orders = []
        for asset, value in self.assets.items():
            target_value = total_value * self.target_weights.get(asset, 0)
            diff = target_value - value
            if abs(diff) > 0.01 * total_value:
                action = "buy" if diff > 0 else "sell"
                orders.append(
                    {
                        "asset": asset,
                        "action": action,
                        "amount": abs(diff),
                    }
                )
                logging.info(f"Rebalancer: {action} {asset} {abs(diff):.2f}")
        return orders
