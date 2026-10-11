#!/usr/bin/env bash
# ROS Humble setup scripts reference optional variables and are not nounset-safe.
# Keep errexit/pipefail enabled in callers while restoring their nounset setting.
source_ros_setup() {
  local had_nounset=0 status=0
  case $- in *u*) had_nounset=1; set +u ;; esac
  if source "$1"; then
    :
  else
    status=$?
  fi
  if [ "$had_nounset" -eq 1 ]; then set -u; fi
  return "$status"
}
