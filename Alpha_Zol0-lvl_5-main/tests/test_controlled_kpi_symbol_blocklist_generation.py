import importlib.util
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


def test_narrow_negative_symbols_drops_symbol_with_positive_side_evidence():
    module = _load_module()
    negative_symbols = {"XRPUSDTM", "ETHUSDTM"}
    alpha_refresh_report = {
        "pair_side_stats_top": [
            {
                "symbol": "XRPUSDTM",
                "strategy": "Momentum",
                "side": "sell",
                "trade_count": 1,
                "expectancy": 0.11745010478777432,
                "winrate": 1.0,
            },
            {
                "symbol": "ETHUSDTM",
                "strategy": "Momentum",
                "side": "buy",
                "trade_count": 5,
                "expectancy": -0.09915454408298016,
                "winrate": 0.0,
            },
        ]
    }

    narrowed = module._narrow_negative_symbols_from_side_evidence(
        negative_symbols,
        alpha_refresh_report,
        active_run_symbols={"XRPUSDTM", "ETHUSDTM"},
    )

    assert narrowed == {"ETHUSDTM"}


def test_narrow_negative_symbols_keeps_symbol_without_positive_side_evidence():
    module = _load_module()
    negative_symbols = {"SOLUSDTM"}
    alpha_refresh_report = {
        "pair_side_stats_top": [
            {
                "symbol": "SOLUSDTM",
                "strategy": "TrendFollowing",
                "side": "buy",
                "trade_count": 3,
                "expectancy": -0.4324222093629379,
                "winrate": 0.3333333333333333,
            }
        ]
    }

    narrowed = module._narrow_negative_symbols_from_side_evidence(
        negative_symbols,
        alpha_refresh_report,
        active_run_symbols={"SOLUSDTM"},
    )

    assert narrowed == {"SOLUSDTM"}


def test_narrow_negative_symbols_fail_closed_when_side_stats_missing():
    module = _load_module()

    narrowed = module._narrow_negative_symbols_from_side_evidence(
        {"BTCUSDTM"},
        {"pair_side_stats_top": []},
        active_run_symbols={"BTCUSDTM"},
    )

    assert narrowed == {"BTCUSDTM"}
