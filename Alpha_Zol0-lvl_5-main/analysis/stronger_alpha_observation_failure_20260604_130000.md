# Post-Signal Alpha Target Failure Autopsy

- classification: `POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK`
- trajectory_event_count: `1695`
- clean_event_count: `1695`
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
- `MEANREVERSION` events=`1112` best_net=`0.003372035335` best_mfe=`0.003622191262`
- `MOMENTUM` events=`539` best_net=`0.002029670957` best_mfe=`0.002279828078`
- `TRENDFOLLOWING` events=`22` best_net=`0.000355407841` best_mfe=`0.000612447467`
- `UNIVERSALV2` events=`22` best_net=`0.000209784403` best_mfe=`0.000459939788`

## Best Events
- `MEANREVERSION:BTCUSDTM:sell:h10` net=`0.003372035335` gross=`0.003622191262` cost=`0.000250155927`
- `MEANREVERSION:SOLUSDTM:sell:h10` net=`0.003130361574` gross=`0.003388869195` cost=`0.000258507621`
- `MEANREVERSION:XRPUSDTM:sell:h10` net=`0.003128661664` gross=`0.003379508658` cost=`0.000250846995`
- `MEANREVERSION:SOLUSDTM:sell:h10` net=`0.002981546931` gross=`0.003232964898` cost=`0.000251417967`
- `MEANREVERSION:SOLUSDTM:sell:h10` net=`0.002976287003` gross=`0.003227705775` cost=`0.000251418772`
- `MEANREVERSION:BNBUSDTM:sell:h10` net=`0.002962267425` gross=`0.00322218183` cost=`0.000259914406`
- `MEANREVERSION:BTCUSDTM:sell:h10` net=`0.00267509502` gross=`0.00292525095` cost=`0.00025015593`
- `MEANREVERSION:XRPUSDTM:sell:h5` net=`0.002502794947` gross=`0.002753642221` cost=`0.000250847275`
- `MEANREVERSION:XRPUSDTM:sell:h5` net=`0.002488530127` gross=`0.002741920446` cost=`0.000253390319`
- `MEANREVERSION:BTCUSDTM:sell:h5` net=`0.002432943303` gross=`0.002683098575` cost=`0.000250155272`

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
