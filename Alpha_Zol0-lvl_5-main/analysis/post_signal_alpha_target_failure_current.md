# Post-Signal Alpha Target Failure Autopsy

- classification: `POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK`
- trajectory_event_count: `86`
- clean_event_count: `86`
- contaminated_event_count: `0`
- alpha_target_count: `0`
- target_threshold: `0.12`
- min_samples: `20`

## Root Cause Answers
- why_alpha_target_count_zero: `POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK`
- any_clean_event_close_to_alpha_target: `False`
- best_strategy_family: `MEANREVERSION`
- best_symbol_side: `BNBUSDTM:sell`
- non_trendfollowing_better_than_trendfollowing_baseline: `True`
- focused_paper_observation_candidate: `BNBUSDTM:MEANREVERSION:sell`
- telemetry_only_extension_needed: `False`

## Near Target Counts
- 25pct: `0`
- 50pct: `0`
- 75pct: `0`
- 90pct: `0`

## Strategy Ranking
- `MEANREVERSION` events=`14` best_net=`0.000510836592` best_mfe=`0.000762476326`
- `TRENDFOLLOWING` events=`22` best_net=`0.000355407841` best_mfe=`0.000612447467`
- `MOMENTUM` events=`28` best_net=`0.000355407841` best_mfe=`0.000612447467`
- `UNIVERSALV2` events=`22` best_net=`0.000209784403` best_mfe=`0.000459939788`

## Best Events
- `MEANREVERSION:BNBUSDTM:sell:h1` net=`0.000510836592` gross=`0.000762476326` cost=`0.000251639734`
- `TRENDFOLLOWING:SOLUSDTM:sell:h5` net=`0.000355407841` gross=`0.000612447467` cost=`0.000257039626`
- `MOMENTUM:SOLUSDTM:sell:h5` net=`0.000355407841` gross=`0.000612447467` cost=`0.000257039626`
- `TRENDFOLLOWING:BTCUSDTM:sell:h5` net=`0.000270353045` gross=`0.00052050842` cost=`0.000250155376`
- `MOMENTUM:BTCUSDTM:sell:h5` net=`0.000270353045` gross=`0.00052050842` cost=`0.000250155376`
- `UNIVERSALV2:BTCUSDTM:sell:h2` net=`0.000209784403` gross=`0.000459939788` cost=`0.000250155385`
- `UNIVERSALV2:SOLUSDTM:sell:h2` net=`0.000164011618` gross=`0.00041541982` cost=`0.000251408203`
- `TRENDFOLLOWING:XRPUSDTM:sell:h5` net=`0.000150051781` gross=`0.000400886962` cost=`0.000250835181`
- `TRENDFOLLOWING:SOLUSDTM:buy:h1` net=`0.000142822195` gross=`0.00039423016` cost=`0.000251407965`
- `TRENDFOLLOWING:XRPUSDTM:sell:h5` net=`7.4969612e-05` gross=`0.00032580501` cost=`0.000250835397`

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
