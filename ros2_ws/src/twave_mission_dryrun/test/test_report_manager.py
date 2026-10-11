import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from twave_mission_dryrun.report_manager import (
    FAULT_TOPIC,
    STATUS_TOPIC,
    TASK_REPORT_TOPIC,
    ReportManager,
)
from twave_mission_dryrun.vehicle_status_store import VehicleStatusStore


class ReportManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = ReportManager()

    def test_normal_status_generates_status_message(self):
        event = {"run_id": 42, "state": "RUNNING_TASK1", "error": "NONE"}
        message = self.manager.status_update(event)
        self.assertEqual(message.topic, STATUS_TOPIC)
        self.assertEqual(message.payload, event)
        self.assertIsNot(message.payload, event)

    def test_task_complete_generates_task_report(self):
        event = {"run_id": 42, "task": "TASK1", "result": "complete"}
        message = self.manager.task_complete(event)
        self.assertIsNotNone(message)
        self.assertEqual(message.topic, TASK_REPORT_TOPIC)
        self.assertEqual(message.payload, event)

    def test_safe_stop_generates_fault(self):
        event = {"run_id": 42, "state": "SAFE_STOP", "detail": "operator stop"}
        message = self.manager.fault_event(event)
        self.assertIsNotNone(message)
        self.assertEqual(message.topic, FAULT_TOPIC)
        self.assertEqual(message.payload, event)

    def test_timeout_does_not_generate_fault(self):
        self.assertIsNone(self.manager.fault_event({"error": "TIMEOUT"}))

    def test_optional_vehicle_data_sources_do_not_change_report_payloads(self):
        store = VehicleStatusStore(clock=lambda: 1.0)
        store.update("T-Wave", "10100000000000")
        manager = ReportManager(vehicle_status_provider=store)
        self.assertEqual(manager.vehicle_data("T-Wave"), {
            "status": {"status_bits": "10100000000000", "timestamp": 1.0},
            "telemetry": None,
        })
        self.assertEqual(manager.status_update({"state": "RUNNING_TASK1"}).payload,
                         {"state": "RUNNING_TASK1"})


if __name__ == "__main__":
    unittest.main()
