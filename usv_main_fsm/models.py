"""Domain models for the T-Wave main mission state machine.

These are intentionally transport-neutral.  ``ActionType`` values are domain
interfaces, not ROS 2 topics, MQTT message names, or hardware commands.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class MainState(str, Enum):
    IDLE = "IDLE"
    WAIT_RUN_START = "WAIT_RUN_START"
    RUNNING_TASK1 = "RUNNING_TASK1"
    RUNNING_TASK3 = "RUNNING_TASK3"
    TASK4_PREEMPTING = "TASK4_PREEMPTING"
    RUNNING_TASK4 = "RUNNING_TASK4"
    TASK4_RESUMING = "TASK4_RESUMING"
    SAFE_HOLD = "SAFE_HOLD"
    SAFE_STOP = "SAFE_STOP"
    RESET_PENDING = "RESET_PENDING"
    FAULT = "FAULT"
    COMPLETED = "COMPLETED"


class TaskId(str, Enum):
    TASK1 = "TASK1"
    TASK3 = "TASK3"
    TASK4 = "TASK4"


class Target(str, Enum):
    USV = "T-Wave"
    UAV = "T-Sky"


class ActionType(str, Enum):
    START_TASK = "START_TASK"
    PAUSE_TASK = "PAUSE_TASK"
    RESUME_TASK = "RESUME_TASK"
    SAFE_HOLD = "SAFE_HOLD"
    SAFE_STOP = "SAFE_STOP"


@dataclass(frozen=True)
class Action:
    """One declaration of intent for a future USV/UAV adapter to enact."""

    command_id: str
    run_id: int
    target: Target
    action_type: ActionType
    task: TaskId | None
    issued_at: float
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Ack:
    """An acknowledgement of a domain action, never proof of task completion."""

    command_id: str
    run_id: int
    target: Target
    accepted: bool
    safe_paused: bool = False
    progress_marker: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class CompletionEvent:
    event_id: str
    run_id: int
    task: TaskId
    source: Target
    authoritative: bool
    succeeded: bool = True
    detail: str = ""


@dataclass(frozen=True)
class Checkpoint:
    """Persisted resumable state assembled only from child FSM confirmations."""

    version: int
    run_id: int
    task: TaskId
    saved_at: float
    affected_targets: tuple[Target, ...]
    progress_by_target: dict[str, str]
    pause_command_ids: dict[str, str]

    def is_valid_for(self, run_id: int, task: TaskId) -> bool:
        return (
            self.version == 1
            and self.run_id == run_id
            and self.task == task
            and bool(self.affected_targets)
            and set(target.value for target in self.affected_targets)
            == set(self.progress_by_target)
            == set(self.pause_command_ids)
            and all(self.progress_by_target.values())
            and all(self.pause_command_ids.values())
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["task"] = self.task.value
        value["affected_targets"] = [target.value for target in self.affected_targets]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Checkpoint":
        return cls(
            version=int(value["version"]),
            run_id=int(value["run_id"]),
            task=TaskId(value["task"]),
            saved_at=float(value["saved_at"]),
            affected_targets=tuple(Target(item) for item in value["affected_targets"]),
            progress_by_target=dict(value["progress_by_target"]),
            pause_command_ids=dict(value["pause_command_ids"]),
        )
