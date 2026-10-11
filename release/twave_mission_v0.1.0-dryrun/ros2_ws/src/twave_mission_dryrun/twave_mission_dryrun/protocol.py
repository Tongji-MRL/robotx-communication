"""Strict, transport-independent JSON schemas for the test-only ROS topics."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "twave-mission-dryrun-v1"


class ProtocolError(ValueError):
    """Raised when a test topic payload is not a valid protocol envelope."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def encode(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def decode(raw: str, *, required: set[str]) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("JSON envelope must be an object")
    missing = required - value.keys()
    if missing:
        raise ProtocolError(f"missing required fields: {', '.join(sorted(missing))}")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ProtocolError("unsupported schema_version")
    if not isinstance(value.get("timestamp"), str):
        raise ProtocolError("timestamp must be an ISO-8601 string")
    try:
        datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolError("timestamp must be ISO-8601") from exc
    if not isinstance(value.get("run_id"), int) or value["run_id"] <= 0:
        raise ProtocolError("run_id must be a positive integer")
    return value


def envelope(*, run_id: int, **fields: Any) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "timestamp": now_iso(), "run_id": run_id, **fields}
