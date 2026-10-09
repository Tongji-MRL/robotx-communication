# OCS 独立测试记录

日期：2026-10-09

## 本次范围

- OCS 请求序号、每车官方报告序号和已接收 `RxCommand.seq` 的跨进程持久化。
- 网关心跳超时、车辆命令 ACK 超时检测；确认 watchdog 不发送任务决策或自动急停。
- 不启动 ROS 2、PX4、真实车辆或执行器，不代替电脑 B 官方 Broker 联调。

## 结果

在项目虚拟环境中执行：

```bash
python -m unittest discover -s OCS -p 'test_*.py'
python -m compileall -q OCS
python -m json.tool OCS/config.example.json >/dev/null
```

结果：30 项单元测试全部通过；Python 编译通过；JSON 配置检查通过。

## 仍需现场验证

- 电脑 B 官方 Broker/test server 与 OCS 的真实 MQTT/Protobuf 收发。
- Broker 临时断开后的重连、官方报告解码和持久化序号连续性。
- 两台 Orin 的真实 ROS 2 适配器、Task4 抢占/checkpoint/恢复和四机时间线日志。
