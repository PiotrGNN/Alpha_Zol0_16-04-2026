import importlib.util
from pathlib import Path


def _load_audit():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "proxy_shadow_realized_agreement_audit.py"
    spec = importlib.util.spec_from_file_location("proxy_shadow_realized_agreement_audit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


audit = _load_audit()


def test_realized_summary_detects_negative_outcome():
    root = Path(__file__).resolve().parents[1]
    events = audit._load_logs(root / "tmp" / "controlled_kpi_before_20260328_010418.db")
    summary = audit._realized_summary(events)
    assert summary["realized_rows"] >= 1
    assert summary["realized_sign"] in {"negative", "flat_or_missing"}


def test_proxy_summary_uses_shadow_only_fields():
    root = Path(__file__).resolve().parents[1]
    shadow = audit._load_json(root / "artifacts" / "diagnostics" / "proxy_readiness_shadow_only_20260328_015643.json")
    summary = audit._proxy_shadow_summary(shadow, "BTCUSDTM", "baseline")
    assert summary["proxy_shadow_trade_count"] >= 0
    assert summary["proxy_shadow_history_ready"] is True


def test_build_report_has_stable_shape():
    root = Path(__file__).resolve().parents[1]
    report = audit._build_report(
        root / "artifacts" / "diagnostics" / "proxy_readiness_shadow_only_20260328_015643.json",
        [
            root / "tmp" / "controlled_kpi_before_20260328_010209.db",
            root / "tmp" / "controlled_kpi_before_20260328_010418.db",
            root / "tmp" / "controlled_kpi_before_20260328_011249.db",
        ],
    )
    assert "metadata" in report
    assert "agreement_metrics" in report
    assert "false_optimism_definition" in report
    assert "why_count_zero" in report
    assert "lead_time_findings" in report
    assert "risk_review" in report
    assert report["final_classification"] in {
        "STRONG_DIRECTIONAL_AGREEMENT",
        "WEAK_BUT_USEFUL_AGREEMENT",
        "NOISY_PROXY_WITH_LIMITED_SIGNAL",
        "MISLEADING_PROXY",
        "INSUFFICIENT_OVERLAP",
    }


def test_md_mentions_false_optimism():
    report = audit._build_report(
        Path(__file__).resolve().parents[1] / "artifacts" / "diagnostics" / "proxy_readiness_shadow_only_20260328_015643.json",
        [
            Path(__file__).resolve().parents[1] / "tmp" / "controlled_kpi_before_20260328_010209.db",
            Path(__file__).resolve().parents[1] / "tmp" / "controlled_kpi_before_20260328_010418.db",
            Path(__file__).resolve().parents[1] / "tmp" / "controlled_kpi_before_20260328_011249.db",
        ],
    )
    md = audit._render_md(report)
    assert "## D. Matching Method" in md
    assert "false optimism" in md.lower()
    assert "False Optimism Definition" in md
    assert "Why count =" in md
    assert "## I. Final Classification" in md


def test_false_optimism_definition_is_pair_level():
    report = audit._build_report(
        Path(__file__).resolve().parents[1] / "artifacts" / "diagnostics" / "proxy_readiness_shadow_only_20260328_015643.json",
        [
            Path(__file__).resolve().parents[1] / "tmp" / "controlled_kpi_before_20260328_010209.db",
            Path(__file__).resolve().parents[1] / "tmp" / "controlled_kpi_before_20260328_010418.db",
            Path(__file__).resolve().parents[1] / "tmp" / "controlled_kpi_before_20260328_011249.db",
        ],
    )
    definition = report["false_optimism_definition"]
    assert "pair_level_rule" in definition
    assert definition["count_scope"] == "matched realized pairs only"
    assert "proxy-positive" in report["why_count_zero"] or "proxy-positive" in definition["pair_level_rule"]


def test_scope_clarification_mentions_corpus_level():
    report = audit._build_report(
        Path(__file__).resolve().parents[1] / "artifacts" / "diagnostics" / "proxy_readiness_shadow_only_20260328_015643.json",
        [
            Path(__file__).resolve().parents[1] / "tmp" / "controlled_kpi_before_20260328_010209.db",
            Path(__file__).resolve().parents[1] / "tmp" / "controlled_kpi_before_20260328_010418.db",
            Path(__file__).resolve().parents[1] / "tmp" / "controlled_kpi_before_20260328_011249.db",
        ],
    )
    assert "scope_clarification" in report
    assert "corpus_level_proxy_positivity" in report["scope_clarification"]
