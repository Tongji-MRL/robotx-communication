"""Candidate T-Wave ROS 2 task-command adapter contract.

There is intentionally no ``rclpy`` import here.  Names and payloads are
candidate mappings for the future ROS 2 owner to freeze, not existing topics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Ack, Action, CompletionEvent, Target


@dataclass(frozen=True)
class CandidateRos2Command:
    command_id: str
    run_id: int
    action: str
    task: str | None
    parameters: dict[str, Any]
    candidate_interface: str = "twave-task-command-v0"


class FakeROS2Adapter:
    """In-memory stand-in for a future T-Wave ROS 2 task adapter."""

    def __init__(self) -> None:
        self.commands: list[CandidateRos2Command] = []

    def send(self, action: Action) -> CandidateRos2Command:
        if action.target != Target.USV:
            raise ValueError("FakeROS2Adapter only accepts T-Wave actions")
        command = CandidateRos2Command(
            command_id=action.command_id,
            run_id=action.run_id,
            action=action.action_type.value,
            task=action.task.value if action.task else None,
            parameters=dict(action.parameters),
        )
        self.commands.append(command)
        return command

    @staticmethod
    def ack(command: CandidateRos2Command, *, accepted: bool, safe_paused: bool = False,
            progress_marker: str | None = None, detail: str = "") -> Ack:
        return Ack(
            command.command_id, command.run_id, Target.USV, accepted,
            safe_paused=safe_paused, progress_marker=progress_marker, detail=detail,
        )

    @staticmethod
    def completion(*, event_id: str, run_id: int, task, authoritative: bool = True,
                   succeeded: bool = True, detail: str = "") -> CompletionEvent:
        return CompletionEvent(event_id, run_id, task, Target.USV, authoritative, succeeded, detail)
