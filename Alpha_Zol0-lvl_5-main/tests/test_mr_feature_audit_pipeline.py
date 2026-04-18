import os
import sys
from datetime import UTC, datetime
from pathlib import Path


WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)
DATA_ANALYSIS_EXPERT_ROOT = os.path.join(WORKSPACE_ROOT, "DataAnalysisExpert")
if DATA_ANALYSIS_EXPERT_ROOT not in sys.path:
    sys.path.insert(0, DATA_ANALYSIS_EXPERT_ROOT)

from DataAnalysisExpert.shadow_promotion_pipeline_lib import (  # noqa: E402
    DecisionRow,
    _extract_mr_features_from_payload,
    assemble_shadow_audit,
)


def test_assemble_shadow_audit_carries_mr_features_into_row_level_json():
    row = DecisionRow(
        db_path=Path("D:/Alpha_Zol0-lvl_5-main/autopsy/test_seed110_paper_v2.db"),
        decision_rowid=7,
        timestamp=datetime(2026, 3, 24, 12, 0, tzinfo=UTC),
        symbol="XRPUSDTM",
        side="buy",
        mr_pocket_symbol="XRPUSDTM",
        mr_pocket_side="buy",
        mr_pocket_regime="trend",
        mr_pocket_atr_bucket="<=0.20",
        mr_pocket_score_bucket=">0.30",
        mr_pocket_tuple="XRPUSDTM|buy|trend|<=0.20|>0.30",
        mr_gate_action="allow",
        mr_gate_reason="allowed_pocket",
        mr_gate_runtime_decision_unchanged=True,
        raw_decision="buy",
        final_decision="buy",
        entry_reason="entry_live_edge_proxy",
        candidate_history_ready=True,
        candidate_proxy_value=0.01,
        candidate_expected_edge_after_fee=0.01,
        candidate_router_lead=0.2,
        edge_history_ready=True,
        bucket_source="primary",
        trade_count=8,
        trade_count_primary=8,
        trade_count_fallback=0,
        strategy="MeanReversion",
        current_mean_gross_fill_model=0.003,
        current_mean_fee_total=0.001,
        current_edge_over_fee_value=0.002,
        active_threshold=0.0015,
        current_margin_to_threshold=0.0005,
        shadow_spread_slippage_proxy=0.0001,
        shadow_execution_cost_total=0.0011,
        shadow_edge_after_execution_cost=0.0019,
        shadow_margin_to_threshold=0.0004,
        current_gate_blocked=False,
        shadow_gate_blocked=False,
        shadow_counterfactual_raw=True,
        shadow_counterfactual_history_gated=True,
        shadow_counterfactual_history_exclusion_reason=None,
        shadow_counterfactual_forensic_class="allowed",
        mr_features={
            "rsi": 31.2,
            "bb_lower": 1.01,
            "bb_upper": 1.03,
            "bb_width": 0.02,
            "price": 1.011,
            "price_dist_to_bb_lower_pct": 0.00099,
            "price_dist_to_bb_lower_std": 0.05,
        },
        mr_shadow_rule_pass=False,
        mr_shadow_rule_reject_reason="bb_width_gt_threshold",
        mr_shadow_rule_thresholds={
            "bb_width": {"comparator": "<=", "threshold": 0.00749576}
        },
        mr_shadow_rule_checks={
            "bb_width": {
                "comparator": "<=",
                "threshold": 0.00749576,
                "value": 0.02,
                "pass": False,
            }
        },
        mr_shadow_rule_variant="ml_light_candidate_v1",
        realtime_execution_snapshot=None,
        realtime_edge_diagnostic=None,
        live_edge_status=None,
    )

    summary, row_level_audit, _ = assemble_shadow_audit(
        rows=[row],
        linked_by_key={},
        linkage_meta_by_key={},
        link_stats={},
    )

    assert summary["rows_audited"] == 1
    assert row_level_audit[0]["mr_features"]["rsi"] == 31.2
    assert row_level_audit[0]["mr_features"]["bb_width"] == 0.02
    assert row_level_audit[0]["mr_features"]["price_dist_to_bb_lower_pct"] == 0.00099
    assert row_level_audit[0]["mr_shadow_rule_pass"] is False
    assert row_level_audit[0]["mr_shadow_rule_variant"] == "ml_light_candidate_v1"
    assert row_level_audit[0]["mr_shadow_rule_checks"]["bb_width"]["pass"] is False


def test_extract_mr_features_from_payload_backfills_from_ensemble_signals():
    payload = {
        "ensemble_signals_filtered": [
            {
                "strategy": "MeanReversion",
                "signal": {
                    "analysis": {
                        "current_price": 1.42006,
                        "std": 0.0016796337320093301,
                    },
                    "metrics": {
                        "bb_lower": 1.4133737325359814,
                        "bb_upper": 1.4200922674640186,
                        "rsi": 65.2706871915425,
                    },
                },
            }
        ]
    }

    features = _extract_mr_features_from_payload(payload)

    assert features is not None
    assert features["rsi"] == 65.2706871915425
    assert features["bb_lower"] == 1.4133737325359814
    assert features["bb_upper"] == 1.4200922674640186
    assert round(features["bb_width"], 12) == round(
        1.4200922674640186 - 1.4133737325359814,
        12,
    )
    assert round(features["price"], 8) == 1.42006
    assert round(features["price_dist_to_bb_lower_pct"], 12) == round(
        (1.42006 - 1.4133737325359814) / 1.42006,
        12,
    )
    assert round(features["price_dist_to_bb_lower_std"], 12) == round(
        (1.42006 - 1.4133737325359814) / 0.0016796337320093301,
        12,
    )


def test_extract_mr_features_prefers_native_payload_over_backfill():
    payload = {
        "mr_features": {
            "rsi": 28.0,
            "bb_lower": 1.0,
            "bb_upper": 1.02,
            "bb_width": 0.02,
            "price": 1.001,
            "price_dist_to_bb_lower_pct": 0.001,
            "price_dist_to_bb_lower_std": 0.05,
        },
        "ensemble_signals_filtered": [
            {
                "strategy": "MeanReversion",
                "signal": {
                    "analysis": {"current_price": 1.5, "std": 0.4},
                    "metrics": {
                        "bb_lower": 1.4,
                        "bb_upper": 1.8,
                        "rsi": 80.0,
                    },
                },
            }
        ],
    }

    features = _extract_mr_features_from_payload(payload)

    assert features == payload["mr_features"]
