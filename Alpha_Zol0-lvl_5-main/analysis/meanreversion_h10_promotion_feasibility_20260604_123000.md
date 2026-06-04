# MeanReversion H10 Promotion Feasibility Audit

- classification: `MEANREVERSION_H10_PROMOTION_PATCH_REQUIRED`
- profitability_claim: `False`
- next_step: `test_first_meanreversion_h10_strategy_calibration_patch`
- patch_strategy: `True`
- patch_threshold: `False`
- position_open_count: `0`
- entry_edge_filtered_count: `328`

## Selected Operating Point
- `BTCUSDTM:MEANREVERSION:sell:h10` samples=`52` win_rate=`0.634615` payoff=`1.3853748762252533` expectancy=`0.00042441913007692307` cost_to_gross=`0.18531629700698496`

## Strategy Source
- meanreversion_formula: `abs(ret_3) * 0.65`
- meanreversion_signal_horizon_ticks: `3`
- formula_uses_ret3: `True`
- formula_uses_h10: `False`

## Minimal Patch Boundary
- allowed_candidate: `core/runtime_v2/strategy_stack.py::MeanReversionV2`
- allowed_change: `calibrate MeanReversionV2 expected_move and signal_horizon_ticks to the observed h10 operating point`
- paper_validation_path: `BTCUSDTM/BNBUSDTM MEANREVERSION sell h10 PAPER-only admission and natural trade validation`

## Forbidden Changes
- `ENTRY_MIN_NET_USDT threshold`
- `V2_MIN_EXPECTED_NET_RATIO threshold`
- `risk gate semantics`
- `readiness gate semantics`
- `execution semantics`
- `LIVE mode`
- `seed/fallback/force-open paths`
