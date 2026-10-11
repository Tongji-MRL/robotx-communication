"""Candidate OCS internal-envelope adapter; no official RoboCommand access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from OCS import vehicle_protocol

from .coordinator import MissionCoordinator
from .models import Action, Target


_TASK4_COMMANDS = {
    "task4_assistance", "task4_keep_out_zone", "task4_all_clear",
    "task4_moving_object", "task4_readiness_confirm",
}
_TASK4_PREEMPT_COMMANDS = {
    "task4_assistance", "task4_keep_out_zone", "task4_moving_object",
}


@dataclass(frozen=True)
class OcsDispatch:
    actions: list[Action]
    response: dict[str, Any]


class OcsAdapter:
    """Parses existing vehicle_protocol v1 envelopes for the T-Wave core."""

    def __init__(self, coordinator: MissionCoordinator) -> None:
        self.coordinator = coordinator
        self._seen_message_ids: set[str] = set()

    def receive(self, mqtt_topic: str, raw: bytes | str) -> OcsDispatch:
        envelope = vehicle_protocol.decode(raw)
        if mqtt_topic != vehicle_protocol.topic("T-Wave", "command"):
            raise ValueError("OCS command arrived on an invalid vehicle topic")
        if envelope["vehicle_id"] != "T-Wave" or envelope["kind"] != "command":
            raise ValueError("only T-Wave command envelopes are accepted")
        if envelope["source"] != "ocs":
            raise ValueError("command envelope source must be ocs")
        message_id = envelope["message_id"]
        if message_id in self._seen_message_ids:
            return OcsDispatch([], self._ack(envelope, True, "DUPLICATE", "already processed"))
        self._seen_message_ids.add(message_id)
        payload = envelope["payload"]
        command = payload.get("command")
        run_id = envelope["run_id"]
        if not isinstance(run_id, int) or run_id <= 0:
            return OcsDispatch([], self._ack(envelope, False, "REJECTED", "positive run_id required"))
        if command == "run_start":
            actions = self.coordinator.start_run(run_id)
        elif command in _TASK4_PREEMPT_COMMANDS:
            try:
                targets = self._targets(payload.get("parameters", {}))
            except ValueError as exc:
                return OcsDispatch([], self._ack(envelope, False, "REJECTED", str(exc)))
            actions = self.coordinator.request_task4(run_id, affected_targets=targets)
        elif command in _TASK4_COMMANDS:
            # All-clear/readiness are valid official inputs, but cannot
            # authorize motion.  A future, frozen recovery-policy adapter may
            # turn them into explicit release_task4() authorization.
            return OcsDispatch([], self._ack(
                envelope, True, "RECEIVED_PENDING_RECOVERY_POLICY",
                "parsed; no automatic preemption or resume",
            ))
        elif command == "safe_stop":
            actions = self.coordinator.safe_stop(run_id, reason=str((payload.get("parameters") or {}).get("reason", "OCS request")))
        else:
            return OcsDispatch([], self._ack(envelope, False, "REJECTED", "unsupported coordinator command"))
        accepted = bool(actions) or (command == "run_start" and self.coordinator.run_id == run_id)
        return OcsDispatch(actions, self._ack(envelope, accepted, "ACCEPTED" if accepted else "REJECTED", "queued for coordinator"))

    @staticmethod
    def _targets(parameters: dict[str, Any]) -> tuple[Target, ...] | None:
        values = parameters.get("affected_targets")
        if values is None:
            return None
        if not isinstance(values, list) or not values:
            raise ValueError("affected_targets must be a non-empty candidate target list")
        try:
            return tuple(Target(value) for value in values)
        except ValueError as exc:
            raise ValueError("affected_targets contains an unsupported vehicle") from exc

    @staticmethod
    def _ack(envelope: dict[str, Any], accepted: bool, state: str, detail: str) -> dict[str, Any]:
        payload = envelope["payload"]
        return vehicle_protocol.make_message("T-Wave", "ack", {
            "in_reply_to": envelope["message_id"], "command": payload.get("command"),
            "command_seq": payload.get("command_seq"), "accepted": accepted,
            "state": state, "detail": detail,
        }, run_id=envelope["run_id"], source="T-Wave", frame_id=envelope["frame_id"])

    @staticmethod
    def candidate_task_report(run_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return vehicle_protocol.make_message("T-Wave", "task_report", payload, run_id=run_id, source="T-Wave")

    @staticmethod
    def candidate_fault(run_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return vehicle_protocol.make_message("T-Wave", "fault", payload, run_id=run_id, source="T-Wave")
