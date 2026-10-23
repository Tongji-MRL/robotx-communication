# OCS FSM integration

The monitor is a read-only consumer of `twave-mission-status-v2`.
The formal source is `/tongji_mrl/mission/status`; the MQTT representation is
`tongji/robotx/v1/T-Wave/mission_status` using the existing v1 envelope.
`protocol_version` remains `"1"`; the full FSM payload retains its separate
`schema_version: "twave-mission-status-v2"`.

The current production bridge does not publish this MQTT topic. The optional
`OCS/ros2_status_mqtt_adapter.py --enable` is separate: it subscribes only to
status, publishes no ROS command, changes no FSM state or safety input, and
starts no executor. Windows read-only use therefore does not need ROS 2.

Formal status-v2 does not expose Task4Guard durable phase, pause-ACK map,
checkpoints, command ID/sequence, or official report sequence. The UI displays
unreported rather than reading guard persistence or inferring confirmation.
