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


def _number(value: Any, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    value = float(value)
    if not low <= value <= high:
        raise ValueError(f"{label} out of range")
    return value


def normalize_uav_status(raw: str | bytes | Mapping[str, Any], *, source_vehicle_id: str,
                         vehicle_id: str = "T-Sky", received_unix_ms: int | None = None) -> dict[str, Any]:
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
    if value.get("vehicle_id") != source_vehicle_id:
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
    normalized = {
        "vehicle_id": vehicle_id, "source_vehicle_id": source_vehicle_id,
        "source": "ros2:/tongji_mrl/tsky/uav_status", "vehicle_type": vehicle_type,
        "state": state, "flight_phase": phase,
        "position": {"latitude_deg": latitude, "longitude_deg": longitude, "altitude_hae_m": altitude},
        "speed_mps": speed, "heading_deg": heading, "battery_status": dict(battery or {}),
        "received_unix_ms": now, "raw": dict(value), "official_heartbeat": None,
    }
    # Do not infer roll/pitch/current_task: official reporting remains blocked
    # until a confirmed producer adds them to the JSON contract.
    return normalized


def heartbeat_envelope(normalized: Mapping[str, Any], *, run_id: int | None) -> dict[str, Any] | None:
    """Return a cache-compatible real heartbeat only when no field is invented."""
    return None
