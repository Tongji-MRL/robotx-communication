import json
import math
import unittest

from ned_map_transform import (
    GpsOrigin,
    add_ned_offset,
    transform_semantic_map,
    uav_origin_in_usv_ned,
)


class NedMapTransformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.origin = GpsOrigin(31.2304, 121.4737, 10.0)

    def test_same_origins_have_zero_offset(self) -> None:
        offset = uav_origin_in_usv_ned(self.origin, self.origin)
        self.assertTrue(all(abs(value) < 1e-9 for value in offset))

    def test_gps_axes_have_expected_ned_signs(self) -> None:
        north_origin = GpsOrigin(self.origin.latitude_deg + 1e-5,
                                 self.origin.longitude_deg,
                                 self.origin.altitude_ellipsoid_m)
        east_origin = GpsOrigin(self.origin.latitude_deg,
                                self.origin.longitude_deg + 1e-5,
                                self.origin.altitude_ellipsoid_m)
        higher_origin = GpsOrigin(self.origin.latitude_deg,
                                  self.origin.longitude_deg,
                                  self.origin.altitude_ellipsoid_m + 5.0)
        north = uav_origin_in_usv_ned(north_origin, self.origin)
        east = uav_origin_in_usv_ned(east_origin, self.origin)
        higher = uav_origin_in_usv_ned(higher_origin, self.origin)
        self.assertGreater(north[0], 1.0)
        self.assertAlmostEqual(north[1], 0.0, delta=0.01)
        self.assertGreater(east[1], 0.8)
        self.assertAlmostEqual(east[0], 0.0, delta=0.01)
        self.assertAlmostEqual(higher[2], -5.0, delta=1e-5)

    def test_semantic_map_is_copied_and_transformed(self) -> None:
        source = {"objects": [{"type": "dock", "NED_position": [5, 2, -0.5]}]}
        result = transform_semantic_map(source, self.origin, self.origin)
        self.assertEqual(result["objects"][0]["NED_position"], [5.0, 2.0, -0.5])
        self.assertEqual(result["source_coordinate_frame"], "uav_ned")
        self.assertEqual(result["coordinate_frame"], "usv_ned")
        self.assertEqual(source["objects"][0]["NED_position"], [5, 2, -0.5])

        encoded = json.dumps(source)
        self.assertEqual(transform_semantic_map(encoded, self.origin, self.origin), result)

    def test_invalid_map_and_gps_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            GpsOrigin(91.0, 121.0, 0.0)
        with self.assertRaises(ValueError):
            add_ned_offset([1, 2], (0.0, 0.0, 0.0))
        with self.assertRaises(ValueError):
            transform_semantic_map({"objects": [{"type": "dock"}]}, self.origin, self.origin)


if __name__ == "__main__":
    unittest.main()
