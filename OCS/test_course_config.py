from datetime import datetime, timezone
import unittest

from course_config import make_payload, validate_payload
from vehicle_protocol import decode, encode, make_message, topic
from vehicle_link import VehicleLink


class CourseConfigTests(unittest.TestCase):
    def payload(self, course_id="RX2026-A", sent_at=None):
        return make_payload(course_id=course_id, pinger_freq_hz=27000,
                            corners=[(1.0, 2.0), (1.0, 3.0), (2.0, 3.0), (1.0, 2.0)],
                            source_sent_at=sent_at)

    def test_envelope_is_pre_run_and_round_trips_all_course_fields(self):
        payload = self.payload(sent_at=datetime(2026, 10, 17, 3, tzinfo=timezone.utc))
        envelope = make_message("T-Wave", "course_config", payload, run_id=None, source="ocs")
        self.assertEqual(topic("T-Wave", "course_config"), "tongji/robotx/v1/T-Wave/course_config")
        self.assertIsNone(envelope["run_id"])
        self.assertEqual(decode(encode(envelope))["payload"], payload)

    def test_invalid_polygon_and_coordinates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "closed"):
            make_payload(course_id="x", pinger_freq_hz=1, corners=[(1, 2), (1, 3), (2, 3)], source_sent_at=None)
        with self.assertRaisesRegex(ValueError, "out of range"):
            make_payload(course_id="x", pinger_freq_hz=1, corners=[(91, 2), (1, 3), (2, 3), (91, 2)], source_sent_at=None)
        with self.assertRaises(ValueError):
            validate_payload({"schema_version": "twave-course-config-v1"})

    def test_vehicle_link_publishes_course_retained_qos1(self):
        published = []
        class Result:
            rc = 0
            def wait_for_publish(self): pass
        class Client:
            def publish(self, *args, **kwargs):
                published.append((args, kwargs)); return Result()
        link = VehicleLink.__new__(VehicleLink)
        link.client = Client()
        link.send_course_config({"kind": "course_config", "vehicle_id": "T-Wave", "payload": self.payload()})
        args, kwargs = published[0]
        self.assertEqual(args[0], "tongji/robotx/v1/T-Wave/course_config")
        self.assertEqual(kwargs, {"qos": 1, "retain": True})
        sent = decode(args[1])
        self.assertEqual(sent["kind"], "course_config")
        self.assertEqual(sent["source"], "ocs")
        self.assertIsNone(sent["run_id"])
