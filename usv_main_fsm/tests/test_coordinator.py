import unittest
from pathlib import Path

from usv_main_fsm.checkpoint_store import CheckpointStore, CheckpointStoreError
from usv_main_fsm.coordinator import MissionCoordinator
from usv_main_fsm.models import Ack, ActionType, CompletionEvent, MainState, Target, TaskId


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class FailingStore(CheckpointStore):
    def save(self, checkpoint):
        raise CheckpointStoreError("disk unavailable")


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.checkpoint_path = Path.cwd() / "usv_main_fsm" / ".test-checkpoint.json"
        self.checkpoint_path.unlink(missing_ok=True)
        self.clock = Clock()
        self.coordinator = MissionCoordinator(
            CheckpointStore(self.checkpoint_path),
            clock=self.clock, ack_timeout_s=2, task_timeout_s=10,
        )

    def tearDown(self):
        self.checkpoint_path.unlink(missing_ok=True)
        self.coordinator.safety_latch_store.path.unlink(missing_ok=True)

    def start_task1(self):
        actions = self.coordinator.start_run(42)
        self.assertEqual(self.coordinator.state, MainState.RUNNING_TASK1)
        self.assertEqual({item.action_type for item in actions}, {ActionType.START_TASK})
        self.assertEqual({item.target for item in actions}, {Target.USV, Target.UAV})
        return actions

    def acknowledge(self, actions, *, safe_pause=False):
        emitted = []
        for action in actions:
            emitted.extend(self.coordinator.receive_ack(Ack(
                action.command_id, action.run_id, action.target, True,
                safe_paused=safe_pause,
                progress_marker=f"{action.target.value}-progress" if safe_pause else None,
            )))
        return emitted

    def complete_task1(self):
        return self.coordinator.complete_task(CompletionEvent("task1-complete", 42, TaskId.TASK1, Target.USV, True))

    def preempt_task1(self):
        self.start_task1()
        pause = self.coordinator.request_task4(42)
        self.assertEqual(self.coordinator.state, MainState.TASK4_PREEMPTING)
        return pause

    def test_run_start_starts_task1(self):
        self.start_task1()

    def test_task1_completion_starts_task3_and_task3_completion_completes(self):
        self.start_task1()
        task3 = self.complete_task1()
        self.assertEqual(self.coordinator.state, MainState.RUNNING_TASK3)
        self.assertTrue(all(action.task == TaskId.TASK3 for action in task3))
        self.coordinator.complete_task(CompletionEvent("task3-complete", 42, TaskId.TASK3, Target.USV, True))
        self.assertEqual(self.coordinator.state, MainState.COMPLETED)

    def test_ack_is_not_task_completion(self):
        actions = self.start_task1()
        self.acknowledge(actions)
        self.assertEqual(self.coordinator.state, MainState.RUNNING_TASK1)

    def test_task4_preempts_task1_after_all_safe_pauses_and_can_resume(self):
        pause = self.preempt_task1()
        task4 = self.acknowledge(pause, safe_pause=True)
        self.assertEqual(self.coordinator.state, MainState.RUNNING_TASK4)
        self.assertTrue(all(action.action_type == ActionType.START_TASK for action in task4))
        self.assertIsNotNone(self.coordinator.checkpoint)
        self.coordinator.complete_task(CompletionEvent("task4-complete", 42, TaskId.TASK4, Target.USV, True))
        resume = self.coordinator.release_task4(42, recovery_permitted=True, vehicles_safe=True)
        self.assertEqual(self.coordinator.state, MainState.TASK4_RESUMING)
        self.assertTrue(all(action.action_type == ActionType.RESUME_TASK for action in resume))
        self.assertTrue(set(item.command_id for item in resume).isdisjoint(item.command_id for item in pause))
        self.acknowledge(resume)
        self.assertEqual(self.coordinator.state, MainState.RUNNING_TASK1)

    def test_task4_preempts_task3(self):
        self.start_task1()
        self.complete_task1()
        pause = self.coordinator.request_task4(42)
        task4 = self.acknowledge(pause, safe_pause=True)
        self.assertEqual(self.coordinator.state, MainState.RUNNING_TASK4)
        self.coordinator.complete_task(CompletionEvent("task4-complete", 42, TaskId.TASK4, Target.USV, True))
        resume = self.coordinator.release_task4(42, recovery_permitted=True, vehicles_safe=True)
        self.acknowledge(resume)
        self.assertEqual(self.coordinator.state, MainState.RUNNING_TASK3)
        self.assertEqual(self.coordinator.current_task, TaskId.TASK3)
        self.assertEqual(len(task4), 2)

    def test_missing_safe_pause_confirmation_does_not_commit_checkpoint(self):
        pause = self.preempt_task1()
        self.coordinator.receive_ack(Ack(pause[0].command_id, 42, pause[0].target, True, safe_paused=True, progress_marker="ok"))
        result = self.coordinator.receive_ack(Ack(pause[1].command_id, 42, pause[1].target, True, safe_paused=False))
        self.assertEqual(self.coordinator.state, MainState.SAFE_HOLD)
        self.assertIsNone(self.coordinator.checkpoint)
        self.assertTrue(all(action.action_type == ActionType.SAFE_HOLD for action in result))

    def test_checkpoint_save_failure_enters_safe_hold(self):
        failing = MissionCoordinator(FailingStore(self.checkpoint_path), clock=self.clock)
        failing.start_run(42)
        pause = failing.request_task4(42)
        failing.receive_ack(Ack(pause[0].command_id, 42, pause[0].target, True, True, "a"))
        failing.receive_ack(Ack(pause[1].command_id, 42, pause[1].target, True, True, "b"))
        self.assertEqual(failing.state, MainState.SAFE_HOLD)

    def test_invalid_checkpoint_blocks_recovery(self):
        pause = self.preempt_task1()
        self.acknowledge(pause, safe_pause=True)
        self.coordinator.complete_task(CompletionEvent("task4-complete", 42, TaskId.TASK4, Target.USV, True))
        self.coordinator._checkpoint = None  # Simulate missing/corrupt durable evidence.
        self.coordinator.saved_checkpoint = None
        self.coordinator.release_task4(42, recovery_permitted=True, vehicles_safe=True)
        self.assertEqual(self.coordinator.state, MainState.SAFE_HOLD)

    def test_old_run_duplicate_event_and_late_ack_do_not_repeat_work(self):
        starts = self.start_task1()
        self.assertEqual(self.coordinator.complete_task(CompletionEvent("old", 41, TaskId.TASK1, Target.USV, True)), [])
        first = self.complete_task1()
        self.assertEqual(len(first), 2)
        self.assertEqual(self.complete_task1(), [])
        self.assertEqual(self.coordinator.receive_ack(Ack(starts[0].command_id, 41, starts[0].target, True)), [])
        self.assertEqual(self.coordinator.state, MainState.RUNNING_TASK3)

    def test_safe_stop_latches_and_blocks_normal_execution(self):
        self.start_task1()
        actions = self.coordinator.safe_stop(42, reason="operator")
        self.assertEqual(self.coordinator.state, MainState.SAFE_STOP)
        self.assertTrue(all(item.action_type == ActionType.SAFE_STOP for item in actions))
        self.assertEqual(self.coordinator.start_run(43), [])
        self.assertEqual(self.complete_task1(), [])
        self.assertEqual(self.coordinator.request_task4(42), [])

    def test_illegal_task3_completion_during_task1_is_ignored(self):
        self.start_task1()
        actions = self.coordinator.complete_task(
            CompletionEvent("wrong-task", 42, TaskId.TASK3, Target.USV, True)
        )
        self.assertEqual(actions, [])
        self.assertEqual(self.coordinator.state, MainState.RUNNING_TASK1)
        self.assertEqual(self.coordinator.current_task, TaskId.TASK1)

    def test_no_public_direct_task3_start_exists_and_run_start_only_starts_task1(self):
        self.assertFalse(hasattr(self.coordinator, "start_task3"))
        actions = self.coordinator.start_run(42)
        self.assertTrue(actions)
        self.assertTrue(all(item.action_type == ActionType.START_TASK for item in actions))
        self.assertTrue(all(item.task == TaskId.TASK1 for item in actions))

    def test_safe_stop_after_task4_request_latches_and_blocks_all_late_inputs(self):
        starts = self.start_task1()
        pause_actions = self.coordinator.request_task4(42)
        self.assertEqual(self.coordinator.state, MainState.TASK4_PREEMPTING)
        stop_actions = self.coordinator.safe_stop(42, reason="operator override")
        self.assertEqual(self.coordinator.state, MainState.SAFE_STOP)
        self.assertTrue(all(action.action_type == ActionType.SAFE_STOP for action in stop_actions))

        self.assertEqual(self.coordinator.start_run(43), [])
        self.assertEqual(self.coordinator.request_task4(42), [])
        self.assertEqual(self.coordinator.release_task4(42, recovery_permitted=True, vehicles_safe=True), [])
        self.assertEqual(self.coordinator.complete_task(
            CompletionEvent("late-task1", 42, TaskId.TASK1, Target.USV, True)
        ), [])
        self.assertEqual(self.coordinator.receive_ack(
            Ack(starts[0].command_id, 42, starts[0].target, True)
        ), [])
        self.assertEqual(self.coordinator.receive_ack(
            Ack(pause_actions[0].command_id, 42, pause_actions[0].target, True, True, "late")
        ), [])
        self.assertEqual(self.coordinator.state, MainState.SAFE_STOP)

    def test_authoritative_task_failure_enters_fault(self):
        self.start_task1()
        actions = self.coordinator.complete_task(
            CompletionEvent("task1-failed", 42, TaskId.TASK1, Target.USV, True, succeeded=False, detail="executor fault")
        )
        self.assertEqual(self.coordinator.state, MainState.FAULT)
        self.assertTrue(all(action.action_type == ActionType.SAFE_HOLD for action in actions))

    def test_timeouts_and_link_loss_enter_safe_hold_without_resuming(self):
        starts = self.start_task1()
        self.clock.value += 3
        self.coordinator.check_timeouts()
        self.assertEqual(self.coordinator.state, MainState.SAFE_HOLD)
        self.assertEqual(self.coordinator.release_task4(42, recovery_permitted=True, vehicles_safe=True), [])

        second = MissionCoordinator(CheckpointStore(self.checkpoint_path), clock=self.clock)
        second.start_run(99)
        second.report_link_lost(Target.UAV, detail="heartbeat deadline")
        self.assertEqual(second.state, MainState.SAFE_HOLD)

        third = MissionCoordinator(CheckpointStore(self.checkpoint_path), clock=self.clock, ack_timeout_s=2, task_timeout_s=10)
        running = third.start_run(123)
        for action in running:
            third.receive_ack(Ack(action.command_id, 123, action.target, True))
        self.clock.value += 11
        third.check_timeouts()
        self.assertEqual(third.state, MainState.SAFE_HOLD)

    def test_restart_loads_checkpoint_but_never_auto_resumes(self):
        pause = self.preempt_task1()
        self.acknowledge(pause, safe_pause=True)
        restarted = MissionCoordinator(self.coordinator.store, clock=self.clock)
        self.assertIsNotNone(restarted.saved_checkpoint)
        self.assertEqual(restarted.state, MainState.IDLE)
        self.assertIsNone(restarted.run_id)
        self.assertEqual(restarted.pending_command_ids, frozenset())

    def test_idle_can_be_armed_for_run_start(self):
        self.assertEqual(self.coordinator.state, MainState.IDLE)
        self.coordinator.arm_for_run_start()
        self.assertEqual(self.coordinator.state, MainState.WAIT_RUN_START)


if __name__ == "__main__":
    unittest.main()
