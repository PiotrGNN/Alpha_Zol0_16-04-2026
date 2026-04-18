param(
  [int]$ApiPort = 8000,
  [int]$UiPort = 5173
)

$ErrorActionPreference = "Stop"

Write-Host "Starting ZoL0 API (FastAPI) on port $ApiPort..."
$apiProc = Start-Process -PassThru -NoNewWindow -FilePath "python" -ArgumentList "-m", "uvicorn", "api_status:app", "--host", "0.0.0.0", "--port", $ApiPort

Write-Host "Starting dashboard (Vite) on port $UiPort..."
$uiProc = Start-Process -PassThru -NoNewWindow -WorkingDirectory "dashboard" -FilePath "npm" -ArgumentList "run", "dev", "--", "--host", "0.0.0.0", "--port", $UiPort

Start-Sleep -Seconds 6

Write-Host "Hitting API health/market/balance endpoints..."
Invoke-WebRequest -UseBasicParsing "http://localhost:$ApiPort/api/health" | Out-Null
Invoke-WebRequest -UseBasicParsing "http://localhost:$ApiPort/api/market" | Out-Null
Invoke-WebRequest -UseBasicParsing "http://localhost:$ApiPort/api/balance" | Out-Null

Write-Host "Open http://localhost:$UiPort and confirm no console errors."
Write-Host "Press Ctrl+C to stop, or close processes manually."

Wait-Process -Id $apiProc.Id
Wait-Process -Id $uiProc.Id
