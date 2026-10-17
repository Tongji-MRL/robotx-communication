# Task3 通信与统一 Orin 工作区归位说明

这份说明用于把 Task3 的通信契约接入统一 USV Orin 工作区，避免在 Task3 包和通信包中
各维护一份相互漂移的协议实现。

## 归属边界

| 责任 | 最终目录 | 内容 |
|---|---|---|
| 车辆级 heartbeat | `src/usv_state_machine` | USV 整车状态、当前任务、位置、航向、健康状态 |
| Task3 事件 | `src/task3` | bay 选择、靠泊确认、喷水窗口、绿色 5 秒完成、14 位 Task3 状态 |
| 通用通信 | `src/robotx_communication` | envelope、heartbeat 校验、ACK、fault、task_report、序号和跨车转发 |

Task3 子状态机不单独发布车辆 heartbeat。它把当前 Task3 状态交给总状态机，由总状态机
在 `/tongji_mrl/twave/heartbeat` 中发布。

## 当前参考实现

Task3 侧当前参考实现位于 `robotx-dock-planner`：

- `dock_planner/task3_ros_contract.py`：Task3 事件和通用 JSON 字段的参考实现；
- `usv_task3_executor/communication_adapter.py`：Task3 事件到 progress/report 的联调节点；
- `TASK3_ROS_INTERFACE.md`：topic、字段和完成门控说明。

这些文件目前用于联调和字段评审，不应直接复制成第二个正式通信 executable。通用部分
确认后再提取到本仓库的协议/schema 和 USV production adapter。

## 三条输入链

```text
usv_state_machine  ->  /tongji_mrl/twave/heartbeat
Task3 child FSM    ->  /tongji_mrl/twave/task3/correct_bay
Task3 watering FSM ->  /tongji_mrl/twave/task3/sprayer_window
```

通信层再输出：

```text
/tongji_mrl/twave/progress
/tongji_mrl/twave/task_report
/tongji_mrl/twave/task_ack
/tongji_mrl/twave/fault
```

## Orin 同步规则

统一工作区是 `/home/robotx/robotx_ws`。它不是单独的 Git 仓库，不能在聚合后的 `src`
目录直接执行 `git pull`。应先在源仓库分支完成评审，再生成 staging，检查重复包并统一
构建；备份目录放到 `/home/robotx/robotx_backups`，不能放进 `src`。

构建和验证使用：

```bash
source /opt/ros/humble/setup.bash
source ~/robotx_ws/install/setup.bash
ros2 pkg prefix robotx_communication
ros2 pkg prefix usv_task3_executor
ros2 topic list -t
```

源码或依赖改变后才统一构建：

```bash
cd ~/robotx_ws
source /opt/ros/humble/setup.bash
colcon build --base-paths src --symlink-install --executor sequential
source install/setup.bash
```

真实 heartbeat、bay、喷水窗口和总规划器 topic 尚未完成现场闭环；在接入推进器、水泵、
云台或 PX4 前，先用 mock/rosbag 做无控制 dry-run。
