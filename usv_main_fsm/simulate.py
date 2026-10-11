"""Windows-friendly dry-run demonstrations; no network or hardware access."""

from __future__ import annotations

import argparse
from pathlib import Path

from .checkpoint_store import CheckpointStore
from .coordinator import MissionCoordinator
from .fake_adapters import FakeAdapter
from .models import Ack, CompletionEvent, Target, TaskId


def _ack_all(coordinator: MissionCoordinator, adapter: FakeAdapter, actions) -> None:
    for action in actions:
        follow_up = coordinator.receive_ack(Ack(
            action.command_id, action.run_id, action.target, True,
            safe_paused=action.action_type.value == "PAUSE_TASK",
            progress_marker=f"{action.target.value}:safe" if action.action_type.value == "PAUSE_TASK" else None,
        ))
        adapter.send_all(follow_up)


def run(scenario: str) -> list[str]:
    checkpoint_path = Path.cwd() / "usv_main_fsm" / ".simulation-checkpoint.json"
    checkpoint_path.unlink(missing_ok=True)
    try:
        coordinator = MissionCoordinator(CheckpointStore(checkpoint_path))
        adapter = FakeAdapter()
        first = coordinator.start_run(42)
        adapter.send_all(first)
        _ack_all(coordinator, adapter, first)
        if scenario == "normal":
            task3 = coordinator.complete_task(CompletionEvent("task1-done", 42, TaskId.TASK1, Target.USV, True))
            adapter.send_all(task3)
            _ack_all(coordinator, adapter, task3)
            coordinator.complete_task(CompletionEvent("task3-done", 42, TaskId.TASK3, Target.USV, True))
        else:
            pause = coordinator.request_task4(42)
            adapter.send_all(pause)
            _ack_all(coordinator, adapter, pause)
            task4_actions = adapter.actions[-2:]
            _ack_all(coordinator, adapter, task4_actions)
            coordinator.complete_task(CompletionEvent("task4-done", 42, TaskId.TASK4, Target.USV, True))
            resume = coordinator.release_task4(42, recovery_permitted=True, vehicles_safe=True)
            adapter.send_all(resume)
            _ack_all(coordinator, adapter, resume)
        return adapter.log() + [f"STATE {coordinator.state.value}"]
    finally:
        checkpoint_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="T-Wave main FSM dry-run simulator")
    parser.add_argument("scenario", choices=("normal", "task4"))
    args = parser.parse_args()
    print("\n".join(run(args.scenario)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
