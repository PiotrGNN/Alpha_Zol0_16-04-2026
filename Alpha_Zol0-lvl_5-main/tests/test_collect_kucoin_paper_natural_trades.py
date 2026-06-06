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
    con.execute("create table equity(id integer primary key, value real)")
    con.commit()
    con.close()

    out = tmp_path / "report.json"
    rc = main(["--db", str(db), "--output-json", str(out)])
    assert rc == 2
    assert not out.exists()


# ---------------------------------------------------------------------------
# logs-schema tests (runtime KPI DBs without closed_trades)
# ---------------------------------------------------------------------------


def _create_logs_db(path: Path) -> None:
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "create table logs "
        "(id integer primary key, timestamp text, event text, details text)"
    )
    con.commit()
    con.close()


def _insert_log_events(path: Path, events: list[tuple[str, dict]]) -> None:
    con = sqlite3.connect(path)
    cur = con.cursor()
    for ev, payload in events:
        cur.execute(
            "insert into logs(event, details) values (?, ?)",
            (ev, json.dumps(payload)),
        )
    con.commit()
    con.close()


_CLOSE_EVENT = "post_close_summary_payload_built"
_POSITION_CLOSE_EVENT = "position_close"


def test_logs_schema_groups_btc_tf_buy(tmp_path: Path) -> None:
    db = tmp_path / "run.db"
    _create_logs_db(db)
    btc_row = {
        "trade_id": "t1",
        "symbol": "BTCUSDTM",
        "strategy": "TrendFollowing",
        "side": "buy",
        "realized_net": 1.25,
    }
    sol_row = {
        "trade_id": "t2",
        "symbol": "SOLUSDTM",
        "strategy": "TrendFollowing",
        "side": "buy",
        "realized_pnl": -0.25,
    }
    _insert_log_events(
        db,
        [
            (_POSITION_CLOSE_EVENT, btc_row),
            (_POSITION_CLOSE_EVENT, {**btc_row, "trade_id": "t3", "realized_net": 0.5}),
            (_POSITION_CLOSE_EVENT, sol_row),
        ],
    )

    report = collect_natural_trades([db])

    assert report["status"] == "ok"
    assert report["schema_by_db"][str(db)]["source_schema"] == "logs"
    assert report["totals"]["natural_closed_rows"] == 3
    assert report["totals"]["rejected_rows"] == 0
    assert report["canonical_close_source"] is True

    btc = next(
        g
        for g in report["groups"]
        if g["symbol"] == "BTCUSDTM"
        and g["strategy"] == "TrendFollowing"
        and g["side"] == "buy"
    )
    assert btc["trade_count"] == 2
    assert btc["economics_available"] is True
    assert btc["net_pnl"] == 1.75


def test_logs_schema_deduplicates_duplicate_trade_id(tmp_path: Path) -> None:
    db = tmp_path / "run.db"
    _create_logs_db(db)
    row = {
        "trade_id": "dup-1",
        "symbol": "BTCUSDTM",
        "strategy": "TrendFollowing",
        "side": "buy",
        "realized_net": 0.75,
    }
    _insert_log_events(
        db,
        [
            (_POSITION_CLOSE_EVENT, row),
            (_POSITION_CLOSE_EVENT, row),
        ],
    )

    report = collect_natural_trades([db])

    assert report["totals"]["natural_closed_rows"] == 1
    assert report["totals"]["duplicate_rows"] == 1
    assert report["totals"]["rejected_reason_counts"]["duplicate_trade_id"] == 1


def test_logs_schema_ignores_summary_rows_when_position_close_exists(
    tmp_path: Path,
) -> None:
    db = tmp_path / "run.db"
    _create_logs_db(db)
    _insert_log_events(
        db,
        [
            (
                _POSITION_CLOSE_EVENT,
                {
                    "trade_id": "pc-1",
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                    "realized_net": 0.5,
                },
            ),
            (
                _CLOSE_EVENT,
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                },
            ),
        ],
    )

    report = collect_natural_trades([db])

    assert report["totals"]["scanned_closed_rows"] == 1
    assert report["totals"]["natural_closed_rows"] == 1
    assert report["schema_by_db"][str(db)]["canonical_close_source"] is True


def test_logs_schema_rejects_contaminated_rows(tmp_path: Path) -> None:
    db = tmp_path / "run.db"
    _create_logs_db(db)
    seed_row = {
        "trade_id": "s1",
        "symbol": "BTCUSDTM",
        "strategy": "TF",
        "side": "buy",
        "is_seed": 1,
    }
    fallback_row = {
        "trade_id": "s2",
        "symbol": "BTCUSDTM",
        "strategy": "TF",
        "side": "buy",
        "is_fallback": True,
    }
    clean_row = {
        "trade_id": "s3",
        "symbol": "BTCUSDTM",
        "strategy": "TF",
        "side": "buy",
    }
    _insert_log_events(
        db,
        [
            (_POSITION_CLOSE_EVENT, seed_row),
            (_POSITION_CLOSE_EVENT, fallback_row),
            (_POSITION_CLOSE_EVENT, clean_row),
        ],
    )

    report = collect_natural_trades([db])

    assert report["totals"]["natural_closed_rows"] == 1
    assert report["totals"]["rejected_rows"] == 2
    rc = report["totals"]["rejected_reason_counts"]
    assert rc.get("seed_trade", 0) == 1
    assert rc.get("fallback_open", 0) == 1


def test_logs_schema_no_supported_events_fails_loud(tmp_path: Path) -> None:
    db = tmp_path / "run.db"
    _create_logs_db(db)
    _insert_log_events(
        db,
        [("unrelated_event", {"symbol": "BTCUSDTM", "strategy": "TF", "side": "buy"})],
    )

    out = tmp_path / "report.json"
    rc = main(["--db", str(db), "--output-json", str(out)])
    assert rc == 2
    assert not out.exists()


def test_logs_schema_economics_available_false_in_output(tmp_path: Path) -> None:
    db = tmp_path / "run.db"
    _create_logs_db(db)
    xrp_row = {
        "trade_id": "x1",
        "symbol": "XRPUSDTM",
        "strategy": "TrendFollowing",
        "side": "buy",
    }
    _insert_log_events(db, [(_POSITION_CLOSE_EVENT, xrp_row)])

    out = tmp_path / "report.json"
    rc = main(["--db", str(db), "--output-json", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["totals"]["natural_closed_rows"] == 1
    g = payload["groups"][0]
    assert g["economics_available"] is False
    assert g["net_pnl"] is None


def test_logs_summary_fallback_is_marked_noncanonical(tmp_path: Path) -> None:
    db = tmp_path / "run.db"
    _create_logs_db(db)
    _insert_log_events(
        db,
        [
            (
                _CLOSE_EVENT,
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                },
            )
        ],
    )

    report = collect_natural_trades([db])

    assert (
        report["schema_by_db"][str(db)]["source_schema"]
        == "logs_summary_noncanonical"
    )
    assert report["schema_by_db"][str(db)]["canonical_close_source"] is False
    assert report["canonical_close_source"] is False
    assert report["totals"]["natural_closed_rows"] == 1


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
