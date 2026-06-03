# Entry Min Net Threshold Calibration Audit

- Classification: `ENTRY_MIN_NET_0_12_SUPPORTED_BY_NEGATIVE_LOWER_BUCKETS`
- Final verdict: `ENTRY_MIN_NET_THRESHOLD_CHANGE_NOT_JUSTIFIED`
- Patch decision: `no_threshold_change`
- Clean controlled runs: `10` / `30`
- Near-miss min-net guard count: `1`

## Bucket-Level Economics

| bucket | runtime_events | opens | clean_trades | net_pnl | expectancy | profit_factor | dominant_rejections |
|---|---:|---:|---:|---:|---:|---:|---|
| <0.03 | 118 | 21 | 21 | -0.0436512400 | -0.0020786305 | 0.7155449703784255 | entry_min_net_guard:76, decision_passed:21 |
| 0.03-0.05 | 6 | 2 | 2 | -0.0255881100 | -0.0127940550 | 0.0 | decision_passed:2, entry_min_net_guard:2 |
| 0.05-0.08 | 3 | 1 | 1 | -0.0255461700 | -0.0255461700 | 0.0 | decision_passed:1, entry_min_net_guard:1 |
| 0.08-0.10 | 0 | 0 | 0 | 0.0000000000 | 0.0000000000 | 0.0 |  |
| 0.10-0.12 | 0 | 0 | 0 | 0.0000000000 | 0.0000000000 | 0.0 |  |
| 0.12-0.15 | 0 | 0 | 0 | 0.0000000000 | 0.0000000000 | 0.0 |  |
| >0.15 | 0 | 0 | 0 | 0.0000000000 | 0.0000000000 | 0.0 |  |

## Hypothetical Threshold Simulation

| threshold | admitted_events | clean_trades | net_pnl | expectancy | sample_sufficient |
|---:|---:|---:|---:|---:|---|
| 0.05 | 3 | 1 | -0.0255461700 | -0.0255461700 | False |
| 0.08 | 0 | 0 | 0.0000000000 | 0.0000000000 | False |
| 0.10 | 0 | 0 | 0.0000000000 | 0.0000000000 | False |
| 0.12 | 0 | 0 | 0.0000000000 | 0.0000000000 | False |
