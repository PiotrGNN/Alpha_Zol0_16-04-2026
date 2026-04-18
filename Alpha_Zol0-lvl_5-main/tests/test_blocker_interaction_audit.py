import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "blocker_interaction_audit.py"
    spec = importlib.util.spec_from_file_location("blocker_interaction_audit_testmod", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_classify_symbol_parallel_population():
    mod = _load_module()
    run = {
        "scenario": "baseline",
        "label": "Scenario 0",
        "result": {
            "summary": {"rows": 2, "admitted_vs_blocked": {"admitted": 0, "blocked": 2}},
            "diagnostic_summary": {"gate_trace_by_gate": []},
        },
        "logs": [
            {"id": 1, "event": "diagnostic_gate_trace", "payload": {"gate_name": "net_target_guard"}},
            {"id": 2, "event": "entry_gate_decision_summary", "payload": {"top_local_gate_reason": [["run_end_cutoff", 1]]}},
            {"id": 3, "event": "diagnostic_gate_trace", "payload": {"gate_name": "current_side"}},
            {"id": 4, "event": "entry_gate_decision_summary", "payload": {"top_local_gate_reason": [["current_side", 1]]}},
        ],
    }
    cls = mod._classify_symbol([run])
    assert cls["interaction_classification"] in {"PARALLEL_BLOCKER_POPULATIONS", "MIXED_INTERACTION", "DOWNSTREAM_CHAIN_RELATION"}
    assert cls["gate_presence"]["net_target_guard"] == 1
    assert cls["gate_presence"]["current_side"] == 1


def test_build_report_shape():
    mod = _load_module()
    per = {
        "BTCUSDTM": [
            {
                "scenario": "baseline",
                "label": "Baseline",
                "result": {"summary": {"rows": 1, "admitted_vs_blocked": {"admitted": 0, "blocked": 1}}, "diagnostic_summary": {}},
                "logs": [],
            }
        ]
    }
    report = mod.build_report(per, ["BTCUSDTM"], 1, ["baseline"])
    assert "run_metadata" in report
    assert "per_symbol" in report
    assert "aggregate_classification_counts" in report
    assert "final_classification" in report

