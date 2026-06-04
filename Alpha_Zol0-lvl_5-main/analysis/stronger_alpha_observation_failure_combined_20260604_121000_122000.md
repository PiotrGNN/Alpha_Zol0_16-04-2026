# Post-Signal Alpha Target Failure Autopsy

- classification: `POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK`
- trajectory_event_count: `758`
- clean_event_count: `758`
- contaminated_event_count: `0`
- alpha_target_count: `0`
- target_threshold: `0.12`
- min_samples: `20`

## Root Cause Answers
- why_alpha_target_count_zero: `POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK`
- any_clean_event_close_to_alpha_target: `False`
- best_strategy_family: `MEANREVERSION`
- best_symbol_side: `BTCUSDTM:sell`
- non_trendfollowing_better_than_trendfollowing_baseline: `True`
- focused_paper_observation_candidate: `BTCUSDTM:MEANREVERSION:sell`
- telemetry_only_extension_needed: `False`

## Near Target Counts
- 25pct: `0`
- 50pct: `0`
- 75pct: `0`
- 90pct: `0`

## Strategy Ranking
- `MEANREVERSION` events=`370` best_net=`0.003372035335` best_mfe=`0.003622191262`
- `MOMENTUM` events=`388` best_net=`0.001650106504` best_mfe=`0.001900955145`

## Best Events
- `MEANREVERSION:BTCUSDTM:sell:h10` net=`0.003372035335` gross=`0.003622191262` cost=`0.000250155927`
- `MEANREVERSION:XRPUSDTM:sell:h10` net=`0.003128661664` gross=`0.003379508658` cost=`0.000250846995`
- `MEANREVERSION:SOLUSDTM:sell:h10` net=`0.002976287003` gross=`0.003227705775` cost=`0.000251418772`
- `MEANREVERSION:BNBUSDTM:sell:h10` net=`0.002962267425` gross=`0.00322218183` cost=`0.000259914406`
- `MEANREVERSION:BTCUSDTM:sell:h10` net=`0.00267509502` gross=`0.00292525095` cost=`0.00025015593`
- `MEANREVERSION:BNBUSDTM:sell:h10` net=`0.002319886875` gross=`0.002578150177` cost=`0.000258263302`
- `MEANREVERSION:SOLUSDTM:sell:h10` net=`0.00203272281` gross=`0.002291235139` cost=`0.000258512329`
- `MEANREVERSION:BTCUSDTM:sell:h10` net=`0.001925058837` gross=`0.002175214544` cost=`0.000250155706`
- `MEANREVERSION:BTCUSDTM:sell:h10` net=`0.001838852159` gross=`0.002089007939` cost=`0.00025015578`
- `MEANREVERSION:XRPUSDTM:sell:h5` net=`0.001824289901` gross=`0.002075136896` cost=`0.000250846995`

## Missing Fields
- symbol: `0`
- canonical_strategy: `0`
- side: `0`
- source: `0`
- horizon_ticks: `0`
- signed_gross_move: `0`
- estimated_cost: `0`
- signed_net_move: `0`
- expected_net_after_cost: `0`
