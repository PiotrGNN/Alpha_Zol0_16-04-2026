from scripts.dot_entry_edge_guard_autopsy import classify_edge_guard


def test_classify_runtime_expected_net_below_min_net():
    result = classify_edge_guard(
        research_expected_net_after_full_cost=0.11373500855615154,
        runtime_min_net_guard_events=[
            {
                "expected_net_after_full_cost": 0.05172288403614261,
                "entry_min_net_usdt": 0.12,
                "expected_net_after_cost": 0.002204021904171412,
                "total_cost_ratio": 0.0003394854586129854,
            }
        ],
        runtime_edge_filtered_events=[],
        required_fields_missing=[],
        strategy_alias_mismatch=False,
        unit_mismatch=False,
    )

    assert result["classification"] == "DOT_RUNTIME_EXPECTED_NET_BELOW_MIN_NET"
    assert result["patch_decision"] == "not_justified"
    assert result["runtime_max_expected_net_after_full_cost"] == 0.05172288403614261


def test_classify_telemetry_insufficient_when_required_fields_missing():
    result = classify_edge_guard(
        research_expected_net_after_full_cost=0.11373500855615154,
        runtime_min_net_guard_events=[],
        runtime_edge_filtered_events=[],
        required_fields_missing=["expected_net_after_full_cost"],
        strategy_alias_mismatch=False,
        unit_mismatch=False,
    )

    assert result["classification"] == "DOT_EDGE_GUARD_TELEMETRY_INSUFFICIENT"
    assert result["patch_decision"] == "telemetry_only"
