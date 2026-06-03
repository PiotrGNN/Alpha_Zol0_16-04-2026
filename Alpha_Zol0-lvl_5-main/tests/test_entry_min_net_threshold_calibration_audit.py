
import json
import sqlite3

from scripts.entry_min_net_threshold_calibration_audit import (
    BUCKET_LABELS,
    ControlledRun,
    bucket_for_expected_net,
    classify_calibration,
    load_runtime_records,
    profit_factor,
    sufficient_sample,
    threshold_simulation,
)


def test_bucket_for_expected_net_boundaries():
    assert BUCKET_LABELS == ["<0.03", "0.03-0.05", "0.05-0.08", "0.08-0.10", "0.10-0.12", "0.12-0.15", ">0.15"]
    assert bucket_for_expected_net(0.0) == "<0.03"
    assert bucket_for_expected_net(0.029999) == "<0.03"
    assert bucket_for_expected_net(0.03) == "0.03-0.05"
    assert bucket_for_expected_net(0.05) == "0.05-0.08"
    assert bucket_for_expected_net(0.08) == "0.08-0.10"
    assert bucket_for_expected_net(0.10) == "0.10-0.12"
    assert bucket_for_expected_net(0.12) == "0.12-0.15"
    assert bucket_for_expected_net(0.15) == ">0.15"


def test_profit_factor_handles_zero_loss_and_mixed_pnl():
    assert profit_factor([1.0, 2.0]) == float("inf")
    assert profit_factor([1.0, -0.5, -0.5]) == 1.0
    assert profit_factor([-1.0]) == 0.0
    assert profit_factor([]) == 0.0


def test_threshold_simulation_counts_only_admitted_events_and_clean_trades():
    events = [
        {"expected_net_after_full_cost": 0.049, "clean_completed_trade": True, "realized_pnl": -0.2, "contaminated": False},
        {"expected_net_after_full_cost": 0.081, "clean_completed_trade": True, "realized_pnl": 0.3, "contaminated": False},
        {"expected_net_after_full_cost": 0.11, "clean_completed_trade": False, "realized_pnl": None, "contaminated": False},
        {"expected_net_after_full_cost": 0.13, "clean_completed_trade": True, "realized_pnl": 0.1, "contaminated": True},
    ]
    sim = threshold_simulation(events, [0.05, 0.08, 0.10, 0.12], min_clean_sample=2)
    assert sim["0.05"]["admitted_event_count"] == 3
    assert sim["0.05"]["clean_completed_trade_count"] == 1
    assert sim["0.08"]["admitted_event_count"] == 3
    assert sim["0.08"]["clean_completed_trade_count"] == 1
    assert sim["0.12"]["admitted_event_count"] == 1
    assert sim["0.12"]["clean_completed_trade_count"] == 0
    assert sim["0.05"]["contamination_rate"] == 1 / 3
    assert sim["0.05"]["sample_sufficient"] is False


def test_classify_calibration_prefers_negative_lower_bucket_support():
    lower = {
        "clean_completed_trade_count": 3,
        "expectancy": -0.01,
        "net_pnl": -0.03,
    }
    assert sufficient_sample(3, min_clean_sample=3) is True
    classification = classify_calibration(
        lower_bucket_aggregate=lower,
        below_threshold_positive_bucket_count=0,
        below_threshold_clean_trade_count=3,
        min_clean_sample=3,
    )
    assert classification == "ENTRY_MIN_NET_0_12_SUPPORTED_BY_NEGATIVE_LOWER_BUCKETS"


def test_classify_calibration_blocks_on_insufficient_clean_sample():
    classification = classify_calibration(
        lower_bucket_aggregate={"clean_completed_trade_count": 1, "expectancy": 1.0, "net_pnl": 1.0},
        below_threshold_positive_bucket_count=1,
        below_threshold_clean_trade_count=1,
        min_clean_sample=3,
    )
    assert classification == "ENTRY_MIN_NET_CALIBRATION_BLOCKED_BY_INSUFFICIENT_CLEAN_SAMPLE"


def test_load_runtime_records_pairs_close_by_symbol_when_position_ids_differ(tmp_path):
    db_path = tmp_path / "controlled.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE logs (id INTEGER, timestamp TEXT, event TEXT, details TEXT)")
    conn.execute(
        "INSERT INTO logs VALUES (1, '2026-06-03T00:00:00Z', 'position_open_v2', ?)",
        (
            json.dumps(
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowingV2",
                    "side": "buy",
                    "expected_net_after_full_cost": 0.016,
                }
            ),
        ),
    )
    conn.execute(
        "INSERT INTO logs VALUES (2, '2026-06-03T00:00:01Z', 'position_close_v2', ?)",
        (
            json.dumps(
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowingV2",
                    "side": "buy",
                    "position_id": "runtime-close-id",
                    "realized_pnl": -0.02,
                    "exit_reason": "protective_exit",
                }
            ),
        ),
    )
    conn.commit()
    conn.close()

    run = ControlledRun(
        run_id="test",
        json_path=tmp_path / "report.json",
        db_path=db_path,
        report={},
        clean=True,
        rejection_reasons=(),
    )
    records = load_runtime_records(run)
    close_records = [row for row in records if row["event"] == "position_close_v2"]
    assert len(close_records) == 1
    assert close_records[0]["expected_net_after_full_cost"] == 0.016
    assert close_records[0]["clean_completed_trade"] is True
    assert close_records[0]["realized_pnl"] == -0.02
