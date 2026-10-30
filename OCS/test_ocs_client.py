import json
import types
import unittest

import ocs_client
from ocs_gateway import Ros2MissionLink
from robotx import rx_commands_pb2, rx_common_pb2, rx_course_pb2


class OcsClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = ocs_client.OcsClient("127.0.0.1", 1883)
        self.published = []
        self.client._publish = lambda topic, message: self.published.append((topic, message)) or len(self.published)
        # Existing test scenarios are not competition declarations.  Supply
        # explicit test-only UAV data so legacy behavior tests remain focused
        # on their own contract; production has no such defaults.
        original = self.client.publish_run_declaration
        def declare_for_test(vehicle_ids, *args, **kwargs):
            if "T-Sky" in vehicle_ids:
                kwargs.setdefault("uav_geofence", [(1.0, 2.0), (1.0, 3.0), (2.0, 3.0), (1.0, 2.0)])
                kwargs.setdefault("uav_geofence_max_altitude_hae_m", 40.0)
                kwargs.setdefault("uav_pilot_callsign", "TEST-PILOT-UAPL-000")
            return original(vehicle_ids, *args, **kwargs)
        self.client.publish_run_declaration = declare_for_test
        self._publish_declaration = original

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
        self.assertEqual(self.client.course_store.get().course_id, "RX2026-A")
        course_actions = self.client.drain_internal_actions()
        self.assertEqual(course_actions[0]["kind"], "course_config")
        self.assertEqual(course_actions[0]["payload"]["corners"][0], {"latitude": 1.0, "longitude": 2.0})

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
        course = rx_course_pb2.RxCourse(course_id="RX2026-A", pinger_freq_hz=27000)
        course.corners.add(latitude=1.0, longitude=2.0)
        course.corners.add(latitude=1.0, longitude=3.0)
        course.corners.add(latitude=2.0, longitude=3.0)
        course.corners.add(latitude=1.0, longitude=2.0)
        self.client._accept_course(course)
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
        self.client.accept_vehicle_readiness_report(
            "T-Wave", command_seq=2, readiness_event_id="task4-2:readiness"
        )
        self.assertEqual(self.published[-1][1].WhichOneof("body"), "readiness")
        publication = self.client.drain_internal_actions()
        self.assertEqual(publication[0]["command"], "TASK4_READINESS_REPORT_PUBLISHED")
        self.assertEqual(publication[0]["parameters"]["report_seq"], 2)

        readiness_confirm = rx_commands_pb2.RxCommand(
            team_id="TONG",
            seq=3,
            readiness_confirm=rx_commands_pb2.ReadinessConfirm(
                report_seq=2, vehicle_id="T-Wave"
            ),
        )
        self.client._accept_command(readiness_confirm)
        confirmation = self.client.drain_internal_actions()[0]
        self.assertEqual(confirmation["command"], "TASK4_READINESS_CONFIRM")
        self.assertEqual(confirmation["parameters"]["original_command_seq"], 2)
        self.client.accept_vehicle_ack("T-Wave", command_seq=3, accepted=True)
        self.assertEqual(self.client.drain_internal_actions(), [])

    def test_run_start_without_course_is_rejected_before_relay(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        command = rx_commands_pb2.RxCommand(
            team_id="TONG", seq=1,
            run_start=rx_commands_pb2.RunStart(
                declaration_seq=self.client.declaration_seq, run_id=42,
            ),
        )
        with self.assertRaisesRegex(ValueError, "RxCourse"):
            self.client._accept_command(command)
        self.assertIsNone(self.client.run_id)
        self.assertEqual(self.client.drain_internal_actions(), [])
        self.assertEqual(self.client.last_rejection_reason, "RunStart received before a valid RxCourse")

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

    def test_ros2_task4_candidate_mapping_is_not_a_publish_authorization(self) -> None:
        assistance = Ros2MissionLink._task4_payload({
            "command": "TASK4_ASSISTANCE",
            "parameters": {"position": {"latitude": 1.0, "longitude": 2.0}, "vehicle_type": 1},
        })
        self.assertIsNone(assistance)  # missing official command sequence is rejected
        readiness = Ros2MissionLink._task4_payload({
            "command": "TASK4_READINESS_CONFIRM",
            "run_id": 42,
            "command_seq": 9,
            "parameters": {
                "report_seq": 4,
                "vehicle": "usv",
                "original_command_seq": 2,
            },
        })
        self.assertEqual(readiness["command"]["type"], "READINESS_CONFIRM")
        self.assertEqual(readiness["command"]["report_seq"], 4)
        self.assertEqual(readiness["command"]["original_command_seq"], 2)
        publication = Ros2MissionLink._task4_payload({
            "command": "TASK4_READINESS_REPORT_PUBLISHED",
            "run_id": 42,
            "parameters": {
                "vehicle": "uav", "original_command_seq": 2,
                "report_seq": 4, "readiness_event_id": "a1:readiness",
            },
        })
        self.assertEqual(publication["command"]["type"], "READINESS_REPORT_PUBLISHED")
        self.assertIsNone(Ros2MissionLink._task4_payload({"command": "TASK4_KEEP_OUT_ZONE"}))

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

    def test_fsm_readiness_is_normalized_correlated_and_confirmed(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.run_id = 42
        self.client.accept_fsm_task_report(json.dumps({
            "run_id": 42, "vehicle": "uav", "task": "TASK4",
            "command_id": "assist-2",
            "official_report": {
                "type": "readiness", "vehicle_id": "uav", "command_seq": 2,
                "readiness_event_id": "assist-2:readiness", "dry_run": True,
            },
        }))
        report = self.published[-1][1]
        self.assertEqual((report.vehicle_id, report.WhichOneof("body"), report.seq), ("T-Sky", "readiness", 1))
        notice = self.client.drain_internal_actions()[0]
        self.assertEqual(notice["parameters"]["vehicle"], "uav")
        self.assertEqual(notice["parameters"]["report_seq"], report.seq)
        self.client._accept_command(rx_commands_pb2.RxCommand(
            team_id="TONG", seq=1,
            readiness_confirm=rx_commands_pb2.ReadinessConfirm(
                report_seq=report.seq, vehicle_id="T-Sky"
            ),
        ))
        confirmation = self.client.drain_internal_actions()[0]
        self.assertEqual(confirmation["parameters"]["original_command_seq"], 2)
        self.assertEqual(confirmation["parameters"]["vehicle"], "uav")

    def test_unmatched_readiness_confirm_is_rejected(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.run_id = 42
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.client._accept_command(rx_commands_pb2.RxCommand(
                team_id="TONG", seq=1,
                readiness_confirm=rx_commands_pb2.ReadinessConfirm(
                    report_seq=99, vehicle_id="T-Sky"
                ),
            ))

    def test_fsm_fault_is_recorded_without_official_fault_report(self) -> None:
        self.client.accept_fsm_fault(json.dumps({
            "run_id": 42, "vehicle": "usv", "error": "motor timeout",
            "safety_state": "SAFE_STOP",
        }))
        self.assertEqual(self.client.latest_fsm_fault["error"], "motor timeout")
        event = self.client.runtime_events[-1]
        self.assertEqual((event["source"], event["event"], event["run_id"]), ("ros2", "fsm_fault", 42))
        self.assertEqual(self.published, [])

    def test_official_2026_proto_fields_are_preserved_without_defaults(self) -> None:
        course = rx_course_pb2.RxCourse(course_id="RX2026-A", pinger_freq_hz=27000)
        for latitude, longitude in ((1.0, 2.0), (1.0, 3.0), (2.0, 3.0), (1.0, 2.0)):
            course.corners.add(latitude=latitude, longitude=longitude)
        for latitude, longitude in ((0.9, 1.9), (0.9, 2.1), (1.1, 2.1), (0.9, 1.9)):
            course.uav_transit_area.add(latitude=latitude, longitude=longitude)
        self.client._accept_course(course)
        payload = self.client.drain_internal_actions()[0]["payload"]
        self.assertEqual(len(payload["corners"]), 4)
        self.assertEqual(len(payload["uav_transit_area"]), 4)
        self._publish_declaration(
            ["T-Sky"],
            uav_geofence=[(1.0, 2.0), (1.0, 3.0), (2.0, 3.0), (1.0, 2.0)],
            uav_geofence_max_altitude_hae_m=40.0,
            uav_pilot_callsign="TEST-PILOT-UAPL-000",
        )
        declaration = self.published[-1][1].run_declaration
        self.assertEqual(declaration.uav_geofence_max_altitude_hae_m, 40.0)
        self.assertEqual(declaration.uav_pilot_callsign, "TEST-PILOT-UAPL-000")
        with self.assertRaisesRegex(ValueError, "uav_geofence_max_altitude"):
            self._publish_declaration(["T-Sky"], uav_geofence=[(1.0, 2.0), (1.0, 3.0), (2.0, 3.0), (1.0, 2.0)], uav_pilot_callsign="TEST")

    def test_heartbeat_registration_and_moving_alert_radius_are_preserved(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.publish_heartbeat(
            "T-Sky", latitude=1.0, longitude=2.0, vehicle_type="uav",
            uav_registration="CAAS-TEST-001",
        )
        self.assertEqual(self.published[-1][1].heartbeat.uav_registration, "CAAS-TEST-001")
        command = rx_commands_pb2.RxCommand(
            team_id="TONG", seq=1,
            moving_object_alert=rx_commands_pb2.MovingObjectAlert(
                keep_out_radius_m=12.5,
            ),
        )
        action = self.client._relay_official_command(command)
        self.assertEqual(action["parameters"]["keep_out_radius_m"], 12.5)


if __name__ == "__main__":
    unittest.main()
