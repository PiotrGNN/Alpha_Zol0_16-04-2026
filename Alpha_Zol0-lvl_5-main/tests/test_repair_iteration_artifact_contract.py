import json
from pathlib import Path

import pytest

from scripts import backfill_repair_iteration_artifacts as backfill
from scripts import repair_plan_kpi_iteration as repair_iter


def _sample_summary() -> dict:
    return {
        "metadata": {
            "generated_at": "2026-04-10T00:00:00+00:00",
            "scorecard_path": "analysis/scorecard.json",
            "seed_report_path": "results/controlled_kpi.json",
            "args": {
                "symbols": "ETHUSDTM",
                "market_type": "futures",
                "timeframe": "1",
                "after_min": 3,
                "paper_auto_close_sec": 20,
                "equity_snapshot_sec": 30,
            },
        },
        "patch_runs": [
            {
                "patch_id": "baseline_locked",
                "title": "Baseline locked",
                "rationale": "baseline",
            },
            {
                "patch_id": "candidate_patch",
                "title": "Candidate",
                "rationale": "candidate rationale",
            },
        ],
        "patch_isolation_matrix": {
            "rows": [
                {
                    "patch_id": "baseline_locked",
                    "profit_factor": 1.0,
                    "net_pnl": 0.1,
                    "trade_count": 4,
                    "delta_profit_factor_vs_baseline": 0.0,
                    "delta_net_pnl_vs_baseline": 0.0,
                    "real_pf_gain": False,
                },
                {
                    "patch_id": "candidate_patch",
                    "profit_factor": 1.2,
                    "net_pnl": 0.2,
                    "trade_count": 5,
                    "delta_profit_factor_vs_baseline": 0.2,
                    "delta_net_pnl_vs_baseline": 0.1,
                    "real_pf_gain": True,
                },
            ]
        },
        "runtime_target_verification": {
            "baseline_locked": {"runtime_target_pass": True, "targets": {}},
            "candidate_patch": {"runtime_target_pass": True, "targets": {}},
        },
        "rollout_gates": {
            "definitions": {"profitability_floor": "pf>=1"},
            "decisions": [
                {"patch_id": "baseline_locked", "action": "hold", "reasons": ["baseline_reference"]},
                {"patch_id": "candidate_patch", "action": "promote", "reasons": ["runtime_targets_pass"]},
            ],
            "recommendation": {
                "patch_id": "candidate_patch",
                "action": "promote",
                "reason": "best_candidate",
            },
        },
    }


def test_contract_enforcement_requires_mandatory_files(tmp_path):
    out_dir = tmp_path / "repair_iteration_foo"
    out_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(RuntimeError):
        repair_iter._enforce_required_artifact_contract(out_dir)


def test_contract_enforcement_passes_when_required_files_exist(tmp_path):
    out_dir = tmp_path / "repair_iteration_bar"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = _sample_summary()
    (out_dir / "repair_iteration_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    (out_dir / "repair_plan.md").write_text(
        repair_iter._render_repair_plan_md(summary),
        encoding="utf-8",
    )
    (out_dir / "repair_iteration.md").write_text(
        repair_iter._render_repair_iteration_md(summary),
        encoding="utf-8",
    )
    (out_dir / "repair_diff.md").write_text(
        repair_iter._render_repair_diff_md(summary),
        encoding="utf-8",
    )
    repair_iter._enforce_required_artifact_contract(out_dir)


def test_backfill_creates_missing_summary_and_contract(tmp_path):
    iteration_dir = tmp_path / "repair_iteration_missing"
    iteration_dir.mkdir(parents=True, exist_ok=True)
    (iteration_dir / "rollout_gate_hardening.json").write_text(
        json.dumps(
            {"recommendation": {"patch_id": "baseline_locked", "action": "hold", "reason": "fallback"}},
            indent=2,
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    row = backfill._backfill_iteration_dir(iteration_dir)
    assert "repair_plan.md" in row["written_files"]
    assert (iteration_dir / "repair_iteration_summary.json").exists()
    assert (iteration_dir / "repair_plan.md").exists()
    assert (iteration_dir / "repair_iteration.md").exists()
    assert (iteration_dir / "repair_diff.md").exists()


def test_run_controlled_kpi_records_entry_admission_fail_closed(
    monkeypatch,
    tmp_path,
):
    contract_path = tmp_path / "entry_admission_contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "contract": {
                    "status": "FAIL_CLOSED",
                    "reason_codes": [
                        "NO_ELIGIBLE_ENTRY_BUCKETS",
                        "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST_EMPTY",
                    ],
                }
            },
            indent=2,
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    class Completed:
        returncode = 1
        stdout = f"ENTRY_ADMISSION_CONTRACT_JSON={contract_path}\n"
        stderr = (
            "controlled_kpi_entry_admission_contract_failed "
            f"artifact={contract_path}"
        )

    monkeypatch.setattr(repair_iter, "WORKDIR", tmp_path)
    monkeypatch.setattr(
        repair_iter,
        "CONTROLLED_KPI_SCRIPT",
        tmp_path / "scripts" / "controlled_kpi_run.py",
    )
    monkeypatch.setattr(repair_iter.subprocess, "run", lambda *a, **k: Completed())

    row = repair_iter._run_controlled_kpi(
        patch=repair_iter.PatchSpec(
            patch_id="baseline_locked",
            title="Baseline",
            rationale="baseline",
            overrides={},
        ),
        base_overrides={},
        symbols="ETHUSDTM",
        market_type="futures",
        timeframe="1",
        after_min=16,
        paper_auto_close_sec=60,
        equity_snapshot_sec=10,
        alpha_source_db_url="sqlite:///tmp/source.db",
        alpha_source_db_glob="tmp/source.db",
    )

    assert row["report_json_path"] is None
    assert row["subprocess_returncode"] == 1
    assert "entry admission contract fail-closed" in row["run_error"]
    assert row["after"]["trade_count"] == 0
    assert row["after"]["process_returncode"] == 1
    assert row["after"]["entry_admission_contract"]["status"] == "FAIL_CLOSED"
    assert "NO_ELIGIBLE_ENTRY_BUCKETS" in row["after"][
        "entry_admission_contract"
    ]["reason_codes"]
