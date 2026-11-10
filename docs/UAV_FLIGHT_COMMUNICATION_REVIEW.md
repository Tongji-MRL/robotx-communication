# UAV-only Flight 通信审计（2026-11-10）

## 范围与结论

本审计只检查本地最新工作区；没有连接 RoboCommand 正式 Broker、没有发送
RunDeclaration，且没有发布 arm、takeoff、land 或任何飞行动作。

| 项目 | 已验证 | 当前结论 |
|---|---|---|
| 官方预运行 Heartbeat 的 `run_id` | 是 | `RxReport` 和 `Heartbeat` 均没有该字段。有效 Declaration 后、RunStart 前允许上报；`run_id` 仅在 OCS 缓存中关联。 |
| 身份 | 是 | ROS 原始 `UAV1` 仅通过配置显式映射为官方 `T-Sky`。官方上行 topic 为 `robocommand/robotx/TONG/T-Sky/report`。 |
| 心跳缓存与频率 | 是 | 完整、真实且不超过 3 秒的样本才进入缓存；Gateway 每 0.5 秒尝试发布，报告序号按车辆连续。 |
| QoS1 发布确认 | 是 | `OcsClient._publish()` 调用 `wait_for_publish()` 且检查 MQTT rc；心跳日志在该调用返回后写出 `HEARTBEAT_PUBACK`。 |
| Orin 原始遥测字段 | 否（不足） | 已审计的 `uav_status_json_node.py` 不发布 `timestamp_unix_ms`、roll/pitch、`current_task`、`source_mode` 或 `health.fcu_connected`。因此真实现场消息会被安全拒绝。 |
| `TASK_NONE` | 条件成立 | Orin 权威任务状态契约中明确出现的 JSON `current_task: null` 映射为 `TASK_NONE`；不得由 `GROUNDED` 推断，字段缺失或未知值仍拒绝。 |
| 注册号 | 配置待现场复核 | `config.flight.local.json` 为 `TONG-53580`。仅可在其确为已核验的 team-code + CAAS sticker number 时使用。 |
| FCU 围栏回读 | 否 | 当前 Orin `uav_geofense_pub` 是下发 String 的原样 echo；它不是 PX4/FCU 已应用证明。 |
| 真实 UAV RunStart 接收与 ACK | 否 | 没有发现可验证的 Orin 接收 topic、接收者或 applied ACK 合约。UAV-only Gateway 会记录阻塞，而不会借用 T-Wave FSM。 |

## 修改内容

| 文件 | 修改 |
|---|---|
| `OCS/ocs_client.py` | UAV 状态流增加 `UAV_STATUS_RECEIVED`、`HEARTBEAT_CACHED`、`HEARTBEAT_REJECTED`；官方 Heartbeat 在 QoS1 返回后打印解码后的身份、类型、任务、飞行阶段、注册号和 `HEARTBEAT_PUBACK`。 |
| `OCS/heartbeat_cache.py` | 保留预 RunStart 的合法缓存条目，RunStart 后仅在内部把新 `run_id` 绑定到新鲜条目；不写入 Protobuf。 |
| `OCS/uav_status.py` | 保持 3 秒新鲜度与真实字段门禁；不补造 AUTO、姿态、任务、健康、时间或注册号。 |
| `OCS/ocs_gateway.py` | Echo 回读只做坐标/HAE 诊断，状态为 `FCU_GEOFENCE_UNVERIFIED`，绝不触发自动 Declaration。围栏下发还需要单独的 `--allow-uav-geofence-apply` 飞手授权；默认仅计算。UAV-only RunStart 仍不走 T-Wave。 |
| `OCS/geofence_planner.py` / `OCS/ocs_client.py` | `auto_course` 是 Course 内的保守候选；显式 `auto_course_union` 用 Shapely/GEOS 求 Course+Transit 并集并向内缓冲 1 m。凹形、无效、自交、多区域、孔洞或无法表示为单闭环时拒绝。 |
| `OCS/config.flight.local.json` | Flight 配置选择显式 `auto_course_union`，对应完整评估运行区；仍不会自动写 PX4。 |
| 测试 | 覆盖预 RunStart `TASK_NONE` Heartbeat 的 Protobuf 解码、T-Sky/TYPE_UAV/注册号/飞行阶段、Echo 回读不放行、错误回读和隔离 RunStart receiver。 |

## 围栏几何依据

官方 `RxCourse` 提供 `corners`（Course Boundary）和可选
`uav_transit_area`。协议的最宽允许范围是二者并集；Flight 评估场景若批准
整个运行区，应显式选择 `auto_course_union`。该模式：

1. 在局部 WGS84 投影中构造两个 Polygon；
2. 以 GEOS 做并集，向内 buffer 1 m；
3. 只接受无孔的单一 Polygon；
4. 反投影回 `(latitude, longitude)`，闭合首尾顶点；
5. 再以 `validate_geofence_within_course` 验证顶点、边和内部仍在批准并集内。

`auto_course` 不读取 Transit，使用 Course 内的保守候选；它不是完整 Flight
运行区的默认替代。围栏高度字段始终是 `uav_geofence_max_altitude_hae_m`，其值
40.0 仅按 HAE 解释；不得把 AGL 或 AMSL 直接填入。

## 最小的 Orin 接口缺口

需要 UAV 队员提供同一时刻、来自 FCU/权威机载状态机的状态快照，至少包括：

```json
{
  "timestamp_unix_ms": 0,
  "roll_deg": 0.0,
  "pitch_deg": 0.0,
  "current_task": "TASK_NONE",
  "source_mode": "real",
  "health": {"fcu_connected": true},
  "uav_registration": "TONG-53580"
}
```

`timestamp_unix_ms` 必须由可靠时间同步提供，不能直接复用 PX4 boot time；
roll/pitch 可由已订阅的 `VehicleAttitude` 四元数在 Orin 上按已确认 PX4 坐标约定
计算。任务必须来自权威任务状态机；该接口的显式 `current_task: null` 表示尚未开始任务，并映射为 `TASK_NONE`。健康必须来自 FCU 连接/健康接口。

还需要单独的 FCU 围栏 readback 接口，包含 FCU source identity、读取时刻、关联
的候选/版本，以及 FCU 实际已应用的闭合水平点和 HAE 高度上限。现有
`/tongji_mrl/tsky/uav_geofense_pub` echo 不能满足该接口。

## RunStart

`RxCommand.RunStart` 同时校验 team、递增 command seq、正 `run_id`，以及与当前
Declaration 相同的 `declaration_seq`。UAV-only 收到后不会发往 T-Wave FSM，也不会
假装 Orin 已接收。当前只存在隔离测试 topic
`/tongji_mrl/offline_test/run_start`；它要求单个、显式声明 `read_only=true` 且
`actuation=false` 的 receiver，不能替代真实 Orin 接口或 ACK。

## 启动命令（按窗口）

以下命令都不发送正式 Declaration，也不执行飞行动作。先在每个 ROS 窗口确认
Domain 一致。

### Windows OCS PowerShell

```powershell
cd D:\RobotX\robotx-rc-lab
$env:ROS_DOMAIN_ID = "62"
$env:ROS_LOCALHOST_ONLY = "0"
ros2 topic echo /tongji_mrl/tsky/uav_status std_msgs/msg/String
ros2 topic info --verbose /tongji_mrl/tsky/uav_status
python .\OCS\ocs_gateway.py --config .\OCS\config.flight.local.json --vehicle-mode uav_only --ros2-diagnose
```

启用任何正式连接前，先检查 Gateway 输出：应出现 `UAV_STATUS_RECEIVED`；若字段
不足，应出现逐项 `HEARTBEAT_REJECTED`。只有字段齐全时，才应出现
`HEARTBEAT_CACHED`、`HEARTBEAT_PUBLISHED`、`HEARTBEAT_PUBACK`。这里的
`--ros2-diagnose` 不启动正式 Broker 连接。

### Ubuntu / Orin 终端

```bash
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=62
export ROS_LOCALHOST_ONLY=0
ros2 topic echo /tongji_mrl/tsky/uav_status std_msgs/msg/String
ros2 topic echo /tongji_mrl/tsky/uav_geofense_sub std_msgs/msg/String
ros2 topic echo /tongji_mrl/tsky/uav_geofense_pub std_msgs/msg/String
ros2 topic info --verbose /tongji_mrl/tsky/uav_status
```

## 正式连接前清单

1. 配置贴纸号与实机 CAAS 登记完全一致。
2. Orin 状态消息包含上述所有权威字段，并连续 3 秒内保持新鲜；OCS 已观察到
   `STATE_AUTO`（不得由地面状态推断）。
3. `TASK_NONE` 来自 Orin 明确的 `current_task: null` 或任务状态机值，不是 OCS 或 Gateway 默认值。
4. FCU readback 接口可证明本轮候选的水平围栏和 40.0 m HAE 已实际应用；echo 不算。
5. 实际 Orin RunStart receiver 和 correlated applied ACK 已完成隔离验证。
6. 使用测试 Broker 或离线测试跑完整链路。正式运行前由飞手明确批准围栏写入、
   `--allow-uav-geofence-apply` 与 `--publish-declaration`；本审计没有执行三者。
