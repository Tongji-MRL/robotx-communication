# Task 3 完整错误码目录（冻结版草案）

更新时间：2026-10-11

目录版本：`task3-errors-v1`

解码键是 `task + progress + error`。`0000～0111` 为所有步骤共用；
`1000～1111` 在每个 Task3 步骤中重新编号。本表已经占满每个步骤的 8 个特有错误位，
总规划器不得按 `error` 单独解码，也不得在运行时接受表外新错误码。

无法归入本表的新故障统一编码为 `0111 UNKNOWN_ERROR`，子状态机必须在结构化 payload 中
提供 `source/detail_code/detail/retry_count`；总规划器按 `SAFE_HOLD` 处理并保存原始详情。

## 通用错误（任意 progress）

| Error | 名称 | 可重试 | 总规划器默认动作 |
|---|---|---|---|
| `0000` | `NONE` | 否 | 无需动作 |
| `0001` | `TIMEOUT` | 是 | 在本步骤限次重试 |
| `0010` | `INVALID_INPUT` | 是 | 等待输入/依赖恢复 |
| `0011` | `STALE_DATA` | 是 | 等待输入/依赖恢复 |
| `0100` | `COMMUNICATION_LOST` | 是 | 进入安全保持并等待决策 |
| `0101` | `EXECUTION_REJECTED` | 是 | 等待输入/依赖恢复 |
| `0110` | `DEPENDENCY_UNAVAILABLE` | 是 | 等待输入/依赖恢复 |
| `0111` | `UNKNOWN_ERROR` | 否 | 进入安全保持并等待决策 |

## `0000` `READY`

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

## `0001` `WAIT_DOCK_OBSERVATION`

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

## `0010` `APPROACH_DOCK`

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

## `0011` `SEARCH_DOCK`

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

## `0100` `CHECK_BAY_COLOR`

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

## `0101` `NEXT_BAY`

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

## `0110` `TERMINAL_DOCKING`

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

## `0111` `DOCKED`

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

## `1000` `WAIT_RED_WINDOW`

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

## `1001` `AIMING`

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

## `1010` `SPRAYING`

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

## `1011` `VERIFY_GREEN`

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

## `1100` `COLOR_SEQUENCE`

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

## `1101` `WAIT_UAV_DELIVERY`

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

## `1110` `EXIT_RETURN`

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

## `1111` `COMPLETE`

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

## 未预见错误 payload

```json
{
  "status_bits": "1 10 0011 0111 000",
  "payload": {
    "fault": {
      "name": "UNKNOWN_ERROR",
      "source": "dock_detector",
      "detail_code": "EXCEPTION",
      "detail": "unexpected detector exception",
      "retry_count": 0,
      "retryable": false,
      "recovery_action": "SAFE_HOLD"
    }
  }
}
```

总规划器只依据固定的 `name/recovery_action` 分支；`detail_code/detail` 用于日志、排障和赛后更新协议。
