from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from scripts.v2_expected_move_calibration_autopsy import (
    RunInput,
    _bucket_calibration_stats,
    _calibration_summary,
    build_expected_move_calibration_corpus,
)


def test_expected_move_calibration_autopsy_imports_without_admitted_edge_audit(
    monkeypatch,
) -> None:
    module_name = "scripts.v2_expected_move_calibration_autopsy"
    dependency_name = "scripts.audit_v2_admitted_edge_quality"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setitem(sys.modules, dependency_name, None)

    module = __import__(module_name, fromlist=["RunInput", "_safe_float"])

    assert isinstance(module.RunInput("r", Path("a.db"), Path("a.json"), {}), object)
    assert module._safe_float("1.25") == 1.25
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.delitem(sys.modules, dependency_name, raising=False)


def _init_logs_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            event VARCHAR(64) NOT NULL,
            details TEXT NULL
        )
        """
    )
    con.commit()
    con.close()


def _insert_log(path: Path, event: str, details: dict) -> None:
    con = sqlite3.connect(str(path))
    cur = con.cursor()
    cur.execute(
        "INSERT INTO logs(timestamp, event, details) VALUES(datetime('now'), ?, ?)",
        (event, json.dumps(details)),
    )
    con.commit()
    con.close()


def test_bucket_calibration_stats_detects_overoptimistic_edge() -> None:
    rows = []
    for idx in range(5):
        strategy = "TrendFollowingV2" if idx < 2 else "MomentumV2"
        realized_pnl = -0.01 if idx < 2 else -0.009
        realized_gross = -0.005 if idx < 2 else -0.0045
        rows.append(
            {
                "symbol": "BTCUSDTM",
                "strategy": strategy,
                "side": "buy",
                "open_timestamp": 1000.0 + idx,
                "close_timestamp": 1020.0 + idx,
                "realized_pnl": realized_pnl,
                "realized_gross": realized_gross,
                "expected_net_after_full_cost": 0.02,
                "expected_gross_before_cost": 0.03,
                "decision_or_gate_reason": "allow",
                "entry_reason": "decision_passed",
                "runtime_profile_source_missing": False,
                "signal_horizon_sec_estimate": 4.0,
                "time_horizon_mismatch_ratio": 1.0,
                "exit_reason": "time_decay_exit",
                "mfe_unrealized_net": -0.002,
            }
        )

    stats = _bucket_calibration_stats(rows)
    summary = _calibration_summary(rows)

    assert stats["bucket_count"] == 2
    assert stats["buckets"][0]["calibration_factor"] < 0.0
    assert summary["classification"] == "EXPECTED_MOVE_OVEROPTIMISTIC_DOMINANT"
    assert summary["clean_trade_count"] == 5
    assert summary["time_decay_loss_count"] == 5


def test_bucket_calibration_stats_coarsens_mismatch_suffixes() -> None:
    rows = []
    for mismatch_ratio in (1.0, 3.0):
        rows.append(
            {
                "symbol": "BTCUSDTM",
                "strategy": "TrendFollowingV2",
                "side": "buy",
                "open_timestamp": 1000.0,
                "close_timestamp": 1020.0,
                "realized_pnl": 0.01,
                "realized_gross": 0.015,
                "expected_net_after_full_cost": 0.01,
                "expected_gross_before_cost": 0.02,
                "decision_or_gate_reason": "allow",
                "entry_reason": "decision_passed",
                "runtime_profile_source_missing": False,
                "signal_horizon_sec_estimate": 4.0,
                "time_horizon_mismatch_ratio": mismatch_ratio,
            }
        )

    stats = _bucket_calibration_stats(rows)

    assert stats["bucket_count"] == 1
    assert stats["buckets"][0]["horizon_bucket"] == "signal_lt_5s"
    assert stats["buckets"][0]["n"] == 2


def test_build_expected_move_calibration_corpus_from_db(tmp_path: Path) -> None:
    db_path = tmp_path / "controlled_kpi_after_20260527_000000.db"
    json_path = tmp_path / "controlled_kpi_20260527_000000.json"
    _init_logs_db(db_path)
    json_path.write_text(
        json.dumps({"run_id": "20260527_000000", "after": {}}),
        encoding="utf-8",
    )

    _insert_log(
        db_path,
        "entry_gate_decision_summary",
        {
            "symbol": "ETHUSDTM",
            "side": "sell",
            "strategy": "TrendFollowingV2",
            "final_allow": True,
            "local_gate_reason": "allow",
            "entry_edge_after_execution": {"expected_net_after_cost": 0.02},
            "entry_edge_over_fee": {"expected_edge_after_fee": 0.03},
        },
    )
    _insert_log(
        db_path,
        "position_open_v2",
        {
            "symbol": "ETHUSDTM",
            "side": "sell",
            "strategy": "TrendFollowingV2",
            "entry_reason": "decision_passed",
            "runtime_profile_source": "rolling_quote_window",
            "runtime_profile_key": "ETHUSDTM|rolling_quote_window|n=48|span=40",
            "runtime_profile_age_sec": 120.0,
            "runtime_profile_span_sec": 40.0,
            "runtime_profile_sample_size": 48,
            "expected_net_after_full_cost": 0.02,
            "expected_move_raw": 0.03,
            "expected_move_scaled": 0.03,
            "expected_gross_before_cost": 0.03,
            "requested_notional_usdt": 25.0,
            "notional_usdt": 24.0,
            "leverage": 3.0,
            "position": {
                "symbol": "ETHUSDTM",
                "side": "sell",
                "strategy": "TrendFollowingV2",
                "opened_at": 1000.0,
                "meta": {
                    "signal_horizon_sec_estimate": 4.0,
                    "execution_horizon_sec": 12.0,
                    "time_decay_exit_sec": 12.0,
                    "time_horizon_mismatch_ratio": 3.0,
                },
            },
        },
    )
    _insert_log(
        db_path,
        "position_close_v2",
        {
            "symbol": "ETHUSDTM",
            "side": "sell",
            "strategy": "TrendFollowingV2",
            "opened_ts": 1000.0,
            "close_timestamp": 1015.0,
            "realized_pnl": -0.01,
            "realized_gross": -0.005,
            "entry_fee_usdt": 0.001,
            "exit_fee_usdt": 0.001,
            "exit_reason": "time_decay_exit",
        },
    )

    run_input = RunInput(
        run_id="20260527_000000",
        db_path=db_path,
        json_path=json_path,
        report={"run_id": "20260527_000000", "after": {}},
    )
    audit = build_expected_move_calibration_corpus([run_input])

    assert audit["clean_trade_count"] == 1
    assert audit["combined_verdict"] == "INSUFFICIENT_TELEMETRY"
    assert audit["bucket_stats"]["bucket_count"] == 1
    assert audit["clean_trades"][0]["clean_trade_eligible"] is True
    assert audit["clean_trades"][0]["calibration_bucket_key"].startswith("ETHUSDTM")
