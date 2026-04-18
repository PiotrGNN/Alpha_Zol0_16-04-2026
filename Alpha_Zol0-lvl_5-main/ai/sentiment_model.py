"""
Sentiment model for ZoL0: NLP, transformers, social/news fusion,
explainability.
Simple NLP Sentiment Model using HuggingFace transformers
(Polish/English).
"""

from typing import Tuple
from transformers import pipeline


class SentimentModel:
    def __init__(
        self,
        model_name: str = "cardiffnlp/twitter-roberta-base-sentiment-latest",
    ):
        self.pipe = pipeline("sentiment-analysis", model=model_name)

    def predict(self, text: str) -> Tuple[float, str]:
        result = self.pipe(text)[0]
        label = result["label"].lower()
        score = result["score"]
        # Map to (-1, 0, 1) for negative/neutral/positive
        if "positive" in label:
            return score, "positive"
        elif "negative" in label:
            return -score, "negative"
        else:
            return 0.0, "neutral"
