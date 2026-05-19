from core.BotCore import _resolve_side_guard_history_inputs


def test_side_guard_history_inputs_default_uses_all_history():
    payload = _resolve_side_guard_history_inputs(
        pnl_hist=[-1.0, 0.5, -0.2],
        history_source=["bootstrap", "runtime", "bootstrap"],
        require_runtime_only=False,
    )

    assert payload["history_source"] == "all_history"
    assert payload["bootstrap_trade_count"] == 2
    assert payload["runtime_trade_count"] == 1
    assert payload["effective_trade_count"] == 3
    assert payload["bootstrap_ignored"] is False
    assert payload["effective_pnl_hist"] == [-1.0, 0.5, -0.2]


def test_side_guard_history_inputs_runtime_only_ignores_bootstrap():
    payload = _resolve_side_guard_history_inputs(
        pnl_hist=[-1.0, 0.5, -0.2, 0.1],
        history_source=["bootstrap", "runtime", "bootstrap", "runtime"],
        require_runtime_only=True,
    )

    assert payload["history_source"] == "runtime_only"
    assert payload["bootstrap_trade_count"] == 2
    assert payload["runtime_trade_count"] == 2
    assert payload["effective_trade_count"] == 2
    assert payload["bootstrap_ignored"] is True
    assert payload["effective_pnl_hist"] == [0.5, 0.1]


def test_side_guard_history_inputs_handles_missing_source_entries():
    payload = _resolve_side_guard_history_inputs(
        pnl_hist=[-1.0, 0.5, -0.2],
        history_source=["runtime"],
        require_runtime_only=True,
    )

    assert payload["bootstrap_trade_count"] == 0
    assert payload["runtime_trade_count"] == 1
    assert payload["effective_trade_count"] == 1
    assert payload["effective_pnl_hist"] == [-1.0]
