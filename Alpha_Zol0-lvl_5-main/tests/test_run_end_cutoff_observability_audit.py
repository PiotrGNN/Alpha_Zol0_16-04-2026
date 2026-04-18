import importlib.util
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_end_cutoff_observability_audit.py"
    spec = importlib.util.spec_from_file_location("run_end_cutoff_observability_audit_testmod", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_report_shape():
    mod = _load_module()
    report = mod.build_report(["BTCUSDTM"], 1, ["baseline"])
    assert "run_metadata" in report
    assert "per_symbol" in report
    assert "aggregate" in report
    assert "final_classification" in report
    assert report["run_metadata"]["method_version"] == "observability_v2"


def test_classification_stable_when_no_run_end_cutoff(monkeypatch):
    mod = _load_module()

    def fake_audit_symbol(symbol, duration_min, scenarios):
        return {
            "symbol": symbol,
            "scenario_results": [
                {
                    "scenario": "baseline",
                    "label": "Baseline",
                    "rows": 2,
                    "admitted": 0,
                    "blocked": 2,
                    "pockets_total": 2,
                    "run_end_cutoff_pockets": 0,
                    "terminal_symptom_events": 0,
                    "diagnostic_presence_counts": {"net_target_guard": 2, "current_side": 0},
                    "effective_blocker_counts": {"net_target_guard": 0, "current_side": 0, "other_named_blocker": 0, "unknown": 0},
                    "presence_only_counts": {"net_target_guard": 2, "current_side": 0},
                    "source_attribution_observable": False,
                    "lifecycle_profile": {"pocket_count": 2, "median_pocket_length": 2, "max_pocket_length": 2, "median_events_per_pocket": 2, "pockets_ending_on_summary": 2},
                    "classification": "NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR",
                    "top_local_gate_reason": [],
                    "observability_notes": "no terminal symptom observed",
                    "notes": "run_end_cutoff not observed in this corridor; source attribution is not available",
                    "local_observability_classification": "NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR",
                }
            ],
            "classification_counter": {"NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR": 1},
            "final_classification": "INSUFFICIENT_EVIDENCE",
        }

    monkeypatch.setattr(mod.source_audit, "_audit_symbol", fake_audit_symbol)
    report = mod.build_report(["BTCUSDTM"], 1, ["baseline"])
    assert report["final_classification"] == "INSUFFICIENT_EVIDENCE"
    assert report["aggregate"]["total_run_end_cutoff_pockets"] == 0


def test_build_report_mixed_observability_when_some_symbols_observable(monkeypatch):
    """
    P3-2: When one symbol is observable (has run_end_cutoff pockets) and
    another is not observable, the final_classification must be
    MIXED_OBSERVABILITY_LIMITS.
    """
    mod = _load_module()

    def _make_sym(symbol, observable, cutoff_pockets):
        return {
            "symbol": symbol,
            "final_classification": (
                "UPSTREAM_BLOCKER_DOMINANCE_BEFORE_CUTOFF"
                if observable
                else "NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR"
            ),
            "scenario_results": [
                {
                    "scenario": "baseline",
                    "label": "Baseline",
                    "rows": 4,
                    "admitted": 0,
                    "blocked": 4,
                    "pockets_total": 2,
                    "run_end_cutoff_pockets": cutoff_pockets,
                    "terminal_symptom_events": int(bool(cutoff_pockets)),
                    "diagnostic_presence_counts": {
                        "net_target_guard": 0,
                        "current_side": 0,
                    },
                    "effective_blocker_counts": {
                        "net_target_guard": 0,
                        "current_side": 0,
                        "other_named_blocker": 0,
                        "unknown": 0,
                    },
                    "presence_only_counts": {
                        "net_target_guard": 0,
                        "current_side": 0,
                    },
                    "source_attribution_observable": observable,
                    "lifecycle_profile": {
                        "pocket_count": 2,
                        "median_pocket_length": 2,
                        "max_pocket_length": 3,
                        "median_events_per_pocket": 2,
                        "pockets_ending_on_summary": 1,
                    },
                    "classification": (
                        "RUN_END_CUTOFF_MOSTLY_POST_BLOCKER_TERMINAL"
                        if observable
                        else "NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR"
                    ),
                    "top_local_gate_reason": [],
                    "observability_notes": "",
                    "notes": "",
                    "local_observability_classification": (
                        "OBSERVABLE_RUN_END_CUTOFF_DETECTED"
                        if observable
                        else "NOT_OBSERVABLE_IN_CURRENT_CONTROLLED_CORRIDOR"
                    ),
                }
            ],
        }

    symbols_data = {
        "BTCUSDTM": _make_sym("BTCUSDTM", observable=True, cutoff_pockets=2),
        "ETHUSDTM": _make_sym("ETHUSDTM", observable=False, cutoff_pockets=0),
    }

    def fake_audit_symbol(symbol, duration_min, scenarios):
        return symbols_data[symbol]

    monkeypatch.setattr(mod.source_audit, "_audit_symbol", fake_audit_symbol)
    report = mod.build_report(["BTCUSDTM", "ETHUSDTM"], 1, ["baseline"])

    assert report["final_classification"] == "MIXED_OBSERVABILITY_LIMITS", (
        f"Expected MIXED_OBSERVABILITY_LIMITS, got: {report['final_classification']}"
    )
    assert report["aggregate"]["total_run_end_cutoff_pockets"] == 2


def test_build_report_upstream_dominance_when_all_symbols_observable(monkeypatch):
    """
    When all symbols have run_end_cutoff pockets (all observable), the
    final_classification must be UPSTREAM_BLOCKER_DOMINANCE_BEFORE_CUTOFF.
    """
    mod = _load_module()

    def fake_audit_symbol(symbol, duration_min, scenarios):
        return {
            "symbol": symbol,
            "final_classification": "UPSTREAM_BLOCKER_DOMINANCE_BEFORE_CUTOFF",
            "scenario_results": [
                {
                    "scenario": "baseline",
                    "rows": 4,
                    "admitted": 0,
                    "blocked": 4,
                    "pockets_total": 2,
                    "run_end_cutoff_pockets": 2,
                    "terminal_symptom_events": 1,
                    "diagnostic_presence_counts": {
                        "net_target_guard": 0,
                        "current_side": 0,
                    },
                    "effective_blocker_counts": {
                        "net_target_guard": 0,
                        "current_side": 0,
                        "other_named_blocker": 0,
                        "unknown": 0,
                    },
                    "presence_only_counts": {
                        "net_target_guard": 0,
                        "current_side": 0,
                    },
                    "source_attribution_observable": True,
                    "lifecycle_profile": {
                        "pocket_count": 2,
                        "median_pocket_length": 2,
                        "max_pocket_length": 3,
                        "median_events_per_pocket": 2,
                        "pockets_ending_on_summary": 1,
                    },
                    "classification": "UPSTREAM_BLOCKER_DOMINANCE_BEFORE_CUTOFF",
                    "top_local_gate_reason": [],
                    "observability_notes": "",
                    "notes": "",
                    "local_observability_classification": (
                        "OBSERVABLE_RUN_END_CUTOFF_DETECTED"
                    ),
                    "label": "Baseline",
                }
            ],
        }

    monkeypatch.setattr(mod.source_audit, "_audit_symbol", fake_audit_symbol)
    report = mod.build_report(["BTCUSDTM"], 1, ["baseline"])

    assert report["final_classification"] == "UPSTREAM_BLOCKER_DOMINANCE_BEFORE_CUTOFF"
    assert report["aggregate"]["total_run_end_cutoff_pockets"] == 2
