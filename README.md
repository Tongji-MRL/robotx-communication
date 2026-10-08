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

| 工作 | 负责人 |
|---|---|
| 官方 RoboCommand、OCS 网关、内部协议、MQTT 骨架、校验和测试工具 | 通信/OCS 负责人 |
| UAV 的真实 ROS 2 Topic/action/service ↔ 团队消息映射 | UAV 状态机负责人 |
| USV 的真实 ROS 2 Topic/action/service ↔ 团队消息映射 | USV 状态机负责人 |
| Task 选择、Task4 抢占、checkpoint/恢复和 UAV 协调 | USV 状态机负责人 |
| 四机联调、故障注入和日志验收 | 通信、UAV、USV 三方共同完成 |

通信负责人维护通用 `vehicle_agent.py`、`fsm_link.py` 骨架和协议测试；UAV/USV
负责人分别实现并维护自己的生产适配器。通信负责人不能代替车辆负责人猜测真实 ROS 2
接口、任务完成条件和安全动作。适配器接入真实执行器前必须先通过 dry-run 和故障测试。

## 当前未完成任务

- USV 已完成源码级 Topic 盘点，详见 `docs/usv_ros2_interfaces.md`；仍需 USV
  状态机负责人补齐运行样例、正式命令/ACK、车辆状态和安全接口，并完成 UAV 侧盘点。
- 由 UAV 负责人实现 UAV 生产适配器；由 USV 负责人实现 USV 生产适配器，并把
  `task_priority_manager.py` 接入真实任务管理节点。
- 共同确认 UAV↔USV 各消息的最终 `payload`、坐标系、状态枚举和完成/失败条件。
- 完成 Task4 checkpoint 持久化、超时看门狗、`SAFE_STOP` 和恢复验证。
- 填写真实 UAV geofence、Team Village Broker/网卡参数和正式配置。
- 使用电脑 B（官方模拟）、电脑 A（OCS）和两台 Orin 完成四机端到端联调。
- 覆盖断线重连、旧 run、重复消息、ACK 超时、畸形消息和车辆故障测试并保存日志。
- 在上述项目通过前，不把参考模块连接到真实 PX4、推进器、水泵、云台或夹爪。

## 测试

```bash
python3 -m unittest discover -s OCS -p 'test_*.py'
python3 -m py_compile OCS/*.py
```

当前基线：23 项单元测试通过。

不要提交密码、密钥、未脱敏日志、`.venv`、缓存或原始传感器数据。
