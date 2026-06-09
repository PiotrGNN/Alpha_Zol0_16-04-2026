@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\zol0.ps1" down local
if errorlevel 1 (
  echo ZoL0 stop failed. Review the FAILED message above.
  pause
  exit /b 1
)
exit /b 0
