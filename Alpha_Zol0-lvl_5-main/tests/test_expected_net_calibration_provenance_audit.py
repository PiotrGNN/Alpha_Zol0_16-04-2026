
import json
import sqlite3

from scripts.expected_net_calibration_provenance_audit import (
    classify_admission_provenance,
    compute_calibration_stats,
    load_clean_lower_bucket_trades,
    profit_factor,
)


def test_classify_admission_provenance_legacy_when_current_min_net_missing():
    trade = {
        "expected_net_after_full_cost": 0.05,
        "effective_entry_min_net_usdt": None,
        "min_net_guard_enabled": None,
        "diagnostic_or_assisted": False,
        "entry_reason": "decision_passed",
    }
    assert classify_admission_provenance(trade, current_threshold=0.12) == "OPENED_UNDER_LEGACY_THRESHOLD"


def test_classify_admission_provenance_gap_when_enabled_current_guard_would_block():
    trade = {
        "expected_net_after_full_cost": 0.05,
        "effective_entry_min_net_usdt": 0.12,
        "min_net_guard_enabled": True,
        "diagnostic_or_assisted": False,
        "entry_reason": "decision_passed",
    }
    assert classify_admission_provenance(trade, current_threshold=0.12) == "OPENED_DUE_TO_GATE_ENFORCEMENT_GAP"


def test_classify_admission_provenance_disabled_guard():
    trade = {
        "expected_net_after_full_cost": 0.05,
        "effective_entry_min_net_usdt": 0.12,
        "min_net_guard_enabled": False,
        "diagnostic_or_assisted": False,
    }
    assert classify_admission_provenance(trade, current_threshold=0.12) == "OPENED_WITH_MIN_NET_GUARD_DISABLED"


def test_compute_calibration_stats_reports_overestimation_and_error():
    trades = [
        {"expected_net_after_full_cost": 0.02, "realized_pnl": -0.01},
        {"expected_net_after_full_cost": 0.04, "realized_pnl": 0.01},
    ]
    stats = compute_calibration_stats(trades)
    assert stats["count"] == 2
    assert stats["average_expected_net"] == 0.03
    assert stats["average_realized_pnl"] == 0.0
    assert stats["average_prediction_error"] == 0.03
    assert stats["overestimation_ratio"] == float("inf")


def test_profit_factor_handles_mixed_and_empty_values():
    assert profit_factor([1.0, -0.5]) == 2.0
    assert profit_factor([]) == 0.0


def test_load_clean_lower_bucket_trades_extracts_mfe_mae_and_meta_expected(tmp_path):
    db_path = tmp_path / "run.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE logs (id INTEGER, timestamp TEXT, event TEXT, details TEXT)")
    open_payload = {
        "symbol": "SOLUSDTM",
        "strategy": "TrendFollowingV2",
        "side": "buy",
        "expected_net_after_full_cost": 0.02,
        "expected_gross_before_cost": 0.001,
        "notional_usdt": 20.0,
        "entry_reason": "decision_passed",
        "cost_breakdown": {"total_cost_ratio": 0.00025, "fee_round_trip_ratio": 0.0002, "spread_ratio": 0.00001, "slippage_ratio": 0.00005},
        "time_decay_exit_sec": 43.2,
    }
    close_payload = {
        "symbol": "SOLUSDTM",
        "strategy": "TrendFollowingV2",
        "side": "buy",
        "realized_pnl": -0.03,
        "realized_gross": 0.001,
        "entry_fee_usdt": 0.002,
        "exit_fee_usdt": 0.002,
        "exit_reason": "protective_exit",
        "opened_ts": 100.0,
        "close_timestamp": 120.0,
        "meta": {"expected_net_after_full_cost": 0.02, "cost_breakdown": {"total_cost_ratio": 0.00025}},
    }
    conn.execute("INSERT INTO logs VALUES (1, '2026-06-03T00:00:00Z', 'position_open_v2', ?)", (json.dumps(open_payload),))
    conn.execute("INSERT INTO logs VALUES (2, '2026-06-03T00:00:05Z', 'exit_eval_v2', ?)", (json.dumps({"symbol": "SOLUSDTM", "unrealized_net_pnl": 0.01}),))
    conn.execute("INSERT INTO logs VALUES (3, '2026-06-03T00:00:10Z', 'exit_eval_v2', ?)", (json.dumps({"symbol": "SOLUSDTM", "unrealized_net_pnl": -0.02}),))
    conn.execute("INSERT INTO logs VALUES (4, '2026-06-03T00:00:20Z', 'position_close_v2', ?)", (json.dumps(close_payload),))
    conn.commit()
    conn.close()

    trades = load_clean_lower_bucket_trades(
        run_id="test",
        db_path=db_path,
        run_report={"after": {"effective_env_values": {}, "diagnostic_env_flags": {"LIVE": "0", "DIAGNOSTIC_MODE": "0"}}},
        current_threshold=0.12,
    )
    assert len(trades) == 1
    trade = trades[0]
    assert trade["expected_net_after_full_cost"] == 0.02
    assert trade["mfe"] == 0.01
    assert trade["mae"] == -0.02
    assert trade["green_to_red"] is True
    assert trade["fee_inversion"] is True
    assert trade["admission_provenance"] == "OPENED_UNDER_LEGACY_THRESHOLD"
