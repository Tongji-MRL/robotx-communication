import time
import unittest
import json
from types import SimpleNamespace

from monitor_ui import MonitorState, MqttMonitor, UAV_STATUS_MQTT_TOPIC
from vehicle_link import heartbeat_envelope


class MonitorStateTests(unittest.TestCase):
    def heartbeat(self, vehicle_id="T-Wave", sent_at=None):
        sent_at = sent_at or int(time.time() * 1000)
        return {
            "protocol_version": "1",
            "message_id": f"hb-{vehicle_id}-{sent_at}",
            "sent_at_unix_ms": sent_at,
            "run_id": None,
            "vehicle_id": vehicle_id,
            "source": vehicle_id,
            "frame_id": "wgs84",
            "kind": "heartbeat",
            "payload": {
                "source_mode": "simulation",
                "vehicle_type": "usv" if vehicle_id == "T-Wave" else "uav",
                "state": "AUTO",
                "position": {"frame_id": "wgs84", "latitude_deg": 1.28,
                              "longitude_deg": 103.85, "altitude_hae_m": 0.0},
                "speed_mps": 0.0, "heading_deg": 0.0, "roll_deg": 0.0,
                "pitch_deg": 0.0, "health": {"simulator": True},
            },
        }

    def test_heartbeat_updates_vehicle_snapshot(self):
        state = MonitorState()
        state.note_message("tongji/robotx/v1/T-Wave/heartbeat", self.heartbeat())
        snapshot = state.snapshot()
        self.assertTrue(snapshot["vehicles"]["T-Wave"]["online"])
        self.assertEqual(snapshot["vehicles"]["T-Wave"]["heartbeat"]["state"], "AUTO")

    def test_uav_status_is_displayed_separately_from_official_heartbeat(self):
        raw = json.dumps({"vehicle_id": "UAV1", "vehicle_type": "uav", "state": "AUTO", "flight_phase": "AIRBORNE", "position": {"latitude": 1.2, "longitude": 103.8}, "altitude_hae_m": 20, "spd_mps": 4, "heading_deg": 90, "battery_status": {"remaining_percent": 70, "warning": "TEST/SIMULATED"}})
        state = MonitorState()
        state.note_uav_status(raw, source_vehicle_id="UAV1")
        snapshot = state.snapshot()
        self.assertTrue(snapshot["uav_status_online"])
        self.assertEqual(snapshot["uav_status"]["battery_status"]["remaining_percent"], 70)
        self.assertEqual(snapshot["messages"][0]["direction"], "in")

    def test_uav_status_stales_without_fabricating_heartbeat(self):
        raw = json.dumps({"vehicle_id": "UAV1", "vehicle_type": "uav", "state": "AUTO", "flight_phase": "AIRBORNE", "position": {"latitude": 1.2, "longitude": 103.8}, "altitude_hae_m": 20, "spd_mps": 4, "heading_deg": 90})
        state = MonitorState(stale_after_s=0.1)
        state.note_uav_status(raw, source_vehicle_id="UAV1")
        state.uav_status_received_monotonic -= 1.0
        snapshot = state.snapshot()
        self.assertFalse(snapshot["uav_status_online"])
        self.assertIsNone(snapshot["uav_status"]["official_heartbeat"])

    def test_mqtt_monitor_requires_explicit_uav_mapping(self):
        state = MonitorState()
        monitor = MqttMonitor(state, "127.0.0.1", 1884)
        monitor._on_message(None, None, SimpleNamespace(topic=UAV_STATUS_MQTT_TOPIC, payload=b"{}"))
        self.assertIsNone(state.snapshot()["uav_status"])
        self.assertEqual(state.snapshot()["messages"][0]["direction"], "error")

    def test_outgoing_command_is_kept_in_command_history(self):
        state = MonitorState()
        message = {
            "message_id": "cmd-1",
            "sent_at_unix_ms": 1_000,
            "vehicle_id": "T-Wave",
            "payload": {"command": "ping"},
        }
        state.note_command("tongji/robotx/v1/T-Wave/command", message)
        snapshot = state.snapshot()
        self.assertEqual(snapshot["commands"][0]["command"]["command"], "ping")
        self.assertEqual(snapshot["messages"][0]["direction"], "out")

    def test_raw_formal_heartbeat_and_current_fsm_status_are_displayed(self):
        raw = self.heartbeat()["payload"]
        raw["sent_at_unix_ms"] = int(time.time() * 1000)
        raw["message_id"] = "raw-wave-1"
        envelope = heartbeat_envelope("/tongji_mrl/twave/heartbeat", json.dumps(raw))
        state = MonitorState()
        state.note_message("/tongji_mrl/twave/heartbeat", envelope)
        state.note_fsm_status(json.dumps({"mission_planner": "MAP_EXECUTE", "uav": None, "usv": None}))
        snapshot = state.snapshot()
        self.assertTrue(snapshot["vehicles"]["T-Wave"]["online"])
        self.assertEqual(snapshot["mission"]["mission_planner"], "MAP_EXECUTE")

    def test_fsm_fault_is_latched_across_a_later_heartbeat(self):
        state = MonitorState()
        state.note_fsm_fault(json.dumps({
            "vehicle": "usv", "run_id": 42, "error": "actuator timeout",
            "error_code": "ACT_TIMEOUT", "error_severity": "CRITICAL",
            "recommended_action": "hold position", "safety_state": "SAFE_HOLD",
        }))
        state.note_message("/tongji_mrl/twave/heartbeat", self.heartbeat("T-Wave"))
        snapshot = state.snapshot()
        self.assertEqual(snapshot["vehicles"]["T-Wave"]["status"], "SAFE_HOLD")
        self.assertEqual(snapshot["vehicles"]["T-Wave"]["last_fault"]["error_code"], "ACT_TIMEOUT")
        self.assertEqual(snapshot["fsm_fault"]["recommended_action"], "hold position")

    def test_invalid_fsm_fault_is_rejected_without_state_change(self):
        state = MonitorState()
        with self.assertRaisesRegex(ValueError, "fault"):
            state.note_fsm_fault("[]")
        self.assertIsNone(state.snapshot()["fsm_fault"])


if __name__ == "__main__":
    unittest.main()
