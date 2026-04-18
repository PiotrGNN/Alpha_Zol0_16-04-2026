import json
from pathlib import Path

from scripts.proxy_corpus_balancing_audit import _summarize_corpus


def test_balanced_corpus_not_feasible_from_one_sided_sample():
    report = _summarize_corpus(
        [
            {
                "run_id": "r1",
                "results_path": "x",
                "scenario": "baseline",
                "env": {},
                "trade_count": 1,
                "net_pnl": -1.0,
                "decisions_count": 1,
                "started_at_utc": "",
                "ended_at_utc": "",
                "duration_sec_actual": 1.0,
                "db_path": Path("does-not-exist"),
            }
        ]
    )
    assert report["realized_outcome_distribution"]["positive"] == 0
    assert report["balanced_corpus_feasibility"]["feasible_without_runtime_changes"] is False
    assert report["final_classification"] == "BALANCED_CORPUS_NOT_FEASIBLE"


def test_report_contains_stable_keys():
    report = _summarize_corpus([])
    for key in [
        "metadata",
        "data_sources",
        "realized_outcome_distribution",
        "matching_feasibility",
        "root_cause",
        "balanced_corpus_feasibility",
        "final_classification",
        "evidence_notes",
    ]:
        assert key in report


def test_root_cause_marks_one_sided_corpus_when_no_positives():
    report = _summarize_corpus(
        [
            {
                "run_id": "r1",
                "results_path": "x",
                "scenario": "baseline",
                "env": {},
                "trade_count": 1,
                "net_pnl": -1.0,
                "decisions_count": 1,
                "started_at_utc": "",
                "ended_at_utc": "",
                "duration_sec_actual": 1.0,
                "db_path": Path("does-not-exist"),
            }
        ]
    )
    assert report["root_cause"]["primary"] in {"SCENARIO_SELECTION_BIAS", "INSUFFICIENT_RUNTIME_WINDOW"}
    assert "one-sided" in report["root_cause"]["note"].lower()
