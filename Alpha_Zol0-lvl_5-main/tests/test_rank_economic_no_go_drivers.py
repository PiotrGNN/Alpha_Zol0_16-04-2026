import json

from scripts import rank_economic_no_go_drivers as rankers


def test_build_ranking_counts_no_go_and_drivers(tmp_path):
    readiness_dir = tmp_path / "paper_readiness"
    readiness_dir.mkdir(parents=True, exist_ok=True)
    (readiness_dir / "paper_readiness_gate_1.json").write_text(
        json.dumps(
            {
                "timestamp": "1",
                "economics_context": {
                    "go_no_go": "NO-GO",
                    "avg_edge_delta": -0.5,
                    "positive_impact_count": 1,
                    "negative_impact_count": 3,
                    "changed_decisions": 2,
                },
            }
        ),
        encoding="utf-8",
    )
    (readiness_dir / "paper_readiness_gate_2.json").write_text(
        json.dumps(
            {
                "timestamp": "2",
                "economics_context": {
                    "go_no_go": "GO",
                    "avg_edge_delta": 0.2,
                    "positive_impact_count": 3,
                    "negative_impact_count": 0,
                    "changed_decisions": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = rankers.build_ranking(readiness_dir)
    assert payload["readiness_reports_total"] == 2
    assert payload["no_go_reports_total"] == 1
    driver_ids = {row["driver_id"] for row in payload["driver_ranking"]}
    assert "EDGE_DELTA_NEGATIVE" in driver_ids
    assert "NEGATIVE_IMPACT_DOMINATES" in driver_ids
    assert "DECISION_CHURN" in driver_ids
