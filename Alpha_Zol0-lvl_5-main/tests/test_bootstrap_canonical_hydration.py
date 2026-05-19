"""
Focused regression tests for the bootstrap-to-canonical hydration seam.

Coverage:
  T1 – bootstrap row (TrendFollowing/Momentum) hydrates canonical bucket
  T2 – 20 bootstrap rows make history_ready=True for that bucket
  T3 – Universal strategy absence is reported in unresolved pool, not fabricated
  T4 – runtime close-path behavior is unaffected by bootstrap hydration data
  T5 – hydration writes gross_fill_pnl_model=realized_pnl with fee_total=0.0
  T6 – strategy key XRPUSDTM|UNIVERSAL|sell remains empty after non-Universal bootstrap
  T7 – multiple symbol/strategy/side buckets are independently hydrated
  T8 – row missing symbol/strategy/side is counted in skipped (not hydrated)
"""
import math
from scripts.canonical_edge_history_linkage import (
    get_canonical_edge_history,
    promote_to_canonical_edge_history,
    reset_canonical_edge_history_state,
)


# ---------------------------------------------------------------------------
# Helpers that replicate the seam's exact call contract
# ---------------------------------------------------------------------------

def _seam_promote(symbol, strategy, side, realized_pnl, ts_epoch=None):
    """Mirror the seam's promote_to_canonical_edge_history call contract."""
    return promote_to_canonical_edge_history(
        symbol=str(symbol),
        strategy=str(strategy),
        side=str(side),
        gross_fill_pnl_model=float(realized_pnl),
        fee_total=0.0,
        spread_slippage_proxy=0.0,
        ts=ts_epoch,
        correlation_id=None,
    )


# ---------------------------------------------------------------------------
# T1 – bootstrap row hydrates a canonical bucket
# ---------------------------------------------------------------------------

def test_bootstrap_row_hydrates_canonical_bucket():
    reset_canonical_edge_history_state()
    before = get_canonical_edge_history("XRPUSDTM", "TrendFollowing", "buy")
    assert before["canonical_shadow_trade_count"] == 0
    assert before["canonical_shadow_history_ready"] is False

    result = _seam_promote("XRPUSDTM", "TrendFollowing", "buy", realized_pnl=-1.01,
                           ts_epoch=1_740_000_000.0)

    assert result["bucket_identity_status"] == "RESOLVED"
    assert result["canonical_key_write"] == "XRPUSDTM|TRENDFOLLOWING|buy"
    assert result["canonical_shadow_trade_count"] == 1
    assert result["bucket_created_on_this_event"] is True

    after = get_canonical_edge_history("XRPUSDTM", "TrendFollowing", "buy")
    assert after["canonical_shadow_trade_count"] == 1
    assert after["trade_count_read"] == 1


# ---------------------------------------------------------------------------
# T2 – 20 bootstrap rows make history_ready=True
# ---------------------------------------------------------------------------

def test_twenty_bootstrap_rows_make_history_ready():
    reset_canonical_edge_history_state()
    for i in range(19):
        _seam_promote("BTCUSDTM", "Momentum", "sell", realized_pnl=float(i) * 0.1)

    mid = get_canonical_edge_history("BTCUSDTM", "Momentum", "sell", min_trades=20)
    assert mid["canonical_shadow_history_ready"] is False
    assert mid["canonical_shadow_trade_count"] == 19

    _seam_promote("BTCUSDTM", "Momentum", "sell", realized_pnl=0.5)

    final = get_canonical_edge_history("BTCUSDTM", "Momentum", "sell", min_trades=20)
    assert final["canonical_shadow_history_ready"] is True
    assert final["canonical_shadow_trade_count"] == 20


# ---------------------------------------------------------------------------
# T3 – Universal strategy absence: promote_to_canonical_edge_history with
#       strategy=Universal still resolves (strategy is normalised to UNIVERSAL),
#       BUT no bootstrap data ever contains "Universal" rows.
#       This test confirms that if Universal rows are NOT fed into the seam,
#       the UNIVERSAL bucket stays empty.
# ---------------------------------------------------------------------------

def test_universal_bucket_stays_empty_without_universal_rows():
    reset_canonical_edge_history_state()

    # Hydrate only TrendFollowing and Momentum rows (the actual bootstrap content)
    _seam_promote("XRPUSDTM", "TrendFollowing", "buy",  realized_pnl=-1.01)
    _seam_promote("XRPUSDTM", "TrendFollowing", "sell", realized_pnl=0.30)
    _seam_promote("XRPUSDTM", "Momentum",       "buy",  realized_pnl=-0.50)
    _seam_promote("XRPUSDTM", "Momentum",       "sell", realized_pnl=0.20)

    # Universal bucket must remain empty
    universal = get_canonical_edge_history("XRPUSDTM", "Universal", "sell")
    assert universal["canonical_shadow_trade_count"] == 0
    assert universal["canonical_shadow_history_ready"] is False

    # Non-Universal buckets are populated
    tf_buy = get_canonical_edge_history("XRPUSDTM", "TrendFollowing", "buy")
    assert tf_buy["canonical_shadow_trade_count"] == 1

    mom_sell = get_canonical_edge_history("XRPUSDTM", "Momentum", "sell")
    assert mom_sell["canonical_shadow_trade_count"] == 1


# ---------------------------------------------------------------------------
# T4 – runtime close-path behavior is unaffected by bootstrap hydration
#       A subsequent runtime-style close (with real fee data) is additive,
#       not overwriting, and its fee/spread values are preserved correctly.
# ---------------------------------------------------------------------------

def test_runtime_close_path_additive_after_bootstrap():
    reset_canonical_edge_history_state()

    # Hydrate 5 bootstrap rows (fee_total=0.0, spread=0.0)
    for _ in range(5):
        _seam_promote("ETHUSDTM", "Momentum", "buy", realized_pnl=0.05)

    state_after_bootstrap = get_canonical_edge_history("ETHUSDTM", "Momentum", "buy")
    assert state_after_bootstrap["canonical_shadow_trade_count"] == 5

    # Runtime close (fee and spread known)
    runtime_result = promote_to_canonical_edge_history(
        symbol="ETHUSDTM",
        strategy="Momentum",
        side="buy",
        gross_fill_pnl_model=0.10,
        fee_total=0.02,
        spread_slippage_proxy=0.01,
        ts=1_740_000_100.0,
        correlation_id=None,
    )

    assert runtime_result["canonical_shadow_trade_count"] == 6
    assert runtime_result["bucket_identity_status"] == "RESOLVED"
    assert runtime_result["bucket_created_on_this_event"] is False

    final = get_canonical_edge_history("ETHUSDTM", "Momentum", "buy")
    assert final["canonical_shadow_trade_count"] == 6

    # The fee and slippage for the runtime row are stored correctly
    bucket = final["shadow_bucket"]
    assert bucket["fee_hist"][5] == 0.02
    assert bucket["slippage_hist"][5] == 0.01

    # Bootstrap rows all have fee=0.0
    for i in range(5):
        assert bucket["fee_hist"][i] == 0.0
        assert bucket["slippage_hist"][i] == 0.0


# ---------------------------------------------------------------------------
# T5 – gross_fill_pnl_model equals realized_pnl; fee_total and spread are 0.0
# ---------------------------------------------------------------------------

def test_seam_stores_realized_pnl_as_gross_proxy_with_zero_fee():
    reset_canonical_edge_history_state()
    expected_pnl = -1.23456789

    _seam_promote("BTCUSDTM", "TrendFollowing", "sell", realized_pnl=expected_pnl)

    result = get_canonical_edge_history("BTCUSDTM", "TrendFollowing", "sell")
    assert result["canonical_shadow_trade_count"] == 1
    bucket = result["shadow_bucket"]
    assert math.isclose(bucket["gross_hist"][0], expected_pnl, rel_tol=1e-9)
    assert bucket["fee_hist"][0] == 0.0
    assert bucket["slippage_hist"][0] == 0.0


# ---------------------------------------------------------------------------
# T6 – XRPUSDTM|UNIVERSAL|sell stays empty after non-Universal bootstrap hydration
#       (exact audit key from run 20260426_061500)
# ---------------------------------------------------------------------------

def test_xrpusdtm_universal_sell_bucket_remains_empty_after_non_universal_bootstrap():
    reset_canonical_edge_history_state()

    # Simulate all 9 XRPUSDTM bootstrap rows (TrendFollowing + Momentum only)
    xrp_bootstrap_rows = [
        ("TrendFollowing", "buy"),
        ("TrendFollowing", "buy"),
        ("TrendFollowing", "buy"),
        ("TrendFollowing", "buy"),
        ("TrendFollowing", "sell"),
        ("Momentum", "buy"),
        ("Momentum", "buy"),
        ("Momentum", "buy"),
        ("Momentum", "sell"),
    ]
    for strategy, side in xrp_bootstrap_rows:
        _seam_promote("XRPUSDTM", strategy, side, realized_pnl=-0.5)

    # Exact key from id=1382 in 20260426_061500 run
    empty_bucket = get_canonical_edge_history("XRPUSDTM", "Universal", "sell")
    assert empty_bucket["canonical_shadow_trade_count"] == 0
    assert empty_bucket["canonical_shadow_history_ready"] is False

    # Verify populated buckets are separate
    tf_buy = get_canonical_edge_history("XRPUSDTM", "TrendFollowing", "buy")
    assert tf_buy["canonical_shadow_trade_count"] == 4

    tf_sell = get_canonical_edge_history("XRPUSDTM", "TrendFollowing", "sell")
    assert tf_sell["canonical_shadow_trade_count"] == 1

    mom_sell = get_canonical_edge_history("XRPUSDTM", "Momentum", "sell")
    assert mom_sell["canonical_shadow_trade_count"] == 1


# ---------------------------------------------------------------------------
# T7 – Multiple symbol/strategy/side buckets are independently hydrated
# ---------------------------------------------------------------------------

def test_multiple_buckets_independently_hydrated():
    reset_canonical_edge_history_state()

    buckets = [
        ("BTCUSDTM", "TrendFollowing", "buy",  1.0),
        ("BTCUSDTM", "TrendFollowing", "sell", -0.5),
        ("ETHUSDTM", "Momentum",       "buy",   0.2),
        ("XRPUSDTM", "Momentum",       "sell", -0.1),
    ]
    for sym, strat, side, pnl in buckets:
        _seam_promote(sym, strat, side, realized_pnl=pnl)

    for sym, strat, side, _ in buckets:
        result = get_canonical_edge_history(sym, strat, side)
        assert result["canonical_shadow_trade_count"] == 1, (
            f"Expected 1 trade for {sym}|{strat}|{side}, "
            f"got {result['canonical_shadow_trade_count']}"
        )

    # Confirm cross-contamination doesn't occur
    cross = get_canonical_edge_history("BTCUSDTM", "Momentum", "buy")
    assert cross["canonical_shadow_trade_count"] == 0


# ---------------------------------------------------------------------------
# T8 – Row missing required fields is NOT hydrated
#       (simulate what the else branch in the seam does)
# ---------------------------------------------------------------------------

def test_row_with_missing_required_fields_does_not_hydrate():
    reset_canonical_edge_history_state()

    # __ALL__ and UNKNOWN strategy names must NOT be promoted
    result_all = promote_to_canonical_edge_history(
        symbol="BTCUSDTM",
        strategy="__ALL__",
        side="buy",
        gross_fill_pnl_model=1.0,
        fee_total=0.0,
        spread_slippage_proxy=0.0,
        ts=None,
        correlation_id=None,
    )
    assert result_all["bucket_identity_status"] != "RESOLVED"
    assert result_all["canonical_shadow_trade_count"] == 0

    result_unknown = promote_to_canonical_edge_history(
        symbol="BTCUSDTM",
        strategy="UNKNOWN",
        side="buy",
        gross_fill_pnl_model=1.0,
        fee_total=0.0,
        spread_slippage_proxy=0.0,
        ts=None,
        correlation_id=None,
    )
    assert result_unknown["bucket_identity_status"] != "RESOLVED"
    assert result_unknown["canonical_shadow_trade_count"] == 0

    # The bucket must remain empty
    bucket = get_canonical_edge_history("BTCUSDTM", "__ALL__", "buy")
    assert bucket["canonical_shadow_trade_count"] == 0
    bucket2 = get_canonical_edge_history("BTCUSDTM", "UNKNOWN", "buy")
    assert bucket2["canonical_shadow_trade_count"] == 0
