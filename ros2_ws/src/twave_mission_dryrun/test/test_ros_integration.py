"""Humble-only in-process integration test for the two dry-run ROS nodes."""

import json
import time
import unittest

try:
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
except ImportError:  # Windows deliberately has no rclpy.
    rclpy = None


@unittest.skipIf(rclpy is None, "ROS 2 Humble is required")
class RosIntegrationTests(unittest.TestCase):
    def setUp(self):
        from twave_mission_dryrun.fake_usv_executor import BASE, FakeUSVExecutor
        from twave_mission_dryrun.mission_coordinator_node import MISSION_BASE, MissionCoordinatorNode
        from twave_mission_dryrun.protocol import encode, envelope
        self.base, self.encode, self.envelope = BASE, encode, envelope
        rclpy.init()
        self.executor = MultiThreadedExecutor()
        self.mission, self.fake, self.probe = MissionCoordinatorNode(), FakeUSVExecutor(), Node("twave_dryrun_test_probe")
        self.commands = []
        self.statuses = []
        self.probe.create_subscription(String, f"{BASE}/usv_command", lambda m: self.commands.append(json.loads(m.data)), 10)
        self.probe.create_subscription(String, f"{MISSION_BASE}/status", lambda m: self.statuses.append(json.loads(m.data)), 10)
        self.command_pub = self.probe.create_publisher(String, f"{MISSION_BASE}/run_start", 10)
        self.test_pub = self.probe.create_publisher(String, f"{BASE}/usv_test_in", 10)
        self.twave_progress_pub = self.probe.create_publisher(String, "/tongji_mrl/twave/progress", 10)
        self.tsky_progress_pub = self.probe.create_publisher(String, "/tongji_mrl/tsky/progress", 10)
        for node in (self.mission, self.fake, self.probe):
            self.executor.add_node(node)

    def tearDown(self):
        for node in (self.mission, self.fake, self.probe):
            self.executor.remove_node(node); node.destroy_node()
        self.executor.shutdown(); rclpy.shutdown()

    def _publish(self, publisher, payload):
        msg = String(); msg.data = self.encode(payload); publisher.publish(msg)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=0.05)

    def _publish_bits(self, publisher, bits):
        msg = String(); msg.data = bits; publisher.publish(msg)
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=0.05)

    def test_ack_does_not_complete_task_and_explicit_event_advances(self):
        self._publish(self.command_pub, self.envelope(run_id=942, command_id="run-942", command="RUN_START", parameters={}))
        self.assertTrue(any(item["task"] == "TASK1" for item in self.commands))
        self.assertFalse(any(item["task"] == "TASK3" for item in self.commands))
        self._publish(self.test_pub, {"dry_run": True, "kind": "complete", "run_id": 942, "task": "TASK1", "event_id": "finish-1"})
        self.assertTrue(any(item["task"] == "TASK3" for item in self.commands))

    def test_vehicle_progress_is_aggregated_in_status(self):
        self._publish_bits(self.twave_progress_pub, "10100000000000")
        self._publish_bits(self.tsky_progress_pub, "00000000000000")
        self._publish(self.command_pub, self.envelope(run_id=943, command_id="run-943", command="RUN_START", parameters={}))
        vehicles = self.statuses[-1]["vehicles"]
        self.assertEqual(vehicles["T-Wave"]["status_bits"], "10100000000000")
        self.assertEqual(vehicles["T-Sky"]["status_bits"], "00000000000000")
