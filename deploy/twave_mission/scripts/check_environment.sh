#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ros_env.sh"
source_ros_setup /opt/ros/humble/setup.bash
test "$(. /etc/os-release; echo "$VERSION_ID")" = "22.04"
command -v ros2 >/dev/null
test -n "${ROS_DISTRO:-}" && test "$ROS_DISTRO" = humble
test -n "${TWAVE_MISSION_STATE_DIR:-}" || echo "TWAVE_MISSION_STATE_DIR defaults to ~/.local/state/twave-mission"
