# DOT Entry Edge / Min-Net Guard Autopsy

- generated_at_utc: `2026-06-03T14:36:06.172187+00:00`
- target: `DOTUSDTM:TrendFollowingV2:sell`
- classification: `DOT_RUNTIME_EXPECTED_NET_BELOW_MIN_NET`
- patch_decision: `not_justified`

## Research Candidate
- symbol: `DOTUSDTM`
- strategy: `TrendFollowingV2`
- canonical_strategy: `TRENDFOLLOWING`
- side: `sell`
- expected_net_after_full_cost: `0.11373500855615154`
- expected_net_after_cost: `0.005666916221033958`
- expected_move: `0.005926916221033962`
- final_notional_usdt: `20.07`
- source: `fresh_kucoin_public_klines_research`
- profile_span_sec: `1920.0`
- sample_count: `23`

## Runtime Blocked Counts
- entry_edge_filtered_count: `36`
- entry_min_net_guard_count: `8`
- nearby_no_runtime_profile_count_sampled: `25`

## Formula And Unit Consistency
- research_full_cost_usdt: `0.11373500855615154`
- research_expected_net_ratio: `0.005666916221033958`
- runtime_expected_net_after_full_cost_stats: `{'count': 4, 'min': 0.025792920667705048, 'max': 0.05172288403614261, 'mean': 0.04041799967371404}`
- runtime_expected_net_after_cost_ratio_stats: `{'count': 52, 'min': 0.0005078339314558016, 'max': 0.002204021904171412, 'mean': 0.0009003158157225756}`
- runtime_total_cost_ratio_stats: `{'count': 36, 'min': 0.0003392458723783927, 'max': 0.0003394854586129854, 'mean': 0.00033941440664559926}`
- effective_entry_min_net_usdt_values: `[0.12]`
- threshold_higher_than_research_expected_full_cost: `True`
- runtime_uses_notional_dependent_full_cost: `True`
- unit_mismatch_suspected: `False`
- runtime_applies_cost_components: `True`
- missing_fields: `['entry_min_net_usdt', 'expected_net_after_full_cost', 'total_cost_ratio']`

## Gate Reason Distribution
- no_runtime_profile: `910`
- symbol_strategy_side_allowlist: `82`
- entry_edge_filtered: `36`
- allow: `8`
- entry_min_net_guard: `8`

## Next Recommended Action
Reject DOT for current runtime economics and test next research candidate unless a later market window produces expected_net_after_full_cost above 0.12.
