# AdversaryDetector.py – wykrywanie counter-AI i frontrunning
import logging
from typing import Dict, List


class AdversaryDetector:
    def __init__(self):
        self.reactions = []

    def analyze_market_reaction(self, own_order, market_data):
        # Analizuj reakcje rynku po własnych zleceniach
        reaction = market_data.get("reaction", 0)
        self.reactions.append(reaction)
        logging.info(f"AdversaryDetector: market reaction={reaction}")
        if reaction < 0:
            return "Możliwy frontrunning lub counter-AI!"
        return "Brak wrogiej reakcji"

    def detect_adversary(self, history: List[Dict]):
        # Wykryj powtarzające się negatywne reakcje
        negatives = [h for h in history if h.get("reaction", 0) < 0]
        if len(negatives) > 2:
            logging.warning("AdversaryDetector: wykryto wrogie działania!")
            return True
        return False
