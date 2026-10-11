"""Pure routing from decoded vehicle progress to ReportManager payloads."""

from __future__ import annotations

from .progress_decoder import decode_progress
from .report_manager import ReportManager, ReportMessage


class MissionEventRouter:
    """Route progress reports without publishing ROS messages or mutating FSMs."""

    def __init__(self, report_manager: ReportManager | None = None) -> None:
        self.report_manager = report_manager or ReportManager()

    def route_progress(self, vehicle: str, status_bits: str) -> list[ReportMessage]:
        """Decode a progress report and return its frozen OCS output messages."""
        event = decode_progress(vehicle, status_bits)
        messages = [self.report_manager.status_update(event)]

        command = event["command"]
        if command == "REPORT_TASK_COMPLETE":
            task_report = self.report_manager.task_complete(event)
            if task_report is not None:
                messages.append(task_report)
        elif command in {"REPORT_TASK_FAILED", "REQUEST_SAFE_HOLD"}:
            fault = self.report_manager.fault_event(event)
            if fault is not None:
                messages.append(fault)
        elif event["error"] != "NONE":
            # The policy decides whether this error is recoverable or a fault.
            fault = self.report_manager.fault_event(event)
            if fault is not None:
                messages.append(fault)
        return messages
