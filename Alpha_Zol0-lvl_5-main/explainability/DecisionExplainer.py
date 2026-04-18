# DecisionExplainer.py – wyjaśnianie decyzji AI krok po kroku
import logging


class DecisionExplainer:
    def __init__(self, log_level: int = logging.INFO):
        """
        Initialize the DecisionExplainer.
        Args:
            log_level (int): Logging level for explanations.
        """
        self.name = "DecisionExplainer"
        self.log_level = log_level
        logging.basicConfig(level=log_level)

    def explain(self, decision, features, engine_log=None):
        explanation = []
        explanation.append(f"Decyzja: {decision}")
        for k, v in features.items():
            explanation.append(f"Feature: {k} = {v}")
        if engine_log:
            explanation.append(f"Log silnika: {engine_log}")
        explanation_str = " | ".join(explanation)
        logging.info(f"DecisionExplainer: {explanation_str}")
        return explanation_str
