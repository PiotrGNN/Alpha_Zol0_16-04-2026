# QuantumPortfolioOptimizer.py –
# optymalizacja portfela z wykorzystaniem algorytmów kwantowych
import logging
from typing import Dict, List

import numpy as np


class QuantumPortfolioOptimizer:
    def optimize_portfolio(
        self,
        positions: list,
        performance_metrics: dict = None,
    ) -> dict:
        """
        Select the best position based on PnL (legacy/test compatibility).
        Args:
            positions: List of position dicts.
            performance_metrics: Optional dict of metrics.
        Returns:
            Dict of the best position.
        """
        if not positions:
            return None
        best = max(positions, key=lambda p: p.get("pnl", 0))
        return best

    """
    Portfolio optimizer using simulated quantum-inspired optimization
    (random weights).
    """

    def __init__(self):
        self.last_result = None

    def optimize(self, assets: List[Dict], constraints: Dict = None) -> Dict | None:
        """
        Simulate quantum optimization by generating random weights for assets.
        Args:
            assets: List of dicts with 'symbol', 'expected_return', 'risk'.
            constraints: Optional constraints dict (unused in this stub).
        Returns:
            Dict with weights, expected_return, risk, and asset symbols, or
            None when no assets are provided.
        """
        n = len(assets)
        if n == 0:
            logging.warning(
                "QuantumPortfolioOptimizer: no assets provided; returning None"
            )
            return None
        weights = np.random.dirichlet(np.ones(n), size=1)[0]
        result = {
            "weights": weights.tolist(),
            "expected_return": sum(
                a["expected_return"] * w for a, w in zip(assets, weights)
            ),
            "risk": sum(a["risk"] * w for a, w in zip(assets, weights)),
            "assets": [a["symbol"] for a in assets],
        }
        self.last_result = result
        logging.info(f"QuantumPortfolioOptimizer: optimized {result}")
        return result

    def get_last_result(self):
        return self.last_result


# Alias for backward compatibility
PortfolioOptimizer = QuantumPortfolioOptimizer
