#!/usr/bin/env bash
set -euo pipefail
pkill -f 'twave_mission_dryrun' || true
echo 'Stopped dry-run ROS nodes only; SAFE_STOP latch was not modified.'
