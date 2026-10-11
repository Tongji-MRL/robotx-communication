"""Global, pure-Python task decision state machine for T-Wave."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping

from .checkpoint_store import CheckpointStore, CheckpointStoreError
from .models import Ack, Action, ActionType, Checkpoint, CompletionEvent, MainState, TaskId, Target
from .task4_manager import checkpoint_from_safe_pauses
from .safety_latch_store import SafetyLatchStore, SafetyLatchStoreError
from .safety_models import SafetyStopRecord
from .audit_log import AuditLogger, AuditLogError


Clock = Callable[[], float]
MISSION_TARGETS = (Target.USV, Target.UAV)


class MissionCoordinator:
    """Decides task-level actions without directly controlling any hardware.

    An adapter must separately map emitted :class:`Action` instances onto
    frozen ROS 2/MQTT contracts.  Receipt ACKs only settle command delivery;
    authoritative CompletionEvent objects are the only normal-task advances.
    """

    def __init__(
        self, checkpoint_store: CheckpointStore, *, clock: Clock = time.monotonic,
        ack_timeout_s: float = 3.0, task_timeout_s: float = 300.0,
        task_targets: Mapping[TaskId, Iterable[Target]] | None = None,
        safety_latch_store: SafetyLatchStore | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.store = checkpoint_store
        self.clock = clock
        self.ack_timeout_s = ack_timeout_s
        self.task_timeout_s = task_timeout_s
        configured = task_targets or {task: MISSION_TARGETS for task in TaskId}
        self.task_targets = {
            task: tuple(dict.fromkeys(configured.get(task, ()))) for task in TaskId
        }
        if any(not targets for targets in self.task_targets.values()):
            raise ValueError("every Task1/Task3/Task4 target set must be non-empty")
        if any(not isinstance(target, Target) for targets in self.task_targets.values() for target in targets):
            raise ValueError("task target configuration must use Target values")
        self.all_targets = tuple(dict.fromkeys(
            target for targets in self.task_targets.values() for target in targets
        ))
        self.safety_latch_store = safety_latch_store or SafetyLatchStore(
            self.store.path.with_name(f"{self.store.path.stem}.safety-stop.json")
        )
        self.safety_latch_persistence_error = ""
        self.audit_logger = audit_logger
        self.audit_write_error = ""
        try:
            self.safety_stop_record = self.safety_latch_store.load()
        except SafetyLatchStoreError as exc:
            # An unreadable existing latch is fail-closed, never first install.
            self.safety_latch_persistence_error = str(exc)
            self.safety_stop_record = SafetyStopRecord(None, "persistence", str(exc), self.clock())
        self.state = MainState.SAFE_STOP if self.safety_stop_record else MainState.IDLE
        self.run_id: int | None = self.safety_stop_record.run_id if self.safety_stop_record else None
        self.current_task: TaskId | None = None
        self._counter = 0
        self._pending: dict[str, Action] = {}
        self._processed_events: set[str] = set()
        self._task_started_at: float | None = None
        self._preempted_task: TaskId | None = None
        self._pause_targets: tuple[Target, ...] = ()
        self._pause_progress: dict[str, str] = {}
        self._pause_ids: dict[str, str] = {}
        self._checkpoint: Checkpoint | None = None
        self._task4_completed = False
        self.safe_hold_reason = ""
        self.safe_hold_source = ""
        self.safe_hold_at: float | None = None
        self.safe_hold_progress: dict[str, str] = {}
        self._safe_hold_ids: dict[str, str] = {}
        # Deliberately only loads durable evidence.  It never resumes movement.
        self.saved_checkpoint = self.store.load()

    @property
    def checkpoint(self) -> Checkpoint | None:
        return self._checkpoint

    @property
    def pending_command_ids(self) -> frozenset[str]:
        return frozenset(self._pending)

    def arm_for_run_start(self) -> None:
        """Move a newly initialized coordinator into its waiting state."""
        if self.state == MainState.IDLE:
            self.state = MainState.WAIT_RUN_START

    def start_run(self, run_id: int) -> list[Action]:
        if run_id <= 0:
            return self._safe_hold("invalid RUN_START run_id")
        if self.state == MainState.SAFE_STOP:
            return []
        if self.run_id == run_id:
            return []  # Idempotent repeat of an already accepted run.
        if self.run_id is not None:
            return self._safe_hold("RUN_START for a different run while active")
        if self.state not in (MainState.IDLE, MainState.WAIT_RUN_START):
            return self._safe_hold("RUN_START is illegal in the current state")
        self.run_id = run_id
        self.state = MainState.RUNNING_TASK1
        self.current_task = TaskId.TASK1
        self._task_started_at = self.clock()
        actions = self._emit_many(ActionType.START_TASK, TaskId.TASK1, self.task_targets[TaskId.TASK1])
        self._audit("RUN_START", task_id="TASK1", state_after=self.state.value)
        return actions

    def complete_task(self, event: CompletionEvent) -> list[Action]:
        if not self._valid_run(event.run_id) or event.event_id in self._processed_events:
            return []
        self._processed_events.add(event.event_id)
        if not event.authoritative:
            return []
        if not event.succeeded:
            return self._fault(f"{event.task.value} failed: {event.detail}")
        if self.state == MainState.RUNNING_TASK1 and event.task == TaskId.TASK1:
            self._clear_pending_for_task(TaskId.TASK1)
            self.state = MainState.RUNNING_TASK3
            self.current_task = TaskId.TASK3
            self._task_started_at = self.clock()
            return self._emit_many(ActionType.START_TASK, TaskId.TASK3, self.task_targets[TaskId.TASK3])
        if self.state == MainState.RUNNING_TASK3 and event.task == TaskId.TASK3:
            self._clear_pending_for_task(TaskId.TASK3)
            self.state = MainState.COMPLETED
            self.current_task = None
            self._task_started_at = None
            return []
        if self.state == MainState.RUNNING_TASK4 and event.task == TaskId.TASK4:
            self._clear_pending_for_task(TaskId.TASK4)
            self._task4_completed = True
        return []

    def request_task4(self, run_id: int, *, affected_targets: Iterable[Target] | None = None) -> list[Action]:
        if not self._valid_run(run_id) or self.state == MainState.SAFE_STOP:
            return []
        if self.state not in (MainState.RUNNING_TASK1, MainState.RUNNING_TASK3):
            return self._safe_hold("Task4 preemption is illegal in the current state")
        targets = tuple(dict.fromkeys(affected_targets or self.task_targets[TaskId.TASK4]))
        if not targets:
            return self._safe_hold("Task4 has no affected targets")
        self._preempted_task = self.current_task
        # A preempted normal-task command is no longer actionable.  A late ACK
        # for it is ignored rather than becoming a future timeout hazard.
        self._clear_pending_for_task(self._preempted_task)
        self._pause_targets = targets
        self._pause_progress.clear()
        self._pause_ids.clear()
        self._task4_completed = False
        self.state = MainState.TASK4_PREEMPTING
        actions = self._emit_many(ActionType.PAUSE_TASK, self._preempted_task, targets)
        for action in actions:
            self._pause_ids[action.target.value] = action.command_id
        return actions

    def receive_ack(self, ack: Ack) -> list[Action]:
        if not self._valid_run(ack.run_id) or self.state == MainState.SAFE_STOP:
            return []
        action = self._pending.pop(ack.command_id, None)
        if action is None or action.target != ack.target:
            return []  # Duplicate, late, or foreign ACK.
        if not ack.accepted:
            return self._safe_hold(f"{action.action_type.value} rejected by {ack.target.value}: {ack.detail}")
        if self.state == MainState.TASK4_PREEMPTING and action.action_type == ActionType.PAUSE_TASK:
            if not ack.safe_paused or not ack.progress_marker:
                return self._safe_hold(f"{ack.target.value} did not confirm safe pause with progress")
            self._pause_progress[ack.target.value] = ack.progress_marker
            if set(self._pause_progress) != {target.value for target in self._pause_targets}:
                return []
            return self._commit_checkpoint_and_start_task4()
        if self.state == MainState.TASK4_RESUMING and action.action_type == ActionType.RESUME_TASK:
            if not any(item.action_type == ActionType.RESUME_TASK for item in self._pending.values()):
                self.state = self._running_state_for(self._preempted_task)
                self.current_task = self._preempted_task
                self._task_started_at = self.clock()
            return []
        if self.state == MainState.SAFE_HOLD and action.action_type == ActionType.SAFE_HOLD:
            if ack.accepted and ack.safe_paused and ack.progress_marker:
                self.safe_hold_progress[ack.target.value] = ack.progress_marker
                if (self.current_task is not None and
                        set(self.safe_hold_progress) == {target.value for target in self.all_targets}):
                    try:
                        self._checkpoint = checkpoint_from_safe_pauses(
                            run_id=self.run_id, task=self.current_task, targets=self.all_targets,
                            saved_at=self.clock(), progress_by_target=self.safe_hold_progress,
                            pause_command_ids=self._safe_hold_ids,
                        )
                        self.store.save(self._checkpoint)
                    except (ValueError, CheckpointStoreError):
                        pass  # Remain held; checkpoint is optional evidence, never an auto-resume trigger.
            return []
        return []

    def release_task4(self, run_id: int, *, recovery_permitted: bool, vehicles_safe: bool) -> list[Action]:
        if not self._valid_run(run_id) or self.state != MainState.RUNNING_TASK4:
            return []
        if not self._task4_completed:
            return self._safe_hold("Task4 is not complete; explicit release is unsafe")
        if not recovery_permitted or not vehicles_safe:
            return self._safe_hold("recovery permission or vehicle safety is missing")
        checkpoint = self._checkpoint or self.saved_checkpoint
        if self._preempted_task is None or checkpoint is None or not checkpoint.is_valid_for(run_id, self._preempted_task):
            return self._safe_hold("checkpoint is missing or invalid for recovery")
        self.state = MainState.TASK4_RESUMING
        return self._emit_many(
            ActionType.RESUME_TASK, self._preempted_task, checkpoint.affected_targets,
            {"checkpoint": checkpoint.to_dict(), "resume_authorized": True},
        )

    def safe_stop(self, run_id: int | None, *, reason: str, source: str = "coordinator") -> list[Action]:
        if run_id is not None and self.run_id is not None and run_id != self.run_id:
            return []
        if self.state == MainState.SAFE_STOP:
            return []
        self.state = MainState.SAFE_STOP
        self._pending.clear()
        self.safety_stop_record = SafetyStopRecord(self.run_id, source, reason, self.clock())
        try:
            self.safety_latch_store.save(self.safety_stop_record)
        except SafetyLatchStoreError as exc:
            self.safety_latch_persistence_error = str(exc)
        actions = self._emit_many(ActionType.SAFE_STOP, self.current_task, self.all_targets, {"reason": reason})
        self._audit("SAFE_STOP", source=source, reason=reason, state_after=self.state.value)
        return actions

    def request_safe_hold(self, run_id: int | None, *, reason: str, source: str = "SafetyMonitor") -> list[Action]:
        if run_id is not None and self.run_id is not None and run_id != self.run_id:
            return []
        return self._safe_hold(reason, source=source)

    def reset_safe_stop(self, *, authorization_id: str, severe_faults_clear: bool,
                        executors_safe: bool, failsafe_cleared: bool,
                        reinitialize_ready: bool, authorization_run_id: int | None = None) -> bool:
        """Testable software-latch reset; never clears hardware E-stop/failsafe."""
        if (self.state != MainState.SAFE_STOP or not authorization_id or
                (self.safety_stop_record and authorization_run_id != self.safety_stop_record.run_id)):
            return False
        self.state = MainState.RESET_PENDING
        if not all((severe_faults_clear, executors_safe, failsafe_cleared, reinitialize_ready)):
            self.state = MainState.SAFE_STOP
            return False
        try:
            self.safety_latch_store.clear()
        except SafetyLatchStoreError as exc:
            self.safety_latch_persistence_error = str(exc)
            self.state = MainState.SAFE_STOP
            return False
        self.safety_stop_record = None
        self.state = MainState.IDLE
        self.run_id = None
        self.current_task = None
        self._pending.clear()
        self._task_started_at = None
        return True

    def release_safe_hold(self, run_id: int, *, health_verified: bool,
                          recovery_permitted: bool, vehicles_safe: bool) -> list[Action]:
        """Explicit recovery only; a cleared fault is never sufficient on its own."""
        checkpoint = self._checkpoint or self.saved_checkpoint
        if (not self._valid_run(run_id) or self.state != MainState.SAFE_HOLD or
                not health_verified or not recovery_permitted or not vehicles_safe or
                self.current_task not in (TaskId.TASK1, TaskId.TASK3) or checkpoint is None or
                not checkpoint.is_valid_for(run_id, self.current_task)):
            return []
        self.state = MainState.TASK4_RESUMING
        return self._emit_many(ActionType.RESUME_TASK, self.current_task, checkpoint.affected_targets,
                               {"checkpoint": checkpoint.to_dict(), "resume_authorized": True, "safe_hold_release": True})

    def report_link_lost(self, target: Target, *, detail: str = "") -> list[Action]:
        if self.state in (MainState.SAFE_STOP, MainState.FAULT, MainState.COMPLETED):
            return []
        return self._safe_hold(f"communication lost with {target.value}: {detail}")

    def check_timeouts(self) -> list[Action]:
        if self.state in (MainState.SAFE_STOP, MainState.SAFE_HOLD, MainState.FAULT, MainState.COMPLETED):
            return []
        now = self.clock()
        if any(now - action.issued_at > self.ack_timeout_s for action in self._pending.values()):
            return self._safe_hold("command ACK timeout")
        if self._task_started_at is not None and now - self._task_started_at > self.task_timeout_s:
            return self._safe_hold("task execution timeout")
        return []

    def _commit_checkpoint_and_start_task4(self) -> list[Action]:
        assert self.run_id is not None and self._preempted_task is not None
        try:
            checkpoint = checkpoint_from_safe_pauses(
                run_id=self.run_id, task=self._preempted_task, targets=self._pause_targets,
                saved_at=self.clock(), progress_by_target=self._pause_progress,
                pause_command_ids=self._pause_ids,
            )
            self.store.save(checkpoint)
        except (ValueError, CheckpointStoreError) as exc:
            return self._safe_hold(f"checkpoint save failed: {exc}")
        self._checkpoint = checkpoint
        self.state = MainState.RUNNING_TASK4
        self.current_task = TaskId.TASK4
        self._task_started_at = self.clock()
        return self._emit_many(ActionType.START_TASK, TaskId.TASK4, self._pause_targets)

    def _emit_many(self, action_type: ActionType, task: TaskId | None, targets: Iterable[Target], parameters: dict | None = None) -> list[Action]:
        assert self.run_id is not None
        actions: list[Action] = []
        for target in targets:
            self._counter += 1
            action = Action(
                command_id=f"{self.run_id}-{self._counter}", run_id=self.run_id,
                target=target, action_type=action_type, task=task,
                issued_at=self.clock(), parameters=dict(parameters or {}),
            )
            actions.append(action)
            if action_type in (ActionType.START_TASK, ActionType.PAUSE_TASK, ActionType.RESUME_TASK):
                self._pending[action.command_id] = action
        return actions

    def _safe_hold(self, reason: str, *, source: str = "coordinator") -> list[Action]:
        if self.state == MainState.SAFE_STOP:
            return []
        self.state = MainState.SAFE_HOLD
        self._pending.clear()
        self.safe_hold_reason, self.safe_hold_source, self.safe_hold_at = reason, source, self.clock()
        self.safe_hold_progress.clear()
        self._audit("SAFE_HOLD", source=source, reason=reason, state_after=self.state.value)
        if self.run_id is None:
            return []
        actions = self._emit_many(ActionType.SAFE_HOLD, self.current_task, self.all_targets, {"reason": reason})
        self._safe_hold_ids = {action.target.value: action.command_id for action in actions}
        self._pending.update({action.command_id: action for action in actions})
        return actions

    def _audit(self, event_type: str, **fields) -> None:
        if self.audit_logger is None:
            return
        try:
            self.audit_logger.event(event_type, run_id=self.run_id, **fields)
        except AuditLogError as exc:
            self.audit_write_error = str(exc)
            # Fail closed without recursive audit writes.
            self.state = MainState.SAFE_STOP

    def _fault(self, reason: str) -> list[Action]:
        self.state = MainState.FAULT
        self._pending.clear()
        if self.run_id is None:
            return []
        return self._emit_many(ActionType.SAFE_HOLD, self.current_task, self.all_targets, {"reason": reason})

    def _valid_run(self, run_id: int) -> bool:
        return self.run_id is not None and self.run_id == run_id

    def _clear_pending_for_task(self, task: TaskId) -> None:
        self._pending = {
            command_id: action for command_id, action in self._pending.items()
            if action.task != task
        }

    @staticmethod
    def _running_state_for(task: TaskId | None) -> MainState:
        if task == TaskId.TASK1:
            return MainState.RUNNING_TASK1
        if task == TaskId.TASK3:
            return MainState.RUNNING_TASK3
        raise ValueError("only Task1 or Task3 can be resumed")
