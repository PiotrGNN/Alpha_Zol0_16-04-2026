# Next Research Candidate Runtime Smoke

- Classification: `NO_RESEARCH_CANDIDATE_PASSES_CURRENT_RUNTIME_GATES`
- Profitability claim: `False`
- Runtime threshold: `ENTRY_MIN_NET_USDT=0.12`

| candidate | run_id | clean | allowlist_match | profile | min_net_guard | opens | clean_trades | classification |
|---|---|---:|---:|---:|---:|---:|---:|---|
| BNBUSDTM:TrendFollowingV2:buy | 20260603_180101 | True | True | True | 20 | 0 | 0 | NEXT_CANDIDATE_BLOCKED_BY_MIN_NET |
| AVAXUSDTM:TrendFollowingV2:sell | 20260603_182201 | True | True | True | 28 | 0 | 0 | NEXT_CANDIDATE_BLOCKED_BY_MIN_NET |

## Candidate Details

### BNBUSDTM:TrendFollowingV2:buy
- result: `results\controlled_kpi_20260603_180101.json`
- db: `D:\Alpha_Zol0-lvl_5-main\Alpha_Zol0-lvl_5-main\tmp\controlled_kpi_after_20260603_180101.db`
- contamination: `{'seed': 0, 'fallback': 0, 'force_open': 0, 'mock': 0, 'forced_cycle': 0, 'pending_positions': 0, 'live': 0, 'process_returncode': 0}`
- target reasons: `{'entry_edge_filtered': 387, 'allow': 20, 'entry_min_net_guard': 20}`
- global reasons: `{'symbol_strategy_side_allowlist': 858, 'entry_edge_filtered': 516, 'no_runtime_profile': 240, 'entry_min_net_guard': 30, 'allow': 20}`
- expected full-cost stats: `{'count': 10, 'min': 0.01671284650768015, 'max': 0.05386902950622281, 'mean': 0.030537919551154792}`

### AVAXUSDTM:TrendFollowingV2:sell
- result: `results\controlled_kpi_20260603_182201.json`
- db: `D:\Alpha_Zol0-lvl_5-main\Alpha_Zol0-lvl_5-main\tmp\controlled_kpi_after_20260603_182201.db`
- contamination: `{'seed': 0, 'fallback': 0, 'force_open': 0, 'mock': 0, 'forced_cycle': 0, 'pending_positions': 0, 'live': 0, 'process_returncode': 0}`
- target reasons: `{'entry_edge_filtered': 210, 'allow': 28, 'entry_min_net_guard': 28}`
- global reasons: `{'no_runtime_profile': 765, 'symbol_strategy_side_allowlist': 459, 'entry_edge_filtered': 280, 'entry_min_net_guard': 42, 'allow': 28}`
- expected full-cost stats: `{'count': 14, 'min': 0.018596702436875164, 'max': 0.044791973511999386, 'mean': 0.02584837712591605}`

