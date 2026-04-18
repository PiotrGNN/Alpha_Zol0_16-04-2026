from scripts.readiness_architecture_mismatch_audit import _canonical_bucket


def test_canonical_bucket_uppercases_strategy():
    assert _canonical_bucket("BTCUSDTM", "TrendFollowing", "buy") == "BTCUSDTM|TRENDFOLLOWING|buy"

