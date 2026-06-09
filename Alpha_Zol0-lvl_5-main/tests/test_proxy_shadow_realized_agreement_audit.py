import importlib.util
import json
import sqlite3
from pathlib import Path


def _load_audit():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "proxy_shadow_realized_agreement_audit.py"
    spec = importlib.util.spec_from_file_location("proxy_shadow_realized_agreement_audit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


audit = _load_audit()


def _create_db(path: Path, symbol: str, realized_pnl: float) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "create table logs (id integer primary key, timestamp text, event text, details text)"
        )
        connection.execute(
            "insert into logs(timestamp, event, details) values (?, ?, ?)",
            (
                "2026-03-28T01:00:00+00:00",
                "realized_outcome_per_side",
                json.dumps({"symbol": symbol, "side": "buy", "realized_net_pnl": realized_pnl}),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _fixture_paths(tmp_path: Path):
    shadow_path = tmp_path / "shadow.json"
    shadow_path.write_text(
        json.dumps(
            {
                "per_symbol": {
                    "BTCUSDTM": {
                        "baseline": {
                            "rows": 1,
                            "proxy_shadow_trade_count": 1,
                            "proxy_shadow_history_ready": True,
                            "proxy_shadow_edge_mean": 1.0,
                            "earlier_observability_gain": True,
                            "shadow_rows": [{"shadow_ready": True}],
                        },
                        "disable_current_side": {
                            "rows": 1,
                            "proxy_shadow_trade_count": 1,
                            "proxy_shadow_history_ready": True,
                            "proxy_shadow_edge_mean": 1.0,
                            "earlier_observability_gain": True,
                            "shadow_rows": [{"shadow_ready": True}],
                        },
                    },
                    "ETHUSDTM": {
                        "disable_current_side": {
                            "rows": 1,
                            "proxy_shadow_trade_count": 1,
                            "proxy_shadow_history_ready": True,
                            "proxy_shadow_edge_mean": 1.0,
                            "earlier_observability_gain": True,
                            "shadow_rows": [{"shadow_ready": True}],
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    db_paths = [
        tmp_path / "controlled_kpi_before_20260328_010209.db",
        tmp_path / "controlled_kpi_before_20260328_010418.db",
        tmp_path / "controlled_kpi_before_20260328_011249.db",
    ]
    _create_db(db_paths[0], "BTCUSDTM", -0.1)
    _create_db(db_paths[1], "BTCUSDTM", -0.2)
    _create_db(db_paths[2], "ETHUSDTM", -0.3)
    return shadow_path, db_paths


def test_realized_summary_detects_negative_outcome(tmp_path):
    _, db_paths = _fixture_paths(tmp_path)
    summary = audit._realized_summary(audit._load_logs(db_paths[1]))
    assert summary["realized_rows"] >= 1
    assert summary["realized_sign"] == "negative"


def test_proxy_summary_uses_shadow_only_fields(tmp_path):
    shadow_path, _ = _fixture_paths(tmp_path)
    summary = audit._proxy_shadow_summary(audit._load_json(shadow_path), "BTCUSDTM", "baseline")
    assert summary["proxy_shadow_trade_count"] >= 0
    assert summary["proxy_shadow_history_ready"] is True


def test_build_report_has_stable_shape(tmp_path):
    shadow_path, db_paths = _fixture_paths(tmp_path)
    report = audit._build_report(shadow_path, db_paths)
    assert "metadata" in report
    assert "agreement_metrics" in report
    assert "false_optimism_definition" in report
    assert "why_count_zero" in report
    assert "lead_time_findings" in report
    assert "risk_review" in report
    assert report["final_classification"] in {
        "STRONG_DIRECTIONAL_AGREEMENT",
        "WEAK_BUT_USEFUL_AGREEMENT",
        "NOISY_PROXY_WITH_LIMITED_SIGNAL",
        "MISLEADING_PROXY",
        "INSUFFICIENT_OVERLAP",
    }


def test_md_mentions_false_optimism(tmp_path):
    shadow_path, db_paths = _fixture_paths(tmp_path)
    md = audit._render_md(audit._build_report(shadow_path, db_paths))
    assert "## D. Matching Method" in md
    assert "false optimism" in md.lower()
    assert "False Optimism Definition" in md
    assert "Why count =" in md
    assert "## I. Final Classification" in md


def test_false_optimism_definition_is_pair_level(tmp_path):
    shadow_path, db_paths = _fixture_paths(tmp_path)
    report = audit._build_report(shadow_path, db_paths)
    definition = report["false_optimism_definition"]
    assert "pair_level_rule" in definition
    assert definition["count_scope"] == "matched realized pairs only"
    assert "proxy-positive" in report["why_count_zero"] or "proxy-positive" in definition["pair_level_rule"]


def test_scope_clarification_mentions_corpus_level(tmp_path):
    shadow_path, db_paths = _fixture_paths(tmp_path)
    report = audit._build_report(shadow_path, db_paths)
    assert "scope_clarification" in report
    assert "corpus_level_proxy_positivity" in report["scope_clarification"]
