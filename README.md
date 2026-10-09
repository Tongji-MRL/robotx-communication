# RobotX Communication

同济 RobotX 2026 通信协议、OCS 网关和联调工具。

## 架构边界

```text
官方 RoboCommand / 电脑 B
          ⇅ MQTT + Protobuf
      OCS Gateway / 电脑 A
          ⇅ MQTT + JSON
        USV T-Wave
          ⇅ USV 内部任务链路
        UAV T-Sky
```

- 只有 OCS 连接官方 RoboCommand。
- OCS 只负责官方消息校验、转发、格式转换和日志，不判断当前执行哪个 Task。
- USV 是任务协调器，负责 Task 选择、Task4 抢占、UAV 协调和任务恢复。
- 车辆内部协议只保留 `heartbeat`、`task_report`、`fault`、`command`、`ack` 五类消息。
- UAV/USV 的原始 ROS 2 Topic、传感器流和低层执行器命令不进入 OCS 协议。

## 目录

- `OCS/ocs_gateway.py`：连接官方 Broker 与内部车辆 Broker。
- `OCS/ocs_client.py`：官方 RoboCommand MQTT/Protobuf 客户端和报告转换。
- `OCS/vehicle_protocol.py`：内部 JSON envelope、Topic 和命令格式。
- `OCS/vehicle_agent.py`：Orin-LQ 侧安全模拟器/适配器骨架。
- `OCS/fsm_protocol.py`：UAV↔USV 状态机直连 JSON 协议和校验。
- `OCS/fsm_link.py`：UAV/USV 状态机 MQTT 通信骨架，不连接执行器。
- `OCS/task_priority_manager.py`：USV 任务协调器的参考状态机，不由 OCS 调用。
- `docs/usv_task_coordinator_deployment.md`：参考状态机在 USV-Orin 上的部署边界和适配清单。
- `docs/usv_ros2_interfaces.md`：USV-Orin 已发现 Topic、可用程度、缺口和交付验收条件。
- `docs/uav_ros2_interfaces.md`：UAV-Orin 已发现 Topic、PX4/任务候选接口、缺口和验收条件。
- `docs/uav_usv_state_machine_link.md`：UAV↔USV Topic、消息格式、ACK 和责任边界。
- `OCS/vehicle_link_contract.md`：内部协议正式草案。
- `docs/communication_overview.md`：当前通信架构和官方/内部接口总览。
- `docs/development_mainline.md`：开发进度、阻塞项和验收主线。
- `examples/`：可用于联调的 JSON 示例。

## 联调

在两台 Orin-LQ 上分别启动车辆适配器：

```bash
python3 vehicle_agent.py --vehicle-id T-Wave --broker <internal-broker-ip> --simulate --accept-commands
python3 vehicle_agent.py --vehicle-id T-Sky --broker <internal-broker-ip> --simulate
```

在 OCS 电脑上启动网关：

```bash
python3 ocs_gateway.py \
  --official-broker <computer-b-ip> \
  --official-port 1883 \
  --internal-broker <internal-broker-ip> \
  --publish-declaration
```

当前模拟器只验证消息收发和 ACK，不连接真实 ROS 2、PX4 或执行器。

## 责任边界

| 端 | 负责内容 | 不负责内容 |
|---|---|---|
| OCS / 电脑 A | 官方 RoboCommand、Protobuf↔内部 JSON、内部 MQTT、序号/run 校验、日志和通信测试 | 选择当前 Task、猜测任务完成、直接控制执行器 |
| USV / T-Wave | 主任务协调、Task 选择、Task4 抢占、checkpoint/恢复、UAV 协调、USV ROS 2 生产适配器 | 连接官方 RoboCommand |
| UAV / T-Sky | UAV 状态机、飞控安全、Task1/3 权威结果、UAV ROS 2 生产适配器 | 连接官方 RoboCommand、决定全局任务优先级 |
| 电脑 B | 在实验室模拟官方 Broker/RoboCommand，发送课程和官方命令、接收并解码 OCS 报告 | 运行 OCS、替车辆决定任务或控制硬件 |
| 四方共同 | dry-run、故障注入、端到端时序和日志验收 | 在接口未验收前连接真实执行器 |

通信负责人维护 `vehicle_agent.py`、`fsm_link.py`、协议/schema 和验收测试；UAV/USV
状态机负责人分别实现并维护自己的生产 ROS 2 接口与适配器。通信负责人不能代替车辆
负责人定义任务完成条件和安全动作。

## 当前未完成任务（按责任端）

### OCS / 电脑 A

- 把两车负责人最终确认的 ROS 2 字段映射接入 OCS 内部协议，不接收未确认的模拟字段。
- 完成车辆心跳、ACK 和任务报告的通信与任务超时监控（watchdog）、断线重连、旧
  `run_id` 隔离、重复消息和乱序序号测试。
- 只根据车辆明确提供的 `official_report` 生成官方 Task1/3 报告，不根据超时或
  `phase=COMPLETE` 自行判断完成。
- 完成报告序号持久化、结构化日志和可复核测试日志包。
- 填写正式 UAV geofence、Team Village Broker/网卡参数；密钥或现场敏感参数不提交仓库。

### USV / T-Wave

- 按 `docs/usv_ros2_interfaces.md` 补齐 `RUN_START`、正式 ACK、统一车辆状态、故障和
  整船 `SAFE_STOP` ROS 2 接口，并提供 dry-run 样例。
- 实现 Task1/Task3 当前任务选择、Task4 最高优先级抢占、checkpoint 持久化、通信与
  任务超时监控（watchdog）、Task4 完成后的安全恢复。
- 实现 Task1 入口/出口/浮标结果，以及 Task3 靠泊、window ID、喷水、颜色请求和
  authoritative 完成/失败事件。
- 实现并维护 USV 生产适配器；在安全验收前不得连接推进器、水泵、云台或其他执行器。

### UAV / T-Sky

- 按 `docs/uav_ros2_interfaces.md` 补齐通用任务命令、正式 ACK、统一车辆状态和
  `SAFE_STOP`/返航/降落边界，并提供 dry-run 样例。
- 实现 Task1 地图版本、坐标系、入口/出口、浮标/门和扫描完成/失败权威事件。
- 实现 Task3 起飞、搜索、抓取、投放及真实夹爪/投放反馈，确认 Task4 抢占、checkpoint
  和恢复行为。
- 明确 PX4 arming/nav/failsafe 到官方 AUTO/MANUAL/KILLED、flight phase 的映射。
- 实现并维护 UAV 生产适配器；在飞控安全验收前不得发布真实 offboard/夹爪命令。

### 电脑 B / 官方模拟端

- 安装 Docker Engine 和 Docker Compose，准备官方 `RobotX_2026` schema/test server；
  若现场无 Internet，应提前拉取或导入 `eclipse-mosquitto:2` 和测试镜像。
- 使用稳定测试网 IP，让电脑 A 能访问 TCP 1883；测试网络与真实比赛网络、车辆执行器
  网络隔离。当前测试配置允许匿名 MQTT，只能用于受控实验室网络。
- 配置与 OCS 一致的 Team ID `TONG`、车辆 ID `T-Sky/T-Wave`、课程边界和测试时间；
  course 边界必须闭合，UAV geofence 必须位于 course 内。
- 启动 Broker/test server，发布 retained `RxCourse`，接收并解码 `RunDeclaration`、
  Heartbeat 和 Task1/3/4 报告；所有声明车辆进入 AUTO 后发送匹配声明序号的 `RunStart`。
- 使用官方测试客户端发送 Task4 `AssistanceRequest`、`KeepOutZone`、`AllClear`、
  `MovingObjectAlert`、`ReadinessConfirm`，验证 OCS 的 ACK/Readiness 和路由行为。
- 保证同一 Team 的所有 `RxCommand.seq`（RunStart 和 Task4）严格递增。当前一次性
  `test_client.py` 进程会重新从 1 计数，不能和 test server 自动 RunStart 混用；电脑 B
  负责人需使用单一持久命令序列器或补齐统一的命令注入工具。
- 保存 `RobotX_2026/logs/` 中的官方侧日志，并与电脑 A 和两台 Orin 的时间线对齐。

### 四方共同联调

- 先完成电脑 B ↔ 电脑 A ↔ 两台模拟 Agent 的纯通信 dry-run，再连接真实 ROS 2 状态机。
- 覆盖 RunStart 声明序号不匹配、断线重连、旧 run、重复消息、ACK 超时、畸形消息、
  Task4 中途抢占和车辆故障。
- 确认所有安全停止、恢复和任务完成判据后，才允许连接真实 PX4、推进器、水泵、云台或夹爪。

## 电脑 B 快速启动官方模拟

电脑 B 不需要 ROS 2。`RobotX_2026` 官方工具不重复提交在本仓库中，应从 Ubuntu
交接包或已核验的官方 RoboCommand 快照取得。进入该目录后执行：

```bash
cd RobotX_2026
docker compose up --build
```

这会启动 Mosquitto（TCP 1883）和官方测试服务。测试服务会发布 retained `RxCourse`、
记录所有 `robocommand/robotx/#` 消息，并在收到 `RunDeclaration` 且所有声明车辆上报
AUTO 后自动发送 `RunStart`。

手动命令测试应使用一个持续运行的交互会话，让 RunStart 和后续 Task4 共用递增序号：

```bash
docker compose run --rm rc-test python test_client.py
# 在 robotx> 提示符中依次输入：
run-start --team TONG --declaration-seq 1 --run-id 42
assistance-request --team TONG --vehicle-type usv --lat 1.2805 --lng 103.8557
```

手动命令模式不要同时让后台 test server 自动发送 RunStart；整场测试必须只有一个
`RxCommand.seq` 生成源。正式四机自动测试前，电脑 B 负责人应把 RunStart 和 Task4
注入统一到同一个模拟服务中。当前 `test_server.py` 没有关闭 auto-start 的命令行开关，
所以上述交互方式只适合受控的早期调试，不是最终自动联调方案。

结束并保留日志：

```bash
docker compose down
```

电脑 A 的 `--official-broker` 必须填写电脑 B 在测试网中的 IP，不能填电脑 A 自己的
`127.0.0.1`。正式比赛时应改用 Team Village 提供的地址，不能继续运行电脑 B 模拟服务。

## 测试

```bash
python3 -m unittest discover -s OCS -p 'test_*.py'
python3 -m py_compile OCS/*.py
```

当前基线：23 项单元测试通过。

不要提交密码、密钥、未脱敏日志、`.venv`、缓存或原始传感器数据。
