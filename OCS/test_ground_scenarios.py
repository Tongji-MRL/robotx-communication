"""Scenario wire/lifecycle checks with a fake clock, never aircraft or DDS."""
import copy
import math
import types
import unittest
from unittest.mock import patch

from test_uav_ground_validation import course_message, ground_config, uav_status
import uav_ground_validation as ground
from uav_ground_validation import GroundOcsClient, GroundValidationSession
from robotx import rx_commands_pb2, rx_reports_pb2, rx_requests_pb2


class ScenarioRig:
    def __init__(self, scenario="normal", *, config=None, **options):
        self.now = 1000.0
        self.wall = 1_800_000_000.0
        self.sent = []
        self.events = []
        config = ground_config() if config is None else config
        self.client = GroundOcsClient("127.0.0.1", 1883, team_id=config["team_id"])
        self.client.connected = True

        def capture(topic, message):
            self.sent.append((topic, type(message).FromString(message.SerializeToString())))
            return len(self.sent)

        self.client._publish = capture
        self.session = GroundValidationSession(
            config, ocs=self.client, scenario=scenario, clock=lambda: self.now,
            wall_clock=lambda: self.wall, emit=self.events.append, **options)
        self.session.telemetry_available = True

    def course(self, value=None):
        value = course_message() if value is None else value
        self.client._on_message(None, None, types.SimpleNamespace(
            topic="robocommand/robotx/course", payload=value.SerializeToString(), retain=True))

    def start(self, value=None, status=None):
        self.course(value)
        assert self.session.on_status(uav_status() if status is None else status)
        self.session.tick()

    def command(self, *, declaration_seq=None, retained=False):
        message = rx_commands_pb2.RxCommand(
            team_id=self.client.team_id, seq=1,
            run_start=rx_commands_pb2.RunStart(
                declaration_seq=self.client.declaration_seq if declaration_seq is None else declaration_seq,
                run_id=42))
        self.client._on_message(None, None, types.SimpleNamespace(
            topic=self.client.command_topic, payload=message.SerializeToString(), retain=retained))

    def reconnect(self):
        transport = types.SimpleNamespace(subscribe=lambda *a, **kw: (0, 1))
        self.client._on_connect(transport, None, None, 0)

    def requests(self):
        return [message for _, message in self.sent if isinstance(message, rx_requests_pb2.RxRequest)]

    def reports(self):
        return [message for _, message in self.sent if isinstance(message, rx_reports_pb2.RxReport)]


def course_with_northern_transit():
    course = course_message()
    for lat, lng in ((1.282, 103.850), (1.282, 103.852),
                     (1.285, 103.852), (1.285, 103.850), (1.282, 103.850)):
        course.uav_transit_area.add(latitude=lat, longitude=lng)
    return course


class GroundScenarioTests(unittest.TestCase):
    def rig(self, scenario="normal", **options):
        value = ScenarioRig(scenario, **options)
        self.addCleanup(value.client.close)
        return value

    def test_outside_changes_only_declared_fence_and_is_beyond_course_and_transit(self):
        course = course_with_northern_transit()
        normal, outside = self.rig(), self.rig("outside-course", outside_offset_m=25.0)
        actual = uav_status(state="KILLED", roll_deg=0.0, pitch_deg=-3.5)
        normal.start(course, actual)
        outside.start(course, actual)
        baseline = normal.requests()[0].run_declaration
        changed = outside.requests()[0].run_declaration
        allowed_max_lat = max(point.latitude for point in (*course.corners, *course.uav_transit_area))
        self.assertTrue(all(point.latitude > allowed_max_lat for point in changed.uav_geofence))
        self.assertEqual(changed.uav_geofence[0], changed.uav_geofence[-1])
        self.assertEqual(len(changed.uav_geofence), len(baseline.uav_geofence))
        shifts = [new.latitude - old.latitude
                  for old, new in zip(baseline.uav_geofence, changed.uav_geofence)]
        self.assertLess(max(shifts) - min(shifts), 1e-12)
        self.assertEqual([point.longitude for point in baseline.uav_geofence],
                         [point.longitude for point in changed.uav_geofence])
        normal_other, outside_other = copy.deepcopy(baseline), copy.deepcopy(changed)
        normal_other.ClearField("uav_geofence")
        outside_other.ClearField("uav_geofence")
        self.assertEqual(normal_other, outside_other)
        self.assertEqual(normal.reports()[0].heartbeat, outside.reports()[0].heartbeat,
                         "Declaration geometry must never move actual UAV telemetry")
        self.assertEqual(outside.reports()[0].heartbeat.position.latitude, actual["position"]["latitude"])

    def test_over_height_changes_only_declared_ceiling_and_preserves_real_heartbeat(self):
        normal, high = self.rig(), self.rig("over-height", test_max_altitude_hae=63.0)
        actual = uav_status(state="AUTO", altitude_hae_m=14.25, roll_deg=0.0, pitch_deg=-3.5)
        normal.start(status=actual)
        high.start(status=actual)
        baseline = copy.deepcopy(normal.requests()[0].run_declaration)
        changed = copy.deepcopy(high.requests()[0].run_declaration)
        self.assertEqual(changed.uav_geofence_max_altitude_hae_m, 63.0)
        self.assertEqual(baseline.uav_geofence_max_altitude_hae_m, 40.0)
        baseline.ClearField("uav_geofence_max_altitude_hae_m")
        changed.ClearField("uav_geofence_max_altitude_hae_m")
        self.assertEqual(baseline, changed)
        self.assertEqual(normal.reports()[0].heartbeat, high.reports()[0].heartbeat)
        self.assertEqual(high.reports()[0].heartbeat.altitude_hae_m, 14.25)

    def test_invalid_scenario_parameters_are_rejected(self):
        for scenario, options in (
            ("typo", {}),
            *(("outside-course", {"outside_offset_m": value})
              for value in (0, .1, 1.0, -1, math.nan, math.inf, -math.inf)),
            *(("over-height", {"test_max_altitude_hae": value})
              for value in (0, -1, 50, 49, math.nan, math.inf, -math.inf)),
        ):
            with self.subTest(scenario=scenario, options=options):
                with self.assertRaises(ValueError):
                    self.rig(scenario, **options)

    def test_team_id_must_be_safe_for_the_exact_request_and_command_topics(self):
        for team in ("", "TONG/a", "TONG+", "TONG#", " TONG", "TONG ", "TONG\n", None, 123):
            with self.subTest(team=team):
                config = ground_config()
                config["team_id"] = team
                with self.assertRaises(ValueError):
                    self.rig(config=config)

    def test_cli_rejects_mismatched_scenario_options_before_opening_ros(self):
        for argv in (
            ["--scenario", "typo"],
            ["--outside-offset-m", "20"],
            ["--test-max-altitude-hae", "60"],
            ["--scenario", "outside-course", "--test-max-altitude-hae", "60"],
            ["--scenario", "over-height", "--outside-offset-m", "20"],
        ):
            with self.subTest(argv=argv), patch.object(ground, "Ros2StatusInput") as ros:
                with self.assertRaises(SystemExit) as stopped:
                    ground.main(argv)
                self.assertEqual(stopped.exception.code, 2)
                ros.assert_not_called()

    def test_over_height_must_remain_over_limit_after_protobuf_float_rounding(self):
        try:
            rig = self.rig("over-height", test_max_altitude_hae=50.0000001)
            rig.start()
        except ValueError:
            return  # Rejecting an unrepresentable negative input is valid.
        self.assertGreater(rig.requests()[0].run_declaration.uav_geofence_max_altitude_hae_m, 50.0)

    def test_normal_reconnect_keeps_per_vehicle_report_sequence_monotonic(self):
        rig = self.rig()
        rig.start()
        rig.now += .5
        rig.session.tick()
        rig.client._on_disconnect(None, None, None, 1)
        rig.session.tick()
        rig.reconnect()
        rig.session.tick()
        rig.course()
        rig.session.tick()
        self.assertEqual(len(rig.reports()), 2, "Reconnect still needs fresh ROS telemetry")
        rig.session.on_status(uav_status())
        rig.session.tick()
        self.assertEqual([request.seq for request in rig.requests()], [1, 2])
        self.assertEqual([report.seq for report in rig.reports()], [1, 2, 3])

    def test_normal_course_update_keeps_per_vehicle_report_sequence_monotonic(self):
        rig = self.rig()
        rig.start()
        rig.now += .5
        rig.session.tick()
        rig.course(course_message(course_id="UPDATED-COURSE", stamp=2))
        rig.session.tick()
        self.assertEqual([request.seq for request in rig.requests()], [1, 2])
        self.assertEqual([report.seq for report in rig.reports()], [1, 2, 3])

    def test_negative_modes_require_official_uav_prefix(self):
        for scenario in ("outside-course", "over-height"):
            with self.subTest(scenario=scenario):
                config = ground_config()
                config["vehicles"]["uav"]["vehicle_id"] = "T-Sky"
                with self.assertRaises(ValueError):
                    self.rig(scenario, config=config)

    def test_all_scenarios_validate_baseline_ceiling_before_publishing(self):
        for scenario in ("normal", "outside-course", "over-height"):
            with self.subTest(scenario=scenario):
                config = ground_config()
                config["run_declaration"]["uav_geofence_max_altitude_hae_m"] = 51.0
                rig = self.rig(scenario, config=config)
                rig.course()
                with self.assertRaises(ValueError):
                    rig.session.tick()
                self.assertEqual(rig.sent, [])

    def test_all_scenarios_validate_baseline_fence_before_publishing(self):
        for scenario in ("normal", "outside-course", "over-height"):
            with self.subTest(scenario=scenario):
                config = ground_config()
                config["run_declaration"]["uav_geofence_mode"] = "manual"
                config["run_declaration"]["uav_geofence"] = [
                    {"latitude": lat, "longitude": lng}
                    for lat, lng in ((2.0, 103.85), (2.0, 103.86), (2.01, 103.86), (2.0, 103.85))]
                rig = self.rig(scenario, config=config)
                rig.course()
                with self.assertRaises(ValueError):
                    rig.session.tick()
                self.assertEqual(rig.sent, [])

    def test_negative_modes_wait_for_valid_course_and_real_fresh_telemetry(self):
        for scenario in ("outside-course", "over-height"):
            with self.subTest(scenario=scenario):
                rig = self.rig(scenario)
                rig.session.on_status(uav_status())
                rig.session.tick()
                self.assertEqual(rig.sent, [])
                invalid_course = course_message()
                invalid_course.ClearField("corners")
                rig.course(invalid_course)
                rig.session.tick()
                self.assertEqual(rig.sent, [])
                rig.course()
                rig.session.on_telemetry_unavailable()
                rig.session.tick()
                self.assertEqual(len(rig.requests()), 1)
                self.assertEqual(rig.reports(), [])
                rig.session.telemetry_available = True
                self.assertFalse(rig.session.on_status(uav_status(simulation=True)))
                rig.session.tick()
                self.assertEqual(rig.reports(), [])
                self.assertTrue(rig.session.on_status(uav_status(state="MANUAL")))
                rig.session.tick()
                self.assertEqual(len(rig.reports()), 1)

    def test_negative_modes_keep_receipt_freshness_and_two_hz_gates(self):
        for scenario in ("outside-course", "over-height"):
            with self.subTest(scenario=scenario):
                rig = self.rig(scenario)
                rig.start()
                rig.now += .49
                rig.session.tick()
                self.assertEqual(len(rig.reports()), 1)
                rig.now += .01
                rig.session.tick()
                self.assertEqual(len(rig.reports()), 2)
                rig.now += 2.5
                rig.session.tick()
                self.assertEqual(len(rig.reports()), 2, "Three-second-old data must stop")
                rig.session.on_status(uav_status(heading_deg=190.0), received_monotonic=rig.now - 3)
                rig.session.tick()
                self.assertEqual(len(rig.reports()), 2, "Queued DDS samples retain original age")
                rig.session.on_status(uav_status(heading_deg=191.0))
                rig.session.tick()
                self.assertEqual(len(rig.requests()), 1)
                self.assertEqual(len(rig.reports()), 3)
                self.assertEqual(rig.reports()[-1].heartbeat.heading_deg, 191.0)

    def test_negative_modes_reject_stale_source_time_and_invalid_updates(self):
        for scenario in ("outside-course", "over-height"):
            with self.subTest(scenario=scenario):
                rig = self.rig(scenario)
                rig.start()
                rig.now += .5
                self.assertFalse(rig.session.on_status(uav_status(
                    timestamp_unix_ms=int((rig.wall - 5) * 1000))))
                rig.session.tick()
                self.assertEqual(len(rig.reports()), 1)
                self.assertFalse(rig.session.on_status(uav_status(vehicle_id="WRONG")))
                rig.session.tick()
                self.assertEqual(len(rig.reports()), 1)

    def test_negative_matching_run_start_is_terminal_without_vehicle_commands(self):
        for scenario in ("outside-course", "over-height"):
            with self.subTest(scenario=scenario):
                rig = self.rig(scenario)
                rig.start(status=uav_status(state="AUTO"))
                count = len(rig.sent)
                rig.command()
                with self.assertRaises(RuntimeError):
                    rig.session.tick()
                rig.now += .5
                rig.session.on_status(uav_status(state="AUTO"))
                with self.assertRaises(RuntimeError):
                    rig.session.tick()
                self.assertEqual(len(rig.sent), count)
                self.assertEqual(rig.client.drain_internal_actions(), [])

    def test_negative_ignores_mismatched_and_retained_start(self):
        for scenario in ("outside-course", "over-height"):
            for retained, seq in ((False, 999), (True, None)):
                with self.subTest(scenario=scenario, retained=retained):
                    rig = self.rig(scenario)
                    rig.start()
                    rig.command(declaration_seq=seq, retained=retained)
                    rig.now += .5
                    rig.session.tick()
                    self.assertEqual(len(rig.reports()), 2)
                    self.assertIsNone(rig.client.run_id)
                    self.assertEqual(rig.client.drain_internal_actions(), [])

    def test_negative_post_publish_disconnect_is_terminal_without_redeclaration(self):
        for scenario in ("outside-course", "over-height"):
            with self.subTest(scenario=scenario):
                rig = self.rig(scenario)
                rig.start()
                count = len(rig.sent)
                rig.client._on_disconnect(None, None, None, 1)
                with self.assertRaises(RuntimeError):
                    rig.session.tick()
                rig.reconnect()
                rig.course()
                rig.session.on_status(uav_status())
                with self.assertRaises(RuntimeError):
                    rig.session.tick()
                self.assertEqual(len(rig.sent), count)

    def test_negative_disconnect_before_declaration_can_recover(self):
        for scenario in ("outside-course", "over-height"):
            with self.subTest(scenario=scenario):
                rig = self.rig(scenario)
                rig.client._on_disconnect(None, None, None, 1)
                rig.session.tick()
                rig.reconnect()
                rig.session.tick()
                self.assertEqual(rig.sent, [])
                rig.start()
                self.assertEqual(len(rig.requests()), 1)
                self.assertEqual(len(rig.reports()), 1)

    def test_negative_changed_course_after_publication_is_terminal(self):
        for scenario in ("outside-course", "over-height"):
            with self.subTest(scenario=scenario):
                rig = self.rig(scenario)
                rig.start()
                count = len(rig.sent)
                rig.course(course_message(course_id="CHANGED-COURSE", stamp=2))
                with self.assertRaises(RuntimeError):
                    rig.session.tick()
                self.assertEqual(len(rig.sent), count)

    def test_negative_publication_failure_stays_latched(self):
        for scenario in ("outside-course", "over-height"):
            with self.subTest(scenario=scenario):
                rig = self.rig(scenario)
                rig.course()
                rig.session.on_status(uav_status())
                capture = rig.client._publish

                def fail(*args, **kwargs):
                    raise TimeoutError("PUBACK not received")

                rig.client._publish = fail
                with self.assertRaises((TimeoutError, RuntimeError)):
                    rig.session.tick()
                rig.client._publish = capture
                with self.assertRaises(RuntimeError):
                    rig.session.tick()
                self.assertEqual(rig.sent, [])


if __name__ == "__main__":
    unittest.main()
