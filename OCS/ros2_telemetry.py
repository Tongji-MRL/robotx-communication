"""Read-only, configurable ROS 2 telemetry normalization.

The class is intentionally ROS-message agnostic. ROS subscribers (when the
real interface is confirmed) feed its ``update_*`` methods. It publishes no
ROS topic and contains no PX4/actuator command path.
"""
from __future__ import annotations

import math
import time
from typing import Any


DEFAULT_SOURCES = {
    "T-Wave": {"gps": "/fix", "mission": "/tongji_mrl/twave/heartbeat", "status": "/tongji_mrl/twave/state"},
    "T-Sky": {"status": "/fmu/out/vehicle_status_v1", "position": "/fmu/out/vehicle_local_position_v1", "attitude": "/fmu/out/vehicle_attitude"},
}


class Ros2TelemetryAdapter:
    """Collect confirmed read-only values and emit only complete heartbeats."""
    def __init__(self, vehicle_id: str, *, sources: dict[str, str] | None = None, now_ms=None) -> None:
        if vehicle_id not in DEFAULT_SOURCES:
            raise ValueError("unsupported vehicle")
        self.vehicle_id = vehicle_id
        self.sources = dict(sources or DEFAULT_SOURCES[vehicle_id])
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._values: dict[str, Any] = {}
        self._timestamp_ms: int | None = None

    def update(self, **values: Any) -> None:
        """Accept a normalized, externally verified input snapshot.

        In particular, local PX4 NED coordinates are not accepted as WGS84;
        callers must supply a verified WGS84/HAE conversion source.
        """
        self._values.update(values)
        timestamp = values.get("timestamp_unix_ms")
        if isinstance(timestamp, int) and not isinstance(timestamp, bool):
            self._timestamp_ms = timestamp

    def heartbeat_payload(self) -> dict[str, Any] | None:
        v = self._values
        required = {"state", "latitude_deg", "longitude_deg", "altitude_hae_m", "speed_mps", "heading_deg", "roll_deg", "pitch_deg", "fcu_connected"}
        if self.vehicle_id == "T-Sky":
            required.add("flight_phase")
        if not required.issubset(v) or self._timestamp_ms is None:
            return None
        if self.now_ms() - self._timestamp_ms > 3000 or v["fcu_connected"] is not True:
            return None
        numeric = ("latitude_deg", "longitude_deg", "altitude_hae_m", "speed_mps", "heading_deg", "roll_deg", "pitch_deg")
        if any(not isinstance(v[key], (int, float)) or isinstance(v[key], bool) or not math.isfinite(v[key]) for key in numeric):
            return None
        result = {
            "source_mode": "real", "state": v["state"],
            "vehicle_type": "uav" if self.vehicle_id == "T-Sky" else "usv",
            "position": {"frame_id": "wgs84", "latitude_deg": v["latitude_deg"], "longitude_deg": v["longitude_deg"], "altitude_hae_m": v["altitude_hae_m"]},
            "speed_mps": v["speed_mps"], "heading_deg": v["heading_deg"],
            "roll_deg": v["roll_deg"], "pitch_deg": v["pitch_deg"],
            "health": {"fcu_connected": True},
        }
        if self.vehicle_id == "T-Sky":
            result["flight_phase"] = v["flight_phase"]
            # Optional registration is sourced only from a verified UAV
            # telemetry/config adapter; it is never invented by the OCS.
            if isinstance(v.get("uav_registration"), str):
                result["uav_registration"] = v["uav_registration"]
        return result
