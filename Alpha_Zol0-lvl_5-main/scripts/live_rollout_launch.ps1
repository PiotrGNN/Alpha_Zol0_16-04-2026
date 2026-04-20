#!/usr/bin/env pwsh
<#
.SYNOPSIS
    ZoL0 Guarded Live Rollout — Phase 1 launcher (ETHUSDTM / KuCoin Futures).

.DESCRIPTION
    Performs pre-flight checks, displays configuration, requires explicit
    human confirmation, then launches the live bot plus the hard-stop monitor
    in separate PowerShell windows.

    READ BEFORE RUNNING:
    - Verify KUCOIN_API_KEY / KUCOIN_API_SECRET / KUCOIN_API_PASSPHRASE are set
      in your shell environment (or stored in secrets/).
    - This script DOES NOT store or print secrets.
    - Hard stop conditions: see config/live_rollout_ethusdtm.env

    ARTIFACTS WRITTEN:
    - tmp/controlled_kpi_after_<timestamp>.db   (live run log DB)
    - tmp/live_rollout_<timestamp>_stdout.txt   (bot stdout)
    - tmp/live_rollout_monitor.log              (monitor log)
    - tmp/live_hard_stop.json                   (if hard stop fires)

    POST-RUN ANALYSIS:
    - python scripts/live_cohort_analysis.py    (run after session ends)

.PARAMETER DurationMin
    Maximum run duration in minutes. Default: 1440 (24 hours).
    The run can be stopped earlier by:
      - CTRL+C in the bot terminal window
      - Hard stop signal from the monitor (tmp/live_hard_stop.json)
      - Milestone: 30 closed trades reached

.PARAMETER PollSec
    Monitor poll interval in seconds. Default: 30.

.EXAMPLE
    .\scripts\live_rollout_launch.ps1
    .\scripts\live_rollout_launch.ps1 -DurationMin 480 -PollSec 20
#>

[CmdletBinding()]
param(
    [int]$DurationMin = 1440,
    [int]$PollSec = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Py     = "d:\Alpha_Zol0-lvl_5-main\.venv\Scripts\python.exe"
$Work   = "d:\Alpha_Zol0-lvl_5-main\Alpha_Zol0-lvl_5-main"
$EnvCfg = Join-Path $Work "config\live_rollout_ethusdtm.env"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Write-Header($msg) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}

function Write-Check($label, $ok, $detail = "") {
    $icon  = if ($ok) { "[OK]" }  else { "[FAIL]" }
    $color = if ($ok) { "Green" } else { "Red" }
    $line  = "  $icon  $label"
    if ($detail) { $line += "  ($detail)" }
    Write-Host $line -ForegroundColor $color
}

function Assert-Check($label, $ok, $detail = "") {
    Write-Check $label $ok $detail
    if (-not $ok) {
        Write-Host ""
        Write-Host "  Pre-flight check FAILED. Aborting." -ForegroundColor Red
        exit 1
    }
}

# ---------------------------------------------------------------------------
# STEP 1 — Pre-flight checks
# ---------------------------------------------------------------------------
Write-Header "ZoL0 LIVE ROLLOUT PRE-FLIGHT CHECKS"

# Python runtime
Assert-Check "Python venv exists" (Test-Path $Py) $Py

# Working directory
Assert-Check "Working dir exists" (Test-Path $Work) $Work

# Env config
Assert-Check "live_rollout_ethusdtm.env exists" (Test-Path $EnvCfg) $EnvCfg

# KuCoin credentials (must be in environment — not read, just verified non-empty)
$apiKey     = [System.Environment]::GetEnvironmentVariable("KUCOIN_API_KEY")
$apiSecret  = [System.Environment]::GetEnvironmentVariable("KUCOIN_API_SECRET")
$apiPass    = [System.Environment]::GetEnvironmentVariable("KUCOIN_API_PASSPHRASE")

Assert-Check "KUCOIN_API_KEY set"         (-not [string]::IsNullOrWhiteSpace($apiKey))
Assert-Check "KUCOIN_API_SECRET set"      (-not [string]::IsNullOrWhiteSpace($apiSecret))
Assert-Check "KUCOIN_API_PASSPHRASE set"  (-not [string]::IsNullOrWhiteSpace($apiPass))

# No stale hard stop file from a previous run
$HardStopFile = Join-Path $Work "tmp\live_hard_stop.json"
if (Test-Path $HardStopFile) {
    Write-Host ""
    Write-Host "  [WARN] Stale hard stop file found: $HardStopFile" -ForegroundColor Yellow
    Write-Host "         If this is from a previous run and you want to continue," -ForegroundColor Yellow
    Write-Host "         delete it manually before launching." -ForegroundColor Yellow
    Write-Host ""
    $del = Read-Host "  Delete stale hard stop file and continue? (yes/no)"
    if ($del.Trim().ToLower() -ne "yes") {
        Write-Host "  Aborting." -ForegroundColor Red
        exit 1
    }
    Remove-Item $HardStopFile -Force
    Write-Check "Stale hard stop file removed" $true
}

# ---------------------------------------------------------------------------
# STEP 2 — Display rollout configuration
# ---------------------------------------------------------------------------
Write-Header "ROLLOUT CONFIGURATION"
Write-Host ""
Write-Host "  Symbol:        ETHUSDTM (ETH/USDT KuCoin Futures — LIVE)"
Write-Host "  Mode:          LIVE (LIVE=1, LIVE_ARMED=1)"
Write-Host "  Duration:      $DurationMin minutes"
Write-Host "  Fee guard:     EXIT_CLOSE_ATTEMPT_FEE_GUARD_COOLDOWN_SEC=10"
Write-Host "  Entry filter:  ENTRY_SYMBOL_STRATEGY_SIDE_ALLOWLIST=ETHUSDTM:MOMENTUM:buy"
Write-Host ""
Write-Host "  Hard stop thresholds:" -ForegroundColor Yellow
Write-Host "    exit_delay      > 120s"
Write-Host "    consec_losses  >= 3"
Write-Host "    drawdown        > 2%"
Write-Host ""
Write-Host "  Gate reference: paper_readiness_gate_20260420_072346 (PASS/PROMOTE_CANDIDATE)"
Write-Host "  Contract ref:   POST_GREEN_RUNTIME_CONTRACT_FIXED (17 runs, 5 triggered exits)"
Write-Host ""
Write-Host "  Artifacts will be written to:"
Write-Host "    tmp/controlled_kpi_after_<ts>.db"
Write-Host "    tmp/live_rollout_<ts>_stdout.txt"
Write-Host "    tmp/live_rollout_monitor.log"
Write-Host ""

# ---------------------------------------------------------------------------
# STEP 3 — Final human confirmation
# ---------------------------------------------------------------------------
Write-Header "FINAL CONFIRMATION REQUIRED"
Write-Host ""
Write-Host "  This will place REAL ORDERS on KuCoin Futures." -ForegroundColor Red -BackgroundColor Black
Write-Host "  Ensure you are monitoring this terminal." -ForegroundColor Red
Write-Host ""
$confirm = Read-Host "  Type exactly: CONFIRM_LIVE_LAUNCH"
if ($confirm.Trim() -ne "CONFIRM_LIVE_LAUNCH") {
    Write-Host ""
    Write-Host "  Confirmation not received. Aborting." -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "  Confirmation received. Starting live rollout..." -ForegroundColor Green
Write-Host ""

# ---------------------------------------------------------------------------
# STEP 4 — Build run ID and paths
# ---------------------------------------------------------------------------
$Ts     = Get-Date -Format "yyyyMMdd_HHmmss"
$DbPath = Join-Path $Work "tmp\controlled_kpi_after_$Ts.db"
$Log    = Join-Path $Work "tmp\live_rollout_${Ts}_stdout.txt"

# ---------------------------------------------------------------------------
# STEP 5 — Launch monitor in a separate window (starts first, waits for DB)
# ---------------------------------------------------------------------------
Write-Header "LAUNCHING MONITOR"
$MonitorCmd = (
    "Push-Location '$Work'; " +
    "& '$Py' scripts\live_rollout_monitor.py " +
    "--db-path '$DbPath' " +
    "--poll-sec $PollSec; " +
    "Read-Host 'Monitor ended — press Enter to close'"
)
Start-Process powershell.exe -ArgumentList (
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-Command", $MonitorCmd
) -WindowStyle Normal

Write-Host "  Monitor launched in separate window." -ForegroundColor Green
Write-Host "  DB path: $DbPath"
Write-Host ""

# ---------------------------------------------------------------------------
# STEP 6 — Source env config and build --after-env args
# ---------------------------------------------------------------------------
$LiveEnv = @{}
Get-Content $EnvCfg | Where-Object {
    $_ -notmatch '^\s*#' -and $_.Trim() -ne ''
} | ForEach-Object {
    $kv = $_ -split '=', 2
    if ($kv.Count -eq 2) {
        $LiveEnv[$kv[0].Trim()] = $kv[1].Trim()
    }
}

$AfterEnvArgs = @()
foreach ($k in $LiveEnv.Keys) {
    $AfterEnvArgs += "--after-env"
    $AfterEnvArgs += "$k=$($LiveEnv[$k])"
}

# ---------------------------------------------------------------------------
# STEP 7 — Launch the live bot
# ---------------------------------------------------------------------------
Write-Header "LAUNCHING LIVE BOT"
Write-Host "  Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "  Duration: $DurationMin min"
Write-Host "  Log: $Log"
Write-Host ""

Push-Location $Work
try {
    $BotArgs = @(
        "scripts\controlled_kpi_run.py",
        "--variant-only", "after",
        "--symbols", "ETHUSDTM",
        "--after-min", $DurationMin,
        "--market-type", "futures"
    ) + $AfterEnvArgs

    & $Py @BotArgs 2>&1 | Tee-Object -FilePath $Log

    $ExitCode = $LASTEXITCODE
    Write-Host ""
    Write-Host "  Bot exited at $(Get-Date -Format 'HH:mm:ss') | exit=$ExitCode" -ForegroundColor $(
        if ($ExitCode -eq 0) { "Green" } else { "Yellow" }
    )
} finally {
    Pop-Location
}

# ---------------------------------------------------------------------------
# STEP 8 — Post-run analysis prompt
# ---------------------------------------------------------------------------
Write-Host ""
Write-Header "LIVE RUN COMPLETE"
Write-Host ""
Write-Host "  DB:  $DbPath"
Write-Host "  Log: $Log"
Write-Host ""

if (Test-Path $HardStopFile) {
    Write-Host "  [WARNING] Hard stop was triggered. Review:" -ForegroundColor Red
    Write-Host "  $HardStopFile" -ForegroundColor Red
    Write-Host ""
}

Write-Host "  To produce the post-session cohort analysis report, run:" -ForegroundColor Cyan
Write-Host ""
Write-Host "    Push-Location '$Work'" -ForegroundColor White
Write-Host "    & '$Py' scripts\live_cohort_analysis.py --db-path '$DbPath'" -ForegroundColor White
Write-Host "    Pop-Location" -ForegroundColor White
Write-Host ""
