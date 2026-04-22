# Runner Validation Runbook

## Guarded Live Promotion Protocol (2026-04-20)

### Purpose
Execute Phase 1 LIVE rollout (ETHUSDTM only) following `PROMOTE_CANDIDATE`
gate and `POST_GREEN_RUNTIME_CONTRACT_FIXED` validation.

### Pre-requisites
- Gate: `paper_readiness_gate_20260420_072346` — PASS / PROMOTE_CANDIDATE
- Contract: POST_GREEN_RUNTIME_CONTRACT_FIXED — 17 runs, 5 triggered exits validated
- KuCoin LIVE API credentials in environment:
  `KUCOIN_API_KEY`, `KUCOIN_API_SECRET`, `KUCOIN_API_PASSPHRASE`

### Launch (deterministic runtime readiness gate)
```powershell
Push-Location "d:\Alpha_Zol0-lvl_5-main\Alpha_Zol0-lvl_5-main"
python scripts\run_paper_readiness_gate.py
.\scripts\live_rollout_launch.ps1
Pop-Location
```

### Key overrides (from `config/live_rollout_ethusdtm.env`)
| Variable | Value | Reason |
|---|---|---|
| `LIVE` | `1` | Enable live mode |
| `LIVE_ARMED` | `1` | Arm gate |
| `LIVE_READINESS_SNAPSHOT_PATH` | `tmp/live_readiness_snapshot.json` | Deterministic readiness evidence |
| `ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST` | `ETHUSDTM:MOMENTUM:buy` | ETH-only restriction |
| `EXIT_CLOSE_ATTEMPT_FEE_GUARD_COOLDOWN_SEC` | `10` | Override 300s default (documented 2026-04-20) |

### Hard stop conditions (auto-detected by `scripts/live_rollout_monitor.py`)
| Condition | Threshold |
|---|---|
| Abnormal exit delay | `post_green_bnr_time_forced_exit_sec` > 120s |
| Consecutive losses | ≥ 3 consecutive losing trades |
| Contract inconsistency | `position_close` missing post-green attribution fields |
| Max drawdown | Cumulative PnL drawdown > 2% |

### Milestones
- 30 closed trades → run can be stopped voluntarily; run cohort analysis
- Hard stop fired → halt bot process; inspect `tmp/live_hard_stop.json`

### Post-session analysis
```powershell
Push-Location "d:\Alpha_Zol0-lvl_5-main\Alpha_Zol0-lvl_5-main"
& "d:\Alpha_Zol0-lvl_5-main\.venv\Scripts\python.exe" `
  scripts\live_cohort_analysis.py --db-path tmp\controlled_kpi_after_<ts>.db
Pop-Location
```

Produces: `reports/live_rollout/cohort_<ts>.json` + `.md`
Verdict: EXTEND / SCALE / ROLLBACK

---

## Post-Green Contract Validation Protocol (2026-04-20, FROZEN)

### Purpose
Reproduce the validated post-green protective exit runtime contract (`POST_GREEN_RUNTIME_CONTRACT_FIXED`) proof without changing BotCore.py.

### Validated batch10g command (canonical)
```powershell
$py = "d:\Alpha_Zol0-lvl_5-main\.venv\Scripts\python.exe"
$work = "d:\Alpha_Zol0-lvl_5-main\Alpha_Zol0-lvl_5-main"
$empty_db = "sqlite:///tmp/alpha_bootstrap_empty_cleanstart.db"
$empty_glob = "tmp/alpha_bootstrap_empty_cleanstart.db"
Push-Location $work
& $py "scripts\controlled_kpi_run.py" `
  --variant-only after --after-min 30 `
  --symbols "ETHUSDTM,BTCUSDTM,SOLUSDTM,XRPUSDTM" `
  --market-type futures --paper-auto-open --paper-auto-close-sec 300 `
  --after-env "ALPHA_BOOTSTRAP_SOURCE_DB_URL=$empty_db" `
  --after-env "ALPHA_BOOTSTRAP_SOURCE_DB_GLOB=$empty_glob" `
  --after-env "PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST=0" `
  --after-env "ALPHA_BOOTSTRAP_REQUIRE_EXTERNAL_SOURCE=0" `
  --after-env "PAPER_AUTO_OPEN_STARTUP_ENABLE=1" `
  --after-env "PAPER_AUTO_OPEN_FALLBACK_ENABLE=1" `
  --after-env "PAPER_AUTO_OPEN_REPEAT=1" `
  --after-env "SEED_TRADES_ENABLE=0"
Pop-Location
```

### Key env flags
| Flag | Value | Purpose |
|------|-------|---------|
| `PAPER_AUTO_OPEN_STARTUP_ENABLE` | 1 | Force startup auto-open to bypass entry quality gates |
| `PAPER_AUTO_OPEN_FALLBACK_ENABLE` | 1 | Allow fallback auto-open |
| `PAPER_AUTO_OPEN_REPEAT` | 1 | Re-open after every close |
| `ALPHA_BOOTSTRAP_REQUIRE_EXTERNAL_SOURCE` | 0 | Allow empty bootstrap DB |
| `SEED_TRADES_ENABLE` | 0 | Disable seed trades |
| `EXIT_CLOSE_ATTEMPT_FEE_GUARD_COOLDOWN_SEC` | **10** | **Override for future runs** — default 300s delays post_green_protective_exit |

### Pass/fail criteria
- `post_green_protective_terminal_trigger_seen=True` in `position_close` events
- All 6 required attribution fields non-null: `post_green_attempt_seq`, `post_green_branch_seq`, `post_green_trigger_mode`, `post_green_trigger_reason_detail`, `post_green_peak_to_burden_ratio`, `post_green_bnr_time_forced_exit_sec`
- All 6 fields consistent between `position_close` and `post_green_protective_exit_terminal_outcome` events
- `shutdown_classification=close_flush_done_pending_positions_zero` (runtime-clean)

### Known finding: fee-guard suppression delay
Default `EXIT_CLOSE_ATTEMPT_FEE_GUARD_COOLDOWN_SEC=300` caused 22 consecutive post_green_protective_exit attempts to be suppressed in batch10g. First BLOCK_FEE_GUARD at 04:04:13 UTC, window expired 04:14:22 UTC, close fired 04:14:42 UTC (attempt_seq=23). Always add `--after-env EXIT_CLOSE_ATTEMPT_FEE_GUARD_COOLDOWN_SEC=10` in validation corridors.

### Validated state
- 17 runs, all runtime-clean; 5 triggered post_green exits confirmed; all 6 fields validated.
- Audit artifact: `artifacts/diagnostics/post_green_natural_entry_contract_audit_20260419_expanded.json`
- BotCore.py: FROZEN at `POST_GREEN_RUNTIME_CONTRACT_FIXED`. Do not modify.

---

## Post-Close Summary Grace Protocol (2026-03-31, VALIDATED)

## Purpose
Reproduce the validated PAPER-only post-close summary grace proof without changing BotCore trading semantics.

## ETH Preset
- `scripts/run_paper_readiness_gate.py` now routes `paper_gate_run_a_eth` through the explicit `ETHUSDTM:MOMENTUM:buy` preset.
- The gate ETH preset uses the corrected after-only path:
  - `ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST=ETHUSDTM:MOMENTUM:buy`
  - `ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST=ETHUSDTM:TRENDFOLLOWING:buy`
  - `PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST=1`
  - `ALPHA_WHITELIST_ENABLE=0`
  - `ALPHA_WHITELIST_COLDSTART_ALLOW=0`
  - `ALPHA_WHITELIST_FALLBACK_ENABLE=0`
  - `ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS=0`
  - missing bootstrap source override under `tmp/alpha_bootstrap_missing_eth_momentum_buy_gate.db`
- The explicit side allowlist now constrains router admission only. It does not auto-enable startup auto-open.
- If no natural candidate appears during the window, the ETH preset may legitimately finish with `trade_count=0` and a readiness summary classification such as `NO_NATURAL_ENTRY_CANDIDATE`.
- Forced startup admission with `PAPER_AUTO_OPEN_STARTUP_ENABLE=1` is reserved for debugging only and is excluded from preferred economics corpus selection.

## ETH Operational Run
Run the corrected 16-minute ETH momentum buy path with the dedicated preset runner:

```powershell
Push-Location Alpha_Zol0-lvl_5-main
python scripts/run_eth_momentum_buy_preset.py --runs 1
Pop-Location
```

Expected outcome on the repaired path:

- A natural ETH momentum buy entry may occur and produce a normal after-run report.
- If no natural ETH momentum buy candidate survives admission, the run still completes cleanly and records zero trades instead of forcing a startup position.

If you need the raw underlying command for debugging, the preset still resolves to:

```powershell
Push-Location Alpha_Zol0-lvl_5-main
$missingPath = "D:/Alpha_Zol0-lvl_5-main/Alpha_Zol0-lvl_5-main/tmp/alpha_bootstrap_missing_repro.db"
if (Test-Path $missingPath) { Remove-Item $missingPath -Force }
python scripts/controlled_kpi_run.py --variant-only after --symbols ETHUSDTM --after-min 16 --paper-auto-open --paper-auto-close-sec 20 --equity-snapshot-sec 10 --market-type futures --timeframe 1 --quality-profile --after-env ALPHA_BOOTSTRAP_SOURCE_DB_URL=sqlite:///$missingPath --after-env ALPHA_BOOTSTRAP_SOURCE_DB_GLOB=$missingPath --after-env ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST=ETHUSDTM:MOMENTUM:buy --after-env ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST=ETHUSDTM:TRENDFOLLOWING:buy --after-env PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST=1 --after-env ALPHA_WHITELIST_ENABLE=0 --after-env ALPHA_WHITELIST_COLDSTART_ALLOW=0 --after-env ALPHA_WHITELIST_FALLBACK_ENABLE=0 --after-env ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS=0
Pop-Location
```

## ETH Stability Series
Run three identical 16-minute ETH preset sessions and write a compact summary artifact:

```powershell
Push-Location Alpha_Zol0-lvl_5-main
python scripts/run_eth_momentum_buy_preset.py --runs 3
Pop-Location
```

The runner writes stdout/stderr per run plus a machine-readable `summary.json` in a new `artifacts/diagnostics/eth_momentum_buy_series_*` directory. The raw PowerShell loop remains useful only for low-level debugging:

```powershell
Push-Location Alpha_Zol0-lvl_5-main
$missingPath = "D:/Alpha_Zol0-lvl_5-main/Alpha_Zol0-lvl_5-main/tmp/alpha_bootstrap_missing_repro.db"
$seriesDir = Join-Path "artifacts/diagnostics" ("eth_momentum_buy_series_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Path $seriesDir -Force | Out-Null
$results = @()
1..3 | ForEach-Object {
    $runIndex = $_
    $logPath = Join-Path $seriesDir ("run_{0}.log" -f $runIndex)
    if (Test-Path $missingPath) { Remove-Item $missingPath -Force }
    python scripts/controlled_kpi_run.py --variant-only after --symbols ETHUSDTM --after-min 16 --paper-auto-open --paper-auto-close-sec 20 --equity-snapshot-sec 10 --market-type futures --timeframe 1 --quality-profile --after-env ALPHA_BOOTSTRAP_SOURCE_DB_URL=sqlite:///$missingPath --after-env ALPHA_BOOTSTRAP_SOURCE_DB_GLOB=$missingPath --after-env ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST=ETHUSDTM:MOMENTUM:buy --after-env ENTRY_SYMBOL_STRATEGY_SIDE_BLOCKLIST=ETHUSDTM:TRENDFOLLOWING:buy --after-env PAPER_AUTO_OPEN_REQUIRE_EXPLICIT_SIDE_ALLOWLIST=1 --after-env ALPHA_WHITELIST_ENABLE=0 --after-env ALPHA_WHITELIST_COLDSTART_ALLOW=0 --after-env ALPHA_WHITELIST_FALLBACK_ENABLE=0 --after-env ALPHA_WHITELIST_FALLBACK_MAX_SIGNALS=0 *> $logPath
    $reportLine = Get-Content $logPath | Where-Object { $_ -like "REPORT_JSON=*" } | Select-Object -Last 1
    $reportPath = ($reportLine -split "=", 2)[1]
    $report = Get-Content $reportPath -Raw | ConvertFrom-Json
    $results += [pscustomobject]@{
        run_id = $report.run_id
        trade_count = [int]$report.after.trade_count
        net_pnl = [double]$report.after.net_pnl
        profit_factor = [string]$report.after.profit_factor
        report_json = $reportPath
    }
}
$summary = [pscustomobject]@{
    run_count = $results.Count
    profitable_runs = @($results | Where-Object { $_.net_pnl -gt 0 }).Count
    total_net_pnl = [double](($results | Measure-Object -Property net_pnl -Sum).Sum)
    avg_net_pnl = if ($results.Count) { [double](($results | Measure-Object -Property net_pnl -Average).Average) } else { 0.0 }
    runs = $results
}
$summaryPath = Join-Path $seriesDir "summary.json"
$summary | ConvertTo-Json -Depth 6 | Set-Content $summaryPath -Encoding utf8
Get-Content $summaryPath
Pop-Location
```

Do not treat a forced-startup debug series as economics evidence unless you explicitly intend to evaluate that diagnostic path.

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
