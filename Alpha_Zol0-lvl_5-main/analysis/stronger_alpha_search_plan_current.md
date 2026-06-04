# Stronger Alpha Search Plan

- classification: `STRONGER_ALPHA_SEARCH_PLAN_READY`
- mode: `PAPER_ONLY`
- exchange: `KuCoin`

## Ranked Families
- `1. MicroBreakoutV2` role=`primary_search`
  - hypothesis: Short-horizon order-flow/quote-window impulse can create post-cost signed movement before spread decay.
  - promotion: clean source=rolling_quote_window; non-contaminated seed/fallback/mock/force_open/forced_cycle flags; sample_count >= 20 per symbol/side/horizon bucket; p95_signed_net_move >= 0.12 in the same ratio unit as trajectory net; expected_net_after_cost remains positive after total_cost_ratio
  - validation: Run PAPER-only capture with RUNTIME_V2_POST_SIGNAL_TRAJECTORY=1, LIVE=0, USE_MOCK=0, no seed/fallback/force-open; analyze only natural post_signal_trajectory_v2 rows.
- `2. MomentumV2` role=`secondary_search`
  - hypothesis: Directional continuation after quote-window momentum can exceed fee/spread burden in selected symbol/side buckets.
  - promotion: clean non-TrendFollowing bucket; sample_count >= 20; p95_signed_net_move >= 0.12 ratio target; median MFE minus cost burden > 0
  - validation: Observe naturally rejected/admitted MomentumV2 candidates in PAPER-only runtime and compare against TrendFollowing baseline.
- `3. MeanReversionV2` role=`tertiary_search`
  - hypothesis: Quote-window overextension can revert enough to create post-cost signed net movement.
  - promotion: clean bucket with sample_count >= 20; p95_signed_net_move >= 0.12 ratio target; best events repeat across more than one run or timestamp cluster
  - validation: Focus PAPER observation on best clean near-target symbol/side only after unit sanity remains consistent.
- `4. TrendFollowingV2` role=`demoted_comparator_only`
  - hypothesis: Baseline directional continuation comparator, not primary stronger-alpha source.
  - promotion: comparator only; do not promote over non-TrendFollowing unless explicitly requested
  - validation: Keep as baseline in the same PAPER-only post-signal reports.
