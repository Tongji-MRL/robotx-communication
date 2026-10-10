# T-Wave USV 状态机 dry-run 交接审查

审查日期：2026-10-10  
交付版本：`v0.1.0-dryrun`  
来源：`twave_mission_v0.1.0-dryrun.tar.gz` 及配套交接文档

文件校验：tar.gz SHA-256 `01c36b4ae9108b407d7e161cc83ed1cd219650763668662ac7f3e81ecc1d9a34`；
PDF SHA-256 `872dab87c4c25d1141577b14462d6a2d53b17c6d393596de767d866be2c28980`。

## 结论

可以部署到 USV Orin 做隔离的 ROS 2 Humble dry-run，但不能直接覆盖现有
`~/robotx_ws`，也不能当作已经接入真实船体、飞控或执行器的生产版本。

建议使用独立目录：

```text
~/robotx_mission_dryrun/twave_mission_v0.1.0-dryrun/
```

## 已确认内容

- `usv_main_fsm/`：Task1→Task3、Task4 抢占/恢复、checkpoint、SAFE_HOLD、SAFE_STOP
  和测试用安全锁存的纯 Python 决策核心。
- `ros2_ws/src/twave_mission_dryrun/`：ROS 2 节点、Fake USV Executor 和测试启动文件。
- `deploy/twave_mission/scripts/`：环境检查、构建、验收、启动、停止、状态和日志脚本。
- 当前 ROS 2 dry-run 话题使用 `/test/twave/mission/*` 和 `std_msgs/msg/String` JSON，
  不是已经冻结的正式 ROS 2 接口。
- `OCS/` 中的 `vehicle_protocol.py` 与 OCS adapter 可作为候选协议适配层；包内没有
  `RobotX_2026/gen/python` 官方生成模块，因此不能把这个包单独当成完整的官方 OCS 运行包。

## 本地离线验证

- `usv_main_fsm` 领域测试及协议测试：45 项通过。
- ROS bridge 测试：6 项通过，1 项因本环境集成测试条件跳过。
- 当前沙箱的 `colcon build` 受到系统 Python 安装路径权限限制，未据此宣称 Orin 构建通过；
  必须在 Orin 上按包内脚本实际构建并保存输出。

## 与现有 OCS 的关系

目前不能直接实现“电脑 A OCS → USV 状态机”的生产闭环，原因是：

1. 该包的 ROS 入口是测试话题，不是 MQTT runtime。
2. 测试 JSON schema 与仓库 `OCS/vehicle_protocol.py` 的生产候选 envelope 不同，必须由
   `MissionBridge`/车辆适配器完成转换。
3. Task4 的 `AllClear`/恢复授权在候选 adapter 中不会自动恢复，仍需正式安全策略和车辆
   负责人确认。
4. 包内 README 所称的测试结果来自交接说明；现场仍需重新运行验收脚本并留存日志。

## Orin 安装顺序

在确认目标 USV Orin 和备份位置后执行：

```bash
mkdir -p ~/uploads ~/robotx_mission_dryrun
# 从电脑 A 上传 tar.gz 后，在 Orin 上：
cd ~/uploads
tar -xzf twave_mission_v0.1.0-dryrun.tar.gz -C ~/robotx_mission_dryrun
cd ~/robotx_mission_dryrun/twave_mission_v0.1.0-dryrun
chmod +x deploy/twave_mission/scripts/*.sh
source /opt/ros/humble/setup.bash
deploy/twave_mission/scripts/check_environment.sh
deploy/twave_mission/scripts/build.sh
deploy/twave_mission/scripts/acceptance.sh
```

首次启动只能使用 dry-run 状态和日志目录：

```bash
export TWAVE_MISSION_STATE_DIR="$HOME/.local/state/twave-mission-dryrun"
export TWAVE_MISSION_LOG_DIR="$HOME/robotx_logs/twave-mission-dryrun"
deploy/twave_mission/scripts/start_dry_run.sh
```

不要删除现有 SAFE_STOP 锁存，不要接入推进器、泵、飞控、云台或夹爪。停止脚本中的
`pkill -f twave_mission_dryrun` 也必须先确认不会匹配其他项目进程。

## 放入正式主线前必须完成

- 冻结正式 ROS 2 topic、消息类型和任务完成/失败判据。
- 实现并验证 MissionBridge↔MQTT runtime，与现有 `tongji/robotx/v1/T-Wave/command`
  适配，不把测试 JSON 直接当作生产协议。
- 补齐 UAV FSM 对接、Task1/3 真实子状态机、执行器 ACK 和安全复位授权。
- 在 USV Orin 上完成构建、验收、日志和回滚记录后，才考虑与电脑 A/B 及 UAV Orin 联调。
