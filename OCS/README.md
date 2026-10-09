# OCS

这里是同济 RobotX 2026 的 OCS（Operator Control Station）程序目录。

当前已加入第一版官方 RoboCommand 客户端 `ocs_client.py`。它只负责 OCS 与官方
RoboCommand 之间的 MQTT/Protobuf 通信，不直接控制飞控或推进器，也不会把演示数据当成真实遥测。

## 当前测试配置

- 内部 Broker：由联调环境填写
- UAV Orin：由联调环境填写
- USV Orin：由联调环境填写
- UAV vehicle ID：`T-Sky`（由团队声明）
- USV vehicle ID：`T-Wave`（由团队声明）
- 官方 Team ID：`TONG`（Tongji University / Tongji MRL）
- 当前参赛声明：Task 1 `DISRUPTIVE`、Task 2 `NONE`、Task 3 `DISRUPTIVE`、Task 4 `DISRUPTIVE`

`DISRUPTIVE` 是累进等级，表示该任务按 Core + Advanced + Disruptive 的完整要求申报。
正式发送声明前，还必须把 UAV geofence
填成首尾相同的闭合多边形，并确认它位于收到的 `RxCourse` 边界内。

Team Village 连接信息和 Orin 任务接口确认后，再接入正式通信功能。

## 新增：车辆内部通信骨架

`vehicle_protocol.py` 定义了 OCS 与两台 Orin 之间的团队内部 JSON/MQTT
协议。它与官方 RoboCommand 协议分开，车辆不会连接官方 RoboCommand。当前 v1
只保留 `heartbeat`、`task_report`、`fault`、`command`、`ack` 五类 Topic。
UAV↔USV 直连使用另一组独立的 `tongji/robotx/fsm/v1/...` Topic，不经过 OCS。

`vehicle_agent.py` 是放在 Orin 上的适配器骨架；当前只支持安全的模拟心跳，
不会启动 ROS 2、飞控、水泵或其他硬件：

```bash
python3 vehicle_agent.py --vehicle-id T-Sky --broker <internal-broker-ip> --simulate
python3 vehicle_agent.py --vehicle-id T-Wave --broker <internal-broker-ip> --simulate
```

`fsm_protocol.py` 定义 UAV↔USV 状态机的 JSON envelope、Topic、校验和 ACK；
`fsm_link.py` 提供 MQTT 传输、去重和自动 ACK 骨架。详细格式见
`../docs/uav_usv_state_machine_link.md`。这两个模块不直接连接 ROS 2 或执行器。

`ocs_client.py` 只把经过校验的 `RunStart` 和官方 Task 4 命令排队给 USV
任务协调器；不会在 OCS 内判断当前执行哪个任务，也不会直接启动 UAV。
收到官方 `RunStart` 后只给 `T-Wave` 发送 `RUN_START`。Task 4 命令由 USV

决定是否抢占 Task 1/3、如何协调 UAV 以及何时恢复。车辆 ACK 和 Readiness
由 `accept_vehicle_ack()`、`accept_vehicle_readiness_report()` 转换为官方报告。
需要发送给 USV 的动作由 `drain_internal_actions()` 取出，再交给独立的
`vehicle_link.py` 通过团队 JSON/MQTT 链路发送。

`sequence_store.py` 会把请求序号、每车报告序号和已接收的官方命令序号原子写入
`logs/ocs_state.json`，避免 OCS 重启后复用序号。`watchdog.py` 由网关调用，默认检测
3 秒心跳超时和 5 秒 ACK 超时，并输出一行 JSON 事件；它不会自动发送 `SAFE_STOP`，也
不会代替 USV 做任务选择、抢占或完成判断。

`task_priority_manager.py` 现在只是 USV 任务协调器的参考状态机，不被 OCS
客户端调用；真正接入时应放入 USV 的任务管理节点。

车辆命令动作可由内部适配器发送：

```python
for action in ocs.drain_internal_actions():
    vehicle_link.send_action(action)
```

USV 端命令处理器至少要能：接收 `RUN_START` 和官方 Task 4、判断并暂停当前
Task 1/3、必要时协调 UAV、返回带 `command_seq` 的 ACK、上报 Readiness，
以及在自己的任务状态机中恢复被抢占任务。具体 Topic 仍只有合约中的五个 Topic；
OCS→车辆的 `command` 在当前联调阶段只发给 `T-Wave`。

电脑 B 作为官方 RoboCommand Broker、电脑 A 运行 OCS 网关时，用
`ocs_gateway.py` 把两条 MQTT 链路接起来：

```bash
python3 ocs_gateway.py \
  --official-broker <电脑B_IP> \
  --internal-broker <内部Broker_IP> \
  --publish-declaration
```

网关收到官方 `RunStart` 后只向 `T-Wave` 发送 `RUN_START`；收到官方 Task 4
后也只把官方事件转发给 `T-Wave`。T-Wave 再根据自己的任务状态机协调
`T-Sky`。车辆回传的 `heartbeat`、`ack` 和带 `official_report` 的
`task_report` 会由网关转换成官方报告。

`vehicle_link.py` 是 OCS 侧观察工具，先只读监听两台车辆：

```powershell
python .\vehicle_link.py --broker <internal-broker-ip> --duration 30
```

## UAV 地图转换

`ned_map_transform.py` 已加入 UAV NED 到 USV NED 的纯 Python 转换。它按照项目
资料中的约定，把 UAV 建图原点与 USV 任务起点的 WGS84 GPS/RTK 差值转换成
`offset_to_add_m`，再将 `/task/semantic_map` 中的 `NED_position` 平移到 USV
坐标系。它不依赖 ROS 2 或 MQTT，便于先做离线验证；车辆适配器准备好后再把
`mapping_start`、`semantic_map` 和 USV GPS 遥测接到它。

```powershell
python .\ned_map_transform.py --uav-lat 31.230410 --uav-lon 121.473710 --uav-alt 15.2 --usv-lat 31.230400 --usv-lon 121.473700 --usv-alt 14.7
```

输入高度必须是 WGS84 椭球高（米），不是未经说明的海拔或相对高度。实现假设
UAV/USV 两套 NED 的北、东、下方向已经对齐，因此当前只做平移，不猜测 yaw。
真实接入前仍需确认 GPS 的实际来源（候选为 PX4 的
`/fmu/out/vehicle_gps_position` 或 USV 桥接器的 `/fix`）、字段单位、RTK 状态、
`/task/semantic_map` 的完整 JSON 样例，以及两台车 NED 轴是否确实共向。

确认模拟心跳后，才允许做命令链路测试。命令必须显式使用 `--send`，当前
Orin 适配器默认会拒绝命令，因为 ROS 2 命令处理器尚未接入：

```powershell
python .\vehicle_link.py --broker <internal-broker-ip> `
  --send T-Wave ping --duration 5
```

协议测试不需要 Broker：

```powershell
python -m unittest discover -s . -p "test_*.py"
```

当前基线为 23 项单元测试通过。

通信/OCS 负责人维护通用协议、MQTT 骨架、模拟器和测试。UAV 状态机负责人实现 UAV
生产适配器，USV 状态机负责人实现 USV 生产适配器并接入任务协调器；两边分别把真实
ROS 2 状态映射到通信模块，并实现经过安全检查的 handler。在确认 dry-run、停止/急停、
Task 1/3 状态和定位语义前，不要把命令处理器接到真实执行器。详细字段和 ACK
规则见 `vehicle_link_contract.md`。

比赛接口要点：只有 OCS 连接 RoboCommand；车辆不直接连接 RoboCommand。OCS 面向比赛网络的网卡必须使用 DHCP，内部车辆网络由团队自行设计。

## 第一版客户端

先安装 OCS 的 Python 依赖，再查看帮助：

```powershell
python -m pip install -r .\requirements.txt
python .\ocs_client.py --help
```

连接当前配置中的内部 Broker，只订阅官方下行主题（不会发布）：

```powershell
python .\ocs_client.py --duration 30
```

连接测试 Broker，并发布当前团队声明和**合成**心跳，用于验证 MQTT/Protobuf 链路：

```powershell
python .\ocs_client.py --broker 127.0.0.1 --publish-declaration --demo-heartbeats --duration 10
```

比赛时应把 `--broker` 换成 Team Village 提供的 RoboCommand 地址；`--demo-heartbeats`
只能用于联调。后续把 Orin/ROS 2 的真实状态接到 `publish_heartbeat()` 和
`publish_safe_passage_report()` 即可，车辆本身不需要连接官方 RoboCommand。

## Task1 当前进度

- `task1_bridge_contract.md`：记录已确认的 ROS 2 Topic、状态映射和未决接口。
- `task1_status_adapter.py`：无依赖的离线状态转换原型，暂不连接 ROS 2 或 MQTT。

演示状态转换：

```powershell
python .\task1_status_adapter.py --phase TASK_COMPLETE --vehicle-id T-Wave
```

## 运行配置检查

```powershell
python .\ocs_bridge.py --config .\config.example.json
```

## 当前未完成任务

完整的 OCS、USV、UAV、电脑 B 责任划分和电脑 B 官方模拟步骤见 `../README.md`。

- 冻结 UAV↔USV 最终 payload、坐标系、状态枚举和任务完成/失败判据。
- UAV 源码级 Topic 和缺口已记录在 `../docs/uav_ros2_interfaces.md`；由 UAV 状态机/
  飞控负责人补齐通用命令/ACK、统一车辆状态、Task1/3 权威结果和安全接口。
- USV 源码级 Topic 和缺口已记录在 `../docs/usv_ros2_interfaces.md`；由 USV 状态机
  负责人补齐正式命令/ACK、车辆状态、Task4 checkpoint/恢复和安全接口。
- 由 UAV/USV 状态机负责人分别完成生产 ROS 2 适配器；通信负责人只维护转换骨架和测试。
- 在 USV-Orin 接入 Task4 抢占、checkpoint 持久化、恢复和 `SAFE_STOP`。
- 完成电脑 B、电脑 A、UAV-Orin、USV-Orin 四机联调，以及通信与任务超时监控
  （watchdog）、断线、旧 run 和重复消息测试。
- 填写真实 geofence、Broker 和比赛网卡参数；在测试通过前不连接真实执行器。
