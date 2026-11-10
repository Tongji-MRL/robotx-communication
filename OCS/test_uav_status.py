import json
import time
import unittest

from robotx import rx_common_pb2

from uav_ground_validation import build_ground_heartbeat
from uav_status import heartbeat_block_reason, normalize_uav_status, heartbeat_envelope
from vehicle_link import UAV_STATUS_TOPIC, VehicleLink


def valid():
    return {"vehicle_id": "UAV1", "vehicle_type": "uav", "state": "AUTO", "flight_phase": "AIRBORNE",
            "position": {"latitude": 1.2, "longitude": 103.8}, "altitude_hae_m": 20.0,
            "spd_mps": 4.0, "heading_deg": 180.0,
            "battery_status": {"connected": True, "remaining_percent": 75.0}}


class UavStatusTests(unittest.TestCase):
    @staticmethod
    def complete_real_status(timestamp):
        status = valid()
        status.update({
            "timestamp_unix_ms": timestamp, "source_mode": "real", "roll_deg": 1.5,
            "pitch_deg": -2.5, "current_task": "TASK_SAFE_PASSAGE",
            "health": {"fcu_connected": True}, "uav_registration": "TEST-UAV-001",
        })
        return status

    def test_valid_status_preserves_raw_and_maps_explicitly(self):
        result = normalize_uav_status(valid(), source_vehicle_id="UAV1", received_unix_ms=100)
        self.assertEqual((result["vehicle_id"], result["state"], result["raw"]["vehicle_id"]), ("T-Sky", "AUTO", "UAV1"))
        self.assertIsNone(heartbeat_envelope(result, run_id=42))

    def test_complete_real_orin_status_builds_official_heartbeat_without_mutating_raw(self):
        status = valid()
        timestamp = int(time.time() * 1000)
        status.update({
            "vehicle_type": "TYPE_UAV", "state": "STATE_AUTO",
            "flight_phase": "FLIGHT_PHASE_AIRBORNE", "timestamp_unix_ms": timestamp,
            "source_mode": "real", "roll_deg": 1.5, "pitch_deg": -2.5,
            "current_task": "TASK_SAFE_PASSAGE", "health": {"fcu_connected": True},
            "uav_registration": "TEST-UAV-001",
        })
        normalized = normalize_uav_status(status, source_vehicle_id="UAV1", vehicle_id="T-Sky")
        envelope = heartbeat_envelope(normalized, run_id=42, now_unix_ms=timestamp)
        self.assertIsNotNone(envelope)
        self.assertEqual(envelope["vehicle_id"], "T-Sky")
        self.assertEqual(envelope["payload"]["current_task"], "task1")
        self.assertEqual(envelope["payload"]["health"], {"fcu_connected": True})
        self.assertEqual(normalized["raw"], status)

    def test_complete_declared_pre_run_status_omits_internal_run_id(self):
        timestamp = int(time.time() * 1000)
        normalized = normalize_uav_status(
            self.complete_real_status(timestamp), source_vehicle_id="UAV1", vehicle_id="T-Sky",
        )
        envelope = heartbeat_envelope(normalized, run_id=None, now_unix_ms=timestamp)
        self.assertIsNotNone(envelope)
        self.assertNotIn("run_id", envelope)

    def test_incomplete_or_simulated_status_is_explicitly_blocked(self):
        normalized = normalize_uav_status(valid(), source_vehicle_id="UAV1")
        self.assertIn("timestamp", heartbeat_block_reason(normalized, run_id=42, now_unix_ms=100))
        status = valid()
        status.update({
            "timestamp_unix_ms": 100, "source_mode": "simulation", "roll_deg": 0.0,
            "pitch_deg": 0.0, "current_task": "TASK_NONE", "health": {"fcu_connected": True},
            "uav_registration": "TEST-UAV-001",
        })
        normalized = normalize_uav_status(status, source_vehicle_id="UAV1")
        self.assertIn("source_mode", heartbeat_block_reason(normalized, run_id=42, now_unix_ms=100))

    def test_explicit_null_current_task_means_no_task_under_orin_contract(self):
        now = int(time.time() * 1000)
        status = self.complete_real_status(now)
        status["current_task"] = None
        normalized = normalize_uav_status(status, source_vehicle_id="UAV1")
        envelope = heartbeat_envelope(normalized, run_id=None, now_unix_ms=now)
        self.assertIsNotNone(envelope)
        self.assertEqual(envelope["payload"]["current_task"], "none")

        del status["current_task"]
        normalized = normalize_uav_status(status, source_vehicle_id="UAV1")
        self.assertIn("current_task", heartbeat_block_reason(normalized, run_id=None, now_unix_ms=now))

    def test_each_required_authoritative_field_has_a_specific_heartbeat_gate(self):
        now = int(time.time() * 1000)
        expectations = {
            "timestamp_unix_ms": "timestamp",
            "roll_deg": "roll_deg",
            "pitch_deg": "pitch_deg",
            "current_task": "current_task",
            "health": "health",
            "source_mode": "source_mode",
            "uav_registration": "registration",
        }
        for field, expected_reason in expectations.items():
            with self.subTest(field=field):
                status = self.complete_real_status(now)
                del status[field]
                normalized = normalize_uav_status(status, source_vehicle_id="UAV1")
                self.assertIn(expected_reason, heartbeat_block_reason(
                    normalized, run_id=42, now_unix_ms=now,
                ))

    def test_stale_authoritative_timestamp_is_blocked(self):
        now = int(time.time() * 1000)
        normalized = normalize_uav_status(self.complete_real_status(now - 3_001), source_vehicle_id="UAV1")
        self.assertIn("stale", heartbeat_block_reason(normalized, run_id=42, now_unix_ms=now))

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

    def test_topic_mapping_accepts_omitted_id_but_rejects_conflicting_id(self):
        status = valid()
        del status["vehicle_id"]
        normalized = normalize_uav_status(status, source_vehicle_id="UAV1", vehicle_id="T-Sky")
        self.assertEqual((normalized["source_vehicle_id"], normalized["vehicle_id"]), ("UAV1", "T-Sky"))
        status["vehicle_id"] = "T-Sky"
        normalized = normalize_uav_status(status, source_vehicle_id="UAV1", vehicle_id="T-Sky")
        self.assertEqual(normalized["vehicle_id"], "T-Sky")
        status["vehicle_id"] = "OTHER-UAV"
        with self.assertRaisesRegex(ValueError, "does not match"):
            normalize_uav_status(status, source_vehicle_id="UAV1", vehicle_id="T-Sky")

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
