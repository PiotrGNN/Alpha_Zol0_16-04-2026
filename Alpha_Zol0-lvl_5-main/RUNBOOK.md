# Runner Validation Runbook

## Purpose
Reproduce the validated PAPER-only post-close summary grace proof without changing BotCore trading semantics.

## Model
- Treat bounded post-close summary grace as envelope-dependent PAPER runner control.
- Record envelope-local minima separately from the conservative cross-envelope preset.
- Do not describe `2/10` as a global baseline.

## Envelope-local minima
- Original envelope local minimum: `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS=2`, `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC=10`
- BTCUSDTM,SOLUSDTM envelope local minimum: `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS=4`, `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC=20`

## Conservative cross-envelope preset
- `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS=4`
- `RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC=20`

## Required opt-in env flags
Set these for the validation run:

```powershell
$env:LIVE = "0"
$env:USE_MOCK = "1"
$env:ZOL0_ALLOW_MOCK = "1"
$env:DIAGNOSTIC_MODE = "1"
$env:DIAG_DISABLE_SIDE_EXPECTANCY = "1"
$env:DIAG_DISABLE_NET_TARGET_GUARD = "1"
$env:DIAG_ALLOW_REENTRY_WHILE_IN_POSITION = "1"
$env:ALPHA_WHITELIST_COLDSTART_ALLOW = "1"
$env:LOSS_COOLDOWN_SEC = "0"
$env:RESEARCH_SINGLE_POST_CLOSE_EVAL_TICK = "1"
$env:RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS = "4"
$env:RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC = "20"
```

## Minimal validation recipe
Run one controlled PAPER corridor through the repaired runner path:

```powershell
@'
from pathlib import Path
from scripts.controlled_kpi_run import _build_diagnostic_runtime_summary, _run_variant, _write_diagnostic_runtime_summary

run_id = "20260331_summarygrace_150_on"
metrics = _run_variant(
    "after",
    150,
    run_id,
    use_mock=True,
    market_type="futures",
    run_symbols="ETHUSDTM",
    paper_auto_open=True,
    paper_auto_close_sec=10,
    equity_snapshot_sec=10,
    quality_profile=True,
    alpha_bootstrap_source_db_url="sqlite:///tmp/alpha_history_auto_recent.db",
    alpha_bootstrap_source_db_glob="tmp/alpha_history_auto_recent.db",
    variant_overrides={
        "DIAGNOSTIC_MODE": "1",
        "ZOL0_ALLOW_MOCK": "1",
        "RESEARCH_SINGLE_POST_CLOSE_EVAL_TICK": "1",
        "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TICKS": "4",
        "RESEARCH_POST_CLOSE_SUMMARY_GRACE_TIMEOUT_SEC": "20",
        "ALPHA_WHITELIST_COLDSTART_ALLOW": "1",
        "LOSS_COOLDOWN_SEC": "0",
        "DIAG_DISABLE_SIDE_EXPECTANCY": "1",
        "DIAG_DISABLE_NET_TARGET_GUARD": "1",
        "DIAG_ALLOW_REENTRY_WHILE_IN_POSITION": "1",
    },
)
summary = _build_diagnostic_runtime_summary(
    db_path=Path(metrics["db_path"]),
    run_id=run_id,
    started_at_utc=metrics["started_at_utc"],
    ended_at_utc=metrics["ended_at_utc"],
    variant="after",
    symbols=["ETHUSDTM"],
    env_flags=metrics["diagnostic_env_flags"],
    metrics=metrics,
)
_write_diagnostic_runtime_summary(summary, f"{run_id}_after")
print(metrics["runner_shutdown_reason"])
print(metrics["post_close_summary_grace_release_reason"])
'@ | python -
```

## Evidence to verify
Check the DB and diagnostic summary artifact for:
- post-close `entry_edge_over_fee_eval`
- `post_close_summary_pre_assembly`
- `post_close_summary_assembly_enter`
- `post_close_summary_payload_built`
- `post_close_summary_emit_attempt`
- `post_close_summary_emit_done`
- `entry_gate_decision_summary`
- `post_close_summary_grace_release_reason = summary_emit_done`
- `runner_shutdown_reason = close_flush_done_pending_positions_zero`

## Boundary note
- BTC/SOL `3/20` failed with:
  - `post_close_summary_pre_assembly = 0`
  - `post_close_summary_emit_done = 0`
  - `entry_gate_decision_summary = 0`
  - `release_reason = null`

## Artifacts
- DB: `tmp/controlled_kpi_after_20260331_summarygrace_150_on.db`
- Diagnostic summary: `artifacts/diagnostics/diagnostic_runtime_summary_20260331_summarygrace_150_on_after.json`
