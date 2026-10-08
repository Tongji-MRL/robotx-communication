"""Team-defined UAV <-> USV state-machine protocol.

This protocol is intentionally separate from both official RoboCommand and
the OCS <-> vehicle protocol.  It carries only normalized task-level state,
events, commands, and acknowledgements between T-Sky and T-Wave.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Mapping


PROTOCOL_VERSION = "1"
ROOT = "tongji/robotx/fsm/v1"
VEHICLES = ("T-Sky", "T-Wave")
KINDS = ("status", "event", "command", "ack")
TASKS = ("TASK_NONE", "TASK1", "TASK3", "TASK4")


def topic(source_vehicle_id: str, target_vehicle_id: str, kind: str) -> str:
    _validate_vehicle_pair(source_vehicle_id, target_vehicle_id)
    if kind not in KINDS:
        raise ValueError(f"unsupported state-machine message kind: {kind}")
    return f"{ROOT}/{source_vehicle_id}/{target_vehicle_id}/{kind}"


def inbound_filter(vehicle_id: str) -> str:
    if vehicle_id not in VEHICLES:
        raise ValueError(f"unsupported vehicle_id: {vehicle_id}")
    return f"{ROOT}/+/{vehicle_id}/+"


def make_message(
    source_vehicle_id: str,
    target_vehicle_id: str,
    kind: str,
    *,
    task: str,
    message_type: str,
    payload: Mapping[str, Any],
    sequence: int,
    run_id: int | None,
    message_id: str | None = None,
    correlation_id: str | None = None,
    sent_at_unix_ms: int | None = None,
) -> dict[str, Any]:
    message = {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": message_id or str(uuid.uuid4()),
        "sent_at_unix_ms": (
            int(time.time() * 1000)
            if sent_at_unix_ms is None
            else sent_at_unix_ms
        ),
        "run_id": run_id,
        "sequence": sequence,
        "source_vehicle_id": source_vehicle_id,
        "target_vehicle_id": target_vehicle_id,
        "kind": kind,
        "task": task,
        "message_type": message_type,
        "correlation_id": correlation_id,
        "payload": dict(payload),
    }
    validate(message)
    return message


def ack_for(
    message: Mapping[str, Any],
    *,
    sequence: int,
    accepted: bool,
    state: str = "ACCEPTED",
    detail: str = "",
) -> dict[str, Any]:
    validate(message)
    return make_message(
        str(message["target_vehicle_id"]),
        str(message["source_vehicle_id"]),
        "ack",
        task=str(message["task"]),
        message_type="ACK",
        payload={
            "in_reply_to": message["message_id"],
            "accepted": bool(accepted),
            "state": state,
            "detail": detail,
            "original_message_type": message["message_type"],
        },
        sequence=sequence,
        run_id=message["run_id"],
        correlation_id=str(message["message_id"]),
    )


def encode(message: Mapping[str, Any]) -> bytes:
    validate(message)
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def decode(raw: bytes | str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid state-machine JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("state-machine message must be a JSON object")
    validate(value)
    return value


def validate_topic(message: Mapping[str, Any], actual_topic: str) -> None:
    validate(message)
    expected = topic(
        str(message["source_vehicle_id"]),
        str(message["target_vehicle_id"]),
        str(message["kind"]),
    )
    if actual_topic != expected:
        raise ValueError(f"message topic mismatch: expected {expected}, got {actual_topic}")


def validate(message: Mapping[str, Any]) -> None:
    required = (
        "protocol_version",
        "message_id",
        "sent_at_unix_ms",
        "run_id",
        "sequence",
        "source_vehicle_id",
        "target_vehicle_id",
        "kind",
        "task",
        "message_type",
        "correlation_id",
        "payload",
    )
    missing = [name for name in required if name not in message]
    if missing:
        raise ValueError(f"missing state-machine fields: {', '.join(missing)}")
    if message["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError(f"unsupported protocol_version: {message['protocol_version']}")
    if not isinstance(message["message_id"], str) or not message["message_id"]:
        raise ValueError("message_id must be a non-empty string")
    if not isinstance(message["sent_at_unix_ms"], int) or isinstance(
        message["sent_at_unix_ms"], bool
    ):
        raise ValueError("sent_at_unix_ms must be an integer")
    if message["run_id"] is not None and (
        not isinstance(message["run_id"], int)
        or isinstance(message["run_id"], bool)
        or message["run_id"] <= 0
    ):
        raise ValueError("run_id must be null or a positive integer")
    if (
        not isinstance(message["sequence"], int)
        or isinstance(message["sequence"], bool)
        or message["sequence"] <= 0
    ):
        raise ValueError("sequence must be a positive integer")
    _validate_vehicle_pair(
        str(message["source_vehicle_id"]), str(message["target_vehicle_id"])
    )
    if message["kind"] not in KINDS:
        raise ValueError(f"unsupported state-machine message kind: {message['kind']}")
    if message["task"] not in TASKS:
        raise ValueError(f"unsupported task: {message['task']}")
    if not isinstance(message["message_type"], str) or not message["message_type"]:
        raise ValueError("message_type must be a non-empty string")
    if message["correlation_id"] is not None and not isinstance(
        message["correlation_id"], str
    ):
        raise ValueError("correlation_id must be null or a string")
    if not isinstance(message["payload"], dict):
        raise ValueError("payload must be a JSON object")
    if message["kind"] == "ack":
        if not message["correlation_id"]:
            raise ValueError("ack requires correlation_id")
        if not isinstance(message["payload"].get("accepted"), bool):
            raise ValueError("ack payload requires boolean accepted")
        if message["payload"].get("in_reply_to") != message["correlation_id"]:
            raise ValueError("ack in_reply_to must match correlation_id")


def _validate_vehicle_pair(source_vehicle_id: str, target_vehicle_id: str) -> None:
    if source_vehicle_id not in VEHICLES:
        raise ValueError(f"unsupported source_vehicle_id: {source_vehicle_id}")
    if target_vehicle_id not in VEHICLES:
        raise ValueError(f"unsupported target_vehicle_id: {target_vehicle_id}")
    if source_vehicle_id == target_vehicle_id:
        raise ValueError("source and target vehicles must be different")
