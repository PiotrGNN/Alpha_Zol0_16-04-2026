import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "build_alpha_history_db.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_alpha_history_db", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_source_db(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event TEXT NOT NULL,
                details TEXT
            )
            """
        )
        for timestamp, details in rows:
            cur.execute(
                (
                    "INSERT INTO logs(timestamp, event, details) "
                    "VALUES(?, 'position_close', ?)"
                ),
                (timestamp, json.dumps(details)),
            )
        conn.commit()
    finally:
        conn.close()


def test_normalize_close_row_preserves_cost_components():
    module = _load_module()
    details = {
        "symbol": "ETHUSDTM",
        "strategy": "TrendFollowing",
        "realized_pnl": -0.001,
        "pnl_decompose": {
            "gross_fill_pnl_model": 0.001,
            "fee_total": 0.002,
            "funding_total": 0.0,
        },
        "position": {
            "symbol": "ETHUSDTM",
            "strategy": "TrendFollowing",
            "side": "buy",
            "entry_price": 1.0,
            "close_price": 1.001,
            "amount": 1.0,
            "timestamp": "entry",
            "close_timestamp": "close",
            "realized_pnl": -0.001,
        },
    }

    normalized = module._normalize_close_row(
        "2026-04-10T00:00:00+00:00",
        json.dumps(details),
    )

    assert normalized is not None
    _, out_details, _ = normalized
    assert out_details["gross_pnl"] == 0.001
    assert out_details["fee_total"] == 0.002
    assert out_details["funding_total"] == 0.0
    assert out_details["position"]["gross_pnl"] == 0.001


def test_pair_side_stats_exposes_cost_burden_fields():
    module = _load_module()
    rows = []
    for idx in range(10):
        details = {
            "symbol": "ETHUSDTM",
            "strategy": "TrendFollowing",
            "gross_pnl": 0.001,
            "fee_total": 0.002,
            "funding_total": 0.0,
            "position": {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
            },
        }
        rows.append(
            {
                "details": details,
                "pnl": -0.001,
                "gross_pnl": 0.001,
                "fee_total": 0.002,
                "funding_total": 0.0,
                "source": f"run-{idx}",
            }
        )

    stats = module._pair_side_stats(rows)
    bucket = stats[("ETHUSDTM", "TrendFollowing", "buy")]

    assert bucket["trade_count"] == 10
    assert round(bucket["gross_pnl"], 6) == 0.01
    assert round(bucket["fee_total"], 6) == 0.02
    assert bucket["gross_positive_net_negative_count"] == 10
    assert round(bucket["fee_to_abs_gross_ratio"], 6) == 2.0


def test_parse_helpers_and_pair_selection_contracts():
    module = _load_module()

    nested = json.dumps(json.dumps({"alpha": 1}))

    assert module._parse_json_payload(None) == {}
    assert module._parse_json_payload({"alpha": 1}) == {"alpha": 1}
    assert module._parse_json_payload("{\"alpha\": 1}") == {"alpha": 1}
    assert module._parse_json_payload(nested) == {"alpha": 1}
    assert module._parse_json_payload(123) == {}
    assert module._parse_json_payload("not-json") == {}

    assert module._to_float("1.25") == 1.25
    assert module._to_float(float("inf")) is None
    assert module._to_float("bad") is None

    assert module._parse_csv_set(" Alpha , beta,alpha ,, GAMMA ") == {
        "alpha",
        "beta",
        "gamma",
    }

    assert module._pair_from_details({"symbol": "ETHUSDTM", "strategy": "Trend"}) == (
        "ETHUSDTM",
        "Trend",
    )
    assert module._pair_from_details({"symbol": "", "strategy": "Trend"}) is None
    assert module._pair_side_from_details(
        {"symbol": "ETHUSDTM", "strategy": "Trend", "side": "long"}
    ) == ("ETHUSDTM", "Trend", "buy")
    assert module._pair_side_from_details(
        {"symbol": "ETHUSDTM", "strategy": "Trend", "side": "short"}
    ) == ("ETHUSDTM", "Trend", "sell")
    assert module._pair_side_from_details(
        {"symbol": "ETHUSDTM", "strategy": "Trend", "side": "hold"}
    ) is None

    allowed, fallback_used, telemetry = module._choose_allowed_pairs(
        {
            ("ETHUSDTM", "Trend"): {
                "trade_count": 3,
                "winrate": 0.5,
                "expectancy": 0.1,
            },
            ("BTCUSDTM", "Trend"): {
                "trade_count": 1,
                "winrate": 0.0,
                "expectancy": -0.2,
            },
        },
        min_pair_trades=2,
        min_pair_winrate=0.25,
        min_pair_expectancy=0.0,
        fallback_top_pairs=2,
    )

    assert allowed == {("ETHUSDTM", "Trend")}
    assert fallback_used is False
    assert telemetry["rejected_min_trades"] == 1
    assert telemetry["rejected_min_winrate"] == 1
    assert telemetry["rejected_min_expectancy"] == 1


def test_build_history_db_and_main_with_temp_sources(monkeypatch, tmp_path, capsys):
    module = _load_module()
    monkeypatch.setattr(module, "WORKDIR", tmp_path)

    source_dir = tmp_path / "tmp"
    src_a = source_dir / "controlled_kpi_a.db"
    src_b = source_dir / "controlled_kpi_b.db"

    eth_row = (
        "2026-04-13T00:00:00+00:00",
        {
            "symbol": "ETHUSDTM",
            "strategy": "TrendFollowing",
            "realized_pnl": 1.0,
            "pnl_decompose": {
                "gross_fill_pnl_model": 1.2,
                "fee_total": 0.2,
                "funding_total": 0.0,
            },
            "position": {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "entry_price": 100.0,
                "close_price": 101.0,
                "amount": 1.0,
                "timestamp": "2026-04-12T23:59:00+00:00",
                "close_timestamp": "2026-04-13T00:00:00+00:00",
                "realized_pnl": 1.0,
            },
        },
    )
    btc_row = (
        "2026-04-13T00:01:00+00:00",
        {
            "symbol": "BTCUSDTM",
            "strategy": "MeanReversion",
            "realized_pnl": -0.5,
            "pnl_decompose": {
                "gross_fill_pnl_model": -0.4,
                "fee_total": 0.1,
                "funding_total": 0.0,
            },
            "position": {
                "symbol": "BTCUSDTM",
                "strategy": "MeanReversion",
                "side": "sell",
                "entry_price": 200.0,
                "close_price": 200.5,
                "amount": 1.0,
                "timestamp": "2026-04-12T23:58:00+00:00",
                "close_timestamp": "2026-04-13T00:01:00+00:00",
                "realized_pnl": -0.5,
            },
        },
    )
    exchange_sync_row = (
        "2026-04-13T00:02:00+00:00",
        {
            "symbol": "LTCUSDTM",
            "strategy": "ExchangeSync",
            "realized_pnl": 2.0,
            "pnl_decompose": {
                "gross_fill_pnl_model": 2.1,
                "fee_total": 0.1,
                "funding_total": 0.0,
            },
            "position": {
                "symbol": "LTCUSDTM",
                "strategy": "ExchangeSync",
                "side": "buy",
                "entry_price": 50.0,
                "close_price": 52.0,
                "amount": 1.0,
                "timestamp": "2026-04-12T23:57:00+00:00",
                "close_timestamp": "2026-04-13T00:02:00+00:00",
                "realized_pnl": 2.0,
            },
        },
    )

    _write_source_db(src_a, [eth_row, eth_row, btc_row])
    _write_source_db(src_b, [exchange_sync_row])

    output_all = tmp_path / "tmp" / "alpha_history_all.db"
    report_all = module.build_history_db(
        output_path=output_all,
        glob_patterns=["tmp/controlled_kpi_*.db"],
        max_sources=10,
        max_per_source=50,
        max_total=100,
        min_abs_pnl=0.0,
        quality_filter=False,
        min_pair_trades=1,
        min_pair_winrate=0.0,
        min_pair_expectancy=-1.0,
        fallback_top_pairs=1,
        exclude_strategies=set(),
    )

    assert report_all["sources_scanned"] == 2
    assert report_all["sources_used"] == 2
    assert report_all["rows_scanned"] == 4
    assert report_all["rows_inserted"] == 3
    assert report_all["dedup_size"] == 3
    assert report_all["quality_filter"] is False
    assert report_all["pairs_total"] == 3
    assert report_all["pairs_selected"] == 3
    assert report_all["fallback_used"] is False
    assert len(report_all["pair_stats_top"]) == 3
    assert len(report_all["pair_side_stats_top"]) == 3

    with sqlite3.connect(output_all) as conn:
        inserted_rows = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    assert inserted_rows == 3

    output_quality = tmp_path / "tmp" / "alpha_history_quality.db"
    report_quality = module.build_history_db(
        output_path=output_quality,
        glob_patterns=["tmp/controlled_kpi_*.db"],
        max_sources=10,
        max_per_source=50,
        max_total=100,
        min_abs_pnl=0.0,
        quality_filter=True,
        min_pair_trades=5,
        min_pair_winrate=0.9,
        min_pair_expectancy=10.0,
        fallback_top_pairs=1,
        exclude_strategies={"exchangesync"},
    )

    assert report_quality["quality_filter"] is True
    assert report_quality["fallback_used"] is True
    assert report_quality["pairs_total"] == 2
    assert report_quality["pairs_selected"] == 1
    assert report_quality["pairs_rejected_per_rule"]["rejected_min_trades"] == 2
    assert len(report_quality["pair_stats_top"]) == 2
    assert len(report_quality["pair_side_stats_top"]) == 2

    with sqlite3.connect(output_quality) as conn:
        filtered_rows = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    assert filtered_rows == 1

    report_json_path = tmp_path / "tmp" / "alpha_history_report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_alpha_history_db.py",
            "--output",
            "tmp/alpha_history_cli.db",
            "--glob",
            "tmp/controlled_kpi_*.db",
            "--max-sources",
            "10",
            "--max-per-source",
            "50",
            "--max-total",
            "100",
            "--quality-filter",
            "--min-pair-trades",
            "5",
            "--min-pair-winrate",
            "0.9",
            "--min-pair-expectancy",
            "10.0",
            "--fallback-top-pairs",
            "1",
            "--report-json",
            "tmp/alpha_history_report.json",
            "--exclude-strategies",
            "exchangesync",
        ],
    )

    module.main()
    captured = capsys.readouterr().out

    assert "ALPHA_HISTORY_DB=" in captured
    assert "ALPHA_HISTORY_STATS" in captured
    assert "ALPHA_HISTORY_REPORT_JSON=" in captured
    assert report_json_path.exists()

    cli_report = json.loads(report_json_path.read_text(encoding="utf-8"))
    assert cli_report["rows_inserted"] == 1
    assert cli_report["fallback_used"] is True
