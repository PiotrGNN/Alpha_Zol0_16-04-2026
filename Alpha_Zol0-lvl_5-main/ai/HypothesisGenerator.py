# HypothesisGenerator.py – generowanie i testowanie hipotez rynkowych
import logging
from typing import Any, Dict, List


class _RuleBasedHypothesisModel:
    def predict(self, market_data: List[Dict[str, Any]]):
        hypotheses: List[Dict[str, Any]] = []
        for data in market_data or []:
            if not isinstance(data, dict):
                continue
            if "close" in data and "open" in data:
                trend = (
                    "UP"
                    if data["close"] > data["open"]
                    else "DOWN" if data["close"] < data["open"] else "SIDE"
                )
                hypotheses.append(
                    {
                        "symbol": data.get("symbol"),
                        "type": "trend",
                        "statement": f"Trend for {data.get('symbol')} is {trend}",
                        "expected": trend,
                    }
                )
            if "volume" in data and data["volume"] > 0:
                hypotheses.append(
                    {
                        "symbol": data.get("symbol"),
                        "type": "volume",
                        "statement": (
                            f"Volume for {data.get('symbol')} is high "
                            f"({data['volume']})"
                        ),
                        "expected": "HIGH" if data["volume"] > 1000 else "NORMAL",
                    }
                )
        return hypotheses


class HypothesisGenerator:
    def __init__(self):
        self.hypotheses: List[Dict[str, Any]] = []
        self.model = None  # [TASK-ID: lazy_init]

    def get_model(self):
        # [TASK-ID: lazy_init] Lazy initialization of ML model
        if self.model is None:
            logging.info(
                "HypothesisGenerator: Loading rule-based hypothesis model "
                "(lazy init)..."
            )
            self.model = _RuleBasedHypothesisModel()
        return self.model

    def generate(self, market_data: List[Dict[str, Any]]):
        # Generate hypotheses based on real market features
        self.hypotheses = self.get_model().predict(market_data)
        logging.info(
            "HypothesisGenerator: Generated %d hypotheses." % len(self.hypotheses)
        )
        return self.hypotheses

    def test(self, hypothesis: Dict[str, Any], market_data: List[Dict[str, Any]]):
        # Test hypothesis against actual market data
        symbol = hypothesis.get("symbol")
        htype = hypothesis.get("type")
        expected = hypothesis.get("expected")
        for data in market_data:
            if data.get("symbol") == symbol:
                if htype == "trend" and "close" in data and "open" in data:
                    real_trend = (
                        "UP"
                        if data["close"] > data["open"]
                        else "DOWN" if data["close"] < data["open"] else "SIDE"
                    )
                    result = real_trend == expected
                    logging.info(
                        "HypothesisGenerator: Tested %s -> %s",
                        hypothesis["statement"],
                        result,
                    )
                    return result
                if htype == "volume" and "volume" in data:
                    real_vol = "HIGH" if data["volume"] > 1000 else "NORMAL"
                    result = real_vol == expected
                    logging.info(
                        "HypothesisGenerator: Tested %s -> %s",
                        hypothesis["statement"],
                        result,
                    )
                    return result
        logging.info(
            "HypothesisGenerator: Could not test %s (data missing)",
            hypothesis["statement"],
        )
        return False
