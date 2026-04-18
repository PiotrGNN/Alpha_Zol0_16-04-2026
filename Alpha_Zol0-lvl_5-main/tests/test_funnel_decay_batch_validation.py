import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "funnel_decay_batch_validation.py"
    spec = importlib.util.spec_from_file_location("funnel_decay_batch_validation_testmod", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_batch_report_shape_and_classification(monkeypatch):
    mod = _load_module()

    def fake_run_scenario(symbol, duration_min, scenario):
        summary_rows = 10 if symbol == "BTCUSDTM" else 12
        return {
            "name": scenario["name"],
            "label": scenario["label"],
            "report": {"before": {"trade_count": 0}},
            "summary": {
                "rows": summary_rows,
                "admitted_vs_blocked": {"admitted": 0, "blocked": summary_rows},
                "top_local_gate_reason": [["run_end_cutoff", summary_rows]],
            },
            "diagnostic_summary": {
                "gate_trace_summary": {"total_trace_events": 0, "total_gate_blocked": 0, "total_gate_skipped": 0},
                "gate_trace_by_gate": [],
            },
        }

    monkeypatch.setattr(mod.funnel_decay, "_run_scenario", fake_run_scenario)
    report = mod._run_batch(["BTCUSDTM", "ETHUSDTM"], 1, ["baseline", "disable_current_side"])
    assert report["run_metadata"]["symbol_count"] == 2
    assert report["run_metadata"]["scenario_count"] == 2
    assert len(report["per_symbol"]) == 2
    assert len(report["per_scenario"]) == 2
    assert report["final_classification"] == "UPSTREAM_SIGNAL_SCARCITY_REPEATED_ACROSS_SMALL_BATCH"


def test_batch_report_mixed_classification(monkeypatch):
    mod = _load_module()

    def fake_run_scenario(symbol, duration_min, scenario):
        classification = "UPSTREAM_SIGNAL_SCARCITY_DOMINATES" if symbol == "BTCUSDTM" else "MIXED_FUNNEL_DECAY"
        return {
            "name": scenario["name"],
            "label": scenario["label"],
            "report": {"before": {"trade_count": 0}},
            "summary": {
                "rows": 10,
                "admitted_vs_blocked": {"admitted": 0, "blocked": 10},
                "top_local_gate_reason": [["run_end_cutoff", 10]],
            },
            "diagnostic_summary": {
                "gate_trace_summary": {"total_trace_events": 1, "total_gate_blocked": 1, "total_gate_skipped": 0},
                "gate_trace_by_gate": [{"gate_name": "current_side", "blocked_count": 1, "skipped_count": 0}],
            },
            "classification": classification,
        }

    monkeypatch.setattr(mod.funnel_decay, "_run_scenario", fake_run_scenario)
    report = mod._run_batch(["BTCUSDTM", "ETHUSDTM"], 1, ["baseline"])
    assert report["final_classification"] in {
        "MIXED_RESULTS_ACROSS_SMALL_BATCH",
        "UPSTREAM_SIGNAL_SCARCITY_REPEATED_ACROSS_SMALL_BATCH",
    }
    assert "aggregate_classification_counts" in report

