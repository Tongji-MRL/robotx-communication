#!/usr/bin/env python3
"""OCS-side client for the team-defined vehicle MQTT link.

It is safe by default: it only observes vehicles.  Commands require the
explicit ``--send`` option and are published as validated JSON envelopes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Callable

try:
    import paho.mqtt.client as mqtt
    _MQTT_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover
    mqtt = None
    _MQTT_IMPORT_ERROR = exc

from vehicle_protocol import command_payload, decode, encode, make_message, topic, topic_filter


INTERNAL_COMMAND_TO_PROTOCOL = {
    "RUN_START": "run_start",
    "SAFE_STOP": "safe_stop",
    "TASK4_ASSISTANCE": "task4_assistance",
    "TASK4_KEEP_OUT_ZONE": "task4_keep_out_zone",
    "TASK4_ALL_CLEAR": "task4_all_clear",
    "TASK4_MOVING_OBJECT": "task4_moving_object",
    "TASK4_READINESS_CONFIRM": "task4_readiness_confirm",
    "TASK4_RESUME": "task4_resume",
    "PING": "ping",
}


class VehicleLink:
    def __init__(
        self,
        broker: str,
        port: int,
        vehicle_id: str | None = None,
        on_message: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if mqtt is None:
            raise SystemExit("请先安装 paho-mqtt：python -m pip install -r requirements.txt") from _MQTT_IMPORT_ERROR
        self.vehicle_id = vehicle_id
        self.on_message = on_message
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.broker = broker
        self.port = port

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code != 0:
            print(f"[MQTT] connection failed: {reason_code}", file=sys.stderr)
            return
        suffix = self.vehicle_id or "+"
        client.subscribe(f"tongji/robotx/v1/{suffix}/+", qos=1)
        print(f"[MQTT] connected; observing {topic_filter()}")

    @staticmethod
    def _on_disconnect(_client, _userdata, _disconnect_flags, reason_code, _properties=None) -> None:
        print(f"[MQTT] listener disconnected: {reason_code}", file=sys.stderr)

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            value = decode(message.payload)
            print(f"[RxVehicle] {message.topic}\n{json.dumps(value, ensure_ascii=False, indent=2)}")
            if self.on_message is not None:
                self.on_message(value)
        except Exception as exc:  # keep the internal MQTT loop alive on bad reports
            print(f"[MQTT] ignored malformed message on {message.topic}: {exc}", file=sys.stderr)

    def connect(self) -> None:
        self.client.connect(self.broker, self.port, keepalive=60)
        self.client.loop_start()

    def send(self, vehicle_id: str, command: str, task_id: str | None = None,
             run_id: int | None = None) -> None:
        message = make_message(
            vehicle_id, "command", command_payload(command, task_id=task_id),
            run_id=run_id, source="ocs",
        )
        result = self.client.publish(topic(vehicle_id, "command"), encode(message), qos=1)
        result.wait_for_publish()
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"command publish failed: {result.rc}")
        print(f"[TxCommand] {message['message_id']} -> {topic(vehicle_id, 'command')}")

    def send_action(self, action: dict) -> None:
        """Publish one action returned by ``OcsClient.drain_internal_actions``."""
        if action.get("kind") != "internal_command":
            raise ValueError("only internal_command actions can be sent to a vehicle")
        vehicle_id = action.get("vehicle_id")
        internal_command = action.get("command")
        try:
            command = INTERNAL_COMMAND_TO_PROTOCOL[internal_command]
        except KeyError as exc:
            raise ValueError(f"unsupported internal command: {internal_command}") from exc
        payload = command_payload(
            command,
            command_seq=action.get("command_seq"),
            parameters=action.get("parameters"),
            priority=action.get("priority", "NORMAL"),
            preempt=bool(action.get("preempt", False)),
        )
        message = make_message(
            vehicle_id,
            "command",
            payload,
            run_id=action.get("run_id"),
            source="ocs",
        )
        result = self.client.publish(topic(vehicle_id, "command"), encode(message), qos=1)
        result.wait_for_publish()
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"command publish failed: {result.rc}")
        print(f"[TxCommand] {message['message_id']} -> {topic(vehicle_id, 'command')}")

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description="观察车辆内部 MQTT 链路")
    parser.add_argument("--broker", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--vehicle-id", choices=("T-Sky", "T-Wave"))
    parser.add_argument("--duration", type=float, default=0.0, help="观察秒数，0 表示持续")
    parser.add_argument("--send", nargs=2, metavar=("VEHICLE_ID", "COMMAND"), help="显式发送一条命令")
    parser.add_argument("--task-id", help="命令对应任务，例如 TASK1")
    args = parser.parse_args()
    link = VehicleLink(args.broker, args.port, args.vehicle_id)
    try:
        link.connect()
        if args.send:
            vehicle_id, command = args.send
            link.send(vehicle_id, command, args.task_id)
        deadline = time.monotonic() + args.duration if args.duration else None
        while deadline is None or time.monotonic() < deadline:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
