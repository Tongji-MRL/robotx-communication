"""ROS-independent translation layer, tested on Windows without rclpy."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from usv_main_fsm.checkpoint_store import CheckpointStore
from usv_main_fsm.coordinator import MissionCoordinator
from usv_main_fsm.models import Ack, Action, CompletionEvent, Target, TaskId
from usv_main_fsm.safety_models import SafetyEvent, SafetyFaultType, SafetyLevel
from usv_main_fsm.safety_monitor import SafetyMonitor
from usv_main_fsm.audit_log import AuditLogger

from .protocol import ProtocolError, decode, envelope


Publish = Callable[[str, dict[str, Any]], None]


class MissionBridge:
    """Converts test JSON envelopes to domain inputs and domain actions to JSON.

    This dry-run bridge intentionally selects USV-only task participants.  The
    existing UAV fake/MQTT candidate remains outside this ROS test transport.
    """

    def __init__(self, checkpoint_path: str | Path, publish: Publish, audit_logger: AuditLogger | None = None) -> None:
        targets = {task: (Target.USV,) for task in TaskId}
        self.coordinator = MissionCoordinator(CheckpointStore(checkpoint_path), task_targets=targets, audit_logger=audit_logger)
        self.coordinator.arm_for_run_start()
        self.publish = publish
        self.seen_commands: set[str] = set()
        self.safety_monitor = SafetyMonitor()
        self.safety_level = SafetyLevel.NORMAL
        self.safety_reason = "no active safety events"

    def handle_command(self, raw: str) -> None:
        try:
            data = decode(raw, required={"schema_version", "timestamp", "run_id", "command_id", "command"})
            if not isinstance(data["command_id"], str) or not data["command_id"]:
                raise ProtocolError("command_id must be a non-empty string")
            if not isinstance(data["command"], str):
                raise ProtocolError("command must be a string")
        except ProtocolError as exc:
            self._publish_fault(0, "INVALID_COMMAND", str(exc))
            return
        if data["command_id"] in self.seen_commands:
            self._publish_state("DUPLICATE_COMMAND")
            return
        self.seen_commands.add(data["command_id"])
        command, run_id = data["command"], data["run_id"]
        parameters = data.get("parameters") or {}
        if not isinstance(parameters, dict):
            self._publish_fault(run_id, "INVALID_COMMAND", "parameters must be an object")
            return
        if command == "RUN_START":
            actions = self.coordinator.start_run(run_id)
        elif command == "TASK4_PREEMPT":
            actions = self.coordinator.request_task4(run_id, affected_targets=(Target.USV,))
        elif command == "TASK4_RELEASE":
            actions = self.coordinator.release_task4(
                run_id, recovery_permitted=parameters.get("recovery_permitted") is True,
                vehicles_safe=parameters.get("vehicles_safe") is True,
            )
        elif command == "SAFE_STOP":
            actions = self.coordinator.safe_stop(run_id, reason=str(parameters.get("reason", "test command")))
        else:
            self._publish_fault(run_id, "ILLEGAL_COMMAND", f"unsupported command {command}")
            return
        self._dispatch(actions)
        self._publish_state()

    def handle_ack(self, raw: str) -> None:
        try:
            data = decode(raw, required={"schema_version", "timestamp", "run_id", "command_id", "target", "accepted"})
            if data["target"] != Target.USV.value or not isinstance(data["accepted"], bool):
                raise ProtocolError("ACK target must be T-Wave and accepted must be boolean")
            ack = Ack(data["command_id"], data["run_id"], Target.USV, data["accepted"],
                      safe_paused=data.get("safe_paused", False), progress_marker=data.get("progress_marker"),
                      detail=str(data.get("detail", "")))
        except (ProtocolError, KeyError, TypeError) as exc:
            self._publish_fault(0, "INVALID_ACK", str(exc))
            return
        self._dispatch(self.coordinator.receive_ack(ack))
        self._publish_state()

    def handle_event(self, raw: str) -> None:
        try:
            data = decode(raw, required={"schema_version", "timestamp", "run_id", "event_id", "task", "target", "authoritative", "succeeded"})
            if not isinstance(data["event_id"], str) or not data["event_id"]:
                raise ProtocolError("event_id must be a non-empty string")
            if not isinstance(data["authoritative"], bool) or not isinstance(data["succeeded"], bool):
                raise ProtocolError("authoritative and succeeded must be booleans")
            event = CompletionEvent(data["event_id"], data["run_id"], TaskId(data["task"]), Target(data["target"]),
                                    data["authoritative"], data["succeeded"], str(data.get("detail", "")))
        except (ProtocolError, KeyError, TypeError, ValueError) as exc:
            self._publish_fault(0, "INVALID_EVENT", str(exc))
            return
        self._dispatch(self.coordinator.complete_task(event))
        self._publish_state()

    def handle_fault(self, raw: str) -> None:
        try:
            data = decode(raw, required={"schema_version", "timestamp", "run_id", "target", "code"})
            # ``fault`` is bidirectional for this small test surface.  Do not
            # feed the bridge's diagnostic publication back into itself.
            if data.get("source") == "mission_bridge":
                return
            target = Target(data["target"])
        except (ProtocolError, KeyError, TypeError, ValueError) as exc:
            self._publish_fault(0, "INVALID_FAULT", str(exc))
            return
        if data["run_id"] == self.coordinator.run_id:
            self._dispatch(self.coordinator.report_link_lost(target, detail=f"{data['code']}: {data.get('detail', '')}"))
        self._publish_state()

    def handle_safety_input(self, raw: str) -> None:
        """Dry-run-only local health injection; this is not a production reset API."""
        try:
            data = decode(raw, required={"schema_version", "timestamp", "run_id", "event_id"})
            if data.get("kind") == "RESET_SAFE_STOP":
                if data.get("test_only") is not True:
                    raise ProtocolError("reset is available only with test_only=true")
                self.coordinator.reset_safe_stop(
                    authorization_id=str(data.get("authorization_id", "")),
                    severe_faults_clear=(data.get("severe_faults_clear") is True and
                                        self.safety_monitor.evaluate().level == SafetyLevel.NORMAL),
                    executors_safe=data.get("executors_safe") is True,
                    failsafe_cleared=data.get("failsafe_cleared") is True,
                    reinitialize_ready=data.get("reinitialize_ready") is True,
                    authorization_run_id=data.get("authorization_run_id"),
                )
                self._publish_state(); return
            event = SafetyEvent(data["event_id"], data["run_id"], SafetyFaultType(data["fault"]),
                bool(data["active"]), str(data.get("source", "test")), 0.0,
                data.get("trustworthy") is True, str(data.get("detail", "")), data.get("clears_event_id"))
        except (ProtocolError, KeyError, TypeError, ValueError) as exc:
            self._publish_fault(0, "INVALID_SAFETY_INPUT", str(exc)); return
        decision = self.safety_monitor.ingest(event, current_run_id=self.coordinator.run_id)
        if decision is None:
            return
        self.safety_level, self.safety_reason = decision.level, decision.reason
        if decision.level == SafetyLevel.CRITICAL:
            self._dispatch(self.coordinator.safe_stop(event.run_id, reason=decision.reason, source="SafetyMonitor"))
        elif decision.level == SafetyLevel.HOLD:
            self._dispatch(self.coordinator.request_safe_hold(event.run_id, reason=decision.reason, source="SafetyMonitor"))
        self._publish_state()

    def tick(self) -> None:
        self._dispatch(self.coordinator.check_timeouts())
        self._publish_state()

    def _dispatch(self, actions: list[Action]) -> None:
        for action in actions:
            self.coordinator._audit("ACTION", command_id=action.command_id, task_id=action.task.value if action.task else None,
                                    action=action.action_type.value)
            if action.target != Target.USV:
                continue
            self.publish("usv_command", envelope(run_id=action.run_id, command_id=action.command_id,
                target=action.target.value, action=action.action_type.value,
                task=action.task.value if action.task else None, parameters=action.parameters,
                dry_run=True))

    def _publish_state(self, note: str = "") -> None:
        run_id = self.coordinator.run_id or 0
        self.publish("state", envelope(run_id=run_id, state=self.coordinator.state.value,
            task=self.coordinator.current_task.value if self.coordinator.current_task else None,
            pending_command_ids=sorted(self.coordinator.pending_command_ids), dry_run=True, note=note,
            safety_level=self.safety_level.name, safety_reason=self.safety_reason,
            safe_hold_reason=self.coordinator.safe_hold_reason,
            safe_stop_reason=self.coordinator.safety_stop_record.reason if self.coordinator.safety_stop_record else ""))

    def _publish_fault(self, run_id: int, code: str, detail: str) -> None:
        self.publish("fault", envelope(run_id=run_id, source="mission_bridge", code=code, detail=detail, dry_run=True))
