# SelfPlayArena.py – symulacja walki strategii o najlepszy wynik
import logging
from typing import Callable, List


class SelfPlayArena:
    def __init__(self, strategies: List[Callable]):
        self.strategies = strategies
        self.results = []

    def run(self, market_data):
        for strategy in self.strategies:
            pnl = 0.0
            dd = 0.0
            for tick in market_data:
                result = strategy(tick)
                pnl += result.get("pnl", 0)
                dd = min(dd, result.get("drawdown", 0))
            self.results.append(
                {"strategy": strategy.__name__, "pnl": pnl, "drawdown": dd}
            )
            logging.info(f"SelfPlayArena: {strategy.__name__} pnl={pnl}, dd={dd}")
        best = max(self.results, key=lambda r: (r["pnl"], -r["drawdown"]), default=None)
        logging.info(f"SelfPlayArena: best strategy={best}")
        return best
