# Task3 子状态机与总规划器 ROS 2 接口

更新时间：2026-10-14  
协议版本：`task3-ros-v1`

## 1. 责任边界

`task3_communication_adapter` 负责 JSON 校验、编码、去重、Task3 progress、正确泊位报告、
喷水窗口报告、命令 ACK/转发以及 UAV/USV heartbeat 超时监测。

该节点不直接控制船、PX4、推进器、泵或云台。命令被 ACK 为 `DISPATCHED` 只代表通过校验并
转发给 Task3 executor，不代表动作完成。

## 2. Topic

全部使用 `std_msgs/msg/String`，内容为 UTF-8 JSON。

| Topic | 方向 | 频率/时机 | 内容 |
|---|---|---|---|
| `/tongji_mrl/twave/task_cmd` | 总规划器 → adapter | 事件触发 | Task3/Task4 命令 |
| `/tongji_mrl/twave/task_ack` | adapter → 总规划器 | 每条有效命令 | `DISPATCHED` 或 `DUPLICATE_IGNORED` |
| `/tongji_mrl/twave/task3/control_command` | adapter → Task3 executor | 每条首次有效命令 | 规范化命令；实际执行方必须另行报告结果 |
| `/tongji_mrl/twave/task3/state` | Task3 executor → adapter | 当前 1 Hz | executor 状态 |
| `/tongji_mrl/twave/progress` | adapter → 总规划器 | 状态/窗口变化时 | 14 位状态码和结构化详情 |
| `/tongji_mrl/twave/task3/correct_bay` | Task3 流程 → adapter | bay 确认/靠泊确认时 | 正确泊位权威输入 |
| `/tongji_mrl/twave/task3/sprayer_window` | 喷水流程 → adapter | 窗口状态变化时 | RED/GREEN、泵状态、绿色确认时长 |
| `/tongji_mrl/twave/task_report` | adapter → 总规划器 | 权威完成事件 | docking/firefighting official report |
| `/tongji_mrl/twave/fault` | adapter → 总规划器 | heartbeat 丢失/恢复 | 双机 heartbeat fault |
| `/tongji_mrl/twave/heartbeat` | USV 状态机 → adapter | 2 Hz | T-Wave 车辆 heartbeat |
| `/tongji_mrl/tsky/heartbeat` | UAV 状态机 → adapter | 2 Hz | T-Sky 车辆 heartbeat |

adapter 只订阅和监测 heartbeat，不伪造 GPS、姿态或车辆模式。两台车辆各自负责发布真实
heartbeat。默认超过 3 秒未收到视为失联；启动后默认有 5 秒宽限期。

## 3. Progress

现有 `/tongji_mrl/twave/task3/state` 会映射到冻结的 14 位状态码。例如：

```json
{
  "protocol_version": "task3-ros-v1",
  "message_id": "uuid",
  "run_id": 42,
  "sequence": 8,
  "sent_at_unix_ms": 1791900000000,
  "source": "T-Wave",
  "task": "TASK3",
  "kind": "progress",
  "message_type": "TASK3_PROGRESS",
  "status_code": 12672,
  "status_bits": "1 10 0011 0000 000",
  "status": {
    "vehicle": "USV",
    "task": "TASK3",
    "step": "SEARCH_DOCK",
    "error": "NONE",
    "command": "NONE"
  },
  "payload": {
    "executor_state": "SEARCH_DOCK",
    "ready_for_task_logic": true,
    "dry_run": false,
    "detail": ""
  }
}
```

完整步骤和 fault 见 `TASK3_COMMUNICATION_PROTOCOL.md` 与 `TASK3_ERROR_CATALOG.md`。

## 4. 正确泊位信息

Task3 流程在确认正确 bay 后发布，并在最终靠泊确认后以同一格式再次发布：

```json
{
  "run_id": 42,
  "bay_id": 2,
  "dock_id": "dock-A",
  "confidence": 0.94,
  "confirmed_at_unix_ms": 1791900000000,
  "docking_confirmed": false,
  "source": "task3_flow"
}
```

约束：

- `bay_id` 只能为 1、2、3；
- `confidence` 为 `[0,1]`；
- `docking_confirmed=false` 时只生成 `TASK3_CORRECT_BAY` progress，让总规划器及时获得
  `dock_id/bay_id/confidence`；
- `docking_confirmed=true` 时除 progress 外再生成正式 docking report；
- 感知到绿色 bay、入口对齐或进入入口均不能代替最终靠泊确认。

输出到 `/tongji_mrl/twave/task_report` 的核心字段：

```json
{
  "task": "TASK3",
  "phase": "DOCKING_COMPLETE",
  "authority": "USV",
  "official_report": {
    "type": "docking",
    "vehicle_id": "T-Wave",
    "bay_id": 2
  }
}
```

## 5. 喷水窗口信息

窗口状态输入：

```json
{
  "run_id": 42,
  "window_id": 1,
  "color": "GREEN",
  "confidence": 0.92,
  "observed_at_unix_ms": 1791900005000,
  "pump_off": true,
  "green_confirmed_duration_s": 5.0,
  "completion_confirmed": true,
  "source": "watering_controller"
}
```

每条有效窗口信息都会形成 `TASK3_SPRAYER_WINDOW` progress。只有同时满足以下四个条件，
才生成正式 firefighting report：

1. `color == GREEN`；
2. `pump_off == true`；
3. `green_confirmed_duration_s >= 5.0`；
4. `completion_confirmed == true`。

正式报告核心字段：

```json
{
  "task": "TASK3",
  "phase": "FIREFIGHTING_COMPLETE",
  "authority": "USV",
  "official_report": {
    "type": "firefighting",
    "vehicle_id": "T-Wave",
    "window_id": 1
  }
}
```

RED、未停泵、绿色不足 5 秒或未得到流程控制器确认时只上报 progress。

## 6. Heartbeat

两个 heartbeat topic 都使用 OCS 车辆协议 `protocol_version=1`：

```json
{
  "protocol_version": "1",
  "message_id": "uuid",
  "sent_at_unix_ms": 1791900000000,
  "run_id": 42,
  "vehicle_id": "T-Wave",
  "source": "T-Wave",
  "frame_id": "wgs84",
  "kind": "heartbeat",
  "payload": {
    "state": "AUTO",
    "current_task": "TASK3",
    "position": {
      "frame_id": "wgs84",
      "latitude_deg": 1.28,
      "longitude_deg": 103.85,
      "altitude_m": 0.0
    },
    "speed_mps": 0.3,
    "heading_deg": 90.0,
    "health": {
      "fcu_connected": true,
      "sensors_ok": true
    }
  }
}
```

Topic 与 `vehicle_id` 必须匹配。未知数据使用 `null`，不能用 0 冒充；位置整体未知时可将
`position` 设为 `null`。正式连接 OCS 前仍需保证 OCS 对未知位置的处理方式一致。

## 7. Command、ACK 与 Task4 恢复

推荐命令：

```json
{
  "command_id": "resume-17",
  "run_id": 42,
  "command": "RESUME_TASK3",
  "payload": {
    "checkpoint_id": "checkpoint-7"
  }
}
```

也兼容当前 `task_id/action/command_seq/parameters` 旧格式。首次有效命令被转发到
`/tongji_mrl/twave/task3/control_command`；重复 `command_id` 不重复转发。

Task4 到达目标后，Task3 必须保持 `WAIT_RESUME`。只有总规划器选择继续 Task3 并下发
`RESUME_TASK3(checkpoint_id)` 后才恢复。总规划器选择 Task1 时，Task3 checkpoint 保留，
Task3 不自行恢复。

## 8. 构建和 dry-run 联调

```bash
cd ~/robotx_ws
colcon build --packages-select usv_task3_executor
source install/setup.bash
ros2 launch usv_task3_executor task3_communication_adapter.launch.py run_id:=42
```

该启动只运行通信 adapter，不启动导航、PX4、泵或云台。
