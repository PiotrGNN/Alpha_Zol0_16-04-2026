import importlib.util
import json
import sqlite3
from pathlib import Path


def _load_audit():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "edge_history_accumulation_root_cause.py"
    spec = importlib.util.spec_from_file_location("edge_history_accumulation_root_cause", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


audit = _load_audit()


def test_scan_timeline_no_close_before_terminal():
    events = [
        {"timestamp": "2026-03-28 01:00:00", "event": "entry_gate_decision_summary"},
        {"timestamp": "2026-03-28 01:00:01", "event": "entry_gate_decision_summary"},
        {"timestamp": "2026-03-28 01:00:02", "event": "position_close"},
    ]
    result = audit._scan_timeline(events)
    assert result["entry_count"] == 2
    assert result["position_close_count"] == 1
    assert result["history_write_path_found"] is True
    assert result["history_write_before_terminal_entries"] is False


def test_bucket_definition_is_stable():
    bucket = audit._bucket_definition_summary()
    assert bucket["primary_bucket"] == "symbol|strategy|side"
    assert bucket["fallback_bucket"] == "symbol|__ALL__|side"
    assert "entry_edge_fee_window" in bucket["window"]


def test_history_write_path_summary_mentions_close():
    summary = audit._history_write_path_summary()
    assert summary["event_source"] == "position_close"
    assert "trade_count" in " ".join(summary["increment_mechanics"])


def test_render_md_contains_required_sections():
    report = {
        "metadata": {
            "classification": "UPSTREAM_GATING_PREVENTS_HISTORY_ACCUMULATION",
            "symbols": ["BTCUSDTM", "ETHUSDTM"],
            "scenarios": ["baseline"],
        },
        "bucket_definition": audit._bucket_definition_summary(),
        "first_non_zero_trade_count_condition": {
            "condition": "a position_close event must occur before the terminal entry window ends",
        },
    }
    md = audit._render_md(
        {
            "metadata": report["metadata"],
            "bucket_definition": report["bucket_definition"],
            "first_non_zero_trade_count_condition": report["first_non_zero_trade_count_condition"],
            "aggregate": {"total_pockets": 0},
        }
    )
    assert "## Executive Summary" in md
    assert "## History Write Path" in md
    assert "## Final Classification" in md
    assert "UPSTREAM_GATING_PREVENTS_HISTORY_ACCUMULATION" in md


def _create_empty_logs_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "create table logs (id integer primary key, timestamp text, event text, details text)"
        )
        connection.commit()
    finally:
        connection.close()


def test_build_report_stable_keys(tmp_path):
    db_paths = [
        tmp_path / "controlled_kpi_before_20260328_010209.db",
        tmp_path / "controlled_kpi_before_20260328_010418.db",
        tmp_path / "controlled_kpi_before_20260328_011249.db",
    ]
    for db_path in db_paths:
        _create_empty_logs_db(db_path)

    terminal_paths_report = tmp_path / "terminal_paths.json"
    terminal_paths_report.write_text(
        json.dumps({"per_symbol": {}}),
        encoding="utf-8",
    )

    report = audit._build_report(
        ["BTCUSDTM", "ETHUSDTM"],
        ["baseline", "disable_net_target_guard", "disable_current_side"],
        db_paths,
        terminal_paths_report,
    )
    assert "metadata" in report
    assert "per_symbol" in report
    assert "aggregate" in report
    assert "history_write_path_found" in report
    assert "first_non_zero_trade_count_condition" in report
    assert report["metadata"]["classification"] in {
        "UPSTREAM_GATING_PREVENTS_HISTORY_ACCUMULATION",
        "INSUFFICIENT_EVIDENCE",
    }
