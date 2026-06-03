# New Alpha Search Space Inventory

- generated_at_utc: `2026-06-03T12:15:52.785708+00:00`
- classification: `NEW_ALPHA_INVENTORY_BUILT`
- min_expected_net_usdt: `0.08`
- single_best_hypothesis: `DOTUSDTM:TrendFollowingV2:sell`

## Read-only Surfaces
- `core/runtime_v2/runner.py` - _parse_symbols, ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST, runtime_v2 telemetry loop
- `core/runtime_v2/strategy_stack.py` - TrendFollowingV2, MomentumV2, MeanReversionV2, UniversalV2
- `core/runtime_v2/decision_engine.py` - expected_net_after_cost and probability gates
- `core/runtime_v2/risk_engine.py` - expected_net_after_full_cost sizing and ENTRY_MIN_NET_USDT guard
- `scripts/autonomous_paper_profit_campaign.py` - candidate symbol universe, exploratory allowlist, campaign floor 0.08
- `scripts/discover_new_alpha_search_space.py` - fresh public KuCoin kline research-only pre-runtime validation

## Candidate Families
| family | classification | symbols | evidence/reason |
|---|---|---|---|
| fresh_ex_current_symbol_trendfollowing | NEW_ALPHA_CANDIDATE_FOUND_FOR_PAPER_VALIDATION | DOTUSDTM, BNBUSDTM, AVAXUSDTM | analysis/new_alpha_research_validation_current.json |
| fresh_ex_current_symbol_momentum | NO_NEW_ALPHA_CANDIDATE_FOUND | DOTUSDTM, BNBUSDTM | public-kline research produced rejected/top momentum rows but no selected candidate above full-cost floor |
| legacy_current_space_btc_sol_xrp_micro_edge | CURRENT_SEARCH_SPACE_CLOSED | BTCUSDTM, SOLUSDTM, XRPUSDTM | loop-breaker verdict frozen and economic discovery qualified_candidate_count=0 |

## Selected Hypotheses
| rank | candidate | expected_net | notional | probability | confidence |
|---:|---|---:|---:|---:|---:|
| 1 | DOTUSDTM:TrendFollowingV2:sell | 0.11373500855615154 | 20.07 | 0.9999999934813502 | 1.0 |
| 2 | BNBUSDTM:TrendFollowingV2:buy | 0.08144557636074735 | 19.343999999999998 | 0.9999999542792811 | 1.0 |
| 3 | AVAXUSDTM:TrendFollowingV2:sell | 0.08137487663914103 | 23.3016 | 0.9999998320920496 | 1.0 |

## Next PAPER Validation Scope
- RUN_SYMBOLS: `DOTUSDTM`
- ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST: `DOTUSDTM:TrendFollowingV2:sell`
- Constraints: `PAPER_ONLY_NO_SEED_NO_FALLBACK_NO_DIAGNOSTIC_FORCE_OPEN`
