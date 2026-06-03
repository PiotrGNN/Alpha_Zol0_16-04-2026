# Expected-Net Calibration Provenance Audit

- Classification: `LOWER_BUCKET_TRADES_OPENED_UNDER_LEGACY_OR_DISABLED_GUARD`
- Final verdict: `LOWER_BUCKET_EVIDENCE_NOT_CURRENT_SEMANTICS`
- Lower-bucket clean trade count: `24`
- Net PnL: `-0.094785519999997`
- Expectancy: `-0.003949396666666541`
- Provenance counts: `{'OPENED_UNDER_LEGACY_THRESHOLD': 24}`

## Calibration

- `count`: `24`
- `average_expected_net`: `0.016099570317985243`
- `average_realized_pnl`: `-0.003949396666666541`
- `average_prediction_error`: `0.020048966984651785`
- `correlation`: `-0.3072107542800192`
- `overestimation_ratio`: `-4.076463236490743`

## Decomposition

- `net_pnl`: `-0.094785519999997`
- `expectancy`: `-0.003949396666666541`
- `profit_factor`: `0.5367049292154902`
- `green_to_red_count`: `2`
- `fee_inversion_count`: `1`
- `protective_exit_count`: `8`
- `missing_calibration_profile_count`: `24`
- `severe_time_horizon_mismatch_count`: `24`

## Trade Sample

| run | symbol | strategy | side | expected | realized | exit | provenance |
|---|---|---|---|---:|---:|---|---|
| 20260602_222423 | BTCUSDTM | TrendFollowingV2 | buy | 0.0161275735 | -0.0232745500 | protective_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_222423 | BTCUSDTM | TrendFollowingV2 | buy | 0.0091860772 | -0.0139755600 | protective_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_213756 | SOLUSDTM | TrendFollowingV2 | buy | 0.0042540620 | -0.0171551700 | protective_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_213756 | SOLUSDTM | TrendFollowingV2 | buy | 0.0108182997 | -0.0126546600 | protective_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0028635628 | 0.0254691300 | take_profit_net | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0305585972 | -0.0093333900 | time_decay_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0199840030 | 0.0029659800 | time_decay_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0259833691 | 0.0044645700 | time_decay_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0088443988 | 0.0119620200 | take_profit_net | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0122670799 | 0.0143598000 | take_profit_net | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0279742847 | 0.0182551500 | time_decay_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0511489411 | -0.0255461700 | time_decay_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0239700663 | -0.0249425100 | protective_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0070326347 | -0.0052282000 | time_decay_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0034180005 | 0.0005711400 | time_decay_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0055095028 | -0.0022293000 | time_decay_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0037964903 | 0.0011695600 | time_decay_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0093128727 | 0.0007683600 | time_decay_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0193927558 | 0.0194484900 | take_profit_net | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0459833959 | -0.0162547200 | time_decay_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0152109971 | -0.0149340700 | protective_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_211507 | SOLUSDTM | TrendFollowingV2 | buy | 0.0041713455 | -0.0110336600 | protective_exit | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_204821 | SOLUSDTM | TrendFollowingV2 | buy | 0.0106764766 | 0.0103702400 | take_profit_net | OPENED_UNDER_LEGACY_THRESHOLD |
| 20260602_204821 | SOLUSDTM | TrendFollowingV2 | buy | 0.0179049005 | -0.0280280000 | protective_exit | OPENED_UNDER_LEGACY_THRESHOLD |
