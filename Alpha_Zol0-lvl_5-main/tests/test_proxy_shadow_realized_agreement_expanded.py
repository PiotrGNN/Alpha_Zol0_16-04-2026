import importlib.util
from pathlib import Path


def _load_audit():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "proxy_shadow_realized_agreement_expanded.py"
    spec = importlib.util.spec_from_file_location("proxy_shadow_realized_agreement_expanded", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


audit = _load_audit()


def test_scenario_from_env_maps_expected_flags():
    assert audit._scenario_from_env({"DIAGNOSTIC_MODE": "0"}) == "baseline"
    assert audit._scenario_from_env({"DIAGNOSTIC_MODE": "1", "DIAG_DISABLE_NET_TARGET_GUARD": "1"}) == "disable_net_target_guard"
    assert audit._scenario_from_env({"DIAGNOSTIC_MODE": "1", "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION": "1"}) == "disable_current_side"


def test_pairwise_rank_agreement_handles_ties():
    pairs = [
        {"rank_proxy_score": 1.0, "rank_realized_score": 1.0},
        {"rank_proxy_score": 2.0, "rank_realized_score": 2.0},
        {"rank_proxy_score": 3.0, "rank_realized_score": 2.0},
    ]
    summary = audit._pairwise_rank_agreement(pairs)
    assert summary["concordant_pairs"] >= 1
    assert "rank_agreement_rate" in summary


def test_build_report_has_stable_shape():
    root = Path(__file__).resolve().parents[1]
    report = audit._build_report(
        results_dir=root / "results",
        scenarios=("baseline", "disable_current_side", "disable_net_target_guard"),
        limit_per_scenario=2,
        small_sample_reference=root / "artifacts" / "diagnostics" / "proxy_shadow_realized_agreement_audit_20260328_020640.json",
    )
    assert "metadata" in report
    assert "agreement_metrics" in report
    assert "lead_time_analysis" in report
    assert "false_optimism_definition" in report
    assert "stability_vs_small_sample" in report
    assert report["final_classification"] in {
        "STRONG_DIRECTIONAL_AGREEMENT",
        "WEAK_BUT_USEFUL_AGREEMENT",
        "NOISY_PROXY_WITH_LIMITED_SIGNAL",
        "MISLEADING_PROXY",
        "INSUFFICIENT_EVIDENCE",
    }


def test_md_mentions_required_sections():
    root = Path(__file__).resolve().parents[1]
    report = audit._build_report(
        results_dir=root / "results",
        scenarios=("baseline", "disable_current_side", "disable_net_target_guard"),
        limit_per_scenario=2,
        small_sample_reference=root / "artifacts" / "diagnostics" / "proxy_shadow_realized_agreement_audit_20260328_020640.json",
    )
    md = audit._render_md(report)
    for section in [
        "## A. Executive Summary",
        "## B. Scope",
        "## C. Data Expansion Method",
        "## D. Matching Method",
        "## E. Agreement Metrics (Expanded)",
        "## F. Lead-Time Analysis",
        "## G. False Optimism / Pessimism",
        "## H. Stability vs Small Sample",
        "## I. Final Classification",
    ]:
        assert section in md
    assert "False Optimism / Pessimism" in md


def test_expanded_report_contains_pair_fields():
    root = Path(__file__).resolve().parents[1]
    report = audit._build_report(
        results_dir=root / "results",
        scenarios=("baseline", "disable_current_side", "disable_net_target_guard"),
        limit_per_scenario=2,
        small_sample_reference=root / "artifacts" / "diagnostics" / "proxy_shadow_realized_agreement_audit_20260328_020640.json",
    )
    assert report["agreement_pairs"]
    pair = report["agreement_pairs"][0]
    for key in [
        "symbol",
        "side",
        "bucket_key",
        "strategy_key",
        "realized_net_pnl",
        "directional_agreement",
        "false_optimism",
        "false_pessimism",
        "lead_time_sec",
    ]:
        assert key in pair
