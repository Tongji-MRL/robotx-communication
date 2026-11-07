import unittest
import json

from robotx import rx_common_pb2

from uav_ground_validation import build_ground_heartbeat
from uav_status import normalize_uav_status, heartbeat_envelope
from vehicle_link import UAV_STATUS_TOPIC, VehicleLink


def valid():
    return {"vehicle_id": "UAV1", "vehicle_type": "uav", "state": "AUTO", "flight_phase": "AIRBORNE",
            "position": {"latitude": 1.2, "longitude": 103.8}, "altitude_hae_m": 20.0,
            "spd_mps": 4.0, "heading_deg": 180.0,
            "battery_status": {"connected": True, "remaining_percent": 75.0}}


class UavStatusTests(unittest.TestCase):
    def test_valid_status_preserves_raw_and_maps_explicitly(self):
        result = normalize_uav_status(valid(), source_vehicle_id="UAV1", received_unix_ms=100)
        self.assertEqual((result["vehicle_id"], result["state"], result["raw"]["vehicle_id"]), ("T-Sky", "AUTO", "UAV1"))
        self.assertIsNone(heartbeat_envelope(result, run_id=42))

    def test_orin_enum_values_normalize_and_build_heartbeat(self):
        expected = {
            "STATE_AUTO": ("AUTO", "FLIGHT_PHASE_AIRBORNE", "airborne"),
            "STATE_MANUAL": ("MANUAL", "FLIGHT_PHASE_GROUNDED", "grounded"),
            "STATE_KILLED": ("KILLED", "FLIGHT_PHASE_GROUNDED", "grounded"),
        }
        for raw_state, (state, raw_phase, phase) in expected.items():
            with self.subTest(raw_state=raw_state):
                status = valid()
                status.update(vehicle_type="TYPE_UAV", state=raw_state, flight_phase=raw_phase)
                result = normalize_uav_status(status, source_vehicle_id="UAV1", received_unix_ms=100)
                self.assertEqual(
                    (result["vehicle_type"], result["state"], result["flight_phase"]),
                    ("uav", state, phase),
                )
                self.assertEqual(
                    (result["raw"]["vehicle_type"], result["raw"]["state"], result["raw"]["flight_phase"]),
                    ("TYPE_UAV", raw_state, raw_phase),
                )
                heartbeat = build_ground_heartbeat(result)
                self.assertEqual(heartbeat.state, getattr(__import__("common_pb2"), raw_state))
                self.assertEqual(heartbeat.flight_phase, getattr(rx_common_pb2, raw_phase))

    def test_rejects_unknown_enum_values(self):
        for field, value in (("vehicle_type", "TYPE_UNKNOWN"), ("state", "UNKNOWN"),
                             ("state", "STATE_UNKNOWN"), ("flight_phase", "UNKNOWN"),
                             ("flight_phase", "FLIGHT_PHASE_UNKNOWN")):
            with self.subTest(field=field):
                status = valid()
                status[field] = value
                with self.assertRaises(ValueError):
                    normalize_uav_status(status, source_vehicle_id="UAV1")

    def test_rejects_mapping_and_numeric_errors(self):
        with self.assertRaisesRegex(ValueError, "mapping"):
            normalize_uav_status(valid(), source_vehicle_id="OTHER")
        bad = valid(); bad["position"]["latitude"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            normalize_uav_status(bad, source_vehicle_id="UAV1")
        bad = valid(); bad["heading_deg"] = 360
        with self.assertRaisesRegex(ValueError, "range"):
            normalize_uav_status(bad, source_vehicle_id="UAV1")

    def test_internal_link_never_turns_status_into_a_heartbeat(self):
        accepted = []
        link = VehicleLink.__new__(VehicleLink)
        link.on_uav_status = accepted.append
        link.uav_source_vehicle_id = "UAV1"
        link.active_run_id = lambda: 42
        message = type("Message", (), {"topic": UAV_STATUS_TOPIC, "payload": json.dumps(valid()).encode()})()
        link._on_message(None, None, message)
        self.assertEqual(len(accepted), 1)
        self.assertIsNone(accepted[0]["official_heartbeat"])
