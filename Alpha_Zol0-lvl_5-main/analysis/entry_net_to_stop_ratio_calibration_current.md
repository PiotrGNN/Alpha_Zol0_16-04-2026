# Entry net-to-stop ratio calibration audit

- classification: `STRATEGY_EDGE_TOO_WEAK_RELATIVE_TO_STOP_RISK`
- final_verdict: `STRATEGY_EDGE_REPAIR_REQUIRED`
- patch_decision: `no_semantic_patch`
- ratio_event_count: `84`
- only_net_to_stop_blocked_count: `10`
- clean_trade_with_ratio_count: `0`
- ratio_stats: `{'count': 84, 'min': 0.909090909090909, 'max': 0.9454525408571117, 'mean': 0.909955553194831}`
- expected_net_after_full_cost_stats: `{'count': 84, 'min': 0.01528842956989063, 'max': 0.056727152451426704, 'mean': 0.028674287212262447}`

## Buckets
- <0.50: events=`0`, candidates=`0`, trades=`0`, net_pnl=`0`, avg_ratio=`None`, avg_expected=`None`, avg_stop=`None`, sample=`INSUFFICIENT_CLEAN_COMPLETED_TRADES`
- 0.50-0.70: events=`0`, candidates=`0`, trades=`0`, net_pnl=`0`, avg_ratio=`None`, avg_expected=`None`, avg_stop=`None`, sample=`INSUFFICIENT_CLEAN_COMPLETED_TRADES`
- 0.70-0.90: events=`0`, candidates=`0`, trades=`0`, net_pnl=`0`, avg_ratio=`None`, avg_expected=`None`, avg_stop=`None`, sample=`INSUFFICIENT_CLEAN_COMPLETED_TRADES`
- 0.90-1.00: events=`84`, candidates=`3`, trades=`0`, net_pnl=`0`, avg_ratio=`0.909955553194831`, avg_expected=`0.028674287212262447`, avg_stop=`0.03148464942262984`, sample=`INSUFFICIENT_CLEAN_COMPLETED_TRADES`
- 1.00-1.10: events=`0`, candidates=`0`, trades=`0`, net_pnl=`0`, avg_ratio=`None`, avg_expected=`None`, avg_stop=`None`, sample=`INSUFFICIENT_CLEAN_COMPLETED_TRADES`
- >=1.10: events=`0`, candidates=`0`, trades=`0`, net_pnl=`0`, avg_ratio=`None`, avg_expected=`None`, avg_stop=`None`, sample=`INSUFFICIENT_CLEAN_COMPLETED_TRADES`

## Hypothetical thresholds
- 1.10: additional_events=`0`, additional_candidates=`0`, clean_trades=`0`, expectancy=`None`, experiment_justified=`False`
- 1.00: additional_events=`0`, additional_candidates=`0`, clean_trades=`0`, expectancy=`None`, experiment_justified=`False`
- 0.95: additional_events=`0`, additional_candidates=`0`, clean_trades=`0`, expectancy=`None`, experiment_justified=`False`
- 0.90: additional_events=`10`, additional_candidates=`2`, clean_trades=`0`, expectancy=`None`, experiment_justified=`False`

## Required checks
- stop_risk_too_large_relative_to_observed_mae: `INSUFFICIENT_CLEAN_MAE_SAMPLE`
- expected_net_too_small_because_strategy_signal_weak: `True`
- expected_net_clipped_or_cost_overburdened_before_ratio: `True`
- ratio_uses_correct_units: `True`
- required_1_10_has_historical_evidence: `NOT_PROVEN_BY_CURRENT_CLEAN_SAMPLE`
- lower_ratio_buckets_positive_under_clean_semantics: `NO_CLEAN_COMPLETED_LOWER_RATIO_SAMPLE`
- candidate_fails_only_because_ratio_guard: `True`
- lowering_to_1_00_0_95_0_90_outcome: `{'1.10': {'additional_admitted_events': 0, 'additional_candidates': 0, 'likely_opens_if_all_other_gates_pass': 0, 'clean_completed_historical_trades_available': 0, 'realized_net_pnl': None, 'expectancy': None, 'profit_factor': None, 'sample_sufficiency': 'INSUFFICIENT_CLEAN_COMPLETED_TRADES', 'experiment_justified': False}, '1.00': {'additional_admitted_events': 0, 'additional_candidates': 0, 'likely_opens_if_all_other_gates_pass': 0, 'clean_completed_historical_trades_available': 0, 'realized_net_pnl': None, 'expectancy': None, 'profit_factor': None, 'sample_sufficiency': 'INSUFFICIENT_CLEAN_COMPLETED_TRADES', 'experiment_justified': False}, '0.95': {'additional_admitted_events': 0, 'additional_candidates': 0, 'likely_opens_if_all_other_gates_pass': 0, 'clean_completed_historical_trades_available': 0, 'realized_net_pnl': None, 'expectancy': None, 'profit_factor': None, 'sample_sufficiency': 'INSUFFICIENT_CLEAN_COMPLETED_TRADES', 'experiment_justified': False}, '0.90': {'additional_admitted_events': 10, 'additional_candidates': 2, 'likely_opens_if_all_other_gates_pass': 10, 'clean_completed_historical_trades_available': 0, 'realized_net_pnl': None, 'expectancy': None, 'profit_factor': None, 'sample_sufficiency': 'INSUFFICIENT_CLEAN_COMPLETED_TRADES', 'experiment_justified': False}}`
- stop_risk_model_symbol_sensitive_enough: `INCONCLUSIVE_WITHOUT_CLEAN_MAE_SAMPLE`
- trendfollowing_entries_too_late_or_weak: `True`
