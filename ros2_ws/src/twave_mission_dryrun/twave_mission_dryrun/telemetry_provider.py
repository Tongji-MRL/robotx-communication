"""Interfaces for future vehicle telemetry sources.

No hardware or ROS transport is connected here.  These protocols only keep a
stable dependency-injection seam for future report enrichment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


VehicleData = Mapping[str, Any]


class VehicleStatusProvider(Protocol):
    """Return the latest stored mission status for one vehicle, if available."""

    def get(self, vehicle: str) -> VehicleData | None: ...


class VehicleTelemetryProvider(Protocol):
    """Return the latest telemetry snapshot for one vehicle, if available."""

    def get(self, vehicle: str) -> VehicleData | None: ...


class NullVehicleTelemetryProvider:
    """Default telemetry source until a real telemetry store is introduced."""

    def get(self, vehicle: str) -> VehicleData | None:
        return None
