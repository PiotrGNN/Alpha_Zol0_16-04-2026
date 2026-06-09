from datetime import datetime, timezone

from paid_beta.trading_metrics import assess_trading_metrics


def test_missing_scorecard_is_fail_closed():
    result = assess_trading_metrics(None)
    assert result["profitability_ready"] is False
    assert result["live_ready"] is False
    assert result["blockers"] == ["FRESH_SCORECARD_MISSING"]


def test_complete_synthetic_scorecard_never_enables_live():
    scorecard = {
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

    result = assess_trading_metrics(scorecard)

    assert result["profitability_ready"] is True
    assert result["blockers"] == []
    assert result["live_ready"] is False
