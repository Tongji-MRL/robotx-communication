# UAV status test guide

## UAV 单机 Ground Validation：完整官方通信流程

**现场直连请使用最新 [TONG 官方现场操作手册](../deliverables/RobotX_TONG_Ground_Validation_Official_20261107.docx)。**
本次 Ground/Flight Validation 网络为 `192.168.69.0/24`，OCS 使用 DHCP，
broker 是工作人员分配的 `192.168.69.2–6` 中一个实例，正式队伍为 `TONG`。
无 UAPL ID 的 Ground 阶段，pilot callsign 只填 first name；registration 填
`TONG-<去掉开头AA的CAAS贴纸号码>`，保留前导零。下文 Docker 重启和 GVSYS
队名仅用于本地模拟；现场轮次切换由官方确认，SYS 判据使用实际 SV 区域和高度上限。

此部分使用新增的 `OCS/uav_ground_validation.py`，主动向指定 RoboCommand 发布
声明和真实遥测。默认 `--scenario normal`；越界和超高也使用同一个入口。
后续章节保留原来的只读 Monitor 测试；两种入口用途不同。

本入口按实际已测通的 ROS 2 上行链路接入：

```text
UAV Orin ROS 2 /tongji_mrl/tsky/uav_status
  std_msgs/msg/String，data 为 JSON，vehicle_id=UAV1
  -> ROS 2 / DDS
  -> OCS uav_ground_validation.py (官方 vehicle_id=UAV1)
  -> RoboCommand MQTT/Protobuf -> MDF
```

不启动 `uav_status_mqtt_bridge.py` 或内部 MQTT Broker。OCS 必须运行在能直接
接收该 ROS 2 topic 的环境里。订阅 QoS 沿用现有 ROS 接口：RELIABLE、VOLATILE、
depth=10。ROS 回调独立运行，将收到的 `message.data` 和接收时间交给主循环；
Heartbeat 的 state、flight_phase、位置、速度、航向和 HAE 高度来自这些数据。

程序自动完成以下顺序，无需另启 `ocs_gateway.py`、`vehicle_agent.py`、USV 或
`dry_run.launch.py`：

1. 连接官方 Broker，订阅 retained `robocommand/robotx/course` 和本队 command。
2. 收到并校验 Course；使用现有围栏生成/验证函数。
3. 发布只有 `UAV1` 的 `RxRequest.run_declaration`，四个 task tier 均为 NONE。
4. 有新鲜 UAV 状态后，按 2 Hz 发布 `robocommand/robotx/TONG/UAV1/report`。
5. 若收到 RunStart，校验 declaration_seq 并记录 run_id；持续地面遥测，不发布车辆命令。

`run_id` 是 RunStart 和 OCS 本地会话/JSONL 中的字段；官方 `RxReport` 没有
`run_id` 字段。报告序号按车辆递增，在同一个地面验证进程中重连或重新声明也不回退。

RunStart 不是地面遥测的前提。程序直接转发 UAV 的 MANUAL/AUTO/KILLED 和
GROUNDED/AIRBORNE，不为获得 RunStart 而强行改为 AUTO。地面观察期间
`current_task=TASK_NONE`。不要同时运行另一个以同一 Team/vehicle 发布声明或
官方心跳的 OCS 实例。

本次使用官方模拟端时，对外 ID 采用 `UAV1`，使官方脚本执行 UAV 围栏/高度检查。
`--vehicle-id` 只改对外 ID；`--source-vehicle-id` 必须匹配真实 ROS JSON。
仍兼容 `T-Sky`，但该官方测试服务会跳过它的 UAV 检查。
完整 Windows 配置、官方模拟启动及 SYS1/SYS2/SYS3 命令见
[协作者交接手册](../deliverables/RobotX_UAV_Ground_Test_Windows_20261107.docx)。

### 配置与启动

新模板 `OCS/config.uav-ground.example.json` 只含 UAV。可以复制到本机的私有
配置位置，再用 `--config` 指向它。需要填写官方 Broker、实际
pilot callsign，核对 `UAV1 -> UAV1` 与 MDF 上的飞机身份；如 MDF 需要机身注册号，
填写 `vehicles.uav.uav_registration` 或 `--uav-registration`。

围栏配置复用 `run_declaration` 中的既有参数。`auto_course` 自动生成候选围栏；
若使用已经验证的手工围栏，设 `uav_geofence_mode=manual` 并提供闭合坐标数组。
模板的 40 m HAE 和 50 m HAE 只是测试配置，不代表现场 SV 空域批准高度。
请沿用已经核实的围栏、高度和高度基准；提交对象是收到的当前 Course。

先加载本机已测通的 ROS 2 环境，沿用与 UAV 通信时的 `ROS_DOMAIN_ID`、RMW 和
网络设置。使用同一终端检查消息类型、发布 QoS 和数据更新：

```text
ros2 topic type /tongji_mrl/tsky/uav_status
ros2 topic info /tongji_mrl/tsky/uav_status --verbose
ros2 topic echo /tongji_mrl/tsky/uav_status
```

预期类型为 `std_msgs/msg/String`，其中 JSON 身份为 `UAV1`。发布端必须与上述
订阅 QoS 兼容；本入口沿用仓库现有 String 接口，不解析其他自定义 ROS 消息类型。
运行程序的 Python 必须同时能导入 `rclpy`、`std_msgs.msg`、`paho.mqtt.client`
和 `google.protobuf`。在该 Python 环境安装 `OCS/requirements.txt` 的依赖。

从仓库根目录运行（替换尖括号参数；Windows 必须已加载 ROS 2 环境）：

```powershell
.\scripts\start_uav_ground_validation.bat `
  --official-broker <RoboCommand_IP> `
  --pilot-callsign "<实际飞手标识>" `
  --uav-registration "<实际机身注册号>" `
  --log logs/uav-ground-validation.jsonl
```

命令行覆盖先于配置校验，可以直接覆盖模板中空的官方地址和 pilot callsign。
Windows 启动器使用当前环境的 `python`，也可通过环境变量
`ROBOTX_GROUND_PYTHON` 指定能导入 ROS 2 的 Python 绝对路径；不再自动选仓库
`.venv`。Linux 在 source ROS 2 环境后，可使用同样参数运行
`python3 OCS/uav_ground_validation.py`。缺少 ROS 2 依赖时程序报错退出，
在连接官方 Broker 前停止，不回退到内部 MQTT。
默认持续运行，Ctrl+C 停止；`--duration 90` 表示从进程启动计时 90 秒，并非
保证已累计 90 秒有效遥测。等 MDF 实际开始更新后，再观察至少一分钟。

### 运行时观察

控制台依次出现 `WAIT_ROBOCOMMAND` / `WAIT_COURSE`、`DECLARING`、
`DECLARATION_PUBLISHED`、`WAIT_UAV_TELEMETRY` 或 `HEARTBEATING`。
`HEARTBEAT_PUBLISHED` 包含 report_seq、真实 state/phase、接收年龄和发布计数。
成功发布是收到 Broker 的 QoS1 PUBACK，不代表 MDF 已验收。
可选 JSONL 文件记录这些事件；围栏坐标由已有声明函数打印到控制台。

UAV 数据超过 3 秒未更新、收到模拟/身份不匹配数据时，停止发布缓存心跳，
等待新鲜有效数据。ROS 订阅使用 VOLATILE，不要求发布端提供历史数据；ROS
执行器故障或接收队列溢出时退出。ROS 订阅创建成功不等于已发现 UAV，必须收到
有效状态才发心跳。来源提供 `sent_at_unix_ms` 或
`timestamp_unix_ms` 时还检查来源时间；现有 JSON 没有来源时间戳时，仅能证明
本机收包新鲜度，不能据此证明 GNSS 采样延迟。现场需确认 GNSS lock 与 MDF 更新。
roll/pitch 若源 JSON 提供则转发，否则保持官方 protobuf 字段未填；不补零。

官方链路在 RunStart 前重连时，重新收到 Course 后重新声明；已收到 RunStart
则保留 run_id 和序号，等待重新接收 Course 和新的 UAV 数据后继续遥测。
发布报错或 3 秒内未收到 PUBACK 时进程退出，避免不确定的声明被自动重复提交。
此时先核对 RoboCommand 是否已经收到声明，再决定重新启动。

### 对应 Ground Screening 表

本入口用于 MDF 1–4 的正常声明/遥测链路，以及 SYS1 的有效请求。
验收人员仍需在 MDF 确认飞机 ID、pilot、实际提交围栏和最高高度，以及至少
一分钟的更新和位置误差要求。SYS2/SYS3 通过下列显式测试参数发送负例，仍需
官方侧明确拒绝日志；模拟服务没有 MDF 页面或现场审批/hold 功能。

### 同一个入口的三个场景

三个场景均直接订阅真实 ROS topic，先接收并校验当前 RxCourse，再校验同一份
合法基线配置。`normal` 原样发布，负例仅修改指定的声明字段；Heartbeat 的实际
坐标、高度、状态和飞行阶段不随测试声明改变。不要把 local.json 改成非法配置。

| 参数 | 声明行为 | 服务端预期 |
|---|---|---|
| `--scenario normal` | 当前 Course 内的合法围栏，基线高度如 40 m HAE | 接受；真实 AUTO 后 RunStart |
| `--scenario outside-course --outside-offset-m 20` | 整个闭合围栏移到 Course 与 Transit 最北边界之外至少 20 m | 越界 refused |
| `--scenario over-height --test-max-altitude-hae 60` | 保留合法围栏，只把声明最高高度改为 60 m HAE | 超高 refused，基于模拟端默认 50 m HAE 上限 |

专属参数用于错误场景会在联网前报错；北移距离范围为 2–100000 m；测试高度
须有限、在 `(50,100000]` m HAE 内，且 protobuf 编码后仍大于 50。
负例要求对外 ID 以 `UAV` 开头，避免官方脚本跳过检查。

每轮先在 A 停止上一份 OCS，再在 B 的官方 `robocommand/RobotX_2026` 目录运行
`docker compose restart rc-test`，等日志重新出现 `Published RxCourse (retained)`。
B 的 Docker 服务保持运行，以下三个命令按轮次在 A 的已加载 ROS 的 PowerShell
执行，不并行运行。`$GroundPython` 指向文档所述 `.venv-ground` 解释器：

```powershell
# SYS1 正常。持续至少一分钟有效心跳后 Ctrl+C。
& $GroundPython .\OCS\uav_ground_validation.py `
  --config .\OCS\config.uav-ground.local.json `
  --scenario normal --team-id GVSYS1 --log .\logs\sys1-normal.jsonl

# 重置 B 后，SYS2 越界。
& $GroundPython .\OCS\uav_ground_validation.py `
  --config .\OCS\config.uav-ground.local.json `
  --scenario outside-course --team-id GVSYS2 `
  --outside-offset-m 20 --duration 90 --log .\logs\sys2-outside-course.jsonl

# 再重置 B 后，SYS3 超高。
& $GroundPython .\OCS\uav_ground_validation.py `
  --config .\OCS\config.uav-ground.local.json `
  --scenario over-height --team-id GVSYS3 `
  --test-max-altitude-hae 60 --duration 90 --log .\logs\sys3-over-height.jsonl
```

`DECLARATION_PUBLISHED` 写出实际发送的围栏和高度、scenario、expected_result，
并明确 `transport_ack="MQTT PUBACK only"` 和 `outcome="acceptance_unknown"`。
退出码 0 仅表示程序通信执行结束或人工中止，不能用作负例通过判定；定时结束时
仍无心跳或运行异常为 2。
官方拒绝不回传消息，需在 B 保存带对应 Team 和原因的 `refused` 日志。
没有 RunStart 也可能源于 MANUAL、无心跳或断线，不能单独证明拒绝。

负例收到匹配 RunStart 会记录 `SCENARIO_FAILED` 并退出；声明之后断线、Course
变化也会退出，避免重复提交污染结果。正常模式保留既有的重连流程，所有模式均无
车辆命令输出。端到端延迟、位置误差、现场身份和 MDF 验收仍由实际系统确认。

离线回归：`python -m unittest discover -s OCS -p "test_*.py"`。
2026-11-07 在仓库 `.venv` 中执行，138 项通过，无失败或跳过。

测试分为两层：`test_ros2_ground_input.py` 用假的 rclpy 模块验证订阅类型、topic、
QoS、回调数据和资源清理；`test_ground_mqtt_flow.py` 用模拟 ROS 输入和一个真实
loopback MQTT Broker 验证接收 Course、声明、Heartbeat 和 RunStart 的官方通信。
这些测试不连接 DDS 或 UAV。仓库当前 `.venv` 没有 rclpy，尚未实测真实 ROS 2
跨机订阅或现场 RoboCommand/MDF。之前双 MQTT 原型的 65 秒测试结果仅属于旧
输入路径，不能用作本 ROS 2 入口的验收证据。

## 原有只读 Monitor 测试

以下是历史 MQTT bridge/Monitor 工具的独立测试说明，不属于上述直接 ROS 2
Ground Validation 链路，也不需要随地面验证一起启动。

This guide tests the read-only UAV status path only. It does not send a
RoboCommand request, Heartbeat, RunDeclaration, RunStart, flight command, or
geofence upload. Do not use a competition broker for the simulator.

## What is in this branch

The branch contains:

* strict JSON validation and explicit source identity mapping in
  `OCS/uav_status.py`;
* an Ubuntu ROS2-to-internal-MQTT bridge in `OCS/uav_status_mqtt_bridge.py`;
* Windows OCS and Monitor MQTT observers, with a read-only status cache;
* a Monitor page showing freshness, state, battery, position, raw JSON, and a
  distinct Course/Transit/verified-Geofence/UAV map preview;
* a 5 Hz `TEST/SIMULATED` MQTT publisher;
* unit tests for valid data, invalid JSON/identity rejection, stale state, and
  the guarantee that this data is not converted to an official Heartbeat.

`OCS/config.uav-status.example.json` is an intentionally credential-free
mapping template. Copy it outside Git or supply equivalent command-line values;
do not commit a real broker password, TLS material, `.env`, or flight data.

## Windows local simulation (no ROS2 required)

Prerequisites:

* Windows Python environment with `OCS/requirements.txt` installed;
* Mosquitto installed locally and listening only as intended; and
* this repository clone, with commands run from its root.

Install Python dependencies once:

```powershell
cd D:\RobotX\robotx-rc-lab
.\.venv\Scripts\python.exe -m pip install -r .\OCS\requirements.txt
```

Start Mosquitto in a separate PowerShell. The exact service command depends on
the local installation; the following is a common explicit foreground command:

```powershell
& 'C:\Program Files\mosquitto\mosquitto.exe' -p 1883 -v
```

Check the listener before starting OCS:

```powershell
Test-NetConnection 127.0.0.1 -Port 1883
```

Start the read-only Monitor UI:

```powershell
cd D:\RobotX\robotx-rc-lab\OCS
..\.venv\Scripts\python.exe .\monitor_ui.py `
  --broker 127.0.0.1 --port 1883 `
  --uav-source-vehicle-id UAV1
```

Open `http://127.0.0.1:8080`. In another PowerShell, publish 5 Hz simulated
data for one minute:

```powershell
cd D:\RobotX\robotx-rc-lab\OCS
..\.venv\Scripts\python.exe .\tools\uav_status_simulator.py `
  --broker 127.0.0.1 --port 1883 `
  --source-vehicle-id UAV1 --duration 60
```

The page should show `ONLINE`, T-Sky, position/heading changes, battery values,
and `TEST/SIMULATED` in raw JSON. It must show C2 signal as **not connected**,
because this path has no C2-radio source.

### Freshness and negative checks

1. Stop the simulator and wait longer than Monitor `--stale-after` (default
   three seconds): the panel must become `STALE` rather than display invented
   values.
2. Start the normal simulator again: it must return to `ONLINE`.
3. Publish one malformed message before valid samples:

   ```powershell
   ..\.venv\Scripts\python.exe .\tools\uav_status_simulator.py --broker 127.0.0.1 --port 1883 --source-vehicle-id UAV1 --malformed-once --duration 10
   ```

4. Publish an identity mismatch: it must be rejected and not replace the last
   valid state.

   ```powershell
   ..\.venv\Scripts\python.exe .\tools\uav_status_simulator.py --broker 127.0.0.1 --port 1883 --source-vehicle-id UAV1 --wrong-vehicle-id --duration 10
   ```

Inspect `http://127.0.0.1:8080/api/state` to see `uav_status`,
`uav_status_age_s`, and `uav_status_online`. This API shows receipt/cache state,
not RoboCommand broker acknowledgement.

## Ubuntu ROS2 bridge and real UAV topic

Windows does not need ROS2. Run the bridge on Ubuntu, in a ROS2 environment
that has `rclpy`, `std_msgs`, Python `paho-mqtt==2.0.0`, and this repository.

```bash
cd /path/to/robotx-rc-lab/OCS
python3 -m pip install -r requirements.txt
python3 uav_status_mqtt_bridge.py \
  --broker <WINDOWS_BROKER_IP> --port <MQTT_PORT> \
  --source-vehicle-id <ORIN_JSON_VEHICLE_ID>
```

The historical lab address `192.168.112.1:1884` is only an example; replace it
with the currently verified Windows-reachable internal broker address and port.
Do not put credentials on the command line if shell history is retained; use
the approved local deployment mechanism instead.

The bridge subscribes to exactly:

```text
topic: /tongji_mrl/tsky/uav_status
type: std_msgs/msg/String
QoS: Reliable, Volatile, Keep Last 10
rate: 5 Hz
```

The JSON must contain the configured exact `vehicle_id`, `vehicle_type: "uav"`,
`state` (`AUTO`, `MANUAL`, or `KILLED`), `flight_phase` (`GROUNDED` or
`AIRBORNE`), `position.latitude`, `position.longitude`, `altitude_hae_m`,
`spd_mps`, and `heading_deg`. Optional `battery_status` must be an object.
The bridge validates then relays the unchanged JSON to the same internal MQTT
topic at QoS 1. It is read-only and does not create an official UAV Heartbeat.

## Automated tests

From repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s OCS -p "test_*.py"
git diff --check
```

The clean GitHub commit `e60b340` was independently tested in a detached
worktree with **80 passing tests**. A local worktree containing uncommitted
QoS1 Heartbeat work has additional tests; do not attribute those results to a
clean UAV-only clone.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Monitor says MQTT disconnected | Verify `Test-NetConnection`, host/port, Mosquitto listener, firewall, and no conflicting service. |
| UI stays UNKNOWN | Ensure `--uav-source-vehicle-id` exactly matches JSON `vehicle_id`; inspect `/api/state` and Monitor stderr. |
| UI becomes STALE | Confirm 5 Hz publisher/bridge is still running and the internal topic has traffic; stale is intentional safety behavior. |
| Data rejected | Validate JSON fields, finite coordinates, heading below 360, vehicle type `uav`, and required state/phase spelling. |
| Ubuntu cannot import ROS2 | Source the correct ROS2 setup and install `rclpy`/`std_msgs` for that Ubuntu distribution. |
| Bridge cannot reach Windows | Verify routable broker address, port, firewall, MQTT credentials/TLS deployment, and DDS network separately. |

## Evidence status

Passed locally: parser/identity/freshness unit tests, UI cache tests, clean
branch OCS regression tests, and a Windows local MQTT→OCS→Monitor simulated
loop as reported by the team.

Still requiring real-device or cross-device evidence: Orin publisher schema
and rate, Ubuntu DDS subscription, Ubuntu-to-Windows MQTT connectivity and
reconnect behavior, real battery/C2 sources, authoritative Course/Transit/
verified-Geofence geometry, official RoboCommand UAV Heartbeat, and any FCU
geofence application/acknowledgement. The technical assessment Ground
validation test list should be used to record GCS/MDF/SYS/SC evidence; it is
not bundled in this repository.
