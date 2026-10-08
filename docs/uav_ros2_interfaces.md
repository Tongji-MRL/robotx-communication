# UAV ROS 2 接口清单与待补契约

更新时间：2026-10-08

## 1. 使用范围

本文件记录 UAV-Orin 只读审计中发现的 ROS 2 Topic、消息类型、当前可用程度，以及
OCS/USV 状态机需要但 UAV 状态机尚未提供的接口。它是通信适配依据，不代表这些节点
已经在线，也不授权启动 PX4 offboard、夹爪、飞行任务或其他执行器。

责任边界：

- 通信/OCS 负责人维护 MQTT Topic、JSON envelope、转换骨架、校验和联调测试；
- UAV 状态机负责人确认并实现任务命令、统一状态、ACK、Task1/3 结果和安全接口；
- PX4 模式映射、飞行完成条件、急停和执行器安全动作由 UAV/飞控负责人定义；
- OCS 和 USV 不根据检测目标、单个 PX4 ACK 或进程退出猜测 UAV 任务完成。

## 2. 审计结论

审计时 UAV-Orin 为 ROS 2 Humble。运行图中只有 Oak 相机、IMU、TF、诊断和视频节点；
没有任务节点、`/fmu/*` Topic、任务 service/action 或飞控节点在线，action 清单为空。
因此当前模式、Task、phase、GPS、速度、姿态、飞控故障和任务健康均无法从现场确认。

原始 ROS 图保存在远端 `/tmp/orin_ros2_audit_20261008/`，不提交设备序列号或未脱敏
日志。相机/IMU/diagnostics 的短窗频率结果存在丢包且明显不适合作为生产配置依据，必须
由负责人重新测量。

状态说明：

- **在线确认**：审计时运行图存在并取得只读样例；
- **源码候选**：找到 publisher/subscriber 和字段，但未在运行图验证；
- **实验实现**：旧或独立试验包，不能作为生产状态机接口；
- **占位/缺失**：只有注释骨架，或没有找到所需接口。

## 3. 当前在线接口

| Topic | 类型/方向 | 现场结论 |
|---|---|---|
| `/diagnostics` | `diagnostic_msgs/msg/DiagnosticArray`，Oak → 外部 | 在线；样例仅为 Oak `sys_logger`，不是飞控或整机健康 |
| `/oak/imu/data` | IMU 数据，Oak → 外部 | 在线；不能替代 PX4 vehicle attitude 或任务状态 |
| `/oak/rgb/image_raw` | 图像，Oak → perception | 在线；只有相机链路，不代表感知或任务节点已运行 |
| `/tf`、`/tf_static` | TF | 在线；未证明任务坐标系链完整 |

没有在线的 `/fmu/*`、Task1、Task3、Task4、夹爪、任务命令或任务结果接口。

## 4. PX4 状态与安全候选接口

下列 Topic 在源码或已安装的 `px4_msgs` 中被引用，但审计时未在线：

| Topic | 类型 | 字段/单位 | 当前判断 |
|---|---|---|---|
| `/fmu/out/vehicle_status_v1` | `px4_msgs/msg/VehicleStatus` | arming/nav state、failsafe、failure status | 源码候选；没有统一 AUTO/MANUAL/KILLED 映射 |
| `/fmu/out/vehicle_local_position_v1` | `px4_msgs/msg/VehicleLocalPosition` | NED 位置（米）、速度（米/秒）、heading（弧度） | 源码候选，未在线 |
| `/fmu/out/vehicle_attitude` | `px4_msgs/msg/VehicleAttitude` | 四元数 | 源码没有统一 roll/pitch 输出 |
| `/fmu/out/battery_status_v1` | `px4_msgs/msg/BatteryStatus` | 电池状态 | 源码候选，未在线 |
| `/fmu/out/vehicle_land_detected` | `px4_msgs/msg/VehicleLandDetected` | 着陆状态 | 源码候选，未在线 |
| `/fmu/out/vehicle_command_ack` | `px4_msgs/msg/VehicleCommandAck` | PX4 命令确认 | 不是 USV/OCS 任务命令 ACK |
| `/robotx/uav/safety_report` | `std_msgs/msg/String` JSON | safe、reason、checks、遥测新鲜度、failsafe、故障、电池 | safety monitor 源码候选，10 Hz 检查；未在线 |

源码中 `/fmu/in/offboard_control_mode`、`trajectory_setpoint` 和 `vehicle_command` 会影响
真实飞行，禁止通信适配器直接发布。生产适配器只连接 UAV 状态机明确批准的任务级接口。

## 5. Task1 地图候选接口

| Topic | 类型/方向 | 内容 | 当前判断 |
|---|---|---|---|
| `/robotx/map/command` | `std_msgs/msg/String` JSON，外部 → map manager | 只接受 `{"command":"begin"}` | 源码候选；不是通用 `RUN_START`，发布后可能推进飞行，禁止联调时直接发送 |
| `/map/perception/detections` | `std_msgs/msg/String` JSON，map manager → 外部 | 感知检测 | 源码候选，未在线 |
| `/map/perception/ned_targets` | `std_msgs/msg/String` JSON，map manager → 外部 | NED 目标 | 源码候选，未在线 |
| `/task1/progress` | `std_msgs/msg/String` JSON，map manager → 外部 | 完成时一次性发布 `task=map/state=complete/message` | 缺失败事件、入口/出口、浮标/门权威结果 |

当前地图配置只有 `tin` 模型有效，buoy/dock 等配置仍是注释项。没有找到 UAV Task1
入口、出口、浮标/门结果、扫描完成/失败的生产 Topic，因此不能生成官方 Task1 报告。

## 6. Task3 实验候选接口

以下接口来自旧的 Task3 UAV offboard/视觉实验包，当前没有运行，不能当作生产接口：

| Topic | 类型/方向 | 内容 | 边界 |
|---|---|---|---|
| `/task3/perception/detections` | `std_msgs/msg/String` JSON，检测 → delivery | 图像尺寸、状态、目标颜色、检测框和深度 | 像素/深度不是 NED；针对平台、supply can、circle |
| `/task3/rule_based/state` | `std_msgs/msg/String` JSON，delivery → 外部 | 搜索、抓取、投放、`COMPLETE/FAILED` 等状态 | 实验状态机，未接 USV 通用命令 |
| `/task3/rule_based/events` | `std_msgs/msg/String` JSON，delivery → 外部 | 状态转换事件 | 未在线，完成判据未由负责人确认 |
| `/task3/gripper/command` | `std_msgs/msg/String` JSON，delivery → 夹爪 | open/close | 未找到订阅者/生产夹爪适配器；禁止发布 |
| `/task3/autonomous/target_observation` | `std_msgs/msg/String` JSON | 目标观察 | 实验实现，未在线 |
| `/task3/autonomous/target_map` | `std_msgs/msg/String` JSON | `px4_local_ned` 目标地图 | 实验实现，未在线 |
| `/task3/autonomous/detection_control` | `std_msgs/msg/String` JSON | ignore track 等检测控制 | 不是任务 pause/checkpoint |
| `/task3/autonomous/mission_state` | `std_msgs/msg/String` JSON | 实验任务状态 | 没有统一 TASK1/3/4 枚举 |
| `/task3/autonomous/mission_events` | `std_msgs/msg/String` JSON | 实验任务事件 | 没有正式 command correlation/ACK |

`robotx_task1/3/4` manager 和 `robotx_interfaces` 的消息、service、action 文件目前是注释
占位，相关包/接口没有形成可用生产入口。源码中也没有 MQTT client/bridge。

## 7. OCS/USV 内部协议映射边界

| 团队消息 | UAV ROS 2 候选来源/去向 | 当前判断 |
|---|---|---|
| UAV `heartbeat` → OCS | PX4 status/local position/attitude/battery + safety report | 候选数据存在，统一模式、GPS、高度、姿态和 2 Hz 输出未实现 |
| UAV `task_report` → OCS | Task1 progress、Task3 authoritative event | 当前只有不完整或实验字段，不能直接发布官方报告 |
| UAV `fault` → OCS | safety report + PX4 failsafe/故障/超时 | 统一故障 schema 和运行样例缺失 |
| USV `command` → UAV | 尚无通用 UAV 状态机命令 Topic/service/action | 缺失；`map begin` 不能替代 |
| UAV `ack` → USV | 尚无正式任务命令 ACK | 缺失；PX4 command ACK 不能替代 |
| UAV → USV Task1 map | detections/NED targets 可作候选来源 | 缺入口/出口、浮标/门、版本、坐标系确认和完成/失败事件 |
| UAV ↔ USV Task3 | 实验 delivery state/事件可作字段参考 | 未接通 USV 命令，夹爪/投放执行反馈不完整 |

通信适配器不得自行把 `nav_state`、检测目标、PX4 ACK、`COMPLETE` 字符串或进程退出
转换成权威任务结果，除非 UAV/飞控负责人冻结映射和完成判据。

## 8. 由 UAV 状态机负责人补齐

| 缺口 | 最低要求 |
|---|---|
| 通用命令入口 | 接收 USV 的 `RUN_START`/Task1/Task3/Task4 协调/暂停/恢复/`SAFE_STOP`，携带 `run_id` 和消息关联 ID |
| 正式 ACK | 明确 ROS 2 Topic/service/action；字段至少含 `run_id/message_id/accepted/state/detail/time` |
| 统一车辆状态 | AUTO/MANUAL/KILLED、current task、phase、GPS/HAE、速度、航向、roll/pitch、flight phase、健康和失联 |
| Task1 authoritative result | 地图版本、坐标系、入口、出口、浮标/门、扫描完成/失败及证据 |
| Task3 authoritative state | 起飞、搜索、抓取、投放、完成/失败，以及夹爪/投放真实执行反馈 |
| Task4 协调 | 定义被 USV 抢占时的安全动作、checkpoint、恢复条件和失败处理 |
| `SAFE_STOP`/急停 | 区分任务级停止、返航/降落和独立硬件/飞控急停；提供确认与恢复流程 |
| 模式映射 | 明确 PX4 arming/nav/failsafe 到官方状态的映射，不把 disarm/kill/failsafe 混为一类 |

这些接口由 UAV 状态机/飞控负责人实现和维护。通信/OCS 负责人在接口冻结后完成
MQTT↔ROS 2 转换、schema 校验和端到端测试，不修改飞行完成条件或安全动作。

## 9. 接口交付验收

UAV 状态机接口交付时，每个 Topic/service/action 必须同时提供：

- 完整名称和 ROS 2 类型；
- publisher/subscriber 节点；
- 字段单位、坐标系和时间基准；
- QoS、频率、启动命令、正常停止和真实急停方式；
- 一条不连接真实执行器的 dry-run 样例；
- 重复命令、旧 `run_id`、超时、失联、Task4 抢占和故障行为；
- 对应自动测试和验证日志。

完成这些项目之前，UAV 生产适配器状态保持“未完成”。
