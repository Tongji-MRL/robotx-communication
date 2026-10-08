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
- `OCS/task_priority_manager.py`：USV 任务协调器的参考状态机，不由 OCS 调用。
- `docs/usv_task_coordinator_deployment.md`：参考状态机在 USV-Orin 上的部署边界和适配清单。
- `OCS/vehicle_link_contract.md`：内部协议正式草案。
- `docs/`：架构、通信总览和开发主线。
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

## 测试

```bash
python3 -m unittest discover -s OCS -p 'test_*.py'
python3 -m py_compile OCS/*.py
```

不要提交密码、密钥、未脱敏日志、`.venv`、缓存或原始传感器数据。
