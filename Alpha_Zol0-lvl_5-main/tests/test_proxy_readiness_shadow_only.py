import importlib.util
import sqlite3
from pathlib import Path


def _load_shadow():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "proxy_readiness_shadow_only.py"
    spec = importlib.util.spec_from_file_location("proxy_readiness_shadow_only", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


shadow = _load_shadow()


def _empty_logs_db(tmp_path: Path) -> Path:
    path = tmp_path / "controlled_kpi_before_20260328_010209.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "create table logs (id integer primary key, timestamp text, event text, details text)"
        )
        connection.commit()
    finally:
        connection.close()
    return path


def test_shadow_ready_uses_only_existing_proxy_signals():
    entry = {
        "entry_live_edge": {"live_edge_proxy": 0.5},
        "entry_expected_edge_after_fee": 0.2,
        "entry_edge_over_fee": {
            "mean_edge_over_fee": 0.1,
            "mean_fee_total": 0.01,
            "mean_spread_slippage_proxy": 0.02,
        },
    }
    assert shadow._shadow_ready(entry) is True


def test_shadow_ready_false_without_proxy_signals():
    assert shadow._shadow_ready({}) is False


def test_build_report_has_separation_guarantees(tmp_path):
    report = shadow._build_report(db_paths=[_empty_logs_db(tmp_path)])
    assert report["separation_guarantees"]["realized_buckets_mutated"] is False
    assert report["separation_guarantees"]["admission_semantics_changed"] is False
    assert report["separation_guarantees"]["shadow_only_namespace"] is True


def test_report_contains_shadow_namespace_and_metrics(tmp_path):
    report = shadow._build_report(db_paths=[_empty_logs_db(tmp_path)])
    assert "shadow_design" in report
    assert "proxy_candidates" in report["shadow_design"]
    assert "per_symbol" in report
    assert "aggregate" in report
    assert "proxy_shadow_trade_count" in report["shadow_design"]["separation"]


def test_md_render_mentions_shadow_only(tmp_path):
    report = shadow._build_report(db_paths=[_empty_logs_db(tmp_path)])
    md = shadow._render_md(report)
    assert "## D. Shadow Design" in md
    assert "shadow-only" in md.lower()
    assert "## I. Final Verdict" in md
