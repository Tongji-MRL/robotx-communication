# UAV status monitor integration - phase 2

## Scope and audited route

The deployed route is deliberately split by device:

`UAV Orin` publishes `std_msgs/msg/String` on
`/tongji_mrl/tsky/uav_status` at 5 Hz (Reliable, Volatile, Keep Last 10).
`Ubuntu ROS2 Bridge` runs `OCS/uav_status_mqtt_bridge.py`, validates the JSON
and exact source identity, then relays the unchanged JSON to the internal MQTT
broker on the same topic at QoS 1. `Windows OCS` receives it through
`VehicleLink` into `OcsClient.latest_uav_status`; `Windows Monitor UI` has its
own MQTT observer/cache and exposes it as `/api/state.uav_status`.

The Windows path does not require ROS2. The existing optional Windows ROS2
observer remains available only for the formal FSM status topics.

The new status path is read-only. `normalize_uav_status` deliberately returns
`official_heartbeat: null`: the status contract has no authoritative
roll/pitch/current-task values. It cannot publish a RoboCommand Heartbeat,
RunDeclaration, RunStart, vehicle command, or flight-control command.

## Validation and display

The relay and both consumers reject malformed JSON, a non-object payload,
non-finite/out-of-range coordinates or dynamics, an incorrect vehicle type,
and a `vehicle_id` different from the configured `--source-vehicle-id`.
The raw accepted JSON and receive time are retained. Freshness is monotonic;
after the configured threshold the UI shows `STALE`, and before any accepted
message it shows `UNKNOWN`. Neither state invents a Heartbeat.

The existing monitor page now has a read-only UAV status section containing
identity, receive state/time, Robot State, Flight Phase, latitude, longitude,
HAE altitude, speed, heading, battery data/warning, raw JSON, and an explicit
`C2 signal: not connected` field. Its SVG map distinguishes blue Course
corners, orange UAV transit area, green *verified* geofence only, and red UAV
position. An unverified geofence is never rendered as verified and Course is
not substituted for a geofence.

## Commands

Windows Monitor:

```powershell
cd D:\RobotX\robotx-rc-lab\OCS
..\.venv\Scripts\python.exe .\monitor_ui.py --broker 192.168.112.1 --port 1884 --uav-source-vehicle-id UAV1
```

Ubuntu Bridge (from the repository's `OCS` directory in a ROS2 environment):

```bash
python3 uav_status_mqtt_bridge.py --broker 192.168.112.1 --port 1884 --source-vehicle-id UAV1
```

The bridge subscribes with `Reliable/Volatile/depth=10`; its MQTT reconnect
delay is 1--10 seconds. A publish result rejected immediately by Paho is
logged. MQTT QoS 1 is transport confirmation only and is not represented as
official RoboCommand receipt.

Windows simulator (TEST/SIMULATED only; never publish it to a competition
broker):

```powershell
cd D:\RobotX\robotx-rc-lab\OCS
..\.venv\Scripts\python.exe .\tools\uav_status_simulator.py --broker 192.168.112.1 --port 1884 --source-vehicle-id UAV1 --duration 60
```

Open `http://127.0.0.1:8080`. The panel should update at about 5 Hz in the
API snapshot, show changing position/heading/battery data, and show
`TEST/SIMULATED` in raw JSON/battery warning. Stop the simulator for more
than the `--stale-after` interval to observe `STALE`, then restart it to
observe recovery. Use `/api/state` to inspect the preserved raw payload and
the exact `uav_status_age_s`.

For negative tests, publish invalid JSON or a JSON whose `vehicle_id` is not
`UAV1` on the internal topic: the UI records an error and leaves the last valid
state unchanged. Stop/restart Mosquitto or the bridge to exercise reconnect;
the monitor reconnect loop continues and no stale status is treated as live.

## Tests actually run

* Clean commit `e60b340`, tested in a detached worktree with the repository's
  Python environment: `..\.venv\Scripts\python.exe -m unittest discover -s
  OCS -p "test_*.py"` - **PASS: 80 tests.** This includes existing OCS
  Client/Gateway/Course/RunStart regression coverage plus UAV JSON validation,
  explicit mapping rejection, stale-state behavior, and proof that the new
  internal status callback does not create an official heartbeat. The separate
  uncommitted QoS1 Heartbeat work adds tests and must not be counted here.
* `git diff --check` - **PASS.**
* Local UI availability check on `127.0.0.1:18080` with an intentionally
  unavailable MQTT endpoint (`127.0.0.1:19999`) - **PASS:** `/api/state`
  returned HTTP 200 with `broker_connected=false` and no fabricated UAV state.

No live Ubuntu ROS2, Orin publisher, Mosquitto at `192.168.112.1:1884`, or
RoboCommand server was contacted for this phase. Cross-device rate, broker
receipt, reconnect recovery, malformed-message injection, and the existing
30-second RC-Test heartbeat flow therefore remain **unverified live tests**,
not PASS results.

## Remaining integration inputs

The UAV/Ubuntu owner must confirm the exact JSON schema/units, literal source
`vehicle_id`, topic namespace/domain, DDS network configuration, broker
credentials/TLS requirements, and whether battery warning/remaining-flight
time/C2 radio quality have authoritative sources. C2 must be added as its
own sourced field; it must not be inferred from ROS2 or MQTT connectivity.
They must also provide the authoritative Course/Transit/verified-geofence
state publisher or API used by the Monitor snapshot before the map can display
live mission geometry. No actual geofence upload or FCU acknowledgement is
implemented in this phase.
