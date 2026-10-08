# RobotX 2026 通信流程与接口总览

更新时间：2026-10-08
资料依据：RoboNation Handbook 3.4（官网最新页面）、官方 `robonation/robocommand` 的
`RobotX_2026` 目录、团队 `task_flow.pdf`。

## 1. 先区分两条通信边界

```text
                    官方 RoboCommand 网络
                           ▲       ▼
                           │ MQTT + Protobuf
                           │
                    ┌──────┴──────┐
                    │     OCS     │
                    │ 官方唯一连接│
                    └───┬──────┬──┘
                        │      │
             团队内部链路│      │团队内部链路
                        │      │
                 ┌──────▼─┐  ┌─▼──────┐
                 │ UAV FSM│◄►│ USV FSM│
                 └────────┘  └────────┘
                    UAV ↔ USV 直接交换任务数据
```

官方只规定 **OCS ⇄ RoboCommand**。UAV 和 USV 不连接官方 RoboCommand；它们之间以及它们与 OCS 之间的网络、Topic、JSON 或 ROS 2 接口由团队自行定义。现在采用的团队设计是：USV 作为任务协调器接收 UAV 的任务数据并决定当前 task，OCS 负责官方通信、RunStart 转发、必要信息收发、报告格式转换和日志。

坐标转换不再作为 OCS 的任务主链路；UAV 与 USV 直接交换已经约定好的任务坐标/目标数据。之前加入的 `ned_map_transform.py` 仅保留为离线参考，不应接入比赛默认流程。

## 2. 官方 RoboCommand ⇄ OCS

### 2.1 官方 MQTT 主题

| 方向 | Topic | Protobuf envelope | 用途 |
|---|---|---|---|
| RoboCommand → OCS | `robocommand/robotx/course` | `RxCourse` | 当前课程配置；Broker retained |
| OCS → RoboCommand | `robocommand/robotx/<team_id>/<vehicle_id>/report` | `RxReport` | 代表某辆车上报心跳和任务结果 |
| OCS → RoboCommand | `robocommand/robotx/<team_id>/request` | `RxRequest` | 团队级请求，当前主要是 `RunDeclaration` |
| RoboCommand → OCS | `robocommand/robotx/<team_id>/command` | `RxCommand` | `RunStart` 和 Task 4 指令 |

`vehicle_id` 只是“这条消息代表哪辆车”，不表示 UAV/USV 自己连接 RoboCommand。所有官方 MQTT payload 都是二进制 Protobuf，不能发送团队内部 JSON 代替。

### 2.2 OCS 向官方发送

#### RunDeclaration（开跑前，一次）

OCS 发布一个 `RxRequest`，包含：

- `team_id`
- `seq`：团队请求序号，单调递增
- `sent_at`
- `vehicle_ids`：本次参加运行的全部车辆
- Task 1、2、3、4 的申报等级；不参加必须填 `TIER_NONE`
- 闭合的 `uav_geofence`，首尾点必须相同，并且位于 `RxCourse` 边界内

#### 每辆车 Heartbeat（运行中，官方要求 2 Hz）

OCS 为每辆车独立维护 `RxReport.seq`，并发布 `Heartbeat`。字段包括：

- `state`：`KILLED`、`MANUAL`、`AUTO`
- GPS `position`
- `spd_mps`、`heading_deg`
- `roll_deg`、`pitch_deg`、`altitude_hae_m`；USV/UUV 还可有 `depth_m`
- `current_task`
- `vehicle_type`：USV/UUV/UAV
- UAV 的 `flight_phase`

`current_task` 是官方判断车辆是否开始/结束某个任务尝试的权威字段：进入具体任务表示开始，切换到 `TASK_NONE` 表示结束；不能把 `TASK_UNKNOWN` 当成结束。

#### 任务报告

| 任务 | 官方消息 | 主要内容 |
|---|---|---|
| Task 1 Safe Passage | `SafePassageReport` | `entry_position`、`exit_position`、全部浮标及 `BeaconState` |
| Task 2 Infrastructure Survey and Repair | `PipelineSurveyReport` | 活动浮标位置、按顺序的管线段状态 |
| Task 2/3 Advanced/Disruptive | `ResourceDeliveryRequest` | 任务、资源颜色、投放圆颜色；UAV 开始投放时需回显 |
| Task 3 Coordinated Logistics | `DockingReport` | 成功停入的 bay ID |
| Task 3 Coordinated Logistics | `FirefightingReport` | 成功完成喷水的 window ID |
| Task 4 Dynamic Incident Response | `IncidentAck`、`ReadinessReport` | 对官方指令的确认、到位准备报告 |

### 2.3 官方向 OCS 发送

#### RxCourse（连接后立即接收）

这是 retained 消息，OCS 订阅后无需等待下一次发布即可收到：

- `course_id`
- 声呐 pinger 频率 `pinger_freq_hz`
- 课程边界 `corners`，首尾点相同
- `sent_at`

OCS 必须先校验课程 ID、边界和 UAV geofence，再进行正式运行。

#### RunStart（正式运行许可）

OCS 收到 `RunStart` 后必须检查：

- `declaration_seq` 是否等于 OCS 刚刚发送的声明序号；
- 保存官方分配的 `run_id`；
- 只有通过检查后，才向 USV 任务协调器发送 `RUN_START`；USV 再决定如何启动/协调 UAV。

在收到并验证 RunStart 之前，两台车应保持自主模式下的位置保持，不应开始任务动作。

#### Task 4 指令

官方 `RxCommand` 通过 OCS 路由到内部车辆：

1. `AssistanceRequest`：指定车辆类型和目标位置；车辆先 ACK，再到位并发送 `ReadinessReport`。
2. `KeepOutZone`：指定危险区域、半径和受影响车辆类型；车辆 ACK 并避开。
3. `AllClear`：解除指定车辆类型的避让状态；车辆 ACK。
4. `MovingObjectAlert`：提供移动目标位置、航向、速度和受影响车辆类型；没有单独 ACK/AllClear 链。
5. `ReadinessConfirm`：OCS 收到 `ReadinessReport` 后由官方发回确认，OCS 再路由给 USV；USV 决定对应车辆的恢复动作。

## 3. 团队内部通信：UAV ↔ USV ↔ OCS

### 3.1 OCS 状态机（官方边界）

```text
INIT
  ↓ 连接官方 Broker、订阅 course/command
COURSE_READY
  ↓ 收到并校验 RxCourse
DECLARED
  ↓ 发布 RunDeclaration、开始 2 Hz 心跳
WAIT_RUN_START
  ↓ 校验 RunStart.declaration_seq，保存 run_id
RUN_ENABLED
  ↓ 向 USV 任务协调器发 RUN_START
MISSION_RUNNING
  ├─ 收集 UAV/USV 状态并发布官方 Heartbeat/明确提供的 TaskReport
  ├─ 收到官方 Task 4 指令 → 路由给 USV 并跟踪 ACK/Readiness
  ├─ 车辆失联/故障 → 上报状态、停止使用旧状态伪造心跳
  └─ 收到 USV 的 authoritative official_report → 转换并发布官方报告
MISSION_COMPLETE / SAFE_STOP / FAULT
```

OCS 不负责 PX4 setpoint、推进器、水泵、云台或夹爪底层控制；这些属于车辆状态机和硬件适配器。

### 3.2 UAV 状态机（按团队任务流程）

```text
UAV_READY
  ↓ 粗略扫描
TASK1_SCAN_COARSE
  ↓ 第二次扫描、确认起点/终点范围和浮标
TASK1_SCAN_FINE
  ↓ 直接把 Task 1 需要的地图/浮标信息发给 USV
TASK1_SHARE_TO_USV
  ↓ 收到 USV 到达/规划完成状态
TASK1_WAIT_USV
  ↓ USV 报告 Task 1 完成
TASK1_DONE → 降落岸边
  ↓ 收到 USV Task 3 的 dock/颜色/投放信息
TASK3_READY
  ↓ 起飞、选择更近的 platform、识别 tin/circle
TASK3_PICK
  ↓ 抓取成功
TASK3_DELIVERY
  ↓ 到另一个 platform，识别 circle，释放 tin
TASK3_DONE → 向 OCS 报告任务完成
```

UAV 与 USV 直接传输的内容至少包括：Task 1 浮标/门信息、Task 3 dock 粗定位、dock
状态、颜色序列、delivery 目标和完成/失败事件。参考 Topic、JSON envelope、ACK 和去重
规则已写入 `uav_usv_state_machine_link.md`；最终 payload 与 ROS 2 映射仍由两车状态机
负责人共同定稿。

### 3.3 USV 状态机（按团队任务流程）

```text
USV_READY
  ↓ 收到 OCS 的 RUN_START，并收到 UAV Task 1 信息
TASK1_NAVIGATE_START
  ↓ UAV 提供浮标/门信息
TASK1_PLAN_AND_PASS
  ↓ 到达终点
TASK1_DONE → 报告本地状态机完成，OCS 发布官方状态/报告
  ↓ UAV 降落、任务进入 Task 3
TASK3_MAP_DOCK
  ↓ 读取 UAV 提供的 dock 信息
TASK3_APPROACH_ARC
  ↓ lidar 判断入口方向，调整朝向
TASK3_DOCK
  ↓ 绿灯/入口中点 setpoint，确认停泊
TASK3_SPRAY
  ↓ 喷水完成判定
TASK3_COLOR_SEQUENCE
  ↓ 识别 tin/circle 颜色并发给 UAV
TASK3_DONE → 通知 UAV FSM 执行 delivery
TASK3_EXIT_DOCK
```

USV 的 Task 3 停泊完成、喷水完成、颜色识别完成必须有明确事件或状态，不应由 OCS 根据超时自行猜测。

## 4. 一次完整运行的信息流

### 开始前

1. OCS 的官方网卡接入 RJ-45 比赛网络，使用 DHCP；关闭桥接、Internet 共享和 DHCP 服务。
2. OCS 连接当前赛道 RoboCommand 地址，订阅 `course` 和 `<team_id>/command`。
3. OCS 收到 retained `RxCourse`，保存 `course_id`、边界和 pinger 信息。
4. OCS 启动内部 UAV/USV 监听，确认两个状态机在线。
5. OCS 发布 `RunDeclaration`，包含 TONG、UAV/USV vehicle ID、Task 1/3 等级和闭合 geofence。
6. 两车进入 `AUTO`，位置保持；OCS 开始为两车发布 2 Hz Heartbeat。

### Task 1

1. OCS 校验 `RunStart` 后，只向 USV 任务协调器发送内部 `RUN_START`；USV 再负责启动和协调 UAV。
2. UAV 粗扫、精扫，并直接向 USV 发送 Task 1 地图/浮标/门信息。
3. USV 接收信息并规划通过两道门，向 UAV/OCS 发送状态。
4. USV 汇总必要的 UAV/USV 数据，生成带 `official_report` 的任务报告；OCS 只转换并发布 `SafePassageReport` 和 Heartbeat。
5. USV 状态机报告完成，OCS 记录并转发官方报告；OCS 不自行判断 Task 1 结束。

### Task 3

1. USV 读取 UAV 直接发送的 dock/平台信息，完成靠泊、喷水和颜色序列识别。
2. USV 把 dock 状态、喷水完成、颜色序列和 delivery 目标直接发给 UAV。
3. OCS 按官方要求，把 USV/UAV 明确产生的事件分别转换为 `DockingReport`、`FirefightingReport` 和 `ResourceDeliveryRequest`，并持续发布 Heartbeat。
4. UAV 起飞、选择平台、抓取 tin、飞向目标并释放。
5. USV 作为协调器汇总完成状态；OCS 发布 USV 明确提供的官方任务报告并保存日志。

### Task 4

当前团队文档把 Task 4 记为“可能在前两个任务中途插入、最高优先级”。官方 Handbook 将 Task 4 定义为 Dynamic Incident Response；正式流程必须以现场收到的 `RxCommand` 为准。OCS 收到官方指令后只转发给 USV，并跟踪序号和 ACK/Readiness；由 USV 决定抢占、协调 UAV 和恢复原任务。

## 5. 建议的团队内部消息最小集合

这些不是官方协议，而是 OCS 与车辆状态机之间的团队协议建议：

| 消息 | 方向 | 必须包含 |
|---|---|---|
| `RUN_START` / `RUN_STOP` | OCS → USV | `run_id`、官方序号、时间戳 |
| `vehicle_heartbeat` | UAV/USV → OCS | 在线、模式、当前任务、位置、故障、时间戳 |
| `task1_map_update` | UAV → USV | 浮标/门位置、坐标系声明、版本号、时间戳 |
| `task1_state` | USV → UAV/OCS | 阶段、当前门、通过门序号、故障/恢复原因 |
| `dock_state` | USV → UAV/OCS | dock ID、入口方向、停泊状态、喷水状态 |
| `delivery_request` | USV → UAV | tin/circle 颜色、目标位置、有效期、版本号 |
| `delivery_state` | UAV → USV/OCS | 起飞、搜索、抓取、释放、成功/失败原因 |
| `task_report` | UAV/USV → OCS | 任务阶段、完成/失败、事件时间、证据；USV 汇总时带 `official_report` |
| `ACK` | 接收方 → 发送方 | 原消息 ID、接受/拒绝、原因 |

内部消息必须带 `message_id`、`sent_at`、`run_id`、`vehicle_id`、`source` 和 `frame_id`；失联恢复后不能把旧 run 的消息当作新 run 数据。

其中 OCS↔车辆使用 `tongji/robotx/v1/...`；UAV↔USV 状态机直连使用独立的
`tongji/robotx/fsm/v1/<source>/<target>/<kind>`，不经过 OCS。直连参考实现为
`OCS/fsm_protocol.py` 和 `OCS/fsm_link.py`，只提供任务级消息传输，不控制执行器。

## 6. 当前 OCS 项目状态

- 官方 OCS 客户端已能连接、订阅 `RxCourse`/`RxCommand`，构造 `RunDeclaration`、Heartbeat、Task 1 报告。
- 官方 `RobotX_2026` schema 与 GitHub 最新主分支内容已下载并核对；当前本地 schema 文本与官方快照一致，主要差异只是换行格式。
- 团队内部 MQTT 模拟链路已验证心跳、ACK、断线恢复；UAV↔USV 参考消息格式和
  通信骨架已完成，真实 ROS 2 状态机尚未接入。
- UAV/USV 直接通信的最终 payload、坐标系以及状态机启动/停止/急停接口仍需两车
  状态机负责人确认。
- USV-Orin 的源码级 Topic 已盘点，见 `usv_ros2_interfaces.md`；当前任务节点未在线，
  `RUN_START`、正式 ACK、Task4 checkpoint/恢复和整船 `SAFE_STOP` 尚未实现。
- UAV-Orin 的源码级 Topic 已盘点，见 `uav_ros2_interfaces.md`；当前没有 PX4/任务节点
  在线，Task1/3 仅有不完整候选或实验接口，通用任务命令、正式 ACK 和安全接口缺失。
- OCS 的 `ned_map_transform.py` 不再属于比赛主链路；如继续保留，只作为离线参考和历史资料。

## 7. 必须补齐的接口清单

1. 确认 UAV↔USV 直连使用的 Broker/端口，并冻结参考 Topic/envelope 的生产版本。
2. UAV 状态机负责人根据 `uav_ros2_interfaces.md` 补齐 Task1 地图/入口/出口/浮标结果、
   Task3 delivery 状态、通用命令/ACK、统一车辆状态和安全接口。
3. USV 状态机负责人根据 `usv_ros2_interfaces.md` 补齐停泊、喷水、window ID、颜色请求
   和 authoritative 任务完成事件。
4. USV 状态机负责人补齐 `RUN_START`、正式 ACK、Task4 checkpoint/恢复和整船
   `SAFE_STOP`；UAV 负责人补齐对应 UAV 状态定义。
5. OCS 如何安全地向 USV 任务协调器发送开始/停止/Task 4 官方事件，以及 USV 如何协调 UAV。
6. 最终 Team ID、vehicle ID、任务等级和比赛现场 RoboCommand 连接参数。
7. 官方最新 schema 变更后的全量本地测试：RunDeclaration、RunStart、2 Hz Heartbeat、Task 1/3 报告、Task 4 ACK/Readiness、重连和旧 run 隔离。

## 8. Ubuntu 交接后的只读审计与离线验证（2026-10-06）

- 已解压并阅读 Ubuntu 说明、通信总览、开发主线、OCS 合约、Handbook 3.4 快照、官方
  `RobotX_2026` README、`rc_test/test_client.py` 和 `test_server.py`。
- OCS 本地单元测试从原有 7 项扩展为 23 项，覆盖 retained `RxCourse` 保存与边界校验、
  RunStart declaration sequence/run ID 校验、每车独立 report sequence、Task 3 报告和旧
  run 隔离；Python 编译和 JSON 检查通过。
- 官方测试客户端离线构造并解析 14 类 protobuf 消息，Topic 和 envelope 与本地 schema
  一致。当前环境没有 Docker、Mosquitto 或 broker 守护进程，因此尚未宣称官方 broker
  端到端测试通过。
- 内部 v1 JSON envelope 已补充 `run_id`、`source`、`frame_id`；ACK 要求、超时记录和旧
  run 丢弃规则已写入 `OCS/vehicle_link_contract.md`。这仍是团队协议草案，不是官方
  RoboCommand schema。
- 包内未发现实际 UAV/USV ROS 2 工程、运行节点或 `ros2 topic list -t` 输出；现有 Topic
  名称和字段仍属于待软件组实测确认项。未启动 ROS 2、PX4 或任何执行器。

## 9. OCS ⇄ UAV/USV 内部协议 v1（2026-10-08）

当前先不把 UAV⇄USV 直连任务数据纳入 OCS 协议，只保留 OCS 与车辆之间的最小闭环。
Task 4 作为 USV 任务协调器的最高优先级：在 Task 1/3 中途收到官方 Task 4 指令时，
OCS 转发给 USV，由 USV 保存断点、抢占车辆、完成 Task 4 官方响应链并恢复原任务。

| Topic | 方向 | 内容 |
|---|---|---|
| `tongji/robotx/v1/<vehicle_id>/heartbeat` | 车辆 → OCS | 车辆状态、任务、位置、健康和故障 |
| `tongji/robotx/v1/<vehicle_id>/task_report` | 车辆 → OCS | 官方 Task 1/3 所需结果 |
| `tongji/robotx/v1/<vehicle_id>/fault` | 车辆 → OCS | 故障、严重度、影响和恢复状态 |
| `tongji/robotx/v1/<vehicle_id>/command` | OCS → USV | `RUN_START`、`SAFE_STOP`、转发给 USV 的 Task 4 官方事件 |
| `tongji/robotx/v1/<vehicle_id>/ack` | 车辆 → OCS | 对 command 的接受结果和处理状态 |

Task 4 command 的内部 payload 必须携带官方 `command_seq` 和 `decision_owner=USV`；
具体 `priority`、`preempt`、断点和 `TASK4_RESUME` 由 USV 任务协调器决定。ACK 必须
说明 USV 是否已接受/转发。`SAFE_STOP`/急停是安全覆盖，不等待 Task 4 完成。

所有消息先使用统一 JSON envelope；官方消息仍只在 OCS⇄RoboCommand 边界使用 Protobuf。
完整字段、payload 和时序见 `OCS/vehicle_link_contract.md`。原始 ROS Topic、传感器流、
详细规划、UAV⇄USV 地图交换和低层执行器命令不纳入该协议。

## 10. 实现责任边界

| 模块 | 负责人 | 当前状态 |
|---|---|---|
| 官方 RoboCommand、OCS 网关、协议/schema、日志和测试 | 通信/OCS 负责人 | 基础实现完成，真实现场参数待填 |
| 通用车辆 MQTT 骨架与 UAV↔USV 直连骨架 | 通信/OCS 负责人 | 参考实现完成，不连接执行器 |
| UAV ROS 2 ↔ 团队协议生产适配器 | UAV 状态机负责人 | 未完成 |
| USV ROS 2 ↔ 团队协议生产适配器 | USV 状态机负责人 | 未完成 |
| Task4 抢占、checkpoint/恢复和 UAV 协调 | USV 状态机负责人 | 纯 Python 参考决策核已有，真实接入未完成 |
| 四机端到端、断线和故障验收 | 三方共同完成 | 未完成 |

任何代码接口变化都必须同时更新对应合约、示例、README 和测试。生产适配器由车辆
状态机负责人编写和维护；通信负责人提供消息骨架、测试用例和联调支持，但不代替车辆
负责人定义真实 ROS 2 Topic、完成判据或安全动作。
