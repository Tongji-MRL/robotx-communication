"""Team-defined OCS <-> vehicle MQTT protocol.

This is deliberately independent of ROS 2 and RoboCommand.  ROS 2 adapters on
the Orins publish normalized JSON envelopes through this protocol; the OCS
then converts the normalized reports to official RoboCommand protobuf reports.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Mapping

PROTOCOL_VERSION = "1"
ROOT = "tongji/robotx/v1"
VEHICLES = ("T-Sky", "T-Wave")
KINDS = (
    "heartbeat", "task_report", "fault", "ack", "command",
)
COMMANDS = (
    "start_task", "pause_task", "resume_task", "stop_task", "set_mode",
    "run_start", "safe_stop", "task4_assistance", "task4_keep_out_zone",
    "task4_all_clear", "task4_moving_object", "task4_readiness_confirm",
    "task4_resume", "ping",
)


def topic(vehicle_id: str, kind: str) -> str:
    if not vehicle_id or "/" in vehicle_id:
        raise ValueError("vehicle_id must be a non-empty MQTT path component")
    if kind not in KINDS:
        raise ValueError(f"unsupported message kind: {kind}")
    return f"{ROOT}/{vehicle_id}/{kind}"


def topic_filter(kind: str = "+") -> str:
    if kind != "+" and kind not in KINDS:
        raise ValueError(f"unsupported message kind: {kind}")
    return f"{ROOT}/+/{kind}"


def make_message(vehicle_id: str, kind: str, payload: Mapping[str, Any], *,
                 message_id: str | None = None, run_id: int | None = None,
                 source: str | None = None, frame_id: str = "unknown") -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"unsupported message kind: {kind}")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": message_id or str(uuid.uuid4()),
        "sent_at_unix_ms": int(time.time() * 1000),
        "run_id": run_id,
        "vehicle_id": vehicle_id,
        "source": source or vehicle_id,
        "frame_id": frame_id,
        "kind": kind,
        "payload": dict(payload),
    }


def encode(message: Mapping[str, Any]) -> bytes:
    validate(message)
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def decode(raw: bytes | str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid protocol JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("protocol message must be a JSON object")
    validate(value)
    return value


def validate(message: Mapping[str, Any]) -> None:
    required = (
        "protocol_version", "message_id", "sent_at_unix_ms", "run_id", "vehicle_id",
        "source", "frame_id", "kind", "payload",
    )
    missing = [name for name in required if name not in message]
    if missing:
        raise ValueError(f"missing protocol fields: {', '.join(missing)}")
    if message["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError(f"unsupported protocol_version: {message['protocol_version']}")
    if not isinstance(message["message_id"], str) or not message["message_id"]:
        raise ValueError("message_id must be a non-empty string")
    if message["run_id"] is not None and (
        not isinstance(message["run_id"], int) or isinstance(message["run_id"], bool)
        or message["run_id"] <= 0
    ):
        raise ValueError("run_id must be null or a positive integer")
    if not isinstance(message["vehicle_id"], str) or not message["vehicle_id"]:
        raise ValueError("vehicle_id must be a non-empty string")
    if not isinstance(message["source"], str) or not message["source"]:
        raise ValueError("source must be a non-empty string")
    if not isinstance(message["frame_id"], str) or not message["frame_id"]:
        raise ValueError("frame_id must be a non-empty string")
    if message["kind"] not in KINDS:
        raise ValueError(f"unsupported message kind: {message['kind']}")
    if not isinstance(message["payload"], dict):
        raise ValueError("payload must be a JSON object")


def command_payload(command: str, *, task_id: str | None = None,
                    command_seq: int | None = None,
                    parameters: Mapping[str, Any] | None = None,
                    priority: str = "NORMAL", preempt: bool = False) -> dict[str, Any]:
    if command not in COMMANDS:
        raise ValueError(f"unsupported command: {command}")
    result: dict[str, Any] = {
        "command": command,
        "priority": priority,
        "preempt": preempt,
    }
    if task_id is not None:
        result["task_id"] = task_id
    if command_seq is not None:
        if command_seq <= 0:
            raise ValueError("command_seq must be positive")
        result["command_seq"] = command_seq
    if parameters:
        result["parameters"] = dict(parameters)
    return result
