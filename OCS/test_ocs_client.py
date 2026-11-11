import json
import time
import threading
import types
import unittest

import ocs_client
from course_config import fingerprint, make_payload
from ocs_gateway import OcsGateway, Ros2MissionLink
from operation_mode import VehicleMode
from robotx import rx_commands_pb2, rx_common_pb2, rx_course_pb2, rx_reports_pb2, rx_requests_pb2


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
        self._accept_course_for_test()
        self.client.drain_internal_actions()

    def message(self, topic, payload):
        return types.SimpleNamespace(topic=topic, payload=payload)

    def _accept_course_for_test(self, course_id="RX2026-A", sent_at=None):
        course = rx_course_pb2.RxCourse(course_id=course_id, pinger_freq_hz=27000)
        for latitude, longitude in ((1.0, 2.0), (1.0, 3.0), (2.0, 3.0), (1.0, 2.0)):
            course.corners.add(latitude=latitude, longitude=longitude)
        if sent_at is not None:
            course.sent_at.seconds = sent_at
        self.client._accept_course(course)
        return course

    def test_course_is_saved_and_matching_run_start_is_accepted(self) -> None:
        course = rx_course_pb2.RxCourse(course_id="RX2026-B", pinger_freq_hz=27000)
        course.corners.add(latitude=1.0, longitude=2.0)
        course.corners.add(latitude=1.0, longitude=3.0)
        course.corners.add(latitude=2.0, longitude=3.0)
        course.corners.add(latitude=1.0, longitude=2.0)
        course.sent_at.seconds = 1
        self.client._on_message(None, None, self.message("robocommand/robotx/course", course.SerializeToString()))
        self.assertEqual(self.client.course.course_id, "RX2026-B")
        self.assertEqual(self.client.course_store.get().course_id, "RX2026-B")
        course_actions = self.client.drain_internal_actions()
        self.assertEqual(course_actions[0]["kind"], "course_config")
        self.assertEqual(course_actions[0]["payload"]["corners"][0], {"latitude": 1.0, "longitude": 2.0})

        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        decoded_declaration = rx_requests_pb2.RxRequest()
        decoded_declaration.ParseFromString(self.published[-1][1].SerializeToString())
        self.assertEqual(decoded_declaration.WhichOneof("body"), "run_declaration")
        self.assertEqual(decoded_declaration.team_id, "TONG")
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
        self.client.course = None
        self.client.course_store = ocs_client.CourseStore()
        self.client._course_fingerprint = None
        with self.assertRaisesRegex(ValueError, "valid current RxCourse"):
            self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.declaration_seq = 1
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

    def test_course_update_invalidates_old_declaration_and_stale_update_is_rejected(self) -> None:
        self._accept_course_for_test(course_id="RX2026-A", sent_at=10)
        self.client.drain_internal_actions()
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        old_declaration = self.client.declaration_seq
        self._accept_course_for_test(course_id="RX2026-B", sent_at=11)
        self.assertIsNone(self.client.declaration_seq)
        self.assertEqual(self.client._declared_vehicle_ids, set())
        with self.assertRaisesRegex(ValueError, "before a RunDeclaration"):
            self.client._accept_command(rx_commands_pb2.RxCommand(
                team_id="TONG", seq=1,
                run_start=rx_commands_pb2.RunStart(declaration_seq=old_declaration, run_id=42),
            ))
        with self.assertRaisesRegex(ValueError, "stale or out of order"):
            self._accept_course_for_test(course_id="RX2026-C", sent_at=10)
        with self.assertRaisesRegex(ValueError, "missing sent_at"):
            self._accept_course_for_test(course_id="RX2026-D")

    def test_reconnect_clears_pre_run_course_and_restores_required_subscriptions(self) -> None:
        self.assertIsNotNone(self.client.course_store.get())
        self.client._on_disconnect(None, None, None, 1)
        self.assertIsNone(self.client.course_store.get())
        with self.assertRaisesRegex(ValueError, "valid current RxCourse"):
            self.client.publish_run_declaration(["T-Sky"])
        subscriptions = []
        self.client._on_connect(types.SimpleNamespace(subscribe=lambda topics: subscriptions.append(topics)), None, None, 0)
        self.assertEqual(subscriptions, [[("robocommand/robotx/course", 1), (self.client.command_topic, 1)]])

    def test_reconnect_invalidates_course_ack_for_held_run_start_until_course_reappears(self) -> None:
        status = {
            "schema_version": "twave-mission-status-v2", "timestamp": "2026-11-05T00:00:00Z",
            "fsm_state": "WAIT_RUN_START", "run_id": None,
            "course": {"course_id": "RX2026-A", "fingerprint": self.client.course_fingerprint,
                       "fsm_accepted": True, "applied": True},
            "safety": {}, "vehicles": {}, "legacy": {},
        }
        self.client.accept_fsm_status(json.dumps(status))
        self.assertTrue(self.client.is_current_course_ready())
        self.client.run_id = 42  # Official RunStart received, but not internally released.
        self.client._on_disconnect(None, None, None, 1)
        self.assertFalse(self.client.is_current_course_ready())
        self._accept_course_for_test()
        self.client.accept_fsm_status(json.dumps(status))
        self.assertTrue(self.client.is_current_course_ready())

    def test_gateway_publishes_course_before_blocking_run_start_without_fsm_ack(self) -> None:
        payload = make_payload(course_id="RX2026-A", pinger_freq_hz=27000,
                               corners=[(1, 2), (1, 3), (2, 3), (1, 2)], source_sent_at=None)
        course_action = {"kind": "course_config", "vehicle_id": "T-Wave", "payload": payload}
        run_action = {"kind": "internal_command", "vehicle_id": "T-Wave", "command": "RUN_START", "run_id": 42,
                      "command_seq": 1, "course_fingerprint": fingerprint(payload)}
        events = []
        gateway = OcsGateway.__new__(OcsGateway)
        gateway.ocs = types.SimpleNamespace(
            mission_coordinator="T-Wave", drain_internal_actions=lambda: [course_action, run_action],
            course_fingerprint=fingerprint(payload), is_current_course_ready=lambda *_args: False,
        )
        gateway.ros2 = types.SimpleNamespace(
            available=True,
            publish_course=lambda payload: events.append(("course", payload)) or True,
            publish_action=lambda action: events.append(("action", action)) or (True, None),
        )
        gateway._start_lock = threading.RLock()
        gateway._clock = time.monotonic
        gateway.startup_state = "WAIT_COURSE"
        gateway.startup_reason = "test"
        gateway.pending_course = None
        gateway.course_published_fingerprint = None
        gateway.pending_control_actions = []
        gateway._pending_run_starts = []
        gateway._published_run_starts = []
        gateway.flush_commands()
        self.assertEqual(events, [("course", course_action["payload"])])
        self.assertEqual(gateway.pending_control_actions[0]["state"], "BLOCKED_COURSE_READY_ACK")

    def test_usv_only_republishes_current_course_for_restarted_task_node(self) -> None:
        """A volatile Orin Course subscription must recover after node restart."""
        now = [10.0]
        course_payload = make_payload(course_id="RX2026-A", pinger_freq_hz=27000,
                                      corners=[(1, 2), (1, 3), (2, 3), (1, 2)], source_sent_at=None)
        course_fingerprint = fingerprint(course_payload)
        republishes = []
        gateway = OcsGateway.__new__(OcsGateway)
        gateway.ocs = types.SimpleNamespace(
            mission_coordinator="T-Wave", course_fingerprint=course_fingerprint,
            drain_internal_actions=lambda: [],
        )
        gateway.ros2 = types.SimpleNamespace(
            available=True,
            republish_course=lambda: republishes.append("course") or True,
        )
        gateway._start_lock = threading.RLock()
        gateway._clock = lambda: now[0]
        gateway.vehicle_mode = VehicleMode.USV_ONLY
        gateway.pending_course = None
        gateway.course_published_fingerprint = course_fingerprint
        gateway._next_usv_course_republish_at = 0.0
        gateway.pending_control_actions = []
        gateway._pending_run_starts = []
        gateway._published_run_starts = []

        gateway.flush_commands()
        self.assertEqual(republishes, ["course"])
        gateway.flush_commands()
        self.assertEqual(republishes, ["course"])
        now[0] += 1.0
        gateway.flush_commands()
        self.assertEqual(republishes, ["course", "course"])

    def test_matching_fsm_course_ack_releases_run_start_once(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.queue_course_sync()
        self.client._accept_command(rx_commands_pb2.RxCommand(
            team_id="TONG", seq=1,
            run_start=rx_commands_pb2.RunStart(declaration_seq=self.client.declaration_seq, run_id=42),
        ))
        events = []
        gateway = OcsGateway.__new__(OcsGateway)
        gateway.ocs = self.client
        gateway.ros2 = types.SimpleNamespace(
            available=True,
            publish_course=lambda payload: events.append(("course", payload)) or True,
            publish_action=lambda action: events.append(("run_start", action)) or (True, None),
        )
        gateway._start_lock = threading.RLock()
        gateway._clock = time.monotonic
        gateway.startup_state = "DECLARED"
        gateway.startup_reason = "test"
        gateway.pending_course = None
        gateway.course_published_fingerprint = None
        gateway.pending_control_actions = []
        gateway._pending_run_starts = []
        gateway._published_run_starts = []
        gateway.flush_commands()
        self.assertEqual([item[0] for item in events], ["course"])
        self.assertEqual(gateway.pending_control_actions[-1]["state"], "BLOCKED_COURSE_READY_ACK")

        status = {
            "schema_version": "twave-mission-status-v2", "timestamp": "2026-11-05T00:00:00Z",
            "fsm_state": "WAIT_RUN_START", "run_id": None,
            "course": {"course_id": "RX2026-A", "fingerprint": self.client.course_fingerprint,
                       "fsm_accepted": True, "applied": True},
            "safety": {}, "vehicles": {}, "legacy": {},
        }
        gateway._on_fsm_status(json.dumps(status))
        self.assertEqual([item[0] for item in events], ["course", "run_start"])
        self.assertEqual(gateway.pending_control_actions[-1]["state"], "RUNSTART_PUBLISHED_UNCONFIRMED")
        status["run_start"] = {
            "run_id": 42, "official_command_seq": 1,
            "command_id": "robocommand:42:1:run-start",
            "accepted": True, "application_state": "APPLIED",
        }
        gateway._on_fsm_status(json.dumps(status))
        self.assertEqual([item[0] for item in events], ["course", "run_start"])
        self.assertEqual(gateway.pending_control_actions[-1]["state"], "RUNNING")
        self.assertEqual(gateway.startup_state, "RUNNING")

    def test_old_or_unapplied_fsm_course_ack_does_not_release_run_start(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.queue_course_sync()
        self.client._accept_command(rx_commands_pb2.RxCommand(
            team_id="TONG", seq=1,
            run_start=rx_commands_pb2.RunStart(declaration_seq=self.client.declaration_seq, run_id=42),
        ))
        events = []
        gateway = OcsGateway.__new__(OcsGateway)
        gateway.ocs = self.client
        gateway.ros2 = types.SimpleNamespace(
            available=True, publish_course=lambda payload: events.append(("course", payload)) or True,
            publish_action=lambda action: events.append(("run_start", action)) or (True, None),
        )
        gateway._start_lock = threading.RLock()
        gateway._clock = time.monotonic
        gateway.startup_state = "DECLARED"
        gateway.startup_reason = "test"
        gateway.pending_course = None
        gateway.course_published_fingerprint = None
        gateway.pending_control_actions = []
        gateway._pending_run_starts = []
        gateway._published_run_starts = []
        gateway.flush_commands()
        gateway._on_fsm_status(json.dumps({
            "schema_version": "twave-mission-status-v2", "timestamp": "2026-11-05T00:00:00Z",
            "fsm_state": "WAIT_RUN_START", "run_id": None,
            "course": {"course_id": "RX2026-A", "fingerprint": "old-fingerprint",
                       "fsm_accepted": True, "applied": True},
            "safety": {}, "vehicles": {}, "legacy": {},
        }))
        self.assertEqual([item[0] for item in events], ["course"])
        self.assertEqual(gateway.pending_control_actions[-1]["state"], "BLOCKED_COURSE_READY_ACK")

    def test_pending_run_start_expires_without_course_ready_ack(self) -> None:
        payload = make_payload(course_id="RX2026-A", pinger_freq_hz=27000,
                               corners=[(1, 2), (1, 3), (2, 3), (1, 2)], source_sent_at=None)
        course_fingerprint = fingerprint(payload)
        action = {"kind": "internal_command", "vehicle_id": "T-Wave", "command": "RUN_START",
                  "run_id": 42, "command_seq": 1, "course_fingerprint": course_fingerprint}
        now = [0.0]
        gateway = OcsGateway.__new__(OcsGateway)
        gateway.ocs = types.SimpleNamespace(
            mission_coordinator="T-Wave", drain_internal_actions=lambda: [action],
            course_fingerprint=course_fingerprint, is_current_course_ready=lambda *_args: False,
        )
        gateway.ros2 = types.SimpleNamespace(available=True, publish_course=lambda _payload: True,
                                             publish_action=lambda _action: (True, None))
        gateway._start_lock = threading.RLock()
        gateway._clock = lambda: now[0]
        gateway.startup_state = "COURSE_READY"
        gateway.startup_reason = "test"
        gateway.pending_course = None
        gateway.course_published_fingerprint = course_fingerprint
        gateway.pending_control_actions = []
        gateway._pending_run_starts = []
        gateway._published_run_starts = []
        gateway.flush_commands()
        now[0] = 6.0
        gateway.ocs.drain_internal_actions = lambda: []
        gateway.flush_commands()
        self.assertEqual(gateway.pending_control_actions[-1]["state"], "BLOCKED_RUNSTART_TIMEOUT")
        self.assertEqual(gateway.startup_state, "BLOCKED")

    def test_uav_only_run_start_never_uses_twave_fsm_route_without_orin_contract(self) -> None:
        action = {"kind": "internal_command", "vehicle_id": "T-Wave", "command": "RUN_START",
                  "run_id": 42, "command_seq": 1, "course_fingerprint": "current"}
        gateway = OcsGateway.__new__(OcsGateway)
        gateway.ocs = types.SimpleNamespace(
            mission_coordinator="T-Wave", drain_internal_actions=lambda: [action],
            course_fingerprint="current", is_current_course_ready=lambda *_args: True,
        )
        gateway.ros2 = types.SimpleNamespace(available=True, publish_course=lambda _payload: True,
                                             publish_action=lambda _action: self.fail("must not publish"))
        gateway._start_lock = threading.RLock()
        gateway._clock = time.monotonic
        gateway.startup_state = "COURSE_READY"
        gateway.startup_reason = "test"
        gateway.pending_course = None
        gateway.course_published_fingerprint = "current"
        gateway.pending_control_actions = []
        gateway._pending_run_starts = []
        gateway._published_run_starts = []
        from operation_mode import VehicleMode
        gateway.vehicle_mode = VehicleMode.UAV_ONLY
        gateway.flush_commands()
        self.assertEqual(gateway.pending_control_actions[-1]["state"], "BLOCKED_UAV_TASK_RECEIVER_UNAVAILABLE")

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
                "readiness_event_id": "assist-2:readiness", "dry_run": False,
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
        course.sent_at.seconds = 1
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

    def test_uav_prefixed_declaration_enforces_fence_height_and_pilot(self) -> None:
        valid = {
            "task_tiers": ("none",) * 4,
            "uav_geofence": [(1.0, 2.0), (1.0, 3.0), (2.0, 3.0), (1.0, 2.0)],
            "uav_geofence_max_altitude_hae_m": 40.0,
            "uav_pilot_callsign": "TEST-PILOT",
        }
        invalid = (
            ({"uav_geofence": []}, "non-empty uav_geofence"),
            ({"uav_geofence_max_altitude_hae_m": None}, "uav_geofence_max_altitude"),
            ({"uav_geofence_max_altitude_hae_m": 51.0}, "height gate"),
            ({"uav_pilot_callsign": " "}, "uav_pilot_callsign"),
        )
        for override, reason in invalid:
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, reason):
                    self._publish_declaration(["UAV1"], **(valid | override))
                self.assertEqual(self.published, [])
                self.assertIsNone(self.client.declaration_seq)
        self._publish_declaration(["UAV1"], **valid)
        declaration = self.published[-1][1].run_declaration
        self.assertEqual(list(declaration.vehicle_ids), ["UAV1"])
        self.assertEqual(declaration.uav_geofence_max_altitude_hae_m, 40.0)
        self.assertEqual(declaration.uav_pilot_callsign, "TEST-PILOT")
        self.assertEqual(list(declaration.uav_geofence)[0], list(declaration.uav_geofence)[-1])

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

    def test_cached_heartbeat_preserves_uav_registration_without_affecting_usv(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.run_id = 42
        sent_at = int(time.time() * 1000)

        def heartbeat(vehicle_id, payload, message_id):
            return {
                "kind": "heartbeat", "vehicle_id": vehicle_id, "source": vehicle_id,
                "run_id": 42, "message_id": message_id, "sent_at_unix_ms": sent_at,
                "payload": payload,
            }

        common = {
            "source_mode": "simulation", "state": "AUTO", "speed_mps": 3.0,
            "heading_deg": 90.0, "roll_deg": 1.0, "pitch_deg": 2.0,
            "position": {
                "frame_id": "wgs84", "latitude_deg": 1.2,
                "longitude_deg": 103.8, "altitude_hae_m": 12.0,
            },
            "health": {"fcu_connected": True, "simulator": True},
        }
        self.client.accept_vehicle_envelope(heartbeat("T-Sky", {
            **common, "vehicle_type": "uav", "flight_phase": "airborne",
            "uav_registration": "CAAS-CACHED-001",
        }, "sky-cached-registration"))
        self.client.accept_vehicle_envelope(heartbeat("T-Wave", {
            **common, "vehicle_type": "usv", "current_task": "TASK_NONE",
        }, "wave-no-registration"))

        self.assertEqual(self.client.publish_cached_heartbeats(), 2)
        reports = {message.vehicle_id: message for _topic, message in self.published[1:]}
        decoded_sky = rx_reports_pb2.RxReport()
        decoded_sky.ParseFromString(reports["T-Sky"].SerializeToString())
        self.assertEqual(reports["T-Sky"].heartbeat.uav_registration, "CAAS-CACHED-001")
        self.assertEqual(decoded_sky.heartbeat.uav_registration, "CAAS-CACHED-001")
        self.assertEqual(reports["T-Wave"].heartbeat.uav_registration, "")


    def test_fsm_dry_run_readiness_cannot_reach_official_broker(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.run_id = 42
        initial = len(self.published)
        self.client.accept_fsm_task_report(json.dumps({
            "run_id": 42, "vehicle": "uav", "task": "TASK4",
            "official_report": {"type": "readiness", "vehicle_id": "uav",
                                "command_seq": 9, "dry_run": True},
        }))
        self.assertEqual(len(self.published), initial)
        self.assertEqual(self.client.runtime_events[-1]["event"], "dry_run_readiness_blocked")

    def test_unconfirmed_and_wrong_run_task4_reports_do_not_reach_rbc(self) -> None:
        self.client.publish_run_declaration(["T-Sky", "T-Wave"])
        self.client.run_id = 42
        initial = len(self.published)
        report = {"type": "incident_ack", "vehicle_id": "usv", "command_seq": 9}
        self.client.accept_fsm_task_report(json.dumps({
            "run_id": 42, "vehicle": "usv", "official_report": report,
            "accepted": True,
        }))
        self.assertEqual(len(self.published), initial)
        self.assertEqual(self.client.runtime_events[-1]["event"], "unconfirmed_incident_ack_blocked")
        self.client.accept_fsm_task_report(json.dumps({
            "run_id": 41, "vehicle": "usv", "official_report": report,
            "accepted": True, "ack_scope": "fsm",
        }))
        self.assertEqual(len(self.published), initial)
        self.assertEqual(self.client.runtime_events[-1]["event"], "task4_cross_run_report_blocked")



if __name__ == "__main__":
    unittest.main()
