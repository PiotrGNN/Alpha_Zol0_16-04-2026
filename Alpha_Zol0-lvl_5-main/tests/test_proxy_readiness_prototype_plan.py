import importlib.util
from pathlib import Path


def _load_plan():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "proxy_readiness_prototype_plan.py"
    spec = importlib.util.spec_from_file_location("proxy_readiness_prototype_plan", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


plan = _load_plan()


def test_report_contains_proxy_candidates():
    report = plan._build_report()
    candidates = report["proxy_candidates"]["available_pre_close_signals"]
    assert "entry_live_edge_proxy" in candidates
    assert "entry_edge_over_fee_status.mean_spread_slippage_proxy" in candidates


def test_semantic_separation_is_explicit():
    report = plan._build_report()
    sem = report["semantic_separation"]
    assert "realized_history" in sem
    assert "proxy_history" in sem
    assert "true_edge_performance_history" in sem


def test_shadow_only_is_separated_from_realized():
    report = plan._build_report()
    shadow = report["prototype_design"]["proxy_readiness_shadow_only"]
    assert "never used for admission" in shadow["wiring"]
    assert "no shared bucket" in " ".join(shadow["artifact_rules"])


def test_final_classification_is_shadow_only():
    report = plan._build_report()
    assert report["final_classification"] == "SHADOW_ONLY_PROTOTYPE_WORTH_IT"

