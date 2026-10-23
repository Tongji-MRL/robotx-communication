# OCS interface matrix

| Topic | Publisher | Consumer | Status |
|---|---|---|---|
| `/tongji_mrl/mission/status` | Formal MissionPlanner | optional adapter | formal read-only source |
| `tongji/robotx/v1/T-Wave/mission_status` | optional adapter/future Bridge | monitor UI | implemented |
| `tongji/robotx/v1/+/heartbeat` | vehicle adapters | monitor UI | existing preserved |
| `tongji/robotx/v1/+/ack`, `task_report`, `fault` | vehicle adapters | monitor UI | existing preserved |
| `tongji/robotx/v1/T-Wave/course_config` | OCS Gateway | FSM/monitor | existing preserved |
| `tongji/robotx/v1/T-Wave/command` | UI only in lab mode | lab receiver | default disabled |

Mapping: `fsm_state` is global FSM; `run_id` is the visible RunStart run;
`course.fsm_accepted` and `course.uav_applied` remain separate; `safety` feeds
the safety card; and `vehicles.{usv,uav}` feeds the vehicle/task cards.
