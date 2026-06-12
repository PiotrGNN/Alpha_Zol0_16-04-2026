from datetime import datetime, timedelta, timezone

from paid_beta.trading_metrics import assess_trading_metrics


def _passing_scorecard():
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": {
                "exchange": "KuCoin",
                "mode": "PAPER_ONLY",
                "live_in_scope": False,
            },
            "validation": {"all_passed": True},
        },
        "global_kpis": {
            "strategy_validation_contract": {
                "usable_strategy_economics": True,
                "natural_entry_trade_count": 60,
                "assisted_entry_trade_count": 0,
                "unknown_entry_trade_count": 0,
            },
            "natural_entry_metrics": {"expectancy": 0.01},
            "profitable_run_rate": 0.75,
            "pf_gt_1_rate": 0.75,
        },
        "out_of_sample": {"profit_factor": 1.20},
        "positive_selected_cohorts_share": 0.80,
        "never_green_share": 0.10,
        "weekly_windows": [
            {"net_pnl": 1.0},
            {"net_pnl": 2.0},
            {"net_pnl": 3.0},
            {"net_pnl": 4.0},
        ],
    }


def test_missing_scorecard_is_fail_closed():
    result = assess_trading_metrics(None)
    assert result["profitability_ready"] is False
    assert result["live_ready"] is False
    assert result["blockers"] == ["FRESH_SCORECARD_MISSING"]


def test_complete_synthetic_scorecard_never_enables_live():
    result = assess_trading_metrics(_passing_scorecard())

    assert result["profitability_ready"] is True
    assert result["blockers"] == []
    assert result["live_ready"] is False


def test_contaminated_entry_counts_fail_profitability_gate():
    scorecard = _passing_scorecard()
    contract = scorecard["global_kpis"]["strategy_validation_contract"]
    contract.update(
        {
            "mock_entry_trade_count": 1,
            "forced_entry_trade_count": 1,
            "fallback_entry_trade_count": 1,
            "seed_entry_trade_count": 1,
        }
    )

    result = assess_trading_metrics(scorecard)

    assert result["profitability_ready"] is False
    assert "MOCK_TRADES_PRESENT" in result["blockers"]
    assert "FORCED_TRADES_PRESENT" in result["blockers"]
    assert "FALLBACK_TRADES_PRESENT" in result["blockers"]
    assert "SEED_TRADES_PRESENT" in result["blockers"]


def test_truth_classification_counts_are_authoritative_for_contamination():
    scorecard = _passing_scorecard()
    contract = scorecard["global_kpis"]["strategy_validation_contract"]
    contract["truth_classification_counts"] = {
        "NATURAL_STRATEGY_ENTRY": 60,
        "PAPER_AUTO_OPEN_FALLBACK": 1,
        "BOOTSTRAP_ALLOWLIST_ASSISTED": 1,
        "SEED_TRADES_OVERRIDE_ASSISTED": 1,
        "UNKNOWN_REQUIRES_REVIEW": 1,
    }

    result = assess_trading_metrics(scorecard)

    assert result["profitability_ready"] is False
    assert "FALLBACK_TRADES_PRESENT" in result["blockers"]
    assert "ASSISTED_TRADES_PRESENT" in result["blockers"]
    assert "SEED_TRADES_PRESENT" in result["blockers"]
    assert "UNKNOWN_TRADES_PRESENT" in result["blockers"]


def test_stale_scorecard_is_not_profitability_ready():
    scorecard = _passing_scorecard()
    scorecard["metadata"]["generated_at"] = (
        datetime.now(timezone.utc) - timedelta(days=8)
    ).isoformat()

    result = assess_trading_metrics(scorecard)

    assert result["profitability_ready"] is False
    assert "SCORECARD_STALE" in result["blockers"]
