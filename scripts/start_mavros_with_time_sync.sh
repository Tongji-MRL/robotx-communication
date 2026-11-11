#!/usr/bin/env bash
# Start MAVROS only after synchronization to a reachable LAN NTP server.
# This script intentionally configures no public/fallback NTP source.
set -euo pipefail

WORKSPACE="${ROBOTX_WORKSPACE:-$HOME/robotx_ws}"
TIME_SERVER="${ROBOTX_TIME_SERVER:-}"
FCU_URL="/dev/serial/by-id/usb-Holybro_Pixhawk6C_38002E001851333531333639-if00:115200"
WAIT_SECONDS=45
CHECK_ONLY=false

usage() {
  cat <<'EOF'
Usage: start_mavros_with_time_sync.sh --ntp-server <LAN_NTP_IP> [options]

Options:
  --ntp-server <IP/host>  Required reachable LAN NTP server; no public NTP is used.
  --fcu-url <URL>         MAVROS FCU URL.
  --wait-seconds <N>      Maximum time to wait for systemd-timesyncd (default: 45).
  --check-only            Synchronize and verify time, but do not launch MAVROS.
  --help                  Show this help.
EOF
}

while (($#)); do
  case "$1" in
    --ntp-server) TIME_SERVER="${2:?missing value for --ntp-server}"; shift 2 ;;
    --fcu-url) FCU_URL="${2:?missing value for --fcu-url}"; shift 2 ;;
    --wait-seconds) WAIT_SECONDS="${2:?missing value for --wait-seconds}"; shift 2 ;;
    --check-only) CHECK_ONLY=true; shift ;;
    --help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$TIME_SERVER" ]]; then
  echo "ERROR: --ntp-server must name a reachable LAN time source." >&2
  exit 2
fi
if [[ ! "$WAIT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: --wait-seconds must be a positive integer." >&2
  exit 2
fi
if [[ ! -e "${FCU_URL%%:*}" ]]; then
  echo "ERROR: FCU device is not present: ${FCU_URL%%:*}" >&2
  exit 2
fi
if [[ ! -f /opt/ros/humble/setup.bash || ! -f "$WORKSPACE/install/setup.bash" ]]; then
  echo "ERROR: ROS or workspace setup file is missing." >&2
  exit 2
fi

# Configure the explicitly supplied LAN source only. This operation requires
# sudo because systemd-timesyncd configuration is system-wide.
sudo install -d -m 755 /etc/systemd/timesyncd.conf.d
printf '[Time]\nNTP=%s\nFallbackNTP=\n' "$TIME_SERVER" |
  sudo tee /etc/systemd/timesyncd.conf.d/robotx-lan-ntp.conf >/dev/null
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd

deadline=$((SECONDS + WAIT_SECONDS))
while ((SECONDS < deadline)); do
  if [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)" == "yes" ]]; then
    echo "[TIME_SYNC_OK] server=$TIME_SERVER utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    break
  fi
  sleep 1
done

if [[ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)" != "yes" ]]; then
  echo "ERROR: LAN NTP synchronization was not confirmed; MAVROS was not started." >&2
  timedatectl status >&2 || true
  timedatectl timesync-status >&2 || true
  exit 1
fi

if [[ "$CHECK_ONLY" == true ]]; then
  exit 0
fi

source /opt/ros/humble/setup.bash
source "$WORKSPACE/install/setup.bash"
exec ros2 launch mavros apm.launch "fcu_url:=$FCU_URL"
