from core.runtime_v2.runner import (
    _shadow_reachability_payload,
    _shadow_verified_guard_fields_from_trace,
)


def test_shadow_reachability_payload_reports_required_counters():
    payload = _shadow_reachability_payload(
        risk_candidate_seen_count=3,
        shadow_candidate_registered_count=1,
        shadow_terminal_outcome_count=1,
        shadow_registration_skipped_count=2,
        shadow_registration_skip_reasons={"guard_not_evaluated": 2},
        shadow_terminal_classifications={"SHADOW_OPEN_AT_SHUTDOWN": 1},
    )

    assert payload["risk_candidate_seen_count"] == 3
    assert payload["shadow_candidate_registered_count"] == 1
    assert payload["shadow_terminal_outcome_count"] == 1
    assert payload["shadow_open_at_shutdown_count"] == 1
    assert payload["shadow_expired_no_terminal_move_count"] == 0
    assert payload["shadow_insufficient_quotes_count"] == 0
    assert payload["shadow_registration_skipped_count"] == 2
    assert payload["shadow_registration_skip_reason_distribution"] == {
        "guard_not_evaluated": 2
    }


def test_shadow_verified_guard_fields_require_evaluated_contract():
    fields = _shadow_verified_guard_fields_from_trace(
        {
            "shadow_verified_guard_required": True,
            "immediate_adverse_guard_shadow_candidate": True,
        }
    )

    assert fields == {}


def test_shadow_verified_guard_fields_preserve_rule_attribution():
    fields = _shadow_verified_guard_fields_from_trace(
        {
            "shadow_verified_guard_evaluated": True,
            "shadow_verified_guard_blocked": True,
            "shadow_verified_guard_rule_id": (
                "SOLUSDTM_buy_TrendFollowingV2_shadow_verified_20260606_000500"
            ),
            "shadow_verified_guard_expected_net_benefit": 0.08687323999998789,
        }
    )

    assert fields["shadow_verified_guard_evaluated"] is True
    assert fields["shadow_verified_guard_blocked"] is True
    assert (
        fields["shadow_verified_guard_rule_id"]
        == "SOLUSDTM_buy_TrendFollowingV2_shadow_verified_20260606_000500"
    )
