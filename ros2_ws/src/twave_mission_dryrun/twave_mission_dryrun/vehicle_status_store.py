"""In-memory snapshots of the latest frozen vehicle progress messages."""

from __future__ import annotations

import time
from collections.abc import Callable


class VehicleStatusStore:
    """Store the latest 14-bit progress value for each vehicle.

    This is intentionally only a transport-side cache.  It does not decode a
    status, infer task state, or feed any state-machine decision.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.time
        self._statuses: dict[str, dict[str, str | float]] = {}

    def update(self, vehicle: str, status_bits: str) -> None:
        if not isinstance(vehicle, str) or not vehicle:
            raise ValueError("vehicle must be a non-empty string")
        if (not isinstance(status_bits, str) or len(status_bits) != 14 or
                set(status_bits) - {"0", "1"}):
            raise ValueError("status_bits must be a 14-bit binary string")
        self._statuses[vehicle] = {
            "status_bits": status_bits,
            "timestamp": self._clock(),
        }

    def get(self, vehicle: str) -> dict[str, str | float] | None:
        status = self._statuses.get(vehicle)
        return dict(status) if status is not None else None

    def get_all(self) -> dict[str, dict[str, str | float]]:
        return {vehicle: dict(status) for vehicle, status in self._statuses.items()}
