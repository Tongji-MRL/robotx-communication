"""Reference USV-side task arbitration for preemptive Task 4 handling.

This module has no MQTT, ROS 2, PX4, or actuator dependency.  It converts
official Task 4 commands into internal high-priority actions and preserves a
Task 1/3 checkpoint for later resumption.  This module is not imported by
``ocs_client.py``; it models the logic that belongs inside the USV mission
coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


TASK4_BODY_TO_COMMAND = {
    "assistance_request": "TASK4_ASSISTANCE",
    "keep_out_zone": "TASK4_KEEP_OUT_ZONE",
    "all_clear": "TASK4_ALL_CLEAR",
    "moving_object_alert": "TASK4_MOVING_OBJECT",
    "readiness_confirm": "TASK4_READINESS_CONFIRM",
}


@dataclass
class VehicleTaskContext:
    vehicle_id: str
    vehicle_type: str
    current_task: str = "TASK_NONE"
    task_phase: str = "IDLE"
    checkpoint: dict[str, Any] = field(default_factory=dict)
    task4_active: bool = False
    task4_body: str | None = None
    task4_command_seq: int | None = None
    preempted_task: str | None = None
    resume_token: str | None = None
    resume_pending: bool = False


class TaskPriorityManager:
    """Arbitrate vehicle tasks without performing vehicle I/O."""

    def __init__(self, team_id: str = "TONG") -> None:
        self.team_id = team_id
        self.run_id: int | None = None
        self.vehicles: dict[str, VehicleTaskContext] = {}
        self._seen_command_seqs: set[int] = set()

    def register_vehicle(self, vehicle_id: str, vehicle_type: str) -> None:
        if not vehicle_id or not vehicle_type:
            raise ValueError("vehicle_id and vehicle_type are required")
        self.vehicles[vehicle_id] = VehicleTaskContext(vehicle_id, vehicle_type.lower())

    def start_run(self, run_id: int) -> None:
        if run_id <= 0:
            raise ValueError("run_id must be positive")
        self.run_id = run_id
        self._seen_command_seqs.clear()
        for context in self.vehicles.values():
            context.current_task = "TASK_NONE"
            context.task_phase = "IDLE"
            context.checkpoint = {}
            context.task4_active = False
            context.task4_body = None
            context.task4_command_seq = None
            context.preempted_task = None
            context.resume_token = None
            context.resume_pending = False

    def update_vehicle_status(
        self,
        vehicle_id: str,
        *,
        current_task: str,
        task_phase: str,
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        context = self._context(vehicle_id)
        if context.task4_active and current_task not in ("TASK4", "TASK_NONE"):
            raise ValueError("a vehicle cannot advance its normal task while Task 4 is active")
        context.current_task = current_task
        context.task_phase = task_phase
        if checkpoint is not None and not context.task4_active:
            context.checkpoint = dict(checkpoint)

    def handle_official_command(self, command) -> list[dict[str, Any]]:
        """Return internal commands for one already-decoded RxCommand."""
        if command.team_id != self.team_id:
            raise ValueError("command team_id does not match the manager")
        if self.run_id is None:
            raise ValueError("Task 4 command received before a run is active")
        if command.seq <= 0 or command.seq in self._seen_command_seqs:
            raise ValueError("duplicate or invalid official command sequence")
        body_name = command.WhichOneof("body")
        if body_name not in TASK4_BODY_TO_COMMAND:
            raise ValueError("command is not a supported Task 4 command")
        self._seen_command_seqs.add(command.seq)

        targets = self._targets(command, body_name)
        actions: list[dict[str, Any]] = []
        for vehicle_id in targets:
            context = self._context(vehicle_id)
            preempt = body_name in {
                "assistance_request", "keep_out_zone", "moving_object_alert"
            }
            if preempt and not context.task4_active:
                context.preempted_task = context.current_task
                context.resume_token = f"{self.run_id}:{vehicle_id}:{command.seq}"
                context.task4_active = True
                context.task4_body = body_name
                context.task4_command_seq = command.seq
                context.task_phase = "TASK4_PREEMPTING"
                context.current_task = "TASK4"
            elif context.task4_active:
                context.task4_body = body_name
                context.task4_command_seq = command.seq

            parameters = self._parameters(command, body_name)
            if preempt:
                parameters.update({
                    "preempted_task": context.preempted_task,
                    "checkpoint": dict(context.checkpoint),
                    "resume_token": context.resume_token,
                })
            actions.append({
                "kind": "internal_command",
                "vehicle_id": vehicle_id,
                "run_id": self.run_id,
                "command": TASK4_BODY_TO_COMMAND[body_name],
                "command_seq": command.seq,
                "priority": "CRITICAL",
                "preempt": preempt,
                "parameters": parameters,
            })
        return actions

    def handle_vehicle_ack(
        self,
        vehicle_id: str,
        *,
        command_seq: int,
        accepted: bool,
        detail: str = "",
    ) -> list[dict[str, Any]]:
        context = self._context(vehicle_id)
        if context.resume_pending and context.task4_command_seq == command_seq:
            if not accepted:
                raise ValueError(f"{vehicle_id} rejected TASK4_RESUME: {detail}")
            context.resume_pending = False
            context.task4_active = False
            context.task_phase = "RESUMED"
            context.current_task = context.preempted_task or "TASK_NONE"
            return []
        if not context.task4_active or context.task4_command_seq != command_seq:
            raise ValueError("ACK does not match the active Task 4 command")
        if not accepted:
            context.task_phase = "TASK4_FAULT"
            return [{
                "kind": "fault",
                "vehicle_id": vehicle_id,
                "run_id": self.run_id,
                "fault_code": "TASK4_COMMAND_REJECTED",
                "detail": detail,
            }]

        context.task_phase = "TASK4_ACTIVE"
        actions: list[dict[str, Any]] = []
        if context.task4_body in {"assistance_request", "keep_out_zone", "all_clear"}:
            actions.append({
                "kind": "official_report",
                "vehicle_id": vehicle_id,
                "report": "incident_ack",
                "command_seq": command_seq,
            })
        if context.task4_body in {"all_clear", "readiness_confirm"}:
            actions.extend(self.release_task4(vehicle_id, reason="official_clear"))
        return actions

    def handle_readiness_report(self, vehicle_id: str, *, command_seq: int) -> list[dict[str, Any]]:
        context = self._context(vehicle_id)
        if not context.task4_active or context.task4_command_seq != command_seq:
            raise ValueError("ReadinessReport does not match the active Task 4 command")
        if context.task4_body != "assistance_request":
            raise ValueError("ReadinessReport is only valid for AssistanceRequest")
        context.task_phase = "TASK4_WAIT_CONFIRM"
        return [{
            "kind": "official_report",
            "vehicle_id": vehicle_id,
            "report": "readiness",
            "command_seq": command_seq,
        }]

    def release_task4(self, vehicle_id: str, *, reason: str) -> list[dict[str, Any]]:
        context = self._context(vehicle_id)
        if not context.task4_active:
            return []
        context.task_phase = "TASK4_RESUMING"
        context.resume_pending = True
        return [{
            "kind": "internal_command",
            "vehicle_id": vehicle_id,
            "run_id": self.run_id,
            "command": "TASK4_RESUME",
            "command_seq": context.task4_command_seq,
            "priority": "CRITICAL",
            "preempt": False,
            "parameters": {
                "reason": reason,
                "resume_token": context.resume_token,
                "resume_task": context.preempted_task,
                "checkpoint": context.checkpoint,
            },
        }]

    def _context(self, vehicle_id: str) -> VehicleTaskContext:
        try:
            return self.vehicles[vehicle_id]
        except KeyError as exc:
            raise ValueError(f"unknown vehicle_id: {vehicle_id}") from exc

    def _targets(self, command, body_name: str) -> list[str]:
        if body_name == "readiness_confirm":
            return [command.readiness_confirm.vehicle_id]
        if command.vehicle_id:
            return [command.vehicle_id]
        if body_name == "assistance_request":
            vehicle_type = command.assistance_request.vehicle_type
        elif body_name == "keep_out_zone":
            vehicle_type = command.keep_out_zone.vehicle_type
        elif body_name == "all_clear":
            vehicle_type = command.all_clear.vehicle_type
        else:
            vehicle_types = set(command.moving_object_alert.affected_vehicle_types)
            return [
                vehicle_id for vehicle_id, context in self.vehicles.items()
                if self._vehicle_type_value(context.vehicle_type) in vehicle_types
            ]
        return [
            vehicle_id for vehicle_id, context in self.vehicles.items()
            if self._vehicle_type_value(context.vehicle_type) == vehicle_type
        ]

    @staticmethod
    def _vehicle_type_value(vehicle_type: str) -> int:
        return {"usv": 1, "uuv": 2, "uav": 3}.get(vehicle_type, 0)

    @staticmethod
    def _parameters(command, body_name: str) -> dict[str, Any]:
        body = getattr(command, body_name)
        if body_name == "assistance_request":
            return {
                "vehicle_type": int(body.vehicle_type),
                "position": {"latitude": body.position.latitude, "longitude": body.position.longitude},
            }
        if body_name == "keep_out_zone":
            return {
                "vehicle_type": int(body.vehicle_type),
                "radius_m": body.radius_m,
                "center": {"latitude": body.center.latitude, "longitude": body.center.longitude},
            }
        if body_name == "all_clear":
            return {"vehicle_type": int(body.vehicle_type)}
        if body_name == "moving_object_alert":
            return {
                "heading_deg": body.heading_deg,
                "speed_mps": body.speed_mps,
                "position": {"latitude": body.position.latitude, "longitude": body.position.longitude},
                "affected_vehicle_types": [int(value) for value in body.affected_vehicle_types],
            }
        return {
            "report_seq": body.report_seq,
            "vehicle_id": body.vehicle_id,
        }
