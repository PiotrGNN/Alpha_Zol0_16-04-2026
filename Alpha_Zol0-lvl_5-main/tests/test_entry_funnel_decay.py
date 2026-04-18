import importlib.util
import json
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "entry_funnel_decay.py"
    spec = importlib.util.spec_from_file_location("entry_funnel_decay_testmod", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_report_shape(tmp_path):
    mod = _load_module()
    runs = [
        {
            "name": "baseline",
            "label": "Scenario 0",
            "report": {"before": {"event_counts": {"strategy_signals": 10, "entry_live_edge_eval": 3, "entry_edge_over_fee_eval": 1, "tf_trend_entry_eval": 10, "run_end_entry_cutoff": 2}}},
            "summary": {"rows": 5, "admitted_vs_blocked": {"admitted": 0, "blocked": 5}, "top_local_gate_reason": [["run_end_cutoff", 5]]},
            "diagnostic_summary": {},
        },
        {
            "name": "disable_current_side",
            "label": "Scenario 2",
            "report": {"before": {"event_counts": {"strategy_signals": 12, "entry_live_edge_eval": 4, "entry_edge_over_fee_eval": 2, "tf_trend_entry_eval": 12, "run_end_entry_cutoff": 1}}},
            "summary": {"rows": 6, "admitted_vs_blocked": {"admitted": 1, "blocked": 5}, "top_local_gate_reason": [["current_side", 4]]},
            "diagnostic_summary": {"gate_trace_by_gate": [{"gate_name": "current_side", "blocked_count": 4, "skipped_count": 0}]},
        },
    ]
    report = mod.build_report(runs, "BTCUSDTM", 2)
    assert report["run_metadata"]["symbol"] == "BTCUSDTM"
    assert report["run_metadata"]["scenario_count"] == 2
    assert "metric_definitions" in report
    assert len(report["funnel_by_scenario"]) == 2
    assert report["funnel_by_scenario"][0]["candidate_entry_rows"] == 10
    assert report["funnel_by_scenario"][0]["strategy_signal_rows"] == 10
    assert report["funnel_by_scenario"][0]["summary_rows"] == 5
    assert report["funnel_by_scenario"][0]["metric_alignment"]["rows_vs_strategy_signals"]["same_source"] is False
    assert report["funnel_by_scenario"][1]["blocked_by_gate"]["current_side"] == 4
    assert report["cross_scenario_comparison"][0]["admitted_rows_delta"] == 1


def test_report_payload_contains_required_sections(tmp_path):
    mod = _load_module()
    report = mod.build_report([], "ETHUSDTM", 2)
    assert "run_metadata" in report
    assert "funnel_by_scenario" in report
    assert "decay_analysis" in report
    assert "cross_scenario_comparison" in report
    assert "final_classification" in report
    assert "metric_definitions" in report


def test_metric_definitions_explain_non_subset_counts(tmp_path):
    mod = _load_module()
    runs = [
        {
            "name": "baseline",
            "label": "Scenario 0",
            "report": {"before": {"event_counts": {"strategy_signals": 7, "entry_live_edge_eval": 4, "entry_edge_over_fee_eval": 2}}},
            "summary": {"rows": 5, "admitted_vs_blocked": {"admitted": 0, "blocked": 5}, "top_local_gate_reason": [["run_end_cutoff", 5]]},
            "diagnostic_summary": {},
        }
    ]
    report = mod.build_report(runs, "BTCUSDTM", 2)
    funnel = report["funnel_by_scenario"][0]
    assert funnel["rows"] == 5
    assert funnel["candidate_entry_rows"] == 7
    assert funnel["metric_definitions"]["candidate_entry_rows"]["source"] == "strategy_signals"
    assert "not required to be <= rows" in funnel["metric_definitions"]["candidate_entry_rows"]["meaning"]
    assert funnel["metric_alignment"]["rows_vs_strategy_signals"]["delta"] == -2
