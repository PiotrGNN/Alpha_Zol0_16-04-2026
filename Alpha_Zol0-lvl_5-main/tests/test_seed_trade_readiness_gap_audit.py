from scripts.seed_trade_readiness_gap_audit import _classify


def test_classify_insufficient_close_writes():
    aggregate = {
        "total_close_writes": 0,
        "history_ready_any": False,
        "observed_trade_count_any": False,
        "bucket_count": 1,
    }
    assert _classify(aggregate) == "INSUFFICIENT_CLOSE_WRITES"


def test_classify_mixed_readiness_limits():
    aggregate = {
        "total_close_writes": 2,
        "history_ready_any": False,
        "observed_trade_count_any": True,
        "bucket_count": 2,
    }
    assert _classify(aggregate) == "MIXED_READINESS_LIMITS"


def test_classify_threshold_too_high_for_corridor():
    aggregate = {
        "total_close_writes": 1,
        "history_ready_any": False,
        "observed_trade_count_any": False,
        "bucket_count": 1,
    }
    assert _classify(aggregate) == "MIN_TRADES_THRESHOLD_TOO_HIGH_FOR_CORRIDOR"
