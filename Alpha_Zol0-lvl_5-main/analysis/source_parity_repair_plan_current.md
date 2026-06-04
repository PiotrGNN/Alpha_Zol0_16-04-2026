# Source Parity Repair Plan

- classification: `SOURCE_PARITY_ENFORCEMENT_PATCH_REQUIRED`
- patch_class: `B`
- runtime_decision_change: `False`
- threshold_change: `False`
- runtime_admissible_candidate_count: `0`
- source_parity_classification: `RESEARCH_RUNTIME_SOURCE_MISMATCH_NOT_RUNTIME_ADMISSIBLE`

## Answers
- where_research_source_selected: `{'file': 'scripts/discover_new_alpha_search_space.py', 'line': 43, 'detail': 'Research universe labels public KuCoin futures klines as RESEARCH_SOURCE; candidate rows use CANDIDATE_SOURCE.'}`
- where_runtime_source_selected: `{'file': 'core/runtime_v2/feature_engine.py', 'line': 68, 'detail': 'Runtime feature profile source is rolling_quote_window and is emitted through runtime_v2 telemetry.'}`
- where_candidate_promoted_from_research_to_runtime_smoke: `{'file': 'scripts/discover_new_alpha_search_space.py', 'line': 316, 'detail': 'selected_hypothesis/candidate_rank reporting is the promotion/reporting seam; runtime smoke itself remains manual/controlled and unchanged.'}`
- missing_metadata_to_prove_source_parity: `['source_overlap_proven remains false unless source match or overlap proof is supplied']`
- can_enforce_without_strategy_execution_change: `True`
- minimal_patch_surface: `['scripts/discover_new_alpha_search_space.py', 'tests/test_research_runtime_source_parity_contract.py']`

## Patch Decision
- reason: `Public-kline research candidates cannot be reported as runtime-admissible against rolling_quote_window runtime unless source match or overlap proof exists.`

## Minimal Patch Surface
- `scripts/discover_new_alpha_search_space.py`
- `tests/test_research_runtime_source_parity_contract.py`
