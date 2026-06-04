# Next Research Candidate Runtime Smoke

- Classification: `NO_RESEARCH_CANDIDATE_PASSES_CURRENT_RUNTIME_GATES`
- Profitability claim: `False`
- Runtime threshold: `ENTRY_MIN_NET_USDT=0.12`
- Runtime mode: `KuCoin PAPER`, `LIVE=0`, `USE_MOCK=0`

| candidate | run_id | clean | allowlist_match | profile | min_net_guard | opens | clean_trades | classification |
|---|---|---:|---:|---:|---:|---:|---:|---|
| BNBUSDTM:TrendFollowingV2:buy | 20260604_010148 | True | True | True | 10 | 0 | 0 | NEXT_CANDIDATE_BLOCKED_BY_MIN_NET |
| AVAXUSDTM:TrendFollowingV2:sell | 20260604_012213 | True | True | True | 24 | 0 | 0 | NEXT_CANDIDATE_BLOCKED_BY_MIN_NET |

## Candidate Details

### BNBUSDTM:TrendFollowingV2:buy
- result: `results\controlled_kpi_20260604_010148.json`
- db: `D:\Alpha_Zol0-lvl_5-main\Alpha_Zol0-lvl_5-main\tmp\controlled_kpi_after_20260604_010148.db`
- contamination: `{'seed': 0, 'fallback': 0, 'force_open': 0, 'mock': 0, 'forced_cycle': 0, 'pending_positions': 0, 'live': 0, 'process_returncode': 0}`
- target reasons: `{'entry_edge_filtered': 342, 'allow': 10, 'entry_min_net_guard': 10}`
- global reasons: `{'symbol_strategy_side_allowlist': 969, 'entry_edge_filtered': 456, 'no_runtime_profile': 240, 'allow': 10, 'entry_min_net_guard': 15, 'net_target_guard': 3}`
- expected full-cost stats: `{'count': 5, 'min': 0.008319553793948758, 'max': 0.023586173712315767, 'mean': 0.01982571080621421}`

### AVAXUSDTM:TrendFollowingV2:sell
- result: `results\controlled_kpi_20260604_012213.json`
- db: `D:\Alpha_Zol0-lvl_5-main\Alpha_Zol0-lvl_5-main\tmp\controlled_kpi_after_20260604_012213.db`
- contamination: `{'seed': 0, 'fallback': 0, 'force_open': 0, 'mock': 0, 'forced_cycle': 0, 'pending_positions': 0, 'live': 0, 'process_returncode': 0}`
- target reasons: `{'entry_edge_filtered': 195, 'allow': 24, 'entry_min_net_guard': 24}`
- global reasons: `{'no_runtime_profile': 903, 'symbol_strategy_side_allowlist': 366, 'entry_edge_filtered': 260, 'allow': 24, 'entry_min_net_guard': 36}`
- expected full-cost stats: `{'count': 12, 'min': 0.01589584119450839, 'max': 0.03410747308055826, 'mean': 0.024866997023869183}`
