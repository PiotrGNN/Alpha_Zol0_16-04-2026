from scripts.bucket_identity_normalization_audit import (
    _bucket_alias_kind,
    _canonical_bucket_key,
    _normalize_strategy_label,
)


def test_strategy_normalization_collapses_case_variants():
    assert _normalize_strategy_label("TrendFollowing") == "TRENDFOLLOWING"
    assert _normalize_strategy_label("TRENDFOLLOWING") == "TRENDFOLLOWING"
    assert _canonical_bucket_key("BTCUSDTM", "TrendFollowing", "buy") == "BTCUSDTM|TRENDFOLLOWING|buy"


def test_alias_kind_detects_case_only_fragmentation():
    raw = "BTCUSDTM|TrendFollowing|buy"
    canonical = "BTCUSDTM|TRENDFOLLOWING|buy"
    assert _bucket_alias_kind(raw, canonical, source="close_write") == "case_only_alias"


def test_alias_kind_detects_fallback_and_unknown_labels():
    assert _bucket_alias_kind("BTCUSDTM|__ALL__|buy", "BTCUSDTM|__ALL__|buy", source="gate_eval") == "fallback_alias"
    assert _bucket_alias_kind("BTCUSDTM|UNKNOWN|buy", "BTCUSDTM|UNKNOWN|buy", source="gate_eval") == "unknown_alias"


def test_alias_kind_marks_realized_axis():
    assert _bucket_alias_kind("side|buy", "side|buy", source="realized") == "realized_axis"
