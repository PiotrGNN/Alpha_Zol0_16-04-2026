import csv
import json
import os
from pathlib import Path

import pytest

from analysis.fl_impact_runner import (
    build_fl_decision_snapshots,
    run_fl_impact_analysis,
    summarize_fl_telemetry_impact,
    summarize_fl_telemetry,
    summarize_fl_telemetry_breakdown,
)


def write_tmp_decision_csv(path: Path):
    rows = [
        (
            "2026-03-26T12:00:00+00:00",
            "buy",
            {
                "entry_decision": "buy",
                "shadow_action": "buy",
                "entry_edge_over_fee": {
                    "mean_edge_over_fee": 1.0,
                    "shadow_edge_after_execution_cost": 1.1,
                },
            },
        ),
        (
            "2026-03-26T12:01:00+00:00",
            "hold",
            {
                "entry_decision": "hold",
                "shadow_action": "sell",
                "entry_edge_over_fee": {
                    "mean_edge_over_fee": 0.5,
                    "shadow_edge_after_execution_cost": 0.75,
                },
            },
        ),
        (
            "2026-03-26T12:02:00+00:00",
            "sell",
            {
                "entry_decision": "sell",
                "shadow_action": "sell",
                "entry_edge_over_fee": {
                    "mean_edge_over_fee": 0.2,
                    "shadow_edge_after_execution_cost": 0.1,
                },
            },
        ),
    ]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for ts, decision, payload in rows:
            writer.writerow([ts, decision, json.dumps(payload)])


def test_build_fl_decision_snapshots_runtime_margin_reconstruction():
    decision_rows = [
        (
            "2026-03-26T12:00:00+00:00",
            "sell",
            {
                "entry_decision_raw": "sell",
                "entry_decision_final": "buy",
                "entry_live_edge": {"threshold": 0.0008},
                "current_margin_to_threshold": 0.0012,
                "shadow_margin_to_threshold": -0.0003,
            },
        )
    ]

    snapshots = build_fl_decision_snapshots(decision_rows)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.decision_before == "sell"
    assert snapshot.decision_after == "buy"
    assert snapshot.edge_before == pytest.approx(0.0020)
    assert snapshot.edge_after == pytest.approx(0.0005)
    assert snapshot.edge_delta == pytest.approx(-0.0015)


def test_build_fl_decision_snapshots_live_proxy_threshold_fallback():
    decision_rows = [
        (
            "2026-03-26T12:01:00+00:00",
            "hold",
            {
                "entry_decision": "hold",
                "shadow_action": "allow",
                "entry_live_edge": {
                    "threshold": 0.0008,
                    "live_edge_proxy": 0.0230,
                },
            },
        )
    ]

    snapshots = build_fl_decision_snapshots(decision_rows)
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.decision_before == "hold"
    assert snapshot.decision_after == "allow"
    assert snapshot.edge_before == pytest.approx(0.0008)
    assert snapshot.edge_after == pytest.approx(0.0230)


def test_summarize_fl_telemetry_counts_override_fields():
    rows = [
        (
            "2026-03-26T12:00:00+00:00",
            "buy",
            {
                "fl_trend_hint": {"applied": True},
                "fl_trend_override_applied": True,
                "fl_trend_override_direction": "UP",
                "fl_trend_override_count_symbol": 2,
            },
        ),
        (
            "2026-03-26T12:01:00+00:00",
            "sell",
            {
                "fl_trend_hint": {"applied": True},
                "fl_trend_override_applied": True,
                "fl_trend_override_direction": "DOWN",
                "fl_trend_override_count_symbol": 5,
            },
        ),
        (
            "2026-03-26T12:02:00+00:00",
            "hold",
            {
                "entry_decision": "hold",
            },
        ),
    ]

    telemetry = summarize_fl_telemetry(rows)

    assert telemetry["rows_with_fl_trend_hint"] == 2
    assert telemetry["override_applied_count"] == 2
    assert telemetry["override_up_count"] == 1
    assert telemetry["override_down_count"] == 1
    assert telemetry["max_override_count_symbol"] == 5


def test_summarize_fl_telemetry_breakdown_counts_by_direction_and_symbol():
    rows = [
        (
            "2026-03-26T12:00:00+00:00",
            "buy",
            {
                "symbol": "BTC-USDT",
                "fl_trend_override_applied": True,
                "fl_trend_override_direction": "UP",
            },
        ),
        (
            "2026-03-26T12:01:00+00:00",
            "sell",
            {
                "symbol": "ETH-USDT",
                "fl_trend_override_applied": True,
                "fl_trend_override_direction": "DOWN",
            },
        ),
        (
            "2026-03-26T12:02:00+00:00",
            "buy",
            {
                "symbol": "BTC-USDT",
                "fl_trend_override_applied": True,
                "fl_trend_override_direction": "UP",
            },
        ),
        (
            "2026-03-26T12:03:00+00:00",
            "hold",
            {
                "symbol": "ETH-USDT",
                "fl_trend_override_applied": False,
                "fl_trend_override_direction": "DOWN",
            },
        ),
    ]

    breakdown = summarize_fl_telemetry_breakdown(rows)

    assert breakdown["override_counts_by_direction"] == {"DOWN": 1, "UP": 2}
    assert breakdown["override_counts_by_symbol"] == {"BTC-USDT": 2, "ETH-USDT": 1}
    assert breakdown["override_share_by_symbol"]["BTC-USDT"] == pytest.approx(
        2.0 / 3.0
    )
    assert breakdown["override_share_by_symbol"]["ETH-USDT"] == pytest.approx(
        1.0 / 3.0
    )


def test_summarize_fl_telemetry_breakdown_normalizes_unknown_direction_and_symbol():
    rows = [
        (
            "2026-03-26T12:00:00+00:00",
            "buy",
            {
                "fl_trend_override_applied": True,
                "fl_trend_override_direction": "SIDEWAYS",
            },
        ),
        (
            "2026-03-26T12:01:00+00:00",
            "sell",
            {
                "symbol": "btc-usdt",
                "fl_trend_override_applied": True,
                "fl_trend_override_direction": None,
            },
        ),
        (
            "2026-03-26T12:02:00+00:00",
            "buy",
            {
                "symbol": "btc-usdt",
                "fl_trend_override_applied": True,
                "fl_trend_override_direction": "up",
            },
        ),
    ]

    breakdown = summarize_fl_telemetry_breakdown(rows)

    assert breakdown["override_counts_by_direction"] == {"UNKNOWN": 2, "UP": 1}
    assert breakdown["override_counts_by_symbol"] == {"BTC-USDT": 2, "UNKNOWN": 1}
    assert breakdown["override_share_by_symbol"]["BTC-USDT"] == pytest.approx(
        2.0 / 3.0
    )
    assert breakdown["override_share_by_symbol"]["UNKNOWN"] == pytest.approx(
        1.0 / 3.0
    )


def test_summarize_fl_telemetry_impact_relates_override_presence_to_decision_changes():
    rows = [
        (
            "2026-03-26T12:00:00+00:00",
            "buy",
            {
                "symbol": "BTC-USDT",
                "fl_trend_override_applied": True,
                "fl_trend_override_direction": "UP",
                "entry_decision_raw": "buy",
                "entry_decision_final": "sell",
                "entry_edge_over_fee": {
                    "mean_edge_over_fee": 0.5,
                    "shadow_edge_after_execution_cost": 0.8,
                },
            },
        ),
        (
            "2026-03-26T12:01:00+00:00",
            "sell",
            {
                "symbol": "ETH-USDT",
                "fl_trend_override_applied": True,
                "fl_trend_override_direction": "DOWN",
                "entry_decision_raw": "sell",
                "entry_decision_final": "sell",
                "entry_edge_over_fee": {
                    "mean_edge_over_fee": 0.4,
                    "shadow_edge_after_execution_cost": 0.2,
                },
            },
        ),
        (
            "2026-03-26T12:02:00+00:00",
            "hold",
            {
                "symbol": "SOL-USDT",
                "fl_trend_override_applied": False,
                "entry_decision_raw": "hold",
                "entry_decision_final": "buy",
                "entry_edge_over_fee": {
                    "mean_edge_over_fee": 0.1,
                    "shadow_edge_after_execution_cost": 0.3,
                },
            },
        ),
        (
            "2026-03-26T12:03:00+00:00",
            "hold",
            {
                "symbol": "XRP-USDT",
                "fl_trend_override_applied": False,
                "entry_decision_raw": "hold",
                "entry_decision_final": "hold",
                "entry_edge_over_fee": {
                    "mean_edge_over_fee": 0.2,
                    "shadow_edge_after_execution_cost": 0.2,
                },
            },
        ),
    ]

    summary = summarize_fl_telemetry_impact(rows)

    assert summary["total_rows_analyzed"] == 4
    assert summary["override_applied_share_all_rows"] == pytest.approx(0.5)
    assert summary["dominant_override_direction"] == "TIED"
    assert summary["top_override_symbols"] == [
        {"symbol": "BTC-USDT", "count": 1, "share": 0.5},
        {"symbol": "ETH-USDT", "count": 1, "share": 0.5},
    ]
    assert summary["changed_decisions_total"] == 2
    assert summary["override_rows_with_decision_change"] == 1
    assert summary["override_rows_with_decision_change_share"] == pytest.approx(0.5)
    assert summary["changed_decisions_with_override_share"] == pytest.approx(0.5)
    assert summary["avg_edge_delta_override_rows"] == pytest.approx(0.05)


def test_run_fl_impact_analysis_writes_reports(tmp_path: Path):
    source_csv = tmp_path / "decision_log.csv"
    write_tmp_decision_csv(source_csv)

    run_id = "test-run"
    result = run_fl_impact_analysis(source_path=source_csv, run_id=run_id)

    assert result["run_id"] == run_id
    json_path = Path(result["result_json_path"])
    md_path = Path(result["summary_md_path"])

    assert json_path.exists()
    assert md_path.exists()
    assert result["snapshot_count"] == 3

    metrics = result["metrics"]
    assert metrics["total_decisions"] == 3
    assert metrics["changed_decisions"] == 1
    assert "percent_changed" in metrics
    assert "avg_edge_delta" in metrics
    assert "positive_impact_count" in metrics
    assert "negative_impact_count" in metrics
    assert "neutral_impact_count" in metrics
    assert "go_no_go" in metrics
    assert "fl_telemetry" in result

    summary_text = md_path.read_text(encoding="utf-8")
    assert (
        "total decisions" in summary_text.lower()
        or "total_decisions" in summary_text
    )
    assert (
        "changed decisions" in summary_text.lower()
        or "changed_decisions" in summary_text
    )
    assert "go/no-go" in summary_text.lower() or "go_no_go" in summary_text.lower()
    assert "evidence summary" in summary_text.lower()

    json_text = json_path.read_text(encoding="utf-8")
    json_data = json.loads(json_text)
    assert "audit_evidence" in json_data
    assert "top_positive_impacts" in json_data["audit_evidence"]
    assert "top_negative_impacts" in json_data["audit_evidence"]
    assert "fl_telemetry" in json_data
    assert json_data["fl_telemetry"] == result["fl_telemetry"]
    assert "fl_telemetry_breakdown" in json_data
    assert json_data["fl_telemetry_breakdown"] == result["fl_telemetry_breakdown"]
    assert "fl_telemetry_summary" in json_data
    assert json_data["fl_telemetry_summary"] == {
        "override_applied_share": 0.0,
        "override_up_share": 0.0,
        "override_down_share": 0.0,
        "max_override_count_symbol": 0,
    }
    assert "fl_telemetry_impact_summary" in json_data
    assert (
        json_data["fl_telemetry_impact_summary"]
        == result["fl_telemetry_impact_summary"]
    )
    assert json_data["fl_telemetry_impact_summary"] == {
        "avg_edge_delta_override_rows": 0.0,
        "changed_decisions_total": 1,
        "changed_decisions_with_override_share": 0.0,
        "dominant_override_direction": "NONE",
        "override_applied_share_all_rows": 0.0,
        "override_rows_with_decision_change": 0,
        "override_rows_with_decision_change_share": 0.0,
        "top_override_symbols": [],
        "total_rows_analyzed": 3,
    }


def test_run_fl_impact_analysis_fl_telemetry_summary_nonzero(tmp_path: Path):
    source_csv = tmp_path / "decision_log.csv"

    rows = [
        (
            "2026-03-26T12:00:00+00:00",
            "buy",
            {
                "entry_decision": "buy",
                "shadow_action": "buy",
                "entry_edge_over_fee": {
                    "mean_edge_over_fee": 1.0,
                    "shadow_edge_after_execution_cost": 1.2,
                },
                "fl_trend_hint": {"applied": True},
                "fl_trend_override_applied": True,
                "fl_trend_override_direction": "UP",
                "fl_trend_override_count_symbol": 2,
            },
        ),
        (
            "2026-03-26T12:01:00+00:00",
            "sell",
            {
                "entry_decision": "sell",
                "shadow_action": "sell",
                "entry_edge_over_fee": {
                    "mean_edge_over_fee": 0.4,
                    "shadow_edge_after_execution_cost": 0.1,
                },
                "fl_trend_hint": {"applied": False},
                "fl_trend_override_applied": False,
                "fl_trend_override_direction": None,
                "fl_trend_override_count_symbol": 2,
            },
        ),
    ]

    with source_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for ts, decision, payload in rows:
            writer.writerow([ts, decision, json.dumps(payload)])

    result = run_fl_impact_analysis(
        source_path=source_csv,
        run_id="test-run-telemetry-summary",
    )

    json_text = Path(result["result_json_path"]).read_text(encoding="utf-8")
    json_data = json.loads(json_text)
    summary = json_data.get("fl_telemetry_summary") or {}

    assert summary["override_applied_share"] == pytest.approx(0.5)
    assert summary["override_up_share"] == pytest.approx(1.0)
    assert summary["override_down_share"] == pytest.approx(0.0)
    assert summary["max_override_count_symbol"] == 2


def test_run_fl_impact_analysis_skips_invalid_json(tmp_path: Path):
    source_csv = tmp_path / "decision_log.csv"

    # One valid row plus one invalid JSON payload row
    rows = [
        (
            "2026-03-26T12:00:00+00:00",
            "buy",
            {
                "entry_decision": "buy",
                "shadow_action": "buy",
                "entry_edge_over_fee": {
                    "mean_edge_over_fee": 1.0,
                    "shadow_edge_after_execution_cost": 1.1,
                },
            },
        ),
        ("2026-03-26T12:01:00+00:00", "hold", "not-a-json"),
    ]

    with source_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for ts, decision, payload in rows:
            writer.writerow([ts, decision, json.dumps(payload)])

    result = run_fl_impact_analysis(
        source_path=source_csv,
        run_id="test-run-skip-invalid-json",
    )

    assert result["total_decisions"] == 1
    assert result["skipped_rows"] >= 1
    assert result["skipped_details"].get("skipped_invalid_json", 0) == 1


def test_run_fl_impact_analysis_classifies_non_decision_event_rows(tmp_path: Path):
    source_csv = tmp_path / "decision_log.csv"

    rows = [
        (
            "2026-03-26T12:00:00+00:00",
            "buy",
            {
                "entry_decision": "buy",
                "shadow_action": "buy",
                "entry_edge_over_fee": {
                    "mean_edge_over_fee": 1.0,
                    "shadow_edge_after_execution_cost": 1.1,
                },
            },
        ),
        (
            "2026-03-26T12:01:00+00:00",
            "strategy_switch",
            "Momentum->TrendFollowing",
        ),
        (
            "2026-03-26T12:02:00+00:00",
            "risk_limit",
            "max_drawdown_triggered",
        ),
    ]

    with source_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for ts, decision, payload in rows:
            if isinstance(payload, dict):
                writer.writerow([ts, decision, json.dumps(payload)])
            else:
                writer.writerow([ts, decision, payload])

    result = run_fl_impact_analysis(
        source_path=source_csv,
        run_id="test-run-non-decision-events",
    )

    assert result["total_decisions"] == 1
    assert result["skipped_rows"] == 2
    assert result["skipped_details"].get("skipped_non_decision_event", 0) == 2
    assert result["skipped_details"].get("skipped_invalid_json", 0) == 0


def test_run_fl_impact_analysis_deterministic_hash(tmp_path: Path):
    source_csv = tmp_path / "decision_log.csv"
    write_tmp_decision_csv(source_csv)

    result1 = run_fl_impact_analysis(
        source_path=source_csv,
        run_id="test-run-determinism",
    )
    hash1 = result1["json_sha256"]

    result2 = run_fl_impact_analysis(
        source_path=source_csv,
        run_id="test-run-determinism",
    )
    hash2 = result2["json_sha256"]

    assert hash1 == hash2


def test_run_fl_impact_analysis_profile_fields(tmp_path: Path):
    source_csv = tmp_path / "decision_log.csv"
    write_tmp_decision_csv(source_csv)

    result = run_fl_impact_analysis(
        source_path=source_csv,
        run_id="test-run-profile",
        profile=True,
    )

    assert "total_time_seconds" in result
    assert result["total_time_seconds"] >= 0
    assert "write_time_seconds" in result
    assert result["write_time_seconds"] >= 0
    assert "perf" in result
    assert "load_time_seconds" in result["perf"]
    assert "snapshot_build_time_seconds" in result["perf"]
    assert "evaluation_time_seconds" in result["perf"]


@pytest.mark.slow
@pytest.mark.manual
@pytest.mark.skipif(
    os.getenv("RUN_FL_IMPACT_FULL_CORPUS") != "1",
    reason=(
        "Full-corpus FL impact run is opt-in; set "
        "RUN_FL_IMPACT_FULL_CORPUS=1 to execute."
    ),
)
def test_run_fl_impact_analysis_full_corpus(tmp_path: Path):
    # Explicit opt-in only: verifies the full corpus completes and yields a GO result.
    from analysis.fl_impact_runner import run_fl_impact_analysis

    result = run_fl_impact_analysis(
        source_path=Path("autopsy/decision_log.csv"),
        run_id="full-corpus-test",
        profile=True,
    )

    assert result["total_decisions"] > 0
    assert result["snapshot_count"] == result["total_decisions"]
    assert result["metrics"]["total_decisions"] == result["total_decisions"]

    json_path = Path(result["result_json_path"])
    md_path = Path(result["summary_md_path"])
    assert json_path.exists()
    assert md_path.exists()
    assert result["metrics"]["go_no_go"] in {"GO", "NO-GO"}


def test_run_fl_impact_analysis_custom_report_dir(tmp_path: Path):
    source_csv = tmp_path / "decision_log.csv"
    write_tmp_decision_csv(source_csv)

    report_dir = tmp_path / "fl_reports"
    result = run_fl_impact_analysis(
        source_path=source_csv,
        run_id="test-run-report-dir",
        report_dir=report_dir,
    )

    json_path = Path(result["result_json_path"])
    md_path = Path(result["summary_md_path"])
    assert report_dir in json_path.parents
    assert report_dir in md_path.parents
    assert json_path.exists()
    assert md_path.exists()


def test_run_fl_impact_analysis_fail_when_exists(tmp_path: Path):
    source_csv = tmp_path / "decision_log.csv"
    write_tmp_decision_csv(source_csv)

    report_dir = tmp_path / "fl_reports"
    run_fl_impact_analysis(
        source_path=source_csv,
        run_id="test-run-x",
        report_dir=report_dir,
    )

    with pytest.raises(FileExistsError):
        run_fl_impact_analysis(
            source_path=source_csv,
            run_id="test-run-x",
            report_dir=report_dir,
            fail_if_exists=True,
        )


def test_run_fl_impact_analysis_overwrite_with_fail_if_exists_false(tmp_path: Path):
    source_csv = tmp_path / "decision_log.csv"
    write_tmp_decision_csv(source_csv)

    report_dir = tmp_path / "fl_reports"
    result1 = run_fl_impact_analysis(
        source_path=source_csv,
        run_id="test-run-y",
        report_dir=report_dir,
    )

    result2 = run_fl_impact_analysis(
        source_path=source_csv,
        run_id="test-run-y",
        report_dir=report_dir,
        fail_if_exists=False,
    )

    assert result1["json_sha256"] == result2["json_sha256"]
    assert result2["fail_if_exists"] is False


def test_run_fl_impact_analysis_separate_run_id_with_fail_if_exists_true(
    tmp_path: Path,
):
    source_csv = tmp_path / "decision_log.csv"
    write_tmp_decision_csv(source_csv)

    report_dir = tmp_path / "fl_reports"
    run_fl_impact_analysis(
        source_path=source_csv,
        run_id="run-a",
        report_dir=report_dir,
    )

    # This should succeed because new run_id gets a distinct summary path
    result = run_fl_impact_analysis(
        source_path=source_csv,
        run_id="run-b",
        report_dir=report_dir,
        fail_if_exists=True,
    )

    assert result["run_id"] == "run-b"
    assert Path(result["result_json_path"]).name == "run-b.json"
    assert Path(result["summary_md_path"]).name == "summary-run-b.md"
    assert Path(result["legacy_summary_md_path"]).name == "summary.md"
    # compatibility: latest summary.md should be updated to last run
    legacy_summary = Path(result["legacy_summary_md_path"]).read_text(
        encoding="utf-8"
    )
    run_summary = Path(result["summary_md_path"]).read_text(encoding="utf-8")
    assert legacy_summary == run_summary


def test_run_fl_impact_analysis_legacy_summary_alias_updates(tmp_path: Path):
    source_csv = tmp_path / "decision_log.csv"
    write_tmp_decision_csv(source_csv)

    report_dir = tmp_path / "fl_reports"
    run_fl_impact_analysis(
        source_path=source_csv,
        run_id="run-1",
        report_dir=report_dir,
    )

    content_run_1 = Path(report_dir / "summary-run-1.md").read_text(encoding="utf-8")
    # legacy fallback should mirror first run
    assert Path(report_dir / "summary.md").read_text(encoding="utf-8") == content_run_1

    run_fl_impact_analysis(
        source_path=source_csv,
        run_id="run-2",
        report_dir=report_dir,
    )
    content_run_2 = Path(report_dir / "summary-run-2.md").read_text(encoding="utf-8")

    # legacy alias should now reflect the latest run summary
    assert Path(report_dir / "summary.md").read_text(encoding="utf-8") == content_run_2
