"""T-Wave's dry-run-only adapter for the existing OCS MQTT envelope.

The adapter intentionally owns transport validation only.  Mission decisions
remain in :class:`MissionBridge`, and its ``usv_command`` output must be wired
only to the existing FakeUSVExecutor test topic.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from OCS import vehicle_protocol

from .protocol import envelope as dryrun_envelope


PublishMqtt = Callable[[str, bytes], None]
PublishDryRun = Callable[[str, dict[str, Any]], None]


class TWaveMqttRuntime:
    """Map validated OCS commands to the frozen MissionCoordinator interface.

    RoboCommand ingress only creates ``run_start`` and ``task4_cmd`` messages.
    Mission decisions and safety latching remain in MissionCoordinator.
    """

    _PREEMPT = {"task4_assistance", "task4_keep_out_zone", "task4_moving_object"}
    _PENDING_POLICY = {"task4_all_clear", "task4_readiness_confirm", "task4_resume"}

    def __init__(
        self,
        checkpoint_path: str | Path,
        publish_mqtt: PublishMqtt,
        publish_dryrun: PublishDryRun,
        *,
        max_message_age_seconds: float = 300.0,
        now_ms: Callable[[], int] | None = None,
        command_topic: str | None = None,
        outbound_topics: dict[str, str] | None = None,
    ) -> None:
        if max_message_age_seconds <= 0:
            raise ValueError("max_message_age_seconds must be positive")
        self.publish_mqtt = publish_mqtt
        self.publish_dryrun = publish_dryrun
        self.max_message_age_ms = int(max_message_age_seconds * 1000)
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.command_topic = command_topic or vehicle_protocol.topic("T-Wave", "command")
        self.outbound_topics = outbound_topics or {
            kind: vehicle_protocol.topic("T-Wave", kind)
            for kind in ("ack", "task_report", "fault")
        }
        if any(not isinstance(value, str) or not value for value in self.outbound_topics.values()):
            raise ValueError("outbound MQTT topics must be non-empty strings")
        # Kept for API compatibility with existing launch code.  It now emits
        # frozen mission-topic messages, never direct coordinator calls.
        self.publish_mission = publish_dryrun
        self._seen_order: deque[str] = deque(maxlen=2048)
        self._seen_ids: set[str] = set()
        self._responses: dict[str, dict[str, Any]] = {}
        self._last_command_seq = 0
        self._latest_run_id = 0
        self._active_run_id: int | None = None

    def receive(self, mqtt_topic: str, raw: bytes | str) -> None:
        """Process one OCS MQTT command and always return a protocol ACK.

        Malformed messages cannot be ACKed safely because their reply metadata
        is untrusted; they are rejected by raising ``ValueError`` to the MQTT
        callback, which logs the error and keeps the connection alive.
        """
        envelope = vehicle_protocol.decode(raw)
        self._validate_envelope(mqtt_topic, envelope)
        message_id = str(envelope["message_id"])
        if message_id in self._seen_ids:
            self._publish(self._ack(envelope, True, "DUPLICATE", "already processed"))
            return
        self._remember(message_id)

        try:
            self._validate_freshness_and_order(envelope)
            command = str(envelope["payload"]["command"])
            if command == "run_start":
                self._forward(envelope, "RUN_START")
            elif command in self._PREEMPT:
                self._forward(envelope, "TASK4_PREEMPT")
            elif command in self._PENDING_POLICY:
                response = self._ack(
                    envelope, True, "RECEIVED_PENDING_RECOVERY_POLICY",
                    "received; no automatic Task4 recovery or UAV action",
                )
                self._responses[message_id] = response
                self._publish(response)
                return
            else:
                raise ValueError("unsupported T-Wave coordinator command")
        except ValueError as exc:
            response = self._ack(envelope, False, "REJECTED", str(exc))
        else:
            response = self._ack(envelope, True, "ACCEPTED", "forwarded to dry-run MissionBridge")
        self._responses[message_id] = response
        self._publish(response)

    def _validate_envelope(self, mqtt_topic: str, message: dict[str, Any]) -> None:
        if mqtt_topic != self.command_topic:
            raise ValueError("OCS command arrived on an invalid vehicle topic")
        if message["vehicle_id"] != "T-Wave" or message["kind"] != "command":
            raise ValueError("only T-Wave command envelopes are accepted")
        if message["source"] != "ocs":
            raise ValueError("command envelope source must be ocs")
        payload = message["payload"]
        if payload.get("command") not in vehicle_protocol.COMMANDS:
            raise ValueError("unsupported command")
        sequence = payload.get("command_seq")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
            raise ValueError("positive command_seq required")
        if not isinstance(message["run_id"], int) or isinstance(message["run_id"], bool) or message["run_id"] <= 0:
            raise ValueError("positive run_id required")

    def _validate_freshness_and_order(self, message: dict[str, Any]) -> None:
        age = self.now_ms() - int(message["sent_at_unix_ms"])
        if age > self.max_message_age_ms:
            raise ValueError("stale command rejected")
        if age < -self.max_message_age_ms:
            raise ValueError("command timestamp is too far in the future")
        run_id = int(message["run_id"])
        command = str(message["payload"]["command"])
        if command == "run_start":
            if run_id < self._latest_run_id:
                raise ValueError("old run_id rejected")
        elif run_id != self._active_run_id:
            raise ValueError("command run_id does not match active run")
        sequence = int(message["payload"]["command_seq"])
        if sequence <= self._last_command_seq:
            raise ValueError("old or out-of-order command_seq rejected")
        self._last_command_seq = sequence
        self._latest_run_id = max(self._latest_run_id, run_id)
        if command == "run_start":
            self._active_run_id = run_id

    def _forward(self, message: dict[str, Any], command: str) -> None:
        payload = message["payload"]
        parameters = payload.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be an object")
        topic = "run_start" if command == "RUN_START" else "task4_cmd"
        self.publish_mission(topic, dryrun_envelope(
            run_id=int(message["run_id"]), command_id=str(message["message_id"]),
            command=command, parameters=parameters,
        ))

    def receive_mission_report(self, name: str, payload: dict[str, Any]) -> None:
        """Convert frozen MissionCoordinator egress to OCS vehicle reports."""
        if name not in {"status", "task_report", "fault"}:
            raise ValueError(f"unexpected mission report: {name}")
        kind = "fault" if name == "fault" else "task_report"
        report_run_id = payload.get("run_id")
        self._publish(vehicle_protocol.make_message(
            "T-Wave", kind, payload,
            run_id=report_run_id if isinstance(report_run_id, int) and report_run_id > 0 else None,
            source="T-Wave",
        ))

    def _ack(self, request: dict[str, Any], accepted: bool, state: str, detail: str) -> dict[str, Any]:
        payload = request["payload"]
        return vehicle_protocol.make_message("T-Wave", "ack", {
            "in_reply_to": request["message_id"], "command": payload.get("command"),
            "command_seq": payload.get("command_seq"), "accepted": accepted,
            "state": state, "detail": detail,
        }, run_id=request["run_id"], source="T-Wave", frame_id=request["frame_id"])

    def _publish(self, message: dict[str, Any]) -> None:
        self.publish_mqtt(self.outbound_topics[message["kind"]], vehicle_protocol.encode(message))

    def _remember(self, message_id: str) -> None:
        if len(self._seen_order) == self._seen_order.maxlen:
            removed = self._seen_order.popleft()
            self._seen_ids.discard(removed)
            self._responses.pop(removed, None)
        self._seen_order.append(message_id)
        self._seen_ids.add(message_id)
