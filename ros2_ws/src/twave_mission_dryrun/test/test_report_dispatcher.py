import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PACKAGE_ROOT), str(PACKAGE_ROOT.parents[2])]

try:
    from twave_mission_dryrun.report_dispatcher import ReportDispatcher
    from twave_mission_dryrun.report_publisher import RxReportPublisher
    from twave_mission_dryrun.rx_report_adapter import RxReportAdapter
except ModuleNotFoundError as exc:
    if exc.name in {"google", "google.protobuf"}:
        raise unittest.SkipTest("protobuf is required for generated RoboCommand messages") from exc
    raise


class FakeMqttClient:
    def __init__(self):
        self.calls = []

    def publish(self, topic, payload, *, qos, retain):
        self.calls.append((topic, payload, qos, retain))
        return "published"


class ReportDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeMqttClient()
        self.publisher = RxReportPublisher(self.client)
        self.dispatcher = ReportDispatcher(self.publisher)
        self.adapter = RxReportAdapter("TONG", now=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc))
        self.payload = {
            "position": {"latitude": 31.23, "longitude": 121.47},
            "spd_mps": 2.5, "heading_deg": 90.0, "roll_deg": 1.0,
            "pitch_deg": -2.0, "altitude_hae_m": 3.5,
            "current_task": "TASK_SAFE_PASSAGE",
        }

    def test_rx_report_dispatches_after_recording_pre_send_state(self):
        report = self.adapter.to_proto("T-Wave", self.payload)
        self.assertEqual(self.dispatcher.dispatch(report), "published")
        self.assertEqual(self.dispatcher.pre_send_records[0].vehicle_id, "T-Wave")
        self.assertEqual(self.dispatcher.pre_send_records[0].seq, 1)
        topic, raw, qos, retain = self.client.calls[0]
        self.assertEqual(topic, "robocommand/robotx/TONG/T-Wave/report")
        self.assertEqual(raw, report.SerializeToString())
        self.assertEqual((qos, retain), (1, False))

    def test_each_vehicle_uses_its_own_report_topic(self):
        self.dispatcher.dispatch(self.adapter.to_proto("T-Wave", self.payload))
        self.dispatcher.dispatch(self.adapter.to_proto("T-Sky", self.payload))
        self.assertEqual([call[0] for call in self.client.calls], [
            "robocommand/robotx/TONG/T-Wave/report",
            "robocommand/robotx/TONG/T-Sky/report",
        ])
