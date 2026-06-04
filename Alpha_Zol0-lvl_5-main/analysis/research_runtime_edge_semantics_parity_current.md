# Research vs Runtime Edge Semantics Parity Audit

- edge_parity_classification: `RESEARCH_RUNTIME_SOURCE_MISMATCH`
- threshold_classification: `MIN_NET_THRESHOLD_APPLIED_CORRECTLY`
- strategy_classification: `TRENDFOLLOWINGV2_RUNTIME_EDGE_TOO_WEAK`
- overall_classification: `FRESH_RESEARCH_EDGE_NOT_RUNTIME_ADMISSIBLE_DUE_TO_SOURCE_MISMATCH`
- final_verdict: `SOURCE_PARITY_REPAIR_REQUIRED`
- profitability_claim: `False`

## Primary Delta
- candidate: `AVAXUSDTM:TrendFollowingV2:buy`
- research_edge: `0.1236719064890212`
- runtime_max_edge: `0.06944317126030092`
- delta_absolute: `-0.05422873522872028`
- delta_percent: `-43.84887139548896`
- effective_threshold: `0.12`
- data_source_mismatch: `True`
- missing_evidence: `['candle_end', 'candle_start', 'fee_estimate', 'quote_source', 'slippage_estimate', 'timestamp']`

## Candidate Findings
| candidate | research_edge | runtime_max | delta_pct | threshold | blocker | source_mismatch | missing_evidence |
|---|---:|---:|---:|---:|---|---:|---|
| AVAXUSDTM:TrendFollowingV2:buy | 0.1236719064890212 | 0.06944317126030092 | -43.84887139548896 | 0.12 | entry_edge_filtered | True | candle_end,candle_start,fee_estimate,quote_source,slippage_estimate,timestamp |
| DOTUSDTM:TrendFollowingV2:sell | None | 0.056727152451426704 | None | 0.12 | missing_fresh_runtime_smoke | False | fresh_runtime_smoke |
| BNBUSDTM:TrendFollowingV2:buy | None | 0.023586173712315767 | None | 0.12 | entry_edge_filtered | True | quote_source |
| AVAXUSDTM:TrendFollowingV2:sell | None | 0.03410747308055826 | None | 0.12 | entry_edge_filtered | True | quote_source |

## Formula Parity
- formula_mismatch_exists: `False`
- formula: `{'expected_net_after_full_cost': 'USDT', 'expected_net_after_cost': 'ratio', 'fee_spread_slippage': 'ratio/bps depending field', 'ENTRY_MIN_NET_USDT': 'USDT'}`

## Source Parity
- research_market_data_source: `kucoin_public_futures_klines`
- research_candidate_source: `fresh_kucoin_public_klines_research`
- runtime_profile_sources: `{'rolling_quote_window': 204}`
- edge_decay_before_runtime: `not_provable_without_research_candidate_timestamp`

## Patch Decision
- recommended_next_target: `source_parity_repair_or_source_label_enforcement`
- reason: `research uses KuCoin public kline path while runtime evidence uses rolling quote window; current artifacts cannot prove timestamp decay.`
