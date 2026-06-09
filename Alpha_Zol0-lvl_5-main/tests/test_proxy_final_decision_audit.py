import importlib.util
import json
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


def _expanded_fixture(tmp_path: Path) -> Path:
    pairs = []
    for index in range(24):
        proxy = 0.01 + index * 0.001 if index < 6 else -(0.01 + index * 0.001)
        pairs.append(
            {
                "proxy_shadow_edge_mean": proxy,
                "realized_net_pnl": -(0.02 + index * 0.001),
                "match_quality": {
                    "strategy_match": True,
                    "bucket_match": True,
                    "symbol_match": True,
                    "side_match": True,
                    "temporal_consistent": True,
                },
            }
        )
    path = tmp_path / "expanded.json"
    path.write_text(
        json.dumps(
            {
                "final_classification": "INSUFFICIENT_EVIDENCE",
                "agreement_pairs": pairs,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_bias_checks_detect_one_sided_realized_distribution(tmp_path):
    report = audit._build_report(_expanded_fixture(tmp_path))
    bias = report["bias_checks"]
    assert bias["observed_pairs"] >= 20
    assert bias["selection_bias"]["one_sided_realized_distribution"] is True
    assert bias["selection_bias"]["no_profitable_cases_observed"] is True


def test_contrarian_signal_is_not_useful(tmp_path):
    report = audit._build_report(_expanded_fixture(tmp_path))
    failure = report["failure_mode"]
    assert failure["inverted_directional_agreement_rate"] is not None
    assert failure["inverted_directional_agreement_rate"] < 0.4
    assert report["final_decision"] == "INSUFFICIENT_EVIDENCE"


def test_md_contains_required_sections(tmp_path):
    report = audit._build_report(_expanded_fixture(tmp_path))
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


def test_decision_matrix_stays_insufficient_evidence(tmp_path):
    report = audit._build_report(_expanded_fixture(tmp_path))
    decision_matrix = report["decision_matrix"]
    assert decision_matrix["INSUFFICIENT_EVIDENCE"] is True
    assert decision_matrix["REMOVE_PROXY_FROM_ALL_DECISION_PATHS"] is False
    assert decision_matrix["USE_PROXY_AS_CONTRARIAN_SIGNAL_RESEARCH_ONLY"] is False
