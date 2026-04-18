# test_riskmanager_rolling.py – Test rolling drawdown i logów RiskManager
from core.RiskManager import RiskManager


def test_rolling_drawdown_logging(caplog):
    caplog.set_level("INFO")
    rm = RiskManager(max_drawdown=0.1)
    pnl_history = [1000, 950, 900, 920, 910, 905, 890, 880, 870, 860, 850]
    result = rm.check_drawdown(pnl_history, window=5)
    # Sprawdź czy rolling drawdown jest logowany
    log_found = any("rolling drawdown" in r.getMessage() for r in caplog.records)
    assert log_found
    assert isinstance(result, bool)
