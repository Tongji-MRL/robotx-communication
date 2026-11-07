"""Direct ROS input contract tests using isolated fake rclpy modules, never DDS."""
from enum import Enum
import sys
import threading
import types
import unittest
from unittest.mock import patch

from uav_ground_validation import Ros2StatusInput, STATUS_TOPIC, UAV_GEOFENCE_READBACK_TOPIC


class FakeRos:
    def __init__(self, *, fail_node=False, fail_spin=False):
        self.contexts = []
        self.nodes = []
        self.executors = []
        self.spin_entered = threading.Event()
        owner = self

        class Context:
            def __init__(self):
                self.live = False
                self.closed = False
                owner.contexts.append(self)

            def ok(self):
                return self.live

            def init(self, args=None):
                self.live = True

            def shutdown(self):
                self.live = False
                self.closed = True

            def try_shutdown(self):
                self.shutdown()

        class Node:
            def __init__(self, name, *, context=None, **kwargs):
                if fail_node:
                    raise RuntimeError("node initialization failed")
                self.name, self.context = name, context
                self.subscriptions = []
                self.destroyed = False
                owner.nodes.append(self)

            def create_subscription(self, message_type, topic, callback, qos):
                subscription = types.SimpleNamespace(message_type=message_type, topic=topic,
                                                     callback=callback, qos=qos)
                self.subscriptions.append(subscription)
                return subscription

            def create_publisher(self, *args, **kwargs):
                raise AssertionError("The ground ROS adapter must not create any publisher")

            def destroy_node(self):
                self.destroyed = True

        class SingleThreadedExecutor:
            def __init__(self, *, context=None):
                self.context = context
                self.nodes = []
                self.stopped = threading.Event()
                owner.executors.append(self)

            def add_node(self, node):
                self.nodes.append(node)

            def remove_node(self, node):
                self.nodes.remove(node)

            def spin(self):
                owner.spin_entered.set()
                if fail_spin:
                    raise RuntimeError("DDS executor failed")
                self.stopped.wait(5)

            def spin_once(self, timeout_sec=None):
                owner.spin_entered.set()
                if fail_spin:
                    raise RuntimeError("DDS executor failed")
                self.stopped.wait(min(timeout_sec or .01, .01))

            def shutdown(self, timeout_sec=None, **kwargs):
                self.stopped.set()
                return True

        class ReliabilityPolicy(Enum):
            RELIABLE = 1
            BEST_EFFORT = 2

        class DurabilityPolicy(Enum):
            VOLATILE = 1
            TRANSIENT_LOCAL = 2

        class HistoryPolicy(Enum):
            KEEP_LAST = 1
            KEEP_ALL = 2

        class QoSProfile:
            def __init__(self, *, depth, reliability, durability,
                         history=HistoryPolicy.KEEP_LAST):
                self.depth = depth
                self.reliability = reliability
                self.durability = durability
                self.history = history

        class String:
            def __init__(self, data=""):
                self.data = data

        def init(args=None, *, context=None, **kwargs):
            context.live = True

        def shutdown(*, context=None, **kwargs):
            context.shutdown()

        def module(name, **symbols):
            result = types.ModuleType(name)
            result.__dict__.update(symbols)
            return result

        self.modules = {
            "rclpy": module("rclpy", init=init, shutdown=shutdown,
                            ok=lambda *, context=None: context.ok()),
            "rclpy.context": module("rclpy.context", Context=Context),
            "rclpy.node": module("rclpy.node", Node=Node),
            "rclpy.executors": module("rclpy.executors", SingleThreadedExecutor=SingleThreadedExecutor,
                                      ExternalShutdownException=type("ExternalShutdownException", (Exception,), {})),
            "rclpy.qos": module("rclpy.qos", QoSProfile=QoSProfile,
                                ReliabilityPolicy=ReliabilityPolicy, DurabilityPolicy=DurabilityPolicy,
                                HistoryPolicy=HistoryPolicy),
            "std_msgs": module("std_msgs"),
            "std_msgs.msg": module("std_msgs.msg", String=String),
        }
        self.String = String
        self.ReliabilityPolicy = ReliabilityPolicy
        self.DurabilityPolicy = DurabilityPolicy


class Ros2GroundInputTests(unittest.TestCase):
    def session(self):
        self.now = 10.0
        self.received = []
        session = types.SimpleNamespace(telemetry_available=False, clock=lambda: self.now)
        session.on_status = lambda raw, **kwargs: self.received.append((raw, kwargs))
        session.event = lambda *_args, **_kwargs: None

        def unavailable():
            session.telemetry_available = False

        session.on_telemetry_unavailable = unavailable
        return session

    def test_exact_string_subscription_qos_private_context_and_read_only_shutdown(self):
        ros, session = FakeRos(), self.session()
        with patch.dict(sys.modules, ros.modules):
            source = Ros2StatusInput(session)
            try:
                source.connect()
                self.assertTrue(ros.spin_entered.wait(1))
                self.assertTrue(session.telemetry_available)
                self.assertEqual(len(ros.nodes), 1)
                node = ros.nodes[0]
                self.assertEqual(len(node.subscriptions), 2)
                subscription = node.subscriptions[0]
                self.assertEqual(subscription.topic, "/tongji_mrl/tsky/uav_status")
                self.assertIs(subscription.message_type, ros.String)
                self.assertEqual(subscription.qos.depth, 10)
                self.assertEqual(subscription.qos.reliability, ros.ReliabilityPolicy.RELIABLE)
                self.assertEqual(subscription.qos.durability, ros.DurabilityPolicy.VOLATILE)
                readback = node.subscriptions[1]
                self.assertEqual(readback.topic, UAV_GEOFENCE_READBACK_TOPIC)
                self.assertIs(readback.message_type, ros.String)
                self.assertEqual(readback.qos.depth, 10)
                self.assertEqual(readback.qos.reliability, ros.ReliabilityPolicy.RELIABLE)
                self.assertEqual(readback.qos.durability, ros.DurabilityPolicy.VOLATILE)
                self.assertIs(node.context, ros.contexts[0])
                self.assertIs(ros.executors[0].context, ros.contexts[0])
            finally:
                source.close()
            self.assertFalse(session.telemetry_available)
            self.assertTrue(ros.nodes[0].destroyed)
            self.assertTrue(ros.executors[0].stopped.is_set())
            self.assertTrue(ros.contexts[0].closed)

    def test_callback_queues_exact_data_and_keeps_original_receive_time(self):
        ros, session = FakeRos(), self.session()
        with patch.dict(sys.modules, ros.modules):
            source = Ros2StatusInput(session)
            try:
                source.connect()
                subscription = ros.nodes[0].subscriptions[0]
                payload = '{"vehicle_id":"UAV1","test":"unchanged ROS payload"}'
                subscription.callback(ros.String(payload))
                self.assertEqual(self.received, [], "Background DDS callback must not publish to RoboCommand")
                self.now = 12.0
                source.pump()
                self.assertEqual(self.received, [(payload, {"received_monotonic": 10.0})])
            finally:
                source.close()

    def test_missing_ros_environment_is_an_explicit_startup_error(self):
        session = self.session()
        with patch.dict(sys.modules, {"rclpy": None}):
            source = Ros2StatusInput(session)
            try:
                with self.assertRaisesRegex(RuntimeError, "ROS|rclpy"):
                    source.connect()
                self.assertFalse(session.telemetry_available)
            finally:
                source.close()

    def test_close_after_initialization_failure_shuts_down_its_own_context(self):
        ros, session = FakeRos(fail_node=True), self.session()
        with patch.dict(sys.modules, ros.modules):
            source = Ros2StatusInput(session)
            try:
                with self.assertRaises(RuntimeError):
                    source.connect()
                self.assertFalse(session.telemetry_available)
            finally:
                source.close()
            self.assertTrue(ros.contexts[0].closed)

    def test_executor_failure_disables_telemetry_and_surfaces_on_main_thread(self):
        ros, session = FakeRos(fail_spin=True), self.session()
        with patch.dict(sys.modules, ros.modules):
            source = Ros2StatusInput(session)
            try:
                source.connect()
                self.assertTrue(ros.spin_entered.wait(1))
                source.thread.join(1)
                with self.assertRaises(RuntimeError):
                    source.pump()
                self.assertFalse(session.telemetry_available)
            finally:
                source.close()

    def test_overflow_disables_telemetry_instead_of_replaying_old_queue(self):
        ros, session = FakeRos(), self.session()
        with patch.dict(sys.modules, ros.modules):
            source = Ros2StatusInput(session)
            try:
                source.connect()
                for number in range(257):
                    ros.nodes[0].subscriptions[0].callback(ros.String(str(number)))
                with self.assertRaisesRegex(RuntimeError, "overflow"):
                    source.pump()
                self.assertFalse(session.telemetry_available)
                self.assertEqual(self.received, [])
            finally:
                source.close()


if __name__ == "__main__":
    unittest.main()
