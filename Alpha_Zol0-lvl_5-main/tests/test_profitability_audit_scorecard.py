import csv
import hashlib
import json
import importlib.util
import sqlite3
from pathlib import Path
from tempfile import mkdtemp

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "profitability_audit_scorecard.py"


@pytest.fixture(autouse=True)
def _quarantine_generated_accepted_corpus(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "ZOL0_ACCEPTED_CORPUS_DIR",
        str(tmp_path / "artifacts" / "accepted_corpus"),
    )


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "profitability_audit_scorecard", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_manifest_inputs(module):
    scorecard_path = module.ANALYSIS_DIR / "zol0_profitability_audit_scorecard.json"
    assert scorecard_path.exists()
    scorecard = module._load_json(scorecard_path)

    global_kpis = scorecard.get("global_kpis") or {}
    if int(global_kpis.get("total_trade_count") or 0) <= 0:
        from test_locked_positive_subset_audit import _build_exact_corpus

        tmp_path = Path(mkdtemp(prefix="scorecard-fixture-"))
        trades = [
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "pnl": 0.02,
            }
            for _ in range(6)
        ] + [
            {
                "symbol": "ETHUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "pnl": -0.01,
            }
            for _ in range(4)
        ]
        scorecard_path, manifest_path = _build_exact_corpus(tmp_path, trades)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_entry = (manifest.get("entries") or [])[0]
        result_descriptor = (
            ((manifest_entry.get("bundled_artifacts") or {}).get("result_json"))
            or {}
        )
        db_descriptor = (
            ((manifest_entry.get("bundled_artifacts") or {}).get("db")) or {}
        )
        result_path = Path(str(result_descriptor.get("path") or ""))
        alpha_history_db_path = Path(
            str(db_descriptor.get("path") or "")
        )
        result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        result_after = result_payload.setdefault("after", {})
        result_after["db_exists"] = True
        result_after["started_at_utc"] = "2026-04-10T00:00:00+00:00"
        result_after["ended_at_utc"] = "2026-04-10T00:01:00+00:00"
        result_path.write_text(
            json.dumps(result_payload, indent=2),
            encoding="utf-8",
        )
        result_bytes = result_path.read_bytes()
        result_descriptor["size_bytes"] = len(result_bytes)
        result_descriptor["sha256"] = hashlib.sha256(result_bytes).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )
        bootstrap_report_path = tmp_path / "bootstrap_report.json"
        bootstrap_report_path.write_text(
            json.dumps(
                {
                    "pair_stats_top": [
                        {
                            "selected": True,
                            "symbol": "ETHUSDTM",
                            "strategy": "TrendFollowing",
                            "trade_count": 10,
                            "winrate": 0.6,
                            "expectancy": 0.008,
                        }
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return (
            scorecard_path,
            manifest_path,
            ("2026-04-10",),
            1,
            bootstrap_report_path,
            alpha_history_db_path,
        )

    metadata = scorecard.get("metadata") or {}
    selection = metadata.get("selection") or {}
    sources = metadata.get("sources") or {}

    bootstrap_report_path = module._resolve_repo_path(
        str(sources.get("bootstrap_report_path") or "").strip()
    )
    alpha_history_db_path = module._resolve_repo_path(
        str(sources.get("alpha_history_db_path") or "").strip()
    )
    assert bootstrap_report_path.exists()
    assert alpha_history_db_path.exists()

    manifest_rel = str(
        sources.get("accepted_corpus_manifest_path")
        or selection.get("accepted_manifest_path")
        or ""
    ).strip()
    assert manifest_rel
    manifest_path = module._resolve_repo_path(manifest_rel)
    assert manifest_path.exists()

    allowed_dates = tuple(
        str(item).strip()
        for item in (selection.get("allowed_dates") or [])
        if str(item).strip()
    )
    if not allowed_dates:
        allowed_dates = tuple(
            str(item).strip()
            for item in (selection.get("accepted_dates") or [])
            if str(item).strip()
        )
    assert allowed_dates

    accepted_run_count = int(selection.get("accepted_run_count") or 0)
    if accepted_run_count <= 0:
        accepted_run_count = len(selection.get("accepted_run_ids") or [])
    assert accepted_run_count > 0

    return (
        scorecard_path,
        manifest_path,
        allowed_dates,
        accepted_run_count,
        bootstrap_report_path,
        alpha_history_db_path,
    )


def _results_dir_from_manifest(module, manifest_path: Path) -> Path:
    manifest = module._load_json(manifest_path)
    manifest_entry = (manifest.get("entries") or [])[0]
    result_descriptor = (
        ((manifest_entry.get("bundled_artifacts") or {}).get("result_json")) or {}
    )
    return Path(str(result_descriptor.get("path") or "")).parent


def test_phase2_build_audit_from_manifest_contract():
    module = _load_module()
    (
        _,
        manifest_path,
        allowed_dates,
        accepted_run_count,
        bootstrap_report_path,
        alpha_history_db_path,
    ) = _resolve_manifest_inputs(module)
    results_dir = _results_dir_from_manifest(module, manifest_path)

    audit = module.build_audit(
        results_dir=results_dir,
        bootstrap_report_path=bootstrap_report_path,
        alpha_history_db_path=alpha_history_db_path,
        allowed_dates=allowed_dates,
        limit=accepted_run_count,
        accepted_manifest_path=manifest_path,
    )

    selection = (audit.get("metadata") or {}).get("selection") or {}
    checks = (
        (((audit.get("metadata") or {}).get("validation") or {}).get("checks"))
        or {}
    )

    assert selection.get("selection_source") == "accepted_manifest"
    assert int(selection.get("accepted_run_count") or 0) == accepted_run_count
    assert len(selection.get("accepted_run_ids") or []) == accepted_run_count
    assert audit["metadata"]["validation"]["all_passed"] is True
    assert checks.get("main_corpus_after_only") is True
    assert checks.get("main_corpus_real_price_only") is True
    assert checks.get("main_corpus_db_nonzero") is True


def test_phase2_manifest_persistence_has_hash_size_timestamp(tmp_path):
    module = _load_module()
    (
        _,
        manifest_path,
        allowed_dates,
        accepted_run_count,
        bootstrap_report_path,
        alpha_history_db_path,
    ) = _resolve_manifest_inputs(module)
    results_dir = _results_dir_from_manifest(module, manifest_path)

    audit = module.build_audit(
        results_dir=results_dir,
        bootstrap_report_path=bootstrap_report_path,
        alpha_history_db_path=alpha_history_db_path,
        allowed_dates=allowed_dates,
        limit=accepted_run_count,
        accepted_manifest_path=manifest_path,
    )
    _, _, manifest_json_path, manifest_md_path = module.write_outputs(
        audit,
        tmp_path / "analysis",
        stem="phase2_manifest_contract",
    )

    assert manifest_json_path.exists()
    assert manifest_md_path.exists()

    persisted = module._load_json(manifest_json_path)
    selection = persisted.get("selection") or {}
    validation = persisted.get("bundle_validation") or {}
    entries = persisted.get("entries") or []

    assert persisted.get("report_type") == "zol0_accepted_corpus_manifest"
    assert int(selection.get("accepted_run_count") or 0) == accepted_run_count
    assert len(entries) == accepted_run_count
    assert validation.get("all_source_artifacts_present") is True
    assert validation.get("all_source_artifacts_nonzero") is True
    assert validation.get("all_bundled_hashes_match_source") is True
    assert validation.get("all_bundled_result_after_only") is True
    assert validation.get("all_bundled_result_use_mock_false") is True
    assert validation.get("all_bundled_result_process_ok") is True

    for entry in entries:
        assert str(entry.get("run_id") or "").strip()
        bundled = entry.get("bundled_artifacts") or {}
        for artifact_key in ("result_json", "csv", "db"):
            descriptor = bundled.get(artifact_key) or {}
            assert str(descriptor.get("path") or "").strip()
            assert int(descriptor.get("size_bytes") or 0) > 0
            assert len(str(descriptor.get("sha256") or "")) == 64
            assert str(descriptor.get("mtime_utc") or "").strip()
        assert int((bundled.get("db") or {}).get("size_bytes") or 0) > 0


def test_candidate_after_row_coerces_string_use_mock(tmp_path):
    module = _load_module()
    json_path = tmp_path / "controlled_kpi_test_run.json"
    csv_path = json_path.with_suffix(".csv")
    db_path = tmp_path / "controlled_kpi_test_run.db"
    db_path.write_bytes(b"db")
    csv_rows = [
        {
            "variant": "after",
            "trade_count": "12",
            "net_pnl": "1.25",
            "winrate": "0.75",
            "max_drawdown": "0.10",
            "profit_factor": "1.50",
            "gross_profit": "2.00",
            "gross_loss_abs": "1.00",
            "decisions_count": "20",
            "duration_sec_actual": "60",
        }
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0].keys()))
        writer.writeheader()
        writer.writerows(csv_rows)

    payload = {
        "run_id": "run-use-mock-string",
        "params": {"use_mock": "false"},
        "after": {
            "variant": "after",
            "trade_count": 12,
            "net_pnl": 1.25,
            "winrate": 0.75,
            "max_drawdown": 0.10,
            "profit_factor": 1.50,
            "gross_profit": 2.00,
            "gross_loss_abs": 1.00,
            "decisions_count": 20,
            "duration_sec_actual": 60,
            "started_at_utc": "2026-04-12T00:00:00+00:00",
            "ended_at_utc": "2026-04-12T00:01:00+00:00",
            "db_path": str(db_path),
            "db_exists": "false",
            "process_returncode": 0,
            "log_health": {"error_count": 0},
        },
        "data_check": {"results": {"core": {"ok": True}}},
    }

    row = module._candidate_after_row(json_path, payload)

    assert row is not None
    assert row["use_mock"] is False
    assert row["db_exists"] is False
    assert row["data_check_all_ok"] is True


def test_data_check_all_ok_coerces_string_flags():
    module = _load_module()

    payload = {
        "data_check": {
            "results": {
                "core": {"ok": "true"},
                "risk": {"ok": "false"},
            }
        }
    }
    assert module._data_check_all_ok(payload) is False

    payload["data_check"]["results"]["risk"]["ok"] = "true"
    assert module._data_check_all_ok(payload) is True


def test_validate_report_coerces_string_truthy_fields():
    module = _load_module()
    candidate_runs = [{"trade_count": 1}]
    accepted_runs = [
        {
            "after": {"variant": "after"},
            "use_mock": False,
            "trade_count": 1,
            "started_date": "2026-04-12",
            "ended_date": "2026-04-12",
            "db_exists": True,
            "db_size_bytes": 1,
            "process_returncode": 0,
            "csv_alignment": {"ok": "true"},
        }
    ]
    areas = [{"weight": 100, "metrics": [1, 2, 3]}]
    appendix_invalid_corpus = {"excluded_from_scorecard": "true"}
    phase1_consistency = {"ok": "true"}

    validation = module._validate_report(
        candidate_runs=candidate_runs,
        accepted_runs=accepted_runs,
        areas=areas,
        appendix_invalid_corpus=appendix_invalid_corpus,
        phase1_consistency=phase1_consistency,
        allowed_dates=("2026-04-12",),
        limit=1,
    )

    checks = validation["checks"]
    assert checks["csv_json_alignment_ok"] is True
    assert checks["phase1_consistency_ok"] is True
    assert checks["appendix_excluded_from_scorecard"] is True
    assert validation["all_passed"] is True


def test_validate_report_rejects_zero_trade_accepted_corpus():
    module = _load_module()
    candidate_runs = [{"trade_count": 0}]
    accepted_runs = [
        {
            "after": {"variant": "after"},
            "use_mock": False,
            "trade_count": 0,
            "started_date": "2026-04-12",
            "ended_date": "2026-04-12",
            "db_exists": True,
            "db_size_bytes": 1,
            "process_returncode": 0,
            "csv_alignment": {"ok": True},
        }
    ]
    areas = [{"weight": 100, "metrics": [1, 2, 3]}]
    appendix_invalid_corpus = {"excluded_from_scorecard": True}
    phase1_consistency = {"ok": True}

    validation = module._validate_report(
        candidate_runs=candidate_runs,
        accepted_runs=accepted_runs,
        areas=areas,
        appendix_invalid_corpus=appendix_invalid_corpus,
        phase1_consistency=phase1_consistency,
        allowed_dates=("2026-04-12",),
        limit=1,
    )

    checks = validation["checks"]
    assert checks["main_corpus_has_closed_trades"] is False
    assert validation["all_passed"] is False


def test_persist_accepted_corpus_bundle_coerces_string_use_mock(tmp_path):
    module = _load_module()
    source_json_path = tmp_path / "controlled_kpi_run_use_mock_string.json"
    source_csv_path = source_json_path.with_suffix(".csv")
    source_db_path = tmp_path / "controlled_kpi_run_use_mock_string.db"
    source_db_path.write_bytes(b"db")
    csv_row = {
        "variant": "after",
        "trade_count": "12",
        "net_pnl": "1.25",
        "winrate": "0.75",
        "max_drawdown": "0.10",
        "profit_factor": "1.50",
        "gross_profit": "2.00",
        "gross_loss_abs": "1.00",
        "decisions_count": "20",
        "duration_sec_actual": "60",
    }
    with source_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_row.keys()))
        writer.writeheader()
        writer.writerow(csv_row)

    source_payload = {
        "run_id": "run-use-mock-string",
        "params": {"use_mock": "false"},
        "after": {
            "variant": "after",
            "trade_count": 12,
            "net_pnl": 1.25,
            "winrate": 0.75,
            "max_drawdown": 0.10,
            "profit_factor": 1.50,
            "gross_profit": 2.00,
            "gross_loss_abs": 1.00,
            "decisions_count": 20,
            "duration_sec_actual": 60,
            "started_at_utc": "2026-04-12T00:00:00+00:00",
            "ended_at_utc": "2026-04-12T00:01:00+00:00",
            "db_path": str(source_db_path),
            "db_exists": True,
            "process_returncode": 0,
            "log_health": {"error_count": 0},
        },
        "data_check": {"results": {"core": {"ok": True}}},
    }
    source_json_path.write_text(
        json.dumps(source_payload, indent=2),
        encoding="utf-8",
    )

    manifest_path = tmp_path / "accepted_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "run_id": "run-use-mock-string",
                        "bundled_artifacts": {
                            "result_json": {"path": str(source_json_path)},
                            "csv": {"path": str(source_csv_path)},
                            "db": {"path": str(source_db_path)},
                        },
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    audit = {
        "metadata": {
            "selection": {
                "selection_source": "accepted_manifest",
                "accepted_manifest_path": str(manifest_path),
                "accepted_run_ids": ["run-use-mock-string"],
                "accepted_run_count": 1,
                "required_limit": 1,
            }
        }
    }

    manifest, _, _ = module._persist_accepted_corpus_bundle(
        audit=audit,
        json_path=tmp_path / "scorecard.json",
        md_path=tmp_path / "scorecard.md",
        stem="use_mock_string",
    )

    validation = manifest.get("bundle_validation") or {}
    assert validation["all_bundled_result_use_mock_false"] is True


def test_phase2_roundtrip_scorecard_from_generated_manifest(tmp_path):
    module = _load_module()
    (
        _,
        manifest_path,
        allowed_dates,
        accepted_run_count,
        bootstrap_report_path,
        alpha_history_db_path,
    ) = _resolve_manifest_inputs(module)
    results_dir = _results_dir_from_manifest(module, manifest_path)

    baseline_audit = module.build_audit(
        results_dir=results_dir,
        bootstrap_report_path=bootstrap_report_path,
        alpha_history_db_path=alpha_history_db_path,
        allowed_dates=allowed_dates,
        limit=accepted_run_count,
        accepted_manifest_path=manifest_path,
    )
    _, _, generated_manifest_json_path, _ = module.write_outputs(
        baseline_audit,
        tmp_path / "analysis",
        stem="phase2_roundtrip",
    )

    replay_audit = module.build_audit(
        results_dir=results_dir,
        bootstrap_report_path=bootstrap_report_path,
        alpha_history_db_path=alpha_history_db_path,
        allowed_dates=allowed_dates,
        limit=accepted_run_count,
        accepted_manifest_path=generated_manifest_json_path,
    )

    baseline_selection = (baseline_audit.get("metadata") or {}).get("selection") or {}
    replay_selection = (replay_audit.get("metadata") or {}).get("selection") or {}

    assert replay_selection.get("selection_source") == "accepted_manifest"
    assert replay_selection.get("accepted_run_ids") == baseline_selection.get(
        "accepted_run_ids"
    )
    assert replay_audit.get("global_kpis", {}).get("run_count") == baseline_audit.get(
        "global_kpis", {}
    ).get("run_count")
    assert replay_audit.get("global_kpis", {}).get(
        "total_trade_count"
    ) == baseline_audit.get("global_kpis", {}).get("total_trade_count")


def test_main_builds_scorecard_and_replays_explicit_manifest(tmp_path, capsys):
    module = _load_module()
    (
        _,
        manifest_path,
        allowed_dates,
        accepted_run_count,
        bootstrap_report_path,
        alpha_history_db_path,
    ) = _resolve_manifest_inputs(module)
    results_dir = _results_dir_from_manifest(module, manifest_path)

    analysis_dir = tmp_path / "analysis"
    output_stem = "cli_replay_contract"
    args = [
        "--results-dir",
        str(results_dir),
        "--bootstrap-report",
        str(bootstrap_report_path),
        "--alpha-history-db",
        str(alpha_history_db_path),
        "--analysis-dir",
        str(analysis_dir),
        "--limit",
        str(accepted_run_count),
        "--accepted-manifest",
        str(manifest_path),
        "--output-stem",
        output_stem,
    ]
    for allowed_date in allowed_dates:
        args.extend(["--allowed-date", allowed_date])

    rc = module.main(args)

    assert rc == 0
    output = capsys.readouterr().out
    assert "JSON=" in output
    assert "MARKDOWN=" in output
    assert "ACCEPTED_MANIFEST_JSON=" in output
    assert "ACCEPTED_MANIFEST_MD=" in output

    json_path = analysis_dir / f"{output_stem}_scorecard.json"
    md_path = analysis_dir / f"{output_stem}_report.md"
    assert json_path.exists()
    assert md_path.exists()

    scorecard = module._load_json(json_path)
    metadata = scorecard.get("metadata") or {}
    selection = metadata.get("selection") or {}
    sources = metadata.get("sources") or {}
    replay_contract = metadata.get("validation_contract_replay") or {}

    assert selection.get("selection_source") == "accepted_manifest"
    assert int(selection.get("accepted_run_count") or 0) == accepted_run_count
    assert replay_contract.get("status") == "PASS"
    assert replay_contract.get("contract") == "explicit_accepted_manifest_replay"
    assert str(sources.get("accepted_corpus_manifest_path") or "").strip()
    assert str(sources.get("accepted_corpus_bundle_dir") or "").strip()


def test_main_seed_replay_branch_emits_seed_artifacts(tmp_path, capsys):
    module = _load_module()
    (
        _,
        manifest_path,
        allowed_dates,
        accepted_run_count,
        bootstrap_report_path,
        alpha_history_db_path,
    ) = _resolve_manifest_inputs(module)
    results_dir = _results_dir_from_manifest(module, manifest_path)

    analysis_dir = tmp_path / "analysis_seed"
    output_stem = "cli_seed_contract"
    args = [
        "--results-dir",
        str(results_dir),
        "--bootstrap-report",
        str(bootstrap_report_path),
        "--alpha-history-db",
        str(alpha_history_db_path),
        "--analysis-dir",
        str(analysis_dir),
        "--limit",
        str(accepted_run_count),
        "--output-stem",
        output_stem,
    ]
    for allowed_date in allowed_dates:
        args.extend(["--allowed-date", allowed_date])

    rc = module.main(args)

    assert rc == 0
    output = capsys.readouterr().out
    assert "SEED_JSON=" in output
    assert "SEED_MARKDOWN=" in output
    assert "SEED_ACCEPTED_MANIFEST_JSON=" in output
    assert "SEED_ACCEPTED_MANIFEST_MD=" in output

    json_path = analysis_dir / f"{output_stem}_scorecard.json"
    md_path = analysis_dir / f"{output_stem}_report.md"
    assert json_path.exists()
    assert md_path.exists()

    scorecard = module._load_json(json_path)
    metadata = scorecard.get("metadata") or {}
    selection = metadata.get("selection") or {}
    replay_contract = metadata.get("validation_contract_replay") or {}

    assert selection.get("selection_source") == "accepted_manifest"
    assert int(selection.get("accepted_run_count") or 0) == accepted_run_count
    assert replay_contract.get("status") == "PASS"
    assert replay_contract.get("contract") == "explicit_accepted_manifest_replay"


def test_build_and_write_audit_rejects_non_manifest_replay(
    tmp_path,
    monkeypatch,
):
    module = _load_module()
    (
        _,
        manifest_path,
        allowed_dates,
        accepted_run_count,
        bootstrap_report_path,
        alpha_history_db_path,
    ) = _resolve_manifest_inputs(module)
    results_dir = _results_dir_from_manifest(module, manifest_path)

    real_build_audit = module.build_audit

    def fake_build_audit(
        *,
        results_dir,
        bootstrap_report_path,
        alpha_history_db_path,
        allowed_dates,
        limit,
        accepted_manifest_path,
    ):
        audit = real_build_audit(
            results_dir=results_dir,
            bootstrap_report_path=bootstrap_report_path,
            alpha_history_db_path=alpha_history_db_path,
            allowed_dates=allowed_dates,
            limit=limit,
            accepted_manifest_path=accepted_manifest_path,
        )
        if accepted_manifest_path is not None:
            metadata = audit.setdefault("metadata", {})
            selection = metadata.setdefault("selection", {})
            selection["selection_source"] = "results_scan"
        return audit

    monkeypatch.setattr(module, "build_audit", fake_build_audit)

    with pytest.raises(
        ValueError,
        match=(
            "canonical profitability scorecard must be built from explicit "
            "accepted manifest"
        ),
    ):
        module.build_and_write_audit(
            results_dir=results_dir,
            bootstrap_report_path=bootstrap_report_path,
            alpha_history_db_path=alpha_history_db_path,
            analysis_dir=tmp_path / "analysis_fail",
            allowed_dates=allowed_dates,
            limit=accepted_run_count,
            accepted_manifest_path=None,
            output_stem="broken_replay_contract",
        )


def test_canonical_write_replays_to_accepted_manifest(tmp_path):
    module = _load_module()
    (
        _,
        manifest_path,
        allowed_dates,
        accepted_run_count,
        bootstrap_report_path,
        alpha_history_db_path,
    ) = _resolve_manifest_inputs(module)
    results_dir = _results_dir_from_manifest(module, manifest_path)

    json_path, _, manifest_json_path, _, replay_artifacts = (
        module.build_and_write_audit(
            results_dir=results_dir,
            bootstrap_report_path=bootstrap_report_path,
            alpha_history_db_path=alpha_history_db_path,
            analysis_dir=tmp_path / "analysis",
            allowed_dates=allowed_dates,
            limit=accepted_run_count,
            accepted_manifest_path=None,
            output_stem="canonical_replay_contract",
        )
    )

    scorecard = module._load_json(json_path)
    selection = (scorecard.get("metadata") or {}).get("selection") or {}
    replay_contract = (scorecard.get("metadata") or {}).get(
        "validation_contract_replay"
    ) or {}
    labels = {label for label, _ in replay_artifacts}

    assert selection.get("selection_source") == "accepted_manifest"
    assert selection.get("accepted_manifest_path") == module._workspace_rel(
        manifest_json_path
    )
    assert replay_contract.get("status") == "PASS"
    assert replay_contract.get("contract") == "explicit_accepted_manifest_replay"
    assert "SEED_ACCEPTED_MANIFEST_JSON" in labels


def test_accepted_manifest_rejects_duplicate_run_ids(tmp_path):
    module = _load_module()
    (
        _,
        manifest_path,
        allowed_dates,
        accepted_run_count,
        bootstrap_report_path,
        alpha_history_db_path,
    ) = _resolve_manifest_inputs(module)
    results_dir = _results_dir_from_manifest(module, manifest_path)

    manifest = module._load_json(manifest_path)
    entries = list(manifest.get("entries") or [])
    assert entries
    duplicated_entry = dict(entries[0])
    duplicated_manifest = dict(manifest)
    duplicated_manifest["selection"] = dict(manifest.get("selection") or {})
    duplicated_manifest["selection"]["accepted_run_count"] = 2
    duplicated_manifest["selection"]["accepted_run_ids"] = [
        str(duplicated_entry.get("run_id") or "").strip(),
        str(duplicated_entry.get("run_id") or "").strip(),
    ]
    duplicated_manifest["selection"]["required_limit"] = 2
    duplicated_manifest["entries"] = [duplicated_entry, dict(duplicated_entry)]

    duplicate_manifest_path = tmp_path / "duplicate_accepted_manifest.json"
    duplicate_manifest_path.write_text(
        json.dumps(duplicated_manifest, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate run_id"):
        module.build_audit(
            results_dir=results_dir,
            bootstrap_report_path=bootstrap_report_path,
            alpha_history_db_path=alpha_history_db_path,
            allowed_dates=allowed_dates,
            limit=2,
            accepted_manifest_path=duplicate_manifest_path,
        )


def test_infer_problem_class_covers_all_outcomes():
    module = _load_module()

    assert module._infer_problem_class(0.6, 2.0, 1.0) == "pozytywny"
    assert module._infer_problem_class(0.5, None, 0.0) == "kosztowy"
    assert module._infer_problem_class(0.35, 0.9, -0.1) == "wyjsciowy"
    assert module._infer_problem_class(0.1, None, -0.1) == "wejsciowy"
    assert module._as_profit_factor("Infinity") == pytest.approx(float("inf"))


def test_aggregate_symbol_rankings_classifies_and_orders_symbols():
    module = _load_module()
    runs = [
        {
            "after": {
                "symbol_stats": {
                    "BTCUSDTM": {
                        "trade_count": 4,
                        "net_pnl": 1.2345678,
                        "wins": 3,
                        "losses": 1,
                        "gross_profit": 2.0,
                        "gross_loss_abs": 0.5,
                    },
                    "ETHUSDTM": {
                        "trade_count": 2,
                        "net_pnl": -0.25,
                        "wins": 2,
                        "losses": 3,
                        "gross_profit": 0.5,
                        "gross_loss_abs": 1.0,
                    },
                }
            }
        },
        {
            "after": {
                "symbol_stats": {
                    "BTCUSDTM": {
                        "trade_count": 1,
                        "net_pnl": -0.5,
                        "wins": 0,
                        "losses": 1,
                        "gross_profit": 0.0,
                        "gross_loss_abs": 0.5,
                    },
                    "XRPUSDTM": {
                        "trade_count": 1,
                        "net_pnl": 0.0,
                        "wins": 0,
                        "losses": 0,
                        "gross_profit": 0.0,
                        "gross_loss_abs": 0.0,
                    },
                }
            }
        },
    ]

    rankings = module._aggregate_symbol_rankings(runs)

    assert [row["name"] for row in rankings] == [
        "BTCUSDTM",
        "XRPUSDTM",
        "ETHUSDTM",
    ]
    btc = rankings[0]
    assert btc["runs"] == 2
    assert btc["trade_count"] == 5
    assert btc["dominant_issue"] == "pozytywny"
    assert btc["profit_factor"] == 2.0
    assert rankings[1]["dominant_issue"] == "wejsciowy"
    assert rankings[2]["dominant_issue"] == "wyjsciowy"


def test_load_alpha_bucket_rankings_reads_close_rows_and_skips_bad_json(tmp_path):
    module = _load_module()
    db_path = tmp_path / "alpha_history.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE logs (event TEXT, details TEXT)")
        conn.execute(
            "INSERT INTO logs (event, details) VALUES (?, ?)",
            (
                "position_close",
                json.dumps(
                    {
                        "position": {
                            "symbol": "BTCUSDTM",
                            "strategy": "TrendFollowing",
                            "realized_pnl": 1.5,
                        }
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO logs (event, details) VALUES (?, ?)",
            ("position_close", "not-json"),
        )
        conn.commit()
    finally:
        conn.close()

    rankings = module._load_alpha_bucket_rankings(db_path)

    assert len(rankings) == 1
    row = rankings[0]
    assert row["entity_type"] == "bucket"
    assert row["name"] == "BTCUSDTM|TrendFollowing"
    assert row["trade_count"] == 1
    assert row["net_pnl"] == 1.5
    assert row["dominant_issue"] == "pozytywny"


def test_load_alpha_bucket_rankings_raises_for_missing_db(tmp_path):
    module = _load_module()
    with pytest.raises(FileNotFoundError, match="alpha history db not found"):
        module._load_alpha_bucket_rankings(tmp_path / "missing.db")


def test_persist_accepted_corpus_bundle_rejects_missing_manifest_run_ids(tmp_path):
    module = _load_module()
    manifest_path = tmp_path / "accepted_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "run_id": "present-run",
                        "bundled_artifacts": {},
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    audit = {
        "metadata": {
            "selection": {
                "selection_source": "accepted_manifest",
                "accepted_manifest_path": str(manifest_path),
                "accepted_run_ids": ["present-run", "missing-run"],
                "accepted_run_count": 2,
                "required_limit": 2,
            }
        }
    }

    with pytest.raises(ValueError, match="missing selected run_ids"):
        module._persist_accepted_corpus_bundle(
            audit=audit,
            json_path=tmp_path / "scorecard.json",
            md_path=tmp_path / "scorecard.md",
            stem="missing_manifest_run_ids",
        )


def test_accepted_manifest_rejects_malformed_root(tmp_path):
    module = _load_module()
    manifest_path = tmp_path / "malformed_accepted_manifest.json"
    manifest_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(ValueError, match="accepted manifest malformed"):
        module._accepted_runs_from_manifest(
            manifest_path,
            allowed_dates=("2026-04-03",),
            limit=1,
        )


def test_score_areas_coerces_selected_string_flags(tmp_path):
    module = _load_module()
    bootstrap_report_path = tmp_path / "bootstrap_report.json"
    bootstrap_report_path.write_text("{}", encoding="utf-8")
    runs = [
        {
            "result_path": tmp_path / "run-1.json",
            "trade_count": 12,
            "conversion_rate": 0.04,
            "use_mock": False,
            "data_check_all_ok": True,
            "db_exists": True,
            "process_returncode": 0,
            "log_error_count": 0,
            "after": {
                "symbol_stats": {},
                "post_close_summary_grace_release_reason": "summary_emit_done",
            },
            "net_pnl": 10.0,
            "profit_factor": 1.2,
        }
    ]
    symbol_rankings = [{"net_pnl": 1.0}]
    bootstrap_report = {
        "pair_stats_top": [
            {
                "selected": "false",
                "symbol": "BTCUSDTM",
                "strategy": "sma_cross",
                "expectancy": -1.0,
                "winrate": 0.4,
            },
            {
                "selected": "true",
                "symbol": "ETHUSDTM",
                "strategy": "momentum",
                "expectancy": 2.5,
                "winrate": 0.7,
            },
        ]
    }
    phase1 = {
        "final_blocker_resolution": {
            "exit_quality_metrics": {
                "share_green_and_closed_green": 0.5,
                "share_green_then_closed_red": 0.25,
                "share_never_green": 0.1,
            }
        },
        "post_freeze_bucket_audit": {"bucket_ranking": []},
    }

    areas = module._score_areas(
        runs=runs,
        symbol_rankings=symbol_rankings,
        bootstrap_report=bootstrap_report,
        phase1=phase1,
        bootstrap_report_path=bootstrap_report_path,
    )
    alpha_area = next(area for area in areas if area["id"] == "AlphaSelection")
    metrics = {metric["name"]: metric["value"] for metric in alpha_area["metrics"]}

    assert metrics["share_selected_pairs_positive_expectancy"] == 1.0
    assert metrics["share_selected_pairs_winrate_ge_50pct"] == 1.0
    assert alpha_area["evidence"][0]["fact"].startswith("Bootstrap wybral 1 pary")


def test_build_audit_handles_missing_sources_field_gracefully(tmp_path):
    """
    P3-7 hardened contract: scorecard metadata missing 'sources' must still
    produce a valid locked-subset audit when manifest_path is passed
    explicitly.
    """
    import importlib.util as ilu
    from pathlib import Path as _Path
    from test_locked_positive_subset_audit import _build_exact_corpus

    root = _Path(__file__).resolve().parents[1]
    subset_path = root / "scripts" / "audit_locked_positive_subset.py"
    spec = ilu.spec_from_file_location("audit_locked_positive_subset_p37", subset_path)
    assert spec is not None and spec.loader is not None
    subset_mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(subset_mod)

    # Build a valid corpus for a minimal manifest
    trades = [
        {
            "symbol": "ETHUSDTM",
            "strategy": "TrendFollowing",
            "side": "buy",
            "pnl": 0.02,
        }
        for _ in range(6)
    ] + [
        {
            "symbol": "ETHUSDTM",
            "strategy": "TrendFollowing",
            "side": "buy",
            "pnl": -0.01,
        }
        for _ in range(4)
    ]
    scorecard_path, manifest_path = _build_exact_corpus(tmp_path, trades)

    # Rewrite the scorecard WITHOUT a 'sources' field in metadata
    import json
    scorecard = json.loads(scorecard_path.read_text())
    metadata = scorecard.get("metadata", {})
    metadata.pop("sources", None)  # remove sources if present
    scorecard["metadata"] = metadata
    scorecard_path.write_text(json.dumps(scorecard, indent=2))
    rewritten = json.loads(scorecard_path.read_text())
    assert "sources" not in (rewritten.get("metadata") or {})

    audit = subset_mod.build_audit(
        scorecard_path=scorecard_path,
        manifest_path=manifest_path,
    )
    assert audit["evidence_contract"]["status"] == "PASS"
    assert audit["subset_decision"]["verdict"] == "LOCKED_POSITIVE_SUBSET_FOUND"
    assert audit["subset_decision"]["locked_symbol_strategy_side_allowlist"] == [
        "ETHUSDTM:TRENDFOLLOWING:buy"
    ]
