from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.realized_profitability_operating_point_audit import (
    CLASS_CONTAMINATED,
    CLASS_NO_TRADES,
    CLASS_REALIZED_LOSS_DOMINANT,
    CLASS_REALIZED_PROFIT_TARGET_FOUND,
    audit_realized_operating_point,
)


def _write_db(path: Path, payloads: list[dict]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE logs (timestamp TEXT, event TEXT, details TEXT)")
        for idx, payload in enumerate(payloads):
            conn.execute(
                "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
                (f"2026-06-04T00:00:{idx:02d}", "position_close", json.dumps(payload)),
            )
        conn.commit()
    finally:
        conn.close()


def _trade(symbol: str, pnl: float, *, contaminated: bool = False) -> dict:
    return {
        "symbol": symbol,
        "side": "sell",
        "strategy": "MeanReversionV2",
        "realized_pnl": pnl,
        "exit_reason": "take_profit_net" if pnl > 0 else "protective_exit",
        "meta": {
            "expected_net_after_full_cost": 0.2,
            "contamination_flags": {"seed": int(contaminated), "fallback": 0, "mock": 0, "force_open": 0, "forced_cycle": 0},
            "sizing_trace": {"expected_net_after_full_cost": 0.2},
            "cost_breakdown": {"runtime_profile_source": "rolling_quote_window"},
        },
    }


def test_finds_realized_profit_target_when_net_winrate_and_profit_factor_pass(tmp_path: Path) -> None:
    db = tmp_path / "trades.db"
    payloads = [_trade("BNBUSDTM", 0.08) for _ in range(7)]
    payloads += [_trade("BNBUSDTM", -0.03) for _ in range(3)]
    _write_db(db, payloads)

    report = audit_realized_operating_point([db])

    assert report["classification"] == CLASS_REALIZED_PROFIT_TARGET_FOUND
    assert report["best_realized_bucket"]["candidate_key"] == "BNBUSDTM:MEANREVERSION:sell"
    assert report["best_realized_bucket"]["net_pnl"] > 0
    assert report["profitability_claim"] is False


def test_classifies_loss_dominant_when_trades_exist_but_best_bucket_loses(tmp_path: Path) -> None:
    db = tmp_path / "trades.db"
    _write_db(db, [_trade("BTCUSDTM", 0.02), _trade("BTCUSDTM", -0.08), _trade("BTCUSDTM", -0.04)])

    report = audit_realized_operating_point([db], min_trades=2)

    assert report["classification"] == CLASS_REALIZED_LOSS_DOMINANT
    assert report["best_realized_bucket"]["net_pnl"] < 0


def test_contamination_overrides_profitable_realized_bucket(tmp_path: Path) -> None:
    db = tmp_path / "trades.db"
    _write_db(db, [_trade("XRPUSDTM", 0.10, contaminated=True), _trade("XRPUSDTM", 0.10)])

    report = audit_realized_operating_point([db], min_trades=1)

    assert report["classification"] == CLASS_CONTAMINATED


def test_no_trades_blocks_realized_profitability_claim(tmp_path: Path) -> None:
    db = tmp_path / "trades.db"
    _write_db(db, [])

    report = audit_realized_operating_point([db])

    assert report["classification"] == CLASS_NO_TRADES
    assert report["best_realized_bucket"] is None
