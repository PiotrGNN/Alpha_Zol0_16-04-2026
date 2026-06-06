from core.runtime_v2.contracts import FeatureFrame, QuoteTick, StrategySignal
from core.runtime_v2.decision_engine import DecisionEngineV2


def _quote() -> QuoteTick:
    return QuoteTick(
        symbol="BTCUSDTM",
        ts_ms=1,
        bid=100.0,
        ask=100.1,
        mid=100.05,
        spread_abs=0.1,
        spread_bps=(0.1 / 100.05) * 10000.0,
        best_bid_size=10.0,
        best_ask_size=10.0,
        raw={},
    )


def _feature(*, sample_count: int, age_sec: float, span_sec: float) -> FeatureFrame:
    return FeatureFrame(
        symbol="BTCUSDTM",
        ts_ms=1,
        mid=100.05,
        ret_1=0.0015,
        ret_3=0.0020,
        volatility=0.0007,
        spread_bps=10.0,
        has_profile=True,
        sample_count=sample_count,
        profile_source="rolling_quote_window",
        profile_age_sec=age_sec,
        profile_span_sec=span_sec,
    )


def _signal(
    strategy: str = "TrendFollowingV2",
    side: str = "buy",
    expected_move: float = 0.002,
) -> StrategySignal:
    return StrategySignal(
        strategy=strategy,
        direction=side,
        score=0.25,
        confidence=0.8,
        expected_move=expected_move,
        reason_code="trendfollowing_signal",
        metadata={"signal_horizon_ticks": 3},
    )


def test_admission_reachability_profile_default_off_preserves_min_expected_net(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.delenv("V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE", raising=False)
    monkeypatch.setenv("V2_MIN_EXPECTED_NET_RATIO", "0.0006")
    engine = DecisionEngineV2()

    candidates, best, reason = engine.evaluate(
        quote=_quote(),
        feature=_feature(sample_count=24, age_sec=120.0, span_sec=60.0),
        signals=[_signal()],
    )

    assert len(candidates) == 1
    assert best is not None
    assert reason == "allow"


def test_admission_reachability_profile_relaxes_min_expected_net(monkeypatch):
    monkeypatch.setenv("LIVE", "0")
    monkeypatch.setenv("V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE", "1")
    monkeypatch.setenv("V2_MIN_EXPECTED_NET_RATIO", "0.0006")
    engine = DecisionEngineV2()

    candidates, best, reason = engine.evaluate(
        quote=_quote(),
        feature=_feature(sample_count=24, age_sec=120.0, span_sec=60.0),
        signals=[_signal(expected_move=0.00038)],
    )

    assert len(candidates) == 1
    assert candidates[0].expected_net_after_cost < 0.0006
    assert best is not None
    assert reason == "allow"
    assert engine.min_expected_net_ratio == 0.00002


def test_admission_reachability_profile_live_ignores_min_expected_net(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE", "1")
    monkeypatch.setenv("V2_MIN_EXPECTED_NET_RATIO", "0.0006")
    engine = DecisionEngineV2()

    candidates, best, reason = engine.evaluate(
        quote=_quote(),
        feature=_feature(sample_count=24, age_sec=120.0, span_sec=60.0),
        signals=[_signal(expected_move=0.00038)],
    )

    assert len(candidates) == 1
    assert best is None
    assert reason == "entry_edge_filtered"
    assert engine.min_expected_net_ratio == 0.0006
