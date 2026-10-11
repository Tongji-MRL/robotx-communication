import unittest
from pathlib import Path

from usv_main_fsm.fake_integration import IntegrationHarness
from usv_main_fsm.models import MainState, TaskId


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.path = Path.cwd() / "usv_main_fsm" / ".integration-checkpoint.json"
        self.path.unlink(missing_ok=True)
        self.harness = IntegrationHarness(self.path)

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    def test_run_start_task1_task3_completed_and_delivery_is_gated(self):
        self.harness.ocs_command("run_start", run_id=42)
        self.assertEqual(self.harness.coordinator.state, MainState.RUNNING_TASK1)
        self.harness.complete(TaskId.TASK1, "task1-done")
        self.assertEqual(self.harness.coordinator.state, MainState.RUNNING_TASK3)
        self.assertFalse(self.harness.uav.delivery_started)
        self.assertFalse(self.harness.uav.accept_delivery_request({"resource_color": "RED"}, scheduling_permitted=True))
        self.assertFalse(self.harness.uav.delivery_started)
        self.assertTrue(self.harness.uav.accept_delivery_request({
            "resource_color": "RED", "delivery_circle_color": "BLUE", "target_position": {"north_m": 1},
        }, scheduling_permitted=True))
        self.harness.complete(TaskId.TASK3, "task3-done")
        self.assertEqual(self.harness.coordinator.state, MainState.COMPLETED)

    def test_task4_preemption_and_recovery_from_task1_and_task3(self):
        self.harness.ocs_command("run_start", run_id=42)
        self.harness.ocs_command("task4_assistance", run_id=42)
        self.assertEqual(self.harness.coordinator.state, MainState.RUNNING_TASK4)
        self.assertIsNotNone(self.harness.coordinator.checkpoint)
        self.harness.complete(TaskId.TASK4, "task4-task1-done")
        self.harness.dispatch(self.harness.coordinator.release_task4(42, recovery_permitted=True, vehicles_safe=True))
        self.assertEqual(self.harness.coordinator.state, MainState.RUNNING_TASK1)

        self.harness.complete(TaskId.TASK1, "task1-done")
        self.harness.ocs_command("task4_assistance", run_id=42)
        self.assertEqual(self.harness.coordinator.state, MainState.RUNNING_TASK4)
        self.harness.complete(TaskId.TASK4, "task4-task3-done")
        self.harness.dispatch(self.harness.coordinator.release_task4(42, recovery_permitted=True, vehicles_safe=True))
        self.assertEqual(self.harness.coordinator.state, MainState.RUNNING_TASK3)


if __name__ == "__main__":
    unittest.main()
