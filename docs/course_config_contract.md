# Course 配置下发接口（v1，冻结）

状态：**v1 冻结**。Course 是运行前的只读配置，绝不是任务命令。

| 边界 | Topic | QoS / retain | 数据 |
| --- | --- | --- | --- |
| 官方 → OCS | `robocommand/robotx/course` | 官方定义 | `RxCourse` Protobuf |
| OCS → T-Wave | `tongji/robotx/v1/T-Wave/course_config` | QoS 1 / retained | 内部 JSON envelope，`kind=course_config`、`source=ocs`、`run_id=null` |
| T-Wave bridge → FSM | `/tongji_mrl/mission/course_config` | Reliable、Transient Local、depth=1 | `std_msgs/msg/String`，payload JSON |

payload 的固定 `schema_version` 为 `twave-course-config-v1`：

```json
{"schema_version":"twave-course-config-v1","course_id":"RX2026-A","pinger_freq_hz":27000,"corners":[{"latitude":1.0,"longitude":2.0},{"latitude":1.0,"longitude":3.0},{"latitude":2.0,"longitude":3.0},{"latitude":1.0,"longitude":2.0}],"source_sent_at":"2026-10-17T03:00:00Z","timestamp":"2026-10-17T03:00:01Z"}
```

`source_sent_at` 保留官方 `RxCourse.sent_at`；官方没有该字段时为 `null`，OCS 不会捏造。`timestamp` 是 OCS 生成/同步 envelope 时的 UTC 时间。OCS 校验非空 Course ID、1–1,000,000 Hz 整数频率、有限且合法的经纬度、闭合三顶点以上的零面积/自交均拒绝的多边形。

OCS 对相同 Course 内容幂等，不重复发布；启动/内部 MQTT 重连时重发当前有效 Course。MQTT retained 只保存最后一个有效配置。桥仅接受来自 `ocs`、`run_id=null` 的 T-Wave course_config；重复内容不再 ROS 发布，较旧 `source_sent_at` 被拒绝。同一 Course ID 在已接收无官方发送时间的 Course 后，不接受无法排序的改动。FSM 订阅端必须使用与发布端兼容的 Reliable + Transient Local QoS。

## RunStart 安全界限

顺序为 `RxCourse → MQTT/bridge 校验并发布 → RunStart`。本仓库当前没有 FSM 的“已解析并应用 Course”回执接口：MQTT QoS 1 成功或 ROS 发布成功**不代表 FSM 已应用**，也不能用不同 ROS topic 的时序推断。OCS 继续只要求收到有效 Course 才转发 RunStart；部署前 FSM 负责人必须提供/确认配置就绪状态或 ACK，并由 RunStart 闸门使用它。Course 在运行中更新只会作为配置 topic 数据发布，桥不会启动 Task1/3/4、发送执行器控制或重置状态机。
