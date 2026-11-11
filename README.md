# RobotX 2026 Communication — TONG USV-only

This repository contains TONG's RobotX communication integration. The formal
default is **USV-only**: `T-Wave` is the sole declared vehicle and mission
coordinator. OCS is a gateway; task execution remains in the T-Wave Orin task
nodes.

## Communication topology

```text
RoboCommand / RBC
        | MQTT + official Protobuf
Windows OCS Gateway
        | internal MQTT JSON                    | ROS 2 String JSON
T-Wave Orin heartbeat publisher          T-Wave task nodes
 /tongji_mrl/twave/heartbeat              course / run_start / task4
```

- OCS ↔ RBC: official MQTT and Protobuf only.
- T-Wave Orin → OCS: internal MQTT raw vehicle heartbeat only.
- OCS ↔ T-Wave task nodes: ROS 2 mission interface.
- Default operation does not subscribe to, declare, or report `T-Sky`.
- Legacy UAV interfaces remain available only through an explicit non-default
  `dual_vehicle` configuration; they are not started in USV-only mode.

## Prerequisites

Before any field connection, provide the actual values locally; do not commit
credentials or event-network addresses.

1. Windows internal MQTT broker is listening on port `1883` and reachable from
   the Orin.
2. T-Wave Orin is publishing real heartbeat JSON to
   `/tongji_mrl/twave/heartbeat` on that broker.
3. Windows and Orin use the required `ROS_DOMAIN_ID`; set
   `ROS_LOCALHOST_ONLY=0` when DDS peers are on the network.
4. RBC connection address and port are known.
5. RBC sends a valid Course before the gateway's declaration window expires.

`OCS/config.usv-only.json` is the production profile template. Its official
broker host is deliberately a placeholder.

## Start the USV-only gateway

On Windows PowerShell:

```powershell
cd D:\RobotX\robotx-rc-lab
$env:ROS_DOMAIN_ID = '<assigned-domain>'
$env:ROS_LOCALHOST_ONLY = '0'

python -u .\OCS\ocs_gateway.py `
  --config .\OCS\config.usv-only.json `
  --vehicle-mode usv_only `
  --official-broker <RBC_IP> `
  --official-port 1883 `
  --internal-broker 127.0.0.1 `
  --internal-port 1883 `
  --publish-declaration
```

Equivalent launcher:

```powershell
.\scripts\start_ocs_usv_only.bat `
  --official-broker <RBC_IP> --official-port 1883 --publish-declaration
```

The gateway connects to both brokers, waits for an official Course, then sends
a RunDeclaration for `T-Wave` only. A live process is required; `--duration 0`
is the default and means continuous operation.

## Orin interfaces

### Heartbeat

The Orin heartbeat publisher sends JSON to:

```text
/tongji_mrl/twave/heartbeat
```

Required non-timestamp content includes the T-Wave identity, `vehicle_type`
`"usv"`, explicit state and task, WGS84 position, speed, heading, roll, pitch,
and health data. OCS preserves the source timestamp as metadata but does not
use it to reject, expire, order, or bind a heartbeat. A received valid
heartbeat remains eligible until a later heartbeat replaces it or the active
declaration/run context is reset.

The OCS log sequence for a healthy path is:

```text
[RxVehicle] heartbeat vehicle=T-Wave ...
[DECLARATION_PUBLISHED] ... vehicles=['T-Wave']
[HEARTBEAT_PUBLISHED] ...
[HEARTBEAT_PUBACK] ...
```

### Course, RunStart, and task events

| Direction | Topic | Payload |
| --- | --- | --- |
| OCS → task nodes | `/tongji_mrl/mission/course_config` | Existing Course JSON contract |
| OCS → task nodes | `/tongji_mrl/mission/run_start` | `{"command":"begin"}` |
| OCS → task nodes | `/tongji_mrl/mission/task4_cmd` | Existing Task4 JSON contract |
| task nodes → OCS | `/tongji_mrl/mission/status` | Mission status |
| task nodes → OCS | `/tongji_mrl/mission/task_report` | Task reports |
| task nodes → OCS | `/tongji_mrl/mission/fault` | Fault reports |

After OCS accepts an official RunStart under its existing RBC validation rules,
USV-only mode publishes exactly `{"command":"begin"}` to the RunStart topic.
It does not wait for the retired main-FSM Course-ready or RunStart-applied ACK.
The task nodes decide execution order, preemption, recovery, and actuator use.

## Troubleshooting

- No `[RxVehicle]`: verify the Orin broker address, MQTT reachability, and the
  exact `/tongji_mrl/twave/heartbeat` topic.
- `waiting for fresh MAVROS telemetry`: restore the FCU/MAVROS link and its
  state, GPS, heading, velocity, and IMU inputs. OCS cannot create vehicle
  telemetry that the Orin did not publish.
- No `DECLARATION_PUBLISHED`: confirm that RBC delivered a valid Course during
  startup and that the official broker address is correct.
- No `HEARTBEAT_PUBACK`: inspect the official broker connection and RBC topic
  permissions.
- RunStart is not forwarded: confirm a task-node subscriber exists on
  `/tongji_mrl/mission/run_start`, and inspect OCS's official command/declaration
  validation logs.

## Testing

Run OCS tests from the `OCS` directory:

```powershell
cd OCS
python -m unittest test_usv_only_gateway test_fsm_interface_alignment test_ocs_client test_operation_mode test_realtime_heartbeat test_fsm_protocol test_fsm_monitor test_monitor_ui test_uav_status test_uav_geofence test_ros2_ground_input test_ocs_gateway_uav_mode
python -m py_compile heartbeat_cache.py vehicle_link.py ocs_gateway.py
```

These are local/simulated checks. They do not constitute live RBC acceptance,
real-vessel verification, or actuator testing.

## Supporting documentation

- [USV-only change report](docs/USV_ONLY_CHANGE_REPORT.md)
- [USV-only run guide](docs/USV_ONLY_RUN_GUIDE.md)
- [USV-only regression record](docs/USV_ONLY_REGRESSION_TEST.md)
- [UAV interface isolation](docs/UAV_INTERFACE_ISOLATION.md)
