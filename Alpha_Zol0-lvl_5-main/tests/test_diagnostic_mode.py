import importlib


def _botcore():
    import core.BotCore as botcore

    return importlib.reload(botcore)


def test_baseline_diagnostic_mode_off(monkeypatch):
    botcore = _botcore()
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("DIAGNOSTIC_MODE", raising=False)
    monkeypatch.delenv("DIAG_DISABLE_NET_TARGET_GUARD", raising=False)
    assert botcore._is_gate_disabled("net_target_guard") is False
    assert botcore._is_gate_disabled("current_side") is False
    assert botcore._is_gate_disabled("side_guard") is False
    assert botcore._is_gate_disabled("side_expectancy") is False


def test_net_target_guard_disabled(monkeypatch):
    botcore = _botcore()
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("DIAGNOSTIC_MODE", "1")
    monkeypatch.setenv("DIAG_DISABLE_NET_TARGET_GUARD", "1")
    assert botcore._is_gate_disabled("net_target_guard") is True
    assert botcore._is_gate_disabled("current_side") is False


def test_side_guard_disabled(monkeypatch):
    botcore = _botcore()
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("DIAGNOSTIC_MODE", "1")
    monkeypatch.setenv("DIAG_DISABLE_SIDE_GUARD", "1")
    assert botcore._is_gate_disabled("side_guard") is True
    assert botcore._is_gate_disabled("side_expectancy") is False


def test_side_expectancy_disabled(monkeypatch):
    botcore = _botcore()
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("DIAGNOSTIC_MODE", "1")
    monkeypatch.setenv("DIAG_DISABLE_SIDE_EXPECTANCY", "1")
    assert botcore._is_gate_disabled("side_expectancy") is True
    assert botcore._is_gate_disabled("side_guard") is False


def test_multi_gate_disabled(monkeypatch):
    botcore = _botcore()
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.setenv("DIAGNOSTIC_MODE", "1")
    monkeypatch.setenv("DIAG_DISABLE_NET_TARGET_GUARD", "1")
    monkeypatch.setenv("DIAG_ALLOW_REENTRY_WHILE_IN_POSITION", "1")
    monkeypatch.setenv("DIAG_DISABLE_SIDE_GUARD", "1")
    monkeypatch.setenv("DIAG_DISABLE_SIDE_EXPECTANCY", "1")
    assert botcore._is_gate_disabled("net_target_guard") is True
    assert botcore._is_gate_disabled("current_side") is True
    assert botcore._is_gate_disabled("side_guard") is True
    assert botcore._is_gate_disabled("side_expectancy") is True


def test_live_safety(monkeypatch):
    botcore = _botcore()
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("DIAGNOSTIC_MODE", "1")
    monkeypatch.setenv("DIAG_DISABLE_NET_TARGET_GUARD", "1")
    monkeypatch.setenv("DIAG_ALLOW_REENTRY_WHILE_IN_POSITION", "1")
    monkeypatch.setenv("DIAG_DISABLE_SIDE_GUARD", "1")
    monkeypatch.setenv("DIAG_DISABLE_SIDE_EXPECTANCY", "1")
    assert botcore._is_gate_disabled("net_target_guard") is False
    assert botcore._is_gate_disabled("current_side") is False
    assert botcore._is_gate_disabled("side_guard") is False
    assert botcore._is_gate_disabled("side_expectancy") is False


def test_trace_payload_fields(monkeypatch):
    botcore = _botcore()
    monkeypatch.delenv("LIVE", raising=False)
    payload = botcore._diagnostic_gate_trace(
        "side_guard",
        gate_blocked=True,
        gate_skipped=False,
        entry_decision_before="buy",
        entry_decision_after="hold",
    )
    assert payload["gate_name"] == "side_guard"
    assert payload["gate_blocked"] is True
    assert payload["gate_skipped"] is False
    assert payload["skip_reason"] is None
    assert payload["entry_decision_before"] == "buy"
    assert payload["entry_decision_after"] == "hold"
