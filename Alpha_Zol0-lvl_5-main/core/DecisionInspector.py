# DecisionInspector.py – Analiza i ocena decyzji AI

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class DecisionInspector:
    """
    Analizuje decyzję AI (buy/sell/wait/risk_limit) i ocenia prawdopodobieństwo
    sukcesu na podstawie trendu, volatility, drawdown, TP score, siły sygnału.
    Zwraca wyjaśnienie jako string.
    """

    def __init__(self):
        self.history = []

    def record_decision(self, decision: Dict[str, Any]):
        self.history.append(decision)
        logging.info(f"DecisionInspector: recorded {decision}")

    def get_history(self):
        return self.history

    def inspect(self, decision: str, features: Dict[str, Any]) -> Dict[str, Any]:
        """
        features: {
            'trend': str,
            'volatility': float,
            'drawdown': float,
            'tp_score': float,
            'symbol': str,
            'strategy': str,
            ...
        }
        """
        score = 0.0
        explanation = []
        # Trend
        if features.get("trend") == "UP" and decision == "buy":
            score += 0.3
            explanation.append("Trend UP sprzyja BUY (+0.3)")
        elif features.get("trend") == "DOWN" and decision == "sell":
            score += 0.3
            explanation.append("Trend DOWN sprzyja SELL (+0.3)")
        elif decision == "wait":
            score += 0.05
            explanation.append("Decyzja WAIT, neutralny trend (+0.05)")
        else:
            score -= 0.2
            explanation.append("Trend niezgodny z decyzją (-0.2)")
        # Volatility
        vol = features.get("volatility", 0)
        if vol > 50:
            score -= 0.2
            explanation.append("Wysoka zmienność, ryzyko (-0.2)")
        else:
            score += 0.1
            explanation.append("Niska zmienność (+0.1)")
        # Drawdown
        dd = features.get("drawdown", 0)
        if dd > 0.1:
            score -= 0.3
            explanation.append("Wysoki drawdown, blokada (-0.3)")
        else:
            score += 0.1
            explanation.append("Drawdown OK (+0.1)")
        # TP score
        tp_score = features.get("tp_score", 0)
        score += tp_score * 0.3
        explanation.append(f"TP score: {tp_score:+.2f} (wagi x0.3)")
        # Signal strength
        signal_strength = features.get("signal_strength", 0)
        score += signal_strength * 0.2
        explanation.append(f"Siła sygnału: {signal_strength:.2f} (wagi x0.2)")
        # Final ocena
        prob_success = min(max(score, 0), 1)
        explanation_str = "; ".join(explanation)
        logging.info(
            f"DecisionInspector: decision={decision}, score={score:.2f}, "
            f"prob_success={prob_success:.2f}, explanation={explanation_str}"
        )
        return {
            "decision": decision,
            "score": score,
            "prob_success": prob_success,
            "explanation": explanation_str,
            "features": features,
        }
