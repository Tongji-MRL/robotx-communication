# RobotX 2026 OCS 程序开发主线

更新时间：2026-10-09

这份文档是 OCS 开发的唯一进度主线。完成一项后，把对应 `[ ]` 改成 `[x]`；
部分完成使用 `[~]`，并在“当前阻塞/待确认”中补充证据。以后新增工作应归入下面某个阶段，
不要脱离主线直接接真实执行器。

## 总体数据路径

```text
UAV ROS 2 ─ UAV 状态机 ───────┐       ┌─ 官方 MQTT/Protobuf ─ RoboNation RoboCommand
                              ├─ OCS ─┤
USV ROS 2 ─ USV 状态机 ───────┘       └─ 官方报告/命令/日志
       └──────── UAV ↔ USV 团队内部直连任务数据 ───────┘
```

官方边界只在 OCS：UAV、USV 不直接连接官方 RoboCommand。USV 是任务协调器，负责
选择当前 task、Task4 抢占、协调 UAV 和恢复；OCS 只负责官方通信、RunStart 校验、
消息转发、官方报告格式转换和日志。OCS 不直接控制 PX4、推进器、水泵、云台或夹爪。

## 当前状态总览

| 阶段 | 状态 | 说明 |
|---|---|---|
| A. 目录和资料归档 | [x] | 已分离电脑 A 测试记录与 OCS 项目，并完成 Ubuntu 交接包 |
| B. 官方 RoboCommand 客户端 | [~] | 连接、订阅、声明、心跳和部分 Task 1 构造已完成；正式运行校验仍未完成 |
| C. 团队内部车辆通信协议 | [~] | OCS↔车辆 v1 和 UAV↔USV 参考协议已实现；真实 payload 与 ROS 2 映射待确认 |
| D. UAV/USV ROS 2 适配器 | [~] | 通用通信骨架已提供；UAV/USV 负责人仍需分别实现自己的生产适配器 |
| E. Task 1/3 官方报告转换 | [~] | OCS 官方构造和显式 `official_report` 转换已完成；真实车辆字段仍待 UAV/USV 适配器 |
| F. 自动化和故障测试 | [~] | OCS 纯 Python 测试已覆盖序号持久化和 watchdog；真实 Broker/四机验收仍待完成 |
| G. 真实硬件联调 | [ ] | 必须先完成 D/E，并在 dry-run 或仿真中通过 |
| H. 比赛现场运行流程 | [ ] | 依赖 Team Village 连接信息和全部接口验收 |

## A. 资料与身份

- [x] 固定 Team ID：`TONG`。
- [x] 当前团队车辆 ID：UAV=`T-Sky`、USV=`T-Wave`。
- [x] 归档官方 schema、生成代码、Docker Broker 和 rc-test。
- [x] 下载并核对官网 Handbook 关键页和官方 RoboCommand 主分支快照；通信总览见 `communication_overview.md`。
- [x] 归档电脑 A 的 Mesh、Ping、MQTT、RoboCommand 测试资料。
- [ ] 比赛前确认 RoboNation/现场最终 vehicle ID 是否仍使用当前声明。
- [x] 确认 Task 4 参赛，按 `DISRUPTIVE` 级别纳入声明和优先级调度。

## B. 官方 RoboCommand OCS 客户端

- [x] 连接官方 MQTT Broker 的基础客户端。
- [x] 订阅 `robocommand/robotx/course`。
- [x] 订阅 `robocommand/robotx/TONG/command`。
- [x] 构造并发布 `RunDeclaration`。
- [x] 构造官方 Heartbeat 和 Task 1 SafePassageReport 的初版函数。
- [x] 按最新版 Handbook 核对官方 topic、envelope、2 Hz Heartbeat、RunStart 和 Task 4 指令链。
- [x] 对 Team ID、vehicle ID、枚举、经纬度和闭合 geofence 做基础校验。
- [x] 从 retained `RxCourse` 读取并保存课程信息（已增加闭合边界校验；尚未接真实 broker）。
- [x] 收到 `RunStart` 后校验 declaration sequence，并保存 `run_id`（已增加单元测试；尚未接真实 broker）。
- [ ] 让两台参与车辆各自以 2 Hz 发布真实 Heartbeat。
- [x] 让每辆车的官方 report sequence 在进程重启后继续单调递增（`logs/ocs_state.json` 原子持久化；真实 Broker 验证仍待完成）。
- [~] 增加可靠重连、恢复订阅、发布失败处理和结构化日志（Paho 自动重连/订阅恢复和 JSON watchdog 事件已配置；真实 broker 验证未完成）。
- [x] 接入官方 Task 3 `DockingReport`、`FirefightingReport`、`ResourceDeliveryRequest` 的构造函数。
- [x] 接入官方 Task 4 `IncidentAck`、`ReadinessReport` 的构造函数；真实命令路由仍未接入。

## C. 团队内部车辆通信

- [x] 定义版本化 JSON/MQTT envelope、Topic 和 ACK 格式；已补齐 `run_id`、`source`、`frame_id`、ACK 超时和旧 run 规则。
- [x] 完成 `vehicle_agent.py` 模拟心跳骨架。
- [x] 完成 OCS 侧 `vehicle_link.py` 观察和测试命令工具。
- [x] 完成协议单元测试。
- [x] 在电脑 A Broker 上安装依赖并运行 T-Sky/T-Wave 两个模拟 Agent。
- [~] 已验证两台模拟 Agent 心跳、OCS 同时监听、`ping` 命令 ACK、T-Wave 停止后重新启动并重新入网，以及 Broker stop/start 后 Agent 自动恢复；消息格式错误仍待测试。监听器现已补充断开事件日志。
- [x] 定义 OCS⇄UAV/USV 内部协议 v1：`heartbeat`、`task_report`、`fault`、`command`、`ack` 五类 Topic 和统一 JSON envelope。
- [x] 约定 Task 4 为 USV 任务协调器的最高优先级；OCS 只转发官方命令，USV 保存 Task 1/3 断点并完成抢占/恢复。
- [x] UAV↔USV 直连使用独立 `tongji/robotx/fsm/v1/...` Topic、统一 envelope、ACK 和去重规则；参考见 `uav_usv_state_machine_link.md`。
- [ ] 由 UAV/USV 状态机负责人共同确认直连消息的最终 payload、坐标系和状态枚举。
- [ ] 确认正式比赛内部 Broker 地址、网卡和端口。
- [ ] 把模拟 payload 与真实 ROS 2 payload 严格分离，禁止模拟数据进入生产默认路径。

## D. ROS 2 适配器接口确认

每一项必须拿到：完整名称、消息类型、方向、真实消息样例、频率、QoS、启动命令、
停止方式和安全说明。

责任边界：通信/OCS 负责人维护协议、通用 MQTT 骨架、校验、模拟器和验收测试；UAV
状态机负责人实现 UAV 生产适配器，USV 状态机负责人实现 USV 生产适配器并接入任务
协调器。真实任务完成条件、ROS 2 接口和安全动作必须由对应车辆负责人确认。

- [~] UAV ROS 2 源码级接口已盘点，见 `uav_ros2_interfaces.md`；审计时只有相机/TF/诊断
  节点在线，未发现 `/fmu/*` 或任务节点。
- [ ] UAV Task 1：已有 map command、detections、NED targets 和单次 progress 候选接口；
  入口/出口、浮标/门、扫描失败和 authoritative 完成事件由 UAV 状态机负责人补齐。
- [ ] UAV Task 3：已有旧实验包的检测、状态、事件和夹爪命令候选接口；通用 USV 命令、
  正式 ACK、真实抓取/投放反馈和生产完成判据由 UAV 状态机负责人补齐。
- [~] USV ROS 2 源码级接口已盘点，见 `usv_ros2_interfaces.md`；审计时工作区 overlay
  未加载且任务节点未在线，尚无真实运行样例。
- [ ] USV Task 1：`/safe_passage/mission_state` 只是独立原型；入口、出口、浮标/门结果和
  authoritative 完成事件仍由 USV 状态机负责人补齐。
- [ ] USV Task 3：已记录 dock、alignment、window、颜色请求和泵候选 Topic；靠泊完成、
  window ID、喷水完成及执行闭环仍由 USV 状态机负责人补齐。
- [~] 两台车的 GPS、位置、速度、航向和姿态来源及坐标系；团队的设计约定是 UAV/USV 两套 NED 轴方向一致，原点分别为 UAV 开始建图位置、USV 开始任务位置，因此地图转换无需旋转；但 USV 当前源码仍使用配置参考点，尚未实现/验证任务启动时抓取原点。
- [x] 阅读地图资料并实现 WGS84 GPS 原点差到 NED 平移的 OCS 离线参考模块；当前不接入比赛主链路。
- [ ] 确认 UAV/USV 直连任务数据的真实格式；坐标数据由车辆侧直接约定和使用，不再由 OCS 转换。
- [ ] 两台车的心跳、飞控连接、传感器健康和失联状态。
- [ ] USV 状态机负责人补齐 `RUN_START`、正式 ACK、Task4 checkpoint/恢复和整船
  `SAFE_STOP`；UAV 状态机负责人补齐通用命令/ACK、Task4 协调和飞行安全接口。
- [ ] `KILLED`、`MANUAL`、`AUTO` 与内部 ROS 2 状态的映射。
- [ ] UAV `DOCKED/完成`、USV 靠泊完成和真实水泵完成的判定。
- [ ] 明确哪些接口只能 OCS 观察，哪些允许 OCS 发送。

当前审计证据：两台 Orin 审计时都只有相机/TF/诊断相关节点在线。UAV 的 PX4、Task1/3
接口只在源码候选或旧实验包中找到，统一任务命令与 ACK 缺失；USV 源码定义了
`/tongji_mrl/twave/task_cmd`、`state`、`heartbeat` 和 `task_report`，但 Task1/Task4 是
placeholder，Task3 控制闭环未完成。完整证据分别见 `uav_ros2_interfaces.md` 和
`usv_ros2_interfaces.md`。

## E. Task 1/3 数据转换

- [~] Task 1 状态离线映射：已支持 `RUNNING/RECOVERY/COMPLETE/FAULT` 原型。
- [ ] 将真实 Task 1 感知和 MissionState 转换为官方 `SafePassageReport`。
- [ ] 将真实 UAV Task 3 状态转换为官方 Task 3 报告。
- [ ] 将真实 USV Task 3 状态转换为官方 Task 3 报告。
- [ ] 明确每个报告的触发条件、序号、时间戳和重复发送策略。
- [ ] 任何缺少可靠来源的经纬度、速度、状态不得用 0 或模拟值冒充。

## F. 自动化验证

- [x] Python 语法检查、协议单元测试、序号持久化和 watchdog 单元测试（当前 30 项，需在项目 venv 中运行）。
- [~] 官方 schema 离线消息回归（14 类消息可构造/解析；真实 Mosquitto/test server 未运行，当前环境缺 Docker/Mosquitto）。
- [ ] 电脑 B 安装 Docker/Compose，准备官方 `RobotX_2026` Broker/test server、稳定测试网
  IP、TCP 1883 和官方侧日志目录。
- [ ] 电脑 B 将 RunStart 与 Task4 注入统一到同一个命令序号生成源，确保每个 Team 的
  `RxCommand.seq` 严格递增；不得混用自动 RunStart 与会从 1 重置的一次性测试客户端。
- [ ] 官方本地 Broker/test server 启动测试。
- [ ] 正确收到 retained `RxCourse`。
- [ ] 正确收到 `RunDeclaration`，任务等级和车辆 ID 正确。
- [ ] 模拟 `RunStart`：匹配 declaration sequence 才允许进入运行状态。
- [ ] 两台车 2 Hz Heartbeat 至少 30 秒，序号独立递增。
- [ ] Task 1/3 模拟报告被官方测试服务正确解码。
- [ ] Broker 临时停止后自动重连，并在项目 venv/真实 Broker 中验证持久化序号。
- [ ] 错误 Team ID、错误 vehicle ID、错误 sequence、畸形 JSON/Protobuf 不执行任务。
- [ ] 生成一次测试摘要和可复核日志包。

## G. 真实硬件联调

- [ ] 先在仿真或明确 `dry_run` 下启动 UAV/USV 节点。
- [ ] 只读验证 ROS 2 状态和遥测能到 OCS。
- [ ] 验证 start/pause/stop/急停命令的 ACK 和超时行为。
- [ ] 验证断开 LQ、重启 Agent、重启 Orin 后自动恢复。
- [ ] 验证 OCS 不会直接发布 PX4、推进器、水泵、云台或夹爪底层命令。
- [ ] 真实测试前保存节点列表、Topic 样例、配置、日志和停止方法。

## H. 最终测试/比赛发送接收流程

### 启动阶段

1. 接入电脑 A 的官方比赛网卡，按 Team Village 要求使用 DHCP。
2. 接通内部 LQ Mesh 和两台 Orin，确认内部地址和 Broker 可达。
3. 在两台 Orin 启动车辆状态机和 UAV↔USV 直连适配器。
4. 在 OCS 启动车辆状态监听，确认 T-Sky、T-Wave 心跳和状态。
5. 启动 OCS 官方 RoboCommand 客户端，连接官方 Broker。

### 声明与开始

1. OCS 接收并保存 retained `RxCourse`。
2. OCS 校验课程边界和 UAV geofence。
3. OCS 发布 `RunDeclaration`，包含 T-Sky、T-Wave 和任务等级。
4. OCS 接收 `RunStart`，校验 declaration sequence 并保存 `run_id`。
5. OCS 只向 USV 任务协调器发送 `RUN_START` 并等待 ACK；USV 再按自己的状态机启动和协调 UAV。

### 运行阶段

1. UAV 与 USV 通过团队直连交换任务数据；两台 Orin 向 OCS 上报心跳、遥测、状态和任务报告。
2. OCS 把真实状态转换为官方 2 Hz Heartbeat 和 Task 1/3 报告。
3. OCS 显示两车在线、当前任务、最近消息、序号、错误和 run ID。
4. 收到官方控制命令或本地安全操作时，先校验权限、vehicle ID 和 run ID，再转发内部命令。
5. 任何失联、超时或故障都进入安全状态，并记录事件；不得用旧数据继续伪造心跳。

### 结束阶段

1. 等待任务完成或收到停止/急停指令。
2. 记录最终任务状态和官方报告序号。
3. 停止内部 Agent 和 OCS，保留官方与内部双侧日志。
4. 导出本次运行的日志包、配置、Topic 样例和错误摘要。

## 当前阻塞/待确认

1. UAV/USV 源码级 Topic 已盘点，但统一任务命令、正式 ACK、权威任务结果、
   checkpoint/恢复和安全停止接口仍由对应状态机负责人补齐。
2. UAV Task 3 和 USV Task 3 的感知输出、执行器输入存在命名/类型不一致。
3. USV 审计时工作区 overlay 未加载、业务节点未运行；已有默认 dry-run 启动说明，但仍需
   状态机负责人确认安全启动入口并提供真实 Topic 样例。
4. 尚未取得两台 Orin 的权威车辆状态样例；原始 ROS 图清单保留在各自远端，仓库只记录
   已脱敏的接口结论。
5. 当前环境没有 Docker、Mosquitto 或可用系统 `python3-venv`；依赖已安装到交接包本地环境目录，未能启动 broker 端到端回归。
6. Team Village 正式 Broker 地址、比赛网卡和最终课程流程尚未实测。
7. UAV↔USV 参考 Topic/envelope 已完成，但最终 payload 以及两台状态机的
   `RUN_START/STOP/FAULT/COMPLETE` ROS 2 映射尚未定稿；坐标转换不由 OCS 负责。
8. UAV 和 USV 的生产适配器尚未实现；分别由对应状态机负责人负责，通信负责人提供
   通用骨架、协议测试和联调审查。
9. 电脑 B 官方模拟端尚未完成固定网络、统一 `RxCommand.seq` 生成、Task4 自动注入和
   四端日志时间线验收。
