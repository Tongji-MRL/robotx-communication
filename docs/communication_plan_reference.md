# 《通信及规划》对照说明

这份说明对应本地收到的《通信及规划》PDF（6 页，SHA-256：`53c276fbc6ea8715bba30fa5fc5d31ec76e99b731902533ac91fbf51f43a370b`）。它是团队规划参考，不是官方 RoboCommand schema，也不是已经验收的 ROS 2 生产接口。

## 已确认并采用的部分

### 官方链路

官方链路与仓库现有 OCS 实现一致：只有 OCS 连接 RoboCommand，使用官方 Protobuf。

| 用途 | Topic | 方向 |
|---|---|---|
| 课程配置 | `robocommand/robotx/course` | 官方 → OCS |
| 车辆报告 | `robocommand/robotx/<team_id>/<vehicle_id>/report` | OCS → 官方 |
| 队伍请求 | `robocommand/robotx/<team_id>/request` | OCS → 官方 |
| 队伍命令 | `robocommand/robotx/<team_id>/command` | 官方 → OCS |

队伍标识暂用 `TONG`，车辆标识暂用 `T-Sky` 和 `T-Wave`。官方消息仍由 OCS 负责 Protobuf 编解码、序号校验、日志和报告转换。

### 任务规划职责

PDF 中的“主规划器/主状态机”在当前团队架构中应解释为 **USV 的任务协调器**，不是 OCS，也不是新增的一台独立电脑：

- OCS 转发 `RUN_START` 和官方 Task 4 命令；不选择当前 Task。
- USV 决定任务顺序、Task 4 抢占、checkpoint、恢复和 UAV 协调。
- UAV 执行 USV 下达的任务级命令，并回报状态和任务结果。
- OCS 接收 USV 的权威汇总和两车必要状态，再生成官方报告；不根据超时自行猜测任务完成。

## PDF 中仍需冻结的内部接口

下列名称可以作为联调候选，但在状态机负责人确认前不能直接视为生产接口：

| 候选链路 | PDF 中的候选 Topic/内容 | 需要确认 |
|---|---|---|
| OCS → USV | `/tongji_mrl/mission/run_start`、`/tongji_mrl/mission/task4_cmd` | 是否映射到现有 `tongji/robotx/v1/T-Wave/command`；命令字段、`run_id`、`command_seq`、ACK |
| USV → OCS | `/tongji_mrl/mission/task_report`、`/status`、`/fault` | 是否统一走现有 `task_report`/`fault`；谁产生 `official_report` |
| USV → UAV | `/tongji_mrl/twave/task_cmd` | Task 1/3/4 命令枚举、参数、过期时间和 ACK |
| UAV → USV | `/tongji_mrl/tsky/progress`、任务结果 | progress 的阶段枚举、完成判据、失败类型和证据字段 |
| USV → 主状态机 | `/tongji_mrl/twave/progress`、`task1_result` | 当前主状态机即 USV 时，不应再设计一条 USV 自己回传自己的重复链路 |

当前仓库的 OCS↔车辆协议仍以 `OCS/vehicle_link_contract.md` 为准；UAV↔USV 任务数据仍以 `docs/uav_usv_state_machine_link.md` 为参考，最终以两车状态机负责人联调确认的 ROS 2 映射为准。

## 必须补齐的内容

1. **统一命名和封装**：确定是 ROS 2 Topic 还是 MQTT Topic；每条消息至少包含 `message_id`、`run_id`、`seq`、`source`、`target`、`sent_at` 和协议版本。
2. **正式 ACK**：命令接受、拒绝、执行中、完成和失败必须能按 `command_seq` 对应，不能用普通 progress 猜 ACK。
3. **Task 4 抢占/恢复**：两车先回报暂停确认和断点，再执行 Task 4；收到 AllClear 后还要有明确的 `resume`/安全许可，不能自动恢复。
4. **心跳直报 OCS**：UAV/USV 以 2 Hz 向 OCS 提供可映射到官方 Heartbeat 的位置、模式、当前任务、健康和故障信息。
5. **任务结果归属**：Task 1/3 由 USV 汇总必要的 UAV/USV 结果并明确生成权威结果；OCS 只做官方格式转换和发送。
6. **失败分类**：正常任务失败走任务状态/报告；通信中断、执行器或安全异常走 fault，并保留恢复状态和证据。
7. **真实适配器**：USV/UAV 状态机负责人把这些协议映射到实际 ROS 2 节点；当前 dry-run 的 `std_msgs/msg/String + JSON` 只能用于验收，不是最终接口。

## 联调采用顺序

先用数字或 JSON 做消息收发验证是可以的，但只作为测试 profile：

1. 电脑 B 官方模拟端 → OCS → USV Orin：验证 RunStart、Task 4、ACK 和日志。
2. USV Orin → UAV Orin：验证 Task 命令、progress、任务结果和去重。
3. USV 汇总 → OCS → 电脑 B：验证 Heartbeat、Task 1/3 官方报告、正常失败和 fault。
4. 最后再把测试消息替换为真实 ROS 2 状态机和安全适配器；在此之前不接真实执行器。

