"""Test-only action sink.  It deliberately does not communicate externally."""

from __future__ import annotations

from .models import Action


class FakeAdapter:
    def __init__(self) -> None:
        self.actions: list[Action] = []

    def send_all(self, actions: list[Action]) -> None:
        self.actions.extend(actions)

    def log(self) -> list[str]:
        return [
            f"{action.command_id} {action.action_type.value} {action.task and action.task.value} -> {action.target.value}"
            for action in self.actions
        ]
