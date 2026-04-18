# StrategyGenome.py – Ewolucyjny silnik strategii
import logging
import random
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class StrategyGenome:
    params: Dict[str, Any]
    score: float = 0.0
    pnl: float = 0.0
    drawdown: float = 0.0
    sharpe: float = 0.0

    def mutate(self):
        # Przykładowa mutacja: losowa zmiana parametru
        for k in self.params:
            if random.random() < 0.3:
                delta = random.uniform(-0.1, 0.1)
                self.params[k] += delta
                logging.info(f"Mutacja: {k} -> {self.params[k]:.3f}")


class StrategyGenomeEngine:
    def __init__(self, population_size=10):
        self.population: List[StrategyGenome] = []
        self.population_size = population_size

    def initialize(self, param_space: Dict[str, Any]):
        for _ in range(self.population_size):
            params = {k: random.choice(v) for k, v in param_space.items()}
            genome = StrategyGenome(params=params)
            self.population.append(genome)
        logging.info(f"Zainicjowano populację: {self.population_size}")

    def evaluate(self, scoring_func):
        for genome in self.population:
            result = scoring_func(genome.params)
            genome.score = result.get("score", 0)
            genome.pnl = result.get("pnl", 0)
            genome.drawdown = result.get("drawdown", 0)
            genome.sharpe = result.get("sharpe", 0)
            logging.info(f"Ocena genomu: {genome}")

    def select(self, top_n=5):
        self.population.sort(key=lambda g: g.score, reverse=True)
        selected = self.population[:top_n]
        logging.info(f"Wybrano najlepsze genomy: {[g.score for g in selected]}")
        return selected

    def evolve(self):
        selected = self.select()
        new_population = []
        for genome in selected:
            clone = StrategyGenome(params=genome.params.copy())
            clone.mutate()
            new_population.append(clone)
        # Uzupełnij populację losowymi genomami
        while len(new_population) < self.population_size:
            params = {k: random.uniform(0, 1) for k in selected[0].params}
            new_population.append(StrategyGenome(params=params))
        self.population = new_population
        logging.info("Populacja po ewolucji zmutowana i uzupełniona.")
