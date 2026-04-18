# test_strategytracker_ext.py – Test rozszerzonych metryk
# StrategyPerformanceTracker

from core.StrategyPerformanceTracker import (
    StrategyPerformanceTracker,
)


def test_extended_metrics():
    tracker = StrategyPerformanceTracker()
    tracker.update("stratA", {"pnl": 10})
    tracker.update("stratA", {"pnl": -5})
    tracker.update("stratA", {"pnl": 20})
    tracker.update("stratB", {"pnl": 5})
    tracker.update("stratB", {"pnl": 5})
    # Test drawdown
    dd_a = tracker.drawdown("stratA")
    dd_b = tracker.drawdown("stratB")
    assert dd_a >= 0 and dd_b >= 0
    # Test hitrate
    hr_a = tracker.hitrate("stratA")
    hr_b = tracker.hitrate("stratB")
    assert 0 <= hr_a <= 1 and 0 <= hr_b <= 1
    # Test score
    score_a = tracker.score("stratA")
    score_b = tracker.score("stratB")
    assert isinstance(score_a, (int, float)) and isinstance(score_b, (int, float))
    # Test best_performing_strategy
    best = tracker.best_performing_strategy()
    assert best in ["stratA", "stratB"]
