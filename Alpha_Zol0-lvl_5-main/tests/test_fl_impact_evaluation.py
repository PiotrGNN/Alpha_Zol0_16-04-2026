from analysis.fl_impact_report import (
    FLDecisionSnapshot,
    create_report_json,
    create_report_markdown,
    evaluate_fl_impact,
)


def test_evaluate_fl_impact_deterministic():
    snapshots = [
        FLDecisionSnapshot(
            id="1",
            decision_before="buy",
            decision_after="sell",
            edge_before=0.5,
            edge_after=0.8,
            admission_before=True,
            admission_after=True,
        ),
        FLDecisionSnapshot(
            id="2",
            decision_before="hold",
            decision_after="hold",
            edge_before=0.2,
            edge_after=0.1,
            admission_before=False,
            admission_after=False,
        ),
    ]

    metrics = evaluate_fl_impact(snapshots)
    assert metrics["total_decisions"] == 2
    assert metrics["changed_decisions"] == 1
    assert metrics["percent_changed"] == 50.0
    assert metrics["positive_impact_count"] == 1
    assert metrics["negative_impact_count"] == 1
    assert metrics["go_no_go"] == "GO"

    json_report = create_report_json(snapshots)
    assert "snapshots" in json_report
    assert "metrics" in json_report

    md_report = create_report_markdown(snapshots)
    assert "# FL Impact Decision Report" in md_report


def test_evaluate_fl_impact_neutral_only_is_no_go():
    snapshots = [
        FLDecisionSnapshot(
            id="n1",
            decision_before="buy",
            decision_after="sell",
            edge_before=0.0,
            edge_after=0.0,
            admission_before=True,
            admission_after=True,
        ),
        FLDecisionSnapshot(
            id="n2",
            decision_before="hold",
            decision_after="hold",
            edge_before=0.0,
            edge_after=0.0,
            admission_before=False,
            admission_after=False,
        ),
    ]

    metrics = evaluate_fl_impact(snapshots)
    assert metrics["changed_decisions"] == 1
    assert metrics["positive_impact_count"] == 0
    assert metrics["negative_impact_count"] == 0
    assert metrics["neutral_impact_count"] == 2
    assert metrics["avg_edge_delta"] == 0.0
    assert metrics["go_no_go"] == "NO-GO"
