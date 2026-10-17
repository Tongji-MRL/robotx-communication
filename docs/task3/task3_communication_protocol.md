# Task 3 子状态机通信编码表（草案 v0.3）

更新时间：2026-10-11

## 1. 14 位状态码

```text
V TT PPPP EEEE CCC
│ │  │    │    └─ command：子状态机给总规划器的指令，3 bit
│ │  │    └────── error：当前步骤内错误，4 bit
│ │  └─────────── progress：当前任务步骤，4 bit
│ └────────────── task：当前任务，2 bit
└──────────────── vehicle：执行车辆，1 bit
```

普通状态上报必须使用 `command=000`。跨机传输的坐标、颜色序列、bay/window ID、
置信度和 checkpoint 使用结构化 payload，不塞进 14 位状态码。

错误目录版本固定为 `task3-errors-v1`，每条结构化状态消息都必须携带该版本。总规划器
发现本地目录版本与消息版本不一致时，应拒绝自动解释并进入安全保持。

## 2. Vehicle

| 二进制 | 名称 |
|---|---|
| `0` | UAV / T-Sky |
| `1` | USV / T-Wave |

## 3. Task

| 二进制 | 名称 |
|---|---|
| `00` | `NOT_STARTED` |
| `01` | `TASK1` |
| `10` | `TASK3` |
| `11` | `TASK4` |

## 4. Task 3 progress

| 二进制 | 状态 | 主要动作 |
|---|---|---|
| `0000` | `READY` | 已收到 Task3 启动命令，检查配置 |
| `0001` | `WAIT_DOCK_OBSERVATION` | 等待 UAV dock 粗中心 |
| `0010` | `APPROACH_DOCK` | 前往安全圆周/观察点 |
| `0011` | `SEARCH_DOCK` | 沿圆周搜索 dock 入口 |
| `0100` | `CHECK_BAY_COLOR` | 检查 bay 红绿颜色 |
| `0101` | `NEXT_BAY` | 退出当前 bay，搜索下一 bay |
| `0110` | `TERMINAL_DOCKING` | 执行最终靠泊 |
| `0111` | `DOCKED` | 靠泊完成 |
| `1000` | `WAIT_RED_WINDOW` | 等待红色喷水窗口 |
| `1001` | `AIMING` | 云台瞄准窗口 |
| `1010` | `SPRAYING` | 开泵喷水 |
| `1011` | `VERIFY_GREEN` | 停泵并连续确认绿色 5 秒 |
| `1100` | `COLOR_SEQUENCE` | 识别/上报资源色和目标圆色 |
| `1101` | `WAIT_UAV_DELIVERY` | 等待 UAV 接收、抓取和投放 |
| `1110` | `EXIT_RETURN` | 退出 dock 并返航 |
| `1111` | `COMPLETE` | Task3 权威完成结果已产生 |

## 5. 通用 error

这些编号在每一个 progress 步骤中含义相同。

| 二进制 | 错误 | 处理原则 |
|---|---|---|
| `0000` | `NONE` | 无错误 |
| `0001` | `TIMEOUT` | 当前步骤超时，按步骤决定重试/退出 |
| `0010` | `INVALID_INPUT` | 拒绝无效输入 |
| `0011` | `STALE_DATA` | 丢弃过期数据 |
| `0100` | `COMMUNICATION_LOST` | 保持/安全暂停，等待链路恢复 |
| `0101` | `EXECUTION_REJECTED` | 保留当前安全状态并报告原因 |
| `0110` | `DEPENDENCY_UNAVAILABLE` | 等待所需节点、传感器或执行器 |
| `0111` | `UNKNOWN_ERROR` | 进入安全状态并记录完整日志 |

## 6. Task 3 步骤特有 error

步骤特有错误从 `1000` 到 `1111`，每个 progress 重新编号。解码时必须同时读取
`task + progress + error`。以下 16 个步骤的 8 个特有错误位已经全部固定，共 128 项。
不允许在运行时增加错误码；无法归类的故障使用通用 `0111 UNKNOWN_ERROR` 并携带详情。

可供程序或表格软件读取的版本见 [`TASK3_ERROR_CATALOG.csv`](TASK3_ERROR_CATALOG.csv)。

### `0000` `READY`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `RUN_NOT_STARTED` | 是 | 等待输入/依赖恢复 |
| `1001` | `CONFIG_INVALID` | 否 | 终止 Task3 并执行安全退出 |
| `1010` | `RUN_ID_CONFLICT` | 是 | 等待输入/依赖恢复 |
| `1011` | `PREVIOUS_RUN_ACTIVE` | 是 | 等待输入/依赖恢复 |
| `1100` | `CHECKPOINT_LOAD_FAILED` | 否 | 终止 Task3 并执行安全退出 |
| `1101` | `REQUIRED_FRAME_UNDEFINED` | 否 | 终止 Task3 并执行安全退出 |
| `1110` | `SAFETY_CONFIG_INVALID` | 否 | 终止 Task3 并执行安全退出 |
| `1111` | `START_CONDITION_UNMET` | 是 | 等待输入/依赖恢复 |

### `0001` `WAIT_DOCK_OBSERVATION`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `DOCK_OBSERVATION_NOT_FOUND` | 是 | 等待输入/依赖恢复 |
| `1001` | `FRAME_MISMATCH` | 否 | 进入安全保持并等待决策 |
| `1010` | `DOCK_ID_MISMATCH` | 是 | 等待输入/依赖恢复 |
| `1011` | `COORDINATE_CONVERSION_FAILED` | 否 | 进入安全保持并等待决策 |
| `1100` | `OBSERVATION_TIMESTAMP_INVALID` | 是 | 等待输入/依赖恢复 |
| `1101` | `DOCK_CENTER_LOW_CONFIDENCE` | 是 | 等待输入/依赖恢复 |
| `1110` | `DOCK_CENTER_OUT_OF_BOUNDARY` | 是 | 等待输入/依赖恢复 |
| `1111` | `DOCK_CENTER_JUMP_DETECTED` | 是 | 等待输入/依赖恢复 |

### `0010` `APPROACH_DOCK`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `NAV_GOAL_REJECTED` | 是 | 从当前位置重新规划 |
| `1001` | `BOUNDARY_VIOLATION` | 是 | 从当前位置重新规划 |
| `1010` | `OBSTACLE_BLOCKED` | 是 | 从当前位置重新规划 |
| `1011` | `NO_FEASIBLE_SAFETY_RADIUS` | 否 | 进入安全保持并等待决策 |
| `1100` | `START_INSIDE_EXCLUSION_ZONE` | 是 | 从当前位置重新规划 |
| `1101` | `NAV_FEEDBACK_LOST` | 是 | 进入安全保持并等待决策 |
| `1110` | `APPROACH_RETRY_EXHAUSTED` | 否 | 终止 Task3 并执行安全退出 |
| `1111` | `CURRENT_POSE_UNAVAILABLE` | 是 | 进入安全保持并等待决策 |

### `0011` `SEARCH_DOCK`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `LIDAR_NO_DATA` | 是 | 等待输入/依赖恢复 |
| `1001` | `SEARCH_ARC_EXHAUSTED` | 是 | 从当前位置重新规划 |
| `1010` | `NO_ENTRANCE_CANDIDATE` | 是 | 在本步骤限次重试 |
| `1011` | `LIDAR_TRANSFORM_UNAVAILABLE` | 是 | 进入安全保持并等待决策 |
| `1100` | `POINTCLOUD_INVALID` | 是 | 等待输入/依赖恢复 |
| `1101` | `ENTRANCE_ESTIMATE_UNSTABLE` | 是 | 在本步骤限次重试 |
| `1110` | `ALL_ENTRANCES_UNSAFE` | 否 | 进入安全保持并等待决策 |
| `1111` | `SEARCH_ROUTE_BLOCKED` | 是 | 从当前位置重新规划 |

### `0100` `CHECK_BAY_COLOR`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `CAMERA_NO_DATA` | 是 | 等待输入/依赖恢复 |
| `1001` | `COLOR_LOW_CONFIDENCE` | 是 | 在本步骤限次重试 |
| `1010` | `BAY_NOT_SAFE` | 否 | 退出并选择下一 bay |
| `1011` | `BAY_COLOR_UNKNOWN` | 是 | 在本步骤限次重试 |
| `1100` | `BAY_COLOR_CONFLICT` | 是 | 在本步骤限次重试 |
| `1101` | `BAY_OBSERVATION_LOST` | 是 | 重新搜索 dock/入口 |
| `1110` | `BAY_ID_MISMATCH` | 是 | 重新搜索 dock/入口 |
| `1111` | `BAY_CHECK_RETRY_EXHAUSTED` | 否 | 退出并选择下一 bay |

### `0101` `NEXT_BAY`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `NO_MORE_BAYS` | 否 | 终止 Task3 并执行安全退出 |
| `1001` | `SAFE_EXIT_UNAVAILABLE` | 否 | 进入安全保持并等待决策 |
| `1010` | `BAY_EXIT_GOAL_REJECTED` | 是 | 从当前位置重新规划 |
| `1011` | `BAY_EXIT_NOT_CONFIRMED` | 是 | 在本步骤限次重试 |
| `1100` | `REJECTED_BAY_LIST_INVALID` | 是 | 重新搜索 dock/入口 |
| `1101` | `NEXT_BAY_CANDIDATE_INVALID` | 是 | 重新搜索 dock/入口 |
| `1110` | `NON_TARGET_BAY_REENTRY_RISK` | 是 | 从当前位置重新规划 |
| `1111` | `NEXT_BAY_RETRY_EXHAUSTED` | 否 | 终止 Task3 并执行安全退出 |

### `0110` `TERMINAL_DOCKING`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `DOCKING_FAILED` | 是 | 重新搜索 dock/入口 |
| `1001` | `DOCK_NOT_CONFIRMED` | 是 | 重新搜索 dock/入口 |
| `1010` | `TERMINAL_PATH_UNSAFE` | 是 | 从当前位置重新规划 |
| `1011` | `DOCK_ALIGNMENT_LOST` | 是 | 重新搜索 dock/入口 |
| `1100` | `ENTRANCE_POSE_STALE` | 是 | 重新搜索 dock/入口 |
| `1101` | `COLLISION_MARGIN_VIOLATED` | 否 | 进入安全保持并等待决策 |
| `1110` | `DOCKING_CONTROLLER_FEEDBACK_LOST` | 是 | 进入安全保持并等待决策 |
| `1111` | `DOCKING_RETRY_EXHAUSTED` | 否 | 退出并选择下一 bay |

### `0111` `DOCKED`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `DOCK_REPORT_FAILED` | 是 | 在本步骤限次重试 |
| `1001` | `DOCK_POSE_DRIFT` | 是 | 退回安全区并重新接近 |
| `1010` | `DOCK_CONTACT_LOST` | 是 | 退回安全区并重新接近 |
| `1011` | `DOCKED_BAY_MISMATCH` | 是 | 重新搜索 dock/入口 |
| `1100` | `UNSAFE_MOTION_AFTER_DOCK` | 否 | 进入安全保持并等待决策 |
| `1101` | `DOCK_RESULT_CONFLICT` | 否 | 进入安全保持并等待决策 |
| `1110` | `VESSEL_STOP_NOT_CONFIRMED` | 是 | 进入安全保持并等待决策 |
| `1111` | `WATERING_HANDOFF_NOT_READY` | 是 | 等待输入/依赖恢复 |

### `1000` `WAIT_RED_WINDOW`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `WINDOW_NOT_FOUND` | 是 | 在本步骤限次重试 |
| `1001` | `WINDOW_ID_INVALID` | 是 | 在本步骤限次重试 |
| `1010` | `RED_WINDOW_NOT_CONFIRMED` | 是 | 在本步骤限次重试 |
| `1011` | `WINDOW_LOW_CONFIDENCE` | 是 | 在本步骤限次重试 |
| `1100` | `WINDOW_OBSERVATION_LOST` | 是 | 在本步骤限次重试 |
| `1101` | `MULTIPLE_RED_WINDOWS` | 是 | 在本步骤限次重试 |
| `1110` | `WINDOW_UNREACHABLE` | 否 | 退回安全区并重新接近 |
| `1111` | `WINDOW_WAIT_RETRY_EXHAUSTED` | 否 | 终止 Task3 并执行安全退出 |

### `1001` `AIMING`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `GIMBAL_NOT_READY` | 是 | 等待输入/依赖恢复 |
| `1001` | `AIMING_FAILED` | 是 | 在本步骤限次重试 |
| `1010` | `AIM_TARGET_LOST` | 是 | 在本步骤限次重试 |
| `1011` | `GIMBAL_LIMIT_REACHED` | 否 | 退回安全区并重新接近 |
| `1100` | `TARGET_POSE_INVALID` | 是 | 在本步骤限次重试 |
| `1101` | `AIM_ALIGNMENT_TIMEOUT` | 是 | 在本步骤限次重试 |
| `1110` | `GIMBAL_FEEDBACK_LOST` | 是 | 进入安全保持并等待决策 |
| `1111` | `GIMBAL_STABILIZATION_FAILED` | 否 | 退回安全区并重新接近 |

### `1010` `SPRAYING`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `PUMP_START_FAILED` | 是 | 在本步骤限次重试 |
| `1001` | `PUMP_STOP_FAILED` | 否 | 进入安全保持并等待决策 |
| `1010` | `PUMP_FAULT` | 否 | 进入安全保持并等待决策 |
| `1011` | `SPRAY_ALIGNMENT_LOST` | 是 | 进入安全保持并等待决策 |
| `1100` | `SPRAY_TARGET_LOST` | 是 | 进入安全保持并等待决策 |
| `1101` | `MAX_SPRAY_TIME_EXCEEDED` | 否 | 进入安全保持并等待决策 |
| `1110` | `PUMP_STATE_UNKNOWN` | 否 | 进入安全保持并等待决策 |
| `1111` | `SPRAY_EMERGENCY_CUTOFF` | 否 | 终止 Task3 并执行安全退出 |

### `1011` `VERIFY_GREEN`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `GREEN_CONFIRM_INTERRUPTED` | 是 | 在本步骤限次重试 |
| `1001` | `GREEN_CONFIRM_TIMEOUT` | 是 | 在本步骤限次重试 |
| `1010` | `GREEN_NOT_DETECTED` | 是 | 在本步骤限次重试 |
| `1011` | `RED_WINDOW_PERSISTS` | 是 | 在本步骤限次重试 |
| `1100` | `WINDOW_COLOR_UNSTABLE` | 是 | 在本步骤限次重试 |
| `1101` | `WINDOW_OBSERVATION_LOST` | 是 | 在本步骤限次重试 |
| `1110` | `PUMP_STILL_ON` | 否 | 进入安全保持并等待决策 |
| `1111` | `WINDOW_STATE_CONFLICT` | 否 | 进入安全保持并等待决策 |

### `1100` `COLOR_SEQUENCE`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `COLOR_SEQUENCE_INVALID` | 是 | 在本步骤限次重试 |
| `1001` | `COLOR_SEQUENCE_TIMEOUT` | 是 | 在本步骤限次重试 |
| `1010` | `COLOR_SEQUENCE_CONFLICT` | 是 | 在本步骤限次重试 |
| `1011` | `RESOURCE_COLOR_UNKNOWN` | 是 | 在本步骤限次重试 |
| `1100` | `DESTINATION_COLOR_UNKNOWN` | 是 | 在本步骤限次重试 |
| `1101` | `COLOR_SEQUENCE_INCOMPLETE` | 是 | 在本步骤限次重试 |
| `1110` | `COLOR_SEQUENCE_LOW_CONFIDENCE` | 是 | 在本步骤限次重试 |
| `1111` | `COLOR_SEQUENCE_PUBLISH_FAILED` | 是 | 等待输入/依赖恢复 |

### `1101` `WAIT_UAV_DELIVERY`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `UAV_NOT_READY` | 是 | 等待输入/依赖恢复 |
| `1001` | `UAV_ACK_TIMEOUT` | 是 | 等待输入/依赖恢复 |
| `1010` | `UAV_DELIVERY_FAILED` | 是 | 在本步骤限次重试 |
| `1011` | `UAV_STATE_STALE` | 是 | 等待输入/依赖恢复 |
| `1100` | `UAV_REQUEST_REJECTED` | 是 | 等待输入/依赖恢复 |
| `1101` | `UAV_REQUEST_ID_MISMATCH` | 是 | 等待输入/依赖恢复 |
| `1110` | `UAV_DELIVERY_TIMEOUT` | 是 | 在本步骤限次重试 |
| `1111` | `UAV_DELIVERY_RESULT_CONFLICT` | 否 | 进入安全保持并等待决策 |

### `1110` `EXIT_RETURN`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `RETURN_GOAL_REJECTED` | 是 | 从当前位置重新规划 |
| `1001` | `RETURN_PATH_BLOCKED` | 是 | 从当前位置重新规划 |
| `1010` | `DOCK_EXIT_FAILED` | 是 | 在本步骤限次重试 |
| `1011` | `RETURN_BOUNDARY_VIOLATION` | 是 | 从当前位置重新规划 |
| `1100` | `RETURN_CONTROLLER_FEEDBACK_LOST` | 是 | 进入安全保持并等待决策 |
| `1101` | `RETURN_POSE_UNAVAILABLE` | 是 | 进入安全保持并等待决策 |
| `1110` | `RETURN_RETRY_EXHAUSTED` | 否 | 终止 Task3 并执行安全退出 |
| `1111` | `SAFE_HOLD_FAILED` | 否 | 终止 Task3 并执行安全退出 |

### `1111` `COMPLETE`

| Error | 固定错误名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `1000` | `TASK3_REPORT_FAILED` | 是 | 在本步骤限次重试 |
| `1001` | `PLANNER_ACK_TIMEOUT` | 是 | 在本步骤限次重试 |
| `1010` | `FINAL_RESULT_INCOMPLETE` | 是 | 等待输入/依赖恢复 |
| `1011` | `FINAL_RESULT_INCONSISTENT` | 否 | 进入安全保持并等待决策 |
| `1100` | `CHECKPOINT_CLEANUP_FAILED` | 否 | 进入安全保持并等待决策 |
| `1101` | `DUPLICATE_COMPLETION_CONFLICT` | 否 | 进入安全保持并等待决策 |
| `1110` | `COLOR_SEQUENCE_NOT_DELIVERED` | 是 | 等待输入/依赖恢复 |
| `1111` | `COMPLETION_REJECTED` | 是 | 等待输入/依赖恢复 |

### 未预见错误规则

表内无法归类的故障统一使用通用 `0111 UNKNOWN_ERROR`，并附带：

```json
{
  "fault": {
    "name": "UNKNOWN_ERROR",
    "source": "产生错误的模块",
    "detail_code": "模块内部错误标识",
    "detail": "完整原因",
    "retry_count": 0,
    "retryable": false,
    "recovery_action": "SAFE_HOLD"
  }
}
```
## 7. Command：子状态机 → 总规划器

| 二进制 | 名称 | 用途 |
|---|---|---|
| `000` | `NONE` | 普通状态上报默认值 |
| `001` | `ACK` | 接受/拒绝总规划器命令，详细结果在 payload |
| `010` | `REQUEST_PAUSE` | 请求总规划器暂停任务 |
| `011` | `REQUEST_RESUME` | 请求总规划器批准恢复 |
| `100` | `REPORT_TASK_COMPLETE` | 报告当前 task 已完成 |
| `101` | `REPORT_TASK_FAILED` | 报告当前 task 最终失败 |
| `110` | `REQUEST_SAFE_HOLD` | 请求整船进入安全保持 |
| `111` | `REQUEST_ABORT` | 请求终止当前任务并执行退出策略 |

示例：USV 正常搜索 dock 入口：

```text
1 10 0011 0000 000
```

示例：搜索阶段 LiDAR 无数据，普通故障上报不要求总规划器执行新命令：

```text
1 10 0011 1000 000
```

示例：USV 到达 Task4 指定位置，通知总规划器 Task4 已完成：

```text
1 11 0010 0000 100
```

## 8. 总规划器 → Task 3 子状态机输入

这些输入使用结构化消息；14 位 status 是子状态机输出，不承担完整命令参数。

| 输入命令 | 必需 payload | 子状态机行为 |
|---|---|---|
| `START_TASK3` | `run_id`、Task3 配置 | 初始化 Task3，返回 `ACK` |
| `PAUSE_TASK3` | `command_id`、原因 | 安全暂停并生成 checkpoint |
| `TASK4_GOTO` | `target_position` | 保存 Task3 checkpoint，停止当前动作，执行 Task4 导航 |
| `RESUME_TASK3` | `checkpoint_id` | 校验 Task4 已完成后按恢复策略继续 |
| `SAFE_STOP` | 原因 | 取消导航、关泵、停止云台跟踪 |
| `RESET` | 新一轮授权信息 | 清理上一轮运行状态 |

最小命令格式：

```json
{
  "command_id": "task4-17",
  "run_id": 42,
  "command": "TASK4_GOTO",
  "payload": {
    "target_position": {
      "frame_id": "wgs84",
      "latitude": 1.2805,
      "longitude": 103.8558
    }
  }
}
```

## 9. Task 3 子状态机 → 总规划器输出

| 输出 | 14 位 command | 结构化 payload |
|---|---|---|
| `TASK3_PROGRESS` | `000` | 可选 detail、测量值、retry_count |
| `TASK3_START_ACK` | `001` | accepted、拒绝原因 |
| `TASK3_PAUSE_ACK` | `001` | safe_paused、checkpoint、safe_actions |
| `TASK4_GOTO_ACK` | `001` | target_position、checkpoint、safe_actions |
| `TASK4_TARGET_REACHED` | `100` | actual_position、checkpoint_id |
| `TASK3_RESUME_ACK` | `001` | saved_step、resume_step、resume_policy |
| `TASK3_COLOR_SEQUENCE` | `000` | resource_color、destination_color、confidence、valid |
| `TASK3_COMPLETE` | `100` | bay/window/颜色/UAV 结果 |
| `TASK3_FAILED` | `101` | 最终错误、detail、checkpoint |

## 10. Task4 抢占后的 Task3 恢复规则

Task4 定义为前往总规划器给出的指定位置。子状态机必须先安全暂停并保存 checkpoint；
到达后用 `TASK4_TARGET_REACHED + REPORT_TASK_COMPLETE` 通知总规划器，并停留在
`TASK4/WAIT_RESUME`，不得自行恢复原任务。

总规划器收到 Task4 完成报告后，根据全局任务安排选择继续 Task1 或 Task3：

- 选择 Task1：总规划器向 Task1 子状态机下发相应继续命令；Task3 保持暂停并保留 checkpoint。
- 选择 Task3：总规划器向本子状态机下发 `RESUME_TASK3(checkpoint_id)`；Task3 校验
  `run_id/checkpoint_id` 后，才按照下表恢复。
- 未收到明确选择：Task3 一直保持 `WAIT_RESUME`，不能因超时自行开船、靠泊或喷水。

| Task4 到来时的 Task3 状态 | 保存内容 | Task4 完成后恢复状态 | 恢复策略 |
|---|---|---|---|
| `READY` | 配置 | `READY` | 原步骤继续 |
| `WAIT_DOCK_OBSERVATION` | dock ID/版本 | `WAIT_DOCK_OBSERVATION` | 等待新鲜 UAV 数据 |
| `APPROACH_DOCK` | dock 粗中心、目标 | `APPROACH_DOCK` | 用当前位置重新规划 approach |
| `SEARCH_DOCK` | dock、已检查 bay、arc index | `APPROACH_DOCK` | Task4 改变了船位，重新进入安全圆周 |
| `CHECK_BAY_COLOR` | 当前 bay、入口候选 | `SEARCH_DOCK` | 原颜色/入口可能过期，重新观察 |
| `NEXT_BAY` | 已拒绝 bay 列表 | `SEARCH_DOCK` | 重新定位剩余 bay |
| `TERMINAL_DOCKING` | 当前 bay、入口 | `SEARCH_DOCK` | 不继续旧靠泊轨迹，重新观察 |
| `DOCKED` | bay ID | `APPROACH_DOCK` | Task4 已离开 dock，必须重新靠泊 |
| `WAIT_RED_WINDOW` | bay/window 上下文 | `APPROACH_DOCK` | 重新靠泊并重新找窗口 |
| `AIMING` | bay/window | `APPROACH_DOCK` | 停止云台跟踪，重新靠泊 |
| `SPRAYING` | bay/window | `APPROACH_DOCK` | 立即关泵；重新靠泊并重置喷水确认 |
| `VERIFY_GREEN` | 已确认绿色时长 | `APPROACH_DOCK` | 保持停泵；重新靠泊并重新确认 5 秒 |
| `COLOR_SEQUENCE` | 已识别颜色和时间戳 | `COLOR_SEQUENCE` | 只接受仍在有效期内的新鲜序列 |
| `WAIT_UAV_DELIVERY` | request ID、UAV 状态 | `WAIT_UAV_DELIVERY` | 先向 UAV 查询最新投放状态 |
| `EXIT_RETURN` | 返航目标 | `EXIT_RETURN` | 用当前位置重新规划返航 |
| `COMPLETE` | 完成报告 | `COMPLETE` | 不重复执行 Task3 |

Task4 checkpoint 至少包含：

```text
checkpoint_id
run_id
saved_step
resume_step
resume_policy
saved_at_unix_ms
Task3 context
safe_actions
```

## 11. 跨机 Task3 数据

颜色序列等任务数据使用结构化 payload，并通过 `message_id/run_id/sequence` 去重：

```json
{
  "message_type": "TASK3_COLOR_SEQUENCE",
  "run_id": 42,
  "sequence": 18,
  "status_bits": "1 10 1100 0000 000",
  "payload": {
    "resource_color": "RED",
    "destination_color": "BLUE",
    "confidence": 0.91,
    "valid": true
  }
}
```

除颜色序列外，结构化 payload 还用于 dock 粗中心、入口 pose、bay ID、window ID、
Task4 目标、实际到达位置、checkpoint 和 UAV 投放结果。

## 12. ROS 2 实际对接

ROS 2 Topic、正确泊位输入、喷水窗口完成门控、UAV/USV heartbeat、命令 ACK 和 dry-run
启动方式已经冻结在 [`TASK3_ROS_INTERFACE.md`](TASK3_ROS_INTERFACE.md)。

`task3_communication_adapter` 只做协议校验和消息转发，不直接操作车辆或执行器。
