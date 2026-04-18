# DynamicStrategyRouter.py – Dynamiczne przełączanie strategii


import logging
import time


class DynamicStrategyRouter:
    def __init__(self, strategies, tracker=None, cooldown_ticks=5):
        self.strategies = strategies
        self.current = strategies[0] if strategies else None
        self.tracker = tracker  # StrategyPerformanceTracker instance
        self.last_switch_tick = 0
        self.cooldown_ticks = cooldown_ticks
        self.tick_count = 0

    def route(self, market_state):
        """
        Analyze market_state (e.g., volatility, trend) and select best strategy
        based on scoring. Only switch if cooldown has passed.
        """
        self.tick_count += 1
        if self.tracker:
            scores = {}
            for s in self.strategies:
                name = getattr(s, "name", str(s))
                scores[name] = self.tracker.score(name)
            # Example: pick strategy with highest score
            best_name = max(scores, key=scores.get)
            current_name = getattr(self.current, "name", str(self.current))
            if current_name != best_name:
                # only switch if cooldown has passed
                ticks_since_last = self.tick_count - self.last_switch_tick
                if ticks_since_last >= self.cooldown_ticks:
                    self.switch_strategy(best_name)
                    self.last_switch_tick = self.tick_count
        # Optionally, add more market_state-based logic here
        return self.current

    def switch_strategy(self, name):
        for s in self.strategies:
            if getattr(s, "name", None) == name:
                prev = getattr(self.current, "name", str(self.current))
                self.current = s
                now = time.strftime("%Y-%m-%dT%H:%M:%S")
                logging.info(f"Strategy switch: {prev} -> {name} at {now}")
                # Log to decision_log.csv
                import os

                if os.environ.get("LIVE", "0") != "1":
                    try:
                        import csv

                        with open(
                            "autopsy/decision_log.csv",
                            "a",
                            newline="",
                        ) as f:
                            writer = csv.writer(f)
                            writer.writerow(
                                [
                                    now,
                                    "switch_strategy",
                                    f"from={prev}, to={name}",
                                ]
                            )
                    except Exception as e:
                        logging.warning(f"Strategy switch log error: {e}")
                else:
                    logging.info(
                        "LIVE mode: CSV logging disabled for strategy switches"
                    )
                return True
        return False

    def track_performance(self, metrics):
        # Log metrics for current strategy
        logging.info(
            "Tracking performance for %s: %s",
            getattr(self.current, "name", str(self.current)),
            metrics,
        )
