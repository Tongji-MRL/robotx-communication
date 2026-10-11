#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export TWAVE_MISSION_STATE_DIR="${TWAVE_MISSION_STATE_DIR:-$HOME/.local/state/twave-mission}"
mkdir -p "$TWAVE_MISSION_STATE_DIR" "${TWAVE_MISSION_LOG_DIR:-$HOME/robotx_logs/twave-mission}"
source "$SCRIPT_DIR/ros_env.sh"
source_ros_setup /opt/ros/humble/setup.bash
source_ros_setup "$ROOT/ros2_ws/install/setup.bash"
exec ros2 launch twave_mission_dryrun dry_run.launch.py
