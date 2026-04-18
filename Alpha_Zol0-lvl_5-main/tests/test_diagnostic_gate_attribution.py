import importlib.util
import json
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "diagnostic_gate_attribution.py"
    spec = importlib.util.spec_from_file_location("diagnostic_gate_attribution_testmod", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_build_report_with_disabled_gate_shift(tmp_path):
    mod = _load_module()
    baseline_summary = tmp_path / "baseline_summary.json"
    diag_summary = tmp_path / "baseline_diag.json"
    scenario_summary = tmp_path / "scenario_summary.json"
    scenario_diag = tmp_path / "scenario_diag.json"
    _write_json(
        baseline_summary,
        {
            "rows": 10,
            "admitted_vs_blocked": {"admitted": 1, "blocked": 9},
            "top_local_gate_reason": [["current_side", 7], ["net_target_guard", 2]],
        },
    )
    _write_json(
        diag_summary,
        {
            "gate_trace_by_gate": [
                {"gate_name": "current_side", "blocked_count": 7, "skipped_count": 0},
                {"gate_name": "net_target_guard", "blocked_count": 2, "skipped_count": 0},
            ]
        },
    )
    _write_json(
        scenario_summary,
        {
            "rows": 10,
            "admitted_vs_blocked": {"admitted": 2, "blocked": 8},
            "top_local_gate_reason": [["net_target_guard", 5], ["side_guard", 3]],
        },
    )
    _write_json(
        scenario_diag,
        {
            "gate_trace_summary": {"total_trace_events": 8, "total_gate_blocked": 5, "total_gate_skipped": 3},
            "gate_trace_by_gate": [
                {"gate_name": "net_target_guard", "blocked_count": 5, "skipped_count": 3},
            ],
        },
    )
    run_results = [
        {
            "name": "baseline",
            "summary_json": str(baseline_summary),
            "diagnostic_summary": json.loads(diag_summary.read_text(encoding="utf-8")),
            "report": {"run_id": "baseline", "before": {"trade_count": 1}},
            "scenario_env": {"DIAGNOSTIC_MODE": "0"},
        },
        {
            "name": "disable_net_target_guard",
            "summary_json": str(scenario_summary),
            "diagnostic_summary": json.loads(scenario_diag.read_text(encoding="utf-8")),
            "report": {"run_id": "scenario", "before": {"trade_count": 2}},
            "scenario_env": {"DIAGNOSTIC_MODE": "1", "DIAG_DISABLE_NET_TARGET_GUARD": "1"},
        },
    ]
    report = mod._build_report(run_results, "20260327_000000")
    assert report["run_metadata"]["scenario_count"] == 2
    assert report["scenario_summary"][0]["rows"] == 10
    assert report["scenario_summary"][1]["gate_trace_summary"]["total_trace_events"] == 8
    assert report["gate_attribution_matrix"][0]["gate"] == "current_side"
    assert report["gate_attribution_matrix"][1]["gate"] == "net_target_guard"
    assert report["final_classification"] in {
        "MULTI_STAGE_BLOCKER_CHAIN_CONFIRMED",
        "NO_MEANINGFUL_PROGRESS_AFTER_DISABLE",
    }

