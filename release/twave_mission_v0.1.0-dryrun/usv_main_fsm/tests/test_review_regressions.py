"""Tests added from the phase-two audit before changing the coordinator."""

import tempfile
import unittest
from pathlib import Path

from usv_main_fsm.checkpoint_store import CheckpointStore
from usv_main_fsm.coordinator import MissionCoordinator
from usv_main_fsm.models import Ack, MainState, Target, TaskId


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.path = Path.cwd() / "usv_main_fsm" / ".review-checkpoint.json"
        self.path.unlink(missing_ok=True)

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_task_participants_are_configurable_per_task(self):
        coordinator = MissionCoordinator(
            CheckpointStore(self.path),
            task_targets={
                TaskId.TASK1: (Target.UAV,),
                TaskId.TASK3: (Target.USV,),
                TaskId.TASK4: (Target.USV, Target.UAV),
            },
        )
        starts = coordinator.start_run(42)
        self.assertEqual([action.target for action in starts], [Target.UAV])

    def test_partial_resume_ack_stays_resuming_and_rejection_enters_safe_hold(self):
        coordinator = MissionCoordinator(CheckpointStore(self.path))
        coordinator.start_run(42)
        pauses = coordinator.request_task4(42)
        task4 = []
        for action in pauses:
            task4.extend(coordinator.receive_ack(Ack(
                action.command_id, 42, action.target, True, True, action.target.value,
            )))
        for action in task4:
            coordinator.receive_ack(Ack(action.command_id, 42, action.target, True))
        from usv_main_fsm.models import CompletionEvent
        coordinator.complete_task(CompletionEvent("task4-done", 42, TaskId.TASK4, Target.USV, True))
        resumes = coordinator.release_task4(42, recovery_permitted=True, vehicles_safe=True)
        coordinator.receive_ack(Ack(resumes[0].command_id, 42, resumes[0].target, True))
        self.assertEqual(coordinator.state, MainState.TASK4_RESUMING)
        coordinator.receive_ack(Ack(resumes[1].command_id, 42, resumes[1].target, False, detail="refused"))
        self.assertEqual(coordinator.state, MainState.SAFE_HOLD)
        # The delayed success must not accidentally resume the original task.
        self.assertEqual(coordinator.receive_ack(Ack(resumes[1].command_id, 42, resumes[1].target, True)), [])
        self.assertEqual(coordinator.state, MainState.SAFE_HOLD)


if __name__ == "__main__":
    unittest.main()
