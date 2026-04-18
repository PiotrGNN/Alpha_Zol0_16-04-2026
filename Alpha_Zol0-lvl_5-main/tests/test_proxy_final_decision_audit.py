import importlib.util
from pathlib import Path


def _load_audit():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "proxy_final_decision_audit.py"
    spec = importlib.util.spec_from_file_location("proxy_final_decision_audit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


audit = _load_audit()


def test_bias_checks_detect_one_sided_realized_distribution():
    root = Path(__file__).resolve().parents[1]
    expanded = root / "artifacts" / "diagnostics" / "proxy_shadow_realized_agreement_expanded_20260328_021928.json"
    report = audit._build_report(expanded)
    bias = report["bias_checks"]
    assert bias["observed_pairs"] >= 20
    assert bias["selection_bias"]["one_sided_realized_distribution"] is True
    assert bias["selection_bias"]["no_profitable_cases_observed"] is True


def test_contrarian_signal_is_not_useful():
    root = Path(__file__).resolve().parents[1]
    expanded = root / "artifacts" / "diagnostics" / "proxy_shadow_realized_agreement_expanded_20260328_021928.json"
    report = audit._build_report(expanded)
    failure = report["failure_mode"]
    assert failure["inverted_directional_agreement_rate"] is not None
    assert failure["inverted_directional_agreement_rate"] < 0.4
    assert report["final_decision"] == "INSUFFICIENT_EVIDENCE"


def test_md_contains_required_sections():
    root = Path(__file__).resolve().parents[1]
    expanded = root / "artifacts" / "diagnostics" / "proxy_shadow_realized_agreement_expanded_20260328_021928.json"
    report = audit._build_report(expanded)
    md = audit._render_md(report)
    for section in [
        "## A. Executive Summary",
        "## B. Scope",
        "## C. Validation of Matching Integrity",
        "## D. Bias Check Results",
        "## E. Failure Mode Classification",
        "## F. Contrarian Signal Test",
        "## G. Decision Matrix Evaluation",
        "## H. Final Decision",
        "## I. Justification (Strict, Technical)",
    ]:
        assert section in md
    assert "INSUFFICIENT_EVIDENCE" in md


def test_decision_matrix_stays_insufficient_evidence():
    root = Path(__file__).resolve().parents[1]
    expanded = root / "artifacts" / "diagnostics" / "proxy_shadow_realized_agreement_expanded_20260328_021928.json"
    report = audit._build_report(expanded)
    dm = report["decision_matrix"]
    assert dm["INSUFFICIENT_EVIDENCE"] is True
    assert dm["REMOVE_PROXY_FROM_ALL_DECISION_PATHS"] is False
    assert dm["USE_PROXY_AS_CONTRARIAN_SIGNAL_RESEARCH_ONLY"] is False
