# SimulationInterface.py – CLI/API do testowania strategii bez realnych zleceń

import logging

logger = logging.getLogger(__name__)


class SimulationInterface:
    def __init__(self, strategy_func):
        self.strategy_func = strategy_func
        self.log = []

    def run(self, market_data_list):
        for i, data in enumerate(market_data_list):
            result = self.strategy_func(data)
            self.log.append(result)
            logging.info(f"Simulation step {i}: {result}")
        return self.log

    def summary(self):
        n = len(self.log)
        wins = sum(1 for r in self.log if r.get("pnl", 0) > 0)
        losses = n - wins
        total_pnl = sum(r.get("pnl", 0) for r in self.log)
        logging.info(
            "Simulation summary: steps=%d, wins=%d, losses=%d, total_pnl=%s",
            n,
            wins,
            losses,
            total_pnl,
        )
        return {
            "steps": n,
            "wins": wins,
            "losses": losses,
            "total_pnl": total_pnl,
        }


# To use SimulationInterface, provide a real strategy function as argument.
