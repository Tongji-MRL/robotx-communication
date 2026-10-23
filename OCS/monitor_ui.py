#!/usr/bin/env python3
"""Local OCS vehicle monitor and guarded command panel.

This UI connects only to the team-internal MQTT broker.  It does not connect
to RoboCommand and it never publishes directly to the UAV.  The production
OCS gateway remains the owner of official commands; this panel is for
observation and controlled lab diagnostics.
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
    from .vehicle_protocol import command_payload, decode, encode, make_message, topic
except ImportError:  # script execution from the OCS directory
    from vehicle_protocol import command_payload, decode, encode, make_message, topic


ROOT = Path(__file__).resolve().parent
UI_FILE = ROOT / "ui" / "index.html"
VEHICLES = ("T-Wave", "T-Sky")
UI_COMMANDS = {
    "ping",
    "safe_stop",
    "task4_assistance",
    "task4_keep_out_zone",
    "task4_all_clear",
    "task4_moving_object",
    "task4_readiness_confirm",
    "task4_resume",
}
STATUS_SCHEMA = "twave-mission-status-v2"


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
            mission_age = None if self.mission_status_received_unix_ms is None else round(max(0, now_ms - self.mission_status_received_unix_ms) / 1000, 2)
            mission_online = mission_age is not None and mission_age <= self.stale_after_s
            return {
                "now_unix_ms": now_ms,
                "uptime_s": round(time.time() - self.started_at, 1),
                "broker": deepcopy(self.broker),
                "vehicles": vehicles,
                "course": deepcopy(self.course),
                "mission": deepcopy(self.mission_status),
                "mission_status": {"received": self.mission_status_received_unix_ms is not None, "last_received_unix_ms": self.mission_status_received_unix_ms, "age_s": mission_age, "online": mission_online, "status": "实时" if mission_online else ("超时" if mission_age is not None else "未收到")},
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
        self.enable_lab_commands = enable_lab_commands
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
        if not self.enable_lab_commands:
            raise PermissionError("实验室命令已禁用；请使用 --enable-lab-commands 显式开启")
        if command not in UI_COMMANDS:
            raise ValueError(f"UI 不允许发送命令: {command}")
        if self.client is None:
            raise RuntimeError("未安装 paho-mqtt，请先安装 OCS/requirements.txt")
        priority = "CRITICAL" if command == "safe_stop" else "MANUAL_DIAGNOSTIC"
        message = make_message(
            "T-Wave", "command",
            command_payload(
                command,
                parameters=parameters,
                priority=priority,
                preempt=command == "safe_stop",
            ),
            run_id=run_id,
            source="ocs-ui",
        )
        mqtt_topic = topic("T-Wave", "command")
        result = self.client.publish(mqtt_topic, encode(message), qos=1)
        result.wait_for_publish()
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed: {result.rc}")
        self.state.note_command(mqtt_topic, message)
        return message

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code != 0:
            self.state.broker_event(connected=False, host=self.host, port=self.port, event=f"连接失败: {reason_code}")
            return
        client.subscribe("tongji/robotx/v1/+/+", qos=1)
        self.state.broker_event(connected=True, host=self.host, port=self.port, event="内部 MQTT 已连接")

    def _on_disconnect(self, _client, _userdata, _disconnect_flags, reason_code, _properties=None) -> None:
        self.state.broker_event(connected=False, host=self.host, port=self.port, event=f"内部 MQTT 已断开: {reason_code}")

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            envelope = decode(message.payload)
            self.state.note_message(message.topic, envelope)
        except Exception as exc:
            self.state.note_error(f"忽略非法消息 {message.topic}: {exc}")


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
    parser.add_argument("--broker", default="127.0.0.1", help="团队内部 MQTT Broker")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--stale-after", type=float, default=3.0)
    parser.add_argument("--enable-lab-commands", action="store_true", help="allow isolated-lab diagnostic MQTT commands")
    args = parser.parse_args()

    state = MonitorState(stale_after_s=args.stale_after)
    monitor = MqttMonitor(state, args.broker, args.port, args.username, args.password, args.enable_lab_commands)
    handler = type("BoundUiHandler", (UiHandler,), {"state": state, "monitor": monitor})
    server = ThreadingHTTPServer((args.web_host, args.web_port), handler)
    print(f"OCS UI: http://{args.web_host}:{args.web_port}")
    print(f"Monitoring internal MQTT: {args.broker}:{args.port}")
    print("LAB COMMANDS: ENABLED (isolated environment only)" if args.enable_lab_commands else "READ-ONLY MODE: lab commands disabled")
    # Start the page first. MQTT may be started later, and the UI will retry.
    monitor.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        monitor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
