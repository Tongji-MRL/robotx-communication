# UAV status test guide

This guide tests the read-only UAV status path only. It does not send a
RoboCommand request, Heartbeat, RunDeclaration, RunStart, flight command, or
geofence upload. Do not use a competition broker for the simulator.

## What is in this branch

The branch contains:

* strict JSON validation and explicit source identity mapping in
  `OCS/uav_status.py`;
* an Ubuntu ROS2-to-internal-MQTT bridge in `OCS/uav_status_mqtt_bridge.py`;
* Windows OCS and Monitor MQTT observers, with a read-only status cache;
* a Monitor page showing freshness, state, battery, position, raw JSON, and a
  distinct Course/Transit/verified-Geofence/UAV map preview;
* a 5 Hz `TEST/SIMULATED` MQTT publisher;
* unit tests for valid data, invalid JSON/identity rejection, stale state, and
  the guarantee that this data is not converted to an official Heartbeat.

`OCS/config.uav-status.example.json` is an intentionally credential-free
mapping template. Copy it outside Git or supply equivalent command-line values;
do not commit a real broker password, TLS material, `.env`, or flight data.

## Windows local simulation (no ROS2 required)

Prerequisites:

* Windows Python environment with `OCS/requirements.txt` installed;
* Mosquitto installed locally and listening only as intended; and
* this repository clone, with commands run from its root.

Install Python dependencies once:

```powershell
cd D:\RobotX\robotx-rc-lab
.\.venv\Scripts\python.exe -m pip install -r .\OCS\requirements.txt
```

Start Mosquitto in a separate PowerShell. The exact service command depends on
the local installation; the following is a common explicit foreground command:

```powershell
& 'C:\Program Files\mosquitto\mosquitto.exe' -p 1883 -v
```

Check the listener before starting OCS:

```powershell
Test-NetConnection 127.0.0.1 -Port 1883
```

Start the read-only Monitor UI:

```powershell
cd D:\RobotX\robotx-rc-lab\OCS
..\.venv\Scripts\python.exe .\monitor_ui.py `
  --broker 127.0.0.1 --port 1883 `
  --uav-source-vehicle-id UAV1
```

Open `http://127.0.0.1:8080`. In another PowerShell, publish 5 Hz simulated
data for one minute:

```powershell
cd D:\RobotX\robotx-rc-lab\OCS
..\.venv\Scripts\python.exe .\tools\uav_status_simulator.py `
  --broker 127.0.0.1 --port 1883 `
  --source-vehicle-id UAV1 --duration 60
```

The page should show `ONLINE`, T-Sky, position/heading changes, battery values,
and `TEST/SIMULATED` in raw JSON. It must show C2 signal as **not connected**,
because this path has no C2-radio source.

### Freshness and negative checks

1. Stop the simulator and wait longer than Monitor `--stale-after` (default
   three seconds): the panel must become `STALE` rather than display invented
   values.
2. Start the normal simulator again: it must return to `ONLINE`.
3. Publish one malformed message before valid samples:

   ```powershell
   ..\.venv\Scripts\python.exe .\tools\uav_status_simulator.py --broker 127.0.0.1 --port 1883 --source-vehicle-id UAV1 --malformed-once --duration 10
   ```

4. Publish an identity mismatch: it must be rejected and not replace the last
   valid state.

   ```powershell
   ..\.venv\Scripts\python.exe .\tools\uav_status_simulator.py --broker 127.0.0.1 --port 1883 --source-vehicle-id UAV1 --wrong-vehicle-id --duration 10
   ```

Inspect `http://127.0.0.1:8080/api/state` to see `uav_status`,
`uav_status_age_s`, and `uav_status_online`. This API shows receipt/cache state,
not RoboCommand broker acknowledgement.

## Ubuntu ROS2 bridge and real UAV topic

Windows does not need ROS2. Run the bridge on Ubuntu, in a ROS2 environment
that has `rclpy`, `std_msgs`, Python `paho-mqtt==2.0.0`, and this repository.

```bash
cd /path/to/robotx-rc-lab/OCS
python3 -m pip install -r requirements.txt
python3 uav_status_mqtt_bridge.py \
  --broker <WINDOWS_BROKER_IP> --port <MQTT_PORT> \
  --source-vehicle-id <ORIN_JSON_VEHICLE_ID>
```

The historical lab address `192.168.112.1:1884` is only an example; replace it
with the currently verified Windows-reachable internal broker address and port.
Do not put credentials on the command line if shell history is retained; use
the approved local deployment mechanism instead.

The bridge subscribes to exactly:

```text
topic: /tongji_mrl/tsky/uav_status
type: std_msgs/msg/String
QoS: Reliable, Volatile, Keep Last 10
rate: 5 Hz
```

The JSON must contain the configured exact `vehicle_id`, `vehicle_type: "uav"`,
`state` (`AUTO`, `MANUAL`, or `KILLED`), `flight_phase` (`GROUNDED` or
`AIRBORNE`), `position.latitude`, `position.longitude`, `altitude_hae_m`,
`spd_mps`, and `heading_deg`. Optional `battery_status` must be an object.
The bridge validates then relays the unchanged JSON to the same internal MQTT
topic at QoS 1. It is read-only and does not create an official UAV Heartbeat.

## Automated tests

From repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s OCS -p "test_*.py"
git diff --check
```

The clean GitHub commit `e60b340` was independently tested in a detached
worktree with **80 passing tests**. A local worktree containing uncommitted
QoS1 Heartbeat work has additional tests; do not attribute those results to a
clean UAV-only clone.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Monitor says MQTT disconnected | Verify `Test-NetConnection`, host/port, Mosquitto listener, firewall, and no conflicting service. |
| UI stays UNKNOWN | Ensure `--uav-source-vehicle-id` exactly matches JSON `vehicle_id`; inspect `/api/state` and Monitor stderr. |
| UI becomes STALE | Confirm 5 Hz publisher/bridge is still running and the internal topic has traffic; stale is intentional safety behavior. |
| Data rejected | Validate JSON fields, finite coordinates, heading below 360, vehicle type `uav`, and required state/phase spelling. |
| Ubuntu cannot import ROS2 | Source the correct ROS2 setup and install `rclpy`/`std_msgs` for that Ubuntu distribution. |
| Bridge cannot reach Windows | Verify routable broker address, port, firewall, MQTT credentials/TLS deployment, and DDS network separately. |

## Evidence status

Passed locally: parser/identity/freshness unit tests, UI cache tests, clean
branch OCS regression tests, and a Windows local MQTT→OCS→Monitor simulated
loop as reported by the team.

Still requiring real-device or cross-device evidence: Orin publisher schema
and rate, Ubuntu DDS subscription, Ubuntu-to-Windows MQTT connectivity and
reconnect behavior, real battery/C2 sources, authoritative Course/Transit/
verified-Geofence geometry, official RoboCommand UAV Heartbeat, and any FCU
geofence application/acknowledgement. The technical assessment Ground
validation test list should be used to record GCS/MDF/SYS/SC evidence; it is
not bundled in this repository.
