import time
import unittest

from monitor_ui import MonitorState


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


if __name__ == "__main__":
    unittest.main()
