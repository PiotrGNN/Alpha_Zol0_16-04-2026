import importlib.util
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "generate_fresh_positive_corpus.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "generate_fresh_positive_corpus", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_position_close_db(path: Path, entries: list[dict]):
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
        for item in entries:
            cur.execute(
                "INSERT INTO logs(timestamp, event, details) VALUES(?, 'position_close', ?)",
                (item["timestamp"], json.dumps(item["details"])),
            )
        conn.commit()
    finally:
        conn.close()


def _entry(
    *,
    symbol: str,
    strategy: str,
    side: str,
    realized_pnl: float,
    entry_ts: str,
    close_ts: str,
):
    return {
        "timestamp": close_ts,
        "details": {
            "symbol": symbol,
            "strategy": strategy,
            "side": side,
            "realized_pnl": realized_pnl,
            "position": {
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "entry_price": 100.0,
                "close_price": 101.0,
                "amount": 1.0,
                "timestamp": entry_ts,
                "close_timestamp": close_ts,
            },
        },
    }


def test_collect_side_stats_and_allowlist_filters_auto_test(tmp_path):
    module = _load_module()
    db_path = tmp_path / "tmp" / "run_a.db"
    _write_position_close_db(
        db_path,
        [
            _entry(
                symbol="ETHUSDTM",
                strategy="Momentum",
                side="buy",
                realized_pnl=0.004,
                entry_ts="e1",
                close_ts="2026-04-21T00:00:01+00:00",
            ),
            _entry(
                symbol="ETHUSDTM",
                strategy="Momentum",
                side="buy",
                realized_pnl=0.002,
                entry_ts="e2",
                close_ts="2026-04-21T00:00:02+00:00",
            ),
            _entry(
                symbol="XRPUSDTM",
                strategy="TrendFollowing",
                side="sell",
                realized_pnl=-0.001,
                entry_ts="e3",
                close_ts="2026-04-21T00:00:03+00:00",
            ),
            _entry(
                symbol="BTCUSDTM",
                strategy="auto_test",
                side="buy",
                realized_pnl=0.8,
                entry_ts="e4",
                close_ts="2026-04-21T00:00:04+00:00",
            ),
        ],
    )

    stats, meta = module._collect_pair_side_stats_from_dbs(
        [db_path],
        exclude_strategies={"auto_test"},
    )
    ranked_rows, allowlist = module._derive_positive_side_rows(
        stats,
        min_side_trades=2,
        min_side_winrate=0.45,
        min_side_expectancy=0.0,
    )

    assert meta["sources_scanned"] == 1
    assert meta["dedup_rows"] == 3
    assert ("BTCUSDTM", "auto_test", "buy") not in stats
    assert ("ETHUSDTM", "Momentum", "buy") in stats
    assert "ETHUSDTM:MOMENTUM:buy" in allowlist
    assert "XRPUSDTM:TRENDFOLLOWING:sell" not in allowlist
    assert ranked_rows[0]["token"] == "ETHUSDTM:MOMENTUM:buy"


def test_write_positive_corpus_db_keeps_only_allowlisted_tokens(tmp_path):
    module = _load_module()
    db_a = tmp_path / "tmp" / "run_a.db"
    db_b = tmp_path / "tmp" / "run_b.db"

    duplicate = _entry(
        symbol="ETHUSDTM",
        strategy="Momentum",
        side="buy",
        realized_pnl=0.003,
        entry_ts="dup_e",
        close_ts="2026-04-21T00:01:01+00:00",
    )
    _write_position_close_db(
        db_a,
        [
            duplicate,
            _entry(
                symbol="ADAUSDTM",
                strategy="TrendFollowing",
                side="sell",
                realized_pnl=-0.001,
                entry_ts="e1",
                close_ts="2026-04-21T00:01:02+00:00",
            ),
        ],
    )
    _write_position_close_db(
        db_b,
        [
            duplicate,
            _entry(
                symbol="BNBUSDTM",
                strategy="TrendFollowing",
                side="buy",
                realized_pnl=0.002,
                entry_ts="e2",
                close_ts="2026-04-21T00:01:03+00:00",
            ),
        ],
    )

    out_db = tmp_path / "tmp" / "positive_corpus.db"
    summary = module._write_positive_corpus_db(
        output_db_path=out_db,
        source_db_paths=[db_a, db_b],
        allowlist_tokens={"ETHUSDTM:MOMENTUM:buy"},
        exclude_strategies={"auto_test"},
    )

    assert summary["rows_inserted"] == 1
    assert summary["tokens_inserted"] == [("ETHUSDTM:MOMENTUM:buy", 1)]

    conn = sqlite3.connect(out_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM logs WHERE event='position_close'")
        assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def test_main_passes_when_target_reached(monkeypatch, tmp_path):
    module = _load_module()
    monkeypatch.setattr(module, "WORKDIR", tmp_path)
    monkeypatch.setattr(module, "TMP_DIR", tmp_path / "tmp")
    monkeypatch.setattr(module, "RESULTS_DIR", tmp_path / "results")

    run_db = tmp_path / "tmp" / "controlled_kpi_after_fake.db"
    _write_position_close_db(
        run_db,
        [
            _entry(
                symbol="XRPUSDTM",
                strategy="TrendFollowing",
                side="sell",
                realized_pnl=0.005,
                entry_ts="e1",
                close_ts="2026-04-21T00:02:01+00:00",
            )
        ],
    )

    def _fake_run_single_after(_args, run_index):
        return {
            "run_index": run_index,
            "returncode": 0,
            "report_json_path": "results/fake.json",
            "db_path": "tmp/controlled_kpi_after_fake.db",
            "trade_count": 1,
            "net_pnl": 0.005,
            "winrate": 1.0,
            "shutdown_classification": "close_flush_done_pending_positions_zero",
        }

    monkeypatch.setattr(module, "_run_single_after", _fake_run_single_after)

    rc = module.main(
        [
            "--max-runs",
            "1",
            "--min-side-trades",
            "1",
            "--min-positive-buckets",
            "1",
            "--min-positive-trades-total",
            "1",
            "--output-db",
            "tmp/out_positive.db",
            "--output-json",
            "tmp/out_positive_report.json",
            "--no-alpha-bootstrap-auto-refresh",
        ]
    )

    assert rc == 0
    report = json.loads(
        (tmp_path / "tmp" / "out_positive_report.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "PASS"
    assert report["target_reached"] is True
    assert report["positive_side_allowlist"] == ["XRPUSDTM:TRENDFOLLOWING:sell"]
    assert report["output_corpus"]["rows_inserted"] == 1
    strict_status = json.loads(
        (
            tmp_path
            / "analysis"
            / "zol0_strict_bucket_gate_fresh_corpus_status_current.json"
        ).read_text(encoding="utf-8")
    )
    assert strict_status["status"] == "PASS"
    assert (
        strict_status["pass_fail_criteria"]["accepted_20_of_20_after_runs"] is True
    )
    assert strict_status["strict_gate_inventory"]["positive_bucket_count"] == 1
