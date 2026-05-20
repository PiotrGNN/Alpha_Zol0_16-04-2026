# Profitability Baseline Audit (Read-only)

- generated_at: `2026-05-20T05:05:56.632538+00:00`
- selected_scorecard: `analysis/zol0_profitability_audit_stability_candidate_20260515_220302_scorecard.json`
- selected_manifest: `artifacts/accepted_corpus/zol0_profitability_audit_stability_candidate_20260515_220302_20260515_224451_251256/zol0_profitability_audit_stability_candidate_20260515_220302_accepted_corpus_manifest.json`
- accepted_clean_run_count: `0`
- rejected_run_count: `12`
- observed_trade_count: `12`
- natural_trade_count: `0`
- observed_net_pnl: `0.010987`
- natural_net_pnl: `0.0`
- forced_cycle_trade_count: `12`
- forced_cycle_net_pnl: `0.010987`
- dominant_loss_carrier_by_exit_reason: `sl_usdt`
- validity: `contaminated`
- final_classification: `PROFITABILITY_CONTAMINATED_BY_RUNTIME_OR_FORCED_EXITS`

## Rejected Run Reasons

- cycle_end_forced_exit: `12`
- post_green_protective_exit_observed: `6`
- shutdown_classification:real_post_promotion_read_observed: `12`

## Bucket Counts

- CYCLE_END_FORCED_EXIT: `12`

## Observed Corpus Metrics

- trade_count: `12`
- net_pnl: `0.010987`
- winrate: `0.333333`
- profit_factor: `1.296284`
- expectancy: `0.000916`
- avg_pnl_per_trade: `0.000916`
- fee_inversion_share: `0.166667`
- green_to_red_share: `0.25`
- exit_reason_distribution: `{"controlled_kpi_window_end": 4, "post_green_protective_exit": 6, "sl_usdt": 2}`
- symbol_distribution: `{"ETHUSDTM": 12}`
- side_distribution: `{"buy": 12}`
- strategy_distribution: `{"Momentum": 12}`
