"""Pure policy for classifying MissionCoordinator output reports.

This module deliberately has no ROS, MQTT, or state-machine dependency.  A
future publisher may consume :class:`ReportDecision`, but this policy does not
publish or alter any mission state.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportDecision:
    """Which existing OCS report category is appropriate for an observation."""

    include_in_status: bool
    emit_fault: bool
    emit_task_report: bool


def decide_report(
    *,
    error: str = "NONE",
    state: str = "",
    command: str = "NONE",
    task_result: str = "",
) -> ReportDecision:
    """Classify one observation without creating a report.

    Ordinary errors remain visible in periodic status and do not independently
    generate a fault.  A latched SAFE_STOP or an explicit abort is not
    autonomously recoverable and therefore requires a fault.  Only an explicit
    task-complete outcome produces a task report at this stage.
    """
    has_error = error != "NONE"
    severe_error = error in {
        "COMMUNICATION_LOST",
        "EXECUTION_REJECTED",
        "DEPENDENCY_UNAVAILABLE",
        "UNKNOWN_ERROR",
    }
    return ReportDecision(
        include_in_status=has_error,
        emit_fault=(state == "SAFE_STOP" or command in {
            "REQUEST_ABORT", "REQUEST_SAFE_HOLD", "REPORT_TASK_FAILED",
        } or severe_error),
        emit_task_report=task_result == "TASK_COMPLETE",
    )


def should_report_error(error: str) -> bool:
    """Return whether an error must be represented in periodic status."""
    return decide_report(error=error).include_in_status
