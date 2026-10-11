import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PACKAGE_ROOT), str(PACKAGE_ROOT.parents[2])]

from twave_mission_dryrun.heartbeat_builder import HeartbeatBuilder
from twave_mission_dryrun.vehicle_status_store import VehicleStatusStore
from twave_mission_dryrun.vehicle_telemetry_store import VehicleTelemetryStore


class HeartbeatBuilderTests(unittest.TestCase):
    def setUp(self):
        self.telemetry = VehicleTelemetryStore(clock=lambda: 10.0)
        self.status = VehicleStatusStore(clock=lambda: 10.0)
        self.telemetry.update(
            "T-Wave", position={"latitude": 31.23, "longitude": 121.47},
            speed=2.5, heading=90.0, roll=1.0, pitch=-2.0, altitude=3.5,
        )
        self.status.update("T-Wave", "10100000000000")

    def test_telemetry_store_saves_required_fields(self):
        self.assertEqual(self.telemetry.get("T-Wave"), {
            "position": {"latitude": 31.23, "longitude": 121.47},
            "speed": 2.5, "heading": 90.0, "roll": 1.0, "pitch": -2.0,
            "altitude": 3.5, "timestamp": 10.0,
        })

    def test_builder_creates_heartbeat_payload_with_current_task(self):
        payload = HeartbeatBuilder(self.telemetry, self.status).build("T-Wave")
        self.assertEqual(payload, {
            "position": {"latitude": 31.23, "longitude": 121.47},
            "spd_mps": 2.5, "heading_deg": 90.0, "roll_deg": 1.0,
            "pitch_deg": -2.0, "altitude_hae_m": 3.5,
            "current_task": "TASK_SAFE_PASSAGE",
        })
        self.assertNotIn("timestamp", payload)


if __name__ == "__main__":
    unittest.main()
