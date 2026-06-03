# Entry edge filtered event autopsy

- classification: `THRESHOLD_OVERRIDE_PROPAGATED_RISK_RATIO_BLOCKS`
- threshold_override_propagated: `True`
- formula_mismatch_count: `0`
- event_count: `1989`

## Formula contract
- expected_edge_after_fee: `expected_move_scaled - fee_round_trip_ratio`
- expected_net_after_cost: `expected_move_scaled - total_cost_ratio`
- expected_net_after_full_cost: `expected_net_after_cost * final_notional_usdt`
- entry_net_to_stop_ratio: `expected_net_after_full_cost / estimated_stop_loss_net_usdt`

## Candidate threshold summary
- AVAXUSDTM:TrendFollowingV2:sell|0.03: records=`337`, edge=`303`, min_net=`20`, net_to_stop=`14`, full_cost_max=`0.045635636741546574`, ratio_max=`0.9090909090909091`
- AVAXUSDTM:TrendFollowingV2:sell|0.05: records=`224`, edge=`180`, min_net=`44`, net_to_stop=`0`, full_cost_max=`0.04826070387426362`, ratio_max=`None`
- AVAXUSDTM:TrendFollowingV2:sell|0.12: records=`238`, edge=`210`, min_net=`28`, net_to_stop=`0`, full_cost_max=`0.044791973511999386`, ratio_max=`None`
- BNBUSDTM:TrendFollowingV2:buy|0.03: records=`304`, edge=`300`, min_net=`4`, net_to_stop=`0`, full_cost_max=`0.025853185922780512`, ratio_max=`None`
- BNBUSDTM:TrendFollowingV2:buy|0.05: records=`381`, edge=`363`, min_net=`18`, net_to_stop=`0`, full_cost_max=`0.03671046608170393`, ratio_max=`None`
- BNBUSDTM:TrendFollowingV2:buy|0.12: records=`407`, edge=`387`, min_net=`20`, net_to_stop=`0`, full_cost_max=`0.05386902950622281`, ratio_max=`None`
- DOTUSDTM:TrendFollowingV2:sell|0.03: records=`43`, edge=`33`, min_net=`8`, net_to_stop=`2`, full_cost_max=`0.0379616349820558`, ratio_max=`0.909090909090909`
- DOTUSDTM:TrendFollowingV2:sell|0.05: records=`55`, edge=`45`, min_net=`6`, net_to_stop=`4`, full_cost_max=`0.056727152451426704`, ratio_max=`0.9454525408571117`

## Runs
- controlled_kpi_after_20260603_180101: threshold=`0.12`, records=`407`, effective_env_has_entry_min_net=`False`
- controlled_kpi_after_20260603_182201: threshold=`0.12`, records=`238`, effective_env_has_entry_min_net=`False`
- controlled_kpi_after_20260603_191201: threshold=`0.05`, records=`381`, effective_env_has_entry_min_net=`False`
- controlled_kpi_after_20260603_191202: threshold=`0.05`, records=`55`, effective_env_has_entry_min_net=`False`
- controlled_kpi_after_20260603_191203: threshold=`0.05`, records=`224`, effective_env_has_entry_min_net=`False`
- controlled_kpi_after_20260603_203001: threshold=`0.03`, records=`304`, effective_env_has_entry_min_net=`False`
- controlled_kpi_after_20260603_205001: threshold=`0.03`, records=`43`, effective_env_has_entry_min_net=`False`
- controlled_kpi_after_20260603_211001: threshold=`0.03`, records=`337`, effective_env_has_entry_min_net=`False`
