import importlib.util
from pathlib import Path
import pytest

from test_locked_positive_subset_audit import _build_exact_corpus


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "audit_alpha_selection_failure_source.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "audit_alpha_selection_failure_source",
        SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alpha_failure_source_classifies_cost_burden_on_eligible_bucket(tmp_path):
    module = _load_module()
    trades = [
        {
            "symbol": "ETHUSDTM",
            "strategy": "TrendFollowing",
            "side": "buy",
            "pnl": -0.001,
            "gross": 0.001,
            "fee": 0.002,
        }
        for _ in range(10)
    ]
    scorecard_path, manifest_path = _build_exact_corpus(tmp_path, trades)

    audit = module.build_audit(
        scorecard_path=scorecard_path,
        manifest_path=manifest_path,
    )

    assert audit["evidence_contract"]["status"] == "PASS"
    assert audit["failure_decision"]["primary_failure"] == (
        "COST_BURDEN_PRIMARY_ON_ELIGIBLE_BUCKET"
    )
    assert audit["failure_decision"]["primary_bucket"] == (
        "ETHUSDTM|TrendFollowing|buy"
    )
    assert audit["failure_decision"]["runtime_change_allowed"] is False


def test_alpha_failure_source_classifies_sample_limited_without_eligible_bucket(tmp_path):
    module = _load_module()
    trades = [
        {
            "symbol": "XRPUSDTM",
            "strategy": "TrendFollowing",
            "side": "buy",
            "pnl": 0.01,
        }
    ]
    scorecard_path, manifest_path = _build_exact_corpus(tmp_path, trades)

    audit = module.build_audit(
        scorecard_path=scorecard_path,
        manifest_path=manifest_path,
    )

    assert audit["evidence_contract"]["status"] == "PASS"
    assert audit["failure_decision"]["primary_failure"] == (
        "SAMPLE_LIMITED_NO_ELIGIBLE_BUCKET"
    )
    assert audit["failure_decision"]["runtime_change_allowed"] is False


def test_extract_cost_rows_returns_empty_on_db_locked(monkeypatch, tmp_path):
    """
    P3-1 hardened contract: _extract_cost_rows must raise
    sqlite3.OperationalError when DB open fails under read-only mode.
    """
    module = _load_module()
    import sqlite3 as _sqlite3

    real_connect = _sqlite3.connect

    def locked_connect(path, *args, **kwargs):
        if "mode=ro" in str(path):
            raise _sqlite3.OperationalError("database is locked")
        return real_connect(path, *args, **kwargs)

    # Build a corpus so we have a valid manifest with at least one entry
    trades = [
        {"symbol": "BTCUSDTM", "strategy": "Scalper", "side": "buy", "pnl": -0.001}
        for _ in range(5)
    ]
    scorecard_path, manifest_path = _build_exact_corpus(tmp_path, trades)

    import json
    manifest = json.loads(manifest_path.read_text())

    # Monkeypatch sqlite3.connect on the loaded module to simulate DB lock
    monkeypatch.setattr(module.sqlite3, "connect", locked_connect)

    with pytest.raises(_sqlite3.OperationalError, match="database is locked"):
        module._extract_cost_rows(
            manifest,
            exclude_strategies=set(),
        )
