import json
import threading
import unittest
from types import SimpleNamespace

from ocs_gateway import OcsGateway, Ros2MissionLink


class _Publisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class _Node:
    def __init__(self):
        self.uav_geofence_pub = _Publisher()

    def get_topic_names_and_types(self):
        return []


class GatewayGeofenceTests(unittest.TestCase):
    @staticmethod
    def _readback_gateway():
        gateway = OcsGateway.__new__(OcsGateway)
        gateway._start_lock = threading.RLock()
        gateway.startup_state = "GEOFENCE_PUBLISHED_FCU_UNVERIFIED"
        gateway.startup_reason = "test"
        gateway._expected_uav_geofence = ((1.2, 103.8), (1.3, 103.8), (1.2, 103.8), (1.2, 103.8))
        gateway._expected_uav_geofence_max_altitude_hae_m = 40.0
        gateway._expected_uav_geofence_course_fingerprint = "course-1"
        gateway._geofence_readback_deadline = 10.0
        gateway._clock = lambda: 1.0
        gateway.ocs = type("Ocs", (), {"course_fingerprint": "course-1"})()
        gateway._uav_geofence_height_verified = False
        gateway._uav_auto_declaration = None
        gateway._uav_auto_declaration_course_fingerprint = None
        return gateway

    def test_ros_link_publishes_only_json_coordinate_array(self):
        link = Ros2MissionLink.__new__(Ros2MissionLink)
        link.available = True
        link.error = None
        link._node = _Node()
        link._string = lambda data: SimpleNamespace(data=data)
        published, reason = link.publish_uav_geofence(
            ((1.2, 103.8), (1.3, 103.8), (1.2, 103.8), (1.2, 103.8)))
        self.assertTrue(published, reason)
        message = link._node.uav_geofence_pub.messages[0]
        self.assertEqual(message.data, "[[1.2,103.8],[1.3,103.8],[1.2,103.8],[1.2,103.8]]")
        self.assertEqual(json.loads(message.data)[0], [1.2, 103.8])

    def test_ros_link_rejects_open_fence_without_publishing(self):
        link = Ros2MissionLink.__new__(Ros2MissionLink)
        link.available = True
        link.error = None
        link._node = _Node()
        published, reason = link.publish_uav_geofence(
            ((1.2, 103.8), (1.3, 103.8), (1.2, 103.9), (1.3, 103.9)))
        self.assertFalse(published)
        self.assertIn("closed", reason)
        self.assertEqual(link._node.uav_geofence_pub.messages, [])

    def test_matching_echo_readback_never_verifies_fcu_application(self):
        gateway = self._readback_gateway()
        gateway._on_uav_geofence_readback(
            '{"points":[[1.2,103.8],[1.3,103.8],[1.2,103.8],[1.2,103.8]],"max_altitude_m":40.0}'
        )
        self.assertEqual(gateway.startup_state, "FCU_GEOFENCE_UNVERIFIED")
        self.assertFalse(gateway._uav_geofence_height_verified)

    def test_mismatched_readback_is_blocked(self):
        gateway = self._readback_gateway()
        gateway._on_uav_geofence_readback(
            '{"points":[[1.2,103.8],[1.31,103.8],[1.2,103.8],[1.2,103.8]],"max_altitude_m":40.0}'
        )
        self.assertEqual(gateway.startup_state, "GEOFENCE_BLOCKED")

    def test_matching_echo_readback_never_auto_declares(self):
        gateway = self._readback_gateway()
        declared = []
        gateway._uav_auto_declaration = {"vehicle_ids": ["T-Sky"]}
        gateway.publish_declaration = lambda **kwargs: declared.append(kwargs)
        raw = '{"points":[[1.2,103.8],[1.3,103.8],[1.2,103.8],[1.2,103.8]],"max_altitude_m":40.0}'
        gateway._on_uav_geofence_readback(raw)
        gateway._on_uav_geofence_readback(raw)
        self.assertEqual(declared, [])

    def test_expired_or_course_changed_readback_stays_blocked(self):
        raw = '{"points":[[1.2,103.8],[1.3,103.8],[1.2,103.8],[1.2,103.8]],"max_altitude_m":40.0}'
        expired = self._readback_gateway()
        expired._clock = lambda: 11.0
        expired._on_uav_geofence_readback(raw)
        self.assertEqual(expired.startup_state, "GEOFENCE_BLOCKED")

        changed = self._readback_gateway()
        changed.ocs.course_fingerprint = "course-2"
        changed._on_uav_geofence_readback(raw)
        self.assertEqual(changed.startup_state, "GEOFENCE_BLOCKED")
