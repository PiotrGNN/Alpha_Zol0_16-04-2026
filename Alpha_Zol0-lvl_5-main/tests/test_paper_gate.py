from datetime import datetime, timedelta, timezone

from utils import paper_gate


def test_paper_gate_activation_and_cooldown():
    paper_gate.reset_state()
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)

    state = paper_gate.update_gate(-1.0, now=now, target=0.5)
    assert state["active"] is False

    state = paper_gate.update_gate(-0.5, now=now + timedelta(minutes=1), target=0.5)
    assert state["active"] is True
    assert state["reason"] == "net_pnl_15m_negative_twice"
    assert state["mode"] == "HARD_NEGATIVE"
    assert state["trigger_count"] == 2

    # Still active before cooldown ends
    state = paper_gate.get_state(now=now + timedelta(minutes=10))
    assert state["active"] is True

    # After cooldown, gate should deactivate
    state = paper_gate.get_state(now=now + timedelta(minutes=16))
    assert state["active"] is False


def test_paper_gate_soft_below_target():
    paper_gate.reset_state()
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(3):
        state = paper_gate.update_gate(0.1, now=now + timedelta(minutes=i), target=0.5)
        assert state["active"] is False
    state = paper_gate.update_gate(0.1, now=now + timedelta(minutes=3), target=0.5)
    assert state["active"] is True
    assert state["mode"] == "SOFT_BELOW_TARGET"
    assert state["reason"] == "net_pnl_15m_below_target"
    assert state["trigger_count"] == 4
