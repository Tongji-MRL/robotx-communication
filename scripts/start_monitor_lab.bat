@echo off
setlocal
cd /d "%~dp0..\OCS"
echo WARNING: isolated laboratory diagnostics only. This does not start executors.
python monitor_ui.py --web-host 127.0.0.1 --enable-lab-commands %*
