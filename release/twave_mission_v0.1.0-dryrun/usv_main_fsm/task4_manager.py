"""Small, transport-free helper for Task4 checkpoint validation."""

from __future__ import annotations

from .models import Checkpoint, Target, TaskId


def checkpoint_from_safe_pauses(
    *, run_id: int, task: TaskId, targets: tuple[Target, ...], saved_at: float,
    progress_by_target: dict[str, str], pause_command_ids: dict[str, str],
) -> Checkpoint:
    checkpoint = Checkpoint(
        version=1,
        run_id=run_id,
        task=task,
        saved_at=saved_at,
        affected_targets=targets,
        progress_by_target=progress_by_target,
        pause_command_ids=pause_command_ids,
    )
    if not checkpoint.is_valid_for(run_id, task):
        raise ValueError("child FSM pause confirmations do not form a valid checkpoint")
    return checkpoint
