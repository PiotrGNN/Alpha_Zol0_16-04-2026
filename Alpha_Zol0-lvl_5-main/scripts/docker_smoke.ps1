# Docker-only smoke test for kucoin-bot, zol0-db, zol0-api
# - Build image (no cache)
# - LIVE gate negative test (must block start)
# - Verify secrets mount (list filenames only)
# - Start zol0-db + zol0-api and check API startup log
# - Cleanup

param()

$ErrorActionPreference = 'Stop'
$failed = $false

function Fail([string]$msg) {
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    $global:failed = $true
}

function Pass([string]$msg) {
    Write-Host "[OK] $msg" -ForegroundColor Green
}

Write-Host "=== Docker smoke test start ==="

# 1) Build without cache
Write-Host "[STEP] Build kucoin-bot (no cache)"
try {
    docker compose build --no-cache kucoin-bot
    Pass "Build completed"
} catch {
    Fail "Build failed: $_"
    Exit 1
}

# 2) LIVE gate negative: should be blocked
Write-Host "[STEP] LIVE gate negative test (expect blocked start)"
& docker run --rm -e BOT_MODE=live kucoin-bot:paper sh -lc '/usr/local/bin/entrypoint.sh true'
$rc = $LASTEXITCODE
if ($rc -eq 0) {
    Fail "LIVE gate unexpectedly allowed start (exit code 0)"
} else {
    Pass "LIVE gate blocked as expected (exit code $rc)"
}

# 3) Verify secrets mount (list filenames only) in live profile
Write-Host "[STEP] Check /run/secrets listing (no secrets values will be shown)"
try {
    $out = docker compose --profile live run --rm kucoin-bot-live sh -lc 'ls -1 /run/secrets' 2>$null
    $ls = @($out -split "`n") | ForEach-Object { $_.Trim() } | Where-Object { 
        $_ -ne '' -and $_ -ne 'total 0'
    }
    if ($ls.Count -eq 0) {
        Fail "No secrets found in /run/secrets (expected names)"
    } else {
        Write-Host "Secrets present (names only):"
        foreach ($name in $ls) { Write-Host " - $name" }
        Pass "Secrets mount OK"
    }
} catch {
    Fail "Error listing /run/secrets: $_"
}

# 4) Start zol0-db and zol0-api and check API startup
Write-Host "[STEP] Start zol0-db and zol0-api"
try {
    docker compose up -d zol0-db zol0-api
} catch {
    Fail "Failed to start zol0-db/zol0-api: $_"
    goto CLEANUP
}

# Wait for zol0-db to be healthy (timeout ~60s)
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $dbCont = (docker compose ps -q zol0-db) -join ''
        if ($dbCont -and (docker inspect -f '{{.State.Health.Status}}' $dbCont) -eq 'healthy') {
            $healthy = $true
            break
        }
    } catch {
        # ignore and retry
    }
    Write-Host "Waiting for zol0-db to become healthy... ($($i+1))"
    Start-Sleep -Seconds 2
}
if (-not $healthy) {
    Fail "zol0-db did not become healthy in time"
    goto CLEANUP
}
Pass "zol0-db healthy"

# Check zol0-api logs for startup message
try {
    $logs = docker compose logs --no-color --tail 200 zol0-api 2>$null
    if ($logs -match 'Application startup complete') {
        Pass "zol0-api startup message found"
    } else {
        Fail "zol0-api startup message not found in logs"
    }
} catch {
    Fail "Error fetching zol0-api logs: $_"
}

:CLEANUP
Write-Host "[STEP] Cleanup"
try {
    docker compose down -v 2>$null
    Pass "Cleanup done"
} catch {
    Write-Host "Warning: cleanup failed: $_" -ForegroundColor Yellow
}

Write-Host "=== Docker smoke test end ==="
if ($failed) {
    Write-Host "RESULT: FAIL" -ForegroundColor Red
    Exit 1
} else {
    Write-Host "RESULT: PASS" -ForegroundColor Green
    Exit 0
}
