import json
import unittest

from uav_geofence import (
    UAV_GEOFENCE_APPLY_TOPIC, UAV_GEOFENCE_READBACK_TOPIC, compare_geofence,
    parse_string_readback, serialize_geofence,
)


class UavGeofenceWireFormatTests(unittest.TestCase):
    def test_apply_topic_uses_confirmed_geofense_spelling(self):
        self.assertEqual(UAV_GEOFENCE_APPLY_TOPIC, "/tongji_mrl/tsky/uav_geofense_sub")
        self.assertEqual(UAV_GEOFENCE_READBACK_TOPIC, "/tongji_mrl/tsky/uav_geofense_pub")

    def test_serializes_latitude_longitude_pairs_as_a_json_array(self):
        payload = serialize_geofence(((1.2, 103.8), (1.3, 103.8), (1.2, 103.8), (1.2, 103.8)))
        self.assertEqual(payload, "[[1.2,103.8],[1.3,103.8],[1.2,103.8],[1.2,103.8]]")
        self.assertEqual(json.loads(payload)[0], [1.2, 103.8])

    def test_rejects_open_or_invalid_polygons(self):
        with self.assertRaisesRegex(ValueError, "closed"):
            serialize_geofence(((1.2, 103.8), (1.3, 103.8), (1.2, 103.9), (1.3, 103.9)))
        with self.assertRaisesRegex(ValueError, "latitude"):
            serialize_geofence(((91, 103.8), (1.3, 103.8), (1.2, 103.8), (91, 103.8)))

    def test_readback_requires_same_ordered_vertices_with_tolerance(self):
        expected = ((1.2, 103.8), (1.3, 103.8), (1.2, 103.8), (1.2, 103.8))
        actual = parse_string_readback("[[1.2000001,103.8],[1.3,103.8],[1.2,103.8],[1.2000001,103.8]]")
        compare_geofence(expected, actual)
        with self.assertRaisesRegex(ValueError, "vertex 1"):
            compare_geofence(expected, (actual[0], actual[2], actual[1], actual[0]))
