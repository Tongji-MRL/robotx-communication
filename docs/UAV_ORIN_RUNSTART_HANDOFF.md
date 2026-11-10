# UAV-Orin RunStart 接入：最小修改交接意见

## 目标与边界

目标是让 OCS 已验证的官方 RoboCommand `RunStart` 通过 ROS 2 到达主规划器；
主规划器再通过 ROS 2 调度 UAV-Orin。UAV 在本机安全门禁通过后请求自主起飞，
并通过主规划器状态、真实遥测和官方报告回传结果。

本意见不授权 OCS 直接发布 PX4 offboard setpoint、强制解锁或直接执行器控制。
`RUN_START` 不是“无条件起飞”：起飞判定与 PX4 命令只应在 Orin 的任务执行
节点内完成。

## 已确认现状

Orin ROS 图中存在：

- `/tongji_mrl/tsky/uav_status` (`std_msgs/msg/String`)
- `/fmu/in/vehicle_command` (`px4_msgs/msg/VehicleCommand`)
- `/fmu/out/vehicle_command_ack`
- `/fmu/out/vehicle_status_v1`、`vehicle_global_position`、`vehicle_attitude`
- `/fmu/out/vehicle_land_detected`、`battery_status`、`failsafe_flags`
- UAV 围栏 topic：`/tongji_mrl/tsky/uav_geofense_sub` / `_pub`

未发现 RunStart/mission/takeoff ROS topic 或已在线的任务执行节点。因此 OCS
当前正确地在 UAV-only 下阻断 RunStart，不能仅改 OCS 就实现起飞。

已安装的 `pymavlink` dialect 文件仅证明 Python 库存在，不能作为有可用 MAVLink
控制进程或已有起飞实现的证据。

## 通信边界：官方 MQTT、Heartbeat MQTT、其余队内 ROS 2

按已确认的团队设计，通信边界如下：

```text
RoboCommand <-> OCS: 官方 MQTT（Course、Declaration、RunStart、官方 Report）

UAV -> OCS: /tongji_mrl/tsky/heartbeat（队内 MQTT；后续常态运行）
UAV -> OCS: /tongji_mrl/tsky/uav_status（ROS 2；当前 flight test 状态验证）

OCS <-> 主规划器 <-> UAV/USV: ROS 2（Course、RunStart、Task4、进度、结果、任务命令）
```

- Flight test 当前使用 ROS 2 `/tongji_mrl/tsky/uav_status` 验证真实状态；它是临时
  现场验证入口，不与 MQTT heartbeat 同时作为同一 OCS 官方 Heartbeat 的来源；
- 后续常态的 UAV heartbeat 走 MQTT `/tongji_mrl/tsky/heartbeat`，由 OCS 映射为
  官方 `RxReport.heartbeat`；
- `RunStart`、Course、Task4、主规划器状态、UAV task command、UAV progress/result/checkpoint
  全部走 ROS 2；不使用队内 MQTT command/ack 作为这些流程的接口；
- 官方 MQTT topic 仅限 RoboCommand 与 OCS，UAV 与主规划器不直接连接官方 broker。

## 从 Course 到飞行的前序流程和缺口

```text
RBC RxCourse
  -> OCS 校验 Course/几何
  -> OCS 发布 Orin 围栏候选（ROS 2）
  -> Orin 实际写入 FCU，并发布 FCU-applied readback（ROS 2）
  -> OCS 验证围栏 + HAE 高度，发布 RunDeclaration
  -> Orin 当前真实状态经 ROS 2 /tongji_mrl/tsky/uav_status 验证
  -> 后续常态 Heartbeat 经队内 MQTT 形成官方 Heartbeat
  -> RBC RunStart
  -> OCS 官方字段校验
  -> OCS 发布 /tongji_mrl/mission/run_start（ROS 2）
  -> 主规划器切换至 MAP_EXECUTE（ROS 2；当前代码没有 APPLIED 回执）
  -> 主规划器发布 /tongji_mrl/tsky/task_cmd（ROS 2）
  -> Orin 本地门禁与自主起飞
  -> AIRBORNE 状态 + 后续 task/fault 上行
```

### 围栏接口：当前必须补齐

OCS 已使用以下现有 topic（拼写 `geofense` 是现有固定接口的一部分，不要擅自改名）：

```text
OCS -> Orin candidate: /tongji_mrl/tsky/uav_geofense_sub
Orin -> OCS FCU readback: /tongji_mrl/tsky/uav_geofense_pub
```

两端均为 `std_msgs/msg/String`。OCS 下发的是闭合坐标数组：

```json
[[lat, lon], [lat, lon], [lat, lon], [lat, lon]]
```

Orin 只能在飞控实际完成写入后发布 readback，且必须严格是：

```json
{
  "points": [[lat, lon], [lat, lon], [lat, lon], [lat, lon]],
  "max_altitude_m": 40.0
}
```

`points` 必须与下发闭合环逐点一致，`max_altitude_m` 在当前 OCS 合同中代表 HAE
高度。不能发布“收到候选围栏”的回显冒充 FCU-applied readback；否则 OCS 应继续
保持 `GEOFENCE_BLOCKED`，不发布正式 Declaration。

### OCS 侧现有阻断点

1. 未收到或未验证 FCU-applied 围栏 readback：Declaration 不发布；
2. Declaration 的 Course 指纹与 RunStart 到达时的 Course 不一致：RunStart 拒绝；
3. `team_id`、递增 command `seq`、`declaration_seq`、非零 `run_id` 任一失败：RunStart 拒绝；
4. 正常 UAV-only 模式当前会记录 `RUNSTART_ORIN_INTERFACE_UNAVAILABLE`，不会下发；
5. 主规划器 Course/RunStart 状态、Orin task command 拒绝或遥测超时：后续生产版本必须
   保持阻断，且不自动重发。

### 已核对的 FSM 现状（2026-11-09 main）

当前主规划器订阅 `/tongji_mrl/mission/run_start` 和
`/tongji_mrl/mission/course_config`。只要它仍处于 `WAIT_FOR_BEGIN`、收到 JSON
对象且 `command` 为 `begin`，并且已经收到 course config，就会切换为
`MAP_EXECUTE`，向 `/tongji_mrl/tsky/task_cmd` 发布 UAV 的 MAP `begin`，同时也会向
T-Wave 发布 USV 的 MAP `begin`。当前代码**没有** UAV-only 开关、RunStart 的
`run_id`/官方序号去重校验、结构化 `APPLIED` 回执或 `preflight.blocking_errors`。

下文涉及 `run_start.application_state=APPLIED` 和 `preflight` 的内容均为**建议新增
的接口合同**，不是当前 FSM 已实现的消息格式。OCS 在未实现双方同意的合同前，不能把
现有 `/tongji_mrl/mission/status` 当作该回执。

### 不可自主补救错误：主规划器声明，OCS 负责阻断

OCS 不应从单个 PX4 字段猜测“可否起飞”。主规划器应在 `/tongji_mrl/mission/status`
提供结构化的起飞准备状态，最小建议：

```json
{
  "preflight": {
    "ready": false,
    "blocking_errors": ["GEOFENCE_NOT_APPLIED"],
    "updated_at": "2026-11-10T00:00:00Z"
  }
}
```

`blocking_errors` 只列无法由 OCS 自主补救、必须由飞手/Orin/场地处置的错误：
`FCU_DISCONNECTED`、`GPS_OR_GLOBAL_POSITION_INVALID`、`GEOFENCE_NOT_APPLIED`、
`FAILSAFE_ACTIVE`、`BATTERY_CRITICAL`、`MANUAL_TAKEOVER_UNAVAILABLE`、
`PX4_COMMAND_REJECTED`。主规划器必须同时保留人类可读的 detail。

后续 OCS 修改中，只有 `preflight.ready=true`、错误为空且状态新鲜时才可将已验证的
官方 RunStart 发布给主规划器；否则 OCS 记录并显示阻断原因。OCS 不自动清除或
“修复”这些错误，也不把短暂的 ROS 2 topic 存在当作 ready。

## 给 UAV 负责人的修改清单（不改 FSM，不由 UAV 接收 RunStart）

职责边界：OCS 将官方 RunStart 交给主规划器；主规划器负责状态机和后续任务编排；UAV
**不订阅** `/tongji_mrl/mission/run_start`，也不连接官方 RBC MQTT。UAV 只接收主规划器
发出的 ROS 2 任务命令，并依据本机飞行安全门禁执行或拒绝。

本节以 FSM 当前 `main` 的实际消息为准。下面 `APPLIED` 和 `preflight` 的段落是
OCS/FSM 未来协议建议，不是交给 UAV 负责人实现的事项。

### 1. ROS 2 RunStart、主规划器状态和 UAV task command 合同

主规划器接收以下 OCS 消息：

```text
/tongji_mrl/mission/run_start       std_msgs/msg/String
/tongji_mrl/mission/course_config   std_msgs/msg/String
/tongji_mrl/mission/task4_cmd       std_msgs/msg/String
```

OCS 当前实际发布的 RunStart JSON 比旧例子 `{\"command\":\"begin\"}` 更完整，
必须保留并由主规划器使用：

```json
{
  "schema_version": "twave-mission-run-v1",
  "command": "begin",
  "run_id": 42,
  "command_id": "robocommand:42:12:run-start",
  "official_command_seq": 12
}
```

主规划器验收后在 `/tongji_mrl/mission/status` 回报。为与当前 OCS 实现兼容，状态
必须包含以下 RunStart ACK；`ACCEPTED` 表示规划器已应用，不代表已经离地：

```json
{
  "schema_version": "twave-mission-status-v2",
  "timestamp": "2026-11-10T00:00:00Z",
  "simulation": false,
  "run_start": {
    "run_id": 42,
    "official_command_seq": 12,
    "command_id": "robocommand:42:12:run-start",
    "accepted": true,
    "application_state": "APPLIED"
  }
}
```

主规划器再向 UAV 发布具体任务命令：

```text
/tongji_mrl/tsky/task_cmd           std_msgs/msg/String
```

UAV 负责人须确认订阅执行器的 package、launch 文件及进程名；若尚不存在，最小新增一个
订阅执行器。它校验 `vehicle == "uav"`，并支持 FSM 当前实际会发布的：

```json
{"vehicle":"uav","task":"MAP","progress":null,"error":null,"command":"begin"}
{"vehicle":"uav","task":"TASK1","progress":null,"error":null,"command":"begin"}
{"vehicle":"uav","task":"TASK3","progress":null,"error":null,"command":"begin"}
```

Task4 的 `task` 为 `TASK4`，`command` 是含 `type: "TASK4_BEGIN"`、`command_seq`、
`target_vehicle` 与 `position` 的对象；恢复命令为原任务配合 `command: "resume"`。
当前 FSM 的 task command **没有** `run_id`，UAV 不能把它当成接收前提。未来若需跨重启
去重，应由 FSM 与 OCS 同步扩展 payload，不能由 UAV 自行生成。

收到 MAP `begin` 后，只能调用已有的本机自主起飞/地图任务入口；不得通过 MQTT 或临时
脚本绕过该入口，直接发送解锁、起飞或航点 PX4 命令。同一运行期间重复 `begin` 必须幂等；
门禁不通过时不发送 PX4 控制命令，并发布可诊断的拒绝原因。

UAV 的起飞结果不能用主规划器 ACK 冒充。只有 PX4 真实状态确认离地后，UAV 才可
将 `flight_phase` 更新为 `AIRBORNE`，主规划器再将真实进度/报告上送 OCS。

### 1.1 交付前逐项核对（UAV 负责人）

- 订阅 `/tongji_mrl/tsky/course_config`：保存并校验 FSM 转发的场地配置；不能把仅收到
  topic 视为已生成或已加载航线。
- 订阅 `/tongji_mrl/tsky/task_cmd`：按上一节处理 MAP、Task1、Task3、Task4 与 resume；
  新增/修改处以中文注释写明“FSM 命令入口”和对应的本机门禁。
- 发布 `/tongji_mrl/tsky/progress`：每条至少保持 `vehicle`、`task`、`progress`、`error`；
  FSM 以 `MAP_FINISH`、`TASK1_FINISH`、`TASK3_FINISH` 且 `error:null` 作为后续状态推进
  条件，因此不得在任务尚未完成时发布这些完成值。
- 发布 `/tongji_mrl/tsky/checkpoint`：Task4 抢占与恢复前，提供当前任务、进度与
  `command:"checkpoint"`；没有真实断点时应拒绝/上报错误，不能伪造断点。
- 持续发布真实 `/tongji_mrl/tsky/uav_status`，并保留 FCU 连接、定位、姿态、速度、HAE、
  时间戳和飞行阶段的原始语义；Heartbeat 的 MQTT 上报另行实现，绝不作为 task command。
- 保持现有 geofence 写入和 FCU readback；只有飞控实际应用后才回读成功，不允许用本地
  候选值模拟 FCU 已应用。

最小联调验收：在不让 PX4 执行起飞的受控条件下，FSM 收到 Course 与 RunStart 后，UAV
执行器应能记录收到 MAP begin 并给出“门禁拒绝”的真实原因；在经批准的飞行条件下，才由
该同一执行器调用已有自主起飞流程，随后用真实状态更新 `FLIGHT_PHASE_AIRBORNE`。

### 2. 起飞前门禁（仅由 Orin 判断）

在向 PX4 发任何命令前，要求每项都有实时来源并记录拒绝原因：

- FCU 已连接，`vehicle_status` 与 required PX4 topic 均新鲜；
- 全局定位可用，纬度/经度和椭球高（HAE）有效；
- `vehicle_land_detected` 明确为已着陆；
- 无 failsafe/关键故障；
- 电池满足队伍阈值；
- 当前已确认的 geofence 已由飞控实际应用；
- 现场飞手确认可接管，且用于测试的 kill、RTH 和手动接管均可用；
- 未进入已有 run，且本节点尚未发出起飞请求。

禁止使用 PX4 强制解锁。使用项目已有、经飞控负责人确认的自主起飞流程；如目前
没有该流程，先实现和单独验证它，不能把 MQTT 接收器变成临时 PX4 控制器。

### 3. OCS 所需真实状态 JSON

现有 `/tongji_mrl/tsky/uav_status` 在发布真实数据后必须包含：

```json
{
  "vehicle_id": "UAV1",
  "vehicle_type": "TYPE_UAV",
  "state": "STATE_AUTO",
  "flight_phase": "FLIGHT_PHASE_GROUNDED",
  "position": {"latitude": 1.0, "longitude": 103.0},
  "altitude_hae_m": 10.0,
  "spd_mps": 0.0,
  "heading_deg": 0.0,
  "roll_deg": 0.0,
  "pitch_deg": 0.0,
  "timestamp_unix_ms": 0,
  "source_mode": "real",
  "current_task": "TASK_NONE",
  "health": {"fcu_connected": true},
  "uav_registration": "TONG-53580"
}
```

说明：

- `timestamp_unix_ms` 使用 Orin 采样时的 Unix 毫秒时间，Windows 与 Orin 时钟偏差
  必须低于 OCS 的 3 秒新鲜度窗口；
- `altitude_hae_m` 必须确认 PX4 源字段确实是 HAE/ellipsoid 高度，不能把 MSL 或
  local NED 高度贴上 HAE 标签；
- `source_mode`、FCU 连接、任务状态和飞行阶段不得由 OCS 猜测或补造；
- 离地后只能由真实 PX4/执行器状态将 `flight_phase` 更新为 `AIRBORNE`。

## 后续任务交互：本次先冻结 ROS 2 接口，不要伪造完成

RunStart 后的交互需要提前统一，但不应在飞行测试前临时把视觉检测、PX4 ACK 或进程
退出解释为任务完成。

### UAV/主规划器 -> OCS（ROS 2）

| Topic | 用途 | 当前要求 |
|---|---|---|
| `/tongji_mrl/mission/status` | Course 已应用、RunStart 已应用、主规划器当前状态 | 需要 `schema_version`、ISO timestamp、真实 course/run_start ACK。 |
| `/tongji_mrl/mission/task_report` | 官方任务结果 | 只有拥有权威完成判据的执行器才提供 `official_report`；普通进度只记日志。 |
| `/tongji_mrl/mission/fault` | failsafe、超时、围栏或执行失败 | 立即上报，包含 `run_id`、reason、发生时间、建议安全状态。 |
| `/tongji_mrl/tsky/progress` | UAV 给主规划器的进度 | 仅状态推进，不是官方完成报告。 |
| `/tongji_mrl/tsky/result` | UAV 给主规划器的任务事实 | 需补齐权威 schema 后才能形成官方 task report。 |
| `/tongji_mrl/tsky/checkpoint` | UAV 的恢复断点 | Task4 抢占/恢复前必须关联 `run_id` 与当前任务。 |

对于 Task 1/Task 3，OCS 只转换明确提供的官方结果，不能根据 `COMPLETE` 字符串、
感知结果或 PX4 command ACK 自行推断完成。若后续仍采用 UAV-only，需要由 UAV 负责人
明确每项任务结果的权威数据源、坐标系、完成/失败条件和 `official_report` JSON；若恢复
USV 协调，则由 USV 汇总后上报。

### OCS -> 主规划器 -> UAV（ROS 2）

除 `run_start` 外，`SAFE_STOP`、Task 4 等命令不能自动复用 RunStart 起飞逻辑。每类
命令需要主规划器和 Orin 明确支持、ACK、去重、超时和安全行为。主规划器依据
`/tongji_mrl/mission/task4_cmd` 决定是否发布 `/tongji_mrl/tsky/task_cmd`；不能在
OCS 中把原先指向 `T-Wave` 的所有目标 ID 全局替换为 `T-Sky`。

## OCS 负责人后续最小改动（Orin 完成上述组件后才做）

当前 OCS 对 UAV-only RunStart 的阻断应保留，直到以下验收完成。届时增加一个显式
的生产配置开关，而不是改默认行为：

1. `OcsClient` 保持现有官方 `team_id`、递增 `seq`、`declaration_seq`、`run_id`、
   Course 指纹验证，不可跳过；
2. `uav_only` 下允许已验证 Course 发布到 `/tongji_mrl/mission/course_config`，并等待
   主规划器在 `/tongji_mrl/mission/status` 回报当前 Course 的 `fsm_accepted=true` 和
   `applied=true`；此处不依赖 T-Wave；
3. `uav_only` 下允许已验证 RunStart 发布到 `/tongji_mrl/mission/run_start`；当前 FSM
   只能以其 `MAP_EXECUTE` 状态作临时可观测证据，不能视为官方关联回执；
4. 在 FSM 实现并经双方确认 `run_start.application_state=APPLIED` 前，OCS 不得声称
   收到结构化 RunStart 回执；无论何种回执均不得解释为已经起飞；
5. 真实 `AIRBORNE` 状态和新鲜官方 Heartbeat 才是飞行开始的可观测证据；
6. Course ACK、RunStart ACK、围栏 readback 或遥测缺失/拒绝时必须保持已阻断状态；
   不自动重发可能引起起飞的 RunStart。

## 分阶段验收（顺序不可调换）

1. **状态验收（不发命令）**：OCS 连续打印
   `[UAV_STATUS_HEARTBEAT_CACHED]` 和 `[HEARTBEAT_PUBLISHED]`。
2. **规划器 RunStart 验收（不连接 PX4 执行器）**：主规划器对合法 RunStart 在
   `/tongji_mrl/mission/status` 回上述 `APPLIED` 状态，并验证重复 `command_id` 不二次处理。
3. **UAV task command 验收**：主规划器发布 `/tongji_mrl/tsky/task_cmd`；UAV 对无 GPS、
   FCU、围栏、failsafe 或电池门禁的情况拒绝开始且不向 PX4 发命令。
4. **受控飞行验收**：仅在飞手、场地、围栏、RTH、kill 与人工接管准备就绪后，执行一次
   真实 RunStart；以 PX4 ACK、`AIRBORNE` 状态和 OCS 官方 Heartbeat 为证据。

## 负责人需回传的最小证据

- `ros2 topic info -v /fmu/in/vehicle_command` 与
  `ros2 topic info -v /fmu/out/vehicle_command_ack`；
- 主规划器与 UAV task executor 的启动命令、节点名和日志样例；
- 一条 `APPLIED` RunStart 状态、一条拒绝状态和一条 duplicate `command_id` 日志；
- 起飞前 `uav_status` 完整 JSON；
- 真实飞行时的 `AIRBORNE` JSON 与对应官方 Heartbeat 日志。
