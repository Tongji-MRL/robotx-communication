import unittest
import time

from heartbeat_cache import HeartbeatCache, HeartbeatRejected
from ros2_telemetry import Ros2TelemetryAdapter


def heartbeat(vehicle_id, *, now=1_000_000, run_id=42, message_id="m", mode="simulation"):
    payload = {
        "source_mode": mode, "state": "AUTO",
        "vehicle_type": "uav" if vehicle_id == "T-Sky" else "usv",
        "position": {"frame_id": "wgs84", "latitude_deg": 1.2, "longitude_deg": 103.8, "altitude_hae_m": 12.0},
        "speed_mps": 3.0, "heading_deg": 90.0, "roll_deg": 1.0, "pitch_deg": 2.0,
        "health": {"fcu_connected": True, "simulator": mode == "simulation"},
    }
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

    def test_rejects_stale_old_run_duplicate_and_invalid_location(self):
        with self.assertRaises(HeartbeatRejected):
            self.cache.accept(heartbeat("T-Wave", now=self.now - 4000), active_run_id=42)
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
    def test_protobuf_mapping_and_shared_per_vehicle_sequence(self):
        # This verifies cache -> official RxReport without a live broker.
        import ocs_client
        client = ocs_client.OcsClient("127.0.0.1", 1883)
        published = []
        client._publish = lambda topic, message: published.append((topic, message)) or len(published)
        client.publish_run_declaration(["T-Wave", "T-Sky"])
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
        self.assertEqual(sky.heartbeat.roll_deg, 1.0)
        self.assertEqual(sky.heartbeat.flight_phase, ocs_client.rx_common_pb2.FLIGHT_PHASE_AIRBORNE)
        self.assertEqual(sky.heartbeat.current_task, ocs_client.rx_common_pb2.TASK_COORDINATED_LOGISTICS)
        client.publish_docking_report("T-Wave", 1)
        self.assertEqual([message.seq for _topic, message in published[1:]
                          if message.vehicle_id == "T-Wave"], [1, 2])


if __name__ == "__main__":
    unittest.main()
