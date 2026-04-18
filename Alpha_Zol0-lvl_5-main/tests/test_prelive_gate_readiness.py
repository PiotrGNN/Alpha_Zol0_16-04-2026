import json
import sqlite3
from datetime import datetime, timezone

from utils.prelive_gate import evaluate_live_readiness


def _init_ready_db(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE logs (timestamp TEXT, event TEXT, details TEXT)"
        )
        conn.execute(
            "CREATE TABLE equity (timestamp TEXT, equity REAL)"
        )
        conn.execute(
            "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)" ,
            (
                datetime.now(timezone.utc).isoformat(),
                "position_close",
                json.dumps({"realized_pnl": 0.25}),
            ),
        )
        conn.execute(
            "INSERT INTO equity (timestamp, equity) VALUES (?, ?)" ,
            (datetime.now(timezone.utc).isoformat(), 1000.0),
        )
        conn.commit()
    finally:
        conn.close()


def _init_negative_equity_db(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE logs (timestamp TEXT, event TEXT, details TEXT)"
        )
        conn.execute(
            "CREATE TABLE equity (timestamp TEXT, equity REAL)"
        )
        conn.execute(
            "INSERT INTO logs (timestamp, event, details) VALUES (?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                "position_close",
                json.dumps({"realized_pnl": -0.15}),
            ),
        )
        conn.execute(
            "INSERT INTO equity (timestamp, equity) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), -1.0),
        )
        conn.execute(
            "INSERT INTO equity (timestamp, equity) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), -1.5),
        )
        conn.execute(
            "INSERT INTO equity (timestamp, equity) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), -2.0),
        )
        conn.commit()
    finally:
        conn.close()


def test_evaluate_live_readiness_trims_padded_sqlite_url(tmp_path):
    db_path = tmp_path / "prelive_ready.db"
    _init_ready_db(db_path)

    result = evaluate_live_readiness(
        database_url=f"  sqlite:///{db_path}  ",
        lookback_hours=1,
        min_trades=1,
        min_profit_factor=0.0,
        min_winrate=0.0,
        max_drawdown=1.0,
    )

    assert result["passed"] is True
    assert result["database_path"].endswith("prelive_ready.db")
    assert result["kpi"]["trade_count"] == 1
    assert result["kpi"]["net_pnl"] == 0.25


def test_evaluate_live_readiness_blocks_negative_only_equity_drawdown(tmp_path):
    db_path = tmp_path / "prelive_negative_equity.db"
    _init_negative_equity_db(db_path)

    result = evaluate_live_readiness(
        database_url=f"sqlite:///{db_path}",
        lookback_hours=1,
        min_trades=1,
        min_profit_factor=0.0,
        min_winrate=0.0,
        max_drawdown=0.1,
    )

    assert result["passed"] is False
    assert result["checks"]["max_drawdown"] is False
    assert result["kpi"]["max_drawdown"] > 0.1
