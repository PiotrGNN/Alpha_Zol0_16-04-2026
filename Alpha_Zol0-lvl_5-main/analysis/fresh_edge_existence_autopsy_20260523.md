A. Executive Summary
Strict bucket gate found zero passing side buckets on fresh source. Positive expectancy buckets exist, but only with 1-2 trades; the best 15-trade bucket remains below winrate requirement.

B. Scope
- Inspect fresh source DB: tmp/alpha_history_all_recent_20260523.db
- Inspect companion report used by probe
- Inspect bucket extraction/gating in scripts/controlled_kpi_run.py via _probe_alpha_bootstrap_source_db and _derive_profitability_bucket_gate
- Check missing script reference scripts/refresh_bootstrap_corpus_from_recent_paper.py

C. Locked facts
- KuCoin-only PAPER constraints preserved; no LIVE commands executed.
- Source DB exists: True; companion report exists: True
- position_close rows in DB: 342
- report rows_inserted: 342
- report output matches DB: True
- strict thresholds: trades>=5, winrate>=0.45, expectancy>0.0000
- strict passing side buckets: 0
- near-pass buckets blocked by min-trades: 5

D. Bucket rejection table
| symbol | strategy | side | trade_count | winrate | net_pnl | expectancy | mean_edge | max_edge | fee_adjusted_edge | rejection reason |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| ADAUSDTM | MEANREVERSION | buy | 4 | 0.500000 | -0.0262870066 | -0.0065717516 | null | null | -0.0065717516 | INSUFFICIENT_TRADES |
| ADAUSDTM | MEANREVERSION | sell | 1 | 1.000000 | 0.0013103640 | 0.0013103640 | null | null | 0.0013103640 | INSUFFICIENT_TRADES |
| ADAUSDTM | MOMENTUM | buy | 1 | 0.000000 | -0.0174177319 | -0.0174177319 | null | null | -0.0174177319 | INSUFFICIENT_TRADES |
| ADAUSDTM | TRENDFOLLOWING | buy | 3 | 0.333333 | -0.0206466018 | -0.0068822006 | null | null | -0.0068822006 | INSUFFICIENT_TRADES |
| ADAUSDTM | TRENDFOLLOWING | sell | 4 | 0.250000 | -0.0262111765 | -0.0065527941 | null | null | -0.0065527941 | INSUFFICIENT_TRADES |
| ADAUSDTM | UNIVERSAL | buy | 2 | 0.000000 | -0.0178213759 | -0.0089106880 | null | null | -0.0089106880 | INSUFFICIENT_TRADES |
| ADAUSDTM | UNIVERSAL | sell | 14 | 0.142857 | -0.1120809625 | -0.0080057830 | null | null | -0.0080057830 | NEGATIVE_EDGE |
| BNBUSDTM | MEANREVERSION | buy | 1 | 0.000000 | -0.0027737929 | -0.0027737929 | null | null | -0.0027737929 | INSUFFICIENT_TRADES |
| BNBUSDTM | MEANREVERSION | sell | 2 | 0.500000 | 0.0011857684 | 0.0005928842 | null | null | 0.0005928842 | INSUFFICIENT_TRADES |
| BNBUSDTM | MOMENTUM | buy | 1 | 0.000000 | -0.0012055090 | -0.0012055090 | null | null | -0.0012055090 | INSUFFICIENT_TRADES |
| BNBUSDTM | MOMENTUM | sell | 6 | 0.000000 | -0.0328788418 | -0.0054798070 | null | null | -0.0054798070 | NEGATIVE_EDGE |
| BNBUSDTM | TRENDFOLLOWING | buy | 1 | 0.000000 | -0.0050103991 | -0.0050103991 | null | null | -0.0050103991 | INSUFFICIENT_TRADES |
| BNBUSDTM | UNIVERSAL | sell | 3 | 0.000000 | -0.0079443788 | -0.0026481263 | null | null | -0.0026481263 | INSUFFICIENT_TRADES |
| BTCUSDTM | MEANREVERSION | buy | 4 | 0.250000 | -0.0121325701 | -0.0030331425 | null | null | -0.0030331425 | INSUFFICIENT_TRADES |
| BTCUSDTM | MEANREVERSION | sell | 1 | 1.000000 | 0.0054589859 | 0.0054589859 | null | null | 0.0054589859 | INSUFFICIENT_TRADES |
| BTCUSDTM | MOMENTUM | buy | 10 | 0.000000 | -0.0783429156 | -0.0078342916 | null | null | -0.0078342916 | NEGATIVE_EDGE |
| BTCUSDTM | MOMENTUM | sell | 9 | 0.111111 | -0.0466163723 | -0.0051795969 | null | null | -0.0051795969 | NEGATIVE_EDGE |
| BTCUSDTM | TRENDFOLLOWING | buy | 12 | 0.083333 | -0.0664413349 | -0.0055367779 | null | null | -0.0055367779 | NEGATIVE_EDGE |
| BTCUSDTM | TRENDFOLLOWING | sell | 1 | 0.000000 | -0.0127980244 | -0.0127980244 | null | null | -0.0127980244 | INSUFFICIENT_TRADES |
| BTCUSDTM | UNIVERSAL | buy | 2 | 0.500000 | -0.0065423013 | -0.0032711506 | null | null | -0.0032711506 | INSUFFICIENT_TRADES |
| BTCUSDTM | UNIVERSAL | sell | 13 | 0.000000 | -0.0887480173 | -0.0068267706 | null | null | -0.0068267706 | NEGATIVE_EDGE |
| DOGEUSDTM | MEANREVERSION | buy | 5 | 0.400000 | -0.0515143350 | -0.0103028670 | null | null | -0.0103028670 | NEGATIVE_EDGE |
| DOGEUSDTM | MOMENTUM | buy | 1 | 0.000000 | -0.0049390580 | -0.0049390580 | null | null | -0.0049390580 | INSUFFICIENT_TRADES |
| DOGEUSDTM | MOMENTUM | sell | 1 | 0.000000 | -0.0098262784 | -0.0098262784 | null | null | -0.0098262784 | INSUFFICIENT_TRADES |
| DOGEUSDTM | TRENDFOLLOWING | buy | 1 | 0.000000 | -0.0036771362 | -0.0036771362 | null | null | -0.0036771362 | INSUFFICIENT_TRADES |
| DOGEUSDTM | UNIVERSAL | buy | 5 | 0.000000 | -0.0448446182 | -0.0089689236 | null | null | -0.0089689236 | NEGATIVE_EDGE |
| DOGEUSDTM | UNIVERSAL | sell | 7 | 0.428571 | -0.0332067445 | -0.0047438206 | null | null | -0.0047438206 | NEGATIVE_EDGE |
| ETHUSDTM | MEANREVERSION | buy | 2 | 0.500000 | -0.0037869853 | -0.0018934927 | null | null | -0.0018934927 | INSUFFICIENT_TRADES |
| ETHUSDTM | MEANREVERSION | sell | 10 | 0.300000 | -0.0061190593 | -0.0006119059 | null | null | -0.0006119059 | NEGATIVE_EDGE |
| ETHUSDTM | MOMENTUM | buy | 7 | 0.000000 | -0.0494626800 | -0.0070660971 | null | null | -0.0070660971 | NEGATIVE_EDGE |
| ETHUSDTM | MOMENTUM | sell | 5 | 0.200000 | -0.0576928590 | -0.0115385718 | null | null | -0.0115385718 | NEGATIVE_EDGE |
| ETHUSDTM | TRENDFOLLOWING | buy | 2 | 0.000000 | -0.0067518103 | -0.0033759052 | null | null | -0.0033759052 | INSUFFICIENT_TRADES |
| ETHUSDTM | TRENDFOLLOWING | sell | 1 | 0.000000 | -0.0041051999 | -0.0041051999 | null | null | -0.0041051999 | INSUFFICIENT_TRADES |
| ETHUSDTM | UNIVERSAL | buy | 5 | 0.000000 | -0.0932810538 | -0.0186562108 | null | null | -0.0186562108 | NEGATIVE_EDGE |
| ETHUSDTM | UNIVERSAL | sell | 13 | 0.230769 | -0.0127457797 | -0.0009804446 | null | null | -0.0009804446 | NEGATIVE_EDGE |
| LINKUSDTM | MOMENTUM | buy | 3 | 0.333333 | -0.0086357032 | -0.0028785677 | null | null | -0.0028785677 | INSUFFICIENT_TRADES |
| LINKUSDTM | MOMENTUM | sell | 2 | 0.000000 | -0.0166663668 | -0.0083331834 | null | null | -0.0083331834 | INSUFFICIENT_TRADES |
| LINKUSDTM | TRENDFOLLOWING | buy | 1 | 0.000000 | -0.0124823037 | -0.0124823037 | null | null | -0.0124823037 | INSUFFICIENT_TRADES |
| LINKUSDTM | UNIVERSAL | buy | 4 | 0.000000 | -0.0379206784 | -0.0094801696 | null | null | -0.0094801696 | INSUFFICIENT_TRADES |
| LINKUSDTM | UNIVERSAL | sell | 1 | 1.000000 | 0.0008140865 | 0.0008140865 | null | null | 0.0008140865 | INSUFFICIENT_TRADES |
| SOLUSDTM | MEANREVERSION | buy | 4 | 0.250000 | -0.0002929912 | -0.0000732478 | null | null | -0.0000732478 | INSUFFICIENT_TRADES |
| SOLUSDTM | MEANREVERSION | sell | 7 | 0.428571 | -0.0168913587 | -0.0024130512 | null | null | -0.0024130512 | NEGATIVE_EDGE |
| SOLUSDTM | MOMENTUM | buy | 2 | 0.000000 | -0.0188460940 | -0.0094230470 | null | null | -0.0094230470 | INSUFFICIENT_TRADES |
| SOLUSDTM | MOMENTUM | sell | 5 | 0.000000 | -0.0191318548 | -0.0038263710 | null | null | -0.0038263710 | NEGATIVE_EDGE |
| SOLUSDTM | TRENDFOLLOWING | buy | 6 | 0.333333 | -0.0344289002 | -0.0057381500 | null | null | -0.0057381500 | NEGATIVE_EDGE |
| SOLUSDTM | TRENDFOLLOWING | sell | 3 | 0.333333 | -0.0049894283 | -0.0016631428 | null | null | -0.0016631428 | INSUFFICIENT_TRADES |
| SOLUSDTM | UNIVERSAL | buy | 16 | 0.062500 | -0.0573406357 | -0.0035837897 | null | null | -0.0035837897 | NEGATIVE_EDGE |
| SOLUSDTM | UNIVERSAL | sell | 20 | 0.200000 | -0.1071703467 | -0.0053585173 | null | null | -0.0053585173 | NEGATIVE_EDGE |
| SUIUSDTM | MOMENTUM | buy | 1 | 0.000000 | -0.0052093241 | -0.0052093241 | null | null | -0.0052093241 | INSUFFICIENT_TRADES |
| SUIUSDTM | MOMENTUM | sell | 1 | 0.000000 | -0.0111468320 | -0.0111468320 | null | null | -0.0111468320 | INSUFFICIENT_TRADES |
| SUIUSDTM | UNIVERSAL | buy | 12 | 0.250000 | -0.0145105921 | -0.0012092160 | null | null | -0.0012092160 | NEGATIVE_EDGE |
| SUIUSDTM | UNIVERSAL | sell | 1 | 0.000000 | -0.0001479473 | -0.0001479473 | null | null | -0.0001479473 | INSUFFICIENT_TRADES |
| XRPUSDTM | MEANREVERSION | buy | 9 | 0.333333 | -0.0269043536 | -0.0029893726 | null | null | -0.0029893726 | NEGATIVE_EDGE |
| XRPUSDTM | MEANREVERSION | sell | 2 | 0.500000 | 0.0012972454 | 0.0006486227 | null | null | 0.0006486227 | INSUFFICIENT_TRADES |
| XRPUSDTM | MOMENTUM | buy | 2 | 0.000000 | -0.0076951333 | -0.0038475667 | null | null | -0.0038475667 | INSUFFICIENT_TRADES |
| XRPUSDTM | MOMENTUM | sell | 15 | 0.400000 | 0.0016697954 | 0.0001113197 | null | null | 0.0001113197 | LOW_WINRATE |
| XRPUSDTM | TRENDFOLLOWING | buy | 5 | 0.000000 | -0.0424960917 | -0.0084992183 | null | null | -0.0084992183 | NEGATIVE_EDGE |
| XRPUSDTM | TRENDFOLLOWING | sell | 23 | 0.173913 | -0.1215085918 | -0.0052829823 | null | null | -0.0052829823 | NEGATIVE_EDGE |
| XRPUSDTM | UNIVERSAL | buy | 2 | 0.500000 | -0.0081581850 | -0.0040790925 | null | null | -0.0040790925 | INSUFFICIENT_TRADES |
| XRPUSDTM | UNIVERSAL | sell | 33 | 0.454545 | -0.0339124602 | -0.0010276503 | null | null | -0.0010276503 | NEGATIVE_EDGE |

E. Missing tooling check
- scripts/refresh_bootstrap_corpus_from_recent_paper.py exists: False
- controlled_kpi_run.py still references the missing refresh script in the staleness warning path

F. Root cause classification
- Final classification: CLEAN_EDGE_BLOCKED_BY_MIN_TRADES
- Reason counts:
  - INSUFFICIENT_TRADES: 35
  - LOW_WINRATE: 1
  - NEGATIVE_EDGE: 24

G. Minimal next step
Keep thresholds/readiness unchanged. Accumulate more fresh PAPER closes for currently positive selected sides (e.g., XRPUSDTM|MeanReversion|sell, BNBUSDTM|MeanReversion|sell) until trade_count >= 5, then rerun this autopsy.

H. LIVE status
LIVE remains blocked. No LIVE command executed.

Artifact paths:
- JSON: D:\Alpha_Zol0-lvl_5-main\Alpha_Zol0-lvl_5-main\analysis\fresh_edge_existence_autopsy_20260523.json
- MD: D:\Alpha_Zol0-lvl_5-main\Alpha_Zol0-lvl_5-main\analysis\fresh_edge_existence_autopsy_20260523.md