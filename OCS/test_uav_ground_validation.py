"""Ground-validation behavior tests using real protobuf serialization, no devices."""
import copy
import json
import types
from unittest.mock import Mock
import unittest

from uav_ground_validation import GroundOcsClient, GroundValidationSession, build_ground_heartbeat
from uav_status import normalize_uav_status
import common_pb2
from robotx import rx_commands_pb2, rx_common_pb2, rx_course_pb2, rx_reports_pb2, rx_requests_pb2


def ground_config():
    return {
        "team_id": "TONG",
        "robocommand": {"host": "127.0.0.1", "port": 1883},
        "vehicles": {"uav": {"vehicle_id": "UAV1", "source_vehicle_id": "UAV1",
                              "uav_registration": "TEST-REGISTRATION"}},
        "run_declaration": {
            "task_tiers": {"task1": "none", "task2": "none", "task3": "none", "task4": "none"},
            "uav_geofence": [], "uav_geofence_mode": "auto_course",
            "uav_geofence_margin_m": 2.0,
            "uav_geofence_max_altitude_hae_m": 40.0,
            "uav_geofence_altitude_limit_hae_m": 50.0,
            "uav_pilot_callsign": "TEST-PILOT",
        },
    }


def uav_status(**changes):
    value = {
        "vehicle_id": "UAV1", "vehicle_type": "uav", "state": "MANUAL",
        "flight_phase": "GROUNDED", "position": {"latitude": 1.2805, "longitude": 103.8505},
        "altitude_hae_m": 12.5, "spd_mps": 0.15, "heading_deg": 178.0,
    }
    value.update(changes)
    return value


def course_message(course_id="GROUND-TEST", stamp=1):
    course = rx_course_pb2.RxCourse(course_id=course_id, pinger_freq_hz=27000)
    course.sent_at.seconds = stamp
    for latitude, longitude in ((1.2800, 103.8500), (1.2800, 103.8520),
                                 (1.2820, 103.8520), (1.2820, 103.8500), (1.2800, 103.8500)):
        course.corners.add(latitude=latitude, longitude=longitude)
    return course


class GroundValidationTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.wall = 1_800_000_000.0
        self.sent = []
        self.events = []
        self.client = GroundOcsClient("127.0.0.1", 1883, team_id="TONG")

        def publish(topic, message):
            # Decode the wire payload rather than retaining a mutable object reference.
            decoded = type(message)()
            decoded.ParseFromString(message.SerializeToString())
            self.sent.append((topic, decoded))
            return len(self.sent)

        self.client._publish = publish
        self.client.connected = True
        self.session = GroundValidationSession(
            ground_config(), ocs=self.client, clock=lambda: self.now,
            wall_clock=lambda: self.wall, emit=lambda *args, **kwargs: self.events.append((args, kwargs)),
        )
        self.session.telemetry_available = True

    def receive_course(self, course=None):
        value = course or course_message()
        self.client._on_message(None, None, types.SimpleNamespace(
            topic="robocommand/robotx/course", payload=value.SerializeToString(), retain=True))

    def receive_start(self, declaration_seq=None, run_id=42, seq=1):
        message = rx_commands_pb2.RxCommand(
            team_id="TONG", seq=seq,
            run_start=rx_commands_pb2.RunStart(
                declaration_seq=self.client.declaration_seq if declaration_seq is None else declaration_seq,
                run_id=run_id))
        self.client._on_message(None, None, types.SimpleNamespace(
            topic=self.client.command_topic, payload=message.SerializeToString(), retain=False))

    def reports(self):
        return [message for _, message in self.sent if isinstance(message, rx_reports_pb2.RxReport)]

    def declarations(self):
        return [message for _, message in self.sent if isinstance(message, rx_requests_pb2.RxRequest)]

    def start(self, status=None):
        self.receive_course()
        self.assertTrue(self.session.on_status(uav_status() if status is None else status))
        self.session.tick()

    def test_waits_for_valid_course_even_with_live_uav(self):
        self.session.on_status(uav_status())
        self.session.tick()
        self.assertEqual(self.sent, [])
        invalid = rx_course_pb2.RxCourse(course_id="BROKEN", pinger_freq_hz=27000)
        self.receive_course(invalid)
        self.session.tick()
        self.assertEqual(self.sent, [])

    def test_serialized_flow_declares_only_uav_then_reports_actual_ground_state(self):
        self.start()
        request = self.sent[0][1]
        self.assertIsInstance(request, rx_requests_pb2.RxRequest)
        self.assertEqual(self.sent[0][0], "robocommand/robotx/TONG/request")
        self.assertEqual(list(request.run_declaration.vehicle_ids), ["UAV1"])
        for number in range(1, 5):
            self.assertEqual(getattr(request.run_declaration, f"task{number}_tier"), common_pb2.TIER_NONE)
        declaration = request.run_declaration
        self.assertEqual(declaration.uav_pilot_callsign, "TEST-PILOT")
        self.assertEqual(declaration.uav_geofence_max_altitude_hae_m, 40.0)
        self.assertGreaterEqual(len(declaration.uav_geofence), 4)
        self.assertEqual(declaration.uav_geofence[0], declaration.uav_geofence[-1])
        report = self.reports()[0]
        self.assertEqual((report.team_id, report.vehicle_id, report.seq), ("TONG", "UAV1", 1))
        self.assertEqual(report.heartbeat.state, common_pb2.STATE_MANUAL)
        self.assertEqual(report.heartbeat.current_task, rx_common_pb2.TASK_NONE)
        self.assertEqual(report.heartbeat.vehicle_type, rx_common_pb2.TYPE_UAV)
        self.assertEqual(report.heartbeat.flight_phase, rx_common_pb2.FLIGHT_PHASE_GROUNDED)
        self.assertEqual(report.heartbeat.position.latitude, 1.2805)
        self.assertEqual(report.heartbeat.altitude_hae_m, 12.5)
        self.assertEqual(report.heartbeat.uav_registration, "TEST-REGISTRATION")
        self.assertEqual({topic for topic, _ in self.sent}, {
            "robocommand/robotx/TONG/request", "robocommand/robotx/TONG/UAV1/report"})

    def test_two_hz_cadence_and_one_declaration(self):
        self.start()
        self.now += .49
        self.session.tick()
        self.assertEqual(len(self.reports()), 1)
        self.now += .01
        self.session.tick()
        self.assertEqual([report.seq for report in self.reports()], [1, 2])
        self.now += .5
        self.session.tick()
        self.assertEqual([report.seq for report in self.reports()], [1, 2, 3])
        self.assertEqual(len(self.declarations()), 1)
        self.assertEqual(self.session.heartbeat_count, 3)

    def test_union_geofence_without_verified_uav_protocol_never_declares(self):
        config = ground_config()
        config["run_declaration"].update(
            uav_geofence_mode="auto_course_union", uav_geofence_margin_m=1.0)
        self.session = GroundValidationSession(
            config, ocs=self.client, clock=lambda: self.now,
            wall_clock=lambda: self.wall, emit=lambda *args, **kwargs: self.events.append((args, kwargs)),
        )
        self.session.telemetry_available = True
        self.receive_course()
        self.assertTrue(self.session.on_status(uav_status()))
        self.session.tick()
        self.assertEqual(self.declarations(), [])
        self.assertEqual(self.session._stage, "WAIT_UAV_VERIFICATION")
        self.assertTrue(any(args[0]["event"] == "UAV_GEOFENCE_BLOCKED"
                            for args, _ in self.events))

    def test_heartbeat_publish_is_nonblocking_and_run_declaration_waits_for_puback(self):
        client = GroundOcsClient("127.0.0.1", 1883, team_id="TONG")
        result = Mock(rc=0, mid=7)
        result.is_published.return_value = False
        result.wait_for_publish = Mock()
        client.client.publish = Mock(return_value=result)
        client._declared_vehicle_ids = {"UAV1"}
        heartbeat = build_ground_heartbeat(
            normalize_uav_status(uav_status(), source_vehicle_id="UAV1"),
            registration="TEST-REGISTRATION",
        )
        self.assertEqual(client._publish_vehicle_body("UAV1", "heartbeat", heartbeat), 7)
        result.wait_for_publish.assert_not_called()
        self.assertEqual(client.heartbeat_transport_status()["pending"], 1)
        client._on_publish(None, None, 7)
        self.assertEqual(client.heartbeat_transport_status()["confirmed"], 1)

    def test_legacy_external_id_maps_independent_ros_source_consistently(self):
        config = ground_config()
        config["vehicles"]["uav"].update(vehicle_id="T-Sky", source_vehicle_id="ROS-UAV-A")
        self.session = GroundValidationSession(
            config, ocs=self.client, clock=lambda: self.now, wall_clock=lambda: self.wall,
            emit=lambda *args, **kwargs: self.events.append((args, kwargs)),
        )
        self.session.telemetry_available = True
        self.assertFalse(self.session.on_status(uav_status(vehicle_id="T-Sky")))
        self.start(uav_status(vehicle_id="ROS-UAV-A"))
        self.assertEqual(self.session.latest_status["vehicle_id"], "T-Sky")
        self.assertEqual(self.session.latest_status["source_vehicle_id"], "ROS-UAV-A")
        self.assertEqual(list(self.declarations()[0].run_declaration.vehicle_ids), ["T-Sky"])
        self.assertEqual(self.reports()[0].vehicle_id, "T-Sky")
        self.assertEqual(self.sent[-1][0], "robocommand/robotx/TONG/T-Sky/report")
        self.assertTrue(all(args[0]["vehicle_id"] == "T-Sky" for args, _ in self.events))

    def test_external_id_must_be_legacy_or_topic_safe_uav_prefix(self):
        for value in ("T-Wave", "uav1", "UAV/a", "UAV+", "UAV#", " UAV1", "UAV1 ", "", None, 1):
            with self.subTest(value=value):
                config = ground_config()
                config["vehicles"]["uav"]["vehicle_id"] = value
                with self.assertRaisesRegex(ValueError, "ground vehicle_id"):
                    GroundValidationSession(config, ocs=self.client)
        for value in ("UAV1", "UAV-A", "UAV_02", "T-Sky"):
            with self.subTest(value=value):
                config = ground_config()
                config["vehicles"]["uav"]["vehicle_id"] = value
                session = GroundValidationSession(config, ocs=self.client)
                self.assertEqual(session.vehicle_id, value)

    def test_ground_uav1_rejects_invalid_height_before_any_publication(self):
        config = ground_config()
        config["run_declaration"]["uav_geofence_max_altitude_hae_m"] = 51.0
        self.session = GroundValidationSession(config, ocs=self.client)
        self.receive_course()
        with self.assertRaisesRegex(ValueError, "height gate"):
            self.session.tick()
        self.assertEqual(self.sent, [])

    def test_no_heartbeat_until_telemetry_arrives(self):
        self.receive_course()
        self.session.tick()
        self.assertEqual(self.reports(), [])
        self.assertTrue(self.session.on_status(uav_status(state="KILLED")))
        self.session.tick()
        self.assertEqual(self.reports()[-1].heartbeat.state, common_pb2.STATE_KILLED)

    def test_stale_uav_stops_reporting_until_fresh_update(self):
        self.start()
        self.now += 3.0
        self.session.tick()
        self.assertEqual(len(self.reports()), 1)
        self.session.on_status(uav_status(heading_deg=190.0))
        self.session.tick()
        self.assertEqual(len(self.reports()), 2)
        self.assertEqual(self.reports()[-1].heartbeat.heading_deg, 190.0)

    def test_rejects_simulated_wrong_identity_and_malformed_status(self):
        self.receive_course()
        invalid = [uav_status(source_mode="simulation"), uav_status(source_mode="TEST/SIMULATED"),
                   uav_status(simulation=True), uav_status(vehicle_id="ANOTHER-UAV"), "{bad json",
                   uav_status(position={"latitude": float("nan"), "longitude": 103.8})]
        for value in invalid:
            with self.subTest(value=value):
                self.assertFalse(self.session.on_status(value))
                self.session.tick()
                self.assertEqual(self.reports(), [])

    def test_invalid_update_cannot_refresh_old_sample(self):
        self.start()
        self.now += 2.9
        self.assertFalse(self.session.on_status(uav_status(vehicle_id="WRONG")))
        self.now += .1
        self.session.tick()
        self.assertEqual(len(self.reports()), 1)

    def test_supplied_stale_source_timestamp_is_rejected(self):
        self.receive_course()
        self.assertFalse(self.session.on_status(uav_status(timestamp_unix_ms=int((self.wall - 10) * 1000))))
        self.session.tick()
        self.assertEqual(self.reports(), [])

    def test_telemetry_unavailable_invalidates_status_without_redeclaring(self):
        self.start()
        self.session.on_telemetry_unavailable()
        self.now += .5
        self.session.tick()
        self.assertEqual(len(self.reports()), 1)
        self.session.telemetry_available = True
        self.session.tick()
        self.assertEqual(len(self.reports()), 1)
        self.session.on_status(uav_status())
        self.session.tick()
        self.assertEqual(len(self.reports()), 2)
        self.assertEqual(len(self.declarations()), 1)

    def test_matching_run_start_is_recorded_without_any_vehicle_command(self):
        self.start(uav_status(state="AUTO"))
        self.receive_start(declaration_seq=999)
        self.session.tick()
        self.assertIsNone(self.client.run_id)
        self.receive_start()
        self.session.tick()
        self.assertEqual(self.client.run_id, 42)
        self.assertEqual(self.client.drain_internal_actions(), [])
        self.now += .5
        self.session.tick()
        self.assertEqual(self.reports()[-1].heartbeat.current_task, rx_common_pb2.TASK_NONE)
        self.assertEqual(len(self.declarations()), 1)
        self.assertTrue(all(topic.endswith(("/request", "/UAV1/report")) for topic, _ in self.sent))

    def reconnect_official(self):
        transport = types.SimpleNamespace(subscribe=lambda *args, **kwargs: (0, 1))
        self.client._on_connect(transport, None, None, 0)

    def test_pre_run_reconnect_redeclares_only_after_course_and_needs_fresh_status(self):
        self.start()
        first_seq = self.declarations()[0].seq
        self.client._on_disconnect(None, None, None, 1)
        self.session.tick()
        self.reconnect_official()
        self.session.tick()
        self.assertEqual(len(self.declarations()), 1)
        self.assertEqual(len(self.reports()), 1)
        self.receive_course()
        self.session.tick()
        self.assertEqual([request.seq for request in self.declarations()], [first_seq, first_seq + 1])
        self.assertEqual(len(self.reports()), 1, "Telemetry cached before disconnect is invalid")
        self.session.on_status(uav_status())
        self.session.tick()
        self.assertEqual(len(self.reports()), 2)

    def test_active_run_reconnect_restores_course_and_telemetry_without_new_flight(self):
        self.start()
        self.receive_start()
        self.session.tick()
        self.client._on_disconnect(None, None, None, 1)
        self.session.tick()
        self.now += .5
        self.reconnect_official()
        self.session.on_status(uav_status())
        self.session.tick()
        self.assertEqual(len(self.reports()), 1, "A retained Course must be received again")
        self.receive_course()
        self.session.tick()
        self.assertEqual(len(self.declarations()), 1, "Reconnect must not create another MDF flight")
        self.assertEqual(self.client.run_id, 42)
        self.assertEqual([report.seq for report in self.reports()], [1, 2])

    def test_ambiguous_declaration_publish_failure_latches_and_prevents_heartbeat(self):
        self.receive_course()
        self.session.on_status(uav_status())
        original_publish = self.client._publish

        def fail(*args, **kwargs):
            raise TimeoutError("PUBACK not received")

        self.client._publish = fail
        with self.assertRaises((TimeoutError, RuntimeError)):
            self.session.tick()
        self.client._publish = original_publish
        with self.assertRaises(RuntimeError):
            self.session.tick()
        self.assertEqual(self.sent, [], "An uncertain declaration cannot silently resume or be retried")

    def test_ambiguous_heartbeat_publish_failure_stops_the_session(self):
        self.start()
        self.now += .5
        original_publish = self.client._publish

        def fail(*args, **kwargs):
            raise TimeoutError("PUBACK not received")

        self.client._publish = fail
        with self.assertRaises((TimeoutError, RuntimeError)):
            self.session.tick()
        self.client._publish = original_publish
        self.now += .5
        with self.assertRaises(RuntimeError):
            self.session.tick()
        self.assertEqual(len(self.reports()), 1)

    def test_ground_heartbeat_omits_missing_attitude_but_preserves_real_zero(self):
        normalized = normalize_uav_status(uav_status(), source_vehicle_id="UAV1")
        heartbeat = build_ground_heartbeat(normalized, registration="REG")
        self.assertFalse(heartbeat.HasField("roll_deg"))
        self.assertFalse(heartbeat.HasField("pitch_deg"))
        normalized = normalize_uav_status(uav_status(roll_deg=0.0, pitch_deg=-3.5), source_vehicle_id="UAV1")
        heartbeat = build_ground_heartbeat(normalized, registration="REG")
        self.assertTrue(heartbeat.HasField("roll_deg"))
        self.assertTrue(heartbeat.HasField("pitch_deg"))
        self.assertEqual((heartbeat.roll_deg, heartbeat.pitch_deg), (0.0, -3.5))

    def test_rejects_multi_vehicle_config(self):
        config = copy.deepcopy(ground_config())
        config["vehicles"]["usv"] = {"vehicle_id": "T-Wave"}
        with self.assertRaises(ValueError):
            GroundValidationSession(config, ocs=self.client)


if __name__ == "__main__":
    unittest.main()
