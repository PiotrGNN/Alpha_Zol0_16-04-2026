from scripts.dot_no_runtime_profile_autopsy import classify_profile_autopsy


def test_classify_profile_exists_but_min_net_guard_blocks_patch_bridge():
    result = classify_profile_autopsy(
        research_key="DOTUSDTM:TrendFollowingV2:sell",
        allowlist_key="DOTUSDTM:TrendFollowingV2:sell",
        runtime_symbols=["DOTUSDTM"],
        runtime_profile_rows=[
            {
                "symbol": "DOTUSDTM",
                "strategy": "TrendFollowingV2",
                "side": "sell",
                "runtime_profile_key": "DOTUSDTM|rolling_quote_window|n=32|span=559",
            }
        ],
        gate_reason_distribution={
            "no_runtime_profile": 455,
            "entry_edge_filtered": 12,
            "entry_min_net_guard": 4,
        },
        alpha_history_candidate_present=False,
    )

    assert result["classification"] == "DOT_PROFILE_EXISTS_BUT_MIN_NET_GUARD_BLOCKED"
    assert result["patch_decision"] == "not_justified"
    assert result["normalization"]["allowlist_matches_research"] is True


def test_classify_missing_runtime_symbol_requires_bridge_patch():
    result = classify_profile_autopsy(
        research_key="DOTUSDTM:TrendFollowingV2:sell",
        allowlist_key="DOTUSDTM:TrendFollowingV2:sell",
        runtime_symbols=["BNBUSDTM"],
        runtime_profile_rows=[],
        gate_reason_distribution={"no_runtime_profile": 1},
        alpha_history_candidate_present=False,
    )

    assert result["classification"] == "DOT_SYMBOL_UNIVERSE_MISSING"
    assert result["patch_decision"] == "runtime_universe_excludes_selected_research_symbol"
