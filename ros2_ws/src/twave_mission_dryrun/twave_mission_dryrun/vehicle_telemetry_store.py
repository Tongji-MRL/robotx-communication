"""In-memory snapshots of telemetry intended for future RoboCommand heartbeat use."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any


class VehicleTelemetryStore:
    """Store the latest telemetry snapshot per vehicle without hardware I/O."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.time
        self._telemetry: dict[str, dict[str, Any]] = {}

    def update(
        self,
        vehicle: str,
        *,
        position: Mapping[str, float],
        speed: float,
        heading: float,
        roll: float,
        pitch: float,
        altitude: float,
        timestamp: float | None = None,
    ) -> None:
        if not isinstance(vehicle, str) or not vehicle:
            raise ValueError("vehicle must be a non-empty string")
        if not isinstance(position, Mapping) or {"latitude", "longitude"} - set(position):
            raise ValueError("position must contain latitude and longitude")
        self._telemetry[vehicle] = {
            "position": {"latitude": float(position["latitude"]), "longitude": float(position["longitude"])},
            "speed": float(speed),
            "heading": float(heading),
            "roll": float(roll),
            "pitch": float(pitch),
            "altitude": float(altitude),
            "timestamp": self._clock() if timestamp is None else float(timestamp),
        }

    def get(self, vehicle: str) -> dict[str, Any] | None:
        telemetry = self._telemetry.get(vehicle)
        if telemetry is None:
            return None
        return {**telemetry, "position": dict(telemetry["position"])}

    def get_all(self) -> dict[str, dict[str, Any]]:
        return {vehicle: self.get(vehicle) for vehicle in self._telemetry}
