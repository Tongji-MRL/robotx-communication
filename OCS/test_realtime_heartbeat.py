import unittest
import time
from unittest.mock import patch

from heartbeat_cache import HeartbeatCache, HeartbeatRejected
from ros2_telemetry import Ros2TelemetryAdapter
from uav_status import normalize_uav_status


def heartbeat(vehicle_id, *, now=1_000_000, run_id=42, message_id="m", mode="simulation"):
    payload = {
        "source_mode": mode, "state": "AUTO",
        "vehicle_type": "uav" if vehicle_id == "T-Sky" else "usv",
        "position": {"frame_id": "wgs84", "latitude_deg": 1.2, "longitude_deg": 103.8, "altitude_hae_m": 12.0},
        "speed_mps": 3.0, "heading_deg": 90.0, "roll_deg": 1.0, "pitch_deg": 2.0,
        "health": {"fcu_connected": True, "simulator": mode == "simulation"},
    }
    if vehicle_id == "T-Wave":
        payload["current_task"] = "TASK_NONE"
    if vehicle_id == "T-Sky":
        payload["flight_phase"] = "airborne"
    return {"kind": "heartbeat", "vehicle_id": vehicle_id, "source": vehicle_id,
            "run_id": run_id, "message_id": message_id, "sent_at_unix_ms": now, "payload": payload}


class RealtimeHeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000
        self.cache = HeartbeatCache(now_ms=lambda: self.now)

    def test_each_vehicle_and_dual_vehicle_cache_at_two_hz_samples(self):
        for vehicle in ("T-Wave", "T-Sky"):
            self.cache.accept(heartbeat(vehicle, message_id=vehicle), active_run_id=42)
            self.assertIsNotNone(self.cache.valid(vehicle, active_run_id=42))
        # A second source sample 500 ms later remains a distinct valid update.
        self.now += 500
        self.cache.accept(heartbeat("T-Wave", now=self.now, message_id="wave-2"), active_run_id=42)
        self.cache.accept(heartbeat("T-Sky", now=self.now, message_id="sky-2"), active_run_id=42)

    def test_ignores_source_timestamp_but_rejects_other_invalid_data(self):
        with patch("builtins.print") as warn:
            self.cache.accept(heartbeat("T-Wave", now=self.now - 4000, message_id="old"), active_run_id=42)
            self.cache.accept(heartbeat("T-Sky", now=self.now + 4_000_000, message_id="future"), active_run_id=42)
        self.assertEqual(warn.call_count, 2)
        self.assertIn("[WARN]", warn.call_args_list[0].args[0])
        missing_timestamp = heartbeat("T-Wave", message_id="no-timestamp")
        del missing_timestamp["sent_at_unix_ms"]
        with patch("builtins.print") as warn:
            self.cache.accept(missing_timestamp, active_run_id=42)
        self.assertIn("no integer source timestamp", warn.call_args.args[0])
        self.now += 60_000
        self.assertIsNotNone(self.cache.valid("T-Wave", active_run_id=42))
        with self.assertRaises(HeartbeatRejected):
            self.cache.accept(heartbeat("T-Wave", run_id=41), active_run_id=42)
        msg = heartbeat("T-Wave", message_id="once")
        self.cache.accept(msg, active_run_id=42)
        with self.assertRaises(HeartbeatRejected):
            self.cache.accept(msg, active_run_id=42)
        bad = heartbeat("T-Wave", message_id="bad")
        bad["payload"]["position"]["latitude_deg"] = None
        with self.assertRaises(HeartbeatRejected):
            self.cache.accept(bad, active_run_id=42)

    def test_rejects_fcu_disconnect_and_simulation_real_mixing(self):
        disconnected = heartbeat("T-Sky", message_id="disconnected")
        disconnected["payload"]["health"]["fcu_connected"] = False
        with self.assertRaises(HeartbeatRejected):
            self.cache.accept(disconnected, active_run_id=42)
        fake_real = heartbeat("T-Wave", message_id="fake-real", mode="real")
        fake_real["payload"]["health"]["simulator"] = True
        with self.assertRaises(HeartbeatRejected):
            self.cache.accept(fake_real, active_run_id=42)

    def test_usv_requires_an_explicit_legal_current_task(self):
        missing = heartbeat("T-Wave", message_id="missing-task")
        del missing["payload"]["current_task"]
        with self.assertRaisesRegex(HeartbeatRejected, "current_task"):
            self.cache.accept(missing, active_run_id=42)
        invalid = heartbeat("T-Wave", message_id="invalid-task")
        invalid["payload"]["current_task"] = "TASK_MADE_UP"
        with self.assertRaisesRegex(HeartbeatRejected, "current_task"):
            self.cache.accept(invalid, active_run_id=42)

    def test_usv_cache_accepts_all_official_task_names(self):
        for index, task in enumerate((
            "TASK_UNKNOWN", "TASK_NONE", "TASK_SAFE_PASSAGE",
            "TASK_INFRA_SURVEY_REPAIR", "TASK_COORDINATED_LOGISTICS",
            "TASK_DYNAMIC_INCIDENT",
        )):
            self.now += 1
            sample = heartbeat("T-Wave", now=self.now, message_id=f"official-task-{index}")
            sample["payload"]["current_task"] = task
            self.cache.accept(sample, active_run_id=42)

    def test_ros_adapter_is_read_only_and_requires_complete_confirmed_data(self):
        adapter = Ros2TelemetryAdapter("T-Sky", now_ms=lambda: self.now)
        self.assertIsNone(adapter.heartbeat_payload())
        adapter.update(timestamp_unix_ms=self.now, state="AUTO", latitude_deg=1.2,
                       longitude_deg=103.8, altitude_hae_m=20.0, speed_mps=4.0,
                       heading_deg=180.0, roll_deg=2.0, pitch_deg=1.0,
                       fcu_connected=True, flight_phase="airborne")
        payload = adapter.heartbeat_payload()
        self.assertEqual(payload["source_mode"], "real")
        self.assertEqual(payload["flight_phase"], "airborne")
        self.now += 3001
        self.assertIsNone(adapter.heartbeat_payload())


class OcsHeartbeatPublicationTests(unittest.TestCase):
    def test_declared_pre_run_heartbeat_publishes_and_binds_to_real_run(self):
        import ocs_client
        client = ocs_client.OcsClient("127.0.0.1", 1883)
        published = []
        client._publish = lambda topic, message: published.append((topic, message)) or len(published)
        client._declared_vehicle_ids = {"T-Sky"}
        now = int(time.time() * 1000)
        status = normalize_uav_status({
            "vehicle_id": "UAV1", "vehicle_type": "TYPE_UAV", "state": "STATE_MANUAL",
            "flight_phase": "FLIGHT_PHASE_GROUNDED", "position": {"latitude": 1.2, "longitude": 103.8},
            "altitude_hae_m": 20.0, "spd_mps": 0.0, "heading_deg": 180.0,
            "timestamp_unix_ms": now, "source_mode": "real", "roll_deg": 1.0, "pitch_deg": -2.0,
            "current_task": "TASK_NONE", "health": {"fcu_connected": True},
            "uav_registration": "TEST-UAV-001",
        }, source_vehicle_id="UAV1", vehicle_id="T-Sky")

        client.accept_uav_status(status)
        self.assertEqual(client.publish_cached_heartbeats(), 1)
        self.assertEqual(published[-1][0], "robocommand/robotx/TONG/T-Sky/report")
        self.assertEqual(published[-1][1].seq, 1)
        report = published[-1][1]
        self.assertEqual(report.team_id, "TONG")
        self.assertEqual(report.vehicle_id, "T-Sky")
        self.assertGreater(report.sent_at.seconds, 0)
        self.assertEqual(report.heartbeat.vehicle_type, ocs_client.rx_common_pb2.TYPE_UAV)
        self.assertEqual(report.heartbeat.current_task, ocs_client.rx_common_pb2.TASK_NONE)
        self.assertEqual(report.heartbeat.flight_phase, ocs_client.rx_common_pb2.FLIGHT_PHASE_GROUNDED)
        self.assertEqual(report.heartbeat.uav_registration, "TEST-UAV-001")
        client.run_id = 42
        self.assertEqual(client.heartbeat_cache.bind_pre_run_entries(client.run_id), 1)
        self.assertEqual(client.publish_cached_heartbeats(), 1)
        self.assertEqual(published[-1][0], "robocommand/robotx/TONG/T-Sky/report")
        self.assertEqual(published[-1][1].seq, 2)

    def test_current_orin_snapshot_is_blocked_without_authoritative_fields(self):
        import ocs_client
        client = ocs_client.OcsClient("127.0.0.1", 1883)
        client._declared_vehicle_ids = {"T-Sky"}
        status = normalize_uav_status({
            "vehicle_id": "UAV1", "vehicle_type": "TYPE_UAV", "state": "STATE_AUTO",
            "flight_phase": "FLIGHT_PHASE_GROUNDED",
            "position": {"latitude": 1.281550930606749, "longitude": 103.8544517713803},
            "spd_mps": 0.010401902305601647, "heading_deg": 16.269135646287282,
            "roll_deg": 0.09218245859619373, "pitch_deg": 0.8789420575508625,
            "altitude_hae_m": 13.759857177734375, "current_task": None,
            "uav_registration": "TONG-53580",
        }, source_vehicle_id="UAV1", vehicle_id="T-Sky", uav_registration="TONG-53580")
        client.accept_uav_status(status)
        self.assertEqual(client.runtime_events[-1]["event"], "uav_status_heartbeat_blocked")
        self.assertIn("timestamp", client.runtime_events[-1]["detail"])
        self.assertEqual(client.publish_cached_heartbeats(), 0)

    def test_configured_trusted_ros2_source_accepts_current_orin_shape(self):
        import ocs_client
        client = ocs_client.OcsClient("127.0.0.1", 1883)
        published = []
        client._publish = lambda topic, message: published.append((topic, message)) or len(published)
        client._declared_vehicle_ids = {"T-Sky"}
        now = int(time.time() * 1000)
        status = normalize_uav_status({
            "vehicle_id": "UAV1", "vehicle_type": "TYPE_UAV", "state": "STATE_AUTO",
            "flight_phase": "FLIGHT_PHASE_GROUNDED",
            "position": {"latitude": 1.281550930606749, "longitude": 103.8544517713803},
            "spd_mps": 0.01, "heading_deg": 16.3, "roll_deg": 0.09, "pitch_deg": 0.95,
            "altitude_hae_m": 14.2, "timestamp_unix_ms": now - 60_000, "current_task": None,
            "uav_registration": "TONG-53580",
        }, source_vehicle_id="UAV1", vehicle_id="T-Sky", uav_registration="TONG-53580",
           trusted_status_source=True, use_ocs_receipt_for_freshness=True,
           received_unix_ms=now)
        client.accept_uav_status(status)
        self.assertEqual(client.publish_cached_heartbeats(), 1)
        report = published[-1][1]
        self.assertEqual(report.team_id, "TONG")
        self.assertEqual(report.vehicle_id, "T-Sky")
        self.assertEqual(report.heartbeat.current_task, ocs_client.rx_common_pb2.TASK_NONE)
        self.assertEqual(report.heartbeat.vehicle_type, ocs_client.rx_common_pb2.TYPE_UAV)

    def test_real_orin_status_enters_only_the_declared_uav_cache(self):
        import ocs_client
        client = ocs_client.OcsClient("127.0.0.1", 1883)
        published = []
        client._publish = lambda topic, message: published.append((topic, message)) or len(published)
        client._declared_vehicle_ids = {"T-Sky"}
        client.run_id = 42
        now = int(time.time() * 1000)
        status = normalize_uav_status({
            "vehicle_id": "UAV1", "vehicle_type": "TYPE_UAV", "state": "STATE_AUTO",
            "flight_phase": "FLIGHT_PHASE_AIRBORNE", "position": {"latitude": 1.2, "longitude": 103.8},
            "altitude_hae_m": 20.0, "spd_mps": 4.0, "heading_deg": 180.0,
            "timestamp_unix_ms": now, "source_mode": "real", "roll_deg": 1.0, "pitch_deg": -2.0,
            "current_task": "TASK_SAFE_PASSAGE", "health": {"fcu_connected": True},
            "uav_registration": "TEST-UAV-001",
        }, source_vehicle_id="UAV1", vehicle_id="T-Sky")
        client.accept_uav_status(status)
        self.assertEqual(client.runtime_events[-1]["event"], "uav_status_heartbeat_cached")
        self.assertEqual(client.publish_cached_heartbeats(), 1)
        report = published[-1][1]
        self.assertEqual(report.vehicle_id, "T-Sky")
        self.assertEqual(report.heartbeat.state, ocs_client.common_pb2.STATE_AUTO)
        self.assertEqual(report.heartbeat.vehicle_type, ocs_client.rx_common_pb2.TYPE_UAV)
        self.assertEqual(report.heartbeat.current_task, ocs_client.rx_common_pb2.TASK_SAFE_PASSAGE)
        self.assertEqual(report.heartbeat.flight_phase, ocs_client.rx_common_pb2.FLIGHT_PHASE_AIRBORNE)
        self.assertEqual(report.heartbeat.uav_registration, "TEST-UAV-001")

    def test_protobuf_mapping_and_shared_per_vehicle_sequence(self):
        # This verifies cache -> official RxReport without a live broker.
        import ocs_client
        client = ocs_client.OcsClient("127.0.0.1", 1883)
        published = []
        client._publish = lambda topic, message: published.append((topic, message)) or len(published)
        course = ocs_client.rx_course_pb2.RxCourse(course_id="RX2026-A", pinger_freq_hz=27000)
        for latitude, longitude in ((1.0, 2.0), (1.0, 3.0), (2.0, 3.0), (1.0, 2.0)):
            course.corners.add(latitude=latitude, longitude=longitude)
        client._accept_course(course)
        client.drain_internal_actions()
        client.publish_run_declaration(
            ["T-Wave", "T-Sky"],
            uav_geofence=[(1.0, 2.0), (1.0, 3.0), (2.0, 3.0), (1.0, 2.0)],
            uav_geofence_max_altitude_hae_m=40.0,
            uav_pilot_callsign="TEST-PILOT-UAPL-000",
        )
        client.run_id = 42
        now = int(time.time() * 1000)
        client.accept_vehicle_envelope(heartbeat("T-Wave", now=now, message_id="wave"))
        client.accept_vehicle_envelope(heartbeat("T-Sky", now=now, message_id="sky"))
        client.set_authoritative_current_task("T-Sky", "task3")
        self.assertEqual(client.publish_cached_heartbeats(), 2)
        reports = [message for _topic, message in published[1:]]
        wave = next(report for report in reports if report.vehicle_id == "T-Wave")
        sky = next(report for report in reports if report.vehicle_id == "T-Sky")
        self.assertEqual(wave.heartbeat.position.latitude, 1.2)
        self.assertEqual(wave.heartbeat.heading_deg, 90.0)
        self.assertEqual(wave.heartbeat.current_task, ocs_client.rx_common_pb2.TASK_NONE)
        self.assertEqual(sky.heartbeat.roll_deg, 1.0)
        self.assertEqual(sky.heartbeat.flight_phase, ocs_client.rx_common_pb2.FLIGHT_PHASE_AIRBORNE)
        self.assertEqual(sky.heartbeat.current_task, ocs_client.rx_common_pb2.TASK_COORDINATED_LOGISTICS)
        self.assertEqual(sky.heartbeat.uav_registration, "")
        client.publish_docking_report("T-Wave", 1)
        self.assertEqual([message.seq for _topic, message in published[1:]
                          if message.vehicle_id == "T-Wave"], [1, 2])

    def test_usv_task_conflict_is_logged_and_not_published(self):
        import ocs_client
        client = ocs_client.OcsClient("127.0.0.1", 1883)
        published = []
        client._publish = lambda topic, message: published.append((topic, message)) or len(published)
        client._declared_vehicle_ids = {"T-Wave"}
        client.run_id = 42
        client.accept_vehicle_envelope(heartbeat("T-Wave", now=int(time.time() * 1000), message_id="wave"))
        client.set_authoritative_current_task("T-Wave", "task3")

        self.assertEqual(client.publish_cached_heartbeats(), 0)
        self.assertEqual(published, [])
        self.assertEqual(client.runtime_events[-1]["event"], "current_task_conflict")


if __name__ == "__main__":
    unittest.main()
