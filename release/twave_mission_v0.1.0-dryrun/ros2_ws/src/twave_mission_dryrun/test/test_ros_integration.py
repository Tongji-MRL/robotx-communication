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
        from twave_mission_dryrun.mission_coordinator_node import MissionCoordinatorNode
        from twave_mission_dryrun.protocol import encode, envelope
        self.base, self.encode, self.envelope = BASE, encode, envelope
        rclpy.init()
        self.executor = MultiThreadedExecutor()
        self.mission, self.fake, self.probe = MissionCoordinatorNode(), FakeUSVExecutor(), Node("twave_dryrun_test_probe")
        self.commands = []
        self.probe.create_subscription(String, f"{BASE}/usv_command", lambda m: self.commands.append(json.loads(m.data)), 10)
        self.command_pub = self.probe.create_publisher(String, f"{BASE}/command_in", 10)
        self.test_pub = self.probe.create_publisher(String, f"{BASE}/usv_test_in", 10)
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

    def test_ack_does_not_complete_task_and_explicit_event_advances(self):
        self._publish(self.command_pub, self.envelope(run_id=942, command_id="run-942", command="RUN_START", parameters={}))
        self.assertTrue(any(item["task"] == "TASK1" for item in self.commands))
        self.assertFalse(any(item["task"] == "TASK3" for item in self.commands))
        self._publish(self.test_pub, {"dry_run": True, "kind": "complete", "run_id": 942, "task": "TASK1", "event_id": "finish-1"})
        self.assertTrue(any(item["task"] == "TASK3" for item in self.commands))
