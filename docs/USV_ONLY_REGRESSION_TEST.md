# USV-only regression test record

## Automated local tests

Run from `OCS` using its established import layout:

```powershell
python -m unittest test_usv_only_gateway test_operation_mode test_ocs_gateway_uav_mode test_realtime_heartbeat test_ocs_client test_fsm_protocol test_fsm_interface_alignment test_fsm_monitor
```

Result: the first USV-only set had **74 tests passed**. The current expanded
local suite has **111 tests passed**, including the follow-up default/isolation
checks and retained UAV status/geofence/ROS2/Monitor tests.

This includes new checks that the profile declares only T-Wave, rejects a
placeholder RBC host, disables gateway UAV ROS2/geofence paths, subscribes only
to the T-Wave heartbeat topic, and rejects a T-Sky topic under that mapping.
The follow-up checks are static/unit checks only; they do not contact a broker.

The current USV task-node adaptation also verifies that a fully validated
RunStart bypasses only the retired main-FSM ACK wait in `usv_only`, is forwarded
once, and serializes to the exact ROS2 JSON `{"command":"begin"}`. RBC
validation remains covered by the existing OCS client tests.

The heartbeat regression also verifies that source timestamps may be absent,
old, or future-dated without blocking the cache or expiring a received entry.
All non-timestamp heartbeat validation remains covered.

Existing tests exercised the retained RBC protocol behavior: QoS1/PUBACK
heartbeat transport, sequences/run correlation, Course fingerprint, Task4
readiness/AllClear flows, fault/report paths, duplicate commands, and
stale/old declaration guards. The legacy Course-ready gate and RunStart
applied-ACK tests remain applicable only to the retained dual/UAV interface;
they are intentionally not prerequisites in the USV task-node architecture.

## What this does not prove

The suite is unit/local integration coverage. It does not connect to a real
RBC server, a real Windows broker, live DDS, T-Wave Orin, or USV actuators.
No real RBC command was sent during this change.

## Required follow-up tests

| Level | Required evidence |
| --- | --- |
| Simulated integration | T-Wave heartbeat at 2 Hz remains fresh for an extended run; inspect PUBACK counters, report sequence, run ID binding, and official vehicle ID. |
| Simulated integration | Send an RBC Course then valid RunStart; observe ROS2 Course forwarding and one exact `{"command":"begin"}` RunStart publication, plus Task Report, Fault, Task4/AllClear, timeout, duplicate, and old-run protection. |
| Real vessel / RBC site | Have the event RBC accept a `vehicle_ids=["T-Wave"]` declaration and observe only compliant T-Wave Heartbeats. Verify the live FSM and monitor with T-Sky completely absent. |

## Behavior difference from prior RBC-tested build

When launched through the new USV-only profile, the gateway no longer waits
for, consumes, or reports T-Sky status/geofence inputs. The RBC client behavior
itself is unchanged; the only intended official difference is the declared
vehicle set and consequently only T-Wave official heartbeats.
