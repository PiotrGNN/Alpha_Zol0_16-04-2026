"""
test_risk_manager.py - testowanie SL/TP i kontroli ryzyka
"""

from core.RiskManager import RiskManager


def test_calculate_sl_tp():
    rm = RiskManager(sl_pct=1, tp_pct=2)
    sl, tp = rm.calculate_sl_tp(100)
    assert sl == 99
    assert tp == 102


def test_apply_risk():
    rm = RiskManager()
    allow, sl, tp, alloc = rm.apply_risk("buy", 100, 1000, "none")
    assert allow is True
    assert sl == 99.5
    assert tp == 101.0
    assert alloc == 1000


def test_check_drawdown():
    rm = RiskManager(max_drawdown=0.1)
    pnl_history = [1000, 950, 900]
    assert rm.check_drawdown(pnl_history) is True
    pnl_history = [1000, 990, 980]
    assert rm.check_drawdown(pnl_history) is False


def test_check_drawdown_handles_non_positive_histories():
    rm = RiskManager(max_drawdown=0.1)
    assert rm.check_drawdown([-1.0, -1.5, -2.0]) is True
    assert rm.calc_global_drawdown([-1.0, -1.5, -2.0]) > 0.0


def test_check_drawdown_handles_zero_to_negative_transition():
    rm = RiskManager(max_drawdown=0.1)
    assert rm.check_drawdown([0.0, -0.5, -1.0]) is True
    assert rm.calc_global_drawdown([0.0, -0.5, -1.0]) >= 1.0


def test_check_drawdown_ignores_non_finite_values():
    rm = RiskManager(max_drawdown=0.1)
    history = [1000.0, float("nan"), 900.0, float("inf"), 850.0]
    assert rm.check_drawdown(history) is True
    assert rm.calc_global_drawdown(history) > 0.1


def test_check_drawdown_returns_false_when_all_values_invalid():
    rm = RiskManager(max_drawdown=0.1)
    assert rm.check_drawdown([float("nan"), float("inf")]) is False
    assert rm.calc_global_drawdown([float("nan"), float("inf")]) == 0.0


def test_apply_risk_respects_env_allocation(monkeypatch):
    """If allocation_pct is set in the environment the RiskManager should
    respect that override at runtime."""
    monkeypatch.setenv("allocation_pct", "0.123")
    rm = RiskManager(allocation_pct=0.5)
    allow, sl, tp, alloc = rm.apply_risk("buy", 100.0, 1000.0, "none")
    assert abs(alloc - (0.123 * 1000.0)) < 1e-6
