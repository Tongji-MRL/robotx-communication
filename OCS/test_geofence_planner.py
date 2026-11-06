"""OCS geofence planning/precheck regression tests (no network/flight control)."""
import math
import unittest

from course_config import validate_geofence_within_course
from geofence_planner import calculate_geofence_from_course, validate_geofence_altitude
from ocs_client import OcsClient
from robotx import rx_course_pb2, rx_requests_pb2


COURSE = [
    (1.28060, 103.85490),
    (1.28060, 103.85540),
    (1.28110, 103.85540),
    (1.28110, 103.85490),
    (1.28060, 103.85490),
]
TRANSIT = [
    (1.28060, 103.85540),
    (1.28060, 103.85560),
    (1.28110, 103.85560),
    (1.28110, 103.85540),
    (1.28060, 103.85540),
]
INSIDE = [
    (1.28075, 103.85505), (1.28075, 103.85520),
    (1.28090, 103.85520), (1.28090, 103.85505),
    (1.28075, 103.85505),
]
OUTSIDE = [
    (1.28075, 103.85535), (1.28075, 103.85580),
    (1.28090, 103.85580), (1.28090, 103.85535),
    (1.28075, 103.85535),
]
TRANSIT_ONLY = [
    (1.28075, 103.85545), (1.28075, 103.85555),
    (1.28090, 103.85555), (1.28090, 103.85545),
    (1.28075, 103.85545),
]


class GeofenceAutoPlannerTests(unittest.TestCase):
    def test_generated_fence_is_closed_and_inside_course(self):
        ring = calculate_geofence_from_course(COURSE, margin_m=2.0)
        self.assertEqual(len(ring), 13)
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(tuple(ring), validate_geofence_within_course(COURSE, ring))

    def test_concave_course_is_safe_or_fails_closed(self):
        concave = [
            (1.2806, 103.8549), (1.2806, 103.8555),
            (1.2808, 103.8555), (1.2808, 103.8551),
            (1.2812, 103.8551), (1.2812, 103.8549),
            (1.2806, 103.8549),
        ]
        try:
            ring = calculate_geofence_from_course(concave, margin_m=1)
        except ValueError:
            return  # Never create an unsafe candidate if geometry is restrictive.
        validate_geofence_within_course(concave, ring)

    def test_insufficient_clearance_rejected(self):
        with self.assertRaises(ValueError):
            calculate_geofence_from_course(COURSE, margin_m=200)

    def test_manual_fence_outside_both_regions_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside Course|leaves Course"):
            validate_geofence_within_course(COURSE, OUTSIDE, TRANSIT)

    def test_manual_fence_inside_transit_is_accepted(self):
        self.assertEqual(
            tuple(TRANSIT_ONLY), validate_geofence_within_course(COURSE, TRANSIT_ONLY, TRANSIT)
        )

    def test_manual_fence_crossing_shared_boundary_is_accepted(self):
        straddling = [
            (1.28075, 103.85528), (1.28075, 103.85547),
            (1.28090, 103.85547), (1.28090, 103.85528),
            (1.28075, 103.85528),
        ]
        self.assertEqual(
            tuple(straddling), validate_geofence_within_course(COURSE, straddling, TRANSIT)
        )

    def test_valid_and_overheight_with_configurable_limit(self):
        self.assertEqual(validate_geofence_altitude(40, limit_hae_m=50), 40)
        self.assertEqual(validate_geofence_altitude(25, limit_hae_m=30), 25)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_geofence_altitude(55, limit_hae_m=50)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_geofence_altitude(40, limit_hae_m=30)
        with self.assertRaises(ValueError):
            validate_geofence_altitude(float("nan"), limit_hae_m=50)
        with self.assertRaises(ValueError):
            validate_geofence_altitude(10, limit_hae_m=60)

    def test_protobuf_run_declaration_and_local_denial_before_publish(self):
        ocs = OcsClient("127.0.0.1", 18983)
        sent = []
        ocs._publish = lambda topic, req: sent.append((topic, req)) or len(sent)
        course = rx_course_pb2.RxCourse(course_id="BENCH", pinger_freq_hz=25000)
        for lat, lon in COURSE:
            course.corners.add(latitude=lat, longitude=lon)
        for lat, lon in TRANSIT:
            course.uav_transit_area.add(latitude=lat, longitude=lon)
        ocs._accept_course(course)
        original = ocs.course_store.get()
        self.assertEqual(original.course_id, "BENCH")
        ocs.publish_run_declaration(
            ["T-Wave", "T-Sky"],
            uav_geofence_mode="auto_course", uav_geofence_margin_m=2,
            uav_geofence_max_altitude_hae_m=40, uav_geofence_altitude_limit_hae_m=50,
            uav_pilot_callsign="BENCH-PILOT",
        )
        self.assertEqual(len(sent), 1)
        payload = rx_requests_pb2.RxRequest.FromString(sent[0][1].SerializeToString())
        self.assertEqual(payload.WhichOneof("body"), "run_declaration")
        self.assertEqual(payload.team_id, "TONG")
        self.assertEqual(payload.run_declaration.uav_geofence_max_altitude_hae_m, 40)
        self.assertEqual(payload.run_declaration.uav_geofence[0], payload.run_declaration.uav_geofence[-1])
        with self.assertRaisesRegex(ValueError, "outside Course|leaves Course"):
            ocs.publish_run_declaration(
                ["T-Sky"], uav_geofence=OUTSIDE,
                uav_geofence_max_altitude_hae_m=40, uav_pilot_callsign="BENCH-PILOT",
            )
        with self.assertRaisesRegex(ValueError, "exceeds"):
            ocs.publish_run_declaration(
                ["T-Sky"], uav_geofence=INSIDE,
                uav_geofence_max_altitude_hae_m=55,
                uav_geofence_altitude_limit_hae_m=50,
                uav_pilot_callsign="BENCH-PILOT",
            )
        self.assertEqual(len(sent), 1, "Rejected declarations must not be published")


if __name__ == "__main__":
    unittest.main()
