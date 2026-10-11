# T-Wave 主状态机（纯 Python 第一版）

`usv_main_fsm` 是 T-Wave 的任务级决策核心。它只产生领域动作：
`START_TASK`、`PAUSE_TASK`、`RESUME_TASK`、`SAFE_HOLD`、`SAFE_STOP`。这些动作**不是**
已经冻结的 ROS 2/MQTT 消息，后续由 T-Wave/T-Sky 适配器映射到双方确认的接口。

它不连接 MQTT、ROS 2、PX4、推进器、水泵或夹爪。扫描、导航、过门、靠泊、喷水、抓取和投放
仍完全由 USV/UAV 子状态机负责；主状态机只接受它们提供的 ACK、权威完成事件和安全暂停进度。

## 行为

- 新建协调器从 `IDLE` 开始；适配器可调用 `arm_for_run_start()` 进入 `WAIT_RUN_START`。
- `RUN_START` 启动 Task1；权威 Task1 完成事件启动 Task3；权威 Task3 完成事件进入 `COMPLETED`。
- Task4 先向受影响子状态机发送 `PAUSE_TASK`；只有全部 ACK 明确 `safe_paused` 并携带 progress
  marker 后，才原子保存 checkpoint 并发送 `START_TASK(TASK4)`。
- Task4 完成后仍需要显式恢复许可和车辆安全确认。`RESUME_TASK` 使用新的内部 `command_id`。
- `SAFE_STOP` 锁存；旧 run、重复事件、迟到 ACK、ACK 超时、执行超时或断联都不会自动恢复运动。
- 构造器会读取已有 checkpoint 作为恢复证据，但不会自动发送任何恢复动作。

## Windows CMD

在仓库根目录运行：

```cmd
python -m unittest discover -s usv_main_fsm\tests -p "test_*.py"
python -m usv_main_fsm.simulate normal
python -m usv_main_fsm.simulate task4
python -m usv_main_fsm.simulate_integration normal
python -m usv_main_fsm.simulate_integration task4
```

## 第二阶段候选协议适配

这些映射只在纯 Python FakeAdapter 中验证，未增加 ROS 2/MQTT 生产连接，也没有修改
`OCS/` 下的任何协议实现。

| 领域动作/事件 | 当前候选适配 | 状态 |
|---|---|---|
| OCS `run_start`、`task4_*`、`safe_stop` | `vehicle_protocol` v1 的 T-Wave `command` envelope | 输入校验、候选 ACK 完成 |
| `START/PAUSE/RESUME/SAFE_*` → T-Wave | `CandidateRos2Command`，`twave-task-command-v0` | 候选，待 ROS 2 负责人冻结 |
| `START/PAUSE/RESUME/SAFE_*` → T-Sky | `fsm_protocol` v1 envelope；含 domain `command_id` | 消息/ACK/去重已用 FakeTransport 验证；message type 为候选 |
| `task_report` / `fault` → OCS | `vehicle_protocol` v1 候选 envelope | 仅序列化，不推断官方报告 |

Task1/Task3/Task4 的参与载具可通过 `MissionCoordinator(task_targets=...)` 配置；默认仍是
双车参与以保持第一阶段行为。Task3 的 `CANDIDATE_TASK3_ARM` 只是准备任务，FakeUAVFSM 不会因
它的 ACK 自动开始 delivery，必须再获得有效 delivery request 和调度许可。

## 待适配/冻结的接口

需要 USV/UAV 负责人冻结：领域 action 到 ROS 2/MQTT 的映射、每项命令的正式 ACK schema、Task1/3/4
权威完成事件、Task4 解除条件、车辆安全状态，以及 `SAFE_STOP` 与硬件急停/PX4 failsafe 的边界。
