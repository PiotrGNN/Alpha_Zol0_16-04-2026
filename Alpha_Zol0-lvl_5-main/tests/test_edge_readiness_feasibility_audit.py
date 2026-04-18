from scripts.edge_readiness_feasibility_audit import _bucket_is_realized_axis


def test_realized_axis_detection():
    assert _bucket_is_realized_axis("side|buy") is True
    assert _bucket_is_realized_axis("BTCUSDTM|TRENDFOLLOWING|buy") is False

