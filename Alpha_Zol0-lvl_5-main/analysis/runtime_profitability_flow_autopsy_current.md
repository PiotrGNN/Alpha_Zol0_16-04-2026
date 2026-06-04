# Runtime Profitability Flow Autopsy

- classification: `FLOW_AUTOPSY_EXIT_LOSS_DOMINANT`
- profitability_claim: `False`
- next_step: `exit_or_quality_redesign_from_realized_losers`
- contaminated_event_count: `0`
- telemetry_gaps: `position_open_event_absent_inferred_from_position_close`

## Flow Counts
- entry_eval_v2: `336`
- entry_reject_v2: `1373`
- risk_decision: `1374`
- position_open: `30`
- explicit_position_open_event_count: `0`
- inferred_position_open_count: `30`
- position_close: `30`
- downstream_unopened_allow_count: `136`

## Risk Blockers
- entry_min_net_guard: `96`
- net_target_guard: `65`
- min_size: `18`

## Exit / Realized
- net_pnl: `-1.0862168599998687`
- win_rate: `0.3333333333333333`
- dominant_loss_exit_reason: `protective_exit`
- protective_exit: pnl=`-1.887783879999939` count=`17`
- run_end: pnl=`-0.021234299999979542` count=`1`
- take_profit_net: pnl=`0.8798451450000374` count=`9`
- time_decay_exit: pnl=`-0.057043824999987655` count=`3`

## Bucket Summaries
- `BTCUSDTM:MEANREVERSION:sell` trades=`7` net=`-0.24027299499995053` win_rate=`0.2857142857142857` pf=`0.5573868794892484` pass=`False` exits=`{'protective_exit': 4, 'take_profit_net': 2, 'time_decay_exit': 1}`
- `BNBUSDTM:MEANREVERSION:sell` trades=`7` net=`-0.2484725849999541` win_rate=`0.42857142857142855` pf=`0.2915583845533185` pass=`False` exits=`{'protective_exit': 3, 'take_profit_net': 2, 'time_decay_exit': 1, 'run_end': 1}`
- `SOLUSDTM:MEANREVERSION:sell` trades=`7` net=`-0.28827900000001905` win_rate=`0.2857142857142857` pf=`0.4892095859469803` pass=`False` exits=`{'protective_exit': 5, 'take_profit_net': 2}`
- `XRPUSDTM:MEANREVERSION:sell` trades=`9` net=`-0.30919227999994503` win_rate=`0.3333333333333333` pf=`0.3948049400966022` pass=`False` exits=`{'protective_exit': 5, 'take_profit_net': 3, 'time_decay_exit': 1}`

## Provenance
- invalid_result: `results\controlled_kpi_20260604_132000.json` reason=`missing_result_json`
