@echo off
setlocal
cd /d "%~dp0..\OCS"
echo Starting RobotX OCS Monitor in READ-ONLY mode. No executors are started.
python monitor_ui.py --web-host 127.0.0.1 %*
