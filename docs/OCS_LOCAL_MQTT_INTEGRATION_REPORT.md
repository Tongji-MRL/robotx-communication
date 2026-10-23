# OCS local MQTT integration report

## Contract and topic

The simulator uses the formal `twave-mission-status-v2` payload fields from
`FSM_audit`: `schema_version`, `run_id`, `timestamp`, `fsm_state`, `course`,
`safety`, `vehicles`, and `legacy`. It puts that payload unchanged inside the
existing protocol-v1 envelope and publishes only to
`tongji/robotx/v1/T-Wave/mission_status`. It also publishes simulated
heartbeats to the existing `T-Wave` and `T-Sky` heartbeat topics.

Every generated payload/envelope uses `simulation: true` or source
`local-fsm-simulator`. The CLI accepts only `127.0.0.1`, `localhost`, or
`::1`; it cannot be pointed at a production broker.

## Commands

Start an isolated local MQTT broker and the read-only UI in separate terminals:

```bat
scripts\start_monitor_readonly.bat --broker 127.0.0.1
scripts\run_local_monitor_test.bat
```

Direct one-shot publish example:

```bat
python OCS\tools\local_fsm_simulator.py --broker 127.0.0.1 --scenario TASK1_ACTIVE --count 1
```

## Scenario mapping

`WAIT_COURSE`, `COURSE_ACCEPTED`, and `WAIT_RUN_START` use actual
`WAIT_FOR_BEGIN`. The formal status has no `run_start_received` field, so the
last two cannot be distinguished from status-v2 alone. `TASK1_ACTIVE` and
`TASK3_ACTIVE` use `TASK1_EXECUTE` and `TASK3_EXECUTE`. There is no formal
`TASK4_WAITING`/`TASK4_PAUSED` FSM enum: both retain `TASK3_EXECUTE` and show
`WAITING_SAFE_PAUSE`; only the latter reports vehicle progress `PAUSED`.
`FAULT` uses actual `FAILED` and `SAFE_STOP`. `DISCONNECTED` publishes nothing.

## Results

Static/unit verification is executed with `python -m unittest discover -s OCS
-p "test_*.py"`. The batch script verifies local broker reachability, HTTP
state retrieval, status contract receipt, Course FSM/UAV distinction, two
heartbeats, default `POST /api/command` rejection, and FSM expiration.

Live local broker-to-HTTP verification was executed on 2026-10-21 with an
already running `127.0.0.1:1883` broker and a temporary UI bound to
`127.0.0.1:8080` (`--stale-after 3`). A continuously publishing local-only
`TASK1_ACTIVE` simulation produced: received=true, online=true,
schema=`twave-mission-status-v2`, fsm=`TASK1_EXECUTE`, run_id=202601,
`uav_applied=false`, and both heartbeats present. A default-mode POST PING
returned HTTP 403. After stopping the simulator, mission status became
`超时` at 4.78 seconds and the USV heartbeat became offline. The temporary
simulator and monitor processes were then stopped.

All named scenarios have contract/static coverage. The live MQTT path was
exercised with `TASK1_ACTIVE`; no claim is made that a physical vehicle or
formal ROS node executed the other scenarios. The batch script reports clear
prerequisites and refuses a non-local UI broker.

## Remaining formal Bridge work

The production Bridge still needs a reviewed `/tongji_mrl/mission/status` to
MQTT forwarding implementation. No real Orin, ROS graph, official
RoboCommand, Task4Guard persistence, or executor was tested. After the local
batch test passes, the monitor is ready for that read-only ROS2 Bridge adapter
validation.
