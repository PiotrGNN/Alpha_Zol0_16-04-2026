import importlib.util
import inspect
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "controlled_kpi_run.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("controlled_kpi_run", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _after_env(module, tmp_path, variant_overrides):
    kwargs = {
        "use_mock": True,
        "market_type": "futures",
        "run_symbols": "SOLUSDTM",
        "paper_auto_open": True,
        "paper_auto_close_sec": 30,
        "equity_snapshot_sec": 10,
        "quality_profile": True,
        "alpha_bootstrap_source_db_url": "sqlite:///source.db",
        "alpha_bootstrap_source_db_glob": "analysis/*.json",
        "variant_overrides": variant_overrides,
    }
    if "engine_version" in inspect.signature(module._variant_env).parameters:
        kwargs["engine_version"] = "v2"
    return module._variant_env(tmp_path / "controlled_kpi.db", "after", **kwargs)


def test_admission_reachability_profile_forces_rejected_guard_off(tmp_path):
    module = _load_module()

    env = _after_env(
        module,
        tmp_path,
        {
            "V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE": "1",
            "V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_ENABLE": "1",
        },
    )

    assert env["V2_PAPER_ADMISSION_REACHABILITY_PROFILE_ENABLE"] == "1"
    assert env["V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_ENABLE"] == "0"
    assert (
        env["V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_POLICY"]
        == "rejected_overfilter_force_off"
    )
    assert (
        env["V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_POLICY_SOURCE"]
        == "analysis/shadow_guard_off_baseline_trade_attribution_current.json"
    )


def test_standalone_shadow_guard_experiment_is_not_rewritten(tmp_path):
    module = _load_module()

    env = _after_env(
        module,
        tmp_path,
        {"V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_ENABLE": "1"},
    )

    assert env["V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_ENABLE"] == "1"
    assert "V2_PAPER_SHADOW_VERIFIED_ADVERSE_GUARD_POLICY" not in env
