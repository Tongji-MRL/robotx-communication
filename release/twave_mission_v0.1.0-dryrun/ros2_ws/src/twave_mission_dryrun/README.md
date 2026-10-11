# `twave_mission_dryrun`

This is a ROS 2 Humble **dry-run-only** package.  It wraps, rather than
rewrites, `usv_main_fsm.MissionCoordinator`; `dry_run=false` raises at node
startup.  It has no hardware, PX4, MAVROS, propulsion, pump, or gimbal topics.

## Test topics (`std_msgs/msg/String`, UTF-8 JSON)

| Topic | Direction | Required JSON fields in addition to `schema_version`, `timestamp`, `run_id` |
|---|---|---|
| `/test/twave/mission/command_in` | test OCS -> coordinator | `command_id`, `command` (`RUN_START`, `TASK4_PREEMPT`, `TASK4_RELEASE`, `SAFE_STOP`), `parameters` |
| `/test/twave/mission/usv_command` | coordinator -> fake USV | `command_id`, `target`, `action`, `task`, `parameters`, `dry_run:true` |
| `/test/twave/mission/usv_ack` | fake USV -> coordinator | `command_id`, `target`, `accepted`, optional `safe_paused`, `progress_marker`, `detail` |
| `/test/twave/mission/usv_event` | fake USV -> coordinator | `event_id`, `task`, `target`, `authoritative`, `succeeded`, optional `detail` |
| `/test/twave/mission/state` | coordinator -> observers | `state`, `task`, `pending_command_ids`, `dry_run:true`, optional `note` |
| `/test/twave/mission/fault` | fake USV -> coordinator; bridge diagnostics -> observers | `target`, `code`, optional `detail`; diagnostics add `source:"mission_bridge"` |
| `/test/twave/mission/usv_test_in` | test driver -> fake USV | `dry_run:true`, `kind` (`complete`, `fault`, `next_ack`) plus kind-specific fields |
| `/test/twave/mission/safety_input` | isolated test driver -> SafetyMonitor | `event_id`, `fault`, `active`, `trustworthy`, `source`, optional `clears_event_id`; reset additionally requires `kind:"RESET_SAFE_STOP"`, `test_only:true` and all reset checks |

`schema_version` is always `twave-mission-dryrun-v1`; `timestamp` is UTC ISO-8601.
`run_id` correlates a mission, while every command and ACK shares `command_id`.
Events use a unique `event_id` and must match active `run_id`/task. ACK only
settles delivery: it never advances Task1/Task3.  Repeated commands, stale
runs, duplicate ACKs and bridge-originated faults are ignored safely.

The fake executor emits an ACK for each received task command but never creates
a completion on a timer.  Send an explicit `complete` test input to advance.

## Provisional safety behavior

`SafetyMonitor` classifies injected health events using candidate rules: link,
executor, navigation, and sensor faults request `HOLD`; flight-controller
critical fault, uncontrolled movement, and manual E-stop request `CRITICAL`.
Unknown/untrustworthy safety data is never `NORMAL` (it requests `HOLD`).
These are dry-run defaults, not agreed vessel safety thresholds.

`HOLD` stops new scheduling, emits `SAFE_HOLD`, and records its source/reason.
Executor ACKs with `safe_paused` plus progress can form a checkpoint, but a
cleared fault never resumes a task.  `CRITICAL` emits `SAFE_STOP`, writes a
software latch beside the checkpoint, and survives a process restart.  It does
not prove a vehicle stopped and cannot clear hardware E-stop/PX4 failsafe.

Only `safety_input` with `test_only:true` exposes reset, strictly for isolated
tests. It requires a fresh authorization run id, monitor health `NORMAL`, and
all supplied executor/failsafe/reinitialization checks. Success enters `IDLE`,
never a task. It is not a production ROS reset interface.

Example hold, critical stop, clear, and isolated reset:

```bash
ros2 topic pub --once /test/twave/mission/safety_input std_msgs/msg/String '{data: "{\\"schema_version\\":\\"twave-mission-dryrun-v1\\",\\"timestamp\\":\\"2026-10-09T00:10:00Z\\",\\"run_id\\":42,\\"event_id\\":\\"link-lost-1\\",\\"fault\\":\\"OCS_LINK_LOST\\",\\"active\\":true,\\"trustworthy\\":true,\\"source\\":\\"test\\",\\"detail\\":\\"timeout\\"}"}'
ros2 topic pub --once /test/twave/mission/safety_input std_msgs/msg/String '{data: "{\\"schema_version\\":\\"twave-mission-dryrun-v1\\",\\"timestamp\\":\\"2026-10-09T00:11:00Z\\",\\"run_id\\":42,\\"event_id\\":\\"estop-1\\",\\"fault\\":\\"MANUAL_ESTOP\\",\\"active\\":true,\\"trustworthy\\":true,\\"source\\":\\"test\\",\\"detail\\":\\"test estop\\"}"}'
# Clear every active safety event before this test-only reset.
ros2 topic pub --once /test/twave/mission/safety_input std_msgs/msg/String '{data: "{\\"schema_version\\":\\"twave-mission-dryrun-v1\\",\\"timestamp\\":\\"2026-10-09T00:12:00Z\\",\\"run_id\\":42,\\"event_id\\":\\"estop-clear-1\\",\\"fault\\":\\"MANUAL_ESTOP\\",\\"active\\":false,\\"clears_event_id\\":\\"estop-1\\",\\"trustworthy\\":true,\\"source\\":\\"test\\"}"}'
ros2 topic pub --once /test/twave/mission/safety_input std_msgs/msg/String '{data: "{\\"schema_version\\":\\"twave-mission-dryrun-v1\\",\\"timestamp\\":\\"2026-10-09T00:12:30Z\\",\\"run_id\\":42,\\"event_id\\":\\"link-clear-1\\",\\"fault\\":\\"OCS_LINK_LOST\\",\\"active\\":false,\\"clears_event_id\\":\\"link-lost-1\\",\\"trustworthy\\":true,\\"source\\":\\"test\\"}"}'
ros2 topic pub --once /test/twave/mission/safety_input std_msgs/msg/String '{data: "{\\"schema_version\\":\\"twave-mission-dryrun-v1\\",\\"timestamp\\":\\"2026-10-09T00:13:00Z\\",\\"run_id\\":42,\\"event_id\\":\\"reset-1\\",\\"kind\\":\\"RESET_SAFE_STOP\\",\\"test_only\\":true,\\"authorization_id\\":\\"isolated-test-authority\\",\\"authorization_run_id\\":42,\\"severe_faults_clear\\":true,\\"executors_safe\\":true,\\"failsafe_cleared\\":true,\\"reinitialize_ready\\":true}"}'
```

## Ubuntu 22.04 / Humble

```bash
source /opt/ros/humble/setup.bash
cd ~/RobotX/robotx-communication/ros2_ws
# The existing domain package is a sibling of this workspace and is included
# as an explicit base path; it is not copied into the ROS wrapper.
colcon build --base-paths src ../usv_main_fsm ../OCS --packages-select robotx_ocs_protocol usv_main_fsm twave_mission_dryrun --symlink-install
source install/setup.bash
ros2 launch twave_mission_dryrun dry_run.launch.py
# Separate test invocation (the ROS integration test is discovered here):
colcon test --base-paths src ../usv_main_fsm ../OCS --packages-select usv_main_fsm twave_mission_dryrun
colcon test-result --verbose
```

In another sourced shell, inspect state:

```bash
ros2 topic echo /test/twave/mission/state std_msgs/msg/String
```

Start, then explicitly complete Task1 and Task3:

```bash
ros2 topic pub --once /test/twave/mission/command_in std_msgs/msg/String '{data: "{\\"schema_version\\":\\"twave-mission-dryrun-v1\\",\\"timestamp\\":\\"2026-10-09T00:00:00Z\\",\\"run_id\\":42,\\"command_id\\":\\"ocs-run-42\\",\\"command\\":\\"RUN_START\\",\\"parameters\\":{}}"}'
ros2 topic pub --once /test/twave/mission/usv_test_in std_msgs/msg/String '{data: "{\\"dry_run\\":true,\\"kind\\":\\"complete\\",\\"run_id\\":42,\\"task\\":\\"TASK1\\",\\"event_id\\":\\"t1-done\\"}"}'
ros2 topic pub --once /test/twave/mission/usv_test_in std_msgs/msg/String '{data: "{\\"dry_run\\":true,\\"kind\\":\\"complete\\",\\"run_id\\":42,\\"task\\":\\"TASK3\\",\\"event_id\\":\\"t3-done\\"}"}'
```

Task4 preemption / explicit recovery / stop (use before Task3 completion):

```bash
ros2 topic pub --once /test/twave/mission/command_in std_msgs/msg/String '{data: "{\\"schema_version\\":\\"twave-mission-dryrun-v1\\",\\"timestamp\\":\\"2026-10-09T00:01:00Z\\",\\"run_id\\":42,\\"command_id\\":\\"ocs-t4\\",\\"command\\":\\"TASK4_PREEMPT\\",\\"parameters\\":{}}"}'
ros2 topic pub --once /test/twave/mission/usv_test_in std_msgs/msg/String '{data: "{\\"dry_run\\":true,\\"kind\\":\\"complete\\",\\"run_id\\":42,\\"task\\":\\"TASK4\\",\\"event_id\\":\\"t4-done\\"}"}'
ros2 topic pub --once /test/twave/mission/command_in std_msgs/msg/String '{data: "{\\"schema_version\\":\\"twave-mission-dryrun-v1\\",\\"timestamp\\":\\"2026-10-09T00:02:00Z\\",\\"run_id\\":42,\\"command_id\\":\\"ocs-release\\",\\"command\\":\\"TASK4_RELEASE\\",\\"parameters\\":{\\"recovery_permitted\\":true,\\"vehicles_safe\\":true}}"}'
ros2 topic pub --once /test/twave/mission/command_in std_msgs/msg/String '{data: "{\\"schema_version\\":\\"twave-mission-dryrun-v1\\",\\"timestamp\\":\\"2026-10-09T00:03:00Z\\",\\"run_id\\":42,\\"command_id\\":\\"ocs-stop\\",\\"command\\":\\"SAFE_STOP\\",\\"parameters\\":{\\"reason\\":\\"test stop\\"}}"}'
```

To test rejection or ACK timeout, publish `{"dry_run":true,"kind":"next_ack","mode":"reject"}` or `mode:"drop"` to `usv_test_in` immediately before the next command.  `fault` inputs are similarly explicit.

## Windows (no ROS installation)

Do not install `rclpy` with pip.  Run the pure-Python domain tests and bridge
tests from `robotx-communication`:

```powershell
$env:PYTHONPATH = "$PWD;$PWD\ros2_ws\src\twave_mission_dryrun"
python -m unittest discover -s usv_main_fsm\tests -p "test_*.py"
python -m unittest discover -s ros2_ws\src\twave_mission_dryrun\test -p "test_*.py"
```
