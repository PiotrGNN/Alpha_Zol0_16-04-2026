from pathlib import Path

from scripts.edge_history_linkage_redesign_plan import WORKDIR, _build_report


def test_linkage_redesign_report_shape():
    report = _build_report(
        WORKDIR / "artifacts" / "diagnostics" / "canonical_bucket_alignment_20260328_092527.json",
        WORKDIR / "artifacts" / "diagnostics" / "long_canonical_readiness_unlock_20260328_092603.json",
    )
    assert report["final_classification"] == "LINKAGE_REDESIGN_REQUIRED_AND_FEASIBLE"
    assert report["write_path"]["function"] == "_update_symbol_strategy_side_edge_perf"
    assert report["read_path"]["function"] == "_entry_edge_over_fee_check"
    assert "canonical_edge_history_state" in {c["name"] for c in report["redesign"]["components"]}
    assert report["validation"]["non_regression_rules"]
