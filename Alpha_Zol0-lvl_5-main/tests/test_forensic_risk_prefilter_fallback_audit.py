"""
Tests for classify_fallback_occurrence and extract_occurrence_fields helpers
in scripts/forensic_risk_prefilter_fallback_audit.py
"""
import sys
import pathlib
import pytest

# Add repo root to path so we can import the script module
REPO = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from forensic_risk_prefilter_fallback_audit import (
    classify_fallback_occurrence,
    extract_occurrence_fields,
    aggregate_occurrences,
    sol_overrepresentation_test,
    determine_aggregate_verdict,
)

# ---------------------------------------------------------------------------
# Fixtures — minimal row shapes
# ---------------------------------------------------------------------------


def _cold_start_row(symbol="XRPUSDTM", strategy="Momentum", side=None):
    """A row with cold-start markers: no history, side=None, bucket_identity_failure."""
    return {
        "symbol": symbol,
        "strategy": strategy,
        "side": side,
        "local_gate_reason": "risk_or_prefilter_block_fallback",
        "effective_gate_reason": "risk_or_prefilter_block_fallback",
        "entry_gate_bucket": "fallback_guard",
        "entry_decision_raw": "hold",
        "entry_decision_final": "hold",
        "regime": "trend",
        "canonical_shadow_history_ready": False,
        "canonical_shadow_trade_count": 0,
        "canonical_bucket": {
            "canonical_bucket_key": f"{symbol}|MOMENTUM|unknown",
            "bucket_identity_status": "RESOLVED",
            "bucket_identity_reason": "explicit_strategy",
            "raw_side": None,
            "normalized_side": "unknown",
        },
        "canonical_shadow_bucket": {
            "shadow_bucket": {"gross_hist": [], "fee_hist": [], "trade_count": 0}
        },
        "decision_snapshot_selection": {
            "bucket_used_final": "fallback",
            "bucket_key_primary": f"{symbol}|UNIVERSAL|sell",
            "trade_count_primary": 0,
            "trade_count_fallback": 0,
            "selected_history_ready": False,
            "selected_trade_count": 0,
        },
        "natural_path_trace": {
            "pre_entry_candidate_exists": True,
            "pre_entry_candidate_source": "router_selection",
            "strategy_assignment_stage": "router_selection",
            "strategy_assignment_reason": "explicit_strategy",
            "side_assignment_stage": "hold_or_fallback_normalization",
            "side_assignment_reason": None,
            "bucket_identity_stage": "build_canonical_edge_bucket_key",
            "bucket_identity_reason": "explicit_strategy",
            "fallback_assignment_stage": "resolve_local_gate_reason",
            "fallback_reason_raw": None,
            "fallback_reason_final": "risk_or_prefilter_block_fallback",
            "risk_prefilter_stage": None,
            "short_circuit_stage": "bucket_identity_formation_failure",
            "fallback_policy_exhausted": False,
            "fallback_policy_exhaustion_reason": None,
            "fallback_policy_blocked_strategies": None,
            "fallback_policy_blocked_sides": None,
            "fallback_policy_viable_assignments_count": None,
        },
    }


def _router_exhaustion_row(symbol="ADAUSDTM"):
    """A row where fallback_policy_exhausted=True."""
    row = _cold_start_row(symbol)
    row["natural_path_trace"]["fallback_policy_exhausted"] = True
    row["natural_path_trace"]["fallback_policy_exhaustion_reason"] = "no_viable_assignments"
    return row


def _prefilter_pressure_row(symbol="ETHUSDTM"):
    """A row where side is resolved but risk_prefilter_stage blocked."""
    row = _cold_start_row(symbol)
    row["side"] = "sell"
    row["natural_path_trace"]["side_assignment_stage"] = "explicit_side"
    row["natural_path_trace"]["risk_prefilter_stage"] = "risk_prefilter_blocked"
    row["natural_path_trace"]["short_circuit_stage"] = None
    return row


# ---------------------------------------------------------------------------
# classify_fallback_occurrence tests
# ---------------------------------------------------------------------------

class TestClassifyFallbackOccurrence:
    def test_cold_start_returns_correct_classification(self):
        row = _cold_start_row("XRPUSDTM")
        result = classify_fallback_occurrence(row)
        assert result == "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY"

    def test_cold_start_solusdtm_returns_cold_start_not_sol(self):
        # SOL-dominant is determined at aggregate level, not per-row
        row = _cold_start_row("SOLUSDTM")
        result = classify_fallback_occurrence(row)
        assert result == "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY"

    def test_router_exhaustion_classification(self):
        row = _router_exhaustion_row("ADAUSDTM")
        result = classify_fallback_occurrence(row)
        assert result == "FALLBACK_CAUSE_ROUTER_POLICY_EXHAUSTION"

    def test_router_exhaustion_takes_priority_over_cold_start(self):
        row = _cold_start_row("XRPUSDTM")
        row["natural_path_trace"]["fallback_policy_exhausted"] = True
        result = classify_fallback_occurrence(row)
        assert result == "FALLBACK_CAUSE_ROUTER_POLICY_EXHAUSTION"

    def test_prefilter_pressure_classification(self):
        row = _prefilter_pressure_row("ETHUSDTM")
        result = classify_fallback_occurrence(row)
        assert result == "FALLBACK_CAUSE_PREFILTER_PRESSURE"

    def test_missing_npt_returns_cold_start_if_no_history(self):
        row = _cold_start_row()
        row.pop("natural_path_trace")
        # No npt → cold_start fallback via history check
        result = classify_fallback_occurrence(row)
        assert result == "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY"

    def test_history_ready_true_with_no_other_markers_returns_unclassified(self):
        row = _cold_start_row()
        row["canonical_shadow_history_ready"] = True
        row["canonical_shadow_trade_count"] = 5
        row["natural_path_trace"]["short_circuit_stage"] = "some_other_stage"
        result = classify_fallback_occurrence(row)
        assert result == "FALLBACK_CAUSE_UNCLASSIFIED"


# ---------------------------------------------------------------------------
# extract_occurrence_fields tests
# ---------------------------------------------------------------------------

class TestExtractOccurrenceFields:
    def test_returns_all_required_keys(self):
        row = _cold_start_row("SOLUSDTM", "TrendFollowing")
        fields = extract_occurrence_fields(row)
        required = [
            "symbol", "strategy", "side", "local_gate_reason", "effective_gate_reason",
            "npt_short_circuit_stage", "npt_fallback_policy_exhausted",
            "canonical_shadow_history_ready", "canonical_shadow_trade_count",
            "classification",
        ]
        for k in required:
            assert k in fields, f"Missing key: {k}"

    def test_symbol_propagated(self):
        row = _cold_start_row("SOLUSDTM")
        fields = extract_occurrence_fields(row)
        assert fields["symbol"] == "SOLUSDTM"

    def test_classification_embedded_in_fields(self):
        row = _cold_start_row("XRPUSDTM")
        fields = extract_occurrence_fields(row)
        assert fields["classification"] == "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY"

    def test_missing_nested_fields_do_not_raise(self):
        row = {"symbol": "ETHUSDTM", "strategy": "Momentum"}
        fields = extract_occurrence_fields(row)
        assert fields["symbol"] == "ETHUSDTM"
        assert fields["npt_short_circuit_stage"] is None


# ---------------------------------------------------------------------------
# aggregate_occurrences tests
# ---------------------------------------------------------------------------

class TestAggregateOccurrences:
    def _make_occ(self, symbol="XRPUSDTM", classification="FALLBACK_CAUSE_COLD_START_EDGE_HISTORY"):
        row = _cold_start_row(symbol)
        f = extract_occurrence_fields(row)
        f["classification"] = classification
        return f

    def test_total_matches_input_count(self):
        occs = [self._make_occ("XRPUSDTM"), self._make_occ("SOLUSDTM")]
        agg = aggregate_occurrences(occs, total_gate=100)
        assert agg["total"] == 2

    def test_rate_computed_correctly(self):
        occs = [self._make_occ()] * 10
        agg = aggregate_occurrences(occs, total_gate=100)
        assert agg["rate"] == pytest.approx(0.10, abs=1e-4)

    def test_by_symbol_counts(self):
        occs = [self._make_occ("XRPUSDTM")] * 3 + [self._make_occ("SOLUSDTM")] * 2
        agg = aggregate_occurrences(occs, total_gate=50)
        assert agg["by_symbol"]["XRPUSDTM"] == 3
        assert agg["by_symbol"]["SOLUSDTM"] == 2

    def test_cold_start_markers_counted(self):
        occs = [self._make_occ()] * 5
        agg = aggregate_occurrences(occs, total_gate=50)
        assert agg["cold_start_markers"]["canonical_shadow_history_ready_false"] == 5

    def test_empty_occurrences(self):
        agg = aggregate_occurrences([], total_gate=100)
        assert agg["total"] == 0
        assert agg["rate"] == 0.0


# ---------------------------------------------------------------------------
# sol_overrepresentation_test tests
# ---------------------------------------------------------------------------

class TestSolOverrepresentationTest:
    def test_sol_dominant_when_above_threshold(self):
        agg = {"total": 10, "by_symbol": {"SOLUSDTM": 5, "XRPUSDTM": 5}}
        result = sol_overrepresentation_test(agg, total_symbols=4)
        # 5/10 = 50% vs expected 25% → 2x → dominant (>1.5x threshold)
        assert result["sol_dominant"] is True
        assert result["sol_overrepresentation_ratio"] == pytest.approx(2.0, abs=0.01)

    def test_sol_not_dominant_when_uniform(self):
        agg = {"total": 40, "by_symbol": {
            "SOLUSDTM": 10, "XRPUSDTM": 10, "ETHUSDTM": 10, "ADAUSDTM": 10
        }}
        result = sol_overrepresentation_test(agg, total_symbols=4)
        assert result["sol_dominant"] is False
        assert result["sol_overrepresentation_ratio"] == pytest.approx(1.0, abs=0.01)

    def test_sol_zero_occurrences(self):
        agg = {"total": 10, "by_symbol": {"XRPUSDTM": 10}}
        result = sol_overrepresentation_test(agg, total_symbols=4)
        assert result["sol_count"] == 0
        assert result["sol_dominant"] is False

    def test_empty_total(self):
        agg = {"total": 0, "by_symbol": {}}
        result = sol_overrepresentation_test(agg, total_symbols=4)
        assert result["sol_actual_share"] == 0.0


# ---------------------------------------------------------------------------
# determine_aggregate_verdict tests
# ---------------------------------------------------------------------------

class TestDetermineAggregateVerdict:
    def _agg(self, classifications: dict, total: int, symbol_dist: dict = None):
        return {
            "total": total,
            "by_classification": classifications,
            "by_symbol": symbol_dist or {},
        }

    def _sol_not_dominant(self):
        return {"sol_dominant": False, "sol_actual_share": 0.10, "sol_expected_share_uniform": 0.25}

    def _sol_dominant(self):
        return {"sol_dominant": True, "sol_actual_share": 0.60, "sol_expected_share_uniform": 0.25}

    def test_cold_start_majority_returns_cold_start(self):
        agg = self._agg({"FALLBACK_CAUSE_COLD_START_EDGE_HISTORY": 8, "FALLBACK_CAUSE_UNCLASSIFIED": 2}, 10)
        result = determine_aggregate_verdict(agg, self._sol_not_dominant())
        assert result == "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY"

    def test_router_exhaustion_majority(self):
        agg = self._agg({"FALLBACK_CAUSE_ROUTER_POLICY_EXHAUSTION": 7, "FALLBACK_CAUSE_UNCLASSIFIED": 3}, 10)
        result = determine_aggregate_verdict(agg, self._sol_not_dominant())
        assert result == "FALLBACK_CAUSE_ROUTER_POLICY_EXHAUSTION"

    def test_sol_dominant_with_cold_start_majority_returns_cold_start(self):
        agg = self._agg({"FALLBACK_CAUSE_COLD_START_EDGE_HISTORY": 8, "FALLBACK_CAUSE_UNCLASSIFIED": 2}, 10)
        result = determine_aggregate_verdict(agg, self._sol_dominant())
        # SOL dominant but cold-start is >50% → cold-start wins
        assert result == "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY"

    def test_sol_dominant_without_cold_start_majority_returns_sol(self):
        agg = self._agg({"FALLBACK_CAUSE_COLD_START_EDGE_HISTORY": 4, "FALLBACK_CAUSE_UNCLASSIFIED": 6}, 10)
        result = determine_aggregate_verdict(agg, self._sol_dominant())
        assert result == "FALLBACK_CAUSE_SOL_DOMINANT"

    def test_empty_returns_unclassified(self):
        agg = self._agg({}, 0)
        result = determine_aggregate_verdict(agg, self._sol_not_dominant())
        assert result == "FALLBACK_CAUSE_UNCLASSIFIED"

    def test_plurality_below_threshold_returns_unclassified(self):
        agg = self._agg({
            "FALLBACK_CAUSE_COLD_START_EDGE_HISTORY": 3,
            "FALLBACK_CAUSE_UNCLASSIFIED": 3,
            "FALLBACK_CAUSE_PREFILTER_PRESSURE": 4,
        }, 10)
        # cold_start = 30%, router = 0%, prefilter = 40% (>=30%) → PREFILTER
        result = determine_aggregate_verdict(agg, self._sol_not_dominant())
        assert result == "FALLBACK_CAUSE_PREFILTER_PRESSURE"
