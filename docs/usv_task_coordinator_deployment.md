# USV 任务协调器部署说明

更新时间：2026-10-08

## 结论

`OCS/task_priority_manager.py` 可以作为 USV-Orin 上任务协调器的核心决策库，
但当前版本不能直接作为完整 ROS 2 节点或车辆控制进程部署。

它目前具备：

- Task1/Task3 状态断点保存；
- Task4 抢占、ACK、Readiness 和恢复状态机；
- 重复官方序号和错误状态的基础校验；
- 纯 Python、无 MQTT/ROS2/PX4/执行器依赖。

它目前不具备：

- 读取 OCS 内部 JSON `command` envelope 的生产入口；
- 真实 USV/UAV 状态订阅；
- ROS 2 service/action/topic 发布；
- 对推进器、导航、飞控或任务执行器的控制；
- 进程重启后的 checkpoint 持久化；
- watchdog、急停和执行器安全互锁。

## 为什么不能直接运行

当前参考测试用 `robotx.rx_commands_pb2.RxCommand` 模拟官方命令。正式架构中，
USV 不连接官方 RoboCommand，而是收到 OCS 发来的内部 JSON：

```text
OCS command envelope
  → USV command_handler
  → TaskPriorityManager
  → USV/UAV 任务执行接口
```

因此不能把 `task_priority_manager.py` 直接接到电机、导航或 ROS 2 节点上。
必须先增加一个 USV 适配层，把内部 JSON 命令转换成状态机输入，再把状态机输出
转换成 USV/UAV 执行动作和 `ack`/`task_report`。

## USV-Orin 必须补齐的四个接口

### 1. 命令入口

订阅：

```text
tongji/robotx/v1/T-Wave/command
```

至少处理：

- `run_start`；
- `task4_assistance`；
- `task4_keep_out_zone`；
- `task4_all_clear`；
- `task4_moving_object`；
- `task4_readiness_confirm`。

USV 收到 Task4 后，自己决定当前 Task1/Task3 是否暂停、是否通知 UAV，以及何时恢复。
OCS 的 `preempt` 字段不能替代 USV 的本地决策。

### 2. 状态输入

USV 任务协调器需要持续获得：

- USV 当前任务、阶段和 checkpoint；
- UAV 当前任务、阶段和必要结果；
- Task4 执行阶段、风险状态和恢复条件；
- 故障、急停和通信超时。

这些信息可以来自 USV 自己的 ROS 2 状态机和 USV↔UAV 内部链路，不要求 OCS 转发全部
原始 ROS 2 消息。

### 3. 执行动作出口

状态机输出不能直接当作 ROS 2 消息。需要由适配器映射到团队实际接口，例如：

- 暂停/保持当前任务；
- 执行 AssistanceRequest 或 KeepOutZone；
- 通知 UAV 进入避让、待命或恢复；
- Task4 完成后恢复原 Task1/Task3 checkpoint；
- SAFE_STOP/急停覆盖所有普通任务。

实际 ROS 2 topic、service 或 action 名称需要由 USV 软件组提供后再填写。

### 4. OCS 回报出口

USV 向 OCS 发布：

- `ack`：确认是否接受 OCS 命令，带 `command_seq`；
- `task_report`：阶段、完成/失败和必要证据；
- `official_report`：USV 已经汇总 UAV/USV 信息后，明确要求 OCS 发布的官方报告；
- `fault`：拒绝、超时、执行器故障和恢复状态。

OCS 只把 `official_report` 转成官方 Protobuf，不根据单独的 `phase=COMPLETE` 自己
判断任务完成。

## 推荐部署顺序

1. 在 USV-Orin 上以 dry-run 方式接入内部 `command_handler`，只打印动作，不连接执行器。
2. 用电脑 B 官方 Broker、电脑 A OCS Gateway 和两个 Orin-LQ 验证 `RunStart → USV ACK`。
3. 验证 Task4 官方命令只到 T-Wave，USV 再通过自己的链路协调 T-Sky。
4. 接入真实 ROS 2 状态输入，但仍保持执行器 dry-run。
5. 验证断点恢复、重复命令、旧 `run_id`、断线、ACK 超时和 SAFE_STOP。
6. 最后才允许连接真实导航和执行器。

在完成上述适配前，`task_priority_manager.py` 的定位是“可测试的决策核心”，不是
“可直接控制车辆的完整程序”。

