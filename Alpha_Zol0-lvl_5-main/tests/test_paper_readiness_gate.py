import json
from pathlib import Path

import pytest

from scripts import run_paper_readiness_gate as gate


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _build_after_bundle(
    tmp_path: Path,
    run_id: str,
    *,
    use_mock: bool = False,
    include_before: bool = False,
    variant_only: str = "after",
    variants_run: list[str] | None = None,
    forbidden_names: bool = False,
    shared_prefix: str | None = None,
    live_trace: bool = False,
    after_process_returncode: int = 0,
    after_error_count: int = 0,
    alpha_runtime_status: str = "PASS",
    paper_auto_open: bool = True,
) -> dict:
    base_name = shared_prefix or run_id
    artifacts_dir = tmp_path / "artifacts" / base_name
    logs_dir = tmp_path / "logs" / base_name
    report_dir = tmp_path / "results" / base_name
    summary_dir = tmp_path / "reports" / "paper_readiness" / base_name

    if forbidden_names:
        db_name = "x.db"
        report_name = "x.json"
        csv_name = "x.csv"
        summary_name = "x_summary.json"
    else:
        db_name = f"controlled_kpi_after_{run_id}.db"
        report_name = f"controlled_kpi_{run_id}.json"
        csv_name = f"controlled_kpi_{run_id}.csv"
        summary_name = f"{run_id}_summary.json"

    db_path = artifacts_dir / db_name
    report_json = report_dir / report_name
    csv_path = report_dir / csv_name
    summary_json = summary_dir / summary_name
    out_log = logs_dir / f"{run_id}.out.log"
    err_log = logs_dir / f"{run_id}.err.log"

    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text("db", encoding="utf-8")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("variant,trade_count\nafter,1\n", encoding="utf-8")
    out_log.parent.mkdir(parents=True, exist_ok=True)
    out_log.write_text("", encoding="utf-8")
    err_log.write_text("", encoding="utf-8")

    summary_payload = {
        "rows": 10,
        "count_alignment": {"count_matches": True},
        "ordering": {"all_pairs_in_order": True},
        "payload_completeness": {"all_complete": True},
    }
    _write_json(summary_json, summary_payload)

    after_report = {
        "variant": "after",
        "db_path": str(db_path),
        "out_log": str(out_log),
        "err_log": str(err_log),
        "process_returncode": after_process_returncode,
        "log_health": {"error_count": after_error_count},
    }
    report_payload = {
        "params": {
            "variant_only": variant_only,
            "use_mock": use_mock,
            "paper_auto_open": paper_auto_open,
        },
        "variants_run": list(variants_run or ["after"]),
        "after": after_report,
        "alpha_bootstrap_runtime_contract": {
            "status": alpha_runtime_status,
            "reason_codes": [],
        },
    }
    if include_before:
        report_payload["before"] = {
            "db_path": str(tmp_path / "legacy_before.db"),
            "db_exists": True,
            "trade_count": 1,
        }
    _write_json(report_json, report_payload)

    return {
        "run_id": run_id,
        "symbols": "ETHUSDTM",
        "proc_returncode": 0,
        "report_json": str(report_json),
        "db_path": str(db_path),
        "stdout_log": str(out_log),
        "stderr_log": str(err_log),
        "controlled_kpi_csv": str(csv_path),
        "summary_json": str(summary_json),
        "summary": summary_payload,
        "report": report_payload,
        "after_report": after_report,
        "artifact_paths": {
            "db_path": str(db_path),
            "controlled_kpi_json": str(report_json),
            "controlled_kpi_csv": str(csv_path),
            "summary_json": str(summary_json),
        },
        "stdout": "LIVE=1" if live_trace else "",
        "stderr": "",
    }


def _corpus_contract_stub(*, status: str, reason_codes: list[str]) -> dict:
    return {
        "status": status,
        "reason_codes": list(reason_codes),
        "scorecard_path": "",
        "strict_corpus_status_path": "",
        "accepted_artifacts_present": status == "PASS",
        "accepted_artifacts_nonzero": status == "PASS",
        "accepted_artifact_source": "accepted_manifest",
        "accepted_manifest_path": "",
        "accepted_corpus_bundle_dir": "",
        "accepted_manifest_hash_mismatch_count": 0,
        "accepted_run_ids": ["a", "b", "c"] if status == "PASS" else [],
        "accepted_run_count": 3 if status == "PASS" else 0,
        "required_accepted_runs": 3 if status == "PASS" else 20,
    }


def _bootstrap_contract_stub(*, status: str, reason_codes: list[str]) -> dict:
    return {
        "status": status,
        "reason_codes": list(reason_codes),
        "manifest_path": "",
        "source_scorecard_path": "",
        "bundle_dir": "",
        "db_path": "",
        "report_path": "",
        "rows_inserted": 0,
        "pairs_selected": 0,
        "positive_side_allowlist": [],
    }


def _write_manifest_fixture(tmp_path: Path, *, total_trade_count: int = 1) -> Path:
    analysis_dir = tmp_path / "analysis"
    manifest_dir = tmp_path / "artifacts" / "accepted_corpus" / "official"
    run_dir = manifest_dir / "accepted_runs"
    result_path = run_dir / "controlled_kpi_run-a.json"
    csv_path = run_dir / "controlled_kpi_run-a.csv"
    db_path = run_dir / "controlled_kpi_after_run-a.db"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "params": {
                    "variant_only": "after",
                    "use_mock": False,
                },
                "after": {
                    "variant": "after",
                    "process_returncode": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    csv_path.write_text("variant,trade_count\nafter,1\n", encoding="utf-8")
    db_path.write_text("db", encoding="utf-8")
    manifest_path = manifest_dir / "official_accepted_corpus_manifest.json"
    manifest_rel = manifest_path.relative_to(tmp_path).as_posix()
    manifest_path.write_text(
        json.dumps(
            {
                "report_type": "zol0_accepted_corpus_manifest",
                "source_scorecard_path": "analysis/zol0_profitability_audit_scorecard.json",
                "bundle_dir": "artifacts/accepted_corpus/official",
                "scope": {
                    "exchange": "KuCoin",
                    "mode": "PAPER_ONLY",
                    "variant": "after",
                    "live_in_scope": False,
                },
                "selection": {
                    "selection_source": "accepted_manifest",
                    "accepted_run_count": 1,
                    "accepted_run_ids": ["run-a"],
                    "required_limit": 1,
                },
                "bundle_validation": {
                    "accepted_run_count_matches_scorecard": True,
                    "all_source_artifacts_present": True,
                    "all_source_artifacts_nonzero": True,
                    "all_bundled_hashes_match_source": True,
                    "all_bundled_result_after_only": True,
                    "all_bundled_result_use_mock_false": True,
                    "all_bundled_result_process_ok": True,
                },
                "entries": [
                    {
                        "run_id": "run-a",
                        "bundled_artifacts": {
                            "result_json": {
                                "path": result_path.relative_to(tmp_path).as_posix()
                            },
                            "csv": {
                                "path": csv_path.relative_to(tmp_path).as_posix()
                            },
                            "db": {
                                "path": db_path.relative_to(tmp_path).as_posix()
                            },
                        },
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    scorecard_path = analysis_dir / "zol0_profitability_audit_scorecard.json"
    _write_json(
        scorecard_path,
        {
            "global_kpis": {
                "total_trade_count": total_trade_count,
                "avg_profit_factor": 1.1,
                "avg_net_pnl": 0.01,
            },
            "metadata": {
                "selection": {
                    "selection_source": "accepted_manifest",
                    "accepted_run_count": 1,
                    "accepted_run_ids": ["run-a"],
                    "accepted_manifest_path": manifest_rel,
                },
                "sources": {
                    "accepted_corpus_manifest_path": manifest_rel,
                },
            },
        },
    )
    _write_json(
        analysis_dir / gate.STRICT_CORPUS_STATUS_CURRENT_NAME,
        {
            "classification": "ACCEPTED_CORPUS_READY",
            "strict_gate_inventory": {"accepted_run_count": 1},
            "collection_standard": {"required_accepted_runs": 1},
            "pass_fail_criteria": {"accepted_20_of_20_after_runs": True},
        },
    )
    return manifest_path


def test_paper_env_is_fail_closed_contract():
    env = gate._paper_env()
    assert env["LIVE"] == "0"
    assert env["BOT_MODE"] == "paper"
    assert env["PAPER_RUN_ONCE"] == "1"
    assert env["USE_MOCK"] == "0"
    assert env["ZOL0_ALLOW_MOCK"] == "0"
    assert str(env.get("ZOL0_TOKEN") or "").strip()


def test_paper_env_overrides_parent_mock_flags(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "1")
    monkeypatch.setenv("ZOL0_ALLOW_MOCK", "1")

    env = gate._paper_env()

    assert env["USE_MOCK"] == "0"
    assert env["ZOL0_ALLOW_MOCK"] == "0"


def test_classifies_entry_admission_contract_failure():
    exc = RuntimeError(
        "controlled_kpi_entry_admission_contract_failed for run rc=1 "
        "artifact=artifacts/diagnostics/contract.json "
        "reasons=NO_ELIGIBLE_ENTRY_BUCKETS"
    )

    assert gate._classify_run_exception(exc) == "ENTRY_ADMISSION_CONTRACT_FAIL"


def test_classify_run_exception_falls_back_for_unknown_error():
    assert gate._classify_run_exception(RuntimeError("something else")) == "READINESS_RUN_EXCEPTION"


def test_parses_entry_admission_contract_artifact_from_exception():
    path = gate._parse_entry_admission_contract_json_path(
        "controlled_kpi_entry_admission_contract_failed "
        "artifact=artifacts/diagnostics/contract.json "
        "reasons=NO_ELIGIBLE_ENTRY_BUCKETS"
    )

    assert path == gate._resolve_repo_path("artifacts/diagnostics/contract.json")


def test_parse_report_json_path_and_missing_path():
    assert gate._parse_report_json_path("REPORT_JSON=results/out.json") == gate._resolve_repo_path("results/out.json")
    with pytest.raises(RuntimeError, match="controlled_kpi_run_missing_report_json"):
        gate._parse_report_json_path("no report here")


def test_parse_entry_admission_contract_json_path_and_none():
    assert gate._parse_entry_admission_contract_json_path(
        "ENTRY_ADMISSION_CONTRACT_JSON=artifacts/diagnostics/contract.json"
    ) == gate._resolve_repo_path("artifacts/diagnostics/contract.json")
    assert gate._parse_entry_admission_contract_json_path("artifact=artifacts/diagnostics/contract.json") == gate._resolve_repo_path("artifacts/diagnostics/contract.json")
    assert gate._parse_entry_admission_contract_json_path("nothing useful") is None


def test_accepted_manifest_rejects_source_scorecard_outside_workdir(tmp_path):
    manifest_path = tmp_path / "test_generated_manifest.json"
    _write_json(
        manifest_path,
        {
            "report_type": "zol0_accepted_corpus_manifest",
            "source_scorecard_path": str(tmp_path.parent / "outside_scorecard.json"),
            "bundle_dir": "artifacts/accepted_corpus/test_generated",
            "scope": {
                "exchange": "KuCoin",
                "mode": "PAPER_ONLY",
                "variant": "after",
                "live_in_scope": False,
            },
            "selection": {
                "accepted_run_ids": ["run-a"],
                "accepted_run_count": 1,
            },
            "bundle_validation": {
                "accepted_run_count_matches_scorecard": True,
                "all_source_artifacts_present": True,
                "all_source_artifacts_nonzero": True,
                "all_bundled_hashes_match_source": True,
                "all_bundled_result_after_only": True,
                "all_bundled_result_use_mock_false": True,
                "all_bundled_result_process_ok": True,
            },
            "entries": [],
        },
    )

    _, reasons, _, _, details = gate._accepted_artifacts_from_manifest(
        str(manifest_path),
        ["run-a"],
        gate.WORKDIR / "analysis" / "scorecard.json",
    )

    assert "ACCEPTED_MANIFEST_SOURCE_SCORECARD_OUTSIDE_WORKDIR" in reasons
    assert "ACCEPTED_MANIFEST_SOURCE_SCORECARD_MISMATCH" in reasons
    assert details["accepted_manifest_source_scorecard_path"]


def test_safe_scalar_helpers_and_path_scoping(tmp_path):
    assert gate._safe_float("3.5") == 3.5
    assert gate._safe_float("bad", default=1.25) == 1.25
    assert gate._safe_int("7") == 7
    assert gate._safe_int("bad", default=11) == 11
    inside = tmp_path / "inside.txt"
    inside.write_text("x", encoding="utf-8")
    assert gate._path_is_within(inside, tmp_path) is True
    assert gate._path_is_within(tmp_path.parent / "outside.txt", tmp_path) is False


def test_check_run_fails_when_use_mock_true(tmp_path):
    bundle = _build_after_bundle(tmp_path, "run_use_mock", use_mock=True)
    ok, errors, checks = gate._check_run(bundle, {})

    assert ok is False
    assert "use_mock_not_false" in errors
    assert checks["use_mock_false"] is False


def test_check_run_classifies_diagnostic_no_open_run(tmp_path):
    bundle = _build_after_bundle(
        tmp_path,
        "run_diagnostic",
        paper_auto_open=False,
    )
    ok, errors, checks = gate._check_run(bundle, {})

    assert ok is False
    assert "paper_auto_open_false" in errors
    assert "diagnostic_no_open_run" in errors
    assert checks["paper_auto_open_true"] is False
    assert checks["diagnostic_no_open_run"] is True
    assert checks["paper_validation_classification"] == "DIAGNOSTIC_NO_OPEN_RUN"


def test_load_corpus_contract_uses_scorecard_manifest_not_latest_artifact(
    monkeypatch,
    tmp_path,
):
    manifest_path = _write_manifest_fixture(tmp_path, total_trade_count=1)
    latest_dir = tmp_path / "artifacts" / "accepted_corpus" / "canonical_replay_contract_latest"
    latest_dir.mkdir(parents=True)
    _write_json(
        latest_dir / "canonical_replay_contract_accepted_corpus_manifest.json",
        {
            "report_type": "zol0_accepted_corpus_manifest",
            "source_scorecard_path": str(tmp_path.parent / "pytest_scorecard.json"),
            "selection": {"accepted_run_ids": ["other"]},
        },
    )
    monkeypatch.setattr(gate, "WORKDIR", tmp_path)
    monkeypatch.setattr(gate, "ANALYSIS_DIR", tmp_path / "analysis")

    contract = gate._load_corpus_contract()

    assert contract["status"] == "PASS"
    assert contract["accepted_manifest_path"] == str(manifest_path)
    assert "canonical_replay_contract_latest" not in contract["accepted_manifest_path"]
    assert "ACCEPTED_MANIFEST_SOURCE_SCORECARD_OUTSIDE_WORKDIR" not in contract["reason_codes"]


def test_load_corpus_contract_fails_zero_trade_scorecard(monkeypatch, tmp_path):
    _write_manifest_fixture(tmp_path, total_trade_count=0)
    monkeypatch.setattr(gate, "WORKDIR", tmp_path)
    monkeypatch.setattr(gate, "ANALYSIS_DIR", tmp_path / "analysis")

    contract = gate._load_corpus_contract()

    assert contract["status"] == "UNCONFIRMED"
    assert "ACCEPTED_CORPUS_ZERO_TRADES" in contract["reason_codes"]
    assert contract["accepted_corpus_total_trade_count"] == 0


def test_check_run_fails_on_before_or_mixed_sources(tmp_path):
    bundle_before = _build_after_bundle(tmp_path, "run_before", include_before=True)
    ok_before, errors_before, _ = gate._check_run(bundle_before, {})

    bundle_mixed = _build_after_bundle(
        tmp_path,
        "run_mixed",
        variant_only="both",
        variants_run=["before", "after"],
    )
    ok_mixed, errors_mixed, _ = gate._check_run(bundle_mixed, {})

    assert ok_before is False
    assert "report_not_after_only" in errors_before
    assert ok_mixed is False
    assert "report_not_after_only" in errors_mixed


def test_check_run_fails_on_forbidden_artifact_names(tmp_path):
    bundle = _build_after_bundle(tmp_path, "run_forbidden", forbidden_names=True)
    ok, errors, checks = gate._check_run(bundle, {})

    assert ok is False
    assert "forbidden_shared_artifact_name" in errors
    assert checks["forbidden_shared_names_detected"] is True


def test_check_run_fails_on_shared_artifact_paths(tmp_path):
    registry = {}
    first = _build_after_bundle(tmp_path, "run_one", shared_prefix="shared_paths")
    second = _build_after_bundle(tmp_path, "run_one", shared_prefix="shared_paths")

    ok_first, errors_first, _ = gate._check_run(first, registry)
    ok_second, errors_second, checks_second = gate._check_run(second, registry)

    assert ok_first is True
    assert errors_first == []
    assert ok_second is False
    assert "shared_artifact_path" in errors_second
    assert checks_second.get("duplicate_path_hits")


def test_gate_do_not_promote_when_corpus_unconfirmed(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "PAPER_REPORT_DIR", tmp_path / "paper_reports")

    def fake_run(symbols, run_id, summary_hours):
        return _build_after_bundle(tmp_path, run_id)

    monkeypatch.setattr(gate, "_run_controlled_kpi", fake_run)
    monkeypatch.setattr(
        gate,
        "_load_corpus_contract",
        lambda: _corpus_contract_stub(
            status="UNCONFIRMED",
            reason_codes=["STRICT_FRESH_CORPUS_STATUS_MISSING"],
        ),
    )
    monkeypatch.setattr(
        gate,
        "_load_bootstrap_contract",
        lambda corpus_contract: _bootstrap_contract_stub(
            status="UNCONFIRMED",
            reason_codes=["BOOTSTRAP_MANIFEST_MISSING"],
        ),
    )

    report = gate.run_gate()

    assert report["operational_gate_status"] == "PASS"
    assert report["economic_channel"]["status"] == "UNCONFIRMED"
    assert report["paper_ready"] is False
    assert report["global_verdict"] == "DO_NOT_PROMOTE"
    assert "ECONOMICS_UNCONFIRMED" in report["global_reason_codes"]


def test_gate_promote_candidate_for_valid_exact_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "PAPER_REPORT_DIR", tmp_path / "paper_reports")

    def fake_run(symbols, run_id, summary_hours):
        return _build_after_bundle(tmp_path, run_id, use_mock=False)

    monkeypatch.setattr(gate, "_run_controlled_kpi", fake_run)
    monkeypatch.setattr(
        gate,
        "_load_corpus_contract",
        lambda: {
            **_corpus_contract_stub(status="PASS", reason_codes=[]),
            "scorecard_path": str(tmp_path / "analysis" / "scorecard.json"),
        },
    )
    monkeypatch.setattr(
        gate,
        "_load_bootstrap_contract",
        lambda corpus_contract: _bootstrap_contract_stub(
            status="PASS",
            reason_codes=[],
        ),
    )
    monkeypatch.setattr(
        gate,
        "_load_economics_context",
        lambda corpus_contract: {
            "status": "AVAILABLE",
            "go_no_go": "GO",
            "reason_codes": ["EXACT_CORPUS_EVIDENCE_AVAILABLE", "SCORECARD_GO"],
            "scorecard_path": corpus_contract.get("scorecard_path"),
            "accepted_run_count": corpus_contract.get("accepted_run_count"),
            "required_accepted_runs": corpus_contract.get("required_accepted_runs"),
        },
    )

    report = gate.run_gate()

    assert report["operational_gate_status"] == "PASS"
    assert report["economic_channel"]["status"] == "PASS"
    assert report["paper_ready"] is True
    assert report["global_verdict"] == "PROMOTE_CANDIDATE"
    assert report["evidence_contract_version"] == "paper_readiness_v2"
    assert report["evidence_scope"]["exchange"] == "kucoin"
    assert report["evidence_scope"]["mode"] == "paper"
    assert report["evidence_scope"]["variant"] == "after"
    assert report["evidence_scope"]["market_data"] == "real"
    assert len(report["runs"]) == len(gate.RUN_MATRIX)


def test_run_matrix_includes_targeted_xrp_corridor():
    assert any(
        run.get("run_id") == "paper_gate_run_d_xrp" and run.get("symbols") == "XRPUSDTM"
        for run in gate.RUN_MATRIX
    )


def test_report_keeps_legacy_top_level_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "PAPER_REPORT_DIR", tmp_path / "paper_reports")

    def fake_run(symbols, run_id, summary_hours):
        return _build_after_bundle(tmp_path, run_id)

    monkeypatch.setattr(gate, "_run_controlled_kpi", fake_run)
    monkeypatch.setattr(
        gate,
        "_load_corpus_contract",
        lambda: _corpus_contract_stub(
            status="UNCONFIRMED",
            reason_codes=["SCORECARD_MISSING"],
        ),
    )
    monkeypatch.setattr(
        gate,
        "_load_bootstrap_contract",
        lambda corpus_contract: _bootstrap_contract_stub(
            status="UNCONFIRMED",
            reason_codes=["BOOTSTRAP_MANIFEST_MISSING"],
        ),
    )

    report = gate.run_gate()

    assert "paper_ready" in report
    assert "global_verdict" in report
    assert "per_run_checks" in report
    assert isinstance(report["per_run_checks"], list)


def test_resolve_alpha_bootstrap_runtime_contract_prefers_explicit_field():
    report = {
        "alpha_bootstrap_runtime_contract": {
            "status": "FAIL_CLOSED",
            "reason_codes": ["source_fail_closed"],
        },
        "alpha_bootstrap_refresh": {
            "source_fail_closed": False,
            "reason_codes": [],
        },
    }

    resolved = gate._resolve_alpha_bootstrap_runtime_contract(report)

    assert resolved["status"] == "FAIL_CLOSED"
    assert resolved["source"] == "explicit_alpha_bootstrap_runtime_contract"
    assert resolved["reason_codes"] == ["source_fail_closed"]


def test_resolve_alpha_bootstrap_runtime_contract_fallback_refresh():
    report = {
        "alpha_bootstrap_refresh": {
            "source_fail_closed": True,
            "reason_codes": ["refresh_not_run"],
        }
    }

    resolved = gate._resolve_alpha_bootstrap_runtime_contract(report)

    assert resolved["status"] == "FAIL_CLOSED"
    assert resolved["source"] == "fallback_alpha_bootstrap_refresh"
    assert resolved["reason_codes"] == ["source_fail_closed", "refresh_not_run"]


def test_resolve_alpha_bootstrap_runtime_contract_fallback_after_env():
    report = {
        "params": {
            "after_env_overrides": {
                "ALPHA_WHITELIST_ENABLE": "0",
                "ALPHA_WHITELIST_COLDSTART_ALLOW": "0",
                "ALPHA_WHITELIST_FALLBACK_ENABLE": "0",
                "ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS": "0",
            }
        }
    }

    resolved = gate._resolve_alpha_bootstrap_runtime_contract(report)

    assert resolved["status"] == "FAIL_CLOSED"
    assert resolved["source"] == "fallback_after_env_overrides"
    assert resolved["reason_codes"] == ["source_fail_closed_inferred_from_after_env"]


def test_resolve_forced_cycle_trigger_contract_prefers_explicit_field():
    after_report = {
        "post_promotion_forced_cycle_trigger_contract": {
            "active": True,
            "status": "mismatch",
            "ok": False,
            "reason_codes": ["forced_cycle_trigger_mode_mismatch"],
        }
    }

    resolved = gate._resolve_forced_cycle_trigger_contract(after_report)

    assert resolved["status"] == "MISMATCH"
    assert (
        resolved["source"]
        == "explicit_post_promotion_forced_cycle_trigger_contract"
    )
    assert resolved["reason_codes"] == ["forced_cycle_trigger_mode_mismatch"]


def test_resolve_forced_cycle_trigger_contract_fallback_ok_after_enqueue_failure():
    after_report = {
        "post_promotion_forced_cycle_requested": True,
        "post_promotion_forced_cycle_trigger_mode": "after_reeval_enqueue_failure",
        "post_promotion_forced_cycle_request_reason": (
            "post_promotion_forced_cycle_after_enqueue_failure"
        ),
        "post_promotion_reeval_completed": False,
        "post_promotion_reeval_result": "request_enqueue_failed",
    }

    resolved = gate._resolve_forced_cycle_trigger_contract(after_report)

    assert resolved["status"] == "OK"
    assert resolved["source"] == "fallback_after_report_fields"
    assert resolved["reason_codes"] == []


def test_check_run_fails_when_forced_cycle_trigger_contract_invalid(tmp_path):
    bundle = _build_after_bundle(tmp_path, "run_forced_cycle_contract_invalid")
    bundle["after_report"]["post_promotion_forced_cycle_trigger_contract"] = {
        "active": True,
        "status": "mismatch",
        "ok": False,
        "reason_codes": ["forced_cycle_trigger_mode_mismatch"],
    }

    ok, errors, checks = gate._check_run(bundle, {})

    assert ok is False
    assert "post_promotion_forced_cycle_trigger_contract_invalid" in errors
    assert checks["post_promotion_forced_cycle_trigger_contract_valid"] is False
    assert checks["post_promotion_forced_cycle_trigger_contract_status"] == "MISMATCH"


def test_build_artifact_contract_flags_forced_cycle_trigger_contract_mismatch():
    per_run_checks = [
        {
            "run_id": "run_a",
            "ok": True,
            "errors": [],
            "checks": {
                "after_db_nonzero": True,
                "report_after_only": True,
                "post_promotion_forced_cycle_trigger_contract_valid": True,
            },
        },
        {
            "run_id": "run_b",
            "ok": False,
            "errors": ["post_promotion_forced_cycle_trigger_contract_invalid"],
            "checks": {
                "after_db_nonzero": True,
                "report_after_only": True,
                "post_promotion_forced_cycle_trigger_contract_valid": False,
                "post_promotion_forced_cycle_trigger_contract_status": "MISMATCH",
                "post_promotion_forced_cycle_trigger_contract_reason_codes": [
                    "forced_cycle_trigger_mode_mismatch"
                ],
            },
        },
        {
            "run_id": "run_c",
            "ok": True,
            "errors": [],
            "checks": {
                "after_db_nonzero": True,
                "report_after_only": True,
                "post_promotion_forced_cycle_trigger_contract_valid": True,
                },
            },
            {
                "run_id": "run_d",
                "ok": True,
                "errors": [],
                "checks": {
                    "after_db_nonzero": True,
                    "report_after_only": True,
                    "post_promotion_forced_cycle_trigger_contract_valid": True,
                },
            },
        ]

    artifact_contract = gate._build_artifact_contract(per_run_checks)

    assert artifact_contract["all_forced_cycle_trigger_contracts_valid"] is False
    assert (
        "POST_PROMOTION_FORCED_CYCLE_TRIGGER_CONTRACT_INVALID"
        in artifact_contract["reason_codes"]
    )
    assert len(artifact_contract["forced_cycle_trigger_contract_invalid_runs"]) == 1
    assert (
        artifact_contract["forced_cycle_trigger_contract_invalid_runs"][0]["run_id"]
        == "run_b"
    )


def test_build_artifact_contract_passes_when_forced_cycle_trigger_contract_valid():
    per_run_checks = [
        {
            "run_id": "run_a",
            "ok": True,
            "errors": [],
            "checks": {
                "after_db_nonzero": True,
                "report_after_only": True,
                "post_promotion_forced_cycle_trigger_contract_valid": True,
            },
        },
        {
            "run_id": "run_b",
            "ok": True,
            "errors": [],
            "checks": {
                "after_db_nonzero": True,
                "report_after_only": True,
                "post_promotion_forced_cycle_trigger_contract_valid": True,
            },
        },
        {
            "run_id": "run_c",
            "ok": True,
            "errors": [],
            "checks": {
                "after_db_nonzero": True,
                "report_after_only": True,
                "post_promotion_forced_cycle_trigger_contract_valid": True,
            },
        },
        {
            "run_id": "run_d",
            "ok": True,
            "errors": [],
            "checks": {
                "after_db_nonzero": True,
                "report_after_only": True,
                "post_promotion_forced_cycle_trigger_contract_valid": True,
            },
        },
    ]

    artifact_contract = gate._build_artifact_contract(per_run_checks)

    assert artifact_contract["all_forced_cycle_trigger_contracts_valid"] is True
    assert (
        "POST_PROMOTION_FORCED_CYCLE_TRIGGER_CONTRACT_INVALID"
        not in artifact_contract["reason_codes"]
    )
    assert artifact_contract["forced_cycle_trigger_contract_invalid_runs"] == []


def test_main_writes_requested_outputs_and_respects_return_code(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "PAPER_REPORT_DIR", tmp_path / "paper_reports")

    report = {
        "paper_ready": True,
        "global_verdict": "PROMOTE_CANDIDATE",
        "evidence_contract_version": "paper_readiness_v2",
        "operational_gate_status": "PASS",
        "operational_channel": {"status": "PASS", "reason_codes": ["OPERATIONAL_GATE_PASS"]},
        "economic_channel": {"status": "PASS", "go_no_go": "GO", "reason_codes": []},
        "artifact_contract": {
            "unique_paths_ok": True,
            "forbidden_shared_names_detected": False,
            "all_after_dbs_nonzero": True,
            "all_reports_after_only": True,
            "all_forced_cycle_trigger_contracts_valid": True,
            "reason_codes": [],
        },
        "corpus_contract": {
            "status": "PASS",
            "reason_codes": [],
            "scorecard_path": "analysis/scorecard.json",
            "strict_corpus_status_path": "analysis/strict.json",
            "accepted_artifacts_present": True,
            "accepted_artifacts_nonzero": True,
            "accepted_artifact_source": "accepted_manifest",
            "accepted_manifest_path": "artifacts/manifest.json",
            "accepted_corpus_bundle_dir": "artifacts/bundle",
            "accepted_manifest_hash_mismatch_count": 0,
            "accepted_run_count": 3,
            "required_accepted_runs": 3,
        },
        "bootstrap_contract": {
            "status": "PASS",
            "reason_codes": [],
            "manifest_path": "artifacts/bootstrap.json",
            "source_scorecard_path": "analysis/scorecard.json",
            "bundle_dir": "artifacts/bundle",
            "db_path": "artifacts/bootstrap.db",
            "report_path": "artifacts/bootstrap_report.json",
            "rows_inserted": 1,
            "pairs_selected": 1,
            "positive_side_allowlist": ["ETHUSDTM:TRENDFOLLOWING:buy"],
        },
        "runs": [],
        "aggregate_checks": {},
        "economics_context": {
            "status": "PASS",
            "go_no_go": "GO",
            "avg_profit_factor": 1.5,
            "avg_net_pnl": 0.01,
            "profitable_run_rate": 1.0,
            "pf_gt_1_rate": 1.0,
            "accepted_run_count": 3,
            "required_accepted_runs": 3,
            "scorecard_path": "analysis/scorecard.json",
        },
        "global_reason_codes": [],
        "next_allowed_step": "STEP_10",
    }

    monkeypatch.setattr(gate, "run_gate", lambda: report)

    json_out = tmp_path / "out" / "gate.json"
    md_out = tmp_path / "out" / "gate.md"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    rc = gate.main(["--json-out", str(json_out), "--md-out", str(md_out)])

    assert rc == 0
    assert json.loads(json_out.read_text(encoding="utf-8"))["paper_ready"] is True
    assert "PROMOTE_CANDIDATE" in md_out.read_text(encoding="utf-8")


def test_main_returns_one_when_report_not_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "run_gate", lambda: {"paper_ready": False, "global_verdict": "DO_NOT_PROMOTE"})
    rc = gate.main([])
    assert rc == 1
