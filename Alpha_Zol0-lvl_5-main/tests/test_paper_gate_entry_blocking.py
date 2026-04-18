from core.BotCore import apply_paper_gate_entry_guard
from core.PositionManager import PositionManager


def test_paper_gate_blocks_entry_only():
    pm = PositionManager()
    order = {
        "symbol": "BTCUSDTM",
        "side": "buy",
        "amount": 1,
        "price": 100.0,
        "timestamp": 1,
    }
    allow = apply_paper_gate_entry_guard(True, 100.0, True)
    if allow:
        pm.update_position("BTCUSDTM", order)
    assert pm.get_position("BTCUSDTM") is None


def test_paper_gate_allows_exit_when_active():
    pm = PositionManager()
    pm.open_position(
        {
            "symbol": "BTCUSDTM",
            "side": "buy",
            "amount": 1,
            "entry_price": 100.0,
            "timestamp": 1,
        }
    )
    allow = apply_paper_gate_entry_guard(True, 0.0, True)
    assert allow is True
    if allow:
        pm.close_position("BTCUSDTM", timestamp=2)
    assert pm.get_position("BTCUSDTM") is None
    assert len(pm.closed) == 1


def test_paper_gate_defers_to_allow_flag_when_gate_inactive():
    assert apply_paper_gate_entry_guard(True, 100.0, False) is True
    assert apply_paper_gate_entry_guard(False, 100.0, False) is False
