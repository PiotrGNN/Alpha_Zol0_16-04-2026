from core.runtime_v2.contracts import EntryCandidate, FeatureFrame, QuoteTick
from core.runtime_v2.post_signal_trajectory import PostSignalTrajectoryTracker


def _quote(symbol: str = "BTCUSDTM", ts_ms: int = 1000, mid: float = 100.0) -> QuoteTick:
    return QuoteTick(
        symbol=symbol,
        ts_ms=ts_ms,
        bid=mid - 0.05,
        ask=mid + 0.05,
        mid=mid,
        spread_abs=0.1,
        spread_bps=(0.1 / mid) * 10000.0,
        best_bid_size=10.0,
        best_ask_size=10.0,
        raw={},
    )


def _feature(source: str = "rolling_quote_window") -> FeatureFrame:
    return FeatureFrame(
        symbol="BTCUSDTM",
        ts_ms=1000,
        mid=100.0,
        ret_1=0.001,
        ret_3=0.002,
        volatility=0.0005,
        spread_bps=5.0,
        has_profile=True,
        sample_count=64,
        profile_source=source,
        profile_age_sec=30.0,
        profile_span_sec=300.0,
    )


def _candidate(
    *,
    side: str = "buy",
    strategy: str = "MomentumV2",
    source: str = "rolling_quote_window",
) -> EntryCandidate:
    quote = _quote()
    return EntryCandidate(
        symbol="BTCUSDTM",
        side=side,
        strategy=strategy,
        score=0.8,
        confidence=0.7,
        expected_move=0.002,
        expected_edge_after_fee=0.0018,
        expected_net_after_cost=0.0016,
        probability_of_profit=0.55,
        quote=quote,
        feature=_feature(source),
        reason_code="candidate_signal",
        cost_breakdown={
            "runtime_profile_source": source,
            "runtime_profile_key": f"BTCUSDTM|{source}|n=64|span=300",
            "runtime_profile_age_sec": 30.0,
            "runtime_profile_span_sec": 300.0,
            "runtime_profile_sample_size": 64,
            "fee_round_trip_ratio": 0.0002,
            "spread_ratio": 0.0001,
            "slippage_ratio": 0.0001,
            "total_cost_ratio": 0.0004,
        },
        signal_metadata={"signal_horizon_ticks": 3},
    )


def test_tracker_captures_only_rolling_quote_window_candidates():
    tracker = PostSignalTrajectoryTracker(horizons=(1,))
    tracker.observe_candidates(
        symbol="BTCUSDTM",
        candidates=[
            _candidate(strategy="MomentumV2"),
            _candidate(strategy="MeanReversionV2", source="kucoin_public_futures_klines"),
        ],
        reason_code="entry_min_net_guard",
    )

    events = tracker.observe_quote(_quote(ts_ms=2000, mid=101.0))

    assert len(events) == 1
    assert events[0]["strategy"] == "MomentumV2"
    assert events[0]["source"] == "rolling_quote_window"
    assert events[0]["runtime_profile_key"] == "BTCUSDTM|rolling_quote_window|n=64|span=300"


def test_tracker_computes_buy_and_sell_signed_net_moves():
    tracker = PostSignalTrajectoryTracker(horizons=(1,))
    tracker.observe_candidates(
        symbol="BTCUSDTM",
        candidates=[
            _candidate(side="buy", strategy="MomentumV2"),
            _candidate(side="sell", strategy="MeanReversionV2"),
        ],
        reason_code="allow",
    )

    events = tracker.observe_quote(_quote(ts_ms=2000, mid=101.0))
    by_side = {event["side"]: event for event in events}

    assert by_side["buy"]["signed_gross_move"] == 0.01
    assert by_side["buy"]["signed_net_move"] == 0.0096
    assert by_side["sell"]["signed_gross_move"] == -0.01
    assert by_side["sell"]["signed_net_move"] == -0.0104


def test_tracker_emits_only_after_configured_horizons():
    tracker = PostSignalTrajectoryTracker(horizons=(2,))
    tracker.observe_candidates(
        symbol="BTCUSDTM",
        candidates=[_candidate(strategy="MomentumV2")],
        reason_code="allow",
    )

    assert tracker.observe_quote(_quote(ts_ms=2000, mid=100.5)) == []
    events = tracker.observe_quote(_quote(ts_ms=3000, mid=101.0))

    assert len(events) == 1
    assert events[0]["horizon_ticks"] == 2


def test_tracker_does_not_emit_contaminated_evidence():
    tracker = PostSignalTrajectoryTracker(horizons=(1,))
    tracker.observe_candidates(
        symbol="BTCUSDTM",
        candidates=[_candidate(strategy="MomentumV2")],
        reason_code="allow",
        contamination_flags={"fallback": 1},
    )

    assert tracker.observe_quote(_quote(ts_ms=2000, mid=101.0)) == []
