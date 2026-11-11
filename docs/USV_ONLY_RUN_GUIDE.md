# USV-only run guide

## Required values

Before a field run, set these real values in a local copy of
`OCS/config.usv-only.json` (do not commit credentials or field IPs):

- `robocommand.host` and `robocommand.port`: RBC/Team Village values issued for the event.
- `internal_broker.host` and `internal_broker.port`: Windows internal MQTT broker, normally `1883`.
- `vehicles.usv.orin_ip`: T-Wave Orin address, if retained for operations records.
- `ROS_DOMAIN_ID`: the assigned T-Wave/OCS domain. `ROS_LOCALHOST_ONLY` must allow the required network peers.

The profile is intentionally invalid until the RBC host is set, preventing an
accidental field connection from a template.

## Start order

1. Start the Windows internal MQTT broker. Confirm it listens on the configured
   host/port and that T-Wave can reach it.
2. On T-Wave Orin, source ROS2 and the T-Wave workspace, set the agreed domain,
   then start the existing Mission Planner FSM and its real status/heartbeat
   publishers. Do not start T-Sky adapters for this profile.
3. On Windows, use the ROS2-enabled Python environment if the gateway needs
   ROS2 discovery. Set the same ROS domain, then start OCS.
4. Optionally start the monitor in read-only USV-only mode.

## Windows commands

```powershell
cd D:\RobotX\robotx-rc-lab
$env:ROS_DOMAIN_ID = '<assigned-domain>'
$env:ROS_LOCALHOST_ONLY = '0'
.\scripts\start_ocs_usv_only.bat --publish-declaration

# Optional, read-only UI; no official command publishing.
python .\OCS\monitor_ui.py --broker <windows-broker-ip> --port 1883
```

The launcher expands to `ocs_gateway.py --config config.usv-only.json
--vehicle-mode usv_only`. Running `ocs_gateway.py` with no mode/config options
uses the same USV-only defaults. It only publishes a declaration after receiving a
valid RBC Course. Never use local/synthetic heartbeat options on a field RBC
broker.

## T-Wave Orin commands

The exact production FSM launch remains platform-owned. For the checked-in
dry-run package only (not an actuator command):

```bash
cd /path/to/robotx-rc-lab
export ROS_DOMAIN_ID=<assigned-domain>
export ROS_LOCALHOST_ONLY=0
./deploy/twave_mission/scripts/check_environment.sh
./deploy/twave_mission/scripts/build.sh
./deploy/twave_mission/scripts/start_dry_run.sh
```

For a real vessel, replace only the final dry-run launch with the approved
T-Wave Mission Planner service. It must retain the existing ROS2 mission
topics: Course, RunStart, Task4, mission status, task report, and fault.

## Quick checks and troubleshooting

- Gateway says no internal MQTT connection: verify the Windows broker address,
  port, credentials, and T-Wave route. USV-only subscribes only to
  `/tongji_mrl/twave/heartbeat`.
- Course forwarding: verify `ROS_DOMAIN_ID`, DDS reachability, and that the
  relevant USV task nodes subscribe to `/tongji_mrl/mission/course_config`.
- RunStart forwarding: in USV-only, after the normal RBC declaration/RunStart
  validation OCS sends exactly `{"command":"begin"}` to
  `/tongji_mrl/mission/run_start`; it does not wait for the retired main-FSM
  Course-ready ACK. If it is not forwarded, verify that this topic has a live
  subscriber and that the official declaration sequence and run ID are valid.
- No heartbeat: inspect real T-Wave JSON for the existing required WGS84,
  health, task, and USV type fields. Source timestamps are forwarded as
  metadata and do not affect acceptance or expiry; duplicate, wrong-run, or
  malformed non-timestamp data is still rejected.
- Monitor shows T-Wave offline: it is read-only; inspect broker connectivity
  and heartbeat freshness. Missing UAV data is not an error in `--usv-only`.
- Future dual-vehicle operation: use an approved dual config and explicitly add
  `--vehicle-mode dual_vehicle`. The gateway rejects incomplete UAV identity/
  registration configuration before it connects; it does not auto-enable from
  a discovered UAV topic.
