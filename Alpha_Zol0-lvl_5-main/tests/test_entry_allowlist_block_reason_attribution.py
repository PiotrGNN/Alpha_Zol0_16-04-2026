"""
Tests for the allowlist block attribution split introduced by the
diagnostic-safe telemetry patch.

Two new attribution classes:
  - symbol_strategy_side_allowlist_unresolved_identity
      candidate_key is None (strategy/side could not be resolved)
  - symbol_strategy_side_allowlist_resolved_not_allowed
      candidate_key is fully formed but absent from the allowlist

Backward-compat contract: decision["reason"] stays "symbol_strategy_side_allowlist"
in both cases so existing callers are unaffected.  The fine-grained split is
exposed via decision["attribution_reason"] and decision["attribution_fields"].
"""
import core.BotCore as botcore

XRP_SELL_ALLOWLIST = {
    "XRPUSDTM:MOMENTUM:sell",
    "XRPUSDTM:TRENDFOLLOWING:sell",
}


# ──────────────────────────────────────────────────────────
# 1. Unresolved-identity class
# ──────────────────────────────────────────────────────────

def test_unresolved_identity_when_strategy_is_none():
    """Missing strategy → candidate_key is None → unresolved_identity."""
    decision = botcore._entry_symbol_strategy_side_allowlist_gate(
        symbol="XRPUSDTM",
        strategy=None,
        side="sell",
        allowlist=XRP_SELL_ALLOWLIST,
        live_mode=False,
    )
    assert decision["allowed"] is False
    assert decision["reason"] == "symbol_strategy_side_allowlist", (
        "backward-compat reason must stay unchanged"
    )
    assert decision["attribution_reason"] == (
        "symbol_strategy_side_allowlist_unresolved_identity"
    )
    af = decision["attribution_fields"]
    assert af["candidate_key"] is None
    assert af["missing_strategy_field"] is True
    assert af["allowlist_match_attempted"] is False


def test_unresolved_identity_when_strategy_empty_string():
    decision = botcore._entry_symbol_strategy_side_allowlist_gate(
        symbol="XRPUSDTM",
        strategy="",
        side="sell",
        allowlist=XRP_SELL_ALLOWLIST,
        live_mode=False,
    )
    assert decision["allowed"] is False
    assert decision["attribution_reason"] == (
        "symbol_strategy_side_allowlist_unresolved_identity"
    )
    assert decision["attribution_fields"]["allowlist_match_attempted"] is False


def test_unresolved_identity_when_side_is_none():
    """Missing side → candidate_key is None → unresolved_identity."""
    decision = botcore._entry_symbol_strategy_side_allowlist_gate(
        symbol="XRPUSDTM",
        strategy="MOMENTUM",
        side=None,
        allowlist=XRP_SELL_ALLOWLIST,
        live_mode=False,
    )
    assert decision["allowed"] is False
    assert decision["attribution_reason"] == (
        "symbol_strategy_side_allowlist_unresolved_identity"
    )


def test_unresolved_identity_when_side_is_hold():
    """'hold' is not a valid side value → candidate_key is None."""
    decision = botcore._entry_symbol_strategy_side_allowlist_gate(
        symbol="XRPUSDTM",
        strategy="MOMENTUM",
        side="hold",
        allowlist=XRP_SELL_ALLOWLIST,
        live_mode=False,
    )
    assert decision["allowed"] is False
    assert decision["attribution_reason"] == (
        "symbol_strategy_side_allowlist_unresolved_identity"
    )


def test_unresolved_identity_attribution_fields_shape():
    decision = botcore._entry_symbol_strategy_side_allowlist_gate(
        symbol="BTCUSDTM",
        strategy=None,
        side="buy",
        allowlist=XRP_SELL_ALLOWLIST,
        live_mode=False,
    )
    af = decision["attribution_fields"]
    assert "symbol" in af
    assert "side" in af
    assert "raw_strategy" in af
    assert "candidate_key" in af
    assert "missing_strategy_field" in af
    assert "allowlist_match_attempted" in af


# ──────────────────────────────────────────────────────────
# 2. Resolved-but-not-allowlisted class
# ──────────────────────────────────────────────────────────

def test_resolved_not_allowed_for_foreign_symbol():
    """Fully resolved key for a symbol not in allowlist."""
    decision = botcore._entry_symbol_strategy_side_allowlist_gate(
        symbol="ETHUSDTM",
        strategy="Momentum",
        side="buy",
        allowlist=XRP_SELL_ALLOWLIST,
        live_mode=False,
    )
    assert decision["allowed"] is False
    assert decision["reason"] == "symbol_strategy_side_allowlist", (
        "backward-compat reason must stay unchanged"
    )
    assert decision["attribution_reason"] == (
        "symbol_strategy_side_allowlist_resolved_not_allowed"
    )
    af = decision["attribution_fields"]
    assert af["candidate_key"] == "ETHUSDTM:MOMENTUM:buy"
    assert af["allowlist_match_attempted"] is True
    assert af["allowlist_match"] is False


def test_resolved_not_allowed_for_wrong_side():
    """XRP+Momentum but buy (not sell) → resolved, not allowed."""
    decision = botcore._entry_symbol_strategy_side_allowlist_gate(
        symbol="XRPUSDTM",
        strategy="Momentum",
        side="buy",
        allowlist=XRP_SELL_ALLOWLIST,
        live_mode=False,
    )
    assert decision["allowed"] is False
    assert decision["attribution_reason"] == (
        "symbol_strategy_side_allowlist_resolved_not_allowed"
    )
    af = decision["attribution_fields"]
    assert af["candidate_key"] == "XRPUSDTM:MOMENTUM:buy"
    assert af["allowlist_match"] is False


def test_resolved_not_allowed_attribution_fields_shape():
    decision = botcore._entry_symbol_strategy_side_allowlist_gate(
        symbol="BTCUSDTM",
        strategy="TrendFollowing",
        side="sell",
        allowlist=XRP_SELL_ALLOWLIST,
        live_mode=False,
    )
    af = decision["attribution_fields"]
    assert "symbol" in af
    assert "side" in af
    assert "strategy_identity" in af
    assert "candidate_key" in af
    assert "effective_allowlist" in af
    assert "allowlist_match_attempted" in af
    assert "allowlist_match" in af
    assert isinstance(af["effective_allowlist"], list)


# ──────────────────────────────────────────────────────────
# 3. Allowlisted candidates are still admitted
# ──────────────────────────────────────────────────────────

def test_allowlisted_xrp_momentum_sell_is_admitted():
    decision = botcore._entry_symbol_strategy_side_allowlist_gate(
        symbol="XRPUSDTM",
        strategy="Momentum",
        side="sell",
        allowlist=XRP_SELL_ALLOWLIST,
        live_mode=False,
    )
    assert decision["allowed"] is True
    assert decision["reason"] is None
    assert "attribution_reason" not in decision


def test_allowlisted_xrp_trendfollowing_sell_is_admitted():
    decision = botcore._entry_symbol_strategy_side_allowlist_gate(
        symbol="XRPUSDTM",
        strategy="TrendFollowing",
        side="sell",
        allowlist=XRP_SELL_ALLOWLIST,
        live_mode=False,
    )
    assert decision["allowed"] is True
    assert decision["reason"] is None
    assert "attribution_reason" not in decision


# ──────────────────────────────────────────────────────────
# 4. No allowlist → gate inactive, nothing blocked
# ──────────────────────────────────────────────────────────

def test_no_allowlist_gate_is_inactive():
    decision = botcore._entry_symbol_strategy_side_allowlist_gate(
        symbol="XRPUSDTM",
        strategy="Momentum",
        side="sell",
        allowlist=[],
        live_mode=False,
    )
    assert decision["active"] is False
    assert decision["allowed"] is True
    assert decision["reason"] is None
    assert "attribution_reason" not in decision


# ──────────────────────────────────────────────────────────
# 5. _classify_entry_reason recognises both new codes
# ──────────────────────────────────────────────────────────

def test_classify_entry_reason_unresolved_identity():
    result = botcore._classify_entry_reason(
        "symbol_strategy_side_allowlist_unresolved_identity"
    )
    # Both new sub-classes fall in the same risk_block bucket as the parent
    # "symbol_strategy_side_allowlist" reason.
    assert result == "risk_block"


def test_classify_entry_reason_resolved_not_allowed():
    result = botcore._classify_entry_reason(
        "symbol_strategy_side_allowlist_resolved_not_allowed"
    )
    assert result == "risk_block"
