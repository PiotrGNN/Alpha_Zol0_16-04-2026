@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\zol0.ps1" setup
if errorlevel 1 goto :fail
powershell -NoProfile -ExecutionPolicy Bypass -File ".\zol0.ps1" doctor local
if errorlevel 1 goto :fail
powershell -NoProfile -ExecutionPolicy Bypass -File ".\zol0.ps1" up local
if errorlevel 1 goto :fail
powershell -NoProfile -ExecutionPolicy Bypass -File ".\zol0.ps1" open local
exit /b 0
:fail
echo ZoL0 start failed. Review the PASS/BLOCKED/FAILED message above.
pause
exit /b 1
