from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.runtime_profitability_flow_autopsy import (
    CLASS_CONTAMINATED,
    CLASS_EXIT_LOSS_DOMINANT,
    CLASS_REALIZED_LOSS_DOMINANT,
    CLASS_RISK_BLOCKED,
    CLASS_TELEMETRY_GAP,
    audit_runtime_profitability_flow,
)


def _write_db(path: Path, events: list[tuple[str, dict]]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE logs (timestamp TEXT, event TEXT, details TEXT)")
        for idx, (event, payload) in enumerate(events):
            conn.execute(
                "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
                (f"2026-06-04T00:00:{idx:02d}", event, json.dumps(payload)),
            )
        conn.commit()
    finally:
        conn.close()


def _candidate(reason: str, *, symbol: str = "BTCUSDTM", strategy: str = "MeanReversionV2") -> dict:
    return {
        "symbol": symbol,
        "strategy": strategy,
        "side": "sell",
        "reason_code": reason,
        "expected_move": 0.001,
        "expected_net_after_cost": 0.0007,
        "cost_breakdown": {
            "runtime_profile_source": "rolling_quote_window",
            "total_cost_ratio": 0.00025,
        },
        "risk_block_fields": {
            "sizing_trace": {
                "final_notional_usdt": 200.0,
                "expected_net_after_full_cost": 0.14,
                "entry_min_net_usdt": 0.12,
            }
        },
    }


def _close(symbol: str, pnl: float, reason: str, *, contaminated: bool = False) -> dict:
    return {
        "symbol": symbol,
        "strategy": "MeanReversionV2",
        "side": "sell",
        "realized_pnl": pnl,
        "exit_reason": reason,
        "notional_usdt": 200.0,
        "meta": {
            "contamination_flags": {
                "seed": int(contaminated),
                "fallback": 0,
                "mock": 0,
                "force_open": 0,
                "forced_cycle": 0,
            },
            "sizing_trace": {
                "final_notional_usdt": 200.0,
                "expected_net_after_full_cost": 0.14,
                "entry_min_net_usdt": 0.12,
            },
            "cost_breakdown": {
                "runtime_profile_source": "rolling_quote_window",
                "expected_move_raw": 0.001,
                "expected_move_scaled": 0.00125,
            },
        },
    }


def test_entry_eval_allow_without_open_is_downstream_risk_blocker(tmp_path: Path) -> None:
    db = tmp_path / "risk_blocked.db"
    _write_db(
        db,
        [
            ("entry_eval_v2", _candidate("allow")),
            ("entry_reject_v2", _candidate("entry_min_net_guard")),
            ("risk_decision", {"symbol": "BTCUSDTM", "allow": False, "local_gate_reason": "entry_min_net_guard"}),
            ("entry_gate_decision_summary", {"symbol": "BTCUSDTM", "reason_code": "entry_min_net_guard"}),
        ],
    )

    report = audit_runtime_profitability_flow([db])

    assert report["classification"] == CLASS_RISK_BLOCKED
    assert report["entry_flow"]["entry_eval_reason_counts"]["allow"] == 1
    assert report["execution_flow"]["position_open_count"] == 0
    assert report["risk_flow"]["risk_block_reason_counts"]["entry_min_net_guard"] == 3


def test_realized_clean_losses_are_loss_dominant(tmp_path: Path) -> None:
    db = tmp_path / "losses.db"
    _write_db(
        db,
        [
            ("position_open", {"symbol": "BTCUSDTM", "strategy": "MeanReversionV2", "side": "sell"}),
            ("position_close", _close("BTCUSDTM", 0.03, "take_profit_net")),
            ("position_close", _close("BTCUSDTM", -0.04, "protective_exit")),
            ("position_close", _close("BTCUSDTM", -0.13, "time_decay_exit")),
            ("risk_decision", {"symbol": "BTCUSDTM", "allow": True, "local_gate_reason": "allow"}),
        ],
    )

    report = audit_runtime_profitability_flow([db], min_realized_trades=2)

    assert report["classification"] == CLASS_REALIZED_LOSS_DOMINANT
    assert report["realized_flow"]["net_pnl"] < 0
    assert report["realized_flow"]["bucket_summaries"][0]["passes_realized_target"] is False


def test_protective_exit_dominance_is_called_out(tmp_path: Path) -> None:
    db = tmp_path / "protective.db"
    _write_db(
        db,
        [
            ("position_close", _close("SOLUSDTM", 0.04, "take_profit_net")),
            ("position_close", _close("SOLUSDTM", -0.08, "protective_exit")),
            ("position_close", _close("SOLUSDTM", -0.09, "protective_exit")),
            ("risk_decision", {"symbol": "SOLUSDTM", "allow": True, "local_gate_reason": "allow"}),
        ],
    )

    report = audit_runtime_profitability_flow([db], min_realized_trades=2)

    assert report["classification"] == CLASS_EXIT_LOSS_DOMINANT
    assert report["exit_flow"]["dominant_loss_exit_reason"] == "protective_exit"
    assert report["exit_flow"]["exit_reason_pnl"]["protective_exit"] < 0


def test_missing_risk_decision_or_position_close_is_telemetry_gap(tmp_path: Path) -> None:
    db = tmp_path / "gap.db"
    _write_db(db, [("entry_eval_v2", _candidate("allow"))])

    report = audit_runtime_profitability_flow([db])

    assert report["classification"] == CLASS_TELEMETRY_GAP
    assert "risk_decision" in report["telemetry_gaps"]
    assert "position_close" in report["telemetry_gaps"]


def test_contamination_overrides_flow_classification(tmp_path: Path) -> None:
    db = tmp_path / "contaminated.db"
    _write_db(
        db,
        [
            ("risk_decision", {"symbol": "XRPUSDTM", "allow": True, "local_gate_reason": "allow"}),
            ("position_close", _close("XRPUSDTM", 0.10, "take_profit_net", contaminated=True)),
        ],
    )

    report = audit_runtime_profitability_flow([db], min_realized_trades=1)

    assert report["classification"] == CLASS_CONTAMINATED
    assert report["provenance"]["contaminated_event_count"] == 1
