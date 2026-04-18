# FullBacktester.py – pełny backtest i wizualizacja tick-by-tick

import logging
from typing import Dict, List

logger = logging.getLogger("FullBacktester")


class FullBacktester:
    def __init__(self, strategy):
        self.strategy = strategy
        self.log = []

    def run(self, market_data: List[Dict]):
        for i, tick in enumerate(market_data):
            result = self.strategy(tick)
            self.log.append({"tick": i, "data": tick, "result": result})
            logger.info(f"FullBacktester: tick={i}, result={result}")

        return self.log

    def visualize(self):
        # Mock: wypisz tick-by-tick
        for entry in self.log:
            print(f"Tick {entry['tick']}: {entry['result']}")
