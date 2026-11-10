"""Read-only normalization for the UAV's ROS2 JSON status topic.

This module does not publish ROS2, MQTT, or vehicle commands.  It preserves
the received JSON for GCS display and only returns an official-heartbeat input
when every mandatory official field has an authoritative source.
"""
from __future__ import annotations

import json
import math
import time
from typing import Any, Mapping


# The ORIN producer serializes protobuf enum names, while older producers use
# the short values below.  Normalize at this boundary only; ``raw`` retains
# the message exactly as received for diagnostics.
_VEHICLE_TYPES = {"uav": "uav", "TYPE_UAV": "uav"}
_STATES = {
    "AUTO": "AUTO", "MANUAL": "MANUAL", "KILLED": "KILLED",
    "STATE_AUTO": "AUTO", "STATE_MANUAL": "MANUAL", "STATE_KILLED": "KILLED",
}
_FLIGHT_PHASES = {
    "GROUNDED": "grounded", "AIRBORNE": "airborne",
    "FLIGHT_PHASE_GROUNDED": "grounded", "FLIGHT_PHASE_AIRBORNE": "airborne",
}
_TASKS = {
    "none": "none", "TASK_NONE": "none",
    "task1": "task1", "TASK_SAFE_PASSAGE": "task1",
    "task2": "task2", "TASK_INFRA_SURVEY_REPAIR": "task2",
    "task3": "task3", "TASK_COORDINATED_LOGISTICS": "task3",
    "task4": "task4", "TASK_DYNAMIC_INCIDENT": "task4",
}
_OFFICIAL_HEARTBEAT_MAX_AGE_MS = 3_000


def _number(value: Any, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    value = float(value)
    if not low <= value <= high:
        raise ValueError(f"{label} out of range")
    return value


def normalize_uav_status(raw: str | bytes | Mapping[str, Any], *, source_vehicle_id: str,
                         vehicle_id: str = "T-Sky", uav_registration: str | None = None,
                         trusted_status_source: bool = False,
                         use_ocs_receipt_for_freshness: bool = False,
                         received_unix_ms: int | None = None) -> dict[str, Any]:
    """Validate the documented UAV JSON and apply an explicit identity mapping.

    Missing roll/pitch/current-task are intentionally not fabricated.  The
    returned ``official_heartbeat`` is therefore null until a verified source
    supplies all fields required by the official heartbeat cache.
    """
    if isinstance(raw, (str, bytes)):
        try:
            value = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid UAV status JSON: {exc}") from exc
    else:
        value = dict(raw)
    if not isinstance(value, Mapping):
        raise ValueError("UAV status must be a JSON object")
    if not source_vehicle_id:
        raise ValueError("UAV source_vehicle_id mapping must be configured")
    if not vehicle_id:
        raise ValueError("UAV official vehicle_id mapping must be configured")
    if uav_registration is not None and not isinstance(uav_registration, str):
        raise ValueError("configured UAV registration must be a string")
    message_vehicle_id = value.get("vehicle_id")
    # The fixed ROS2 topic is the configured identity source when the Orin
    # payload omits vehicle_id.  The producer may report either its raw
    # source ID or the configured official ID; both resolve to the one
    # official report identity.  Never remap any third identifier.
    if message_vehicle_id is not None and message_vehicle_id not in {source_vehicle_id, vehicle_id}:
        raise ValueError("UAV status vehicle_id does not match configured source mapping")
    vehicle_type = _VEHICLE_TYPES.get(value.get("vehicle_type"))
    if vehicle_type is None:
        raise ValueError("UAV status vehicle_type must be uav or TYPE_UAV")
    state = _STATES.get(value.get("state"))
    phase = _FLIGHT_PHASES.get(value.get("flight_phase"))
    if state is None:
        raise ValueError("UAV state must be AUTO, MANUAL, or KILLED")
    if phase is None:
        raise ValueError("UAV flight_phase must be GROUNDED or AIRBORNE")
    position = value.get("position")
    if not isinstance(position, Mapping):
        raise ValueError("UAV position must be an object")
    latitude = _number(position.get("latitude"), "position.latitude", -90, 90)
    longitude = _number(position.get("longitude"), "position.longitude", -180, 180)
    altitude = _number(value.get("altitude_hae_m"), "altitude_hae_m", -2000, 100000)
    speed = _number(value.get("spd_mps"), "spd_mps", 0, 200)
    heading = _number(value.get("heading_deg"), "heading_deg", 0, 359.999999)
    battery = value.get("battery_status")
    if battery is not None and not isinstance(battery, Mapping):
        raise ValueError("battery_status must be an object when present")
    now = int(time.time() * 1000) if received_unix_ms is None else received_unix_ms
    source_registration = value.get("uav_registration")
    if source_registration is not None and not isinstance(source_registration, str):
        raise ValueError("uav_registration must be a string when present")
    if uav_registration and source_registration and uav_registration != source_registration:
        raise ValueError("UAV registration does not match configured aircraft")
    normalized = {
        "vehicle_id": vehicle_id, "source_vehicle_id": source_vehicle_id,
        "source": "ros2:/tongji_mrl/tsky/uav_status", "vehicle_type": vehicle_type,
        "state": state, "flight_phase": phase,
        "position": {"latitude_deg": latitude, "longitude_deg": longitude, "altitude_hae_m": altitude},
        "speed_mps": speed, "heading_deg": heading, "battery_status": dict(battery or {}),
        "received_unix_ms": now, "uav_registration": uav_registration or source_registration,
        "trusted_status_source": trusted_status_source,
        "use_ocs_receipt_for_freshness": use_ocs_receipt_for_freshness,
        "raw": dict(value), "official_heartbeat": None,
    }
    # Do not infer roll/pitch/current_task: official reporting remains blocked
    # until a confirmed producer adds them to the JSON contract.
    return normalized


def _freshness_timestamp(normalized: Mapping[str, Any], now_unix_ms: int) -> tuple[int, str] | str:
    """Return a fresh timestamp and its provenance, or a refusal reason."""
    raw = normalized.get("raw")
    if not isinstance(raw, Mapping):
        return "normalized status does not retain a raw JSON object"
    timestamp = raw.get("timestamp_unix_ms")
    if isinstance(timestamp, int) and not isinstance(timestamp, bool):
        if abs(now_unix_ms - timestamp) <= _OFFICIAL_HEARTBEAT_MAX_AGE_MS:
            return timestamp, "orin"
    if normalized.get("use_ocs_receipt_for_freshness") is True:
        received = normalized.get("received_unix_ms")
        if isinstance(received, int) and not isinstance(received, bool):
            if abs(now_unix_ms - received) <= _OFFICIAL_HEARTBEAT_MAX_AGE_MS:
                return received, "ocs_receipt"
        return "OCS receipt timestamp is stale or invalid"
    if not isinstance(timestamp, int) or isinstance(timestamp, bool):
        return "missing authoritative timestamp_unix_ms"
    return "UAV telemetry timestamp is stale or too far in the future"


def heartbeat_block_reason(normalized: Mapping[str, Any], *, run_id: int | None,
                           now_unix_ms: int | None = None) -> str | None:
    """Explain why a status cannot become an official heartbeat, without changing it."""
    raw = normalized.get("raw")
    if not isinstance(raw, Mapping):
        return "normalized status does not retain a raw JSON object"
    now = int(time.time() * 1000) if now_unix_ms is None else now_unix_ms
    freshness = _freshness_timestamp(normalized, now)
    if isinstance(freshness, str):
        return freshness
    missing = [name for name in ("roll_deg", "pitch_deg")
               if name not in raw]
    if missing:
        return "missing authoritative UAV fields: " + ", ".join(missing)
    source_mode = raw.get("source_mode")
    trusted_topic = normalized.get("trusted_status_source") is True
    if source_mode is None:
        if not trusted_topic:
            return "UAV source_mode is absent and the ROS2 source is not explicitly trusted"
    elif source_mode != "real":
        return "UAV source_mode must explicitly be real"
    health = raw.get("health")
    if health is None:
        if not trusted_topic:
            return "missing authoritative FCU-connected health"
    elif not isinstance(health, Mapping) or health.get("fcu_connected") is not True:
        return "missing authoritative FCU-connected health"
    if isinstance(health, Mapping) and health.get("simulator"):
        return "simulated UAV telemetry cannot become a real heartbeat"
    for name, low, high in (("roll_deg", -180.0, 180.0), ("pitch_deg", -90.0, 90.0)):
        try:
            _number(raw.get(name), name, low, high)
        except ValueError as exc:
            return str(exc)
    # The team's authoritative Orin task-state contract uses an explicit JSON
    # null to mean that no competition task has started.  This is not inferred
    # from flight phase or any other telemetry value.
    if "current_task" not in raw:
        return "missing authoritative current_task"
    if raw.get("current_task") is not None and _TASKS.get(raw.get("current_task")) is None:
        return "current_task must be an explicit non-UNKNOWN UAV task"
    registration = normalized.get("uav_registration")
    if not isinstance(registration, str) or not registration.strip():
        return "missing authoritative UAV registration"
    return None


def heartbeat_envelope(normalized: Mapping[str, Any], *, run_id: int | None,
                       now_unix_ms: int | None = None) -> dict[str, Any] | None:
    """Return a fresh, complete real-UAV envelope, or ``None`` without inventing data."""
    reason = heartbeat_block_reason(normalized, run_id=run_id, now_unix_ms=now_unix_ms)
    if reason is not None:
        return None
    raw = normalized["raw"]
    freshness = _freshness_timestamp(normalized, int(time.time() * 1000) if now_unix_ms is None else now_unix_ms)
    if isinstance(freshness, str):  # guarded above; retain fail-closed behavior
        return None
    timestamp, timestamp_basis = freshness
    envelope = {
        "kind": "heartbeat", "vehicle_id": normalized["vehicle_id"],
        "source": normalized["vehicle_id"],
        "message_id": f"ros2-uav:{normalized['source_vehicle_id']}:{timestamp}",
        "sent_at_unix_ms": timestamp,
        "timestamp_basis": timestamp_basis,
        "payload": {
            "source_mode": "real" if raw.get("source_mode") == "real" else "trusted_ros2",
            "vehicle_type": "uav", "state": normalized["state"],
            "position": {"frame_id": "wgs84", **normalized["position"]},
            "speed_mps": normalized["speed_mps"], "heading_deg": normalized["heading_deg"],
            "roll_deg": float(raw["roll_deg"]), "pitch_deg": float(raw["pitch_deg"]),
            "current_task": "none" if raw["current_task"] is None else _TASKS[raw["current_task"]],
            "health": dict(raw.get("health") or {}), "flight_phase": normalized["flight_phase"],
            "uav_registration": normalized["uav_registration"],
        },
    }
    # RobotX 2026 Heartbeat/RxReport has no run_id field.  Retain the real
    # RunStart identifier only as internal cache correlation once it exists.
    if run_id is not None:
        envelope["run_id"] = run_id
    return envelope
