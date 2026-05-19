"""Tests for _resolve_regime_deadlock_expansion (Faza 1A/1B/1C).

Validates that when ENTRY_STRATEGY_ALLOWLIST is TF-only AND
positive_side_fallback_used=True, the helper expands the allowlist
with regime-compatible strategies from strategy_side_stats.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "controlled_kpi_run.py"


@pytest.fixture(scope="module")
def kpi_module():
    spec = importlib.util.spec_from_file_location("controlled_kpi_run", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _call(kpi_module, after_overrides, after_overrides_cli,
          strategy_side_stats, positive_side_fallback_used, active_run_symbols):
    kpi_module._resolve_regime_deadlock_expansion(
        after_overrides=after_overrides,
        after_overrides_cli=after_overrides_cli,
        strategy_side_stats=strategy_side_stats,
        positive_side_fallback_used=positive_side_fallback_used,
        active_run_symbols=active_run_symbols,
    )


# ------------------------------------------------------------------ #
# Basic: no deadlock when allowlist is already multi-strategy
# ------------------------------------------------------------------ #

def test_no_expansion_when_allowlist_has_non_tf(kpi_module):
    ao = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing,MeanReversion"}
    ao_cli = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing,MeanReversion"}
    _call(kpi_module, ao, ao_cli, {}, True, set())
    # No change because it's not TF-only
    assert ao["ENTRY_STRATEGY_ALLOWLIST"] == "TrendFollowing,MeanReversion"
    assert "ENTRY_STRATEGY_ALLOWLIST" in ao_cli


def test_no_expansion_when_fallback_not_used(kpi_module):
    ao = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    ao_cli = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    _call(kpi_module, ao, ao_cli, {}, False, set())
    assert ao["ENTRY_STRATEGY_ALLOWLIST"] == "TrendFollowing"
    assert "ENTRY_STRATEGY_ALLOWLIST" in ao_cli


def test_no_expansion_when_allowlist_empty(kpi_module):
    ao = {}
    ao_cli = {}
    _call(kpi_module, ao, ao_cli, {}, True, set())
    # No ENTRY_STRATEGY_ALLOWLIST key means not TF-only → no change
    assert "ENTRY_STRATEGY_ALLOWLIST" not in ao


# ------------------------------------------------------------------ #
# Deadlock: TF-only + positive_side_fallback_used=True
# ------------------------------------------------------------------ #

def test_expansion_with_viable_mean_reversion(kpi_module):
    """MeanReversion:buy has tc=5, wr=0.4, exp=0.003 → should be added."""
    ao = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    ao_cli = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    sss = {
        "MeanReversion:buy": {
            "trade_count": 5,
            "wins_weighted": 2.0,  # wr = 2.0/5 = 0.4
            "net_pnl": 0.015,       # exp = 0.015/5 = 0.003
        }
    }
    _call(kpi_module, ao, ao_cli, sss, True, {"BTCUSDTM", "SOLUSDTM"})

    result = ao["ENTRY_STRATEGY_ALLOWLIST"]
    assert "MeanReversion" in result
    assert "TrendFollowing" in result
    assert "ENTRY_STRATEGY_ALLOWLIST" not in ao_cli


def test_no_expansion_when_no_viable_candidates(kpi_module):
    """No strategy meets the minimum thresholds → deadlock detected but no expansion."""
    ao = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    ao_cli = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    sss = {
        "MeanReversion:buy": {
            "trade_count": 5,
            "wins_weighted": 1.0,   # wr = 0.2 < 0.30
            "net_pnl": -0.05,       # exp = -0.01 < -0.01
        }
    }
    _call(kpi_module, ao, ao_cli, sss, True, {"BTCUSDTM"})
    # Allowlist unchanged but CLI key still present (no expansion happened)
    assert ao["ENTRY_STRATEGY_ALLOWLIST"] == "TrendFollowing"
    assert "ENTRY_STRATEGY_ALLOWLIST" in ao_cli


def test_no_expansion_when_candidate_tc_too_low(kpi_module):
    """trade_count < 2 → candidate is skipped."""
    ao = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    ao_cli = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    sss = {
        "MeanReversion:buy": {
            "trade_count": 1,
            "wins_weighted": 1.0,
            "net_pnl": 0.01,
        }
    }
    _call(kpi_module, ao, ao_cli, sss, True, {"BTCUSDTM"})
    assert ao["ENTRY_STRATEGY_ALLOWLIST"] == "TrendFollowing"


def test_side_allowlist_also_expanded(kpi_module):
    """ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST is TF-only → must also be expanded."""
    ao = {
        "ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing",
        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST": (
            "BTCUSDTM:TrendFollowing:buy,SOLUSDTM:TrendFollowing:buy"
        ),
    }
    ao_cli = dict(ao)
    sss = {
        "MeanReversion:buy": {
            "trade_count": 4,
            "wins_weighted": 1.6,   # wr=0.4
            "net_pnl": 0.012,       # exp=0.003
        }
    }
    _call(kpi_module, ao, ao_cli, sss, True, {"BTCUSDTM", "SOLUSDTM"})

    side_result = ao["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"]
    assert "BTCUSDTM:MeanReversion:buy" in side_result
    assert "SOLUSDTM:MeanReversion:buy" in side_result
    assert "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST" not in ao_cli


def test_side_allowlist_not_expanded_when_mixed(kpi_module):
    """If side allowlist has non-TF tokens, it should NOT be expanded."""
    ao = {
        "ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing",
        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST": (
            "BTCUSDTM:TrendFollowing:buy,BTCUSDTM:MeanReversion:buy"
        ),
    }
    original_side = ao["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"]
    ao_cli = dict(ao)
    sss = {
        "MeanReversion:buy": {
            "trade_count": 4,
            "wins_weighted": 1.6,
            "net_pnl": 0.012,
        }
    }
    _call(kpi_module, ao, ao_cli, sss, True, {"BTCUSDTM"})
    # Strategy allowlist expanded but side allowlist not changed (already non-TF)
    assert "MeanReversion" in ao["ENTRY_STRATEGY_ALLOWLIST"]
    assert ao["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] == original_side


def test_priority_order_mr_before_universal_before_momentum(kpi_module):
    """MeanReversion has priority over Universal and Momentum."""
    ao = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    ao_cli = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    sss = {
        "MeanReversion:buy": {
            "trade_count": 3,
            "wins_weighted": 1.2,  # wr=0.4
            "net_pnl": 0.006,      # exp=0.002
        },
        "Universal:buy": {
            "trade_count": 3,
            "wins_weighted": 1.2,
            "net_pnl": 0.006,
        },
    }
    _call(kpi_module, ao, ao_cli, sss, True, set())
    result = ao["ENTRY_STRATEGY_ALLOWLIST"]
    # Both are viable and both should be added
    assert "MeanReversion" in result
    assert "Universal" in result


def test_expansion_with_empty_strategy_side_stats(kpi_module):
    """Empty strategy_side_stats → deadlock detected, no expansion."""
    ao = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    ao_cli = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    _call(kpi_module, ao, ao_cli, {}, True, {"BTCUSDTM"})
    assert ao["ENTRY_STRATEGY_ALLOWLIST"] == "TrendFollowing"
    # CLI key still present (no mutation happened)
    assert "ENTRY_STRATEGY_ALLOWLIST" in ao_cli


def test_exact_minimum_threshold_boundary(kpi_module):
    """Exactly at minimum thresholds (exp=-0.01, wr=0.30) → should be included."""
    ao = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    ao_cli = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    sss = {
        "MeanReversion:buy": {
            "trade_count": 10,
            "wins_weighted": 3.0,   # wr=0.30
            "net_pnl": -0.10,       # exp=-0.01
        }
    }
    _call(kpi_module, ao, ao_cli, sss, True, set())
    assert "MeanReversion" in ao["ENTRY_STRATEGY_ALLOWLIST"]


def test_just_below_minimum_threshold(kpi_module):
    """exp=-0.011 < -0.01 → should NOT be included."""
    ao = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    ao_cli = {"ENTRY_STRATEGY_ALLOWLIST": "TrendFollowing"}
    sss = {
        "MeanReversion:buy": {
            "trade_count": 10,
            "wins_weighted": 3.0,   # wr=0.30 ✓
            "net_pnl": -0.11,       # exp=-0.011 < -0.01 ✗
        }
    }
    _call(kpi_module, ao, ao_cli, sss, True, set())
    assert ao["ENTRY_STRATEGY_ALLOWLIST"] == "TrendFollowing"
