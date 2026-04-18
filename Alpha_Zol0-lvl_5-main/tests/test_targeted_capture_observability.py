import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "DataAnalysisExpert"
    / "profitability_total_cost_audit.py"
)
SPEC = importlib.util.spec_from_file_location(
    "profitability_total_cost_audit", MODULE_PATH
)
AUDIT = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def test_extract_run_metrics_prefers_direct_close_observability_fields(tmp_path):
    db_path = tmp_path / "capture_observability.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT, "
        "event TEXT, "
        "details TEXT"
        ")"
    )
    cur.execute(
        "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
        (
            "2026-03-12T00:00:00+00:00",
            "position_open",
            json.dumps(
                {
                    "trade_id": "trade-1",
                    "symbol": "BTCUSDTM",
                    "position": {
                        "trade_id": "trade-1",
                        "symbol": "BTCUSDTM",
                        "timestamp": "2026-03-12T00:00:00+00:00",
                        "fill_price": 100.0,
                        "amount": 1.0,
                        "side": "buy",
                        "entry_regime": "trend",
                        "strategy": "MomentumStrategy",
                        "open_snapshot": {"mid": 100.0},
                    },
                }
            ),
        ),
    )
    cur.execute(
        "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
        (
            "2026-03-12T00:00:40+00:00",
            "close_candidates_evaluated",
            json.dumps(
                {
                    "trade_id": "trade-1",
                    "selected_reason": "auto_close_hard",
                    "selected_expected_net_after_fee": 0.8,
                    "candidates": [
                        {
                            "reason": "auto_close_time_economics",
                            "allowed": True,
                            "expected_net_after_fee": 7.0,
                        }
                    ],
                }
            ),
        ),
    )
    cur.execute(
        "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
        (
            "2026-03-12T00:00:59+00:00",
            "hard_close_missed_economic_exit",
            json.dumps(
                {
                    "trade_id": "trade-1",
                    "positive_time_candidate_within_40_sec": True,
                    "time_economics_probe": {"expected_net_after_fee": 9.0},
                }
            ),
        ),
    )
    cur.execute(
        "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
        (
            "2026-03-12T00:01:00+00:00",
            "position_close",
            json.dumps(
                {
                    "trade_id": "trade-1",
                    "symbol": "BTCUSDTM",
                    "close_price": 102.0,
                    "realized_pnl": 2.0,
                    "exit_reason": "auto_close_hard",
                    "close_reason": "auto_close_hard",
                    "mfe": 4.0,
                    "mae": -1.0,
                    "realized_net": 2.0,
                    "pre_hard_close_feasible_net": 4.0,
                    "pre_hard_close_best_feasible_net": 4.0,
                    "economic_exit_feasible": True,
                    "economic_exit_captured": False,
                    "capture_ratio_proxy": 0.5,
                    "hard_close_missed_event_positive_within_40": True,
                    "close_snapshot": {"mid": 102.0},
                    "pnl_decompose": {
                        "net_pnl": 2.0,
                        "gross_fill_pnl_model": 2.4,
                        "fee_total": 0.3,
                        "spread_cost": 0.05,
                        "slippage_cost": 0.05,
                        "funding_total": 0.0,
                    },
                    "position": {
                        "trade_id": "trade-1",
                        "symbol": "BTCUSDTM",
                        "timestamp": "2026-03-12T00:00:00+00:00",
                        "close_timestamp": "2026-03-12T00:01:00+00:00",
                        "fill_price": 100.0,
                        "close_fill_price": 102.0,
                        "amount": 1.0,
                        "side": "buy",
                        "entry_regime": "trend",
                        "strategy": "MomentumStrategy",
                    },
                }
            ),
        ),
    )
    conn.commit()
    conn.close()

    metrics = AUDIT._extract_run_metrics(db_path)
    coverage_gate = metrics["coverage_gate"]

    assert metrics["pre_hard_close_best_feasible_net"] == 4.0
    assert metrics["mean_capture_ratio_proxy"] == 0.5
    assert metrics["economic_exit_feasible_count"] == 1
    assert coverage_gate["status"] == "pass"
    assert coverage_gate["gate_pass"] is True
    assert coverage_gate["pre_hard_close_best_feasible_net_share_hard"] == 1.0
    assert coverage_gate["capture_ratio_proxy_share_all"] == 1.0
    assert coverage_gate["direct_position_close_mfe_source_share"] == 1.0

    close_record = metrics["close_records"][0]
    assert close_record["mfe"] == 4.0
    assert close_record["mae"] == -1.0
    assert close_record["mfe_mae_source"] == "position_close_direct"
    assert close_record["pre_hard_close_best_feasible_net"] == 4.0
    assert close_record["capture_ratio_proxy"] == 0.5
    assert close_record["hard_close_missed_event_positive_within_40"] is True
