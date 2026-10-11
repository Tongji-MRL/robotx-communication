import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PACKAGE_ROOT), str(PACKAGE_ROOT.parents[2])]

try:
    from twave_mission_dryrun.mqtt_report_runtime import MqttReportRuntime
    from twave_mission_dryrun.rx_report_adapter import RxReportAdapter
except ModuleNotFoundError as exc:
    if exc.name in {"google", "google.protobuf"}:
        raise unittest.SkipTest("protobuf is required for generated RoboCommand messages") from exc
    raise


class FakeMqttClient:
    def __init__(self):
        self.credentials = None
        self.connected = None
        self.loop_started = False
        self.closed = False
        self.published = []

    def username_pw_set(self, username, password):
        self.credentials = (username, password)

    def connect(self, host, port, keepalive):
        self.connected = (host, port, keepalive)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_started = False

    def disconnect(self):
        self.closed = True

    def publish(self, topic, payload, *, qos, retain):
        self.published.append((topic, payload, qos, retain))
        return "success"


class MqttReportRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeMqttClient()
        self.runtime = MqttReportRuntime(
            host="broker.example", port=1884, username="user", password="secret",
            client_factory=lambda: self.client,
        )

    def test_runtime_creates_client_and_provides_it_to_publisher(self):
        self.assertIs(self.runtime.publisher.client, self.client)
        self.assertEqual(self.client.credentials, ("user", "secret"))
        self.runtime.connect()
        self.assertEqual(self.client.connected, ("broker.example", 1884, 60))
        self.assertTrue(self.client.loop_started)
        self.runtime.close()
        self.assertTrue(self.client.closed)

    def test_mock_mqtt_publish_succeeds(self):
        report = RxReportAdapter(
            "TONG", now=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc),
        ).to_proto("T-Wave", {
            "position": {"latitude": 31.23, "longitude": 121.47},
            "spd_mps": 2.5, "heading_deg": 90.0, "roll_deg": 1.0,
            "pitch_deg": -2.0, "altitude_hae_m": 3.5,
            "current_task": "TASK_SAFE_PASSAGE",
        })
        self.assertEqual(self.runtime.publisher.publish(report), "success")
        self.assertEqual(self.client.published[0][0], "robocommand/robotx/TONG/T-Wave/report")


if __name__ == "__main__":
    unittest.main()
