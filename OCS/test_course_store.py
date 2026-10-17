from datetime import datetime, timezone
import unittest

from course_store import CourseStore


class CourseStoreTests(unittest.TestCase):
    def test_saves_a_protobuf_free_immutable_config(self):
        store = CourseStore()
        sent_at = datetime(2026, 10, 11, tzinfo=timezone.utc)
        store.update(
            course_id="RX2026-A", pinger_freq_hz=27000,
            corners=[(1.0, 2.0), (1.0, 3.0), (2.0, 3.0), (1.0, 2.0)], sent_at=sent_at,
        )
        config = store.get()
        self.assertEqual(config.course_id, "RX2026-A")
        self.assertEqual(config.pinger_freq_hz, 27000)
        self.assertEqual(config.corners, ((1.0, 2.0), (1.0, 3.0), (2.0, 3.0), (1.0, 2.0)))
        self.assertEqual(config.sent_at, sent_at)
