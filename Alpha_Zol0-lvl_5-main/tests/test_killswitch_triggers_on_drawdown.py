# Kill-switch must trigger on drawdown
from core.RiskManager import RiskManager
from core import kill_switch


def test_killswitch_triggers_on_drawdown():
    kill_switch.reset()
    rm = RiskManager(max_drawdown=0.1)
    pnl_history = [1000, 900, 800]
    assert rm.check_drawdown(pnl_history) is True
    assert kill_switch.is_active() is True
