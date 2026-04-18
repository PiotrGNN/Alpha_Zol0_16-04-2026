from scripts.long_corridor_readiness_unlock import _canonical_bucket


def test_canonical_bucket_shape():
    assert _canonical_bucket("BTCUSDTM", "TrendFollowing", "buy") == "BTCUSDTM|TRENDFOLLOWING|buy"
    assert _canonical_bucket("BTCUSDTM", "TRENDFOLLOWING", "buy") == "BTCUSDTM|TRENDFOLLOWING|buy"
