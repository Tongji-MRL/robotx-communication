import unittest

from geofence_watch import evaluate_uav_fence


FENCE = [
    {"latitude": 1.2800, "longitude": 103.8550}, {"latitude": 1.2800, "longitude": 103.8560},
    {"latitude": 1.2810, "longitude": 103.8560}, {"latitude": 1.2810, "longitude": 103.8550},
    {"latitude": 1.2800, "longitude": 103.8550},
]
DECLARATION = {"source": "RBC_MQTT_OBSERVED_REQUEST_NOT_ACCEPTANCE", "seq": 7,
               "uav_geofence": FENCE, "uav_geofence_max_altitude_hae_m": 40.0}


def status(latitude=1.2805, longitude=103.8555, altitude=20.0):
    return {"position": {"latitude_deg": latitude, "longitude_deg": longitude, "altitude_hae_m": altitude}}


class GeofenceWatchTests(unittest.TestCase):
    def test_inside(self):
        value = evaluate_uav_fence(status(), 0, DECLARATION)
        self.assertEqual((value["level"], value["horizontal"], value["vertical"]), ("INSIDE", "INSIDE", "BELOW"))

    def test_outside_and_over_height_alarm(self):
        value = evaluate_uav_fence(status(latitude=1.282, altitude=55), 0, DECLARATION)
        self.assertEqual(value["level"], "ALARM")
        self.assertEqual((value["horizontal"], value["vertical"]), ("OUTSIDE", "OVER"))
        self.assertLess(value["horizontal_clearance_m"], 0)
        self.assertEqual(value["height_clearance_m"], -15)

    def test_boundary_and_ceiling_are_caution(self):
        value = evaluate_uav_fence(status(latitude=1.2800, altitude=40), 0, DECLARATION)
        self.assertEqual(value["level"], "CAUTION")
        self.assertEqual((value["horizontal"], value["vertical"]), ("NEAR", "NEAR"))

    def test_stale_and_missing_data_never_safe(self):
        self.assertEqual(evaluate_uav_fence(status(), 3.1, DECLARATION)["level"], "STALE")
        self.assertEqual(evaluate_uav_fence(status(), 0, None)["level"], "UNKNOWN")
        self.assertEqual(evaluate_uav_fence(None, None, DECLARATION)["level"], "UNKNOWN")

    def test_invalid_fence_never_safe(self):
        value = evaluate_uav_fence(status(), 0, {**DECLARATION, "uav_geofence": FENCE[:-1]})
        self.assertEqual(value["level"], "UNKNOWN")
