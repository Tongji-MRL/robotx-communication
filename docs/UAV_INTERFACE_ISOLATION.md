# UAV interface isolation

## Retained interfaces

No UAV protocol implementation was deleted. The following remain available for
an explicitly configured `dual_vehicle`/UAV workflow:

- ROS2 `std_msgs/msg/String` status input: `/tongji_mrl/tsky/uav_status`, with
  the existing `source_vehicle_id` identity mapping, JSON normalization, and
  reliable/volatile QoS in `Ros2MissionLink`.
- Internal MQTT: `/tongji_mrl/tsky/heartbeat` and the existing
  `uav_status_mqtt_bridge.py`, `VehicleLink`, heartbeat cache/timeout handling,
  and official UAV Heartbeat conversion.
- UAV geofence: existing Course geometry validation, candidate calculation,
  `/tongji_mrl/tsky/uav_geofense_sub` publication,
  `/tongji_mrl/tsky/uav_geofense_pub` readback discovery/subscription, parser,
  comparison, safety gates, and tests.
- Configuration/templates and tests: `config.example.json`,
  `config.uav-status.example.json`, `config.uav-ground.example.json`,
  `test_uav_status.py`, `test_uav_geofence.py`, and the UAV ground-validation
  materials.

Topic names, JSON payloads, QoS, and callback implementations are unchanged.

## USV-only isolation boundary

`ocs_gateway.py` defaults to `config.usv-only.json` and `usv_only`.
In that mode it:

- subscribes only to `/tongji_mrl/twave/heartbeat` on internal MQTT;
- creates no UAV MQTT-status subscription or UAV Heartbeat cache input;
- creates no UAV ROS2 status subscription;
- creates no UAV geofence publisher or readback subscription;
- declares only `T-Wave`, so an unexpected T-Sky MQTT publication cannot create
  an official UAV report or change the declaration;
- retains Course, RunStart, Task4, status, task-report, and fault ROS2 paths
  for the T-Wave FSM.

The Monitor UI retains its UAV display implementation. Its default (and
`--usv-only`) does not subscribe to UAV MQTT/ROS2 data; absence of UAV data is
therefore not reported as a T-Wave or RBC connection fault. Use explicit
`--dual-vehicle` only for an approved dual monitoring session.

## Explicit future re-enable path

Use an approved dual-vehicle configuration and explicitly pass both options:

```powershell
cd D:\RobotX\robotx-rc-lab\OCS
python .\ocs_gateway.py --config .\config.example.json --vehicle-mode dual_vehicle `
  --official-broker <rbc-host> --internal-broker <team-broker>
```

Before it opens communications, dual mode requires non-empty
`vehicles.uav.vehicle_id`, `source_vehicle_id`, and `uav_registration`.
The existing declaration/geofence validation remains in force. No observed UAV
topic can select this mode, and mode selection never modifies RBC connection
settings.

## Non-goals

This isolation layer does not create a second RBC client, change `ocs_client.py`,
or make OCS a task planner. The T-Wave FSM remains the sole owner of task
ordering, preemption, and recovery decisions.
