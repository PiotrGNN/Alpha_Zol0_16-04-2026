# EmotionModulator.py – ocena nastroju rynku i modulacja AI
import logging


from typing import Any, Dict, Union


class EmotionModulator:
    """
    Modulates AI trading decisions based on market sentiment and
    fear/greed index.
    Adjusts risk, confidence, or action based on emotional state of the market.
    """

    def __init__(self) -> None:
        self.fear_greed_index: float = 0.0
        self.sentiment: float = 0.0

    def update(self, fear_greed: float, sentiment: float) -> None:
        """
        Update the internal state with the latest fear/greed index and
        sentiment.
        Args:
            fear_greed (float): Value from 0 (fear) to 1 (greed).
            sentiment (float): Market sentiment, -1 (bearish) to 1 (bullish).
        """
        self.fear_greed_index = fear_greed
        self.sentiment = sentiment
        logging.info(
            "EmotionModulator: fear_greed=%.2f, sentiment=%.2f",
            fear_greed,
            sentiment,
        )

    def modulate(
        self, ai_decision: Union[str, Dict[str, Any]]
    ) -> Union[str, Dict[str, Any]]:
        """
        Modulate the AI decision based on current emotional state.
        Args:
            ai_decision (str or dict): The original AI decision or signal.
        Returns:
            Modified decision (str or dict),
            possibly with adjusted risk/confidence.
        """
        # Example: scale risk/confidence or override action based on emotion
        modulated = ai_decision
        # If extreme fear, reduce risk or override to 'wait'
        if self.fear_greed_index < 0.2:
            logging.info("EmotionModulator: Extreme fear detected, reducing risk.")
            if isinstance(ai_decision, dict):
                modulated = ai_decision.copy()
                modulated["risk"] = min(modulated.get("risk", 1.0) * 0.5, 0.5)
                modulated["confidence"] = min(modulated.get("confidence", 1.0), 0.5)
            elif isinstance(ai_decision, str) and ai_decision in ("buy", "sell"):
                modulated = "wait"
        # If extreme greed, increase risk slightly (but cap)
        elif self.fear_greed_index > 0.8:
            logging.info("EmotionModulator: Extreme greed detected, increasing risk.")
            if isinstance(ai_decision, dict):
                modulated = ai_decision.copy()
                modulated["risk"] = min(modulated.get("risk", 1.0) * 1.2, 2.0)
                modulated["confidence"] = min(
                    modulated.get("confidence", 1.0) * 1.1, 1.0
                )
        # If negative sentiment, be more cautious
        if self.sentiment < -0.5:
            logging.info("EmotionModulator: Negative sentiment, increasing caution.")
            if isinstance(modulated, dict):
                modulated["risk"] = min(modulated.get("risk", 1.0) * 0.7, 1.0)
                modulated["confidence"] = min(modulated.get("confidence", 1.0), 0.7)
            elif isinstance(modulated, str) and modulated in ("buy", "sell"):
                modulated = "wait"
        # If positive sentiment, allow more confidence
        elif self.sentiment > 0.5:
            logging.info("EmotionModulator: Positive sentiment, increasing confidence.")
            if isinstance(modulated, dict):
                modulated["confidence"] = min(
                    modulated.get("confidence", 1.0) * 1.2, 1.0
                )
        return modulated
