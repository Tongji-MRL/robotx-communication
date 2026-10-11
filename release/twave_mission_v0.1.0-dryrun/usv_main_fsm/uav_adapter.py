"""Candidate T-Wave → T-Sky FSM adapter using the existing v1 envelope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from OCS import fsm_protocol

from .models import Ack, Action, ActionType, Target


_CANDIDATE_TYPES = {
    (ActionType.START_TASK, "TASK1"): "CANDIDATE_TASK1_START",
    (ActionType.START_TASK, "TASK3"): "CANDIDATE_TASK3_ARM",
    (ActionType.START_TASK, "TASK4"): "CANDIDATE_TASK4_START",
    (ActionType.PAUSE_TASK, None): "TASK4_PAUSE",
    (ActionType.RESUME_TASK, None): "TASK4_RESUME",
    (ActionType.SAFE_HOLD, None): "CANDIDATE_SAFE_HOLD",
    (ActionType.SAFE_STOP, None): "SAFE_STOP",
}


@dataclass(frozen=True)
class PublishedFsmMessage:
    topic: str
    message: dict[str, Any]


class FakeTransport:
    """Validated in-memory transport with MQTT-style message-id de-duplication."""

    def __init__(self) -> None:
        self.published: list[PublishedFsmMessage] = []
        self._seen_message_ids: set[str] = set()

    def publish(self, mqtt_topic: str, raw: bytes) -> bool:
        message = fsm_protocol.decode(raw)
        fsm_protocol.validate_topic(message, mqtt_topic)
        if message["message_id"] in self._seen_message_ids:
            return False
        self._seen_message_ids.add(message["message_id"])
        self.published.append(PublishedFsmMessage(mqtt_topic, message))
        return True


class UavFsmAdapter:
    """Maps T-Sky-targeted domain actions to candidate FSM v1 commands.

    Candidate message types are explicitly not a claim that the UAV implements
    them.  They preserve the existing envelope, topic, validation and ACK
    correlation semantics while those message types are negotiated.
    """

    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport
        self._sequence = 0
        self._sent_by_message_id: dict[str, Action] = {}
        self._last_inbound_sequence = 0

    def send(self, action: Action) -> PublishedFsmMessage:
        if action.target != Target.UAV:
            raise ValueError("UavFsmAdapter only accepts T-Sky actions")
        self._sequence += 1
        key = (action.action_type, action.task.value if action.task else None)
        message_type = _CANDIDATE_TYPES.get(key) or _CANDIDATE_TYPES.get((action.action_type, None))
        if message_type is None:
            raise ValueError(f"no candidate UAV mapping for {key}")
        payload = {
            "candidate_mapping": True,
            "command_id": action.command_id,
            "domain_action": action.action_type.value,
            "task": action.task.value if action.task else None,
            "parameters": dict(action.parameters),
        }
        message = fsm_protocol.make_message(
            "T-Wave", "T-Sky", "command", task=action.task.value if action.task else "TASK_NONE",
            message_type=message_type, payload=payload, sequence=self._sequence, run_id=action.run_id,
        )
        mqtt_topic = fsm_protocol.topic("T-Wave", "T-Sky", "command")
        self.transport.publish(mqtt_topic, fsm_protocol.encode(message))
        self._sent_by_message_id[message["message_id"]] = action
        return PublishedFsmMessage(mqtt_topic, message)

    def receive_ack(self, mqtt_topic: str, raw: bytes | str) -> Ack | None:
        message = fsm_protocol.decode(raw)
        fsm_protocol.validate_topic(message, mqtt_topic)
        if message["kind"] != "ack" or message["source_vehicle_id"] != "T-Sky" or message["target_vehicle_id"] != "T-Wave":
            raise ValueError("unexpected UAV FSM acknowledgement direction")
        action = self._sent_by_message_id.get(str(message["correlation_id"]))
        if action is None or message["run_id"] != action.run_id:
            return None
        if int(message["sequence"]) <= self._last_inbound_sequence:
            return None
        self._last_inbound_sequence = int(message["sequence"])
        payload = message["payload"]
        return Ack(
            action.command_id, action.run_id, Target.UAV, bool(payload["accepted"]),
            safe_paused=bool(payload.get("safe_paused", False)),
            progress_marker=payload.get("progress_marker"), detail=str(payload.get("detail", "")),
        )

    @staticmethod
    def make_fake_ack(published: PublishedFsmMessage, *, sequence: int, accepted: bool,
                      safe_paused: bool = False, progress_marker: str | None = None,
                      detail: str = "") -> PublishedFsmMessage:
        ack = fsm_protocol.ack_for(published.message, sequence=sequence, accepted=accepted, detail=detail)
        if safe_paused:
            ack["payload"]["safe_paused"] = True
        if progress_marker:
            ack["payload"]["progress_marker"] = progress_marker
        return PublishedFsmMessage(
            fsm_protocol.topic("T-Sky", "T-Wave", "ack"), ack,
        )
