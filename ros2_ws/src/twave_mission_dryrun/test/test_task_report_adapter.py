import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PACKAGE_ROOT), str(PACKAGE_ROOT.parents[2])]

try:
    from twave_mission_dryrun.task_report_adapter import TaskReportAdapter
except ModuleNotFoundError as exc:
    if exc.name in {"google", "google.protobuf"}:
        raise unittest.SkipTest("protobuf is required for generated RoboCommand messages") from exc
    raise


class TaskReportAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = TaskReportAdapter(
            "TONG", now=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc),
        )

    def test_task1_success_maps_safe_passage(self):
        report = self.adapter.to_proto({
            "run_id": 42, "vehicle_id": "T-Wave", "task": "TASK1", "result": "SUCCESS",
            "payload": {
                "entry_position": {"latitude": 31.0, "longitude": 121.0},
                "exit_position": {"latitude": 31.1, "longitude": 121.1},
                "buoys": [{
                    "position": {"latitude": 31.05, "longitude": 121.05},
                    "state": "BEACON_STATE_FLASHING_BLUE",
                }],
            },
        })
        self.assertEqual(report.WhichOneof("body"), "safe_passage")
        self.assertEqual(report.safe_passage.entry_position.latitude, 31.0)
        self.assertEqual(report.safe_passage.buoys[0].state, 4)

    def test_task3_dock_complete_maps_docking(self):
        report = self.adapter.to_proto({
            "run_id": 42, "vehicle_id": "T-Wave", "task": "TASK3", "result": "DOCK_COMPLETE",
            "payload": {"bay_id": 7},
        })
        self.assertEqual(report.WhichOneof("body"), "docking")
        self.assertEqual(report.docking.bay_id, 7)

    def test_task3_fire_complete_maps_firefighting(self):
        report = self.adapter.to_proto({
            "run_id": 42, "vehicle_id": "T-Wave", "task": "TASK3", "result": "FIRE_COMPLETE",
            "payload": {"window_id": 3},
        })
        self.assertEqual(report.WhichOneof("body"), "firefighting")
        self.assertEqual(report.firefighting.window_id, 3)

    def test_missing_required_payload_field_is_rejected(self):
        with self.assertRaises(ValueError):
            self.adapter.to_proto({
                "run_id": 42, "vehicle_id": "T-Wave", "task": "TASK3", "result": "DOCK_COMPLETE",
                "payload": {},
            })


if __name__ == "__main__":
    unittest.main()
