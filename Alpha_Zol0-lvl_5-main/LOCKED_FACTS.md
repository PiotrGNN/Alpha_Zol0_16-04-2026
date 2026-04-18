# Locked Facts

## Runner / PAPER validation state
- KuCoin-only.
- PAPER-only.
- No LIVE impact.
- No BotCore trading semantics were changed for the validated fix.
- Bounded post-close summary grace is an envelope-dependent PAPER runner control, not a global constant.

## Envelope-local minima and conservative preset
- Original envelope local minimum:
  - `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS=2`
  - `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC=10`
- BTCUSDTM,SOLUSDTM envelope local minimum:
  - `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS=4`
  - `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC=20`
- Conservative cross-envelope research preset:
  - `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS=4`
  - `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC=20`

## Post-close summary cutoff cause
- Proven diagnostic conclusion before the fix: `PROCESS_TERMINATES_BEFORE_SUMMARY_BLOCK_ENTRY_CONFIRMED`.
- Root cause: the runner terminated the process before BotCore could complete the post-close summary path.
- Proven stop point before the fix:
  - post-close flow reached `canonical_gate_read`
  - post-close flow reached `entry_edge_over_fee_eval`
  - post-close flow did not reach `post_close_summary_pre_assembly`
  - post-close flow did not reach `post_close_summary_assembly_enter`
  - post-close flow did not reach `post_close_summary_emit_done`
  - post-close flow did not reach `entry_gate_decision_summary`
  - runner shutdown reason remained `close_flush_done_pending_positions_zero`

## Confirmed bounded runner-only fix
- Final validated classification: `RUNNER_ONLY_POST_CLOSE_SUMMARY_GRACE_CONFIRMED`.
- Fix shape:
  - runner-only
  - PAPER-only
  - opt-in
  - bounded
  - gated by `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS`
- BotCore summary code was not changed.
- The runner only defers shutdown after a proven post-close eval cycle until summary completion is observed or the bounded grace expires.

## Validated run evidence
- Validated run ID: `20260331_summarygrace_150_on`
- Evidence sequence after `position_close`:
  - `entry_edge_over_fee_eval`
  - `post_close_summary_pre_assembly`
  - `post_close_summary_assembly_enter`
  - `post_close_summary_payload_built`
  - `post_close_summary_emit_attempt`
  - `entry_gate_decision_summary`
  - `post_close_summary_emit_done`
- Runner release reason: `summary_emit_done`
- Final shutdown reason: `close_flush_done_pending_positions_zero`

## Failing boundary evidence
- BTC/SOL cross-envelope failure at `3/20`:
  - `post_close_summary_pre_assembly = 0`
  - `post_close_summary_emit_done = 0`
  - `entry_gate_decision_summary = 0`
  - `release_reason = null`
  - `shutdown_reason = close_flush_done_pending_positions_zero`
- Interpretation:
  - `2/10` remains valid only as the original-envelope local minimum.
  - `2/10` is not a global baseline because the BTC/SOL envelope required a larger bounded grace window.

## Persistence
- The runner termination trace is persisted in the diagnostic runtime summary artifact.
- The summary artifact used for validation:
  - `artifacts/diagnostics/diagnostic_runtime_summary_20260331_summarygrace_150_on_after.json`
