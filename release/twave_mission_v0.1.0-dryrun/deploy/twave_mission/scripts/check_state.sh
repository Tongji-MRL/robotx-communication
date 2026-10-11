#!/usr/bin/env bash
set -euo pipefail
STATE_DIR="${TWAVE_MISSION_STATE_DIR:-$HOME/.local/state/twave-mission}"
find "$STATE_DIR" -maxdepth 1 -type f -name '*.json' -print -exec cat {} \;
