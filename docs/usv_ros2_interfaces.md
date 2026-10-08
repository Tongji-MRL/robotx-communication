# USV ROS 2 接口清单与待补契约

更新时间：2026-10-08

## 1. 使用范围

本文件记录 USV-Orin 只读审计中发现的 ROS 2 Topic、消息类型、当前可用程度，以及
OCS/团队内部协议需要但状态机尚未提供的接口。它是通信适配依据，不代表这些节点已经
在线，也不授权启动推进器、泵、云台、PX4 或真实任务。

责任边界：

- 通信/OCS 负责人维护 MQTT Topic、JSON envelope、转换骨架、校验和联调测试；
- USV 状态机负责人确认并实现 ROS 2 命令、状态、ACK、Task4 抢占/恢复和安全接口；
- 感知或执行器 Topic 只有在对应车辆负责人给出完成判据后，才能映射成官方报告；
- OCS 不根据超时、感知目标出现或单个 `phase` 字段猜测任务完成。

## 2. 审计结论

审计时 USV-Orin 为 ROS 2 Humble，工作区 overlay 未加载。运行图中只有 Oak 相机、IMU、
TF、诊断和视频节点；没有飞控、GPS、任务状态机、Task1/3/4、泵或云台节点在线，action
清单为空。因此下表多数为“源码已定义、运行未验证”，不能当作现场 Topic 已连通。

远端生成的原始清单为 `orin_ros2_inventory_20261008.txt`。该运行日志保留在 USV-Orin，
不提交设备序列号或未经脱敏的整机日志。

状态说明：

- **源码定义**：找到 publisher/subscriber 和消息结构，但未在运行图验证；
- **占位**：Topic 存在，但任务逻辑明确未实现；
- **缺失**：通信主链路需要，但没有找到可用接口。

## 3. USV 任务协调器接口

| Topic | 类型和方向 | QoS/频率 | 当前内容 | 状态 |
|---|---|---|---|---|
| `/tongji_mrl/twave/task_cmd` | `std_msgs/msg/String`，外部 → `/usv_mission_state_machine` | depth 10，事件触发 | JSON：`task_id` 为 1/3/4；`action` 支持 `execute_task`、`start_task_execution`、`pause_task` | 源码定义，未在线 |
| `/tongji_mrl/twave/state` | `std_msgs/msg/String`，状态机 → 外部 | depth 10，状态变化 | JSON：`event/state/task_id/executor` | 源码定义，未在线 |
| `/tongji_mrl/twave/heartbeat` | `std_msgs/msg/String`，状态机 → 外部 | depth 10，1 Hz | JSON：`state/task_id`；不是完整车辆健康状态 | 源码定义，未在线 |
| `/tongji_mrl/twave/task_report` | `std_msgs/msg/String`，状态机 → 外部 | depth 10，事件触发 | JSON：`event/task_id/executor/detail`；不是正式命令 ACK | 源码定义，未在线 |
| `/tongji_mrl/twave/task1/state` | `std_msgs/msg/String`，Task1 executor → 外部 | depth 10，1 Hz | `TASK1_PLACEHOLDER`、`ready_for_task_logic:false` | 占位 |
| `/tongji_mrl/twave/task3/state` | `std_msgs/msg/String`，Task3 executor → 外部 | depth 10，1 Hz | `state/ready_for_task_logic/position_received/position_valid/position_ned_m/frame_id/dry_run` | 部分实现，控制闭环未完成 |
| `/tongji_mrl/twave/task4/state` | `std_msgs/msg/String`，Task4 executor → 外部 | depth 10，1 Hz | `TASK4_PLACEHOLDER`、`ready_for_task_logic:false` | 占位 |

当前 `/task_cmd` 不是完整 OCS 命令接口：没有 `run_id`、`command_seq`、`RUN_START`、
整船 `SAFE_STOP`、正式接受/拒绝 ACK，也没有 checkpoint 保存和恢复。`pause_task` 会停止
执行器进程组并标记 `PAUSED`；Task4 激活会覆盖原活动任务，但没有可靠恢复原 Task 的实现。

## 4. 位置和任务数据接口

| Topic | 类型和方向 | 内容/单位 | 当前状态 |
|---|---|---|---|
| `/fix` | `sensor_msgs/msg/NavSatFix`，GPS → shared position | WGS84 纬经度（度）、高度（米）、协方差 | 未在线，无真实样例 |
| `/tongji_mrl/twave/ned_position` | `std_msgs/msg/String`，shared position → 任务节点 | JSON：N/E/D（米）、GPS 源、时间戳、sequence、frame | 源码 10 Hz；参考点未配置，默认不能输出有效位置 |
| `/tongji_mrl/twave/shared_position/status` | `std_msgs/msg/String`，shared position → 外部 | `status/frame_id`；含等待 GPS、过期、无效等状态 | 源码定义，未在线 |
| `/safe_passage/mission_state` | `safe_passage/msg/MissionState`，Task1 原型 → 外部 | stage、已通过/当前 gate、恢复次数、reason | 独立原型，未在线；不是完整 Task1 结果 |
| `/tongji_mrl/twave/task3/coarse_dock` | `std_msgs/msg/String`，感知 → Task3 executor | JSON，NED 米制粗定位 | 源码定义，未在线 |
| `/tongji_mrl/twave/task3/dock_perception` | `std_msgs/msg/String`，感知 → Task3 executor | NED、`entrance_heading_rad`、confidence、时间戳、current pose | 源码定义，未在线 |
| `/tongji_mrl/twave/task3/approach_reached` | `std_msgs/msg/Empty`，导航 → Task3 executor | 到达 approach 点事件 | 未找到在线发布者 |

Task3 状态枚举包含 `IDLE`、`APPROACH_DOCK`、`SEARCH_DOCK`、`CHECK_BAY_COLOR`、
`NEXT_BAY`、`TERMINAL_DOCKING`、`DOCKED`、`WATERING`、`FINISHED`、`ERROR`，但
docking、颜色、泵和 PX4 接口仍有 TODO；枚举存在不等于真实完成闭环。

## 5. Task3 感知与执行器候选接口

这些 Topic 在部署源码中存在，但审计时未在线。它们只能作为状态机负责人接线时的候选，
不能直接当作官方完成事件。

| Topic | 类型 | 可提供的信息 | 不能直接代表 |
|---|---|---|---|
| `/robotx/perception/docking/safe_bay` | `std_msgs/msg/String` | bay、颜色、相机坐标 XYZ、confidence | NED 目标或靠泊完成 |
| `/robotx/perception/docking/alignment` | `robotx_msgs/msg/DockingStatus` | bay、对齐/航向/距离误差 | `DOCKED`；当前只找到 `APPROACHING/ALIGNED` |
| `/robotx/perception/docking/entrance_base` | `robotx_task3_interfaces/msg/DockEntrance` | `base_link` 下入口位置、yaw、confidence、误差 | 全局 dock 位置或靠泊完成 |
| `/robotx/perception/sprayer/active_window_3d` | `robotx_msgs/msg/LEDObservation` | observation ID、平台、颜色、相机坐标 | 官方 window ID 或喷水完成 |
| `/robotx/perception/sprayer/window_state` | `std_msgs/msg/String` | 视觉窗口状态 | 喷水完成确认 |
| `/robotx/perception/sprayer/task_state` | `std_msgs/msg/String` | 视觉/解码阶段 | 整体 Task3 完成 |
| `/robotx/perception/task3/logistics_request` | `std_msgs/msg/String` JSON | `resource_color/destination_color` 等投放目标 | UAV 已抓取或投放完成 |
| `/pump/set` | `robotx_gimbal_interfaces/srv/SetPump` | 请求字段 `on` | 整船急停 |
| `/pump/status` | `robotx_gimbal_interfaces/msg/PumpStatus` | initialized、pump_on、mission_state、fault | 带官方 window ID 的喷水报告 |
| `/robotx/task3/docked_confirmed` | `std_msgs/msg/Bool` | 设计上的靠泊确认 | 当前只找到订阅者，没有发布者 |

## 6. OCS/内部协议映射边界

| 团队消息 | USV ROS 2 候选来源/去向 | 当前判断 |
|---|---|---|
| OCS `command` → USV | `/tongji_mrl/twave/task_cmd` | 只能承载现有 task/action；需状态机负责人扩展正式命令契约 |
| USV `heartbeat` → OCS | `/tongji_mrl/twave/heartbeat` + 导航/飞控状态 | 当前只有 1 Hz、state/task_id，不满足官方完整 2 Hz Heartbeat |
| USV `ack` → OCS | 尚无正式 ROS 2 ACK Topic | 缺失，不能用 `task_report` 猜测 |
| USV `task_report` → OCS | `/tongji_mrl/twave/task_report` + Task1/3 authoritative events | 结构不足，完成判据未确认 |
| USV `fault` → OCS | shared-position status、泵状态、飞控/任务健康 | 缺统一故障接口，飞控状态来源未找到 |
| UAV↔USV Task3 request | `/robotx/perception/task3/logistics_request` 可作候选数据源 | 只包含颜色请求，不是完整通用状态机命令 |

通信适配器只能转换状态机明确提供的权威字段。以下数据不得由适配器推断：当前车辆模式、
Task 完成、靠泊完成、喷水完成、Task4 恢复条件、SAFE_STOP 成功以及 UAV 投放完成。

## 7. 由 USV 状态机负责人补齐

| 缺口 | 最低要求 |
|---|---|
| `RUN_START` | 接收并持久保存 `run_id`，返回带 `command_seq` 的接受/拒绝结果；不能直接由 OCS 选择 Task |
| 正式命令 ACK | 明确 ROS 2 Topic/service/action；字段至少含 `run_id/command_seq/accepted/state/detail/time` |
| `SAFE_STOP` | 定义状态机级安全停止与独立硬件急停边界、确认方式和恢复条件 |
| Task4 抢占 | 保存原 Task、phase、checkpoint 和影响车辆，Task4 优先级最高 |
| Task4 恢复 | 只从有效 checkpoint 恢复；处理进程重启、重复命令、旧 run 和失败恢复 |
| Task1 authoritative result | 入口、出口、浮标/门结果、坐标系、版本和完成/失败事件 |
| Task3 authoritative result | bay/dock 完成、window ID、喷水完成、颜色请求及完成/失败事件 |
| 车辆状态 | AUTO/MANUAL/KILLED、GPS、速度、航向、姿态、飞控/传感器健康和失联语义 |
| UAV 协调 | 确认哪些 FSM 消息发给 UAV，以及对应 ACK、超时和失败处理 |

这些接口由 USV 状态机负责人实现和维护。通信/OCS 负责人负责在接口冻结后完成 MQTT↔ROS 2
适配、schema 校验和端到端测试，不修改任务完成条件或执行器安全策略。

## 8. 接口交付验收

USV 状态机接口交付时，每个 Topic/service/action 必须同时提供：

- 完整名称和 ROS 2 类型；
- publisher/subscriber 节点；
- 字段单位、坐标系和时间基准；
- QoS、频率、启动命令和正常停止方式；
- 一条 dry-run 样例；
- 重复命令、旧 `run_id`、乱序 `command_seq`、超时和故障行为；
- 对应自动测试及不连接真实执行器的验证日志。

完成这些项目之前，USV 生产适配器状态保持“未完成”。
