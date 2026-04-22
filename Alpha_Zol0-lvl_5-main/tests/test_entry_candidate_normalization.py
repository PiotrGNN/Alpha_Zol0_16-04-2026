from core.BotCore import (
    _normalize_local_gate_reason_for_summary,
    _resolve_entry_candidate_strategy,
)


def test_resolve_entry_candidate_strategy_uses_main_strategy_alias():
    strategy = _resolve_entry_candidate_strategy(
        {"main_strategy": "TrendFollowing", "signal": {"side": "buy"}}
    )

    assert strategy == "TrendFollowing"


def test_resolve_entry_candidate_strategy_uses_nested_signal_alias():
    strategy = _resolve_entry_candidate_strategy(
        {"signal": {"selected_strategy": "Momentum", "side": "sell"}}
    )

    assert strategy == "Momentum"


def test_normalize_local_gate_reason_treats_blank_main_strategy_as_missing():
    normalized = _normalize_local_gate_reason_for_summary(
        local_gate_reason="risk_or_prefilter_block_fallback",
        entry_reason=None,
        main_strategy="  ",
        entry_decision_raw="hold",
        entry_decision_final="hold",
        ensemble_signals=[{"strategy": ""}],
        filtered_ensemble_signals=[],
    )

    assert normalized == "missing_strategy_field"


def test_normalize_local_gate_reason_keeps_fallback_when_strategy_alias_present():
    normalized = _normalize_local_gate_reason_for_summary(
        local_gate_reason="risk_or_prefilter_block_fallback",
        entry_reason=None,
        main_strategy=None,
        entry_decision_raw="hold",
        entry_decision_final="hold",
        ensemble_signals=[{"strategy": "Momentum", "signal": "buy"}],
        filtered_ensemble_signals=[],
    )

    assert normalized == "risk_or_prefilter_block_fallback"
