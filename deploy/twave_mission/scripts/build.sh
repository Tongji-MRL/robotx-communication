#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ros_env.sh"
source_ros_setup /opt/ros/humble/setup.bash
cd "$ROOT/ros2_ws"
colcon build --base-paths src ../usv_main_fsm ../OCS --packages-select robotx_ocs_protocol usv_main_fsm twave_mission_dryrun
