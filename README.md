# RobotX 2026 通信系统（TONG / USV-only）

本仓库包含同济大学 TONG 队 RobotX 2026 的通信集成代码。当前正式默认模式为
**USV-only**：`T-Wave` 是唯一声明车辆和任务协调者；OCS 只做通信网关，实际
任务决策与执行由 T-Wave Orin 上的任务节点负责。

## 通信架构

```text
RoboCommand / RBC
        │ MQTT + 官方 Protobuf
Windows OCS Gateway
        │ 内部 MQTT JSON                     │ ROS 2 String JSON
T-Wave Orin 心跳发布器                 T-Wave 任务节点
/tongji_mrl/twave/heartbeat            Course / RunStart / Task4
```

- OCS ↔ RBC：仅使用官方 MQTT 和 Protobuf。
- T-Wave Orin → OCS：仅使用内部 MQTT 上报原始车辆心跳。
- OCS ↔ T-Wave 任务节点：使用 ROS 2 任务接口。
- 默认模式不订阅、不声明、不上报 `T-Sky`。
- 历史 UAV 接口仍保留；只有显式使用非默认的 `dual_vehicle` 配置时才会启用。

## 启动前提

现场连接前，请在本地填写实际地址，且不要提交密码、凭据或现场网络信息。

1. Windows 内部 MQTT Broker 已启动在 `1883` 端口，且 T-Wave Orin 可访问。
2. T-Wave Orin 正在向该 Broker 的 `/tongji_mrl/twave/heartbeat` 发布真实心跳 JSON。
3. Windows 与 Orin 使用相同的 `ROS_DOMAIN_ID`；需要跨设备 DDS 通信时，设置
   `ROS_LOCALHOST_ONLY=0`。
4. 已取得 RBC 的地址与端口。
5. RBC 在 Gateway 声明等待窗口内下发有效 Course。

`OCS/config.usv-only.json` 是正式 USV-only 配置模板，其中 RBC 地址故意保留为
占位符，必须由现场操作员显式提供。

## 启动 USV-only Gateway

在 Windows PowerShell 中运行：

```powershell
cd D:\RobotX\robotx-rc-lab
$env:ROS_DOMAIN_ID = '<现场域编号>'
$env:ROS_LOCALHOST_ONLY = '0'

python -u .\OCS\ocs_gateway.py `
  --config .\OCS\config.usv-only.json `
  --vehicle-mode usv_only `
  --official-broker <RBC_IP> `
  --official-port 1883 `
  --internal-broker 127.0.0.1 `
  --internal-port 1883 `
  --publish-declaration
```

也可以使用启动脚本：

```powershell
.\scripts\start_ocs_usv_only.bat `
  --official-broker <RBC_IP> --official-port 1883 --publish-declaration
```

Gateway 会连接官方与内部 Broker，等待官方 Course，然后只为 `T-Wave` 发布
RunDeclaration。默认 `--duration 0`，表示持续运行。

## Orin 接口

### 心跳

Orin 心跳发布 Topic：

```text
/tongji_mrl/twave/heartbeat
```

除时间戳外，心跳必须包含 T-Wave 身份、`"usv"` 车辆类型、明确状态和任务、
WGS84 位置、速度、航向、横滚、俯仰及健康状态。OCS 会保留源时间戳作为诊断元数据，
但不会用它拒绝、过期、排序或绑定心跳。已接收且通过其他校验的心跳会持续有效，直到
被新的心跳替换，或当前声明/运行上下文被重置。

正常路径的 OCS 日志应依次包含：

```text
[RxVehicle] heartbeat vehicle=T-Wave ...
[DECLARATION_PUBLISHED] ... vehicles=['T-Wave']
[HEARTBEAT_PUBLISHED] ...
[HEARTBEAT_PUBACK] ...
```

### Course、RunStart 与任务事件

| 方向 | Topic | 内容 |
| --- | --- | --- |
| OCS → 任务节点 | `/tongji_mrl/mission/course_config` | 现有 Course JSON 合约 |
| OCS → 任务节点 | `/tongji_mrl/mission/run_start` | `{"command":"begin"}` |
| OCS → 任务节点 | `/tongji_mrl/mission/task4_cmd` | 现有 Task4 JSON 合约 |
| 任务节点 → OCS | `/tongji_mrl/mission/status` | 任务状态 |
| 任务节点 → OCS | `/tongji_mrl/mission/task_report` | 任务报告 |
| 任务节点 → OCS | `/tongji_mrl/mission/fault` | 故障报告 |

OCS 在既有 RBC 校验通过后，会在 USV-only 模式向 RunStart Topic 精确发布
`{"command":"begin"}`。它不等待已移除主状态机的 Course-ready 或 RunStart-applied
ACK。任务顺序、抢占、恢复和执行器使用由任务节点决定。

## 常见问题排查

- 没有 `[RxVehicle]`：检查 Orin 的 Broker 地址、MQTT 连通性和
  `/tongji_mrl/twave/heartbeat` Topic。
- 出现 `waiting for fresh MAVROS telemetry`：恢复 FCU/MAVROS 链路以及 state、GPS、
  heading、velocity、IMU 输入；OCS 不会生成 Orin 未发布的车辆遥测。
- 没有 `DECLARATION_PUBLISHED`：确认 RBC 在启动时下发了有效 Course，并检查官方
  Broker 地址。
- 没有 `HEARTBEAT_PUBACK`：检查官方 Broker 连接和 RBC Topic 权限。
- RunStart 未转发：确认 `/tongji_mrl/mission/run_start` 有任务节点订阅者，并检查
  OCS 的官方命令与声明校验日志。

## 测试

在 `OCS` 目录中运行：

```powershell
cd OCS
python -m unittest test_usv_only_gateway test_fsm_interface_alignment test_ocs_client test_operation_mode test_realtime_heartbeat test_fsm_protocol test_fsm_monitor test_monitor_ui test_uav_status test_uav_geofence test_ros2_ground_input test_ocs_gateway_uav_mode
python -m py_compile heartbeat_cache.py vehicle_link.py ocs_gateway.py
```

这些是本地/模拟验证，不代表真实 RBC 接入、实船联调或执行器验证已经完成。

## 相关文档

- [USV-only 变更报告](docs/USV_ONLY_CHANGE_REPORT.md)
- [USV-only 运行指南](docs/USV_ONLY_RUN_GUIDE.md)
- [USV-only 回归测试记录](docs/USV_ONLY_REGRESSION_TEST.md)
- [UAV 接口隔离说明](docs/UAV_INTERFACE_ISOLATION.md)
