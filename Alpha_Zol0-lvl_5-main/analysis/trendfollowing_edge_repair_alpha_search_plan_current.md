# TrendFollowingV2 edge repair and stronger-alpha search plan

- classification: `EDGE_REPAIR_AND_STRONGER_ALPHA_SEARCH`
- profitability_claim: `False`
- max_expected_net_after_full_cost: `0.056727152451426704`
- do_not_lower_thresholds: `True`
- live_allowed: `False`

## TrendFollowingV2 repair gates
- offline_expected_net_replay: Replay TrendFollowingV2 ret_3 signals against current cost and risk formulas before any strategy mutation. Pass: `candidate families produce expected_net_after_full_cost >= 0.08 and ratio >= 1.10 without threshold relaxation`
- signal_timing_audit: Measure whether ret_3 enters after most move has already occurred. Pass: `post-signal MFE supports current expected_move formula after costs`
- cost_burden_replay: Separate weak signal from fee/spread/slippage overburden. Pass: `edge remains positive after current total cost ratio with margin to reach full-cost net >= 0.08`
- paper_only_shadow_candidate_test: Run clean PAPER-only runtime smoke only after offline replay finds stronger TFV2 parameter family. Pass: `natural current-semantics admission, completed clean trades, no profitability claim until sufficient sample`

## Stronger-alpha search lanes
- P1 `MicroBreakoutV2` source=`fresh discovery required` min_expected=`0.08` rationale=`search for impulse edges with expected_net_after_full_cost >= 0.08 under current gates`
- P2 `MomentumV2` source=`fresh discovery required` min_expected=`0.08` rationale=`one-tick impulse horizon may better match short PAPER exit geometry than ret_3 trend lag`
- P3 `MeanReversionV2` source=`fresh discovery required` min_expected=`0.08` rationale=`test opposite-side extreme reversion where stop-risk ratio can exceed 1.10 naturally`
- P4 `TrendFollowingV2` source=`current rejected runtime evidence` min_expected=`0.08` rationale=`keep as repair benchmark, not as immediate runtime candidate`
- P5 `TrendFollowingV2` source=`current rejected runtime evidence` min_expected=`0.08` rationale=`keep as repair benchmark, not as immediate runtime candidate`
- P6 `TrendFollowingV2` source=`current rejected runtime evidence` min_expected=`0.08` rationale=`keep as repair benchmark, not as immediate runtime candidate`

## Rejected current candidates
- AVAXUSDTM:TrendFollowingV2:sell: reason=`strategy_weakness`, max_expected=`0.04826070387426362`, max_ratio=`0.9090909090909091`
- BNBUSDTM:TrendFollowingV2:buy: reason=`strategy_weakness`, max_expected=`0.05386902950622281`, max_ratio=`0.9090909090909091`
- DOTUSDTM:TrendFollowingV2:sell: reason=`strategy_weakness`, max_expected=`0.056727152451426704`, max_ratio=`0.9454525408571117`

## Execution sequence
- Do not mutate thresholds.
- Build/refresh clean discovery corpus under KuCoin PAPER only.
- Rank non-TrendFollowing and repaired TrendFollowing candidates by expected_net_after_full_cost >= 0.08 and ratio >= 1.10.
- Run one candidate at a time through clean current runtime smoke.
- Promote only candidates with natural opens and clean completed trade evidence; do not claim profitability before sample sufficiency.
