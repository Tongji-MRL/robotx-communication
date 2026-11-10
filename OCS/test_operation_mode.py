import unittest

from operation_mode import VehicleMode, select_declaration


class OperationModeTests(unittest.TestCase):
    def setUp(self):
        self.values = dict(
            uav_vehicle_id="T-Sky", usv_vehicle_id="T-Wave",
            uav_geofence=[(1.0, 2.0), (1.0, 3.0), (1.0, 2.0)],
            uav_geofence_max_altitude_hae_m=40.0, uav_pilot_callsign="PILOT",
            uav_geofence_mode="auto_course",
        )

    def test_uav_only_keeps_uav_declaration_fields(self):
        result = select_declaration(VehicleMode.UAV_ONLY, **self.values)
        self.assertEqual(result.vehicle_ids, ["T-Sky"])
        self.assertEqual(result.uav_geofence_mode, "auto_course")

    def test_usv_only_removes_uav_declaration_fields(self):
        result = select_declaration("usv_only", **self.values)
        self.assertEqual(result.vehicle_ids, ["T-Wave"])
        self.assertEqual((result.uav_geofence, result.uav_geofence_max_altitude_hae_m,
                          result.uav_pilot_callsign, result.uav_geofence_mode),
                         ([], None, None, "manual"))

    def test_dual_vehicle_keeps_both_vehicles(self):
        result = select_declaration("dual_vehicle", **self.values)
        self.assertEqual(result.vehicle_ids, ["T-Sky", "T-Wave"])

    def test_missing_selected_vehicle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "uav_only"):
            select_declaration("uav_only", **{**self.values, "uav_vehicle_id": None})
