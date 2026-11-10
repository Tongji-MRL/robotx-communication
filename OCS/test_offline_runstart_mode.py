import os
import threading
import types
import unittest
from unittest.mock import patch

import ocs_gateway
from ocs_gateway import OcsGateway
from ocs_gateway import MISSION_TOPICS, Ros2MissionLink
from ocs_client import OcsClient
from operation_mode import VehicleMode
from robotx import rx_commands_pb2, rx_course_pb2


class OfflineRunStartModeTests(unittest.TestCase):
    def test_fake_rbc_to_ocs_to_isolated_ros2_receiver(self):
        """The test receiver is non-actuating and is never an Orin ACK."""
        client = OcsClient("127.0.0.1", 1883)
        client._publish = lambda _topic, _message: 1
        course = rx_course_pb2.RxCourse(course_id="OFFLINE", pinger_freq_hz=25000)
        for latitude, longitude in ((1.0, 2.0), (1.0, 2.1), (1.1, 2.1), (1.0, 2.0)):
            course.corners.add(latitude=latitude, longitude=longitude)
        client._accept_course(course)
        client.drain_internal_actions()
        client.publish_run_declaration(
            ["T-Sky"],
            uav_geofence=[(1.01, 2.01), (1.01, 2.09), (1.09, 2.09), (1.01, 2.01)],
            uav_geofence_max_altitude_hae_m=40.0,
            uav_pilot_callsign="TEST-PILOT",
        )
        # Fake RBC delivers a protobuf command into OCS; no broker is used.
        client._accept_command(rx_commands_pb2.RxCommand(
            team_id="TONG", seq=1,
            run_start=rx_commands_pb2.RunStart(
                declaration_seq=client.declaration_seq, run_id=41,
            ),
        ))
        action = client.drain_internal_actions()[-1]
        self.assertEqual((action["command"], action["run_id"]), ("RUN_START", 41))

        gateway = OcsGateway.__new__(OcsGateway)
        forwarded = []
        gateway.ocs = types.SimpleNamespace(mission_coordinator="T-Wave", drain_internal_actions=lambda: [action])
        gateway.ros2 = types.SimpleNamespace(
            publish_action=lambda _action: self.fail("real mission topic must not be used"),
            publish_offline_test_run_start=lambda got: (forwarded.append(got) is None, None),
        )
        gateway.vehicle_mode = VehicleMode.UAV_ONLY
        gateway.offline_test_mode = True
        gateway._start_lock = threading.RLock()
        gateway._clock = lambda: 1.0
        gateway.startup_state = "WAIT_COURSE"
        gateway.startup_reason = "test"
        gateway.pending_course = gateway.course_published_fingerprint = None
        gateway.pending_control_actions = gateway._pending_run_starts = gateway._published_run_starts = []
        gateway.flush_commands()
        self.assertEqual(forwarded, [action])

    def test_offline_receiver_requires_explicit_capability_and_single_endpoint(self):
        class Publisher:
            def __init__(self, count):
                self.count, self.messages = count, []
            def get_subscription_count(self):
                return self.count
            def publish(self, value):
                self.messages.append(value)

        class Node:
            def __init__(self, endpoints, publisher):
                self.endpoints, self.offline_test_run_start_pub = endpoints, publisher
            def get_subscriptions_info_by_topic(self, _topic):
                return self.endpoints

        link = Ros2MissionLink.__new__(Ros2MissionLink)
        publisher = Publisher(1)
        link.available = True
        link.error = None
        link._node = Node([object()], publisher)
        link._offline_test_receiver_token = "0123456789abcdef"
        link._offline_test_receiver_ready = False
        link._string = lambda value: value
        action = {"command": "RUN_START", "run_id": 9, "command_seq": 4,
                  "official_team_id": "TONG", "declaration_seq": 2}
        self.assertFalse(link.publish_offline_test_run_start(action)[0])
        link._accept_offline_test_receiver_ready(__import__("json").dumps({
            "kind": "offline_test_receiver_ready", "token": "0123456789abcdef",
            "read_only": True, "actuation": False, "topic": MISSION_TOPICS["offline_test_run_start"],
        }))
        self.assertTrue(link.publish_offline_test_run_start(action)[0])
        self.assertEqual(len(publisher.messages), 1)
        link._node.endpoints = [object(), object()]
        link._node.offline_test_run_start_pub.count = 2
        self.assertFalse(link.publish_offline_test_run_start(action)[0])

    def test_uav_offline_mode_forwards_only_to_test_receiver(self):
        gateway = OcsGateway.__new__(OcsGateway)
        action = {"kind": "internal_command", "vehicle_id": "T-Wave", "command": "RUN_START",
                  "run_id": 41, "command_seq": 7, "official_team_id": "TONG", "declaration_seq": 3}
        calls = []
        gateway.ocs = types.SimpleNamespace(mission_coordinator="T-Wave", drain_internal_actions=lambda: [action])
        gateway.ros2 = types.SimpleNamespace(
            publish_action=lambda _action: self.fail("normal mission topic must not be used"),
            publish_offline_test_run_start=lambda got: (calls.append(got) is None, None),
        )
        gateway.vehicle_mode = VehicleMode.UAV_ONLY
        gateway.offline_test_mode = True
        gateway._start_lock = threading.RLock()
        gateway._clock = lambda: 1.0
        gateway.startup_state = "WAIT_COURSE"
        gateway.startup_reason = "test"
        gateway.pending_course = None
        gateway.course_published_fingerprint = None
        gateway.pending_control_actions = []
        gateway._pending_run_starts = []
        gateway._published_run_starts = []
        gateway.flush_commands()
        self.assertEqual(calls, [action])
        self.assertEqual(gateway.pending_control_actions[-1]["state"], "OFFLINE_TEST_RUNSTART_FORWARDED")
        self.assertEqual(gateway.startup_state, "OFFLINE_TEST_RUNSTART_FORWARDED")

    def test_offline_cli_rejects_wrong_ros_environment(self):
        with patch.dict(os.environ, {"ROS_DOMAIN_ID": "63", "ROS_LOCALHOST_ONLY": "1"}, clear=False), \
             patch("sys.argv", ["ocs_gateway.py", "--offline-test-mode", "--vehicle-mode", "uav_only",
                                 "--official-broker", "127.0.0.1", "--internal-broker", "127.0.0.1",
                                 "--offline-test-receiver-token", "0123456789abcdef"]):
            with self.assertRaises(SystemExit) as raised:
                ocs_gateway.main()
        self.assertEqual(raised.exception.code, 2)
