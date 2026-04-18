"""
StrategyPerformanceTracker.py – Production-grade strategy performance tracker
(LEVEL-ML/LEVEL-API DONE)
- Advanced metrics: rolling drawdown, score, hitrate, Sharpe ratio, etc.
- Robust logging, error handling, type annotations
- ML pipeline compatibility
"""

import logging
from typing import Any, Dict

logger = logging.getLogger("StrategyPerformanceTracker")


class StrategyPerformanceTracker:
    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        """
        Return a dict of stats (sharpe, pnl, winrate, drawdown, score, PF, etc.)
        for each strategy.
        """
        stats = {}
        for strategy in self.performance:
            stats[strategy] = {
                "sharpe": self.sharpe_ratio(strategy),
                "pnl": self.track_pnl(strategy),
                "winrate": self.winrate(strategy),
                "drawdown": self.drawdown(strategy),
                "score": self.score(strategy),
                "trade_count": self.trade_count(strategy),
                "wins": self.wins(strategy),
                "losses": self.losses(strategy),
                "gross_profit": self.gross_profit(strategy),
                "gross_loss_abs": self.gross_loss_abs(strategy),
                "profit_factor": self.profit_factor(strategy),
                "expectancy": self.expectancy(strategy),
            }
        return stats

    def sharp_ratio(self, strategy: str) -> float:
        # Alias for legacy test compatibility (should be sharpe_ratio)
        return self.sharpe_ratio(strategy)

    def __init__(self):
        self.name = "StrategyPerformanceTracker"
        self.performance: Dict[str, Dict[str, Any]] = {}

    def update(self, strategy: str, result: Dict[str, Any]):
        """Update strategy performance with new result."""
        try:
            if strategy not in self.performance:
                self.performance[strategy] = {
                    "pnl": [],
                    "wins": 0,
                    "losses": 0,
                }
            self.performance[strategy]["pnl"].append(result.get("pnl", 0))
            if result.get("pnl", 0) > 0:
                self.performance[strategy]["wins"] += 1
            else:
                self.performance[strategy]["losses"] += 1
            logger.info(
                f"StrategyTracker: {strategy} updated. "
                f"PnL={result.get('pnl', 0)}, "
                f"Wins={self.performance[strategy]['wins']}, "
                f"Losses={self.performance[strategy]['losses']}"
            )
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.update error: {e}")

    def track_pnl(self, strategy: str) -> float:
        try:
            pnl_list = self.performance.get(strategy, {}).get("pnl", [])
            return float(sum(pnl_list))
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.track_pnl error: {e}")
            return 0.0

    def trade_count(self, strategy: str) -> int:
        try:
            return int(len(self.performance.get(strategy, {}).get("pnl", [])))
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.trade_count error: {e}")
            return 0

    def wins(self, strategy: str) -> int:
        try:
            return int(self.performance.get(strategy, {}).get("wins", 0))
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.wins error: {e}")
            return 0

    def losses(self, strategy: str) -> int:
        try:
            return int(self.performance.get(strategy, {}).get("losses", 0))
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.losses error: {e}")
            return 0

    def gross_profit(self, strategy: str) -> float:
        try:
            pnl_list = self.performance.get(strategy, {}).get("pnl", [])
            return float(sum(x for x in pnl_list if x > 0))
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.gross_profit error: {e}")
            return 0.0

    def gross_loss_abs(self, strategy: str) -> float:
        try:
            pnl_list = self.performance.get(strategy, {}).get("pnl", [])
            return float(abs(sum(x for x in pnl_list if x < 0)))
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.gross_loss_abs error: {e}")
            return 0.0

    def profit_factor(self, strategy: str) -> float:
        try:
            gp = self.gross_profit(strategy)
            gl = self.gross_loss_abs(strategy)
            if gl > 0:
                return float(gp / gl)
            if gp > 0:
                return float("inf")
            return 0.0
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.profit_factor error: {e}")
            return 0.0

    def expectancy(self, strategy: str) -> float:
        try:
            pnl_list = self.performance.get(strategy, {}).get("pnl", [])
            if not pnl_list:
                return 0.0
            return float(sum(pnl_list) / len(pnl_list))
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.expectancy error: {e}")
            return 0.0

    def winrate(self, strategy: str) -> float:
        try:
            perf = self.performance.get(strategy, {})
            total = perf.get("wins", 0) + perf.get("losses", 0)
            return perf.get("wins", 0) / total if total > 0 else 0.0
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.winrate error: {e}")
            return 0.0

    def sharpe_ratio(self, strategy: str) -> float:
        try:
            pnl = self.performance.get(strategy, {}).get("pnl", [])
            if not pnl:
                return 0.0
            mean = sum(pnl) / len(pnl)
            std = (
                (sum((x - mean) ** 2 for x in pnl) / len(pnl)) ** 0.5
                if len(pnl) > 1
                else 1.0
            )
            return mean / std if std != 0 else 0.0
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.sharpe_ratio error: {e}")
            return 0.0

    def drawdown(self, strategy: str, window: int = 10) -> float:
        """Calculate rolling drawdown for a strategy over a window."""
        try:
            pnl = self.performance.get(strategy, {}).get("pnl", [])
            if not pnl:
                return 0.0
            recent = pnl[-window:] if len(pnl) >= window else pnl
            peak = max(recent)
            trough = min(recent)
            dd = (peak - trough) / peak if peak != 0 else 0.0
            logger.info(
                f"StrategyTracker: {strategy} rolling drawdown={dd:.4f} "
                f"(window={window})"
            )
            return dd
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.drawdown error: {e}")
            return 0.0

    def hitrate(self, strategy: str) -> float:
        """Calculate hitrate (percentage of winning trades)."""
        try:
            perf = self.performance.get(strategy, {})
            total = perf.get("wins", 0) + perf.get("losses", 0)
            hitrate = perf.get("wins", 0) / total if total > 0 else 0.0
            logger.info(f"StrategyTracker: {strategy} hitrate={hitrate:.2f}")
            return hitrate
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.hitrate error: {e}")
            return 0.0

    def score(self, strategy: str) -> float:
        """Calculate composite score: PnL * winrate - drawdown."""
        try:
            pnl = self.track_pnl(strategy)
            winrate = self.winrate(strategy)
            dd = self.drawdown(strategy)
            score = pnl * winrate - dd
            logger.info(
                f"StrategyTracker: {strategy} score={score:.2f} "
                f"(PnL={pnl}, Winrate={winrate:.2f}, DD={dd:.2f})"
            )
            return score
        except Exception as e:
            logger.error(f"StrategyPerformanceTracker.score error: {e}")
            return 0.0

    def best_performing_strategy(self) -> str:
        try:
            best = None
            best_score = float("-inf")
            for strategy in self.performance:
                score = self.score(strategy)
                if score > best_score:
                    best_score = score
                    best = strategy
            return best
        except Exception as e:
            logger.error(
                ("StrategyPerformanceTracker." f"best_performing_strategy error: {e}")
            )
            return ""
