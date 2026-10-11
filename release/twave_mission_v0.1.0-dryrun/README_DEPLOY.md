# T-Wave 主状态机 v0.1.0-dryrun

本包仅用于 Ubuntu 22.04 / ROS 2 Humble 的隔离 dry-run。默认使用 Fake USV
Executor；不会连接 PX4、MAVROS、推进器、水泵、夹爪或发送 arm/disarm、速度、位置命令。
测试复位接口不是生产安全授权接口。

## 上传、校验与解压

Windows PowerShell：

```powershell
scp .\twave_mission_v0.1.0-dryrun.tar.gz robotx@ORIN_HOST:~/uploads/
scp .\twave_mission_v0.1.0-dryrun.sha256 robotx@ORIN_HOST:~/uploads/
```

Orin 上：

```bash
cd ~/uploads
sha256sum -c twave_mission_v0.1.0-dryrun.sha256
mkdir -p ~/robotx_mission_dryrun
tar -xzf twave_mission_v0.1.0-dryrun.tar.gz -C ~/robotx_mission_dryrun
cd ~/robotx_mission_dryrun/twave_mission_v0.1.0-dryrun
chmod +x deploy/twave_mission/scripts/*.sh
```

这不会修改或覆盖既有 `~/robotx_ws`。

## 环境、构建、测试

```bash
source /opt/ros/humble/setup.bash
sudo apt update
sudo apt install -y python3-pytest python3-colcon-common-extensions ros-humble-launch-testing
deploy/twave_mission/scripts/check_environment.sh
deploy/twave_mission/scripts/build.sh
deploy/twave_mission/scripts/acceptance.sh
```

启动、停止与检查：

```bash
export TWAVE_MISSION_STATE_DIR="$HOME/.local/state/twave-mission"
export TWAVE_MISSION_LOG_DIR="$HOME/robotx_logs/twave-mission"
deploy/twave_mission/scripts/start_dry_run.sh
deploy/twave_mission/scripts/stop_dry_run.sh
deploy/twave_mission/scripts/check_state.sh
deploy/twave_mission/scripts/show_logs.sh
```

状态文件位于 `$TWAVE_MISSION_STATE_DIR`，日志位于 `$TWAVE_MISSION_LOG_DIR`。
不得删除 SAFE_STOP 锁存文件来绕过安全状态；必须排除根因并执行受控流程。

## 测试记录和边界

Windows 已报告领域测试 32/32 通过、ROS bridge 6/6 通过；ROS 集成测试因没有
`rclpy` 跳过。Ubuntu 已报告构建、主任务/Task4、SAFE_HOLD/SAFE_STOP、锁存和受控
复位 dry-run 验证。此前 `colcon test-result` 曾报告 `0 tests`；除非本次实际输出
证明，否则不应视为已彻底解决。尚未在 T-Wave Orin 实机完成部署验收。

尚未实现：MQTT runtime、真实 UAV/USV 接口、生产安全复位授权。更新前备份本目录及
状态目录；回滚时恢复上一已验证 tar 包，不复制旧 checkpoint 或绕过 SAFE_STOP。
