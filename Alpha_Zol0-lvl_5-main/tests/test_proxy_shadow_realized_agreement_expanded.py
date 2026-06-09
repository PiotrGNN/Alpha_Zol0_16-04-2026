import importlib.util
import json
import sqlite3
from pathlib import Path


def _load_audit():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "proxy_shadow_realized_agreement_expanded.py"
    spec = importlib.util.spec_from_file_location("proxy_shadow_realized_agreement_expanded", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


audit = _load_audit()


def _fixture(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    db_path = tmp_path / "controlled_kpi_fixture.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "create table logs (id integer primary key, timestamp text, event text, details text)"
        )
        connection.execute(
            "insert into logs(timestamp, event, details) values (?, ?, ?)",
            (
                "2026-03-28T01:00:00+00:00",
                "entry_gate_decision_summary",
                json.dumps(
                    {
                        "ts": "2026-03-28T01:00:00+00:00",
                        "symbol": "BTCUSDTM",
                        "side": "buy",
                        "entry_live_edge": {"live_edge_proxy": 0.25},
                        "entry_edge_over_fee": {
                            "strategy": "fixture_strategy",
                            "bucket_key_primary": "BTCUSDTM|fixture_strategy|buy",
                        },
                    }
                ),
            ),
        )
        connection.execute(
            "insert into logs(timestamp, event, details) values (?, ?, ?)",
            (
                "2026-03-28T01:01:00+00:00",
                "realized_outcome_per_side",
                json.dumps(
                    {
                        "ts": "2026-03-28T01:01:00+00:00",
                        "symbol": "BTCUSDTM",
                        "side": "buy",
                        "main_strategy": "fixture_strategy",
                        "realized_net_pnl": -0.10,
                    }
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    controlled = {
        "run_id": "fixture",
        "before": {
            "variant": "before",
            "diagnostic_env_flags": {"DIAGNOSTIC_MODE": "0"},
            "db_path": str(db_path),
            "trade_count": 1,
            "net_pnl": -0.10,
            "decisions_count": 1,
            "started_at_utc": "2026-03-28T01:00:00+00:00",
            "ended_at_utc": "2026-03-28T01:01:00+00:00",
        },
    }
    (results_dir / "controlled_kpi_fixture.json").write_text(
        json.dumps(controlled), encoding="utf-8"
    )
    small_reference = tmp_path / "small_reference.json"
    small_reference.write_text(json.dumps({}), encoding="utf-8")
    return results_dir, small_reference


def _report(tmp_path: Path):
    results_dir, small_reference = _fixture(tmp_path)
    return audit._build_report(
        results_dir=results_dir,
        scenarios=("baseline", "disable_current_side", "disable_net_target_guard"),
        limit_per_scenario=2,
        small_sample_reference=small_reference,
    )


def test_scenario_from_env_maps_expected_flags():
    assert audit._scenario_from_env({"DIAGNOSTIC_MODE": "0"}) == "baseline"
    assert audit._scenario_from_env(
        {"DIAGNOSTIC_MODE": "1", "DIAG_DISABLE_NET_TARGET_GUARD": "1"}
    ) == "disable_net_target_guard"
    assert audit._scenario_from_env(
        {"DIAGNOSTIC_MODE": "1", "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION": "1"}
    ) == "disable_current_side"


def test_pairwise_rank_agreement_handles_ties():
    pairs = [
        {"rank_proxy_score": 1.0, "rank_realized_score": 1.0},
        {"rank_proxy_score": 2.0, "rank_realized_score": 2.0},
        {"rank_proxy_score": 3.0, "rank_realized_score": 2.0},
    ]
    summary = audit._pairwise_rank_agreement(pairs)
    assert summary["concordant_pairs"] >= 1
    assert "rank_agreement_rate" in summary


def test_build_report_has_stable_shape(tmp_path):
    report = _report(tmp_path)
    assert "metadata" in report
    assert "agreement_metrics" in report
    assert "lead_time_analysis" in report
    assert "false_optimism_definition" in report
    assert "stability_vs_small_sample" in report
    assert report["final_classification"] in {
        "STRONG_DIRECTIONAL_AGREEMENT",
        "WEAK_BUT_USEFUL_AGREEMENT",
        "NOISY_PROXY_WITH_LIMITED_SIGNAL",
        "MISLEADING_PROXY",
        "INSUFFICIENT_EVIDENCE",
    }


def test_md_mentions_required_sections(tmp_path):
    md = audit._render_md(_report(tmp_path))
    for section in [
        "## A. Executive Summary",
        "## B. Scope",
        "## C. Data Expansion Method",
        "## D. Matching Method",
        "## E. Agreement Metrics (Expanded)",
        "## F. Lead-Time Analysis",
        "## G. False Optimism / Pessimism",
        "## H. Stability vs Small Sample",
        "## I. Final Classification",
    ]:
        assert section in md
    assert "False Optimism / Pessimism" in md


def test_expanded_report_contains_pair_fields(tmp_path):
    report = _report(tmp_path)
    assert report["agreement_pairs"]
    pair = report["agreement_pairs"][0]
    for key in [
        "symbol",
        "side",
        "bucket_key",
        "strategy_key",
        "realized_net_pnl",
        "directional_agreement",
        "false_optimism",
        "false_pessimism",
        "lead_time_sec",
    ]:
        assert key in pair
