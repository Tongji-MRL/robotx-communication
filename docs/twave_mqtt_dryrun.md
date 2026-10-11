# T-Wave MQTT dry-run 联调

本联调只使用团队内部 MQTT 协议和 ROS 2 的 FakeUSVExecutor，不连接 Orin、真实执行器或 RoboCommand 设备。

## 已接入与边界

- 入站 topic：`tongji/robotx/v1/T-Wave/command`；出站仍使用现有 `ack`、`task_report`、`fault` topic。
- `run_start` -> `RUN_START`；`task4_assistance`、`task4_keep_out_zone`、`task4_moving_object` -> `TASK4_PREEMPT`；`safe_stop` -> `SAFE_STOP`。
- `task4_all_clear`、`task4_readiness_confirm` 和 `task4_resume` 仅回复 `RECEIVED_PENDING_RECOVERY_POLICY`，不自动恢复，也不生成 T-Sky 命令。候选 UAV FSM 的 ACK/correlation_id 语义仍由 `fsm_protocol.py`/`fsm_link.py` 保持，未固化任何未确认业务字段。
- 每条命令要求正整数 `run_id`、`command_seq`，并校验 `message_id` 去重、时间戳（默认 300 秒）、单调 `command_seq`、活动 run。重连由 Paho 的 1–30 秒退避处理；拒绝会写 ROS 日志。
- SAFE_STOP 软件锁存期间，后续 MQTT 启动或 Task4 消息被拒绝。只有已有的、测试专用安全复位流程可清除锁存；MQTT 不提供复位入口。

## Ubuntu 22.04 / ROS 2 Humble

在测试机安装本地 broker 和 Python 依赖：

```bash
sudo apt update
sudo apt install -y mosquitto mosquitto-clients python3-paho-mqtt
source /opt/ros/humble/setup.bash
cd ~/RobotX/robotx-communication/ros2_ws
colcon build --base-paths src ../usv_main_fsm ../OCS \
  --packages-select robotx_ocs_protocol usv_main_fsm twave_mission_dryrun --symlink-install
source install/setup.bash
```

终端 A 启动唯一的控制出口（Fake Executor）：

```bash
ros2 run twave_mission_dryrun fake_usv_executor --ros-args -p dry_run:=true
```

终端 B 启动 MQTT Runtime。地址、端口、认证、四个 MQTT topic 和消息时效均为 ROS 参数；默认值就是既有 OCS 协议 topic。

```bash
ros2 run twave_mission_dryrun twave_mqtt_runtime --ros-args \
  -p dry_run:=true -p broker_host:=127.0.0.1 -p broker_port:=1883 \
  -p mqtt_username:=robotx -p mqtt_password:=change-me \
  -p command_topic:=tongji/robotx/v1/T-Wave/command \
  -p ack_topic:=tongji/robotx/v1/T-Wave/ack \
  -p task_report_topic:=tongji/robotx/v1/T-Wave/task_report \
  -p fault_topic:=tongji/robotx/v1/T-Wave/fault \
  -p max_message_age_seconds:=300.0
```

若 broker 无认证，省略 `mqtt_username`/`mqtt_password`。若改 topic，OCS 网关/VehicleLink 必须使用同一组 topic；消息 envelope 的既有字段和校验规则不变。

终端 C 先观察回传：

```bash
mosquitto_sub -h 127.0.0.1 -t 'tongji/robotx/v1/T-Wave/#' -v
```

终端 D 用现有 OCS 协议产生命令（不要手写简化 JSON）：

```bash
cd ~/RobotX/robotx-communication
PYTHONPATH=. python3 - <<'PY'
from OCS import vehicle_protocol as p
import paho.mqtt.publish as publish
message = p.make_message('T-Wave', 'command', p.command_payload(
    'run_start', command_seq=1), run_id=42, source='ocs')
publish.single(p.topic('T-Wave', 'command'), p.encode(message), hostname='127.0.0.1', qos=1)
PY
```

然后用相同方式把 `task4_assistance`（递增 `command_seq`）与 `safe_stop` 发出。重复同一 `message_id` 会得到 `DUPLICATE`；过期时间戳、旧序号及旧 run 会得到 `REJECTED`。SAFE_STOP 后再发 `run_start` 必须被拒绝。

## 分阶段链路

第一阶段是上述 OCS 内部 MQTT -> T-Wave Runtime -> MissionBridge -> Fake Executor -> OCS 回传。第二阶段才运行 `OCS/ocs_gateway.py`：它接收模拟 RoboCommand 的 RunStart/Task4，经过 `OcsClient.drain_internal_actions()` 和 `VehicleLink.send_action()` 发布到相同内部 topic。网关和 Runtime 使用同一 broker 地址、端口、认证配置；仍不要连接真实 broker、Orin 或硬件。

Gateway example:

```bash
cd ~/RobotX/robotx-communication/OCS
python3 ocs_gateway.py --official-broker <simulated-robocommand-host> \
  --internal-broker 127.0.0.1 --internal-port 1883 \
  --internal-username robotx --internal-password change-me \
  --internal-command-topic tongji/robotx/v1/T-Wave/command \
  --internal-subscription-topic 'tongji/robotx/v1/T-Wave/+'
```

运行回归：

```bash
cd ~/RobotX/robotx-communication
export PYTHONPATH="$PWD:$PWD/ros2_ws/src/twave_mission_dryrun"
python3 -m unittest discover -s ros2_ws/src/twave_mission_dryrun/test -p 'test_*.py'
python3 -m unittest discover -s usv_main_fsm/tests -p 'test_*.py'
```
