# Post-Signal Alpha Target Unit Sanity Audit

- classification: `POST_SIGNAL_ALPHA_TARGET_UNITS_CONSISTENT`
- final_verdict: `STRONGER_ALPHA_SEARCH_CONFIRMED_UNITS_CONSISTENT`
- runtime_artifact_classification: `POST_SIGNAL_TRAJECTORY_NO_TARGETS`
- failure_artifact_classification: `POST_SIGNAL_NO_TARGETS_BECAUSE_SIGNALS_WEAK`
- trajectory_event_count: `86`
- clean_event_count: `86`
- alpha_target_count: `0`

## Unit Findings
- alpha_target: unit=`ratio` reason=`derived_from_p95_signed_net_move_comparison`
- signed_gross_move: unit=`ratio` reason=`quote_mid_relative_delta`
- MFE: unit=`ratio` reason=`max_positive_signed_gross_move`
- MAE: unit=`ratio` reason=`absolute_negative_signed_gross_move`
- estimated_cost: unit=`ratio` reason=`total_cost_ratio_or_ratio_components`
- signed_net_move: unit=`ratio` reason=`signed_gross_move_minus_estimated_cost`
- expected_net_after_cost: unit=`ratio` reason=`candidate.expected_net_after_cost_ratio`
- expected_net_after_full_cost: unit=`not_present_in_post_signal_tracker` reason=`requires_notional_multiplication`

## Compatibility
- p95_signed_net_vs_alpha_target: `True`
- mfe_vs_cost_burden: `True`
- expected_net_vs_post_signal_mfe: `True`

## Normalization Check
- alpha_target_value: `0.12`
- best_signed_net_move: `0.000510836592`
- best_mfe: `0.000762476326`
- best_event_remains_far_from_target: `True`
- best_net_to_target_ratio: `0.0042569716`

## Patch Decision
- patch_runtime: `False`
- patch_analyzer: `False`
- create_stronger_alpha_search_plan: `True`
- reason: alpha target and trajectory net are unit-compatible ratio values
