from scripts.canonical_bucket_identity import build_canonical_bucket_key, resolve_strategy_identity


def test_resolve_strategy_identity_from_evaluated_payload():
    payload = {"entry_edge_over_fee": {"strategy": "TrendFollowing"}, "symbol": "BTCUSDTM", "side": "buy"}
    strategy, status, reason = resolve_strategy_identity(payload)
    assert strategy == "TRENDFOLLOWING"
    assert status == "RESOLVED"
    assert reason == "explicit_strategy"


def test_build_canonical_bucket_key_from_close_payload():
    payload = {
        "symbol": "BTCUSDTM",
        "side": "buy",
        "position": {"entry_main_strategy": "TrendFollowing"},
    }
    canonical = build_canonical_bucket_key(payload)
    assert canonical["canonical_bucket_key"] == "BTCUSDTM|TRENDFOLLOWING|buy"
    assert canonical["bucket_identity_status"] == "RESOLVED"
