import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONTROLLED_KPI_RUN = ROOT / "scripts" / "controlled_kpi_run.py"
LIVE_ROLLOUT_LAUNCHER = ROOT / "scripts" / "live_rollout_launch.ps1"


def _load_controlled_kpi_run():
    spec = importlib.util.spec_from_file_location(
        "controlled_kpi_run",
        CONTROLLED_KPI_RUN,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def controlled_kpi_run_module():
    return _load_controlled_kpi_run()


def test_controlled_kpi_run_accepts_explicit_launcher_run_id(controlled_kpi_run_module):
    assert (
        controlled_kpi_run_module._resolve_run_id("20260420_125236")
        == "20260420_125236"
    )


def test_controlled_kpi_run_rejects_non_timestamp_launcher_run_id(
    controlled_kpi_run_module,
):
    with pytest.raises(SystemExit, match="--run-id must match YYYYMMDD_HHMMSS"):
        controlled_kpi_run_module._resolve_run_id("2026-04-20T12:52:36Z")


def test_live_rollout_launcher_passes_ts_to_controlled_kpi_run():
    script = LIVE_ROLLOUT_LAUNCHER.read_text(encoding="utf-8")

    assert "$Ts     = (Get-Date).ToUniversalTime().ToString(\"yyyyMMdd_HHmmss\")" in script
    assert "\"--run-id\", $Ts" in script
    assert "controlled_kpi_after_$Ts.db" in script


def test_live_rollout_launcher_clears_stale_hard_stop_fail_closed():
    script = LIVE_ROLLOUT_LAUNCHER.read_text(encoding="utf-8")

    assert "Remove-Item -LiteralPath $HardStopFile -Force -ErrorAction SilentlyContinue" in script
    assert (
        'Assert-Check "Stale hard stop file cleared" '
        "(-not (Test-Path -LiteralPath $HardStopFile)) $HardStopFile"
    ) in script
