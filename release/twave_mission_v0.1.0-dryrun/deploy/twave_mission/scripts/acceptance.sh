#!/usr/bin/env bash
set -euo pipefail
"$(dirname "$0")/check_environment.sh"
"$(dirname "$0")/build.sh"
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ros_env.sh"
source_ros_setup /opt/ros/humble/setup.bash
source_ros_setup "$ROOT/ros2_ws/install/setup.bash"
colcon test --base-paths "$ROOT/ros2_ws/src" "$ROOT/usv_main_fsm" "$ROOT/OCS" --packages-select usv_main_fsm twave_mission_dryrun
RESULT="$(colcon test-result --verbose 2>&1)"
printf '%s\n' "$RESULT"
if grep -Eq 'Summary: 0 tests|0 tests' <<<"$RESULT"; then
  echo 'ERROR: colcon discovered zero tests.' >&2
  exit 1
fi
if grep -Eq '[1-9][0-9]* (failures|errors)' <<<"$RESULT"; then
  echo 'ERROR: colcon reported test failures or errors.' >&2
  exit 1
fi
