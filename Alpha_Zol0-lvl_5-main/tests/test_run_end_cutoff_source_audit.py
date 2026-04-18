import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_end_cutoff_source_audit.py"
    spec = importlib.util.spec_from_file_location("run_end_cutoff_source_audit_testmod", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_classify_pocket_source_counts():
    mod = _load_module()
    pocket = [
        {"event": "run_end_entry_cutoff", "payload": {"symbol": "BTCUSDTM"}},
        {"event": "diagnostic_gate_trace", "payload": {"gate_name": "net_target_guard", "gate_blocked": True, "gate_skipped": False}},
        {"event": "entry_gate_decision_summary", "payload": {"top_local_gate_reason": [["run_end_cutoff", 1]], "admitted_vs_blocked": {"admitted": 0, "blocked": 1}, "rows": 1}},
    ]
    cls = mod._classify_pocket(pocket)
    assert cls["terminal_symptom"] is True
    assert cls["summary_cutoff_label"] is True
    assert "net_target_guard" in cls["named_blockers"]


def test_audit_symbol_shape():
    mod = _load_module()

    def fake_run_scenario(symbol, duration_min, scenario):
        return {
            "run": {
                "summary": {"rows": 2, "admitted_vs_blocked": {"admitted": 0, "blocked": 2}},
            },
            "logs": [
                {"event": "run_end_entry_cutoff", "payload": {"symbol": symbol}},
                {"event": "diagnostic_gate_trace", "payload": {"gate_name": "current_side", "gate_blocked": True, "gate_skipped": False}},
                {"event": "entry_gate_decision_summary", "payload": {"top_local_gate_reason": [["run_end_cutoff", 1]], "admitted_vs_blocked": {"admitted": 0, "blocked": 1}, "rows": 1}},
            ],
        }

    original = mod._run_scenario
    mod._run_scenario = fake_run_scenario
    try:
        audit = mod._audit_symbol("BTCUSDTM", 1, ["baseline"])
    finally:
        mod._run_scenario = original
    assert audit["symbol"] == "BTCUSDTM"
    assert audit["final_classification"] in {
        "RUN_END_CUTOFF_MOSTLY_SIGNAL_SCARCITY",
        "RUN_END_CUTOFF_MOSTLY_POST_BLOCKER_TERMINAL",
        "RUN_END_CUTOFF_MIXED_SOURCES",
        "INSUFFICIENT_EVIDENCE",
        "NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR",
    }
    assert "scenario_results" in audit



def test_not_observable_when_no_run_end_cutoff():
    mod = _load_module()

    def fake_run_scenario(symbol, duration_min, scenario):
        return {
            "run": {"summary": {"rows": 2, "admitted_vs_blocked": {"admitted": 0, "blocked": 2}}},
            "logs": [
                {"event": "diagnostic_gate_trace", "payload": {"gate_name": "current_side", "gate_blocked": False, "gate_skipped": True, "skip_reason": "diagnostic_override"}},
                {"event": "entry_gate_decision_summary", "payload": {"top_local_gate_reason": [["current_side", 1]], "admitted_vs_blocked": {"admitted": 0, "blocked": 1}, "rows": 1}},
            ],
        }

    original = mod._run_scenario
    mod._run_scenario = fake_run_scenario
    try:
        audit = mod._audit_symbol("BTCUSDTM", 1, ["disable_current_side"])
    finally:
        mod._run_scenario = original
    scenario = audit["scenario_results"][0]
    assert scenario["run_end_cutoff_pockets"] == 0
    assert scenario["source_attribution_observable"] is False
    assert scenario["classification"] == "NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR"
    assert scenario["effective_blocker_counts"]["current_side"] == 0
    assert scenario["presence_only_counts"]["current_side"] == 1
    assert scenario["observability_notes"].startswith("no terminal symptom")


def test_run_end_cutoff_observed_uses_effective_blockers_only():
    mod = _load_module()

    def fake_run_scenario(symbol, duration_min, scenario):
        return {
            "run": {"summary": {"rows": 1, "admitted_vs_blocked": {"admitted": 0, "blocked": 1}}},
            "logs": [
                {"event": "run_end_entry_cutoff", "payload": {"symbol": symbol}},
                {"event": "diagnostic_gate_trace", "payload": {"gate_name": "current_side", "gate_blocked": True, "gate_skipped": False}},
                {"event": "entry_gate_decision_summary", "payload": {"top_local_gate_reason": [["run_end_cutoff", 1]], "admitted_vs_blocked": {"admitted": 0, "blocked": 1}, "rows": 1}},
            ],
        }

    original = mod._run_scenario
    mod._run_scenario = fake_run_scenario
    try:
        audit = mod._audit_symbol("ETHUSDTM", 1, ["baseline"])
    finally:
        mod._run_scenario = original
    scenario = audit["scenario_results"][0]
    assert scenario["run_end_cutoff_pockets"] == 1
    assert scenario["source_attribution_observable"] is True
    assert scenario["effective_blocker_counts"]["current_side"] == 1
    assert scenario["presence_only_counts"]["current_side"] == 0
    assert scenario["classification"] in {
        "RUN_END_CUTOFF_MOSTLY_POST_BLOCKER_TERMINAL",
        "RUN_END_CUTOFF_MIXED_SOURCES",
        "RUN_END_CUTOFF_MOSTLY_SIGNAL_SCARCITY",
    }
    assert "lifecycle_profile" in scenario
    assert "terminal_symptom_events" in scenario


def test_markdown_sections_and_json_keys():
    mod = _load_module()
    report = {
        "run_metadata": {
            "stamp": "20260328_000000",
            "symbols": ["BTCUSDTM"],
            "scenarios": ["baseline"],
            "duration_min": 1,
            "method_version": "observability_v2",
        },
        "per_symbol": [],
        "aggregate": {
            "total_pockets": 0,
            "total_run_end_cutoff_pockets": 0,
            "named_blocker_dominance_summary": {},
            "segmentation_findings": {},
            "signal_scarcity_findings": {},
            "final_classification": "INSUFFICIENT_EVIDENCE",
        },
        "aggregate_classification_counts": {"INSUFFICIENT_EVIDENCE": 1},
        "final_classification": "INSUFFICIENT_EVIDENCE",
    }
    assert report["run_metadata"]["method_version"] == "observability_v2"
