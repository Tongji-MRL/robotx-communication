@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%\OCS"
echo Starting RobotX OCS Gateway in USV-only mode (T-Wave only).
echo Set OCS/config.usv-only.json robocommand.host or pass --official-broker before use.
python ocs_gateway.py --config config.usv-only.json --vehicle-mode usv_only %*
exit /b %ERRORLEVEL%
