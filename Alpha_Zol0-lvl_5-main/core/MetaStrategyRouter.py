# MetaStrategyRouter.py – Dynamic LLM/metrics-based strategy router with
# logging, cooldown, dashboard sync
import logging
import time

logger = logging.getLogger(__name__)


class MetaStrategyRouter:
    def get_status(self):
        """Zwraca status strategii dla FastAPI /strategy."""
        return self.get_current_strategy_info()

    def __init__(
        self,
        strategies,
        tracker=None,
        llm_model=None,
        cooldown_ticks=5,
        use_llm=True,
    ):

        self.strategies = strategies  # list of strategy objects
        # (must have .name)
        self.current = strategies[0] if strategies else None
        self.tracker = tracker  # StrategyPerformanceTracker instance
        self.llm_model = llm_model or "gpt-4"
        self.last_decision = ""
        self.last_switch_tick = 0
        self.cooldown_ticks = cooldown_ticks
        self.tick_count = 0
        self.use_llm = use_llm

        # Ensure all strategies have get_status method
        # for dashboard compatibility
        for s in self.strategies:
            if not hasattr(s, "get_status"):
                if hasattr(s, "get_current_strategy_info"):
                    s.get_status = s.get_current_strategy_info
                else:
                    s.get_status = lambda: {}

    def route(self, market_state):
        self.tick_count += 1
        # Cooldown: only allow switch every N ticks
        if self.tick_count - self.last_switch_tick < self.cooldown_ticks:
            return self.current

        # LLM-based routing
        if self.use_llm:
            prompt = f"""
                Given the market state:
                Volatility: {market_state.get('volatility', 'unknown')},
                Trend: {market_state.get('trend', 'unknown')},
                Momentum: {market_state.get('momentum', 'unknown')}

                Available strategies:
                {[s.name for s in self.strategies]}

                Which strategy should be used and why?
                Answer in the format:
                STRATEGY: <strategy_name>
                REASON: <short_reason>
                """
            try:
                from utils.llm import ask_llm

                response = ask_llm(prompt, model=self.llm_model)
                strategy_line = next(
                    (line for line in response.splitlines() if "STRATEGY:" in line),
                    None,
                )
                reason_line = next(
                    (line for line in response.splitlines() if "REASON:" in line),
                    "",
                )
                if strategy_line:
                    name = strategy_line.split("STRATEGY:")[1].strip()
                    success = self.switch_strategy(name)
                    self.last_decision = (
                        reason_line.strip() if reason_line else "No reason given"
                    )
                    if success:
                        logger.info(f"LLM routed to {name}: {self.last_decision}")
                        self.last_switch_tick = self.tick_count
                return self.current
            except Exception as e:
                logger.error(f"LLM routing failed: {e}")
                # fallback to metrics

        # Metrics-based routing
        best_score = float("-inf")
        best_strategy = self.current
        if self.tracker:
            for s in self.strategies:
                score = self.tracker.score(s.name)
                if score > best_score:
                    best_score = score
                    best_strategy = s
            if best_strategy != self.current:
                self.switch_strategy(best_strategy.name)
                self.last_decision = (
                    f"Metrics-based switch to {best_strategy.name} "
                    f"(score={best_score:.2f})"
                )
                self.last_switch_tick = self.tick_count
                logger.info(self.last_decision)
        return self.current

    def switch_strategy(self, name):
        for s in self.strategies:
            if getattr(s, "name", None) == name:
                if self.current != s:
                    old = getattr(self.current, "name", str(self.current))
                    self.current = s
                    self.log_switch(old, name)
                return True
        return False

    def log_switch(self, old, new):
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        msg = f"{ts} STRATEGY_SWITCH: {old} -> {new}"
        logger.info(msg)
        # Optionally append to decision_log.csv
        import os

        if os.environ.get("LIVE", "0") != "1":
            try:
                with open("autopsy/decision_log.csv", "a", encoding="utf-8") as f:
                    f.write(f"{ts},strategy_switch,{old}->{new}\n")
            except Exception as e:
                logger.error(f"Failed to log strategy switch: {e}")
        else:
            logger.info("LIVE mode: CSV logging disabled for strategy switches")

    def track_performance(self, metrics):
        # Optionally update tracker here
        if self.tracker and self.current:
            self.tracker.update(self.current.name, metrics)
        logger.info(
            f"Tracking performance for "
            f"{getattr(self.current, 'name', str(self.current))}: "
            f"{metrics}"
        )

    def get_current_strategy_info(self):
        """Return info for FastAPI /strategy endpoint."""
        return {
            "active_strategy": getattr(self.current, "name", "unknown"),
            "all_strategies": [getattr(s, "name", "unnamed") for s in self.strategies],
            "last_decision_reason": self.last_decision,
            "cooldown": self.cooldown_ticks,
            "tick_count": self.tick_count,
        }
