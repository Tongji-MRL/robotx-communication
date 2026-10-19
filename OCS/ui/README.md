# OCS Vehicle Monitor UI

这是电脑 A 上运行的 OCS 内部通信监控界面。它通过团队内部 MQTT 链路观察
T-Wave（USV）和 T-Sky（UAV），不连接官方 RoboCommand，也不直接控制 ROS 2、PX4
或任何车辆执行器。

## 1. 启动位置

必须在包含 `OCS/` 目录的仓库根目录启动：

```bash
cd /home/y/robotx_ws/robotx-communication
source .venv/bin/activate
python3 OCS/monitor_ui.py --broker 127.0.0.1 --port 1883
```

如果内部 MQTT Broker 在另一台机器，把 `127.0.0.1` 换成内部 Broker 的 IP：

```bash
python3 OCS/monitor_ui.py --broker <内部Broker_IP> --port 1883
```

服务启动后默认监听：

```text
http://127.0.0.1:8080
```

MQTT 暂时未启动时，网页仍然可以打开，页面会显示“等待 MQTT”，后台会继续尝试连接。
连接成功后车辆数据会自动更新。

## 2. Ubuntu 远程开发时怎么打开

如果 UI 运行在远程 Ubuntu，而浏览器在本地 Windows：

1. 在 VS Code 的“端口 / Ports”面板中转发远程端口 `8080`；
2. 打开 VS Code 生成的本地转发地址；
3. 不要在 Windows 浏览器中直接使用 `127.0.0.1:8080`，除非 UI 也运行在 Windows 本机。

如果不使用 VS Code 端口转发，也可以让 UI 监听远程主机地址：

```bash
python3 OCS/monitor_ui.py \
  --web-host 0.0.0.0 \
  --web-port 8080 \
  --broker <内部Broker_IP> \
  --port 1883
```

然后访问：

```text
http://<Ubuntu_IP>:8080
```

这种方式只建议在受控的实验室网络中使用。

## 3. 安装依赖

首次使用时：

```bash
cd /home/y/robotx_ws/robotx-communication
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r OCS/requirements.txt
```

其中 `paho-mqtt` 用于接收车辆消息和发送联调命令。没有安装 MQTT 依赖时，界面仍可
打开，但只会作为离线页面，不能收发消息。

## 4. 界面展示

### 顶部连接状态

- 显示内部 MQTT Broker 是否连接；
- 显示当前 Broker 地址和端口；
- MQTT 未连接时显示等待或断开原因。

### Course 信息

- 当前 `course_id`；
- Pinger 频率；
- UI 进程运行时长和最后刷新时间。

### 车辆状态卡片

每辆车一张卡片：

- `T-Wave`：USV；
- `T-Sky`：UAV；
- 在线、心跳超时或故障状态；
- `AUTO/MANUAL/KILLED` 模式；
- 当前任务；
- 仿真/真实数据来源；
- WGS84 纬度、经度和高度；
- 速度、航向和最后一次心跳时间；
- 最近 ACK 或故障信息。

界面中的“在线”只表示 OCS 最近收到有效标准化 heartbeat，不代表推进器、飞控或任务
执行器一定正常。

### 通信时间线

显示最近的：

- 车辆 heartbeat；
- ACK；
- task report；
- fault；
- Course 配置；
- UI 发出的内部命令；
- MQTT 连接和解析错误。

时间线只保存在 UI 进程内存中，重启 UI 后会清空。正式比赛日志仍由 OCS Gateway 和
电脑 B 官方测试工具保存。

### USV 联调控制

控制区固定只面向 `T-Wave`，当前包含：

- `PING`：检查内部通信链路；
- `SAFE_STOP`：发送车辆侧安全停止命令，需要二次确认；
- Task4 相关内部联调命令；
- 可选 `run_id`；
- 可选 JSON `parameters`。

这里的 Task4 按钮只用于实验室内部协议测试，不能代替官方 RoboCommand 的正式命令
链路。正式 Task4 必须由 OCS 从官方 Broker 收到后，再按官方序号转发给 USV。

## 5. 安全边界

- UI 只订阅 `tongji/robotx/v1/+/+`；
- UI 只向 USV 的内部 `command` Topic 发布；
- UI 不向 UAV 直接发布任务命令；
- UI 不连接 `robocommand/robotx/#`；
- UI 不发布官方 Protobuf；
- UI 不包含任务选择逻辑；
- UI 不根据心跳超时自行判定任务完成；
- UI 不连接真实执行器。

## 6. 常见问题

### 页面完全打不开

确认 Python 进程仍在运行，并检查 VS Code 是否转发了远程 `8080` 端口。

### 页面能打开，但一直显示“等待 MQTT”

检查 Broker 地址、端口和 MQTT 认证参数：

```bash
python3 OCS/monitor_ui.py \
  --broker <内部Broker_IP> \
  --port 1883 \
  --username <用户名> \
  --password <密码>
```

### 端口已被占用

换一个网页端口：

```bash
python3 OCS/monitor_ui.py --web-port 8081 --broker <内部Broker_IP>
```

然后打开 `http://127.0.0.1:8081` 或对应的 VS Code 转发地址。

### 车辆卡片没有数据

确认两台车辆适配器已经发布标准化 heartbeat，并且 topic 使用：

```text
tongji/robotx/v1/T-Wave/heartbeat
tongji/robotx/v1/T-Sky/heartbeat
```

UI 不会把原始 ROS 2 Topic、PX4 Topic 或截图自动转换成车辆状态。

