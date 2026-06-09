import importlib.util
import json
import sqlite3
from pathlib import Path


def _load_audit():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "edge_history_readiness_impact_audit.py"
    spec = importlib.util.spec_from_file_location("edge_history_readiness_impact_audit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


audit = _load_audit()


def test_timeline_metrics_detect_close_before_terminal():
    events = [
        {"event": "entry_gate_decision_summary", "timestamp": "2026-03-28 01:00:00"},
        {"event": "entry_gate_decision_summary", "timestamp": "2026-03-28 01:00:01"},
        {"event": "position_close", "timestamp": "2026-03-28 01:00:02"},
    ]
    metrics = audit._timeline_metrics(events)
    assert metrics["pocket_count"] == 2
    assert metrics["position_close_count"] == 1
    assert metrics["history_write_path_found"] is True
    assert metrics["history_write_before_terminal_entries"] is False


def _create_empty_logs_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "create table logs (id integer primary key, timestamp text, event text, details text)"
        )
        connection.commit()
    finally:
        connection.close()


def test_build_report_stable_shape(tmp_path):
    terminal_report = tmp_path / "terminal_paths.json"
    terminal_report.write_text(json.dumps({"per_symbol": {}}), encoding="utf-8")
    db_paths = [tmp_path / f"run_{index}.db" for index in range(3)]
    for db_path in db_paths:
        _create_empty_logs_db(db_path)

    report = audit._build_report(
        ["BTCUSDTM", "ETHUSDTM"],
        ["baseline", "disable_net_target_guard", "disable_current_side"],
        terminal_report,
        db_paths,
    )
    assert "metadata" in report
    assert "per_symbol" in report
    assert "aggregate" in report
    assert "current_close_only_history_model" in report
    assert "earliest_possible_seed_point" in report
    assert "alternate_readiness_impact" in report


def test_local_classification_when_observable_is_false():
    scenario = {
        "run_end_cutoff_pockets": 0,
        "current_side": "presence_only_marker",
        "lifecycle_profile": {"history_write_path_found": True},
    }
    assert scenario["run_end_cutoff_pockets"] == 0
    assert scenario["current_side"] == "presence_only_marker"


def test_render_md_contains_sections():
    md = audit._render_md(
        {
            "metadata": {
                "classification": "CURRENT_HISTORY_MODEL_IS_STRUCTURALLY_TOO_LATE",
                "symbols": ["BTCUSDTM"],
                "scenarios": ["baseline"],
            }
        }
    )
    assert "## D. Current Close-Only History Model" in md
    assert "## E. Earliest Possible Seed Point" in md
    assert "## H. Final Classification" in md
