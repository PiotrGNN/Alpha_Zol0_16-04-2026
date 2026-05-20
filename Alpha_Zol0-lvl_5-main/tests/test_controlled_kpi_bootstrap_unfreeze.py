import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "controlled_kpi_run.py"

pytestmark = pytest.mark.skip(
    reason="requires unaccepted stashed controlled_kpi_run semantics"
)


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


def _variant_metrics(variant):
    return {
        "variant": variant,
        "db_path": f"/tmp/{variant}.db",
        "out_log": f"/tmp/{variant}.out.log",
        "err_log": f"/tmp/{variant}.err.log",
        "trade_count": 3,
        "net_pnl": 0.25,
        "winrate": 0.50,
        "max_drawdown": 0.10,
        "profit_factor": 1.10,
        "gross_profit": 0.5,
        "gross_loss_abs": 0.25,
        "decisions_count": 3,
        "equity_points": 4,
        "duration_sec_actual": 5,
        "started_at_utc": "2026-04-21T00:00:00+00:00",
        "ended_at_utc": "2026-04-21T00:00:05+00:00",
        "log_health": {"error_count": 0, "sample_errors": []},
        "diagnostic_env_flags": {"DIAGNOSTIC_MODE": "0"},
        "effective_env_values": {},
        "process_returncode": 0,
    }


def test_prebuilt_source_enables_refresh_for_paper_auto_open(monkeypatch, tmp_path):
    module = _load_module()
    results_dir, diagnostics_dir, _ = _patch_workspace(monkeypatch, module, tmp_path)

    prebuilt_db_path = diagnostics_dir / "prebuilt_alpha_history.db"
    prebuilt_db_path.write_bytes(b"prebuilt")
    prebuilt_report_path = diagnostics_dir / "prebuilt_alpha_history_report.json"
    prebuilt_report_path.write_text("{}", encoding="utf-8")
    refreshed_db_path = (tmp_path / "tmp" / "alpha_history_auto_recent.db").resolve()
    refreshed_db_path.parent.mkdir(parents=True, exist_ok=True)
    refreshed_db_path.write_bytes(b"refreshed")

    refresh_calls = []
    run_calls = []

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
        refresh_calls.append(kwargs)
        return {
            "enabled": kwargs["enabled"],
            "ran": True,
            "success": True,
            "status": "PASS",
            "returncode": 0,
            "output_path": str(refreshed_db_path),
            "output_exists": True,
            "report_path": str(tmp_path / "tmp" / "alpha_history_auto_recent_report.json"),
            "report": {
                "pairs_selected": 1,
                "rows_inserted": 1,
                "pair_stats_top": [
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "trade_count": 3,
                        "expectancy": 0.01,
                        "winrate": 0.50,
                        "selected": True,
                    }
                ],
                "pair_side_stats_top": [
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "buy",
                        "trade_count": 3,
                        "expectancy": 0.02,
                        "winrate": 0.60,
                    }
                ],
            },
            "reason_codes": [],
            "stdout_tail": "",
            "stderr_tail": "",
        }

    def fake_run_variant(variant, duration_sec, run_id, **kwargs):
        run_calls.append(
            {"variant": variant, "duration_sec": duration_sec, "run_id": run_id, "kwargs": kwargs}
        )
        return _variant_metrics(variant)

    monkeypatch.setattr(module, "_block_mock_ohlcv_kucoin_paper_startup", lambda **kwargs: None)
    monkeypatch.setattr(module, "_run_data_integrity_checks", fake_run_data_integrity_checks)
    monkeypatch.setattr(
        module,
        "_resolve_alpha_bootstrap_exact_source_contract",
        fake_resolve_alpha_bootstrap_exact_source_contract,
    )
    monkeypatch.setattr(module, "_refresh_alpha_bootstrap_history", fake_refresh_alpha_bootstrap_history)
    monkeypatch.setattr(module, "_run_variant", fake_run_variant)
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(module, "_write_diagnostic_runtime_summary", lambda summary, run_id: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_kpi_run.py",
            "--variant-only",
            "after",
            "--symbols",
            "BTCUSDTM",
            "--paper-auto-open",
        ],
    )

    module.main()

    assert len(refresh_calls) == 1
    assert refresh_calls[0]["enabled"] is True
    assert "diagnostics/prebuilt_alpha_history.db" in str(refresh_calls[0]["glob_patterns"])
    assert "tmp/controlled_kpi_after_*.db" in str(refresh_calls[0]["glob_patterns"])
    assert len(run_calls) == 1
    assert run_calls[0]["kwargs"]["alpha_bootstrap_source_db_glob"] == refreshed_db_path.as_posix()

    json_reports = sorted(results_dir.glob("controlled_kpi_*.json"))
    assert len(json_reports) == 1
    report = json.loads(json_reports[0].read_text(encoding="utf-8"))
    assert report["params"]["alpha_bootstrap_auto_refresh"] is True
    assert "diagnostics/prebuilt_alpha_history.db" in report["params"]["alpha_bootstrap_build_glob"]
    assert "tmp/controlled_kpi_after_*.db" in report["params"]["alpha_bootstrap_build_glob"]


def test_strict_positive_side_allowlist_symbol_not_added_to_global_symbol_blocklist(
    monkeypatch, tmp_path
):
    module = _load_module()
    results_dir, _, _ = _patch_workspace(monkeypatch, module, tmp_path)

    refresh_calls = []
    run_calls = []

    def fake_run_data_integrity_checks(**kwargs):
        return {
            "skipped": False,
            "market_type": kwargs["market_type"],
            "timeframe": kwargs["timeframe"],
            "symbols": list(kwargs["symbols"]),
            "results": {
                "XRPUSDTM": {
                    "ok": True,
                    "count": 60,
                    "monotonic_ts": True,
                    "stale_sec": 0.0,
                }
            },
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
        output_path = (tmp_path / "tmp" / "alpha_history_auto_recent.db").resolve()
        output_path.write_bytes(b"alpha-refresh")
        return {
            "enabled": kwargs["enabled"],
            "ran": True,
            "success": True,
            "status": "PASS",
            "returncode": 0,
            "output_path": str(output_path),
            "output_exists": True,
            "report_path": str(tmp_path / "tmp" / "alpha_history_auto_recent_report.json"),
            "report": {
                "pairs_selected": 1,
                "rows_inserted": 8,
                "pair_stats_top": [
                    {
                        "symbol": "XRPUSDTM",
                        "strategy": "TrendFollowing",
                        "trade_count": 12,
                        "expectancy": -0.04,
                        "winrate": 0.40,
                        "selected": True,
                    },
                    {
                        "symbol": "BTCUSDTM",
                        "strategy": "Momentum",
                        "trade_count": 12,
                        "expectancy": 0.08,
                        "winrate": 0.60,
                        "selected": False,
                    },
                ],
                "pair_side_stats_top": [
                    {
                        "symbol": "XRPUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "sell",
                        "trade_count": 12,
                        "expectancy": 0.06,
                        "winrate": 0.60,
                    },
                    {
                        "symbol": "XRPUSDTM",
                        "strategy": "TrendFollowing",
                        "side": "buy",
                        "trade_count": 12,
                        "expectancy": -0.08,
                        "winrate": 0.20,
                    },
                ],
            },
            "reason_codes": [],
            "stdout_tail": "",
            "stderr_tail": "",
        }

    def fake_run_variant(variant, duration_sec, run_id, **kwargs):
        run_calls.append(
            {"variant": variant, "duration_sec": duration_sec, "run_id": run_id, "kwargs": kwargs}
        )
        return _variant_metrics(variant)

    monkeypatch.setattr(module, "_block_mock_ohlcv_kucoin_paper_startup", lambda **kwargs: None)
    monkeypatch.setattr(module, "_run_data_integrity_checks", fake_run_data_integrity_checks)
    monkeypatch.setattr(
        module,
        "_resolve_alpha_bootstrap_exact_source_contract",
        fake_resolve_alpha_bootstrap_exact_source_contract,
    )
    monkeypatch.setattr(module, "_refresh_alpha_bootstrap_history", fake_refresh_alpha_bootstrap_history)
    monkeypatch.setattr(module, "_run_variant", fake_run_variant)
    monkeypatch.setattr(
        module,
        "_build_diagnostic_runtime_summary",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(module, "_write_diagnostic_runtime_summary", lambda summary, run_id: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_kpi_run.py",
            "--variant-only",
            "after",
            "--symbols",
            "XRPUSDTM,BTCUSDTM",
            "--paper-auto-open",
        ],
    )

    module.main()

    assert len(refresh_calls) == 1
    assert len(run_calls) == 1

    json_reports = sorted(results_dir.glob("controlled_kpi_*.json"))
    assert len(json_reports) == 1
    report = json.loads(json_reports[0].read_text(encoding="utf-8"))

    allowlist = str(
        report["params"]["after_env_overrides"].get("ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST", "")
    )
    assert "XRPUSDTM:TRENDFOLLOWING:sell" in allowlist

    global_symbol_blocklist = str(
        report["params"]["after_env_overrides"].get("ENTRY_SYMBOL_BLOCKLIST", "")
    )
    assert "XRPUSDTM" not in global_symbol_blocklist
