import unittest

from qgc_geofence_export import build_qgc_plan


class QgcGeofenceExportTests(unittest.TestCase):
    def test_plan_contains_clockwise_open_inclusion_polygon(self):
        plan = build_qgc_plan(
            [(1.0, 103.0), (1.0, 104.0), (2.0, 104.0), (2.0, 103.0), (1.0, 103.0)],
            home_lat=1.1, home_lon=103.1, home_alt_amsl_m=12.0,
        )
        self.assertEqual(plan["fileType"], "Plan")
        self.assertEqual(plan["geoFence"]["circles"], [])
        polygon = plan["geoFence"]["polygons"][0]
        self.assertTrue(polygon["inclusion"])
        self.assertEqual(len(polygon["polygon"]), 4)
        self.assertEqual(plan["mission"]["plannedHomePosition"], [1.1, 103.1, 12.0])
        self.assertEqual(plan["mission"]["items"], [])

    def test_home_coordinates_are_validated(self):
        with self.assertRaisesRegex(ValueError, "home_lat"):
            build_qgc_plan([(1, 1), (1, 2), (2, 1), (1, 1)],
                           home_lat=91, home_lon=1, home_alt_amsl_m=0)
