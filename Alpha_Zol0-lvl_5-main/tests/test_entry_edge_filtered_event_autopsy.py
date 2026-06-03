from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.entry_edge_filtered_event_autopsy import (
    build_report,
    classify_autopsy,
    extract_runtime_events,
)


def _write_result(path: Path, db_path: Path, threshold: float) -> None:
    path.write_text(
        json.dumps(
            {
                "params": {"after_env_overrides": {"ENTRY_MIN_NET_USDT": f"{threshold:.2f}"}},
                "after": {
                    "db_path": str(db_path),
                    "effective_env_values": {},
                    "diagnostic_env_flags": {"LIVE": "0"},
                },
            }
        ),
        encoding="utf-8",
    )


def _insert_log(conn: sqlite3.Connection, event: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO logs(timestamp, event, details) VALUES (?, ?, ?)",
        ("2026-06-03T00:00:00Z", event, json.dumps(payload)),
    )


def test_extract_runtime_events_recomputes_entry_formula_and_stop_ratio(tmp_path: Path):
    db_path = tmp_path / "run.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE logs(id INTEGER PRIMARY KEY, timestamp TEXT, event TEXT, details TEXT)")
    _insert_log(
        conn,
        "entry_reject_v2",
        {
            "symbol": "AVAXUSDTM",
            "strategy": "TrendFollowingV2",
            "side": "sell",
            "reason_code": "entry_net_to_stop_guard",
            "expected_move": 0.001,
            "expected_net_after_cost": 0.0007,
            "expected_edge_after_fee": 0.0008,
            "cost_breakdown": {
                "fee_round_trip_ratio": 0.0002,
                "spread_ratio": 0.00005,
                "slippage_ratio": 0.00005,
                "total_cost_ratio": 0.0003,
            },
            "risk_block_fields": {
                "sizing_trace": {
                    "final_notional_usdt": 50.0,
                    "expected_net_after_full_cost": 0.035,
                    "entry_net_to_stop_ratio": 0.9090909091,
                    "entry_min_net_to_stop_ratio": 1.1,
                    "estimated_stop_loss_net_usdt": 0.0385,
                }
            },
        },
    )
    conn.commit()
    conn.close()

    records = extract_runtime_events(db_path, run_id="r1", threshold=0.03)

    assert len(records) == 1
    assert records[0]["formula_expected_edge_after_fee"] == 0.0008
    assert records[0]["formula_expected_net_after_cost"] == pytest.approx(0.0007)
    assert records[0]["formula_entry_net_to_stop_ratio"] == pytest.approx(0.9090909090909092)
    assert records[0]["formula_match"] is True
    assert records[0]["net_to_stop_triggered"] is True
    assert records[0]["dominant_blocker"] == "entry_net_to_stop_guard"


def test_classify_autopsy_detects_propagated_override_and_ratio_block():
    result = classify_autopsy(
        [
            {
                "threshold": 0.03,
                "entry_min_net_usdt": 0.03,
                "reason_code": "entry_net_to_stop_guard",
                "formula_match": True,
                "entry_net_to_stop_ratio": 0.91,
                "entry_min_net_to_stop_ratio": 1.1,
            }
        ]
    )

    assert result["classification"] == "THRESHOLD_OVERRIDE_PROPAGATED_RISK_RATIO_BLOCKS"
    assert result["threshold_override_propagated"] is True
    assert result["formula_mismatch_count"] == 0


def test_build_report_aggregates_candidate_thresholds(tmp_path: Path):
    db_path = tmp_path / "run.db"
    result_path = tmp_path / "result.json"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE logs(id INTEGER PRIMARY KEY, timestamp TEXT, event TEXT, details TEXT)")
    _insert_log(
        conn,
        "entry_reject_v2",
        {
            "symbol": "BNBUSDTM",
            "strategy": "TrendFollowingV2",
            "side": "buy",
            "reason_code": "entry_min_net_guard",
            "expected_move": 0.001,
            "expected_net_after_cost": 0.0007,
            "expected_edge_after_fee": 0.0008,
            "cost_breakdown": {"fee_round_trip_ratio": 0.0002, "total_cost_ratio": 0.0003},
            "risk_block_fields": {
                "sizing_trace": {
                    "final_notional_usdt": 50.0,
                    "expected_net_after_full_cost": 0.035,
                    "entry_min_net_usdt": 0.05,
                    "estimated_stop_loss_net_usdt": 0.0385,
                }
            },
        },
    )
    conn.commit()
    conn.close()
    _write_result(result_path, db_path, 0.05)

    report = build_report([result_path])

    assert report["classification"] == "ENTRY_EDGE_FILTER_CORRECT_WEAK_EDGE"
    assert report["candidate_threshold_summary"]["BNBUSDTM:TrendFollowingV2:buy|0.05"][
        "entry_min_net_guard_count"
    ] == 1
    assert report["candidate_threshold_summary"]["BNBUSDTM:TrendFollowingV2:buy|0.05"][
        "expected_net_after_full_cost_stats"
    ]["max"] == 0.035
