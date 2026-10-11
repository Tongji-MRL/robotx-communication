import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PACKAGE_ROOT), str(PACKAGE_ROOT.parents[2])]

try:
    from twave_mission_dryrun.rx_report_adapter import RxReportAdapter
except ModuleNotFoundError as exc:
    if exc.name in {"google", "google.protobuf"}:
        raise unittest.SkipTest("protobuf is required for generated RoboCommand messages") from exc
    raise


class RxReportAdapterTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 11, 1, 2, 3, tzinfo=timezone.utc)
        self.adapter = RxReportAdapter("TONG", now=lambda: self.now)
        self.payload = {
            "position": {"latitude": 31.23, "longitude": 121.47},
            "spd_mps": 2.5, "heading_deg": 90.0, "roll_deg": 1.0,
            "pitch_deg": -2.0, "altitude_hae_m": 3.5,
            "current_task": "TASK_SAFE_PASSAGE",
        }

    def test_heartbeat_fields_map_to_rx_report(self):
        report = self.adapter.to_proto("T-Wave", self.payload)
        self.assertEqual(report.team_id, "TONG")
        self.assertEqual(report.vehicle_id, "T-Wave")
        self.assertEqual(report.seq, 1)
        self.assertEqual(report.sent_at.ToDatetime(tzinfo=timezone.utc), self.now)
        self.assertEqual(report.heartbeat.position.latitude, 31.23)
        self.assertEqual(report.heartbeat.position.longitude, 121.47)
        self.assertEqual(report.heartbeat.spd_mps, 2.5)
        self.assertEqual(report.heartbeat.heading_deg, 90.0)
        self.assertEqual(report.heartbeat.current_task, 2)  # TASK_SAFE_PASSAGE

    def test_sequence_increments_per_vehicle(self):
        self.assertEqual(self.adapter.to_proto("T-Wave", self.payload).seq, 1)
        self.assertEqual(self.adapter.to_proto("T-Wave", self.payload).seq, 2)

    def test_multiple_vehicles_have_independent_sequences(self):
        self.assertEqual(self.adapter.to_proto("T-Wave", self.payload).seq, 1)
        self.assertEqual(self.adapter.to_proto("T-Sky", self.payload).seq, 1)
        self.assertEqual(self.adapter.to_proto("T-Wave", self.payload).seq, 2)


if __name__ == "__main__":
    unittest.main()
