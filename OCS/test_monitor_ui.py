import time
import unittest
import json

from monitor_ui import MonitorState
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
        self.assertEqual(snapshot["messages"][0]["direction"], "in")

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
