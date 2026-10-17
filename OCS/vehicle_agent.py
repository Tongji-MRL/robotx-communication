#!/usr/bin/env python3
"""Minimal Orin-side MQTT agent.

The ROS 2 callbacks are intentionally not hard-coded yet.  This first agent
proves the cross-machine protocol and provides a safe simulator.  Later, the
team-specific ROS 2 adapter should call ``publish_report`` and implement
``command_handler`` instead of publishing PX4 or actuator commands directly.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from typing import Any, Callable

try:
    import paho.mqtt.client as mqtt
    _MQTT_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover
    mqtt = None
    _MQTT_IMPORT_ERROR = exc

from vehicle_protocol import command_payload, decode, encode, make_message, topic


class VehicleAgent:
    def __init__(self, vehicle_id: str, broker: str, port: int = 1883,
                 command_handler: Callable[[dict[str, Any]], tuple[bool, str]] | None = None,
                 *, username: str | None = None, password: str | None = None) -> None:
        if mqtt is None:
            raise SystemExit("请先安装 paho-mqtt：python -m pip install -r requirements.txt") from _MQTT_IMPORT_ERROR
        self.vehicle_id = vehicle_id
        self.broker = broker
        self.port = port
        self.command_handler = command_handler or self._safe_default_handler
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._active_run_id: int | None = None
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    @staticmethod
    def _safe_default_handler(_payload: dict[str, Any]) -> tuple[bool, str]:
        return False, "no ROS 2 command handler configured"

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code != 0:
            print(f"[MQTT] connection failed: {reason_code}", file=sys.stderr)
            return
        client.subscribe(topic(self.vehicle_id, "command"), qos=1)
        self._connected.set()
        print(f"[MQTT] vehicle agent online: {self.vehicle_id}")

    def _on_disconnect(self, _client, _userdata, _disconnect_flags, reason_code, _properties=None) -> None:
        self._connected.clear()
        print(f"[MQTT] vehicle agent disconnected: {reason_code}", file=sys.stderr)

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            if message.topic != topic(self.vehicle_id, "command"):
                raise ValueError("command arrived on an unexpected topic")
            envelope = decode(message.payload)
            if envelope["vehicle_id"] != self.vehicle_id:
                raise ValueError("command vehicle_id does not match this agent")
            payload = envelope["payload"]
            if envelope["kind"] != "command":
                return
            accepted, detail = self.command_handler(payload)
            if accepted and payload.get("command") == "run_start":
                self._active_run_id = envelope["run_id"]
            parameters = payload.get("parameters") or {}
            ack = make_message(self.vehicle_id, "ack", {
                "in_reply_to": envelope["message_id"],
                "command": payload.get("command"),
                "command_seq": payload.get("command_seq"),
                "subject_vehicle_id": parameters.get("subject_vehicle_id"),
                "accepted": accepted,
                "state": (
                    "TASK4_PREEMPTED" if accepted and payload.get("preempt")
                    else "ACCEPTED" if accepted else "REJECTED"
                ),
                "preempted_task": parameters.get("preempted_task"),
                "detail": detail,
            }, run_id=envelope["run_id"], source=self.vehicle_id,
               frame_id=envelope["frame_id"])
            self.client.publish(topic(self.vehicle_id, "ack"), encode(ack), qos=1)
            print(f"[Ack] {payload.get('command')}: {'accepted' if accepted else 'rejected'} ({detail})")
        except ValueError as exc:
            print(f"[MQTT] rejected malformed command: {exc}", file=sys.stderr)

    def connect(self) -> None:
        self.client.connect(self.broker, self.port, keepalive=60)
        self.client.loop_start()

    def publish_report(self, kind: str, payload: dict[str, Any], *,
                       run_id: int | None = None, frame_id: str = "unknown") -> None:
        if kind not in ("heartbeat", "task_report", "fault"):
            raise ValueError(f"invalid report kind: {kind}")
        if run_id is not None and run_id != self._active_run_id:
            raise ValueError("refusing to publish a report for a non-active run")
        if not self._connected.is_set() or not self.client.is_connected():
            raise RuntimeError("internal MQTT is disconnected; report not queued as current telemetry")
        message = make_message(
            self.vehicle_id, kind, payload, run_id=run_id,
            source=self.vehicle_id, frame_id=frame_id,
        )
        result = self.client.publish(topic(self.vehicle_id, kind), encode(message), qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"report publish failed: {result.rc}")

    def run(self, simulate: bool = False, heartbeat_period: float = 0.5,
            telemetry_provider: Callable[[], dict[str, Any] | None] | None = None) -> None:
        next_heartbeat = 0.0
        while not self._stop.wait(0.1):
            now = time.monotonic()
            if now >= next_heartbeat:
                try:
                    if simulate:
                        vehicle_type = "uav" if "sky" in self.vehicle_id.lower() else "usv"
                        payload = {
                        "source_mode": "simulation", "state": "AUTO",
                        "position": {
                            "frame_id": "wgs84",
                            "latitude_deg": 1.2806142,
                            "longitude_deg": 103.8557120,
                            "altitude_hae_m": 0.0,
                        },
                        "speed_mps": 0.0, "heading_deg": 0.0, "roll_deg": 0.0, "pitch_deg": 0.0,
                        "vehicle_type": vehicle_type,
                        "health": {"simulator": True, "fcu_connected": True},
                        }
                        if vehicle_type == "uav":
                            payload["flight_phase"] = "grounded"
                    else:
                        payload = telemetry_provider() if telemetry_provider else None
                        if payload is None:
                            next_heartbeat = now + heartbeat_period
                            continue
                    self.publish_report("heartbeat", payload, run_id=self._active_run_id, frame_id="wgs84")
                except RuntimeError as exc:
                    # Keep the agent alive while Paho reconnects after a broker outage.
                    print(f"[MQTT] heartbeat deferred: {exc}", file=sys.stderr)
                next_heartbeat = now + heartbeat_period

    def close(self) -> None:
        self._stop.set()
        self.client.loop_stop()
        self.client.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description="Orin 侧车辆 MQTT 适配器骨架")
    parser.add_argument("--vehicle-id", choices=("T-Sky", "T-Wave"), required=True)
    parser.add_argument("--broker", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--simulate", action="store_true", help="只发布模拟心跳，不连接 ROS 2 或硬件")
    parser.add_argument(
        "--accept-commands",
        action="store_true",
        help="联调模式下接受命令并回 ACK；不连接真实执行器",
    )
    args = parser.parse_args()
    command_handler = (
        (lambda _payload: (True, "simulated command accepted"))
        if args.accept_commands else None
    )
    agent = VehicleAgent(args.vehicle_id, args.broker, args.port, command_handler,
                         username=args.username, password=args.password)
    try:
        agent.connect()
        agent.run(simulate=args.simulate)
    except KeyboardInterrupt:
        pass
    finally:
        agent.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
