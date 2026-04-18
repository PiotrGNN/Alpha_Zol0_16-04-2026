param(
  [int]$ApiPort = 10000
)

$ErrorActionPreference = "Stop"

function Import-DotEnv([string]$Path) {
  if (-not (Test-Path $Path)) { return }
  Get-Content $Path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line) { return }
    if ($line.StartsWith("#")) { return }
    $idx = $line.IndexOf("=")
    if ($idx -le 0) { return }
    $key = $line.Substring(0, $idx).Trim()
    $val = $line.Substring($idx + 1).Trim()
    if (-not $key) { return }
    # Strip optional surrounding quotes
    if ($val.Length -ge 2 -and (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'")))) {
      $val = $val.Substring(1, $val.Length - 2)
    }
    # Set env var for child processes. Never print values.
    [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
  }
}

function Stop-ApiByPort([int]$Port) {
  try {
    $pids = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
      Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($pid in ($pids | Sort-Object -Unique)) {
      try { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue } catch {}
    }
  } catch {}

  # Fallback: parse netstat output (works even when Get-NetTCPConnection is limited)
  try {
    $lines = netstat -ano | Select-String -Pattern (":$Port") | ForEach-Object { $_.Line } | Where-Object { $_ -match "LISTENING" }
    foreach ($line in $lines) {
      try {
        $parts = ($line -split "\\s+") | Where-Object { $_ -ne "" }
        $pid = [int]$parts[-1]
        if ($pid -gt 0) {
          try { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue } catch {}
        }
      } catch {}
    }
  } catch {}
}

function Stop-BotByPidFile([string]$PidFile) {
  if (-not (Test-Path $PidFile)) { return }
  try {
    $pid = [int](Get-Content $PidFile | Select-Object -First 1)
    if ($pid -gt 0) { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue }
  } catch {}
}

Set-Location (Split-Path -Parent $PSScriptRoot)

# Load .env if present (dev runtime convenience)
Import-DotEnv ".env"
# Also support repo-root .env one level above (common in this workspace layout)
Import-DotEnv "..\\.env"

# Enforce PAPER by default (LIVE arming still required in codepath)
[System.Environment]::SetEnvironmentVariable("LIVE", "0", "Process")
[System.Environment]::SetEnvironmentVariable("MARKET_TYPE", "futures", "Process")
[System.Environment]::SetEnvironmentVariable("PYTHONUNBUFFERED", "1", "Process")
# Optional: connect to Docker Postgres for parity
if ($env:USE_DOCKER_DB -eq "1") {
  [System.Environment]::SetEnvironmentVariable("DATABASE_URL", "postgresql://zol0:zol0@localhost:5432/zol0", "Process")
}

New-Item -ItemType Directory -Force -Path "logs" | Out-Null

Stop-ApiByPort $ApiPort
Stop-BotByPidFile "bot.pid"

Write-Output "Starting API on port $ApiPort..."
$apiOut = Join-Path "logs" "api_runtime.out"
$apiErr = Join-Path "logs" "api_runtime.err"
$apiProc = Start-Process -WindowStyle Hidden -PassThru -WorkingDirectory (Get-Location).Path -FilePath "python" -ArgumentList "-m","uvicorn","api_status:app","--host","0.0.0.0","--port",$ApiPort -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr
Set-Content -Path "api.pid" -Value $apiProc.Id -Encoding ascii

Write-Output "Starting bot (PAPER)..."
$botOut = Join-Path "logs" "bot_runtime.out"
$botErr = Join-Path "logs" "bot_runtime.err"
$botProc = Start-Process -WindowStyle Hidden -PassThru -WorkingDirectory (Get-Location).Path -FilePath "python" -ArgumentList "main.py","--mode","simulate","--no-api" -RedirectStandardOutput $botOut -RedirectStandardError $botErr
Set-Content -Path "bot.pid" -Value $botProc.Id -Encoding ascii

Start-Sleep -Seconds 2
try {
  $resp = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://localhost:$ApiPort/api/health"
  Write-Output "api/health: $($resp.StatusCode) $($resp.Content)"
} catch {
  Write-Output "api/health check failed: $($_.Exception.Message)"
}
