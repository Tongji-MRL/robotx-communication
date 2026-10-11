"""Pure execution layer for frozen MissionCoordinator report payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .report_policy import ReportDecision, decide_report
from .telemetry_provider import (
    NullVehicleTelemetryProvider,
    VehicleStatusProvider,
    VehicleTelemetryProvider,
)


STATUS_TOPIC = "/tongji_mrl/mission/status"
TASK_REPORT_TOPIC = "/tongji_mrl/mission/task_report"
FAULT_TOPIC = "/tongji_mrl/mission/fault"


@dataclass(frozen=True)
class ReportMessage:
    """A publisher-ready frozen topic and its unchanged structured payload."""

    topic: str
    payload: dict[str, Any]


class ReportManager:
    """Apply report policy without publishing ROS or MQTT messages."""

    def __init__(
        self,
        *,
        vehicle_status_provider: VehicleStatusProvider | None = None,
        vehicle_telemetry_provider: VehicleTelemetryProvider | None = None,
    ) -> None:
        """Reserve source injection points without enriching reports yet.

        ``VehicleStatusStore`` already satisfies ``VehicleStatusProvider`` via
        its ``get`` method.  Telemetry remains a null source until a dedicated
        store is introduced.
        """
        self.vehicle_status_provider = vehicle_status_provider
        self.vehicle_telemetry_provider = (
            vehicle_telemetry_provider or NullVehicleTelemetryProvider()
        )

    def vehicle_data(self, vehicle: str) -> dict[str, object | None]:
        """Expose one unified, read-only lookup for future report enrichment.

        This method does not affect payload generation in the current release.
        """
        status = (
            self.vehicle_status_provider.get(vehicle)
            if self.vehicle_status_provider is not None else None
        )
        telemetry = self.vehicle_telemetry_provider.get(vehicle)
        return {"status": status, "telemetry": telemetry}

    @staticmethod
    def _decision(event: Mapping[str, Any], *, task_result: str = "") -> ReportDecision:
        return decide_report(
            error=str(event.get("error", "NONE")),
            state=str(event.get("state", "")),
            command=str(event.get("command", "NONE")),
            task_result=task_result,
        )

    @staticmethod
    def _payload(event: Mapping[str, Any]) -> dict[str, Any]:
        return dict(event)

    def status_update(self, event: Mapping[str, Any]) -> ReportMessage:
        """Create the periodic status message for a coordinator status update."""
        self._decision(event)  # Keep policy evaluation at the execution boundary.
        return ReportMessage(STATUS_TOPIC, self._payload(event))

    def task_complete(self, event: Mapping[str, Any]) -> ReportMessage | None:
        """Create a task report only for an explicit final task completion."""
        if not self._decision(event, task_result="TASK_COMPLETE").emit_task_report:
            return None
        return ReportMessage(TASK_REPORT_TOPIC, self._payload(event))

    def fault_event(self, event: Mapping[str, Any]) -> ReportMessage | None:
        """Create a fault only when policy marks the event unrecoverable."""
        if not self._decision(event).emit_fault:
            return None
        return ReportMessage(FAULT_TOPIC, self._payload(event))
