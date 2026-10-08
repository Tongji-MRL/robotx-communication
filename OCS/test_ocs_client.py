import types
import unittest

import ocs_client
from robotx import rx_commands_pb2, rx_common_pb2, rx_course_pb2


class OcsClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = ocs_client.OcsClient("127.0.0.1", 1883)
        self.published = []
        self.client._publish = lambda topic, message: self.published.append((topic, message)) or len(self.published)

    def message(self, topic, payload):
        return types.SimpleNamespace(topic=topic, payload=payload)

    def test_course_is_saved_and_matching_run_start_is_accepted(self) -> None:
        course = rx_course_pb2.RxCourse(course_id="RX2026-A", pinger_freq_hz=27000)
        course.corners.add(latitude=1.0, longitude=2.0)
        course.corners.add(latitude=1.0, longitude=3.0)
        course.corners.add(latitude=2.0, longitude=3.0)
        course.corners.add(latitude=1.0, longitude=2.0)
        self.client._on_message(None, None, self.message("robocommand/robotx/course", course.SerializeToString()))
        self.assertEqual(self.client.course.course_id, "RX2026-A")

        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        command = rx_commands_pb2.RxCommand(
            team_id="TONG",
            seq=1,
            run_start=rx_commands_pb2.RunStart(
                declaration_seq=self.client.declaration_seq,
                run_id=42,
            ),
        )
        self.client._on_message(None, None, self.message(self.client.command_topic, command.SerializeToString()))
        self.assertEqual(self.client.run_id, 42)
        self.assertEqual(self.client.last_command.seq, 1)

    def test_run_start_for_old_declaration_is_ignored(self) -> None:
        self.client.publish_run_declaration(["T-Sky"])
        command = rx_commands_pb2.RxCommand(
            team_id="TONG",
            seq=1,
            run_start=rx_commands_pb2.RunStart(declaration_seq=999, run_id=42),
        )
        self.client._on_message(None, None, self.message(self.client.command_topic, command.SerializeToString()))
        self.assertIsNone(self.client.run_id)
        self.assertIsNone(self.client.last_command)

    def test_report_sequences_are_per_vehicle_and_task3_bodies_are_supported(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.publish_heartbeat("T-Sky", latitude=1.0, longitude=2.0, vehicle_type="uav")
        self.client.publish_heartbeat("T-Wave", latitude=1.0, longitude=2.0)
        self.client.publish_docking_report("T-Wave", bay_id=2)
        self.client.publish_firefighting_report("T-Wave", window_id=1)
        self.client.publish_resource_delivery_request(
            "T-Wave", resource_color="red", delivery_circle_color="blue"
        )
        self.assertEqual([message.seq for _, message in self.published[1:]], [1, 1, 2, 3, 4])
        self.assertEqual(self.published[3][1].WhichOneof("body"), "docking")
        self.assertEqual(self.published[4][1].WhichOneof("body"), "firefighting")
        self.assertEqual(self.published[5][1].WhichOneof("body"), "resource_delivery")

    def test_undeclared_vehicle_is_rejected(self) -> None:
        self.client.publish_run_declaration(["T-Sky"])
        with self.assertRaises(ValueError):
            self.client.publish_heartbeat("T-Wave", latitude=1.0, longitude=2.0)

    def test_ocs_routes_to_usv_without_deciding_the_current_task(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        run_start = rx_commands_pb2.RxCommand(
            team_id="TONG",
            seq=1,
            run_start=rx_commands_pb2.RunStart(
                declaration_seq=self.client.declaration_seq, run_id=42
            ),
        )
        self.client._accept_command(run_start)
        run_actions = self.client.drain_internal_actions()
        self.assertEqual(len(run_actions), 1)
        self.assertEqual(run_actions[0]["command"], "RUN_START")
        self.assertEqual(run_actions[0]["vehicle_id"], "T-Wave")
        assistance = rx_commands_pb2.RxCommand(
            team_id="TONG",
            seq=2,
            assistance_request=rx_commands_pb2.AssistanceRequest(
                position=ocs_client.common_pb2.LatLng(latitude=1.28, longitude=103.85),
                vehicle_type=rx_common_pb2.TYPE_USV,
            ),
        )
        self.client._accept_command(assistance)
        task4_actions = self.client.drain_internal_actions()
        self.assertEqual(task4_actions[0]["command"], "TASK4_ASSISTANCE")
        self.assertFalse(task4_actions[0]["preempt"])
        self.assertEqual(task4_actions[0]["priority"], "OFFICIAL")
        self.assertEqual(task4_actions[0]["parameters"]["decision_owner"], "USV")

        self.client.accept_vehicle_ack("T-Wave", command_seq=2, accepted=True)
        self.assertEqual(self.published[-1][1].WhichOneof("body"), "incident_ack")
        self.client.accept_vehicle_readiness_report("T-Wave", command_seq=2)
        self.assertEqual(self.published[-1][1].WhichOneof("body"), "readiness")

        readiness_confirm = rx_commands_pb2.RxCommand(
            team_id="TONG",
            seq=3,
            readiness_confirm=rx_commands_pb2.ReadinessConfirm(
                report_seq=1, vehicle_id="T-Wave"
            ),
        )
        self.client._accept_command(readiness_confirm)
        self.assertEqual(self.client.drain_internal_actions()[0]["command"], "TASK4_READINESS_CONFIRM")
        self.client.accept_vehicle_ack("T-Wave", command_seq=3, accepted=True)
        self.assertEqual(self.client.drain_internal_actions(), [])

    def test_vehicle_task_report_is_converted_only_when_official_report_is_present(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.run_id = 42
        envelope = {
            "protocol_version": "1",
            "message_id": "m1",
            "sent_at_unix_ms": 0,
            "run_id": 42,
            "vehicle_id": "T-Wave",
            "source": "T-Wave",
            "frame_id": "wgs84",
            "kind": "task_report",
            "payload": {"task": "TASK1", "phase": "COMPLETE"},
        }
        self.client.accept_vehicle_envelope(envelope)
        self.assertEqual(len(self.published), 1)

        envelope["payload"] = {
            "task": "TASK1",
            "phase": "COMPLETE",
            "official_report": {
                "type": "safe_passage",
                "entry_position": {"latitude": 1.0, "longitude": 2.0},
                "exit_position": {"latitude": 1.1, "longitude": 2.1},
                "buoys": [],
            },
        }
        self.client.accept_vehicle_envelope(envelope)
        self.assertEqual(self.published[-1][1].WhichOneof("body"), "safe_passage")

    def test_usv_can_report_an_official_result_for_the_uav(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.run_id = 42
        self.client.accept_vehicle_task_report("T-Wave", {
            "task": "TASK4",
            "official_report": {
                "type": "readiness",
                "vehicle_id": "T-Sky",
                "command_seq": 9,
            },
        })
        self.assertEqual(self.published[-1][1].vehicle_id, "T-Sky")
        self.assertEqual(self.published[-1][1].WhichOneof("body"), "readiness")


if __name__ == "__main__":
    unittest.main()
