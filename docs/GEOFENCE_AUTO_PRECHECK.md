# OCS RxCourse → UAV Geofence 自动候选与地面预检

> 本补丁仅实现 OCS 侧的围栏候选计算、校验与 Protobuf RunDeclaration 组包；**不会**向 FCU/PX4 下发围栏，也不会自动向 RBC 发布申报。原有 `--publish-declaration` 才会请求实际发送。仅在隔离 RoboCommand 测试环境中测试违规案例。

## 1. 参数说明

在本地配置文件的 `run_declaration` 中设置：

```json
{
  "task_tiers": {"task1": "disruptive", "task2": "none", "task3": "disruptive", "task4": "disruptive"},
  "uav_geofence_mode": "auto_course",
  "uav_geofence": [],
  "uav_geofence_margin_m": 1.0,
  "uav_geofence_max_altitude_hae_m": 40.0,
  "uav_geofence_altitude_limit_hae_m": 50.0,
  "uav_pilot_callsign": "实际飞手呼号，必须人工填写"
}
```

- `uav_geofence_mode`: `auto_course`（以及兼容名称 `auto_course_union`）= 从当前有效 RxCourse 的真实几何计算闭合候选多边形；`manual` = 继续使用 `uav_geofence` 中人工提供的点。
- `uav_geofence_margin_m`: 自动围栏固定为 1 m 内缩；非 1 m 会拒绝生成，避免各部署产生不一致的候选区域。
- `uav_geofence_max_altitude_hae_m`: **本次拟申报的最高 HAE 高度**。改成 55 m 可验证本地“超高拒绝”；并非实际可以飞到 55 m。
- `uav_geofence_altitude_limit_hae_m`: **OCS 本地高度门槛**，默认 50 m，对应官方示例 RC-test Server 的上限，允许设得更严格（例如 30 m）；不能仅通过修改此参数擅自提高官方允许的高度。
- `uav_pilot_callsign`: 真实飞手呼号，不可使用占位值发送真正的申报。

配置中 `uav_geofence` 必须保持空数组才可使用 `auto_course`，避免覆盖手工申报。

## 2. 算法及限制

1. 等待 RBC 经 MQTT 发送并被 OCS 验证的 `RxCourse`；读取原始 `corners` 与 `uav_transit_area`，保留全部顶点。
2. 若收到了非空 `uav_transit_area`，在局部米制平面计算 `Union(corners, uav_transit_area)`；未收到时仅使用 `corners`。不会补造 transit 或 corner 顶点。
3. 对上述真实区域使用 GEOS/Shapely 作精确 `buffer(-1 m)`；结果为多块区域、含孔洞、空区域或无效时拒绝生成，要求人工提供经审批的 `manual` 围栏。
4. 使用闭合性、自交、顶点及边界包含性验证，并验证可配置的申报高度。
5. 原始坐标保持经纬度十进制度，打包成 `common_pb2.LatLng`，在 `RxRequest.run_declaration` 中通过 MQTT Protobuf 发送。

**重要：自动候选不会再缩成 Course 中心附近的内接圆。** 它覆盖收到的 Course，且仅在收到 transition 时覆盖其与 Course 的并集；但仍须由飞手核验实际起降点、港口/浮标坐标与 FCU 已应用的围栏。若结果不能由单一无孔闭合环表达，请使用经审批的 `manual` 围栏。

这部分并不是将 UAV 原始 GPS 坐标变换到 NED。经纬度直接作为 `LatLng(latitude, longitude)` 发送。高度必须由飞手确认是 HAE，而不是 AGL。

## 3. 三种测试（单元预检；不接 RBC）

在项目根目录使用 Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s OCS -p 'test_geofence_planner.py' -v
.\.venv\Scripts\python.exe -m unittest discover -s OCS -p 'test_*.py'
git diff --check
```

新增测试包含：

- **IN_BOUNDS**：OCS 从 Course 计算合法闭合 Geofence；Protobuf 序列化正常，仅测试拦截的发送调用，不连接 MQTT。
- **OUT_OF_BOUNDS**：手工输入越过 Course 和 Transit Area 的围栏，OCS 抛出越界异常，阻断 `_publish()`。
- **OVER_HEIGHT**：将拟申报高度设为 55 m，高于本地 50 m 上限，OCS 抛出高度异常，阻断 `_publish()`。另测本地上限 30 m 的参数调整。

以上测试**不能**替代地面评估表中 RoboCommand/MDF 的拒绝记录。官方评估 SYS 项必须在批准的隔离测试服务和获授权的操作流程下验证模拟 RBC 的接收／拒绝及原因，正式 RBC 不可发违规测试消息。

## 4. 连接隔离 RBC 模拟服务器后验证正式数据路径

当前自动计算是在 OCS 收到 retained `RxCourse` 后才能执行。`ocs_client.py` 和 `ocs_gateway.py` 的 CLI 发送模式会等待最多 10 秒取得 Course；如果未收到则阻断声明。请在运行前从终端审查所计算候选点、实际任务区域和 FCU 围栏是否一致。

与先前阶段相同：

- Windows Monitor 只读，不执行任何飞控动作；
- 正式 UAV Heartbeat 仍需独立权威 roll、pitch、current_task 等字段，不会由本补丁填造；
- RC-test Server 的示例 GEO 参数与具体比赛授权空域不一定相同，不要直接用于实际飞行；
- 需与 UAV 飞手共同验证飞控围栏的应用与记录，并确认实际被授权的高度限制。

## 5. 补丁与提交边界

本补丁新增：`OCS/geofence_planner.py`、`OCS/test_geofence_planner.py`、本文档。

修改：`OCS/course_config.py`（支持可选 Transit Area 范围校验）、`OCS/ocs_client.py`（自动生成及参数化高度校验）、`OCS/ocs_gateway.py`（配置向下传递、等待 Course）、`OCS/config.example.json`（候选配置示例）。

**没有**修改 UAV Orin、PX4、真实 RoboCommand Broker、Monitor UI、Heartbeat QoS1、FSM、官方 Protobuf schema；不上传凭据，不包含任何自动发起申报的测试脚本。
