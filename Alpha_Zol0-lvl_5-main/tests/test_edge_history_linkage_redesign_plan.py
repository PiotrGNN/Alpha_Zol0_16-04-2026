import json

from scripts.edge_history_linkage_redesign_plan import _build_report


def test_linkage_redesign_report_shape(tmp_path):
    canonical_path = tmp_path / "canonical.json"
    readiness_path = tmp_path / "readiness.json"
    canonical_path.write_text(json.dumps({}), encoding="utf-8")
    readiness_path.write_text(json.dumps({}), encoding="utf-8")

    report = _build_report(canonical_path, readiness_path)
    assert report["final_classification"] == "LINKAGE_REDESIGN_REQUIRED_AND_FEASIBLE"
    assert report["write_path"]["function"] == "_update_symbol_strategy_side_edge_perf"
    assert report["read_path"]["function"] == "_entry_edge_over_fee_check"
    assert "canonical_edge_history_state" in {
        component["name"] for component in report["redesign"]["components"]
    }
    assert report["validation"]["non_regression_rules"]
