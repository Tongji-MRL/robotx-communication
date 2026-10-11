#!/usr/bin/env bash
set -euo pipefail
LOG_DIR="${TWAVE_MISSION_LOG_DIR:-$HOME/robotx_logs/twave-mission}"
if [ "$#" -eq 1 ]; then grep -F '"run_id":'$1 "$LOG_DIR"/coordinator/events.jsonl* || true; else tail -n 200 "$LOG_DIR"/coordinator/events.jsonl; fi
