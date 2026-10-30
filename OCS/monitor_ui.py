#!/usr/bin/env python3
"""Local OCS vehicle monitor and guarded command panel.

This UI observes raw team MQTT heartbeats and the formal ROS 2 FSM API.  It
does not connect to RoboCommand and is never a mission command source.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from collections import deque
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - exercised on installations without MQTT deps
    mqtt = None

try:
    from .vehicle_link import HEARTBEAT_TOPICS, heartbeat_envelope
    from .vehicle_protocol import command_payload, encode, make_message, topic
except ImportError:  # script execution from the OCS directory
    from vehicle_link import HEARTBEAT_TOPICS, heartbeat_envelope
    from vehicle_protocol import command_payload, encode, make_message, topic


ROOT = Path(__file__).resolve().parent
UI_FILE = ROOT / "ui" / "index.html"
VEHICLES = ("T-Wave", "T-Sky")
STATUS_SCHEMA = "twave-mission-status-v2"
MISSION_STATUS_TOPIC = "/tongji_mrl/mission/status"
MISSION_REPORT_TOPIC = "/tongji_mrl/mission/task_report"
MISSION_FAULT_TOPIC = "/tongji_mrl/mission/fault"


def _empty_vehicle(vehicle_id: str) -> dict[str, Any]:
    return {
        "vehicle_id": vehicle_id,
        "online": False,
        "status": "未连接",
        "last_seen_unix_ms": None,
        "heartbeat_age_s": None,
        "heartbeat": None,
        "last_ack": None,
        "last_task_report": None,
        "last_fault": None,
        "last_updated_unix_ms": None,
    }


class MonitorState:
    """Thread-safe in-memory state used by MQTT and HTTP threads."""

    def __init__(self, stale_after_s: float = 3.0) -> None:
        self.stale_after_s = stale_after_s
        self.lock = threading.RLock()
        self.started_at = time.time()
        self.broker = {
            "connected": False,
            "host": None,
            "port": None,
            "last_event": "等待连接",
        }
        self.vehicles = {vehicle_id: _empty_vehicle(vehicle_id) for vehicle_id in VEHICLES}
        self.course: dict[str, Any] | None = None
        self.mission_status: dict[str, Any] | None = None
        self.mission_status_received_unix_ms: int | None = None
        # Wall-clock time is kept for the API/UI, but freshness must not be
        # affected by an NTP or manual Windows clock adjustment.
        self.mission_status_received_monotonic: float | None = None
        self.fsm_task_report: dict[str, Any] | None = None
        self.fsm_task_report_received_unix_ms: int | None = None
        self.fsm_fault: dict[str, Any] | None = None
        self.fsm_fault_received_unix_ms: int | None = None
        self.ros2 = {"available": False, "connected": False, "last_event": "ROS2 未收到"}
        self.official = {"connected": None, "last_course": None, "last_command": None, "last_report": None, "last_error": None}
        self.messages: deque[dict[str, Any]] = deque(maxlen=300)
        self.commands: deque[dict[str, Any]] = deque(maxlen=80)

    def broker_event(self, *, connected: bool, host: str, port: int, event: str) -> None:
        with self.lock:
            self.broker = {
                "connected": connected,
                "host": host,
                "port": port,
                "last_event": event,
            }
            self._append_message("system", event, {"connected": connected})

    def note_error(self, message: str) -> None:
        with self.lock:
            self._append_message("error", message, {})

    def note_message(self, mqtt_topic: str, envelope: Mapping[str, Any], direction: str = "in") -> None:
        with self.lock:
            kind = str(envelope.get("kind", "unknown"))
            vehicle_id = str(envelope.get("vehicle_id", ""))
            payload = dict(envelope.get("payload") or {})
            if kind == "mission_status":
                self._note_mission_status(payload)
            elif kind == "course_config":
                self.course = payload
            elif vehicle_id in self.vehicles:
                vehicle = self.vehicles[vehicle_id]
                if kind == "heartbeat":
                    sent_at = envelope.get("sent_at_unix_ms")
                    vehicle["last_seen_unix_ms"] = sent_at
                    vehicle["last_updated_unix_ms"] = int(time.time() * 1000)
                    vehicle["heartbeat"] = payload
                    vehicle["online"] = True
                    vehicle["status"] = "在线"
                    # Connectivity evidence must not clear a latched fault.
                    if vehicle["last_fault"] is not None:
                        vehicle["status"] = str(vehicle["last_fault"].get("safety_state") or "FAULT")
                elif kind == "ack":
                    vehicle["last_ack"] = payload
                elif kind == "task_report":
                    vehicle["last_task_report"] = payload
                elif kind == "fault":
                    vehicle["last_fault"] = payload
                    vehicle["status"] = "故障"
                if kind in {"ack", "task_report", "fault"}:
                    vehicle["last_updated_unix_ms"] = int(time.time() * 1000)
            self._append_message(
                direction,
                f"{kind} · {vehicle_id or 'system'}",
                {"topic": mqtt_topic, "message": deepcopy(dict(envelope))},
            )

    def ros2_event(self, *, available: bool, connected: bool, event: str) -> None:
        with self.lock:
            self.ros2 = {"available": available, "connected": connected, "last_event": event}

    def note_fsm_status(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid FSM status JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("FSM status must be a JSON object")
        with self.lock:
            # Accept the current mission_planner/uav/usv form and the historic
            # status-v2 display form.  Neither is rewritten for the FSM.
            if payload.get("schema_version") == STATUS_SCHEMA:
                self._note_mission_status(payload)
            elif not isinstance(payload.get("mission_planner"), str):
                raise ValueError("FSM status requires mission_planner string")
            else:
                self.mission_status = deepcopy(payload)
                self.mission_status_received_unix_ms = int(time.time() * 1000)
                self.mission_status_received_monotonic = time.monotonic()
            self._append_message("ros2", "FSM status", {"topic": MISSION_STATUS_TOPIC, "payload": deepcopy(payload)})

    def note_fsm_task_report(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid FSM task report JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("FSM task report must be a JSON object")
        with self.lock:
            self.fsm_task_report = deepcopy(payload)
            self.fsm_task_report_received_unix_ms = int(time.time() * 1000)
            self._append_message("ros2", "FSM task report", {"topic": MISSION_REPORT_TOPIC, "payload": deepcopy(payload)})

    def note_fsm_fault(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid FSM fault JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("FSM fault must be a JSON object")
        with self.lock:
            self.fsm_fault = deepcopy(payload)
            self.fsm_fault_received_unix_ms = int(time.time() * 1000)
            label = payload.get("vehicle_id", payload.get("vehicle"))
            vehicle_id = {"usv": "T-Wave", "uav": "T-Sky"}.get(label, label)
            if vehicle_id in self.vehicles:
                vehicle = self.vehicles[vehicle_id]
                vehicle["last_fault"] = deepcopy(payload)
                vehicle["status"] = str(payload.get("safety_state") or "FAULT")
                vehicle["last_updated_unix_ms"] = self.fsm_fault_received_unix_ms
            self._append_message("ros2", "FSM fault", {
                "topic": MISSION_FAULT_TOPIC, "payload": deepcopy(payload),
            })

    def _note_mission_status(self, payload: Mapping[str, Any]) -> None:
        """Accept only the formal status-v2 shape; never synthesize status."""
        if payload.get("schema_version") != STATUS_SCHEMA:
            raise ValueError("mission_status must contain twave-mission-status-v2")
        if not isinstance(payload.get("fsm_state"), str) or not payload["fsm_state"]:
            raise ValueError("mission_status fsm_state must be a non-empty string")
        if payload.get("run_id") is not None and (not isinstance(payload["run_id"], int) or isinstance(payload["run_id"], bool) or payload["run_id"] <= 0):
            raise ValueError("mission_status run_id must be null or positive integer")
        required_objects = ("course", "safety", "vehicles", "legacy")
        missing = [name for name in required_objects if not isinstance(payload.get(name), Mapping)]
        if missing:
            raise ValueError(f"mission_status missing object fields: {', '.join(missing)}")
        if not isinstance(payload.get("timestamp"), str) or not payload["timestamp"]:
            raise ValueError("mission_status timestamp must be a non-empty string")
        self.mission_status = deepcopy(dict(payload))
        self.mission_status_received_unix_ms = int(time.time() * 1000)
        self.mission_status_received_monotonic = time.monotonic()

    def note_command(self, mqtt_topic: str, envelope: Mapping[str, Any]) -> None:
        with self.lock:
            command = dict(envelope.get("payload") or {})
            record = {
                "sent_at_unix_ms": envelope.get("sent_at_unix_ms"),
                "vehicle_id": envelope.get("vehicle_id"),
                "command": command,
                "message_id": envelope.get("message_id"),
                "topic": mqtt_topic,
            }
            self.commands.appendleft(record)
            self._append_message("out", f"{command.get('command', 'command')} · T-Wave", record)

    def snapshot(self) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        now_monotonic = time.monotonic()
        with self.lock:
            vehicles = deepcopy(self.vehicles)
            for vehicle in vehicles.values():
                sent_at = vehicle.get("last_seen_unix_ms")
                age = None if not isinstance(sent_at, int) else max(0.0, (now_ms - sent_at) / 1000)
                vehicle["heartbeat_age_s"] = round(age, 2) if age is not None else None
                if age is None or age > self.stale_after_s:
                    vehicle["online"] = False
                    if vehicle["status"] == "在线":
                        vehicle["status"] = "心跳超时"
            mission_age = None if self.mission_status_received_monotonic is None else round(
                max(0.0, now_monotonic - self.mission_status_received_monotonic), 2
            )
            mission_online = mission_age is not None and mission_age <= self.stale_after_s
            return {
                "now_unix_ms": now_ms,
                "uptime_s": round(time.time() - self.started_at, 1),
                "broker": deepcopy(self.broker),
                "vehicles": vehicles,
                "course": deepcopy(self.course),
                "mission": deepcopy(self.mission_status),
                "mission_status": {"received": self.mission_status_received_unix_ms is not None, "last_received_unix_ms": self.mission_status_received_unix_ms, "age_s": mission_age, "online": mission_online, "status": "实时" if mission_online else ("超时" if mission_age is not None else "未收到")},
                "fsm_task_report": deepcopy(self.fsm_task_report),
                "fsm_task_report_received_unix_ms": self.fsm_task_report_received_unix_ms,
                "fsm_fault": deepcopy(self.fsm_fault),
                "fsm_fault_received_unix_ms": self.fsm_fault_received_unix_ms,
                "ros2": deepcopy(self.ros2),
                "official": deepcopy(self.official),
                "messages": list(self.messages),
                "commands": list(self.commands),
            }

    def _append_message(self, direction: str, title: str, data: Mapping[str, Any]) -> None:
        self.messages.appendleft({
            "received_at_unix_ms": int(time.time() * 1000),
            "direction": direction,
            "title": title,
            "data": deepcopy(dict(data)),
        })


class MqttMonitor:
    def __init__(self, state: MonitorState, host: str, port: int, username: str | None = None,
                 password: str | None = None, enable_lab_commands: bool = False) -> None:
        self.state = state
        self.host = host
        self.port = port
        # The monitor is read-only in every mode.  This retained parameter only
        # avoids silently accepting legacy command-line invocations.
        self.enable_lab_commands = False
        self.client = None
        if mqtt is not None:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        else:
            self.state.broker_event(
                connected=False,
                host=host,
                port=port,
                event="未安装 paho-mqtt，当前为离线界面",
            )
        if username and self.client is not None:
            self.client.username_pw_set(username, password)
        if self.client is not None:
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._connect_loop, name="ocs-ui-mqtt", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.client is None:
            return
        self.client.loop_stop()
        if self.client.is_connected():
            self.client.disconnect()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _connect_loop(self) -> None:
        """Keep the web UI available while the internal broker is offline."""
        if self.client is None:
            return
        while not self._stop.is_set():
            if not self.client.is_connected():
                try:
                    self.client.connect(self.host, self.port, keepalive=60)
                    self.client.loop_start()
                    # on_connect updates the visible broker state.
                except Exception as exc:
                    self.state.broker_event(
                        connected=False,
                        host=self.host,
                        port=self.port,
                        event=f"等待 MQTT：{exc}",
                    )
                    self._stop.wait(3.0)
                    continue
            self._stop.wait(1.0)

    def send_command(self, command: str, *, parameters: Mapping[str, Any] | None = None,
                     run_id: int | None = None) -> dict[str, Any]:
        raise PermissionError("监控页面是只读的；RunStart、Task4 和执行命令只能经正式 OCS Gateway")

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code != 0:
            self.state.broker_event(connected=False, host=self.host, port=self.port, event=f"连接失败: {reason_code}")
            return
        for mqtt_topic in HEARTBEAT_TOPICS:
            client.subscribe(mqtt_topic, qos=1)
        self.state.broker_event(connected=True, host=self.host, port=self.port, event="内部 MQTT 已连接")

    def _on_disconnect(self, _client, _userdata, _disconnect_flags, reason_code, _properties=None) -> None:
        self.state.broker_event(connected=False, host=self.host, port=self.port, event=f"内部 MQTT 已断开: {reason_code}")

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            envelope = heartbeat_envelope(message.topic, message.payload)
            self.state.note_message(message.topic, envelope)
        except Exception as exc:
            self.state.note_error(f"忽略非法消息 {message.topic}: {exc}")


class Ros2Monitor:
    """Optional, non-blocking ROS 2 observer for the formal FSM outputs."""

    def __init__(self, state: MonitorState) -> None:
        self.state = state
        self._rclpy = None
        self._node = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            import rclpy
            from rclpy.node import Node
            from std_msgs.msg import String
        except ImportError as exc:
            self.state.ros2_event(available=False, connected=False, event=f"ROS2 不可用: {exc}")
            return

        state = self.state
        class MonitorNode(Node):
            def __init__(node_self) -> None:
                super().__init__("robotx_ocs_monitor")
                node_self.create_subscription(String, MISSION_STATUS_TOPIC, lambda msg: state.note_fsm_status(msg.data), 10)
                node_self.create_subscription(String, MISSION_REPORT_TOPIC, lambda msg: state.note_fsm_task_report(msg.data), 10)
                node_self.create_subscription(String, MISSION_FAULT_TOPIC, lambda msg: state.note_fsm_fault(msg.data), 10)
        try:
            rclpy.init(args=None)
            self._rclpy, self._node = rclpy, MonitorNode()
            self.state.ros2_event(available=True, connected=True, event="已订阅 FSM ROS2 Status/TaskReport")
            self._thread = threading.Thread(target=rclpy.spin, args=(self._node,), name="ocs-ui-ros2", daemon=True)
            self._thread.start()
        except Exception as exc:
            self.state.ros2_event(available=True, connected=False, event=f"ROS2 初始化失败: {exc}")

    def stop(self) -> None:
        if self._node is not None:
            self._node.destroy_node()
        if self._rclpy is not None and self._rclpy.ok():
            self._rclpy.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2)


class UiHandler(BaseHTTPRequestHandler):
    state: MonitorState
    monitor: MqttMonitor

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._send_file(UI_FILE, "text/html; charset=utf-8")
        elif path == "/api/state":
            snapshot = self.state.snapshot()
            # Added metadata is non-breaking for existing /api/state clients.
            snapshot["lab_commands_enabled"] = self.monitor.enable_lab_commands
            self._send_json(snapshot)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/command":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            if not self.monitor.enable_lab_commands:
                self._send_json({"ok": False, "error": "只读模式：实验室命令未启用"}, status=HTTPStatus.FORBIDDEN)
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            command = str(body.get("command", ""))
            if command == "safe_stop" and body.get("confirm") is not True:
                raise ValueError("SAFE_STOP 必须显式确认")
            parameters = body.get("parameters") or {}
            if not isinstance(parameters, dict):
                raise ValueError("parameters 必须是 JSON 对象")
            run_id = body.get("run_id")
            if run_id is not None:
                run_id = int(run_id)
            message = self.monitor.send_command(command, parameters=parameters, run_id=run_id)
            self._send_json({"ok": True, "message_id": message["message_id"], "topic": topic("T-Wave", "command")})
        except (ValueError, TypeError, RuntimeError, PermissionError, json.JSONDecodeError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _send_file(self, path: Path, content_type: str) -> None:
        try:
            content = path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, value: Mapping[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description="OCS 本地车辆监控 UI")
    parser.add_argument("--broker", default="192.168.206.123", help="团队内部 MQTT Broker")
    parser.add_argument("--port", type=int, default=1884)
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--stale-after", type=float, default=3.0)
    parser.add_argument("--enable-lab-commands", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    state = MonitorState(stale_after_s=args.stale_after)
    monitor = MqttMonitor(state, args.broker, args.port, args.username, args.password, args.enable_lab_commands)
    ros2_monitor = Ros2Monitor(state)
    handler = type("BoundUiHandler", (UiHandler,), {"state": state, "monitor": monitor})
    server = ThreadingHTTPServer((args.web_host, args.web_port), handler)
    print(f"OCS UI: http://{args.web_host}:{args.web_port}")
    print(f"Monitoring internal MQTT: {args.broker}:{args.port}")
    print("LAB COMMANDS: ENABLED (isolated environment only)" if args.enable_lab_commands else "READ-ONLY MODE: lab commands disabled")
    # Start the page first. MQTT may be started later, and the UI will retry.
    monitor.start()
    ros2_monitor.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        monitor.stop()
        ros2_monitor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
