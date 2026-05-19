import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "controlled_kpi_run.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "controlled_kpi_run", SCRIPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_variant_env_receives_runtime_derived_strict_positive_side_allowlist():
    module = _load_module()
    allowlist = "XRPUSDTM:MOMENTUM:sell,XRPUSDTM:TRENDFOLLOWING:sell"
    env = module._variant_env(
        ROOT / "tmp" / "test_runtime_allowlist_env.db",
        "after",
        use_mock=False,
        market_type="futures",
        run_symbols="ETHUSDTM,BTCUSDTM,SOLUSDTM,XRPUSDTM,ADAUSDTM,BNBUSDTM",
        paper_auto_open=True,
        paper_auto_close_sec=20,
        equity_snapshot_sec=10,
        quality_profile=True,
        alpha_bootstrap_source_db_url="sqlite:///aligned.db",
        alpha_bootstrap_source_db_glob="aligned.db",
        variant_overrides={
            "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST": allowlist,
            "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST_SOURCE": (
                "strict_positive_side_allowlist"
            ),
            "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST_CONTRACT_HASH": "A" * 64,
            "ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST_BOOTSTRAP_REPORT_HASH": "B" * 64,
        },
    )

    assert env["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST"] == allowlist
    assert (
        env["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST_SOURCE"]
        == "strict_positive_side_allowlist"
    )
    assert env["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST_CONTRACT_HASH"] == "A" * 64
    assert (
        env["ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST_BOOTSTRAP_REPORT_HASH"]
        == "B" * 64
    )
