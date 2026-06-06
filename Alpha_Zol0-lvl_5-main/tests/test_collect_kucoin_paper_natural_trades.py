from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.collect_kucoin_paper_natural_trades import collect_natural_trades, main


def _create_db(path: Path) -> None:
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        create table closed_trades (
            id integer primary key,
            symbol text,
            strategy_name text,
            side text,
            net_pnl real,
            mode text,
            live integer,
            use_mock integer,
            is_seed integer,
            is_fallback integer,
            is_force_open integer,
            is_diagnostic integer
        )
        """
    )
    con.commit()
    con.close()


def _insert_rows(path: Path, rows: list[tuple]) -> None:
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executemany(
        """
        insert into closed_trades (
            symbol, strategy_name, side, net_pnl,
            mode, live, use_mock, is_seed, is_fallback, is_force_open, is_diagnostic
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    con.commit()
    con.close()


def test_aggregation_counts_natural_and_groups_btc_tf_buy(tmp_path: Path) -> None:
    db = tmp_path / "run.db"
    _create_db(db)
    _insert_rows(
        db,
        [
            ("BTCUSDTM", "TrendFollowing", "buy", 1.0, "paper", 0, 0, 0, 0, 0, 0),
            ("BTCUSDTM", "TrendFollowing", "buy", -0.4, "paper", 0, 0, 0, 0, 0, 0),
            ("SOLUSDTM", "TrendFollowing", "buy", 0.3, "paper", 0, 0, 0, 0, 0, 0),
        ],
    )

    report = collect_natural_trades([db])

    assert report["totals"]["natural_closed_rows"] == 3
    assert report["totals"]["rejected_rows"] == 0

    btc = next(
        g
        for g in report["groups"]
        if g["symbol"] == "BTCUSDTM"
        and g["strategy"] == "TrendFollowing"
        and g["side"] == "buy"
    )
    assert btc["trade_count"] == 2
    assert btc["winrate"] == 0.5
    assert round(float(btc["net_pnl"]), 6) == 0.6
    assert round(float(btc["expectancy"]), 6) == 0.3
    assert round(float(btc["profit_factor"]), 6) == 2.5


def test_seed_fallback_force_diagnostic_rows_are_rejected(tmp_path: Path) -> None:
    db = tmp_path / "run.db"
    _create_db(db)
    _insert_rows(
        db,
        [
            ("BTCUSDTM", "TrendFollowing", "buy", 1.0, "paper", 0, 0, 1, 0, 0, 0),
            ("BTCUSDTM", "TrendFollowing", "buy", 1.0, "paper", 0, 0, 0, 1, 0, 0),
            ("BTCUSDTM", "TrendFollowing", "buy", 1.0, "paper", 0, 0, 0, 0, 1, 0),
            ("BTCUSDTM", "TrendFollowing", "buy", 1.0, "paper", 0, 0, 0, 0, 0, 1),
            ("BTCUSDTM", "TrendFollowing", "buy", 1.0, "live", 1, 0, 0, 0, 0, 0),
            ("BTCUSDTM", "TrendFollowing", "buy", 1.0, "paper", 0, 1, 0, 0, 0, 0),
            ("BTCUSDTM", "TrendFollowing", "buy", 1.0, "paper", 0, 0, 0, 0, 0, 0),
        ],
    )

    report = collect_natural_trades([db])

    assert report["totals"]["natural_closed_rows"] == 1
    assert report["totals"]["rejected_rows"] == 6
    reasons = report["totals"]["rejected_reason_counts"]
    assert reasons["seed_trade"] == 1
    assert reasons["fallback_open"] == 1
    assert reasons["force_open"] == 1
    assert reasons["diagnostic_open"] == 1
    assert reasons["live_mode"] == 1
    assert reasons["mock_data"] == 1


def test_missing_table_returns_nonzero_exit(tmp_path: Path) -> None:
    db = tmp_path / "broken.db"
    con = sqlite3.connect(db)
    con.execute("create table logs(id integer primary key, details text)")
    con.commit()
    con.close()

    out = tmp_path / "report.json"
    rc = main(["--db", str(db), "--output-json", str(out)])
    assert rc == 2
    assert not out.exists()


def test_zero_natural_rows_still_writes_valid_json(tmp_path: Path) -> None:
    db = tmp_path / "run.db"
    _create_db(db)
    _insert_rows(
        db,
        [
            ("BTCUSDTM", "TrendFollowing", "buy", 1.0, "paper", 0, 0, 1, 0, 0, 0),
            ("SOLUSDTM", "TrendFollowing", "buy", 1.0, "paper", 0, 0, 0, 1, 0, 0),
        ],
    )

    out = tmp_path / "report.json"
    rc = main(["--db", str(db), "--output-json", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["totals"]["natural_closed_rows"] == 0
    assert payload["totals"]["group_count"] == 0
    assert payload["groups"] == []
