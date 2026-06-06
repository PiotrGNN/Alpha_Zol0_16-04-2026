from core.runtime_v2.contracts import EntryCandidate, FeatureFrame, QuoteTick
from core.runtime_v2.risk_engine import ContractSpec, RiskEngineV2


def _candidate(
    *,
    expected_net_after_cost: float = 0.0035,
    symbol: str = "BTCUSDTM",
    side: str = "buy",
    strategy: str = "MomentumV2",
    probability_of_profit: float = 0.74,
) -> EntryCandidate:
    quote = QuoteTick(
        symbol=symbol,
        ts_ms=1,
        bid=100.0,
        ask=100.2,
        mid=100.1,
        spread_abs=0.2,
        spread_bps=19.98,
        best_bid_size=10.0,
        best_ask_size=12.0,
        raw={},
    )
    feature = FeatureFrame(
        symbol=symbol,
        ts_ms=1,
        mid=100.1,
        ret_1=0.0008,
        ret_3=0.0012,
        volatility=0.0009,
        spread_bps=19.98,
        has_profile=True,
        sample_count=20,
    )
    return EntryCandidate(
        symbol=symbol,
        side=side,
        strategy=strategy,
        score=0.3,
        confidence=0.8,
        expected_move=0.0045,
        expected_edge_after_fee=0.0033,
        expected_net_after_cost=expected_net_after_cost,
        probability_of_profit=probability_of_profit,
        quote=quote,
        feature=feature,
        reason_code="momentum_signal",
        cost_breakdown={"fee_rate": 0.0006, "fee_round_trip_ratio": 0.0012},
    )


def _engine_with_spec(symbol: str = "BTCUSDTM") -> RiskEngineV2:
    engine = RiskEngineV2()
    engine.spec_resolver.get = lambda _symbol: ContractSpec(
        symbol=symbol,
        multiplier=0.001,
        lot_size=1.0,
        min_size=1.0,
        max_size=5000.0,
    )
    return engine


def test_admission_reachability_profile_default_off_preserves_entry_min_guard(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.delenv("V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE", raising=False)
    monkeypatch.setenv("ENTRY_MIN_NET_USDT", "0.12")
    engine = _engine_with_spec("SOLUSDTM")

    plan = engine.build_order_plan(
        candidate=_candidate(
            symbol="SOLUSDTM",
            side="buy",
            strategy="TrendFollowingV2",
            expected_net_after_cost=0.0035,
            probability_of_profit=0.999,
        ),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is False
    assert plan.reason_code == "entry_min_net_guard"


def test_admission_reachability_profile_on_relaxes_entry_min_guard(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE", "1")
    monkeypatch.setenv("ENTRY_MIN_NET_USDT", "0.12")
    engine = _engine_with_spec("SOLUSDTM")

    plan = engine.build_order_plan(
        candidate=_candidate(
            symbol="SOLUSDTM",
            side="buy",
            strategy="TrendFollowingV2",
            expected_net_after_cost=0.0035,
            probability_of_profit=0.999,
        ),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is True
    assert plan.reason_code == "allow"
    assert engine.entry_min_net_usdt == 0.02


def test_admission_reachability_profile_live_ignores_entry_min_relaxation(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE", "1")
    monkeypatch.setenv("ENTRY_MIN_NET_USDT", "0.12")
    engine = _engine_with_spec("SOLUSDTM")

    plan = engine.build_order_plan(
        candidate=_candidate(
            symbol="SOLUSDTM",
            side="buy",
            strategy="TrendFollowingV2",
            expected_net_after_cost=0.0035,
            probability_of_profit=0.999,
        ),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is False
    assert plan.reason_code == "entry_min_net_guard"
    assert engine.entry_min_net_usdt == 0.12
    assert plan.sizing_trace["expected_net_after_full_cost"] > 0.0
    assert plan.sizing_trace["entry_min_net_usdt"] == 0.12

def test_immediate_adverse_guard_disabled_preserves_admission(monkeypatch):
    monkeypatch.delenv("V2_PAPER_IMMEDIATE_ADVERSE_GUARD_ENABLE", raising=False)
    engine = _engine_with_spec("SOLUSDTM")

    plan = engine.build_order_plan(
        candidate=_candidate(
            symbol="SOLUSDTM",
            side="buy",
            strategy="TrendFollowingV2",
            expected_net_after_cost=0.0035,
            probability_of_profit=0.999,
        ),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is True
    assert plan.reason_code == "allow"

def test_immediate_adverse_guard_does_not_block_without_shadow_verified_rule(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("V2_PAPER_IMMEDIATE_ADVERSE_GUARD_ENABLE", "1")
    monkeypatch.setenv(
        "V2_PAPER_IMMEDIATE_ADVERSE_GUARD_PROFILE_BLOCKLIST",
        "SOLUSDTM:buy:TrendFollowingV2",
    )
    engine = _engine_with_spec("SOLUSDTM")

    plan = engine.build_order_plan(
        candidate=_candidate(
            symbol="SOLUSDTM",
            side="buy",
            strategy="TrendFollowingV2",
            expected_net_after_cost=0.0035,
            probability_of_profit=0.999,
        ),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is True
    assert plan.reason_code == "allow"
    assert plan.sizing_trace["immediate_adverse_guard_type"] == "SYMBOL_SIDE_PROFILE_QUARANTINE"
    assert plan.sizing_trace["immediate_adverse_guard_reason"] == "shadow_net_benefit_unverified"
    assert plan.sizing_trace["historical_immediate_adverse_rate"] > 0.0
    assert plan.sizing_trace["historical_tail_loss_net"] < 0.0
    assert plan.sizing_trace["immediate_adverse_guard_blocked"] is False
    assert plan.sizing_trace["immediate_adverse_guard_allowed"] is True
    assert plan.sizing_trace["shadow_verified_guard_required"] is True

def test_immediate_adverse_guard_trace_survives_downstream_entry_min_reject(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("V2_PAPER_IMMEDIATE_ADVERSE_GUARD_ENABLE", "1")
    monkeypatch.setenv(
        "V2_PAPER_IMMEDIATE_ADVERSE_GUARD_PROFILE_BLOCKLIST",
        "SOLUSDTM:buy:TrendFollowingV2",
    )
    monkeypatch.setenv("ENTRY_MIN_NET_USDT", "0.12")
    engine = _engine_with_spec("SOLUSDTM")

    plan = engine.build_order_plan(
        candidate=_candidate(
            symbol="SOLUSDTM",
            side="buy",
            strategy="TrendFollowingV2",
            expected_net_after_cost=0.0035,
            probability_of_profit=0.999,
        ),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is False
    assert plan.reason_code == "entry_min_net_guard"
    assert plan.sizing_trace["immediate_adverse_guard_reason"] == (
        "shadow_net_benefit_unverified"
    )
    assert plan.sizing_trace["immediate_adverse_guard_shadow_candidate"] is True
    assert plan.sizing_trace["immediate_adverse_guard_blocked"] is False

def test_immediate_adverse_guard_allows_other_paper_profile(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("V2_PAPER_IMMEDIATE_ADVERSE_GUARD_ENABLE", "1")
    monkeypatch.setenv(
        "V2_PAPER_IMMEDIATE_ADVERSE_GUARD_PROFILE_BLOCKLIST",
        "SOLUSDTM:buy:TrendFollowingV2",
    )
    engine = _engine_with_spec("SOLUSDTM")

    plan = engine.build_order_plan(
        candidate=_candidate(
            symbol="SOLUSDTM",
            side="sell",
            strategy="TrendFollowingV2",
            expected_net_after_cost=0.0035,
            probability_of_profit=0.999,
        ),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is True
    assert plan.reason_code == "allow"
    assert plan.sizing_trace["immediate_adverse_guard_type"] == "SYMBOL_SIDE_PROFILE_QUARANTINE"
    assert plan.sizing_trace["immediate_adverse_guard_reason"] == "profile_not_quarantined"

def test_live_ignores_immediate_adverse_guard(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("V2_PAPER_IMMEDIATE_ADVERSE_GUARD_ENABLE", "1")
    monkeypatch.setenv(
        "V2_PAPER_IMMEDIATE_ADVERSE_GUARD_PROFILE_BLOCKLIST",
        "SOLUSDTM:buy:TrendFollowingV2",
    )
    engine = _engine_with_spec("SOLUSDTM")

    plan = engine.build_order_plan(
        candidate=_candidate(
            symbol="SOLUSDTM",
            side="buy",
            strategy="TrendFollowingV2",
            expected_net_after_cost=0.0035,
            probability_of_profit=0.999,
        ),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is True
    assert plan.reason_code == "allow"
    assert "immediate_adverse_guard_type" not in plan.sizing_trace

def test_shadow_verified_guard_default_off_preserves_exact_rule(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.delenv("V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_ENABLE", raising=False)
    engine = _engine_with_spec("SOLUSDTM")

    plan = engine.build_order_plan(
        candidate=_candidate(
            symbol="SOLUSDTM",
            side="buy",
            strategy="TrendFollowingV2",
            expected_net_after_cost=0.0035,
            probability_of_profit=0.999,
        ),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is True
    assert plan.reason_code == "allow"
    assert "shadow_verified_guard_evaluated" not in plan.sizing_trace

def test_shadow_verified_guard_blocks_exact_rule_when_paper_enabled(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_ENABLE", "1")
    engine = _engine_with_spec("SOLUSDTM")

    plan = engine.build_order_plan(
        candidate=_candidate(
            symbol="SOLUSDTM",
            side="buy",
            strategy="TrendFollowingV2",
            expected_net_after_cost=0.0035,
            probability_of_profit=0.999,
        ),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is False
    assert plan.reason_code == "entry_shadow_verified_immediate_adverse_guard"
    assert plan.sizing_trace["shadow_verified_guard_evaluated"] is True
    assert plan.sizing_trace["shadow_verified_guard_allowed"] is False
    assert plan.sizing_trace["shadow_verified_guard_blocked"] is True
    assert (
        plan.sizing_trace["shadow_verified_guard_rule_id"]
        == "SOLUSDTM_buy_TrendFollowingV2_shadow_verified_20260606_000500"
    )
    assert (
        plan.sizing_trace["shadow_verified_guard_source_artifact"]
        == "analysis/immediate_adverse_shadow_verified_guard_candidates_long_shadow_current.json"
    )
    assert plan.sizing_trace["shadow_verified_guard_reason"] == "verified_rule_matched"
    assert plan.sizing_trace["shadow_verified_guard_symbol"] == "SOLUSDTM"
    assert plan.sizing_trace["shadow_verified_guard_side"] == "buy"
    assert plan.sizing_trace["shadow_verified_guard_strategy"] == "TrendFollowingV2"
    assert plan.sizing_trace["shadow_verified_guard_terminal_outcome_count"] == 18
    assert plan.sizing_trace["shadow_verified_guard_immediate_adverse_loss_count"] == 7
    assert plan.sizing_trace["shadow_verified_guard_missed_winner_count"] == 6
    assert plan.sizing_trace["shadow_verified_guard_missed_winner_rate"] == 0.3333333333333333
    assert plan.sizing_trace["shadow_verified_guard_expected_net_benefit"] == 0.08687323999998789
    assert plan.sizing_trace["shadow_verified_guard_avoided_loss_proxy_abs"] == 0.22447031999998474
    assert plan.sizing_trace["shadow_verified_guard_missed_winner_proxy_net"] == 0.13759707999999685

def test_shadow_verified_guard_live_ignores_enabled_flag(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_ENABLE", "1")
    engine = _engine_with_spec("SOLUSDTM")

    plan = engine.build_order_plan(
        candidate=_candidate(
            symbol="SOLUSDTM",
            side="buy",
            strategy="TrendFollowingV2",
            expected_net_after_cost=0.0035,
            probability_of_profit=0.999,
        ),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is True
    assert plan.reason_code == "allow"
    assert "shadow_verified_guard_evaluated" not in plan.sizing_trace

def test_shadow_verified_guard_allows_non_matching_profiles(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_ENABLE", "1")

    cases = [
        {"symbol": "SOLUSDTM", "side": "sell", "strategy": "TrendFollowingV2"},
        {"symbol": "BTCUSDTM", "side": "buy", "strategy": "TrendFollowingV2"},
        {"symbol": "SOLUSDTM", "side": "buy", "strategy": "MomentumV2"},
    ]
    for case in cases:
        engine = _engine_with_spec(case["symbol"])
        plan = engine.build_order_plan(
            candidate=_candidate(
                **case,
                expected_net_after_cost=0.0035,
                probability_of_profit=0.999,
            ),
            free_equity_usdt=1000.0,
            open_positions_count=0,
        )

        assert plan.accepted is True
        assert plan.reason_code == "allow"
        assert plan.sizing_trace["shadow_verified_guard_evaluated"] is True
        assert plan.sizing_trace["shadow_verified_guard_allowed"] is True
        assert plan.sizing_trace["shadow_verified_guard_blocked"] is False
        assert plan.sizing_trace["shadow_verified_guard_reason"] == "rule_not_matched"

def test_paper_diagnostic_can_bypass_entry_min_net_guard(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("DIAGNOSTIC_MODE", "1")
    monkeypatch.setenv("DIAG_DISABLE_ENTRY_MIN_NET_GUARD", "1")
    monkeypatch.setenv("ENTRY_MIN_NET_USDT", "0.05")
    engine = RiskEngineV2()
    engine.spec_resolver.get = lambda _symbol: ContractSpec(
        symbol="BTCUSDTM",
        multiplier=0.001,
        lot_size=1.0,
        min_size=1.0,
        max_size=None,
    )
    plan = engine.build_order_plan(
        candidate=_candidate(expected_net_after_cost=0.0002),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is True
    skip = plan.sizing_trace["diagnostic_gate_skips"][0]
    assert skip["gate_skipped"] is True
    assert skip["gate_name"] == "entry_min_net_guard"
    assert skip["skip_reason"] == "diagnostic_override"
    assert skip["entry_min_net_usdt"] == 0.05

def test_live_ignores_diagnostic_entry_min_net_bypass(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("DIAGNOSTIC_MODE", "1")
    monkeypatch.setenv("DIAG_DISABLE_ENTRY_MIN_NET_GUARD", "1")
    monkeypatch.setenv("ENTRY_MIN_NET_USDT", "0.05")
    engine = RiskEngineV2()
    engine.spec_resolver.get = lambda _symbol: ContractSpec(
        symbol="BTCUSDTM",
        multiplier=0.001,
        lot_size=1.0,
        min_size=1.0,
        max_size=None,
    )
    plan = engine.build_order_plan(
        candidate=_candidate(expected_net_after_cost=0.0002),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is False
    assert plan.reason_code == "entry_min_net_guard"
    assert "diagnostic_gate_skips" not in plan.sizing_trace

def test_build_order_plan_rejects_expected_net_below_stop_ratio(monkeypatch):
    monkeypatch.setenv("ENTRY_MIN_NET_TO_STOP_RATIO", "1.10")
    monkeypatch.setenv("V2_EXIT_USE_EXPECTED_NET_TARGETS", "1")
    monkeypatch.setenv("V2_EXIT_TP_EXPECTED_MULT", "0.90")
    monkeypatch.setenv("V2_EXIT_SL_EXPECTED_MULT", "0.60")
    monkeypatch.setenv("V2_EXIT_TP_MIN_USDT", "0.003")
    monkeypatch.setenv("V2_EXIT_SL_MIN_USDT", "0.020")
    engine = RiskEngineV2()
    engine.spec_resolver.get = lambda _symbol: ContractSpec(
        symbol="BTCUSDTM",
        multiplier=0.001,
        lot_size=1.0,
        min_size=1.0,
        max_size=None,
    )
    plan = engine.build_order_plan(
        candidate=_candidate(expected_net_after_cost=0.00025),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is False
    assert plan.reason_code == "entry_net_to_stop_guard"
    assert plan.sizing_trace["entry_net_to_stop_ratio"] < 1.10
    assert plan.sizing_trace["entry_min_net_to_stop_ratio"] == 1.10

def test_paper_diagnostic_can_bypass_entry_net_to_stop_guard(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("DIAGNOSTIC_MODE", "1")
    monkeypatch.setenv("DIAG_DISABLE_ENTRY_NET_TO_STOP_GUARD", "1")
    monkeypatch.setenv("ENTRY_MIN_NET_TO_STOP_RATIO", "1.10")
    monkeypatch.setenv("V2_EXIT_USE_EXPECTED_NET_TARGETS", "1")
    monkeypatch.setenv("V2_EXIT_TP_EXPECTED_MULT", "0.90")
    monkeypatch.setenv("V2_EXIT_SL_EXPECTED_MULT", "0.60")
    monkeypatch.setenv("V2_EXIT_TP_MIN_USDT", "0.003")
    monkeypatch.setenv("V2_EXIT_SL_MIN_USDT", "0.020")
    engine = RiskEngineV2()
    engine.spec_resolver.get = lambda _symbol: ContractSpec(
        symbol="BTCUSDTM",
        multiplier=0.001,
        lot_size=1.0,
        min_size=1.0,
        max_size=None,
    )
    plan = engine.build_order_plan(
        candidate=_candidate(expected_net_after_cost=0.00025),
        free_equity_usdt=1000.0,
        open_positions_count=0,
    )

    assert plan.accepted is True
    skip = plan.sizing_trace["diagnostic_gate_skips"][0]
    assert skip["gate_name"] == "entry_net_to_stop_guard"
    assert skip["entry_min_net_to_stop_ratio"] == 1.10
