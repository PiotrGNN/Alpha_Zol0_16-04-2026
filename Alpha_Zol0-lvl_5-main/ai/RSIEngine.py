# RSIEngine.py – automatyczna analiza i ulepszanie strategii AI
import logging

import numpy as np


class RSIEngine:
    def __init__(self, window=14):
        self.window = window

    def compute_rsi(self, prices):
        prices = np.array(prices)
        deltas = np.diff(prices)
        seed = deltas[: self.window]
        up = seed[seed > 0].sum() / self.window
        down = -seed[seed < 0].sum() / self.window
        rs = up / down if down != 0 else 0
        rsi = 100 - 100 / (1 + rs)
        return rsi

    def analyze_performance(self, pnl_history):
        # Analizuj performance, sugeruj zmiany
        avg_pnl = np.mean(pnl_history)
        std_pnl = np.std(pnl_history)
        logging.info(f"RSIEngine: avg_pnl={avg_pnl:.2f}, std_pnl={std_pnl:.2f}")
        if avg_pnl < 0:
            suggestion = "Zmień strategię: negatywny PnL!"
        elif std_pnl > 10:
            suggestion = "Zoptymalizuj: duża zmienność!"
        else:
            suggestion = "Strategia OK"
        return suggestion

    def create_pull_request(self, changes):
        # Mock: twórz lokalny pull request
        logging.info(f"RSIEngine: creating pull request with changes: {changes}")
        return True
