from core.BotCore import _research_only_hold_transition_debug


def test_hold_transition_debug_default_off(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("RESEARCH_HOLD_TRANSITION_DEBUG", raising=False)
    assert (
        _research_only_hold_transition_debug(
            branch_name="hold_transition",
            symbol="BTCUSDTM",
            entry_decision_before="buy",
            entry_decision_after="hold",
            entry_reason="current_side",
        )
        is None
    )


def test_hold_transition_debug_live_noop(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("RESEARCH_HOLD_TRANSITION_DEBUG", "1")
    assert (
        _research_only_hold_transition_debug(
            branch_name="hold_transition",
            symbol="BTCUSDTM",
            entry_decision_before="buy",
            entry_decision_after="hold",
            entry_reason="current_side",
        )
        is None
    )


def test_hold_transition_debug_builds_payload(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("RESEARCH_HOLD_TRANSITION_DEBUG", "1")
    payload = _research_only_hold_transition_debug(
        branch_name="hold_transition",
        symbol="BTCUSDTM",
        entry_decision_before="buy",
        entry_decision_after="hold",
        entry_reason="current_side",
        branch_fields={"mfe": 0.2, "time_since_peak_sec": 12.5},
    )
    assert payload["branch"] == "hold_transition"
    assert payload["symbol"] == "BTCUSDTM"
    assert payload["entry_decision_before"] == "buy"
    assert payload["entry_decision_after"] == "hold"
    assert payload["entry_reason"] == "current_side"
    assert payload["branch_fields"] == {"mfe": 0.2, "time_since_peak_sec": 12.5}
