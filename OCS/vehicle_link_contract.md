# OCS ⇄ UAV/USV 内部通信协议 v1（草案）

更新时间：2026-10-08

本协议只定义 OCS 与车辆的必要信息通信，不定义 UAV⇄USV 的任务数据交换。官方
RoboCommand 仍只连接 OCS；车辆不连接官方 RoboCommand。任务选择、Task4 抢占、
Task1/3 恢复由 USV 任务协调器负责，OCS 不做任务判断。

## 1. 通信边界

```text
UAV ── heartbeat/task_report/fault ─┐
                                    ├─ OCS ─ MQTT + Protobuf ─ RoboCommand
USV ── heartbeat/task_report/fault ─┘
                 OCS ─ command ─> USV 任务协调器 ──> UAV（内部链路）
```

OCS 只接收车辆的必要状态、任务结果和故障，并向车辆发送运行许可、安全停止和
官方 Task 4 指令。原始相机、雷达、点云、详细规划路径、PX4 setpoint、推进器/水泵/
夹爪/云台控制指令不进入本协议。

## 2. Topic 约定

根路径固定为：

```text
tongji/robotx/v1/<vehicle_id>
```

| Topic | 方向 | 发送时机 | QoS/retain | 内容 |
|---|---|---|---|---|
| `.../heartbeat` | UAV/USV → OCS | 建议 2 Hz | QoS 1，不 retain | 车辆实时状态，供 OCS 生成官方 Heartbeat |
| `.../task_report` | UAV/USV → OCS | 任务结果变化时 | QoS 1，不 retain | 官方 Task 1/3 所需结果 |
| `.../fault` | UAV/USV → OCS | 故障或恢复立即发送 | QoS 1，不 retain | 故障码、影响和安全建议 |
| `.../command` | OCS → USV | 运行开始、停止、官方 Task 4 | QoS 1，不 retain | USV 任务协调器接收并决定如何执行/转发 |
| `.../ack` | USV/UAV → OCS | 每条 command 后 | QoS 1，不 retain | 对应消息、接受结果和处理状态 |

`<vehicle_id>` 当前为 `T-Sky` 或 `T-Wave`。Topic 中的车辆 ID 必须与 envelope 中的
`vehicle_id` 一致。本协议命名空间内不存在 UAV⇄USV 直接 Topic；两车直连使用独立
`tongji/robotx/fsm/v1/...` 命名空间，见 `../docs/uav_usv_state_machine_link.md`。

## 3. JSON envelope

所有内部消息使用 UTF-8 JSON，每条消息都必须有以下字段：

```json
{
  "protocol_version": "1",
  "message_id": "uuid",
  "run_id": 42,
  "sent_at_unix_ms": 0,
  "source": "T-Wave",
  "vehicle_id": "T-Wave",
  "kind": "heartbeat",
  "payload": {}
}
```

约束：

- `message_id`：全局唯一，用于 ACK 和日志关联；
- `run_id`：官方 `RunStart` 前为 `null`，运行中必须为当前 run；
- `source`：实际发送者，OCS 使用 `ocs`，车辆使用自身 ID；
- `vehicle_id`：消息代表或目标车辆；
- `kind`：必须与 Topic 最后一段一致；
- `sent_at_unix_ms`：发送时间，不使用接收时间代替；
- 有位置时，`payload` 必须携带 `frame_id`，不得猜测坐标系；
- 没有可靠来源的字段省略或填 `null`，不得用 0 冒充真实数据。

## 4. 五类消息的 payload

### 4.1 `heartbeat`：车辆 → OCS

```json
{
  "state": "AUTO",
  "current_task": "TASK1",
  "position": {
    "frame_id": "wgs84",
    "latitude_deg": null,
    "longitude_deg": null,
    "altitude_m": null
  },
  "speed_mps": null,
  "heading_deg": null,
  "roll_deg": null,
  "pitch_deg": null,
  "depth_m": null,
  "flight_phase": null,
  "health": {
    "fcu_connected": true,
    "sensors_ok": true,
    "battery_percent": null
  },
  "fault": null
}
```

OCS 将其转换为每车独立的官方 `RxReport.Heartbeat`。车辆失联后，OCS 不得继续用旧
心跳伪造官方状态。

### 4.2 `task_report`：车辆 → OCS

```json
{
  "task": "TASK1",
  "phase": "COMPLETE",
  "authority": "USV",
  "official_report": {
    "type": "safe_passage",
    "entry_position": {"latitude": null, "longitude": null},
    "exit_position": {"latitude": null, "longitude": null},
    "buoys": []
  },
  "result": {},
  "completed_at_unix_ms": 0,
  "failure_reason": null
}
```

`official_report` 只由 USV 在完成必要的 UAV/USV 信息汇总后提供；OCS 只负责格式转换和
发送，不根据 `phase=COMPLETE` 自己推断任务完成。其内容只包含官方需要的字段：

- Task 1：入口、出口、浮标 ID/位置/灯光状态；
- Task 3 docking：`bay_id`；
- Task 3 firefighting：`window_id`；
- Task 3 delivery：资源颜色、投放圆颜色、目标位置、抓取/释放结果。
- Task 4：`report_type=READINESS`、对应官方 `command_seq` 和车辆当前可执行状态；

USV 作为协调器代 UAV 上报时，`official_report.vehicle_id` 或 ACK 中的
`subject_vehicle_id` 必须填写被代表的车辆；OCS 会按该 ID 发布官方报告，不能默认
把 USV 的消息归到 USV 自身。

### 4.3 `fault`：车辆 → OCS

```json
{
  "fault_code": "FCU_DISCONNECTED",
  "severity": "STOP",
  "task": "TASK1",
  "detail": "...",
  "recoverable": false,
  "occurred_at_unix_ms": 0
}
```

### 4.4 `command`：OCS → 车辆

统一 payload：

```json
{
  "command": "RUN_START",
  "command_seq": 12,
  "priority": "NORMAL",
  "preempt": false,
  "parameters": {}
}
```

允许的第一版命令：

| command | 使用条件 | 必要参数 |
|---|---|---|
| `RUN_START` | OCS 已验证官方 `RunStart` | `run_id` 在 envelope 中 |
| `SAFE_STOP` | 官方结束、故障或人工安全停止 | `reason`、`stop_mode`；安全覆盖，不属于普通任务优先级 |
| `TASK4_ASSISTANCE` | OCS 收到官方 AssistanceRequest 后转给 USV | 目标位置、官方 `command_seq`；USV 决定本地优先级 |
| `TASK4_KEEP_OUT_ZONE` | OCS 收到官方 KeepOutZone 后转给 USV | 中心、半径、车辆类型、官方 `command_seq` |
| `TASK4_ALL_CLEAR` | OCS 收到官方 AllClear 后转给 USV | 车辆类型、官方 `command_seq` |
| `TASK4_MOVING_OBJECT` | OCS 收到官方 MovingObjectAlert 后转给 USV | 位置、航向、速度、官方 `command_seq` |
| `TASK4_RESUME` | 仅 USV 任务协调器内部使用 | 被抢占任务、恢复断点或 `resume_token` |
| `PING` | 仅内部联调 | 无；不触发真实执行器 |

### 4.5 `ack`：车辆 → OCS

```json
{
  "in_reply_to": "command-message-uuid",
  "command": "RUN_START",
  "command_seq": 12,
  "subject_vehicle_id": "T-Sky",
  "accepted": true,
  "state": "ACCEPTED",
  "preempted_task": "TASK1",
  "detail": "position hold enabled"
}
```

ACK 规则：

- 每条 `command` 必须返回 ACK；
- 建议 1 秒内返回接收 ACK；
- Task 4 命令的 ACK 必须明确说明当前任务是否已暂停/抢占；
- 3 秒未收到 ACK，OCS 记录超时并进入待确认状态；
- 不自动重发可能触发执行器的命令；
- 当前 `vehicle_agent.py` 默认拒绝真实控制命令。

## 5. 运行状态规则

1. OCS 收到 retained `RxCourse` 并完成校验。
2. OCS 发布官方 `RunDeclaration`。
3. OCS 收到并验证 `RunStart.declaration_seq` 后，只向 USV 任务协调器发送 `RUN_START`。
4. USV 回 ACK，并负责启动/协调 UAV；OCS 不直接启动 UAV 任务。
5. 车辆以 2 Hz 发送 `heartbeat`；任务结果只在变化或完成时发送。
6. Task 4 是任务级最高优先级。Task 1/3 执行中收到 Task 4 命令时，由 USV 保存当前
   任务、阶段和恢复断点，并决定是否暂停 UAV/USV 当前任务。
7. USV 完成本地抢占、Task4 执行和恢复；OCS 只转发官方命令，并根据 USV 的 ACK/报告
   生成官方 `IncidentAck`/`ReadinessReport`。
8. AssistanceRequest 必须完成 `IncidentAck → ReadinessReport → ReadinessConfirm`；
   KeepOutZone 必须保持避让直到 AllClear；MovingObjectAlert 必须立即执行避让策略。
9. Task 4 官方响应链完成或风险解除后，由 USV 发送内部 `TASK4_RESUME`，车辆才可恢复被抢占任务。
10. 新 `run_id` 开始后，旧 run 的延迟消息只记录日志，不更新当前状态。
11. `SAFE_STOP`/急停是安全覆盖，不等待 Task 4 完成；故障优先级高于普通任务。

## 6. 暂不纳入本协议

- UAV⇄USV 直接任务数据；
- UAV 地图到 USV 地图的 NED 转换；
- 原始 ROS 2 Topic；
- 原始感知数据和传感器流；
- 低层飞控、推进器、水泵、夹爪和云台命令。
