@echo off
setlocal EnableExtensions
set "ROOT=%~dp0.."
set "BROKER=127.0.0.1"
set "PORT=1883"
set "API=http://127.0.0.1:8080/api/state"

echo [1/7] Checking Python and paho-mqtt...
python --version || goto :help
python -c "import paho.mqtt.client" || goto :help

echo [2/7] Checking isolated local MQTT broker at %BROKER%:%PORT%...
python -c "import socket; s=socket.create_connection(('%BROKER%',%PORT%),2); s.close()" || goto :broker

echo [3/7] Checking Monitor UI API...
powershell -NoProfile -Command "Invoke-RestMethod '%API%' | Out-Null" || goto :ui

echo [4/7] Refusing non-local monitor broker configuration...
powershell -NoProfile -Command "$s=Invoke-RestMethod '%API%'; if ($s.broker.host -notin @('127.0.0.1','localhost','::1')) { throw ('Monitor broker is not local: '+$s.broker.host) }" || goto :unsafe

echo [5/7] Publishing one simulated TASK1 status; no command topic is used...
pushd "%ROOT%"
python OCS\tools\local_fsm_simulator.py --broker %BROKER% --port %PORT% --scenario TASK1_ACTIVE --count 1 || (popd & goto :failed)
popd

echo [6/7] Validating /api/state contract and Course/UAV distinction...
powershell -NoProfile -Command "$s=Invoke-RestMethod '%API%'; $m=$s.mission; if (!$s.mission_status.received -or $m.schema_version -ne 'twave-mission-status-v2' -or $m.run_id -ne 202601 -or $m.fsm_state -ne 'TASK1_EXECUTE' -or !$m.course -or !$m.safety -or !$m.vehicles -or !$m.legacy) { throw 'status-v2 contract not received' }; if ($m.course.uav_applied -eq $true) { throw 'simulated UAV must not be marked applied' }; if (!$s.vehicles.'T-Wave'.heartbeat -or !$s.vehicles.'T-Sky'.heartbeat) { throw 'simulated heartbeats not received' }; Write-Host 'State verification passed'" || goto :failed

echo [7/7] Verifying default read-only command rejection and FSM timeout (default stale-after=3)...
powershell -NoProfile -Command "try { Invoke-WebRequest '%API:/state=/command%' -Method Post -ContentType 'application/json' -Body (ConvertTo-Json @{command='ping'}) -ErrorAction Stop; throw 'POST unexpectedly accepted' } catch [System.Net.WebException] { if ($_.Exception.Response.StatusCode.value__ -ne 403) { throw } }" || goto :failed
timeout /t 4 /nobreak >nul
powershell -NoProfile -Command "$s=Invoke-RestMethod '%API%'; if ($s.mission_status.online) { throw 'FSM status did not time out; start UI with default --stale-after 3' }; Write-Host 'Timeout verification passed'" || goto :failed

echo PASS: local MQTT monitor integration completed. The one-shot simulator has already exited.
exit /b 0

:broker
echo MQTT broker is not reachable. Start an isolated local broker on 127.0.0.1:1883, then retry.
exit /b 2
:ui
echo Monitor UI is not reachable. In another terminal run: scripts\start_monitor_readonly.bat --broker 127.0.0.1
exit /b 3
:unsafe
echo Refused: the running UI is configured for a non-local broker.
exit /b 4
:help
echo Install Python and paho-mqtt first: python -m pip install -r OCS\requirements.txt
exit /b 5
:failed
echo FAIL: local monitor integration check did not complete. No real vehicle was contacted.
exit /b 1
