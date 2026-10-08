#!/usr/bin/env python3
"""MQTT transport skeleton for the UAV <-> USV state-machine protocol.

State-machine owners provide ``message_handler`` and map normalized messages
to their own ROS 2 topics/services/actions.  This module never controls a
vehicle actuator directly.
"""

from __future__ import annotations

import sys
import threading
from collections import deque
from typing import Any, Callable, Iterable

try:
    import paho.mqtt.client as mqtt
    _MQTT_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - environment dependent
    mqtt = None
    _MQTT_IMPORT_ERROR = exc

from fsm_protocol import (
    VEHICLES,
    ack_for,
    decode,
    encode,
    inbound_filter,
    make_message,
    topic,
    validate_topic,
)


HandlerResult = tuple[bool, str] | None
MessageHandler = Callable[[dict[str, Any]], HandlerResult]


class StateMachineLink:
    """Bidirectional task-level link for one vehicle state machine."""

    def __init__(
        self,
        vehicle_id: str,
        broker: str,
        *,
        port: int = 1883,
        peers: Iterable[str] | None = None,
        message_handler: MessageHandler | None = None,
    ) -> None:
        if mqtt is None:
            raise SystemExit(
                "请先安装 paho-mqtt：python -m pip install -r requirements.txt"
            ) from _MQTT_IMPORT_ERROR
        if vehicle_id not in VEHICLES:
            raise ValueError(f"unsupported vehicle_id: {vehicle_id}")
        selected_peers = tuple(
            peers or (item for item in VEHICLES if item != vehicle_id)
        )
        if not selected_peers or any(
            item not in VEHICLES or item == vehicle_id for item in selected_peers
        ):
            raise ValueError("peers must contain another known vehicle")
        self.vehicle_id = vehicle_id
        self.peers = selected_peers
        self.broker = broker
        self.port = port
        self.message_handler = message_handler or self._safe_default_handler
        self._sequence = 0
        self._sequence_lock = threading.Lock()
        self._seen_order: deque[str] = deque(maxlen=2048)
        self._seen_ids: set[str] = set()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    @staticmethod
    def _safe_default_handler(_message: dict[str, Any]) -> HandlerResult:
        return False, "no state-machine handler configured"

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code != 0:
            print(f"[FSM MQTT] connection failed: {reason_code}", file=sys.stderr)
            return
        client.subscribe(inbound_filter(self.vehicle_id), qos=1)
        print(f"[FSM MQTT] {self.vehicle_id} subscribed to {inbound_filter(self.vehicle_id)}")

    @staticmethod
    def _on_disconnect(
        _client, _userdata, _disconnect_flags, reason_code, _properties=None
    ) -> None:
        print(f"[FSM MQTT] disconnected: {reason_code}", file=sys.stderr)

    def _on_message(self, _client, _userdata, mqtt_message) -> None:
        try:
            message = decode(mqtt_message.payload)
            validate_topic(message, mqtt_message.topic)
            if message["target_vehicle_id"] != self.vehicle_id:
                raise ValueError("message target does not match this state machine")
            if message["source_vehicle_id"] not in self.peers:
                raise ValueError("message source is not an allowed peer")
            if not self._remember_message(str(message["message_id"])):
                print(f"[FSM MQTT] duplicate ignored: {message['message_id']}")
                return
            result = self.message_handler(message)
            if message["kind"] == "command":
                accepted, detail = result or (False, "handler returned no command result")
                self.publish_ack(message, accepted=accepted, detail=detail)
        except Exception as exc:  # keep Paho callback thread alive
            print(f"[FSM MQTT] rejected message: {exc}", file=sys.stderr)

    def connect(self) -> None:
        self.client.connect(self.broker, self.port, keepalive=60)
        self.client.loop_start()

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def publish(
        self,
        target_vehicle_id: str,
        kind: str,
        *,
        task: str,
        message_type: str,
        payload: dict[str, Any],
        run_id: int | None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if target_vehicle_id not in self.peers:
            raise ValueError("target_vehicle_id is not an allowed peer")
        message = make_message(
            self.vehicle_id,
            target_vehicle_id,
            kind,
            task=task,
            message_type=message_type,
            payload=payload,
            sequence=self._next_sequence(),
            run_id=run_id,
            correlation_id=correlation_id,
        )
        self._publish_message(message)
        return message

    def publish_ack(
        self, message: dict[str, Any], *, accepted: bool, detail: str = ""
    ) -> dict[str, Any]:
        ack = ack_for(
            message,
            sequence=self._next_sequence(),
            accepted=accepted,
            state="ACCEPTED" if accepted else "REJECTED",
            detail=detail,
        )
        self._publish_message(ack)
        return ack

    def _publish_message(self, message: dict[str, Any]) -> None:
        mqtt_topic = topic(
            message["source_vehicle_id"], message["target_vehicle_id"], message["kind"]
        )
        result = self.client.publish(mqtt_topic, encode(message), qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"state-machine publish failed: {result.rc}")

    def _next_sequence(self) -> int:
        with self._sequence_lock:
            self._sequence += 1
            return self._sequence

    def _remember_message(self, message_id: str) -> bool:
        if message_id in self._seen_ids:
            return False
        if len(self._seen_order) == self._seen_order.maxlen:
            self._seen_ids.discard(self._seen_order[0])
        self._seen_order.append(message_id)
        self._seen_ids.add(message_id)
        return True
