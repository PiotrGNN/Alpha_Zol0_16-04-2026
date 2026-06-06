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
