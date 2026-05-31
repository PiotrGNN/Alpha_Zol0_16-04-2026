from core.BotCore import (
    _canonical_bucket_trace_for_summary,
    _classify_entry_gate_bucket,
    _classify_entry_reason,
    _classify_entry_reason_with_gate_fallback,
    _derive_entry_reason_from_signal_funnel,
    _classify_entry_open_truth,
    _build_entry_identity_fields,
    _diagnostic_gate_trace,
    _normalize_local_gate_reason_for_summary,
    _resolve_entry_policy_pipeline,
    _resolve_entry_gate_reason_context,
    _resolve_local_gate_reason,
    _should_fail_closed_unknown_fallback_admission,
)


def test_case_1_current_side():
    assert _classify_entry_reason("current_side") == "position_hold"


def test_case_2_loss_cooldown():
    assert _classify_entry_reason("loss_cooldown") == "cooldown_block"


def test_case_3_fallback():
    assert _classify_entry_reason(None) == "unknown_fallback"
    assert _classify_entry_reason("") == "unknown_fallback"
    assert _classify_entry_reason("some_unknown_reason") == "unknown_fallback"


def test_case_4_existing_reason_not_overwritten():
    assert _classify_entry_reason("entry_live_edge_proxy") == "risk_block"
    assert _classify_entry_reason("symbol_blocklist") == "risk_block"
    assert _classify_entry_reason("hysteresis") == "prefilter_block"
    assert _classify_entry_reason("profit_focus_history_not_ready") == "risk_block"
    assert _classify_entry_reason("profit_focus_confidence_too_low") == "risk_block"
    assert _classify_entry_reason("missing_strategy_field") == "prefilter_block"
    assert _classify_entry_reason("hold_ignored") == "prefilter_block"


def test_gate_reason_fallback_uses_effective_gate_reason():
    assert (
        _classify_entry_reason_with_gate_fallback(
            entry_reason=None,
            effective_gate_reason="missing_strategy_field",
        )
        == "prefilter_block"
    )
    assert (
        _classify_entry_reason_with_gate_fallback(
            entry_reason=None,
            effective_gate_reason="hold_ignored",
        )
        == "prefilter_block"
    )
    assert (
        _classify_entry_reason_with_gate_fallback(
            entry_reason="current_side",
            effective_gate_reason="missing_strategy_field",
        )
        == "position_hold"
    )


def test_local_gate_fallback_resolution():
    assert _resolve_local_gate_reason(None, None) == "risk_or_prefilter_block_fallback"
    assert _resolve_local_gate_reason("current_side", None) == "current_side"
    assert _resolve_local_gate_reason("loss_cooldown", None) == "loss_cooldown"
    assert (
        _resolve_local_gate_reason("current_side", "paper_gate_active")
        == "paper_gate_active"
    )


def test_local_gate_reason_normalization_keeps_existing_fallback_case():
    normalized = _normalize_local_gate_reason_for_summary(
        local_gate_reason="risk_or_prefilter_block_fallback",
        entry_reason="",
        main_strategy="TrendFollowing",
        entry_decision_raw="hold",
        entry_decision_final="hold",
        ensemble_signals=[{"strategy": "TrendFollowing", "signal": "hold"}],
        filtered_ensemble_signals=[{"strategy": "TrendFollowing", "signal": "hold"}],
    )
    assert normalized == "risk_or_prefilter_block_fallback"


def test_local_gate_reason_normalization_maps_missing_strategy_field():
    normalized = _normalize_local_gate_reason_for_summary(
        local_gate_reason="risk_or_prefilter_block_fallback",
        entry_reason=None,
        main_strategy=None,
        entry_decision_raw="hold",
        entry_decision_final="hold",
        ensemble_signals=[{"signal": "buy"}],
        filtered_ensemble_signals=[],
    )
    assert normalized == "missing_strategy_field"

    ctx = _resolve_entry_gate_reason_context(
        global_block_reason=None,
        local_gate_reason=normalized,
        entry_reason=None,
    )
    assert ctx == {
        "effective_gate_reason": "missing_strategy_field",
        "effective_gate_reason_origin": "local_gate_reason",
    }


def test_local_gate_reason_normalization_maps_bucket_identity_missing():
    normalized = _normalize_local_gate_reason_for_summary(
        local_gate_reason="risk_or_prefilter_block_fallback",
        entry_reason=None,
        main_strategy=None,
        entry_decision_raw="hold",
        entry_decision_final="hold",
        ensemble_signals=None,
        filtered_ensemble_signals=None,
        dropped_ensemble_signals=None,
        bucket_identity_reason="missing_strategy_field",
    )
    assert normalized == "missing_strategy_field"


def test_local_gate_reason_normalization_does_not_change_final_allow_semantics():
    allow = False
    entry_decision = "hold"
    final_allow_before = bool(allow and entry_decision in ("buy", "sell"))

    normalized = _normalize_local_gate_reason_for_summary(
        local_gate_reason="risk_or_prefilter_block_fallback",
        entry_reason=None,
        main_strategy=None,
        entry_decision_raw="hold",
        entry_decision_final="hold",
        ensemble_signals=[{"signal": "buy"}],
        filtered_ensemble_signals=[],
    )

    final_allow_after = bool(allow and entry_decision in ("buy", "sell"))
    assert normalized == "missing_strategy_field"
    assert final_allow_before is False
    assert final_allow_after is False


def test_local_gate_reason_normalization_prefers_dropped_hold_reason():
    normalized = _normalize_local_gate_reason_for_summary(
        local_gate_reason="risk_or_prefilter_block_fallback",
        entry_reason=None,
        main_strategy=None,
        entry_decision_raw="hold",
        entry_decision_final="hold",
        ensemble_signals=[{"signal": "hold"}],
        filtered_ensemble_signals=[],
        dropped_ensemble_signals=[{"reason": "hold_ignored"}],
    )

    assert normalized == "hold_ignored"


def test_local_gate_reason_normalization_prefers_non_hold_block_over_hold_noise():
    normalized = _normalize_local_gate_reason_for_summary(
        local_gate_reason="risk_or_prefilter_block_fallback",
        entry_reason=None,
        main_strategy=None,
        entry_decision_raw="hold",
        entry_decision_final="hold",
        ensemble_signals=[{"signal": "hold"}, {"signal": "sell"}],
        filtered_ensemble_signals=[],
        dropped_ensemble_signals=[
            {"reason": "hold_ignored"},
            {"reason": "symbol_strategy_side_blocklist"},
            {"reason": "hold_ignored"},
        ],
    )

    assert normalized == "symbol_strategy_side_blocklist"


def test_derive_entry_reason_from_signal_funnel_prefers_dropped_hold_reason():
    reason = _derive_entry_reason_from_signal_funnel(
        entry_decision_raw="hold",
        entry_decision_final="hold",
        ensemble_signals=[{"signal": "hold"}],
        filtered_ensemble_signals=[],
        dropped_ensemble_signals=[{"reason": "hold_ignored"}],
    )

    assert reason == "hold_ignored"


def test_derive_entry_reason_from_signal_funnel_prefers_non_hold_block():
    reason = _derive_entry_reason_from_signal_funnel(
        entry_decision_raw="hold",
        entry_decision_final="hold",
        ensemble_signals=[{"signal": "hold"}, {"signal": "sell"}],
        filtered_ensemble_signals=[],
        dropped_ensemble_signals=[
            {"reason": "hold_ignored"},
            {"reason": "symbol_strategy_side_allowlist"},
        ],
    )

    assert reason == "symbol_strategy_side_allowlist"


def test_derive_entry_reason_from_signal_funnel_maps_missing_strategy():
    reason = _derive_entry_reason_from_signal_funnel(
        entry_decision_raw="hold",
        entry_decision_final="hold",
        ensemble_signals=[{"signal": "buy"}],
        filtered_ensemble_signals=[],
        dropped_ensemble_signals=[{"reason": "missing_strategy"}],
    )

    assert reason == "missing_strategy_field"


def test_entry_policy_pipeline_requires_supporting_signal_for_decision_side():
    decision, reason = _resolve_entry_policy_pipeline(
        symbol="BTC-USDT",
        decision_value="buy",
        current_side=None,
        current_side_disabled=False,
        reverse_entry=False,
        now_ts=100.0,
        signal_score=0.25,
        ensemble_signals=[{"strategy": "TrendFollowing", "signal": "sell"}],
        filtered_ensemble_signals=[{"strategy": "TrendFollowing", "_side": "sell"}],
        dropped_ensemble_signals=[],
        last_decision_state={},
        entry_symbol_allowlist=set(),
        entry_symbol_blocklist=set(),
        entry_symbol_strategy_side_allowlist=set(),
        signal_votes=[],
        entry_allow_buy=True,
        entry_allow_sell=True,
        decision_hysteresis_score=0.1,
        decision_change_cooldown_sec=30.0,
    )

    assert decision == "hold"
    assert reason == "no_supporting_signal"


def test_entry_policy_pipeline_updates_last_state_from_supporting_basket():
    last_state = {}
    decision, reason = _resolve_entry_policy_pipeline(
        symbol="BTC-USDT",
        decision_value="buy",
        current_side=None,
        current_side_disabled=False,
        reverse_entry=False,
        now_ts=125.0,
        signal_score=0.4,
        ensemble_signals=[{"strategy": "Momentum", "signal": "buy"}],
        filtered_ensemble_signals=[{"strategy": "Momentum", "_side": "buy"}],
        dropped_ensemble_signals=[],
        last_decision_state=last_state,
        entry_symbol_allowlist=set(),
        entry_symbol_blocklist=set(),
        entry_symbol_strategy_side_allowlist=set(),
        signal_votes=[],
        entry_allow_buy=True,
        entry_allow_sell=True,
        decision_hysteresis_score=0.1,
        decision_change_cooldown_sec=30.0,
    )

    assert decision == "buy"
    assert reason is None
    assert last_state == {"BTC-USDT": {"decision": "buy", "ts": 125.0}}


def test_unknown_fallback_admission_is_blocked_in_kucoin_paper_futures():
    assert (
        _should_fail_closed_unknown_fallback_admission(
            simulate=True,
            market_type="futures",
            allow=True,
            entry_decision="buy",
            entry_reason=None,
        )
        is True
    )
    assert (
        _should_fail_closed_unknown_fallback_admission(
            simulate=True,
            market_type="futures",
            allow=True,
            entry_decision="buy",
            entry_reason=None,
            signal_confidence_abs=0.35,
            history_ready=True,
        )
        is True
    )
    assert (
        _should_fail_closed_unknown_fallback_admission(
            simulate=True,
            market_type="futures",
            allow=True,
            entry_decision="buy",
            entry_reason=None,
            signal_confidence_abs=None,
            history_ready=False,
        )
        is True
    )


def test_unknown_fallback_admission_guard_does_not_block_non_fallback_or_non_paper():
    assert (
        _should_fail_closed_unknown_fallback_admission(
            simulate=True,
            market_type="futures",
            allow=True,
            entry_decision="buy",
            entry_reason="seed_trades_override",
        )
        is False
    )
    assert (
        _should_fail_closed_unknown_fallback_admission(
            simulate=True,
            market_type="futures",
            allow=True,
            entry_decision="buy",
            entry_reason=None,
            signal_confidence_abs=0.75,
            history_ready=True,
        )
        is False
    )
    assert (
        _should_fail_closed_unknown_fallback_admission(
            simulate=True,
            market_type="futures",
            allow=True,
            entry_decision="buy",
            entry_reason=None,
            signal_confidence_abs=0.75,
            history_ready=False,
        )
        is False
    )
    assert (
        _should_fail_closed_unknown_fallback_admission(
            simulate=False,
            market_type="futures",
            allow=True,
            entry_decision="buy",
            entry_reason=None,
        )
        is False
    )
    assert (
        _should_fail_closed_unknown_fallback_admission(
            simulate=True,
            market_type="spot",
            allow=True,
            entry_decision="buy",
            entry_reason=None,
        )
        is False
    )


def test_unknown_fallback_admission_guard_respects_fail_open_coldstart():
    assert (
        _should_fail_closed_unknown_fallback_admission(
            simulate=True,
            market_type="futures",
            allow=True,
            entry_decision="buy",
            entry_reason=None,
            signal_confidence_abs=0.45,
            history_ready=False,
            coldstart_mode="fail_open",
        )
        is False
    )
    assert (
        _should_fail_closed_unknown_fallback_admission(
            simulate=True,
            market_type="futures",
            allow=True,
            entry_decision="buy",
            entry_reason=None,
            signal_confidence_abs=0.45,
            history_ready=False,
            coldstart_mode="seed_only",
        )
        is True
    )


def test_entry_gate_reason_normalization_handles_exceptions_and_fallbacks():
    class BadReason:
        def __str__(self):
            raise RuntimeError("boom")

    assert _resolve_entry_gate_reason_context(
        global_block_reason=None,
        local_gate_reason=None,
        entry_reason=None,
    ) == {
        "effective_gate_reason": "risk_or_prefilter_block_fallback",
        "effective_gate_reason_origin": "fallback",
    }
    assert _resolve_entry_gate_reason_context(
        global_block_reason="paper_gate_active",
        local_gate_reason=None,
        entry_reason="current_side",
    ) == {
        "effective_gate_reason": "paper_gate_active",
        "effective_gate_reason_origin": "global_block_reason",
    }
    assert _resolve_entry_gate_reason_context(
        global_block_reason=None,
        local_gate_reason="side_guard",
        entry_reason="current_side",
    ) == {
        "effective_gate_reason": "side_guard",
        "effective_gate_reason_origin": "local_gate_reason",
    }
    assert _resolve_entry_gate_reason_context(
        global_block_reason=None,
        local_gate_reason=None,
        entry_reason="current_side",
    ) == {
        "effective_gate_reason": "current_side",
        "effective_gate_reason_origin": "entry_reason",
    }
    assert _resolve_entry_gate_reason_context(
        global_block_reason=BadReason(),
        local_gate_reason="side_guard",
        entry_reason="current_side",
    ) == {
        "effective_gate_reason": "side_guard",
        "effective_gate_reason_origin": "local_gate_reason",
    }


def test_entry_gate_reason_context_prefers_global_reason():
    ctx = _resolve_entry_gate_reason_context(
        global_block_reason="paper_gate_active",
        local_gate_reason="current_side",
        entry_reason="loss_cooldown",
    )
    assert ctx["effective_gate_reason"] == "paper_gate_active"
    assert ctx["effective_gate_reason_origin"] == "global_block_reason"


def test_entry_gate_bucket_classification_for_history_coldstart():
    bucket = _classify_entry_gate_bucket(
        final_allow=False,
        effective_gate_reason="insufficient_history_seed_only",
        effective_gate_reason_origin="local_gate_reason",
        research_block_active=False,
    )
    assert bucket == "history_coldstart"


def test_entry_gate_bucket_classification_for_research_block():
    bucket = _classify_entry_gate_bucket(
        final_allow=False,
        effective_gate_reason="net_target_guard",
        effective_gate_reason_origin="local_gate_reason",
        research_block_active=True,
    )
    assert bucket == "research_loss_driver_block"


def test_entry_gate_bucket_classification_for_admitted_path():
    bucket = _classify_entry_gate_bucket(
        final_allow=True,
        effective_gate_reason="allow",
        effective_gate_reason_origin="entry_reason",
        research_block_active=False,
    )
    assert bucket == "admitted"


def test_entry_gate_bucket_classification_covers_global_and_prefilter_paths():
    bucket = _classify_entry_gate_bucket(
        final_allow=False,
        effective_gate_reason="paper_gate_active",
        effective_gate_reason_origin="global_block_reason",
        research_block_active=False,
    )
    assert bucket == "global_gate_block"

    bucket = _classify_entry_gate_bucket(
        final_allow=False,
        effective_gate_reason="entry_edge_filtered",
        effective_gate_reason_origin="local_gate_reason",
        research_block_active=False,
    )
    assert bucket == "economics_or_quality_guard"

    bucket = _classify_entry_gate_bucket(
        final_allow=False,
        effective_gate_reason="current_side",
        effective_gate_reason_origin="local_gate_reason",
        research_block_active=False,
    )
    assert bucket == "position_side_guard"

    bucket = _classify_entry_gate_bucket(
        final_allow=False,
        effective_gate_reason="profit_gate",
        effective_gate_reason_origin="local_gate_reason",
        research_block_active=False,
    )
    assert bucket == "cooldown_guard"

    bucket = _classify_entry_gate_bucket(
        final_allow=False,
        effective_gate_reason="hysteresis",
        effective_gate_reason_origin="local_gate_reason",
        research_block_active=False,
    )
    assert bucket == "prefilter_guard"


def test_entry_gate_bucket_classification_locks_coldstart_reason_family():
    for reason in (
        "insufficient_history_seed_only",
        "insufficient_history_fail_open",
        "seed_trades_override",
    ):
        assert (
            _classify_entry_gate_bucket(
                final_allow=False,
                effective_gate_reason=reason,
                effective_gate_reason_origin="local_gate_reason",
                research_block_active=False,
            )
            == "history_coldstart"
        )


def test_entry_gate_bucket_classification_locks_fallback_reason_family():
    for reason in ("risk_or_prefilter_block_fallback", "unknown_fallback"):
        assert (
            _classify_entry_gate_bucket(
                final_allow=False,
                effective_gate_reason=reason,
                effective_gate_reason_origin="local_gate_reason",
                research_block_active=False,
            )
            == "fallback_guard"
        )


def test_entry_gate_bucket_classification_locks_prefilter_reason_family():
    for reason in (
        "symbol_allowlist",
        "strategy_blocklist",
        "buy_disabled",
        "low_votes",
        "router_lead_filtered",
        "buy_score",
        "sell_trend",
    ):
        assert (
            _classify_entry_gate_bucket(
                final_allow=False,
                effective_gate_reason=reason,
                effective_gate_reason_origin="local_gate_reason",
                research_block_active=False,
            )
            == "prefilter_guard"
        )


def test_entry_open_truth_classification_maps_auto_open_sources():
    assert (
        _classify_entry_open_truth(
            selection_source="entry_symbol_strategy_side_allowlist",
            entry_reason="paper_auto_open_allowlisted",
            decision_router_path="paper_auto_open_allowlisted",
            override_reason="paper_auto_open_allowlisted",
        )
        == "BOOTSTRAP_ALLOWLIST_ASSISTED"
    )
    assert (
        _classify_entry_open_truth(
            selection_source="paper_auto_open_fallback",
            entry_reason="auto_test_open",
            decision_router_path="paper_auto_open_fallback",
            override_reason="paper_auto_open_fallback",
        )
        == "PAPER_AUTO_OPEN_FALLBACK"
    )
    assert (
        _classify_entry_open_truth(
            selection_source=None,
            entry_reason="seed_trades_override",
            decision_router_path="router_selection",
            override_reason=None,
        )
        == "SEED_TRADES_OVERRIDE_ASSISTED"
    )
    assert (
        _classify_entry_open_truth(
            selection_source=None,
            entry_reason="edge_discovered_dynamic",
            decision_router_path="router_selection",
            override_reason=None,
        )
        == "EDGE_DISCOVERED_DYNAMIC"
    )
    assert (
        _classify_entry_open_truth(
            selection_source=None,
            entry_reason=None,
            decision_router_path=None,
            override_reason=None,
        )
        == "NATURAL_STRATEGY_ENTRY"
    )

    bucket = _classify_entry_gate_bucket(
        final_allow=False,
        effective_gate_reason="unexpected_reason",
        effective_gate_reason_origin="local_gate_reason",
        research_block_active=False,
    )
    assert bucket == "other_local_guard"

    bucket = _classify_entry_gate_bucket(
        final_allow=False,
        effective_gate_reason="risk_or_prefilter_block_fallback",
        effective_gate_reason_origin="local_gate_reason",
        research_block_active=False,
    )
    assert bucket == "fallback_guard"


def test_build_entry_identity_fields_carries_canonical_bucket_key():
    identity = _build_entry_identity_fields(
        symbol="BTCUSDTM",
        strategy="TrendFollowing",
        side="buy",
        selection_source="entry_symbol_strategy_side_allowlist",
        decision_router_path="paper_auto_open_allowlisted",
        entry_reason="paper_auto_open_allowlisted",
        override_reason="paper_auto_open_allowlisted",
    )

    assert identity["symbol"] == "BTCUSDTM"
    assert identity["strategy"] == "TrendFollowing"
    assert identity["entry_main_strategy"] == "TrendFollowing"
    assert identity["side"] == "buy"
    assert identity["canonical_bucket_key"] == "BTCUSDTM|TRENDFOLLOWING|buy"
    assert identity["canonical_bucket"]["bucket_identity_status"] == "RESOLVED"


def test_canonical_bucket_trace_for_summary_defaults_to_empty_dict():
    assert _canonical_bucket_trace_for_summary(None) == {}
    assert _canonical_bucket_trace_for_summary({}) == {}
    assert _canonical_bucket_trace_for_summary({"canonical_bucket": None}) == {}


def test_canonical_bucket_trace_for_summary_returns_bucket_payload():
    summary = {
        "canonical_bucket": {
            "canonical_bucket_key": "BTCUSDTM|TRENDFOLLOWING|buy",
            "bucket_identity_reason": "explicit_strategy",
        }
    }

    assert _canonical_bucket_trace_for_summary(summary) == summary["canonical_bucket"]


def test_diagnostic_gate_trace_defaults_blocker_label_from_gate_name():
    payload = _diagnostic_gate_trace(
        "net_target_guard",
        gate_blocked=True,
        gate_skipped=False,
        entry_decision_before="buy",
        entry_decision_after="hold",
    )

    assert payload["gate_name"] == "net_target_guard"
    assert payload["gate_blocked"] is True
    assert payload["gate_skipped"] is False
    assert payload["local_gate_reason_final"] == "net_target_guard"


def test_diagnostic_gate_trace_defaults_skipped_blocker_label_from_gate_name():
    payload = _diagnostic_gate_trace(
        "rr_net_guard",
        gate_blocked=False,
        gate_skipped=True,
        skip_reason="diagnostic_override",
        entry_decision_before="buy",
        entry_decision_after="buy",
    )

    assert payload["gate_name"] == "rr_net_guard"
    assert payload["gate_blocked"] is False
    assert payload["gate_skipped"] is True
    assert payload["skip_reason"] == "diagnostic_override"
    assert payload["local_gate_reason_final"] == "rr_net_guard"
