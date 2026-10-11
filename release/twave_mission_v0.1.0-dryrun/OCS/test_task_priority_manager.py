import unittest

from task_priority_manager import TaskPriorityManager
from robotx import rx_commands_pb2, rx_common_pb2


class TaskPriorityManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = TaskPriorityManager("TONG")
        self.manager.register_vehicle("T-Sky", "uav")
        self.manager.register_vehicle("T-Wave", "usv")
        self.manager.start_run(42)
        self.manager.update_vehicle_status(
            "T-Wave", current_task="TASK1", task_phase="RUNNING", checkpoint={"gate": 1}
        )

    def test_task4_assistance_preempts_task1_and_resume_restores_checkpoint(self):
        command = rx_commands_pb2.RxCommand(
            team_id="TONG",
            seq=7,
            assistance_request=rx_commands_pb2.AssistanceRequest(
                position={"latitude": 1.28, "longitude": 103.85},
                vehicle_type=rx_common_pb2.TYPE_USV,
            ),
        )
        actions = self.manager.handle_official_command(command)
        self.assertEqual(actions[0]["priority"], "CRITICAL")
        self.assertTrue(actions[0]["preempt"])
        self.assertEqual(self.manager.vehicles["T-Wave"].preempted_task, "TASK1")

        ack_actions = self.manager.handle_vehicle_ack(
            "T-Wave", command_seq=7, accepted=True,
        )
        self.assertEqual(ack_actions[0]["report"], "incident_ack")
        readiness = self.manager.handle_readiness_report("T-Wave", command_seq=7)
        self.assertEqual(readiness[0]["report"], "readiness")

        resume = self.manager.release_task4("T-Wave", reason="readiness_confirmed")
        self.assertEqual(resume[0]["command"], "TASK4_RESUME")
        self.manager.handle_vehicle_ack("T-Wave", command_seq=7, accepted=True)
        self.assertEqual(self.manager.vehicles["T-Wave"].current_task, "TASK1")
        self.assertEqual(self.manager.vehicles["T-Wave"].checkpoint["gate"], 1)

    def test_duplicate_and_old_commands_are_rejected(self):
        command = rx_commands_pb2.RxCommand(
            team_id="TONG",
            seq=8,
            moving_object_alert=rx_commands_pb2.MovingObjectAlert(
                affected_vehicle_types=[rx_common_pb2.TYPE_UAV, rx_common_pb2.TYPE_USV],
            ),
        )
        self.manager.handle_official_command(command)
        with self.assertRaises(ValueError):
            self.manager.handle_official_command(command)

    def test_all_clear_generates_ack_and_resume(self):
        command = rx_commands_pb2.RxCommand(
            team_id="TONG",
            seq=9,
            keep_out_zone=rx_commands_pb2.KeepOutZone(
                radius_m=10.0, vehicle_type=rx_common_pb2.TYPE_USV,
            ),
        )
        self.manager.handle_official_command(command)
        self.manager.handle_vehicle_ack("T-Wave", command_seq=9, accepted=True)
        clear = rx_commands_pb2.RxCommand(
            team_id="TONG",
            seq=10,
            all_clear=rx_commands_pb2.AllClear(vehicle_type=rx_common_pb2.TYPE_USV),
        )
        actions = self.manager.handle_official_command(clear)
        self.assertEqual(actions[0]["command"], "TASK4_ALL_CLEAR")
        actions = self.manager.handle_vehicle_ack("T-Wave", command_seq=10, accepted=True)
        self.assertEqual(actions[0]["report"], "incident_ack")
        self.assertEqual(actions[1]["command"], "TASK4_RESUME")


if __name__ == "__main__":
    unittest.main()
