# Task1 Bridge 接口约定（第一版）

这是 OCS 与 Orin 上 Task1 之间的最小接口记录。当前只记录已经确认的内容，未确认的启动/取消接口不擅自定义。RoboCommand 只连接 OCS；OCS 与车辆之间的传输方式由团队自行决定。

## RoboCommand Task 1 对外报告

OCS 不应把 `/task1/beacons/results_json` 原样发送给 RoboCommand，而应转换为官方 protobuf 的 `RxReport.safe_passage` / `SafePassageReport`，包含：

- `entry_position`：识别出的入口位置；
- `exit_position`：识别出的出口位置；
- `buoys`：已检测浮标及其 beacon 状态。

当新浮标被检测到或浮标状态发生变化时，重新发布更新后的报告。报告必须使用团队声明的唯一 `vehicle_id`。当前约定为 UAV=`T-Sky`、USV=`T-Wave`，并且必须在 Topic、`RxReport.vehicle_id` 和 `RunDeclaration.vehicle_ids` 中保持一致。

OCS 还要为每个参与车辆独立维护 2Hz 心跳和 `RxReport.seq`，并在 `RunDeclaration` 中填写所有参与车辆的官方 ID。

## 已确认的 ROS 2 Topic

| Topic | 用途 | OCS 当前处理建议 |
|---|---|---|
| `/task1/beacons/results_json` | 感知结果，`std_msgs/msg/String` 内嵌 JSON | 先保留原始数据，不直接映射为 RoboCommand 状态 |
| `/safe_passage/buoys` | 航门/浮标相关规划输入 | 由 Task1 内部使用，暂不直接转发 |
| `/safe_passage/forward_plan` | 前向规划结果 | 由 Task1 内部使用，暂不直接转发 |
| `/safe_passage/mission_state` | 任务状态 | OCS 重点订阅并转换为车辆报告 |

## 状态映射

| Task1 状态或故障 | OCS 统一状态 |
|---|---|
| `ENTRY_CLOCKWISE_ORBIT` | `RUNNING` |
| `RECOVERY` | `RECOVERY` |
| `TASK_COMPLETE` | `COMPLETE` |
| `COMMAND_TIMEOUT` | `FAULT` |
| `MAVROS_DISCONNECTED` | `FAULT` |

## 暂未确定

- 启动 Task1 的 ROS 2 Topic、Service 或 Action；
- 暂停、取消、终止任务的正式接口；
- `MissionState` 的完整消息类型和字段名；
- OCS 与 Orin 之间采用 ROS 2 DDS、MQTT Bridge 还是 TCP；
- RoboCommand 报告中需要携带哪些 Task1 字段。

在这些信息确认前，OCS 不应直接向内部规划/控制 Topic 发布控制命令。

## 仿真联调顺序

```bash
gz sim -r task1_test.sdf
ros2 launch safe_passage v2_simulation.launch.py enable_realistic_perception:=true
```

然后由 Bridge 订阅 `/safe_passage/mission_state`，先验证状态能被正确读取和转换，再接入 RoboCommand。
