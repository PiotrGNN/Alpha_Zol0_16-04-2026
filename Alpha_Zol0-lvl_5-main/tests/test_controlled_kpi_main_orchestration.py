import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "controlled_kpi_run.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("controlled_kpi_run", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch_workspace(monkeypatch, module, tmp_path):
    results_dir = tmp_path / "results"
    diagnostics_dir = tmp_path / "diagnostics"
    tmp_dir = tmp_path / "tmp"
    for directory in (results_dir, diagnostics_dir, tmp_dir):
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(module, "WORKDIR", tmp_path)
    monkeypatch.setattr(module, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(module, "DIAGNOSTICS_DIR", diagnostics_dir)
    monkeypatch.setattr(module, "TMP_DIR", tmp_dir)

    return results_dir, diagnostics_dir, tmp_dir


def _variant_metrics(variant, *, process_returncode=0, diagnostic_mode=False):
    trade_count = 6 if variant == "before" else 8
    return {
        "variant": variant,
        "db_path": f"/tmp/{variant}.db",
        "out_log": f"/tmp/{variant}.out.log",
        "err_log": f"/tmp/{variant}.err.log",
        "trade_count": trade_count,
        "net_pnl": 1.5 if variant == "before" else 3.25,
        "winrate": 0.40 if variant == "before" else 0.55,
        "max_drawdown": 0.20 if variant == "before" else 0.10,
        "profit_factor": 1.75 if variant == "before" else 2.50,
        "gross_profit": 4.0 if variant == "before" else 6.0,
        "gross_loss_abs": 1.0,
        "decisions_count": 3 if variant == "before" else 4,
        "equity_points": 5 if variant == "before" else 6,
        "duration_sec_actual": 7,
        "started_at_utc": "2026-04-13T00:00:00+00:00",
        "ended_at_utc": "2026-04-13T00:00:07+00:00",
        "log_health": {
            "error_count": 0 if process_returncode == 0 else 1,
            "sample_errors": ["controlled_kpi_run_stub_failure"]
            if process_returncode
            else [],
        },
        "diagnostic_env_flags": {
            "DIAGNOSTIC_MODE": "1" if diagnostic_mode else "0",
        },
        "effective_env_values": {},
        "process_returncode": process_returncode,
    }


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_main_before_only_prefers_prebuilt_source_and_writes_outputs(
    monkeypatch,
    tmp_path,
):
    module = _load_module()
    results_dir, diagnostics_dir, _ = _patch_workspace(monkeypatch, module, tmp_path)

    prebuilt_db_path = diagnostics_dir / "prebuilt_alpha_history.db"
    prebuilt_db_path.write_bytes(b"prebuilt-db")
    prebuilt_report_path = diagnostics_dir / "prebuilt_alpha_history_report.json"
    _write_json(
        prebuilt_report_path,
        {
            "pairs_selected": 1,
            "rows_inserted": 1,
            "pair_stats_top": [
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "trade_count": 15,
                    "expectancy": -0.01,
                    "winrate": 0.30,
                    "selected": True,
                },
                {
                    "symbol": "ETHUSDTM",
                    "strategy": "Momentum",
                    "trade_count": 8,
                    "expectancy": 0.02,
                    "winrate": 0.50,
                    "selected": False,
                },
                {
                    "symbol": "XRPUSDTM",
                    "strategy": "BadStrat",
                    "trade_count": 5,
                    "expectancy": -0.20,
                    "winrate": 0.20,
                    "selected": False,
                },
            ],
            "pair_side_stats_top": [
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                    "trade_count": 15,
                    "expectancy": 0.02,
                    "winrate": 0.60,
                    "gross_pnl": 1.0,
                    "fee_total": 0.2,
                },
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "sell",
                    "trade_count": 15,
                    "expectancy": -0.05,
                    "winrate": 0.60,
                    "gross_pnl": 1.0,
                    "fee_total": 0.2,
                },
                {
                    "symbol": "ETHUSDTM",
                    "strategy": "Momentum",
                    "side": "buy",
                    "trade_count": 12,
                    "expectancy": 0.04,
                    "winrate": 0.55,
                    "gross_pnl": 1.0,
                    "fee_total": 0.2,
                },
                {
                    "symbol": "ETHUSDTM",
                    "strategy": "Momentum",
                    "side": "sell",
                    "trade_count": 12,
                    "expectancy": -0.08,
                    "winrate": 0.20,
                    "gross_pnl": 0.5,
                    "fee_total": 0.3,
                },
                {
                    "symbol": "XRPUSDTM",
                    "strategy": "BadStrat",
                    "side": "buy",
                    "trade_count": 8,
                    "expectancy": -0.20,
                    "winrate": 0.10,
                    "gross_pnl": 0.4,
                    "fee_total": 0.2,
                },
            ],
        },
    )
    scorecard_path = tmp_path / "scorecards" / "controlled_kpi_scorecard.json"
    manifest_path = tmp_path / "analysis" / "prebuilt_manifest.json"

    block_calls = []
    run_calls = []
    refresh_calls = []

    def fake_block_mock_ohlcv_kucoin_paper_startup(**kwargs):
        block_calls.append(kwargs)

    def fake_run_data_integrity_checks(**kwargs):
        return {
            "skipped": False,
            "market_type": kwargs["market_type"],
            "timeframe": kwargs["timeframe"],
            "symbols": list(kwargs["symbols"]),
            "results": {
                "BTCUSDTM": {
                    "ok": True,
                    "count": 60,
                    "monotonic_ts": True,
                    "stale_sec": 0.0,
                }
            },
        }

    def fake_resolve_alpha_bootstrap_exact_source_contract(_accepted_scorecard_path):
        return {
            "active": True,
            "source_mode": "prebuilt_alpha_history_db",
            "prebuilt_alpha_history_db_path": str(prebuilt_db_path),
            "prebuilt_alpha_history_report_path": str(prebuilt_report_path),
            "scorecard_path": str(scorecard_path),
            "resolved_scorecard_path": str(scorecard_path.resolve()),
            "prebuilt_manifest_path": str(manifest_path),
            "accepted_run_ids": ["run-a"],
            "existing_run_ids": ["run-a"],
            "nonzero_run_ids": ["run-a"],
            "missing_run_ids": [],
            "exact_after_db_patterns": ["tmp/controlled_kpi_after_run-a.db"],
            "reason_codes": [],
        }

    def fake_refresh_alpha_bootstrap_history(**kwargs):
        refresh_calls.append(kwargs)
        pytest.fail("prebuilt-source routing should skip refresh helper")

    def fake_run_variant(variant, duration_sec, run_id, **kwargs):
        run_calls.append(
            {
                "variant": variant,
                "duration_sec": duration_sec,
                "run_id": run_id,
                "kwargs": kwargs,
            }
        )
        return _variant_metrics(variant, process_returncode=0, diagnostic_mode=False)

    monkeypatch.setattr(
        module,
        "_block_mock_ohlcv_kucoin_paper_startup",
        fake_block_mock_ohlcv_kucoin_paper_startup,
    )
    monkeypatch.setattr(
        module,
        "_run_data_integrity_checks",
        fake_run_data_integrity_checks,
    )
    monkeypatch.setattr(
        module,
        "_resolve_alpha_bootstrap_exact_source_contract",
        fake_resolve_alpha_bootstrap_exact_source_contract,
    )
    monkeypatch.setattr(
        module,
        "_refresh_alpha_bootstrap_history",
        fake_refresh_alpha_bootstrap_history,
    )
    monkeypatch.setattr(
        module,
        "_run_variant",
        fake_run_variant,
    )
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        lambda **kwargs: pytest.fail("diagnostic summary should not be built"),
    )
    monkeypatch.setattr(
        module,
        "_write_diagnostic_runtime_summary",
        lambda summary, run_id: pytest.fail("diagnostic summary should not be written"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_kpi_run.py",
            "--variant-only",
            "before",
            "--symbols",
            "BTCUSDTM",
            "--before-env",
            "ENTRY_FILTER_STRICT=3",
        ],
    )

    module.main()

    assert len(block_calls) == 1
    assert block_calls[0]["use_mock"] is False
    assert block_calls[0]["market_type"] == "futures"
    assert block_calls[0]["symbols"] == ["BTCUSDTM"]

    assert len(run_calls) == 1
    assert run_calls[0]["variant"] == "before"
    assert run_calls[0]["duration_sec"] == 1800
    assert run_calls[0]["kwargs"]["variant_overrides"] == {
        "ENTRY_FILTER_STRICT": "3"
    }

    assert not refresh_calls

    json_reports = sorted(results_dir.glob("controlled_kpi_*.json"))
    csv_reports = sorted(results_dir.glob("controlled_kpi_*.csv"))
    assert len(json_reports) == 1
    assert len(csv_reports) == 1

    report = json.loads(json_reports[0].read_text(encoding="utf-8"))
    assert report["variants_run"] == ["before"]
    assert report["before"]["variant"] == "before"
    assert report["after"] is None
    assert report["delta"] == {}
    assert report["params"]["variant_only"] == "before"
    assert report["params"]["paper_auto_open"] is False
    assert report["params"]["quality_profile"] is False
    assert report["params"]["alpha_bootstrap_auto_refresh"] is False
    assert report["params"]["before_env_overrides_cli"] == {
        "ENTRY_FILTER_STRICT": "3"
    }
    assert report["params"]["before_env_overrides"] == {
        "ENTRY_FILTER_STRICT": "3"
    }
    assert report["params"]["after_env_overrides_cli"] == {}
    assert "ENTRY_FILTER_STRICT" not in report["params"]["after_env_overrides"]
    assert report["alpha_bootstrap_refresh"]["success"] is True
    assert report["alpha_bootstrap_refresh"]["ran"] is True
    assert report["alpha_bootstrap_runtime_contract"]["status"] == "PASS"
    assert report["data_check"]["results"]["BTCUSDTM"]["ok"] is True

    csv_lines = csv_reports[0].read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 2
    assert csv_lines[0].startswith("variant,trade_count,net_pnl")


def test_main_after_only_fail_closed_preserves_cli_override_and_reports_failure(
    monkeypatch,
    tmp_path,
):
    module = _load_module()
    results_dir, diagnostics_dir, _ = _patch_workspace(monkeypatch, module, tmp_path)

    scorecard_path = tmp_path / "scorecards" / "controlled_kpi_scorecard.json"
    manifest_path = tmp_path / "analysis" / "controlled_kpi_manifest.json"
    empty_sentinel_path = tmp_path / module.EXACT_ALPHA_BOOTSTRAP_EMPTY_SENTINEL
    empty_sentinel_path.parent.mkdir(parents=True, exist_ok=True)
    empty_sentinel_path.write_text("stale sentinel", encoding="utf-8")
    empty_sentinel_posix = empty_sentinel_path.resolve().as_posix()

    refresh_calls = []
    run_calls = []
    diag_build_calls = []
    diag_write_calls = []

    def fake_block_mock_ohlcv_kucoin_paper_startup(**kwargs):
        assert kwargs["use_mock"] is False

    def fake_run_data_integrity_checks(**kwargs):
        return {
            "skipped": False,
            "market_type": kwargs["market_type"],
            "timeframe": kwargs["timeframe"],
            "symbols": list(kwargs["symbols"]),
            "results": {
                "ETHUSDTM": {
                    "ok": True,
                    "count": 60,
                    "monotonic_ts": True,
                    "stale_sec": 0.0,
                }
            },
        }

    def fake_resolve_alpha_bootstrap_exact_source_contract(_accepted_scorecard_path):
        return {
            "active": True,
            "source_mode": "scorecard_exact",
            "scorecard_path": str(scorecard_path),
            "resolved_scorecard_path": str(scorecard_path.resolve()),
            "prebuilt_manifest_path": str(manifest_path),
            "accepted_run_ids": ["run-b"],
            "existing_run_ids": ["run-b"],
            "nonzero_run_ids": ["run-b"],
            "missing_run_ids": [],
            "exact_after_db_patterns": ["tmp/controlled_kpi_after_run-b.db"],
            "reason_codes": [],
        }

    def fake_refresh_alpha_bootstrap_history(**kwargs):
        refresh_calls.append(kwargs)
        return {
            "enabled": kwargs["enabled"],
            "ran": True,
            "success": False,
            "status": "FAIL",
            "returncode": 1,
            "output_path": str(tmp_path / "tmp" / "alpha_history_auto_recent.db"),
            "output_exists": False,
            "report_path": str(
                tmp_path / "tmp" / "alpha_history_auto_recent_report.json"
            ),
            "report": {
                "pairs_selected": 1,
                "rows_inserted": 1,
                "pair_stats_top": [
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "trade_count": 15,
                        "expectancy": -0.01,
                        "winrate": 0.30,
                        "selected": True,
                    },
                    {
                        "symbol": "ETHUSDTM",
                        "strategy": "Momentum",
                        "trade_count": 15,
                        "expectancy": 0.04,
                        "winrate": 0.50,
                        "selected": False,
                    },
                    {
                        "symbol": "SOLUSDTM",
                        "strategy": "MeanReversion",
                        "trade_count": 15,
                        "expectancy": 0.03,
                        "winrate": 0.45,
                        "selected": False,
                    },
                    {
                        "symbol": "XRPUSDTM",
                        "strategy": "BadStrat",
                        "trade_count": 15,
                        "expectancy": -0.12,
                        "winrate": 0.20,
                        "selected": False,
                    },
                ],
                "pair_side_stats_top": [
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "buy",
                        "trade_count": 10,
                        "expectancy": -0.10,
                        "winrate": 0.20,
                    },
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "sell",
                        "trade_count": 10,
                        "expectancy": 0.05,
                        "winrate": 0.60,
                    },
                    {
                        "symbol": "ETHUSDTM",
                        "strategy": "Momentum",
                        "side": "buy",
                        "trade_count": 10,
                        "expectancy": 0.04,
                        "winrate": 0.55,
                    },
                    {
                        "symbol": "SOLUSDTM",
                        "strategy": "MeanReversion",
                        "side": "sell",
                        "trade_count": 10,
                        "expectancy": 0.03,
                        "winrate": 0.52,
                    },
                    {
                        "symbol": "XRPUSDTM",
                        "strategy": "BadStrat",
                        "side": "buy",
                        "trade_count": 10,
                        "expectancy": -0.15,
                        "winrate": 0.10,
                    },
                    {
                        "symbol": "XRPUSDTM",
                        "strategy": "BadStrat",
                        "side": "sell",
                        "trade_count": 10,
                        "expectancy": -0.12,
                        "winrate": 0.15,
                    },
                ],
            },
            "stdout_tail": "refresh stdout tail",
            "stderr_tail": "refresh stderr tail",
            "reason_codes": ["refresh_returncode_nonzero"],
        }

    def fake_run_variant(variant, duration_sec, run_id, **kwargs):
        run_calls.append(
            {
                "variant": variant,
                "duration_sec": duration_sec,
                "run_id": run_id,
                "kwargs": kwargs,
            }
        )
        assert variant == "after"
        return _variant_metrics(variant, process_returncode=7, diagnostic_mode=True)

    def fake_build_diagnostic_runtime_summary(**kwargs):
        diag_build_calls.append(kwargs)
        return {
            "variant": kwargs["variant"],
            "run_id": kwargs["run_id"],
            "db_path": str(kwargs["db_path"]),
            "symbols": kwargs["symbols"],
            "metrics": kwargs["metrics"],
        }

    def fake_write_diagnostic_runtime_summary(summary, run_id):
        diag_write_calls.append({"summary": summary, "run_id": run_id})
        out_path = diagnostics_dir / f"{run_id}.json"
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return out_path

    monkeypatch.setattr(
        module,
        "_block_mock_ohlcv_kucoin_paper_startup",
        fake_block_mock_ohlcv_kucoin_paper_startup,
    )
    monkeypatch.setattr(
        module,
        "_run_data_integrity_checks",
        fake_run_data_integrity_checks,
    )
    monkeypatch.setattr(
        module,
        "_resolve_alpha_bootstrap_exact_source_contract",
        fake_resolve_alpha_bootstrap_exact_source_contract,
    )
    monkeypatch.setattr(
        module,
        "_refresh_alpha_bootstrap_history",
        fake_refresh_alpha_bootstrap_history,
    )
    monkeypatch.setattr(
        module,
        "_run_variant",
        fake_run_variant,
    )
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        fake_build_diagnostic_runtime_summary,
    )
    monkeypatch.setattr(
        module,
        "_write_diagnostic_runtime_summary",
        fake_write_diagnostic_runtime_summary,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_kpi_run.py",
            "--variant-only",
            "after",
            "--symbols",
            "ETHUSDTM",
            "--paper-auto-open",
            "--quality-profile",
            "--after-env",
            "ALPHA_WHITELIST_ENABLE=1",
            "--after-env",
            "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST=BTCUSDTM:TRENDFOLLOWING:sell",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 7
    assert len(refresh_calls) == 1
    assert len(run_calls) == 1
    assert run_calls[0]["variant"] == "after"
    assert run_calls[0]["kwargs"]["variant_overrides"]["ALPHA_WHITELIST_ENABLE"] == "1"
    assert run_calls[0]["kwargs"]["alpha_bootstrap_source_db_url"] == (
        f"sqlite:///{empty_sentinel_posix}"
    )
    assert (
        run_calls[0]["kwargs"]["alpha_bootstrap_source_db_glob"]
        == empty_sentinel_posix
    )
    assert not empty_sentinel_path.exists()

    json_reports = sorted(results_dir.glob("controlled_kpi_*.json"))
    csv_reports = sorted(results_dir.glob("controlled_kpi_*.csv"))
    assert len(json_reports) == 1
    assert len(csv_reports) == 1
    assert len(diag_build_calls) == 1
    assert len(diag_write_calls) == 1

    report = json.loads(json_reports[0].read_text(encoding="utf-8"))
    assert report["variants_run"] == ["after"]
    assert report["before"] is None
    assert report["after"]["variant"] == "after"
    assert report["delta"] == {}
    assert report["params"]["variant_only"] == "after"
    assert report["params"]["paper_auto_open"] is True
    assert report["params"]["quality_profile"] is True
    assert report["params"]["alpha_bootstrap_auto_refresh"] is True
    assert report["params"]["alpha_bootstrap_source_db_url"] == (
        f"sqlite:///{empty_sentinel_posix}"
    )
    assert report["params"]["alpha_bootstrap_source_db_glob"] == empty_sentinel_posix
    assert report["alpha_bootstrap_refresh"]["source_fail_closed"] is True
    assert (
        report["alpha_bootstrap_refresh"]["source_fail_closed_path"]
        == str(empty_sentinel_path.resolve())
    )
    assert report["alpha_bootstrap_runtime_contract"]["status"] == "FAIL_CLOSED"
    assert report["params"]["after_env_overrides_cli"]["ALPHA_WHITELIST_ENABLE"] == "1"
    assert report["params"]["after_env_overrides"]["ALPHA_WHITELIST_ENABLE"] == "1"
    assert (
        report["params"]["after_env_overrides"]["ALPHA_WHITELIST_COLDSTART_ALLOW"]
        == "0"
    )
    assert (
        report["params"]["after_env_overrides"]["ALPHA_WHITELIST_FALLBACK_ENABLE"]
        == "0"
    )
    assert (
        report["params"]["after_env_overrides"]["ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS"]
        == "0"
    )
    assert report["entry_admission_contract"]["status"] == "PASS"
    assert (
        "EXPLICIT_SIDE_ALLOWLIST_PRESENT"
        in report["entry_admission_contract"]["reason_codes"]
    )
    assert report["after"]["process_returncode"] == 7
    assert report["after"]["diagnostic_env_flags"]["DIAGNOSTIC_MODE"] == "1"

    csv_lines = csv_reports[0].read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 2

    assert diag_build_calls[0]["variant"] == "after"
    assert diag_write_calls[0]["run_id"].endswith("after")


def test_main_after_only_entry_admission_fail_closed_blocks_run(
    monkeypatch,
    tmp_path,
):
    module = _load_module()
    results_dir, diagnostics_dir, _ = _patch_workspace(monkeypatch, module, tmp_path)

    scorecard_path = tmp_path / "scorecards" / "controlled_kpi_scorecard.json"
    manifest_path = tmp_path / "analysis" / "controlled_kpi_manifest.json"
    admission_calls = []

    def fake_block_mock_ohlcv_kucoin_paper_startup(**kwargs):
        assert kwargs["use_mock"] is False

    def fake_run_data_integrity_checks(**kwargs):
        return {
            "skipped": False,
            "market_type": kwargs["market_type"],
            "timeframe": kwargs["timeframe"],
            "symbols": list(kwargs["symbols"]),
            "results": {
                "BTCUSDTM": {
                    "ok": True,
                    "count": 60,
                    "monotonic_ts": True,
                    "stale_sec": 0.0,
                }
            },
        }

    def fake_resolve_alpha_bootstrap_exact_source_contract(_accepted_scorecard_path):
        return {
            "active": True,
            "source_mode": "scorecard_exact",
            "scorecard_path": str(scorecard_path),
            "resolved_scorecard_path": str(scorecard_path.resolve()),
            "prebuilt_manifest_path": str(manifest_path),
            "accepted_run_ids": ["run-c"],
            "existing_run_ids": ["run-c"],
            "nonzero_run_ids": ["run-c"],
            "missing_run_ids": [],
            "exact_after_db_patterns": ["tmp/controlled_kpi_after_run-c.db"],
            "reason_codes": [],
        }

    def fake_refresh_alpha_bootstrap_history(**kwargs):
        return {
            "enabled": kwargs["enabled"],
            "ran": True,
            "success": False,
            "status": "FAIL",
            "returncode": 1,
            "output_path": str(tmp_path / "tmp" / "alpha_history_auto_recent.db"),
            "output_exists": False,
            "report_path": str(
                tmp_path / "tmp" / "alpha_history_auto_recent_report.json"
            ),
            "report": {
                "pairs_selected": 1,
                "rows_inserted": 1,
                "pair_stats_top": [
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "trade_count": 12,
                        "expectancy": -0.03,
                        "winrate": 0.40,
                        "selected": False,
                    }
                ],
                "pair_side_stats_top": [
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "buy",
                        "trade_count": 12,
                        "expectancy": -0.03,
                        "winrate": 0.40,
                    }
                ],
            },
            "stdout_tail": "refresh stdout tail",
            "stderr_tail": "",
            "reason_codes": ["refresh_returncode_nonzero"],
        }

    def fake_run_variant(*args, **kwargs):
        pytest.fail(
            "run_variant should not be called when entry admission fails closed"
        )

    def fake_write_entry_admission_contract_artifact(**kwargs):
        admission_calls.append(kwargs)
        out_path = diagnostics_dir / "entry_admission.json"
        out_path.write_text(json.dumps(kwargs["contract"], indent=2), encoding="utf-8")
        return out_path

    monkeypatch.setattr(
        module,
        "_block_mock_ohlcv_kucoin_paper_startup",
        fake_block_mock_ohlcv_kucoin_paper_startup,
    )
    monkeypatch.setattr(
        module,
        "_run_data_integrity_checks",
        fake_run_data_integrity_checks,
    )
    monkeypatch.setattr(
        module,
        "_resolve_alpha_bootstrap_exact_source_contract",
        fake_resolve_alpha_bootstrap_exact_source_contract,
    )
    monkeypatch.setattr(
        module,
        "_refresh_alpha_bootstrap_history",
        fake_refresh_alpha_bootstrap_history,
    )
    monkeypatch.setattr(module, "_run_variant", fake_run_variant)
    monkeypatch.setattr(
        module,
        "_write_entry_admission_contract_artifact",
        fake_write_entry_admission_contract_artifact,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_kpi_run.py",
            "--variant-only",
            "after",
            "--symbols",
            "BTCUSDTM,ETHUSDTM",
            "--paper-auto-open",
            "--after-env",
            "QUALITY_FLAG=1",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert "CONTROLLED_KPI_ENTRY_ADMISSION_CONTRACT_FAIL" in str(excinfo.value)
    assert len(admission_calls) == 1
    assert admission_calls[0]["contract"]["status"] == "FAIL_CLOSED"
    assert "NO_ELIGIBLE_ENTRY_BUCKETS" in admission_calls[0]["contract"]["reason_codes"]
    assert not list(results_dir.glob("controlled_kpi_*.json"))
    assert not list(results_dir.glob("controlled_kpi_*.csv"))
    assert (diagnostics_dir / "entry_admission.json").exists()


def test_main_after_only_fallback_analysis_merges_strict_and_auto_overrides(
    monkeypatch,
    tmp_path,
):
    module = _load_module()
    results_dir, diagnostics_dir, _ = _patch_workspace(monkeypatch, module, tmp_path)

    prebuilt_db_path = diagnostics_dir / "prebuilt_alpha_history.db"
    prebuilt_db_path.write_bytes(b"prebuilt-db")
    prebuilt_report_path = diagnostics_dir / "prebuilt_alpha_history_report.json"
    _write_json(
        prebuilt_report_path,
        {
            "pairs_selected": 1,
            "rows_inserted": 1,
            "pair_stats_top": [
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "trade_count": 15,
                    "expectancy": -0.04,
                    "winrate": 0.40,
                    "selected": True,
                },
                {
                    "symbol": "ETHUSDTM",
                    "strategy": "Momentum",
                    "trade_count": 15,
                    "expectancy": -0.16,
                    "winrate": 0.40,
                    "selected": False,
                },
                {
                    "symbol": "XRPUSDTM",
                    "strategy": "BadStrat",
                    "trade_count": 15,
                    "expectancy": -0.20,
                    "winrate": 0.20,
                    "selected": False,
                },
                {
                    "symbol": "SOLUSDTM",
                    "strategy": "Flat",
                    "trade_count": 0,
                    "expectancy": 0.0,
                    "winrate": 0.50,
                    "selected": False,
                },
            ],
            "pair_side_stats_top": [
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                    "trade_count": 12,
                    "expectancy": -0.02,
                    "winrate": 0.40,
                    "gross_pnl": 1.0,
                    "fee_total": 0.2,
                },
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "sell",
                    "trade_count": 12,
                    "expectancy": 0.02,
                    "winrate": 0.44,
                    "gross_pnl": 1.0,
                    "fee_total": 0.2,
                },
                {
                    "symbol": "ETHUSDTM",
                    "strategy": "Momentum",
                    "side": "buy",
                    "trade_count": 12,
                    "expectancy": -0.04,
                    "winrate": 0.40,
                    "gross_pnl": 1.0,
                    "fee_total": 0.2,
                },
                {
                    "symbol": "ETHUSDTM",
                    "strategy": "Momentum",
                    "side": "sell",
                    "trade_count": 12,
                    "expectancy": -0.02,
                    "winrate": 0.44,
                    "gross_pnl": 0.5,
                    "fee_total": 0.3,
                },
                {
                    "symbol": "XRPUSDTM",
                    "strategy": "BadStrat",
                    "side": "buy",
                    "trade_count": 12,
                    "expectancy": -0.15,
                    "winrate": 0.10,
                    "gross_pnl": 0.4,
                    "fee_total": 0.2,
                },
                {
                    "symbol": "XRPUSDTM",
                    "strategy": "BadStrat",
                    "side": "sell",
                    "trade_count": 12,
                    "expectancy": -0.12,
                    "winrate": 0.15,
                    "gross_pnl": 0.4,
                    "fee_total": 0.2,
                },
            ],
        },
    )
    scorecard_path = tmp_path / "scorecards" / "controlled_kpi_scorecard.json"
    manifest_path = tmp_path / "analysis" / "prebuilt_manifest.json"

    block_calls = []
    run_calls = []
    refresh_calls = []
    diag_build_calls = []
    diag_write_calls = []

    def fake_block_mock_ohlcv_kucoin_paper_startup(**kwargs):
        block_calls.append(kwargs)

    def fake_run_data_integrity_checks(**kwargs):
        return {
            "skipped": False,
            "market_type": kwargs["market_type"],
            "timeframe": kwargs["timeframe"],
            "symbols": list(kwargs["symbols"]),
            "results": {
                "BTCUSDTM": {
                    "ok": True,
                    "count": 60,
                    "monotonic_ts": True,
                    "stale_sec": 0.0,
                }
            },
        }

    def fake_resolve_alpha_bootstrap_exact_source_contract(_accepted_scorecard_path):
        return {
            "active": True,
            "source_mode": "prebuilt_alpha_history_db",
            "prebuilt_alpha_history_db_path": str(prebuilt_db_path),
            "prebuilt_alpha_history_report_path": str(prebuilt_report_path),
            "scorecard_path": str(scorecard_path),
            "resolved_scorecard_path": str(scorecard_path.resolve()),
            "prebuilt_manifest_path": str(manifest_path),
            "accepted_run_ids": ["run-a"],
            "existing_run_ids": ["run-a"],
            "nonzero_run_ids": ["run-a"],
            "missing_run_ids": [],
            "exact_after_db_patterns": ["tmp/controlled_kpi_after_run-a.db"],
            "reason_codes": [],
        }

    def fake_refresh_alpha_bootstrap_history(**kwargs):
        refresh_calls.append(kwargs)
        return {
            "enabled": kwargs["enabled"],
            "ran": True,
            "success": False,
            "status": "FAIL",
            "returncode": 1,
            "output_path": str(tmp_path / "tmp" / "alpha_history_auto_recent.db"),
            "output_exists": False,
            "report_path": str(
                tmp_path / "tmp" / "alpha_history_auto_recent_report.json"
            ),
            "report": {
                "pairs_selected": 1,
                "rows_inserted": 1,
                "pair_stats_top": [
                    "not-a-dict",
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "trade_count": 15,
                        "expectancy": -0.01,
                        "winrate": 0.60,
                        "selected": True,
                    },
                    {
                        "symbol": "ETHUSDTM",
                        "strategy": "Momentum",
                        "trade_count": 8,
                        "expectancy": 0.02,
                        "winrate": 0.50,
                        "selected": False,
                    },
                    {
                        "symbol": "",
                        "strategy": "Invalid",
                        "trade_count": 12,
                        "expectancy": 0.03,
                        "winrate": 0.50,
                        "selected": False,
                    },
                    {
                        "symbol": "XRPUSDTM",
                        "strategy": "BadStrat",
                        "trade_count": "bad",
                        "expectancy": "bad",
                        "winrate": "bad",
                        "selected": False,
                    },
                    {
                        "symbol": "XRPUSDTM",
                        "strategy": "BadStrat",
                        "trade_count": 5,
                        "expectancy": -0.20,
                        "winrate": 0.20,
                        "selected": False,
                    },
                ],
                "pair_side_stats_top": [
                    "bad-side-row",
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "long",
                        "trade_count": 15,
                        "expectancy": 0.02,
                        "winrate": 0.60,
                        "gross_pnl": 1.0,
                        "fee_total": 0.2,
                    },
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "short",
                        "trade_count": 15,
                        "expectancy": -0.05,
                        "winrate": 0.60,
                        "gross_pnl": 1.0,
                        "fee_total": 0.2,
                    },
                    {
                        "symbol": "ETHUSDTM",
                        "strategy": "Momentum",
                        "side": "buy",
                        "trade_count": 12,
                        "expectancy": 0.04,
                        "winrate": 0.55,
                        "gross_pnl": 1.0,
                        "fee_total": 0.2,
                    },
                    {
                        "symbol": "ETHUSDTM",
                        "strategy": "Momentum",
                        "side": "sell",
                        "trade_count": 12,
                        "expectancy": -0.08,
                        "winrate": 0.20,
                        "gross_pnl": 0.5,
                        "fee_total": 0.3,
                    },
                    {
                        "symbol": "XRPUSDTM",
                        "strategy": "BadStrat",
                        "side": "left",
                        "trade_count": 8,
                        "expectancy": -0.20,
                        "winrate": 0.10,
                        "gross_pnl": 0.4,
                        "fee_total": 0.2,
                    },
                    {
                        "symbol": "XRPUSDTM",
                        "strategy": "BadStrat",
                        "side": "short",
                        "trade_count": "bad",
                        "expectancy": "bad",
                        "winrate": "bad",
                        "gross_pnl": "bad",
                        "fee_total": "bad",
                    },
                ],
            },
            "stdout_tail": "refresh stdout tail",
            "stderr_tail": "",
            "reason_codes": ["refresh_returncode_nonzero"],
        }

    def fake_run_variant(variant, duration_sec, run_id, **kwargs):
        run_calls.append(
            {
                "variant": variant,
                "duration_sec": duration_sec,
                "run_id": run_id,
                "kwargs": kwargs,
            }
        )
        return _variant_metrics(variant, process_returncode=1, diagnostic_mode=True)

    monkeypatch.setattr(
        module,
        "_block_mock_ohlcv_kucoin_paper_startup",
        fake_block_mock_ohlcv_kucoin_paper_startup,
    )
    monkeypatch.setattr(
        module,
        "_run_data_integrity_checks",
        fake_run_data_integrity_checks,
    )
    monkeypatch.setattr(
        module,
        "_resolve_alpha_bootstrap_exact_source_contract",
        fake_resolve_alpha_bootstrap_exact_source_contract,
    )
    monkeypatch.setattr(
        module,
        "_refresh_alpha_bootstrap_history",
        fake_refresh_alpha_bootstrap_history,
    )
    monkeypatch.setattr(module, "_run_variant", fake_run_variant)
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        lambda **kwargs: diag_build_calls.append(kwargs) or {
            "variant": kwargs["variant"],
            "run_id": kwargs["run_id"],
            "db_path": str(kwargs["db_path"]),
            "symbols": kwargs["symbols"],
            "metrics": kwargs["metrics"],
        },
    )
    monkeypatch.setattr(
        module,
        "_write_diagnostic_runtime_summary",
        lambda summary, run_id: diag_write_calls.append(
            {"summary": summary, "run_id": run_id}
        )
        or (diagnostics_dir / f"{run_id}.json"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_kpi_run.py",
            "--variant-only",
            "after",
            "--symbols",
            "BTCUSDTM,ETHUSDTM,XRPUSDTM",
            "--paper-auto-open",
            "--quality-profile",
            "--after-env",
            "QUALITY_FLAG=1",
            "--after-env",
            "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST=BTCUSDTM:TRENDFOLLOWING:buy",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        module.main()

    assert excinfo.value.code == 1
    assert len(block_calls) == 1
    assert block_calls[0]["symbols"] == ["BTCUSDTM", "ETHUSDTM", "XRPUSDTM"]
    assert len(refresh_calls) == 0
    assert len(run_calls) == 1
    assert len(diag_build_calls) == 1
    assert len(diag_write_calls) == 1

    json_reports = sorted(results_dir.glob("controlled_kpi_*.json"))
    csv_reports = sorted(results_dir.glob("controlled_kpi_*.csv"))
    assert len(json_reports) == 1
    assert len(csv_reports) == 1

    report = json.loads(json_reports[0].read_text(encoding="utf-8"))
    assert report["variants_run"] == ["after"]
    assert report["before"] is None
    assert report["after"]["variant"] == "after"
    assert report["delta"] == {}
    assert report["params"]["after_env_overrides_cli"]["QUALITY_FLAG"] == "1"
    assert report["params"]["after_env_overrides"]["QUALITY_FLAG"] == "1"
    assert report["params"]["after_env_overrides"][
        "ENTRY_SYMBOL_BLOCKLIST"
    ] == "XRPUSDTM"
    assert report["params"]["auto_after_overrides"][
        "ENTRY_SYMBOL_BLOCKLIST"
    ] == "XRPUSDTM"
    assert report["params"]["auto_after_overrides"][
        "ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST"
    ] == "ETHUSDTM:Momentum:buy,XRPUSDTM:BadStrat:buy,XRPUSDTM:BadStrat:sell"
    assert (
        "ENTRY_STRATEGY_SIDE_ALLOWLIST"
        not in report["params"]["auto_after_overrides"]
    )
    assert "ENTRY_STRATEGY_ALLOWLIST" not in report["params"]["auto_after_overrides"]
    assert report["alpha_bootstrap_refresh"]["success"] is True
    assert report["alpha_bootstrap_refresh"]["status"] == "PASS"


def test_main_both_variants_emits_delta_and_auto_overrides(
    monkeypatch,
    tmp_path,
):
    module = _load_module()
    results_dir, diagnostics_dir, _ = _patch_workspace(monkeypatch, module, tmp_path)

    prebuilt_db_path = diagnostics_dir / "prebuilt_alpha_history.db"
    prebuilt_db_path.write_bytes(b"prebuilt-db")
    prebuilt_report_path = diagnostics_dir / "prebuilt_alpha_history_report.json"
    _write_json(
        prebuilt_report_path,
        {
            "pairs_selected": 2,
            "rows_inserted": 2,
            "pair_stats_top": [
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "trade_count": 15,
                    "expectancy": -0.01,
                    "winrate": 0.30,
                    "selected": True,
                },
                {
                    "symbol": "ETHUSDTM",
                    "strategy": "Momentum",
                    "trade_count": 15,
                    "expectancy": 0.01,
                    "winrate": 0.40,
                    "selected": True,
                },
                {
                    "symbol": "SOLUSDTM",
                    "strategy": "MeanReversion",
                    "trade_count": 15,
                    "expectancy": 0.03,
                    "winrate": 0.45,
                    "selected": False,
                },
                {
                    "symbol": "XRPUSDTM",
                    "strategy": "BadStrat",
                    "trade_count": 15,
                    "expectancy": -0.12,
                    "winrate": 0.20,
                    "selected": False,
                },
            ],
            "pair_side_stats_top": [
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "buy",
                    "trade_count": 10,
                    "expectancy": -0.10,
                    "winrate": 0.20,
                },
                {
                    "symbol": "BTCUSDTM",
                    "strategy": "TrendFollowing",
                    "side": "sell",
                    "trade_count": 10,
                    "expectancy": 0.05,
                    "winrate": 0.60,
                },
                {
                    "symbol": "ETHUSDTM",
                    "strategy": "Momentum",
                    "side": "buy",
                    "trade_count": 10,
                    "expectancy": 0.04,
                    "winrate": 0.55,
                },
                {
                    "symbol": "SOLUSDTM",
                    "strategy": "MeanReversion",
                    "side": "sell",
                    "trade_count": 10,
                    "expectancy": 0.03,
                    "winrate": 0.52,
                },
                {
                    "symbol": "XRPUSDTM",
                    "strategy": "BadStrat",
                    "side": "buy",
                    "trade_count": 10,
                    "expectancy": -0.15,
                    "winrate": 0.10,
                },
                {
                    "symbol": "XRPUSDTM",
                    "strategy": "BadStrat",
                    "side": "sell",
                    "trade_count": 10,
                    "expectancy": -0.12,
                    "winrate": 0.15,
                },
            ],
        },
    )
    scorecard_path = tmp_path / "scorecards" / "controlled_kpi_scorecard.json"
    manifest_path = tmp_path / "analysis" / "prebuilt_manifest.json"

    block_calls = []
    run_calls = []
    diag_build_calls = []
    diag_write_calls = []

    def fake_block_mock_ohlcv_kucoin_paper_startup(**kwargs):
        block_calls.append(kwargs)

    def fake_run_data_integrity_checks(**kwargs):
        return {
            "skipped": False,
            "market_type": kwargs["market_type"],
            "timeframe": kwargs["timeframe"],
            "symbols": list(kwargs["symbols"]),
            "results": {
                "BTCUSDTM": {
                    "ok": True,
                    "count": 60,
                    "monotonic_ts": True,
                    "stale_sec": 0.0,
                },
                "ETHUSDTM": {
                    "ok": True,
                    "count": 60,
                    "monotonic_ts": True,
                    "stale_sec": 0.0,
                },
            },
        }

    def fake_resolve_alpha_bootstrap_exact_source_contract(_accepted_scorecard_path):
        return {
            "active": True,
            "source_mode": "prebuilt_alpha_history_db",
            "prebuilt_alpha_history_db_path": str(prebuilt_db_path),
            "prebuilt_alpha_history_report_path": str(prebuilt_report_path),
            "scorecard_path": str(scorecard_path),
            "resolved_scorecard_path": str(scorecard_path.resolve()),
            "prebuilt_manifest_path": str(manifest_path),
            "accepted_run_ids": ["run-c"],
            "existing_run_ids": ["run-c"],
            "nonzero_run_ids": ["run-c"],
            "missing_run_ids": [],
            "exact_after_db_patterns": ["tmp/controlled_kpi_after_run-c.db"],
            "reason_codes": [],
        }

    def fake_refresh_alpha_bootstrap_history(**kwargs):
        pytest.fail("prebuilt-source routing should skip refresh helper")

    def fake_run_variant(variant, duration_sec, run_id, **kwargs):
        run_calls.append(
            {
                "variant": variant,
                "duration_sec": duration_sec,
                "run_id": run_id,
                "kwargs": kwargs,
            }
        )
        return _variant_metrics(variant, process_returncode=0, diagnostic_mode=True)

    def fake_build_diagnostic_runtime_summary(**kwargs):
        diag_build_calls.append(kwargs)
        return {
            "variant": kwargs["variant"],
            "run_id": kwargs["run_id"],
            "db_path": str(kwargs["db_path"]),
            "symbols": kwargs["symbols"],
            "metrics": kwargs["metrics"],
        }

    def fake_write_diagnostic_runtime_summary(summary, run_id):
        diag_write_calls.append({"summary": summary, "run_id": run_id})
        out_path = diagnostics_dir / f"{run_id}.json"
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return out_path

    monkeypatch.setattr(
        module,
        "_block_mock_ohlcv_kucoin_paper_startup",
        fake_block_mock_ohlcv_kucoin_paper_startup,
    )
    monkeypatch.setattr(
        module,
        "_run_data_integrity_checks",
        fake_run_data_integrity_checks,
    )
    monkeypatch.setattr(
        module,
        "_resolve_alpha_bootstrap_exact_source_contract",
        fake_resolve_alpha_bootstrap_exact_source_contract,
    )
    monkeypatch.setattr(
        module,
        "_refresh_alpha_bootstrap_history",
        fake_refresh_alpha_bootstrap_history,
    )
    monkeypatch.setattr(
        module,
        "_run_variant",
        fake_run_variant,
    )
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        fake_build_diagnostic_runtime_summary,
    )
    monkeypatch.setattr(
        module,
        "_write_diagnostic_runtime_summary",
        fake_write_diagnostic_runtime_summary,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_kpi_run.py",
            "--variant-only",
            "both",
            "--symbols",
            "BTCUSDTM,ETHUSDTM",
            "--before-env",
            "ENTRY_FILTER_STRICT=4",
            "--after-env",
            "QUALITY_FLAG=1",
        ],
    )

    module.main()

    assert len(block_calls) == 1
    assert block_calls[0]["symbols"] == ["BTCUSDTM", "ETHUSDTM"]
    assert len(run_calls) == 2
    assert [call["variant"] for call in run_calls] == ["before", "after"]
    assert run_calls[0]["duration_sec"] == 1800
    assert run_calls[1]["duration_sec"] == 1800
    assert run_calls[0]["kwargs"]["variant_overrides"] == {
        "ENTRY_FILTER_STRICT": "4"
    }
    assert run_calls[1]["kwargs"]["variant_overrides"]["QUALITY_FLAG"] == "1"
    assert len(diag_build_calls) == 2
    assert len(diag_write_calls) == 2

    json_reports = sorted(results_dir.glob("controlled_kpi_*.json"))
    csv_reports = sorted(results_dir.glob("controlled_kpi_*.csv"))
    assert len(json_reports) == 1
    assert len(csv_reports) == 1

    report = json.loads(json_reports[0].read_text(encoding="utf-8"))
    assert report["variants_run"] == ["before", "after"]
    assert report["before"]["variant"] == "before"
    assert report["after"]["variant"] == "after"
    delta = report["delta"]
    assert delta["net_pnl_delta"] == pytest.approx(1.75)
    assert delta["winrate_delta_pct_points"] == pytest.approx(15.0)
    assert delta["max_drawdown_delta_pct_points"] == pytest.approx(-10.0)
    assert delta["profit_factor_delta"] == pytest.approx(0.75)
    assert delta["trade_count_delta"] == 2
    assert delta["decisions_count_delta"] == 1
    assert report["params"]["variant_only"] == "both"
    assert report["params"]["before_env_overrides_cli"] == {
        "ENTRY_FILTER_STRICT": "4"
    }
    assert report["params"]["after_env_overrides_cli"] == {"QUALITY_FLAG": "1"}
    assert report["params"]["alpha_bootstrap_auto_refresh"] is False
    assert report["alpha_bootstrap_refresh"]["success"] is True
    assert report["alpha_bootstrap_runtime_contract"]["status"] == "PASS"

    auto_after_overrides = report["params"]["auto_after_overrides"]
    assert auto_after_overrides["ENTRY_ALLOW_BUY"] == "0"
    assert auto_after_overrides["ENTRY_ALLOW_SELL"] == "1"
    assert auto_after_overrides["ENTRY_STRATEGY_SIDE_ALLOWLIST"]
    assert "ENTRY_SYMBOL_ALLOWLIST" not in auto_after_overrides
    assert "ENTRY_STRATEGY_ALLOWLIST" not in auto_after_overrides
    assert "DISABLE_STRATEGIES" not in auto_after_overrides
    assert report["before"]["diagnostic_env_flags"]["DIAGNOSTIC_MODE"] == "1"
    assert report["after"]["diagnostic_env_flags"]["DIAGNOSTIC_MODE"] == "1"

    csv_lines = csv_reports[0].read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 3
    assert csv_lines[0].startswith("variant,trade_count,net_pnl")


def test_main_rejects_empty_symbol_list(monkeypatch, tmp_path):
    module = _load_module()
    _patch_workspace(monkeypatch, module, tmp_path)
    monkeypatch.setattr(sys, "argv", ["controlled_kpi_run.py", "--symbols", ""])

    with pytest.raises(SystemExit, match="No symbols provided"):
        module.main()


def test_main_before_only_mock_data_check_skip_and_fallback_edge_paths(
    monkeypatch,
    tmp_path,
):
    module = _load_module()
    results_dir, diagnostics_dir, _ = _patch_workspace(monkeypatch, module, tmp_path)

    refresh_calls = []
    run_calls = []

    def fake_block_mock_ohlcv_kucoin_paper_startup(**kwargs):
        assert kwargs["use_mock"] is True
        assert kwargs["market_type"] == "futures"

    def fake_run_data_integrity_checks(**kwargs):
        return {
            "skipped": True,
            "market_type": kwargs["market_type"],
            "timeframe": kwargs["timeframe"],
            "symbols": list(kwargs["symbols"]),
            "results": {},
        }

    def fake_resolve_alpha_bootstrap_exact_source_contract(_accepted_scorecard_path):
        return {
            "active": False,
            "source_mode": "disabled",
            "accepted_run_ids": [],
            "existing_run_ids": [],
            "nonzero_run_ids": [],
            "missing_run_ids": [],
            "reason_codes": [],
        }

    def fake_refresh_alpha_bootstrap_history(**kwargs):
        refresh_calls.append(kwargs)
        output_path = tmp_path / "tmp" / "alpha_history_auto_recent.db"
        output_path.write_bytes(b"alpha-refresh")
        return {
            "enabled": kwargs["enabled"],
            "ran": True,
            "success": True,
            "status": "PASS",
            "returncode": 0,
            "output_path": str(output_path),
            "output_exists": True,
            "report_path": str(
                tmp_path / "tmp" / "alpha_history_auto_recent_report.json"
            ),
            "report": {
                "pairs_selected": "bad",
                "rows_inserted": "bad",
                "pair_stats_top": [
                    "not-a-dict",
                    {
                        "symbol": "",
                        "strategy": "Blank",
                        "trade_count": 5,
                        "expectancy": 0.20,
                        "winrate": 0.60,
                        "selected": True,
                    },
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "trade_count": "bad",
                        "expectancy": "bad",
                        "winrate": "bad",
                        "selected": True,
                    },
                    {
                        "symbol": "BADUSDTM",
                        "strategy": "BadStrat",
                        "trade_count": 8,
                        "expectancy": -0.20,
                        "winrate": 0.10,
                        "selected": False,
                    },
                    {
                        "symbol": "ETHUSDTM",
                        "strategy": "Momentum",
                        "trade_count": 1,
                        "expectancy": -0.11,
                        "winrate": 0.10,
                        "selected": False,
                    },
                ],
                "pair_side_stats_top": [
                    "bad-side-row",
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "long",
                        "trade_count": "bad",
                        "expectancy": "bad",
                        "winrate": "bad",
                    },
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "short",
                        "trade_count": 3,
                        "expectancy": -0.11,
                        "winrate": 0.10,
                    },
                    {
                        "symbol": "ETHUSDTM",
                        "strategy": "Momentum",
                        "side": "weird",
                        "trade_count": 3,
                        "expectancy": 0.02,
                        "winrate": 0.50,
                    },
                    {
                        "symbol": "SOLUSDTM",
                        "strategy": "Mini",
                        "side": "buy",
                        "trade_count": 2,
                        "expectancy": 0.50,
                        "winrate": 1.00,
                    },
                    {
                        "symbol": "XRPUSDTM",
                        "strategy": "Micro",
                        "side": "buy",
                        "trade_count": 2,
                        "expectancy": 0.40,
                        "winrate": 1.00,
                    },
                    {
                        "symbol": "ADAUSDTM",
                        "strategy": "Alt",
                        "side": "sell",
                        "trade_count": 3,
                        "expectancy": 0.01,
                        "winrate": 0.20,
                    },
                ],
            },
            "stdout_tail": "",
            "stderr_tail": "",
            "reason_codes": [],
        }

    def fake_run_variant(variant, duration_sec, run_id, **kwargs):
        run_calls.append(
            {
                "variant": variant,
                "duration_sec": duration_sec,
                "run_id": run_id,
                "kwargs": kwargs,
            }
        )
        return _variant_metrics(variant, process_returncode=0, diagnostic_mode=False)

    monkeypatch.setattr(
        module,
        "_block_mock_ohlcv_kucoin_paper_startup",
        fake_block_mock_ohlcv_kucoin_paper_startup,
    )
    monkeypatch.setattr(
        module,
        "_run_data_integrity_checks",
        fake_run_data_integrity_checks,
    )
    monkeypatch.setattr(
        module,
        "_resolve_alpha_bootstrap_exact_source_contract",
        fake_resolve_alpha_bootstrap_exact_source_contract,
    )
    monkeypatch.setattr(
        module,
        "_refresh_alpha_bootstrap_history",
        fake_refresh_alpha_bootstrap_history,
    )
    monkeypatch.setattr(module, "_run_variant", fake_run_variant)
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        lambda **kwargs: pytest.fail("diagnostic summary should not be built"),
    )
    monkeypatch.setattr(
        module,
        "_write_diagnostic_runtime_summary",
        lambda summary, run_id: pytest.fail("diagnostic summary should not be written"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_kpi_run.py",
            "--variant-only",
            "before",
            "--symbols",
            "BTCUSDTM,ETHUSDTM",
            "--use-mock",
            "--after-env",
            "ENTRY_SYMBOL_BLOCKLIST=CLIUSDTM",
        ],
    )

    module.main()

    assert len(refresh_calls) == 1
    assert len(run_calls) == 1
    assert run_calls[0]["variant"] == "before"
    assert run_calls[0]["duration_sec"] == 1800

    json_reports = sorted(results_dir.glob("controlled_kpi_*.json"))
    csv_reports = sorted(results_dir.glob("controlled_kpi_*.csv"))
    assert len(json_reports) == 1
    assert len(csv_reports) == 1

    report = json.loads(json_reports[0].read_text(encoding="utf-8"))
    assert report["variants_run"] == ["before"]
    assert report["before"]["variant"] == "before"
    assert report["after"] is None
    assert report["data_check"]["skipped"] is True
    assert report["params"]["use_mock"] is True
    assert report["params"]["after_env_overrides_cli"]["ENTRY_SYMBOL_BLOCKLIST"] == (
        "CLIUSDTM"
    )
    assert "ENTRY_SYMBOL_BLOCKLIST" not in report["params"]["auto_after_overrides"]
    assert report["params"]["after_env_overrides"]["ENTRY_SYMBOL_BLOCKLIST"] == (
        "CLIUSDTM"
    )
    assert report["alpha_bootstrap_refresh"]["success"] is True
    assert report["alpha_bootstrap_runtime_contract"]["status"] == "PASS"


def test_main_before_only_fallback_filters_off_universe_symbols_from_blocklists(
    monkeypatch,
    tmp_path,
):
    module = _load_module()
    results_dir, _, _ = _patch_workspace(monkeypatch, module, tmp_path)

    refresh_calls = []
    run_calls = []

    def fake_block_mock_ohlcv_kucoin_paper_startup(**kwargs):
        assert kwargs["use_mock"] is True
        assert kwargs["market_type"] == "futures"

    def fake_run_data_integrity_checks(**kwargs):
        return {
            "skipped": True,
            "market_type": kwargs["market_type"],
            "timeframe": kwargs["timeframe"],
            "symbols": list(kwargs["symbols"]),
            "results": {},
        }

    def fake_resolve_alpha_bootstrap_exact_source_contract(_accepted_scorecard_path):
        return {
            "active": False,
            "source_mode": "disabled",
            "accepted_run_ids": [],
            "existing_run_ids": [],
            "nonzero_run_ids": [],
            "missing_run_ids": [],
            "reason_codes": [],
        }

    def fake_refresh_alpha_bootstrap_history(**kwargs):
        refresh_calls.append(kwargs)
        output_path = tmp_path / "tmp" / "alpha_history_auto_recent.db"
        output_path.write_bytes(b"alpha-refresh")
        return {
            "enabled": kwargs["enabled"],
            "ran": True,
            "success": True,
            "status": "PASS",
            "returncode": 0,
            "output_path": str(output_path),
            "output_exists": True,
            "report_path": str(
                tmp_path / "tmp" / "alpha_history_auto_recent_report.json"
            ),
            "report": {
                "pairs_selected": 2,
                "rows_inserted": 4,
                "pair_stats_top": [
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "trade_count": 12,
                        "expectancy": -0.06,
                        "winrate": 0.40,
                        "selected": True,
                    },
                    {
                        "symbol": "ETHUSDTM",
                        "strategy": "Momentum",
                        "trade_count": 12,
                        "expectancy": -0.09,
                        "winrate": 0.30,
                        "selected": True,
                    },
                    {
                        "symbol": "BNBUSDTM",
                        "strategy": "Momentum",
                        "trade_count": 12,
                        "expectancy": 0.08,
                        "winrate": 0.60,
                        "selected": False,
                    },
                    {
                        "symbol": "ADAUSDTM",
                        "strategy": "TrendFollowing",
                        "trade_count": 12,
                        "expectancy": 0.04,
                        "winrate": 0.55,
                        "selected": False,
                    },
                ],
                "pair_side_stats_top": [
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "buy",
                        "trade_count": 12,
                        "expectancy": -0.05,
                        "winrate": 0.35,
                    },
                    {
                        "symbol": "ETHUSDTM",
                        "strategy": "Momentum",
                        "side": "buy",
                        "trade_count": 12,
                        "expectancy": -0.08,
                        "winrate": 0.25,
                    },
                    {
                        "symbol": "BNBUSDTM",
                        "strategy": "Momentum",
                        "side": "sell",
                        "trade_count": 12,
                        "expectancy": 0.09,
                        "winrate": 0.62,
                    },
                    {
                        "symbol": "ADAUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "buy",
                        "trade_count": 7,
                        "expectancy": -0.09,
                        "winrate": 0.20,
                    },
                ],
            },
            "stdout_tail": "",
            "stderr_tail": "",
            "reason_codes": [],
        }

    def fake_run_variant(variant, duration_sec, run_id, **kwargs):
        run_calls.append(
            {
                "variant": variant,
                "duration_sec": duration_sec,
                "run_id": run_id,
                "kwargs": kwargs,
            }
        )
        return _variant_metrics(variant, process_returncode=0, diagnostic_mode=False)

    monkeypatch.setattr(
        module,
        "_block_mock_ohlcv_kucoin_paper_startup",
        fake_block_mock_ohlcv_kucoin_paper_startup,
    )
    monkeypatch.setattr(
        module,
        "_run_data_integrity_checks",
        fake_run_data_integrity_checks,
    )
    monkeypatch.setattr(
        module,
        "_resolve_alpha_bootstrap_exact_source_contract",
        fake_resolve_alpha_bootstrap_exact_source_contract,
    )
    monkeypatch.setattr(
        module,
        "_refresh_alpha_bootstrap_history",
        fake_refresh_alpha_bootstrap_history,
    )
    monkeypatch.setattr(module, "_run_variant", fake_run_variant)
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        lambda **kwargs: pytest.fail("diagnostic summary should not be built"),
    )
    monkeypatch.setattr(
        module,
        "_write_diagnostic_runtime_summary",
        lambda summary, run_id: pytest.fail("diagnostic summary should not be written"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_kpi_run.py",
            "--variant-only",
            "before",
            "--symbols",
            "BTCUSDTM,ETHUSDTM",
            "--use-mock",
        ],
    )

    module.main()

    assert len(refresh_calls) == 1
    assert len(run_calls) == 1

    json_reports = sorted(results_dir.glob("controlled_kpi_*.json"))
    assert len(json_reports) == 1

    report = json.loads(json_reports[0].read_text(encoding="utf-8"))
    assert report["params"]["auto_after_overrides"]["ENTRY_SYMBOL_BLOCKLIST"] == (
        "ETHUSDTM"
    )
    assert report["params"]["auto_after_overrides"][
        "ENTRY_SYMBOL_STRATEGY_BLOCKLIST"
    ] == "BTCUSDTM:TrendFollowing,ETHUSDTM:Momentum"
    assert "BNBUSDTM" not in json.dumps(report["params"]["auto_after_overrides"])
    assert "ADAUSDTM" not in json.dumps(report["params"]["auto_after_overrides"])


def test_main_prebuilt_invalid_report_json_and_non_dict_variant_metrics(
    monkeypatch, tmp_path
):
    module = _load_module()
    results_dir, diagnostics_dir, _ = _patch_workspace(monkeypatch, module, tmp_path)

    prebuilt_db_path = diagnostics_dir / "prebuilt_alpha_history.db"
    prebuilt_db_path.write_bytes(b"prebuilt-db")
    prebuilt_report_path = diagnostics_dir / "prebuilt_alpha_history_report.json"
    prebuilt_report_path.write_text("{invalid-json", encoding="utf-8")

    def fake_block_mock_ohlcv_kucoin_paper_startup(**kwargs):
        return None

    def fake_run_data_integrity_checks(**kwargs):
        return {
            "skipped": False,
            "market_type": kwargs["market_type"],
            "timeframe": kwargs["timeframe"],
            "symbols": list(kwargs["symbols"]),
            "results": {},
        }

    def fake_resolve_alpha_bootstrap_exact_source_contract(_accepted_scorecard_path):
        return {
            "active": True,
            "source_mode": "prebuilt_alpha_history_db",
            "prebuilt_alpha_history_db_path": str(prebuilt_db_path),
            "prebuilt_alpha_history_report_path": str(prebuilt_report_path),
            "scorecard_path": str(tmp_path / "scorecard.json"),
            "resolved_scorecard_path": str((tmp_path / "scorecard.json").resolve()),
            "prebuilt_manifest_path": str(tmp_path / "manifest.json"),
            "accepted_run_ids": ["run-a"],
            "existing_run_ids": ["run-a"],
            "nonzero_run_ids": ["run-a"],
            "missing_run_ids": [],
            "exact_after_db_patterns": ["tmp/controlled_kpi_after_run-a.db"],
            "reason_codes": [],
        }

    def fake_refresh_alpha_bootstrap_history(**kwargs):
        pytest.fail("prebuilt exact source should skip refresh helper")

    def fake_run_variant(*args, **kwargs):
        # Keep orchestration alive with a non-dict variant payload so the
        # failure scan guard branch is exercised.
        return None

    monkeypatch.setattr(
        module,
        "_block_mock_ohlcv_kucoin_paper_startup",
        fake_block_mock_ohlcv_kucoin_paper_startup,
    )
    monkeypatch.setattr(
        module,
        "_run_data_integrity_checks",
        fake_run_data_integrity_checks,
    )
    monkeypatch.setattr(
        module,
        "_resolve_alpha_bootstrap_exact_source_contract",
        fake_resolve_alpha_bootstrap_exact_source_contract,
    )
    monkeypatch.setattr(
        module,
        "_refresh_alpha_bootstrap_history",
        fake_refresh_alpha_bootstrap_history,
    )
    monkeypatch.setattr(module, "_run_variant", fake_run_variant)
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        lambda **kwargs: pytest.fail("diagnostic summary should not be built"),
    )
    monkeypatch.setattr(
        module,
        "_write_diagnostic_runtime_summary",
        lambda summary, run_id: pytest.fail("diagnostic summary should not be written"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_kpi_run.py",
            "--variant-only",
            "before",
            "--symbols",
            "BTCUSDTM",
        ],
    )

    module.main()

    json_reports = sorted(results_dir.glob("controlled_kpi_*.json"))
    csv_reports = sorted(results_dir.glob("controlled_kpi_*.csv"))
    assert len(json_reports) == 1
    assert len(csv_reports) == 1

    report = json.loads(json_reports[0].read_text(encoding="utf-8"))
    assert report["variants_run"] == ["before"]
    assert report["before"] is None
    assert report["after"] is None
    assert report["alpha_bootstrap_refresh"]["report"] == {}


def test_main_exact_source_stale_artifact_unlink_failure_is_tolerated(
    monkeypatch, tmp_path
):
    module = _load_module()
    results_dir, _diagnostics_dir, _ = _patch_workspace(monkeypatch, module, tmp_path)

    output_rel = "tmp/custom_alpha_history.db"
    report_rel = "tmp/custom_alpha_history_report.json"
    stale_output = (tmp_path / output_rel).resolve()
    stale_report = (tmp_path / report_rel).resolve()
    stale_output.parent.mkdir(parents=True, exist_ok=True)
    stale_output.write_text("stale-output", encoding="utf-8")
    stale_report.write_text("stale-report", encoding="utf-8")

    unlink_calls = []
    original_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        resolved = self.resolve()
        if resolved in {stale_output, stale_report}:
            unlink_calls.append(str(resolved))
            raise OSError("unlink-blocked-for-test")
        return original_unlink(self, *args, **kwargs)

    def fake_run_data_integrity_checks(**kwargs):
        return {
            "skipped": False,
            "market_type": kwargs["market_type"],
            "timeframe": kwargs["timeframe"],
            "symbols": list(kwargs["symbols"]),
            "results": {},
        }

    def fake_resolve_alpha_bootstrap_exact_source_contract(_accepted_scorecard_path):
        return {
            "active": True,
            "source_mode": "accepted_after_runs",
            "accepted_run_ids": ["run-a"],
            "existing_run_ids": ["run-a"],
            "nonzero_run_ids": ["run-a"],
            "missing_run_ids": [],
            "exact_after_db_patterns": ["tmp/controlled_kpi_after_run-a.db"],
            "reason_codes": [],
        }

    def fake_refresh_alpha_bootstrap_history(**kwargs):
        refreshed_path = tmp_path / "tmp" / "fresh_alpha_history.db"
        refreshed_path.write_bytes(b"fresh")
        return {
            "enabled": kwargs["enabled"],
            "ran": True,
            "success": True,
            "status": "PASS",
            "returncode": 0,
            "output_path": str(refreshed_path),
            "output_exists": True,
            "report_path": None,
            "report": {},
            "stdout_tail": "",
            "stderr_tail": "",
            "reason_codes": [],
        }

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    monkeypatch.setattr(
        module,
        "_block_mock_ohlcv_kucoin_paper_startup",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        module,
        "_run_data_integrity_checks",
        fake_run_data_integrity_checks,
    )
    monkeypatch.setattr(
        module,
        "_resolve_alpha_bootstrap_exact_source_contract",
        fake_resolve_alpha_bootstrap_exact_source_contract,
    )
    monkeypatch.setattr(
        module,
        "_refresh_alpha_bootstrap_history",
        fake_refresh_alpha_bootstrap_history,
    )
    monkeypatch.setattr(module, "_run_variant", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        lambda **kwargs: pytest.fail("diagnostic summary should not be built"),
    )
    monkeypatch.setattr(
        module,
        "_write_diagnostic_runtime_summary",
        lambda summary, run_id: pytest.fail("diagnostic summary should not be written"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_kpi_run.py",
            "--variant-only",
            "before",
            "--symbols",
            "BTCUSDTM",
            "--alpha-bootstrap-build-output",
            output_rel,
            "--alpha-bootstrap-build-report-json",
            report_rel,
        ],
    )

    module.main()

    assert len(unlink_calls) == 2
    assert stale_output.exists()
    assert stale_report.exists()
    assert sorted(results_dir.glob("controlled_kpi_*.json"))
