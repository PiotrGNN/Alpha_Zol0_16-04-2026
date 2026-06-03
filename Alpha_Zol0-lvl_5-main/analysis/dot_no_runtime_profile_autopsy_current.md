# DOT No Runtime Profile Autopsy

- generated_at_utc: `2026-06-03T14:27:41.312118+00:00`
- target: `DOTUSDTM:TrendFollowingV2:sell`
- classification: `DOT_PROFILE_EXISTS_BUT_MIN_NET_GUARD_BLOCKED`
- patch_decision: `not_justified`

## Canonical Keys
- research_key: `DOTUSDTM:TrendFollowingV2:sell`
- allowlist_key: `DOTUSDTM:TrendFollowingV2:sell`
- canonical_research_key: `DOTUSDTM:TRENDFOLLOWING:sell`
- canonical_allowlist_key: `DOTUSDTM:TRENDFOLLOWING:sell`
- allowlist_matches_research: `True`
- strategy_name_mismatch: `False`
- symbol_in_runtime_universe: `True`

## Runtime Profile Sources
- runtime_symbols: `['DOTUSDTM']`
- alpha_history_candidate_present: `False`
- bootstrap_rows_inserted: `0`
- positive_side_allowlist: `[]`
- runtime_profile_source_values: `['rolling_quote_window']`

## Gate Path
- gate_reason_distribution: `{'no_runtime_profile': 455, 'symbol_strategy_side_allowlist': 41, 'entry_edge_filtered': 12, 'entry_min_net_guard': 4}`
- profile_row_count: `52`
- matching_profile_row_count: `52`

## Matching Profile Sample Rows
- `{'id': 346, 'timestamp': '2026-06-03 12:32:03.143493', 'event': 'entry_eval_v2', 'symbol': 'DOTUSDTM', 'strategy': 'TrendFollowingV2', 'side': 'sell', 'runtime_profile_source': 'rolling_quote_window', 'runtime_profile_key': 'DOTUSDTM|rolling_quote_window|n=13|span=145', 'runtime_profile_sample_size': 13, 'runtime_profile_span_sec': 145.323, 'expected_net_after_cost': 0.000509187668196724, 'reason_code': 'entry_edge_filtered', 'risk_block_fields': {}}`
- `{'id': 347, 'timestamp': '2026-06-03 12:32:04.014366', 'event': 'entry_gate_decision_summary', 'symbol': 'DOTUSDTM', 'strategy': 'TrendFollowingV2', 'side': 'sell', 'runtime_profile_source': 'rolling_quote_window', 'runtime_profile_key': 'DOTUSDTM|rolling_quote_window|n=13|span=145', 'runtime_profile_sample_size': 13, 'runtime_profile_span_sec': 145.323, 'expected_net_after_cost': 0.000509187668196724, 'reason_code': 'entry_edge_filtered', 'risk_block_fields': {}}`
- `{'id': 349, 'timestamp': '2026-06-03 12:32:04.322623', 'event': 'entry_reject_v2', 'symbol': 'DOTUSDTM', 'strategy': 'TrendFollowingV2', 'side': 'sell', 'runtime_profile_source': 'rolling_quote_window', 'runtime_profile_key': 'DOTUSDTM|rolling_quote_window|n=13|span=145', 'runtime_profile_sample_size': 13, 'runtime_profile_span_sec': 145.323, 'expected_net_after_cost': 0.000509187668196724, 'reason_code': 'entry_edge_filtered', 'risk_block_fields': {}}`
- `{'id': 351, 'timestamp': '2026-06-03 12:32:06.102995', 'event': 'entry_eval_v2', 'symbol': 'DOTUSDTM', 'strategy': 'TrendFollowingV2', 'side': 'sell', 'runtime_profile_source': 'rolling_quote_window', 'runtime_profile_key': 'DOTUSDTM|rolling_quote_window|n=14|span=147', 'runtime_profile_sample_size': 14, 'runtime_profile_span_sec': 147.0, 'expected_net_after_cost': 0.000509187668196724, 'reason_code': 'entry_edge_filtered', 'risk_block_fields': {}}`
- `{'id': 352, 'timestamp': '2026-06-03 12:32:06.260110', 'event': 'entry_gate_decision_summary', 'symbol': 'DOTUSDTM', 'strategy': 'TrendFollowingV2', 'side': 'sell', 'runtime_profile_source': 'rolling_quote_window', 'runtime_profile_key': 'DOTUSDTM|rolling_quote_window|n=14|span=147', 'runtime_profile_sample_size': 14, 'runtime_profile_span_sec': 147.0, 'expected_net_after_cost': 0.000509187668196724, 'reason_code': 'entry_edge_filtered', 'risk_block_fields': {}}`
