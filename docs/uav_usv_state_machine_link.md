# UAV ↔ USV 状态机通信参考

## 1. 边界

这套协议只服务 T-Sky 与 T-Wave 的任务状态机，不属于官方 RoboCommand，也不由 OCS
解释任务含义。它可以与 OCS 内部 MQTT 共用 Broker，但使用独立 Topic 根路径：

```text
tongji/robotx/fsm/v1/<source_vehicle_id>/<target_vehicle_id>/<kind>
```

`kind` 只有：`status`、`event`、`command`、`ack`。

OCS 不订阅这组 Topic。USV 是任务协调器；UAV 执行 USV 明确发出的任务级命令并返回
状态、事件和 ACK。

## 2. Envelope

```json
{
  "protocol_version": "1",
  "message_id": "uuid",
  "sent_at_unix_ms": 0,
  "run_id": 42,
  "sequence": 1,
  "source_vehicle_id": "T-Wave",
  "target_vehicle_id": "T-Sky",
  "kind": "command",
  "task": "TASK3",
  "message_type": "TASK3_DELIVERY_REQUEST",
  "correlation_id": null,
  "payload": {}
}
```

要求：

- `sequence` 按发送车辆单调递增；
- `message_id` 全局唯一，用于去重；
- `run_id` 必须与当前官方 run 一致；
- ACK 的 `correlation_id` 和 `payload.in_reply_to` 必须等于原消息 ID；
- Topic 中的 source、target、kind 必须与 envelope 完全一致；
- 原始图像、点云、PX4 setpoint 和执行器命令不进入此协议。
- `examples/` 中的 `null` 坐标是待替换占位符；未知位置必须显式为 `null`，不能用
  `(0, 0)` 冒充真实数据。

## 3. 建议消息

| 方向 | kind | message_type | 最小内容 |
|---|---|---|---|
| UAV → USV | `status` | `VEHICLE_STATUS` | 模式、当前 task、phase、health |
| UAV → USV | `event` | `TASK1_MAP_UPDATE` | 坐标系、版本、入口/出口、浮标摘要 |
| UAV → USV | `event` | `TASK1_SCAN_COMPLETE` | 扫描结果版本、成功/失败原因 |
| UAV → USV | `event` | `TASK3_DOCK_OBSERVATION` | dock/平台观测、坐标系、置信度 |
| UAV → USV | `event` | `TASK3_DELIVERY_STATE` | 起飞、抓取、投放、完成/失败 |
| USV → UAV | `command` | `RUN_START` | `run_id`、任务许可 |
| USV → UAV | `command` | `TASK3_DELIVERY_REQUEST` | 资源颜色、投放圆颜色、目标位置 |
| USV → UAV | `command` | `TASK4_PAUSE` | 原因、checkpoint 请求 |
| USV → UAV | `command` | `TASK4_RESUME` | resume token、checkpoint |
| USV → UAV | `command` | `SAFE_STOP` | 原因、停止模式 |
| 双向 | `ack` | `ACK` | 原消息 ID、接受/拒绝、原因 |

字段仍需由 UAV/USV 负责人根据真实状态机接口共同确认；确认前先使用 `payload` 中的
版本字段和明确坐标系，不能用位置为 0 代表未知。

## 4. 代码使用方式

纯协议：

```python
from fsm_protocol import make_message, encode

message = make_message(
    "T-Wave",
    "T-Sky",
    "command",
    task="TASK3",
    message_type="TASK3_DELIVERY_REQUEST",
    payload={"resource_color": "RED", "delivery_circle_color": "BLUE"},
    sequence=1,
    run_id=42,
)
wire_bytes = encode(message)
```

MQTT 骨架：

```python
from fsm_link import StateMachineLink

def handle_message(message):
    # 状态机负责人在这里映射到自己的 ROS 2 service/action/topic。
    return True, "accepted by local task state machine"

link = StateMachineLink(
    "T-Wave",
    "<internal-broker-ip>",
    message_handler=handle_message,
)
link.connect()
```

`fsm_link.py` 不直接控制任何执行器。所有 `command` 都会根据 handler 返回值自动生成
ACK；重复 `message_id` 会被忽略。

## 5. 责任边界

| 工作 | 负责人 |
|---|---|
| Topic、JSON envelope、校验、去重、ACK、测试工具 | 通信/OCS 负责人 |
| UAV ROS 2 状态 → `status/event` payload | UAV 状态机负责人 |
| `command` payload → UAV ROS 2 action/service | UAV 状态机负责人 |
| USV ROS 2 状态与任务仲裁 → `status/event/command` | USV 状态机负责人 |
| Task4 抢占、checkpoint、恢复和 UAV 协调策略 | USV 状态机负责人 |
| 四机联调、故障注入、日志核对 | 三方共同完成 |

通信负责人提供骨架和验收测试，但不能替状态机负责人猜测真实 ROS 2 Topic、消息类型、
任务完成条件或安全动作。
