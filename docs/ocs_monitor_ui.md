# OCS 通信监控 UI

`OCS/monitor_ui.py` 提供一个本地 Web 监控台，用于在电脑 A 上观察 OCS 内部 MQTT
链路。它不是官方 RoboCommand 客户端，也不替代 `ocs_gateway.py`。

具体启动步骤、远程 Ubuntu 端口转发和界面各区域说明见 [`OCS/ui/README.md`](../OCS/ui/README.md)。

## 能做什么

- 显示 T-Wave（USV）和 T-Sky（UAV）的最近心跳、在线/超时状态、模式、当前任务、位置、速度和健康信息；
- 显示 Course 配置和最近的接收/发送消息；
- 向 T-Wave 发送受控的实验室联调命令，并记录发送结果；
- `SAFE_STOP` 需要二次确认；UI 不向 UAV 直接发送命令。

正式比赛的 RunStart、Task4 和官方报告仍必须经过 OCS 官方 RoboCommand 链路。UI 中的
Task4 命令仅用于内部链路调试，不应绕过官方命令序号和现场安全流程。

## 启动

在仓库根目录执行：

```bash
python3 -m pip install -r OCS/requirements.txt
python3 OCS/monitor_ui.py --broker <内部Broker_IP> --port 1883
```

浏览器打开 `http://127.0.0.1:8080`。如果 MQTT Broker 在电脑 A 上，则使用
`--broker 127.0.0.1`；如果由独立机器提供，则填写内部 Broker 地址，不要填写电脑 B
的官方 RoboCommand 地址。

带认证的内部 Broker：

```bash
python3 OCS/monitor_ui.py --broker <内部Broker_IP> --username <用户名> --password <密码>
```

## 安全边界

- UI 只订阅 `tongji/robotx/v1/+/+`，只发布到 T-Wave 的内部 `command` Topic；
- UI 不连接 `robocommand/robotx/#`，不发布官方 Protobuf；
- UI 不连接 ROS 2、PX4、推进器、水泵、云台或夹爪；
- 浏览器服务默认只监听 `127.0.0.1`，不要直接暴露到公网或比赛网络；
- 车辆状态和任务完成仍以车辆状态机的权威消息为准。

## 当前定位

这是 OCS 电脑 A 上的联调和监视工具。后续如果要接入真实车辆，应先确认车辆适配器
发布的 heartbeat/ack/task_report/fault 字段，再把 UI 的状态卡片映射到正式字段；不在
UI 内部增加任务决策逻辑。
