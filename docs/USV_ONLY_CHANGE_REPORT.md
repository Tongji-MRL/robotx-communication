# RobotX 2026 USV-only change report

## Scope and result

The formal OCS gateway default is now USV-only: invoking `ocs_gateway.py`
without `--config` or `--vehicle-mode` selects `OCS/config.usv-only.json` and
`usv_only`. Its only declared vehicle is `T-Wave` for team `TONG`; `T-Wave`
remains the mission coordinator. The default configuration deliberately has a
placeholder RBC host, so the operator must supply field connection details.

This is a mode/configuration adaptation, not a replacement of the existing
RoboCommand client or the mission state machine.

## Changed files

| File | Change |
| --- | --- |
| `OCS/config.usv-only.json` | New explicit production profile containing only T-Wave and no UAV declaration values. The RBC host remains a required operator-supplied value. |
| `OCS/ocs_gateway.py` | In `usv_only`, disables UAV ROS2 status/geofence I/O and passes only the T-Wave heartbeat topic to the internal MQTT adapter. Course, RunStart and Task4 still use their existing ROS2 paths. |
| `OCS/vehicle_link.py` | Adds a constrained heartbeat-topic map at the receive boundary. Default dual/UAV behavior is unchanged. |
| `OCS/monitor_ui.py` | Adds read-only `--usv-only`; it subscribes only to T-Wave and does not create a UAV ROS2 observer. |
| `scripts/start_ocs_usv_only.bat` | New Windows launcher that always selects the USV-only config/mode. |
| `OCS/test_usv_only_gateway.py` | New mode-boundary regression coverage. |

Explicit `--vehicle-mode dual_vehicle` remains available. It requires a
complete `vehicles.uav` mapping (`vehicle_id`, `source_vehicle_id`, and
`uav_registration`) before any connection attempt; it never changes RBC host,
port, topic, or protocol selection automatically.

## Disabled from the formal USV-only path

- T-Sky raw heartbeat MQTT subscription.
- T-Sky ROS2 status subscription and status-to-official-heartbeat cache path.
- UAV geofence publisher and FCU/readback discovery/subscription.
- UAV configuration requirement in the USV-only profile.

Historical UAV modules, flight profiles, tests, and protocol fields remain in
the repository for audit/recovery and are not started by the USV-only default.
See `UAV_INTERFACE_ISOLATION.md` for the retained interfaces and recovery path.

## RBC and FSM invariants not changed

`OCS/ocs_client.py` was not modified.  In particular, this change does not
alter RBC MQTT connection/topics/QoS, Protobuf encoding/decoding, QoS1
non-blocking Heartbeat/PUBACK handling, heartbeat frequency/timestamp/sequence
handling, Course fingerprints, RunDeclaration publishing, RunStart validation,
Task Report/Fault/Readiness/Task4 handling, or old-run/duplicate protection.

`usv_main_fsm` and USV actuator logic were not modified.  OCS still only
validates and forwards Course, RunStart and supported Task4 events.  It does
not choose task order, preemption, or recovery.

### Heartbeat timestamp policy

The USV heartbeat cache no longer compares Orin source timestamps with the
Windows clock and has no source-timestamp expiry window. A received heartbeat
remains eligible until replaced or its declaration/run context is reset.
Source timestamp values remain diagnostic metadata only. Vehicle identity,
message-ID deduplication, run binding, and all non-timestamp telemetry
validation remain unchanged.

### USV task-node RunStart contract

The USV Orin no longer uses the former main-FSM Course-ready/RunStart-applied
acknowledgement contract. In `usv_only`, OCS still performs all official RBC
Course, declaration, Team ID, command sequence, declaration sequence, and
nonzero run ID validation, then directly publishes the exact ROS2 payload
`{"command":"begin"}` to `/tongji_mrl/mission/run_start`. It records
`RUNSTART_FORWARDED`; it does not claim an applied acknowledgement that the new
task-node architecture does not provide. Dual/UAV modes retain their prior
Course-ready and applied-ACK gate.

## Protocol compatibility note

The checked-in official protobuf permits a RunDeclaration with only `T-Wave`;
the existing declaration builder requires UAV geofence/callsign only when a
declared ID is `T-Sky` or `UAV*`.  USV-only deliberately emits empty/default
UAV-specific protobuf fields rather than deleting them from the official
schema.  Final acceptance of a single-USV declaration remains an RBC field
test item.

## Remaining compatibility risks

- The actual RBC competition server has not yet been exercised with the new
  single-vehicle declaration.
- The real T-Wave Orin must still publish the currently validated JSON shape
  on `/tongji_mrl/twave/heartbeat`.
- The real USV task nodes must be checked on the configured ROS domain for
  Course consumption and handling of `{"command":"begin"}`; no UAV status is
  fabricated if a task needs unavailable UAV input.
