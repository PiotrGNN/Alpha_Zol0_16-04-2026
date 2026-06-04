# Post-Signal Alpha Target Failure Autopsy

- classification: `POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK`
- trajectory_event_count: `547`
- clean_event_count: `547`
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
- `MEANREVERSION` events=`159` best_net=`0.001713356636` best_mfe=`0.001963513466`
- `MOMENTUM` events=`388` best_net=`0.001650106504` best_mfe=`0.001900955145`

## Best Events
- `MEANREVERSION:BTCUSDTM:sell:h5` net=`0.001713356636` gross=`0.001963513466` cost=`0.00025015683`
- `MOMENTUM:XRPUSDTM:sell:h5` net=`0.001650106504` gross=`0.001900955145` cost=`0.000250848641`
- `MOMENTUM:BTCUSDTM:sell:h10` net=`0.001615036257` gross=`0.001865193127` cost=`0.000250156871`
- `MEANREVERSION:BNBUSDTM:sell:h10` net=`0.00159484429` gross=`0.001846500344` cost=`0.000251656054`
- `MEANREVERSION:BNBUSDTM:sell:h10` net=`0.001594477743` gross=`0.001846133468` cost=`0.000251655725`
- `MEANREVERSION:BTCUSDTM:sell:h10` net=`0.001533323595` gross=`0.001783480453` cost=`0.000250156858`
- `MOMENTUM:XRPUSDTM:sell:h3` net=`0.00147219888` gross=`0.001723047672` cost=`0.000250848792`
- `MOMENTUM:SOLUSDTM:sell:h10` net=`0.001418272147` gross=`0.00166969924` cost=`0.000251427093`
- `MOMENTUM:SOLUSDTM:sell:h5` net=`0.001404615149` gross=`0.001656042772` cost=`0.000251427623`
- `MOMENTUM:BNBUSDTM:sell:h5` net=`0.001393132221` gross=`0.001648101371` cost=`0.00025496915`

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
