# Post-Signal Alpha Target Failure Autopsy

- classification: `POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK`
- trajectory_event_count: `155`
- clean_event_count: `155`
- contaminated_event_count: `0`
- alpha_target_count: `0`
- target_threshold: `0.12`
- min_samples: `20`

## Root Cause Answers
- why_alpha_target_count_zero: `POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK`
- any_clean_event_close_to_alpha_target: `False`
- best_strategy_family: `MOMENTUM`
- best_symbol_side: `BTCUSDTM:sell`
- non_trendfollowing_better_than_trendfollowing_baseline: `True`
- focused_paper_observation_candidate: `BTCUSDTM:MOMENTUM:sell`
- telemetry_only_extension_needed: `False`

## Near Target Counts
- 25pct: `0`
- 50pct: `0`
- 75pct: `0`
- 90pct: `0`

## Strategy Ranking
- `MEANREVERSION` events=`32` best_net=`0.002029670957` best_mfe=`0.002279828078`
- `MOMENTUM` events=`123` best_net=`0.002029670957` best_mfe=`0.002279828078`

## Best Events
- `MOMENTUM:BTCUSDTM:sell:h10` net=`0.002029670957` gross=`0.002279828078` cost=`0.000250157121`
- `MEANREVERSION:BTCUSDTM:sell:h10` net=`0.002029670957` gross=`0.002279828078` cost=`0.000250157121`
- `MOMENTUM:SOLUSDTM:sell:h10` net=`0.001961893389` gross=`0.002213321339` cost=`0.000251427949`
- `MEANREVERSION:BTCUSDTM:sell:h10` net=`0.001773108902` gross=`0.002023265988` cost=`0.000250157086`
- `MOMENTUM:SOLUSDTM:sell:h3` net=`0.001691303773` gross=`0.001942732253` cost=`0.00025142848`
- `MOMENTUM:XRPUSDTM:sell:h10` net=`0.001668903193` gross=`0.001919752641` cost=`0.000250849448`
- `MOMENTUM:BTCUSDTM:sell:h10` net=`0.001665414696` gross=`0.001915571839` cost=`0.000250157143`
- `MEANREVERSION:BTCUSDTM:sell:h10` net=`0.001665414696` gross=`0.001915571839` cost=`0.000250157143`
- `MOMENTUM:XRPUSDTM:sell:h3` net=`0.001643419751` gross=`0.001894269199` cost=`0.000250849448`
- `MOMENTUM:SOLUSDTM:sell:h5` net=`0.001633465062` gross=`0.001884893011` cost=`0.000251427949`

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
