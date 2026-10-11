"""Build internal RoboCommand ``Heartbeat`` payloads from cached vehicle data."""

from __future__ import annotations

from typing import Any

from mission_protocol import decode_status

from .vehicle_status_store import VehicleStatusStore
from .vehicle_telemetry_store import VehicleTelemetryStore


_RX_TASK_BY_MISSION_TASK = {
    "NOT_STARTED": "TASK_NONE",
    "TASK1": "TASK_SAFE_PASSAGE",
    "TASK3": "TASK_COORDINATED_LOGISTICS",
    "TASK4": "TASK_DYNAMIC_INCIDENT",
}


class HeartbeatBuilder:
    """Create a protobuf-field-shaped payload without importing protobuf or MQTT."""

    def __init__(self, telemetry_store: VehicleTelemetryStore, status_store: VehicleStatusStore) -> None:
        self.telemetry_store = telemetry_store
        self.status_store = status_store

    def build(self, vehicle: str) -> dict[str, Any]:
        """Return fields matching ``rx_reports.proto:Heartbeat`` where data exists.

        The telemetry timestamp is intentionally not included: it belongs to
        the outer ``RxReport.sent_at`` field, not to ``Heartbeat``.
        """
        telemetry = self.telemetry_store.get(vehicle)
        if telemetry is None:
            raise ValueError(f"no telemetry available for {vehicle}")

        current_task = "TASK_NONE"
        status = self.status_store.get(vehicle)
        if status is not None:
            decoded = decode_status(str(status["status_bits"]))
            current_task = _RX_TASK_BY_MISSION_TASK[decoded["task"]]

        return {
            "position": telemetry["position"],
            "spd_mps": telemetry["speed"],
            "heading_deg": telemetry["heading"],
            "roll_deg": telemetry["roll"],
            "pitch_deg": telemetry["pitch"],
            "altitude_hae_m": telemetry["altitude"],
            "current_task": current_task,
        }
