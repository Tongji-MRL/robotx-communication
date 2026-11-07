@echo off
setlocal
set "ROOT=%~dp0.."
rem Use the activated ROS 2 environment, not a repo venv that may lack rclpy.
if not defined ROBOTX_GROUND_PYTHON set "ROBOTX_GROUND_PYTHON=python"
"%ROBOTX_GROUND_PYTHON%" "%ROOT%\OCS\uav_ground_validation.py" %*
exit /b %ERRORLEVEL%
