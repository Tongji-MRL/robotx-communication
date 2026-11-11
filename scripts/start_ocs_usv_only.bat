@echo off
setlocal
set "ROOT=%~dp0.."
echo Synchronizing Orin clock before starting OCS...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\sync_orin_time.ps1"
if errorlevel 1 (
  echo WARNING: Orin time synchronization failed. OCS Gateway will still start.
)
start "RobotX Orin Time Sync" /b powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\sync_orin_time_loop.ps1"
cd /d "%ROOT%\OCS"
echo Starting RobotX OCS Gateway in USV-only mode (T-Wave only).
echo Set OCS/config.usv-only.json robocommand.host or pass --official-broker before use.
python ocs_gateway.py --config config.usv-only.json --vehicle-mode usv_only %*
exit /b %ERRORLEVEL%
