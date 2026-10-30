import time
import unittest
from monitor_ui import MonitorState, MqttMonitor
from ros2_status_mqtt_adapter import build_envelope
from tools.local_fsm_simulator import SCENARIOS, status_for
from vehicle_protocol import decode, encode, make_message, topic

def status(**changes):
    result = {"schema_version":"twave-mission-status-v2","run_id":7,"timestamp":"2026-10-21T00:00:00Z","fsm_state":"TASK4_EXECUTE","course":{"course_id":"C1","fingerprint":"abc","fsm_accepted":True,"uav_applied":False,"uav_application_state":"NOT_CONFIRMED"},"safety":{"state":"WAITING_SAFE_PAUSE","recovery_conditions":["pause_ack_uav"]},"vehicles":{"usv":{"current_task":"TASK4","progress":"PAUSED","error":None},"uav":{"current_task":"TASK1","progress":"PAUSED","error":None}},"legacy":{"mission_planner":"TASK4_EXECUTE","uav":{},"usv":{}}}
    result.update(changes); return result

class FsmMonitorTests(unittest.TestCase):
    def test_mission_status_protocol_round_trip(self):
        msg=make_message("T-Wave","mission_status",status(),run_id=7)
        self.assertEqual(decode(encode(msg)),msg); self.assertEqual(topic("T-Wave","mission_status"),"tongji/robotx/v1/T-Wave/mission_status")
    def test_status_maps_course_and_safety_without_uav_inference(self):
        state=MonitorState(); state.note_message(topic("T-Wave","mission_status"),make_message("T-Wave","mission_status",status(),run_id=7))
        s=state.snapshot(); self.assertTrue(s["mission_status"]["online"]); self.assertFalse(s["mission"]["course"]["uav_applied"]); self.assertEqual(s["mission"]["safety"]["state"],"WAITING_SAFE_PAUSE")
    def test_invalid_status_rejected(self):
        state=MonitorState()
        with self.assertRaises(ValueError): state.note_message("x",make_message("T-Wave","mission_status",{"schema_version":"bad"}))
        self.assertIsNone(state.snapshot()["mission_status"]["last_received_unix_ms"])
        incomplete = status(); incomplete.pop("legacy")
        with self.assertRaises(ValueError): state.note_message("x", make_message("T-Wave", "mission_status", incomplete, run_id=7))
        self.assertIsNone(state.snapshot()["mission_status"]["last_received_unix_ms"])
    def test_status_times_out_independently_of_broker(self):
        state=MonitorState(stale_after_s=0.001); state.note_message("x",make_message("T-Wave","mission_status",status(),run_id=7)); time.sleep(.01)
        self.assertFalse(state.snapshot()["mission_status"]["online"])

    def test_default_monitor_rejects_even_ping(self):
        with self.assertRaises(PermissionError):
            MqttMonitor(MonitorState(), "127.0.0.1", 1883).send_command("ping")

    def test_optional_adapter_keeps_full_v2_payload(self):
        raw = __import__("json").dumps(status())
        envelope = build_envelope(raw)
        self.assertEqual(envelope["kind"], "mission_status")
        self.assertEqual(envelope["payload"], status())

    def test_legacy_state_snapshot_keys_remain_available(self):
        snapshot = MonitorState().snapshot()
        self.assertTrue({"broker", "vehicles", "course", "messages", "commands"}.issubset(snapshot))

    def test_local_simulator_uses_full_status_v2_contract(self):
        for scenario in SCENARIOS:
            if scenario == "DISCONNECTED":
                continue
            payload = status_for(scenario)
            self.assertEqual(payload["schema_version"], "twave-mission-status-v2")
            self.assertTrue(payload["simulation"])
            self.assertTrue(all(name in payload for name in ("run_id", "fsm_state", "course", "safety", "vehicles", "legacy")))

    def test_simulated_course_does_not_claim_uav_application(self):
        payload = status_for("COURSE_ACCEPTED")
        self.assertTrue(payload["course"]["fsm_accepted"])
        self.assertFalse(payload["course"]["uav_applied"])
        self.assertEqual(status_for("TASK4_WAITING")["safety"]["state"], "WAITING_SAFE_PAUSE")

    def test_simulator_scenario_mapping_uses_real_fsm_names(self):
        self.assertEqual(status_for("WAIT_COURSE")["fsm_state"], "WAIT_FOR_BEGIN")
        self.assertEqual(status_for("WAIT_RUN_START")["fsm_state"], "WAIT_FOR_BEGIN")
        self.assertEqual(status_for("TASK1_ACTIVE")["fsm_state"], "TASK1_EXECUTE")
        self.assertEqual(status_for("TASK3_ACTIVE")["fsm_state"], "TASK3_EXECUTE")
        self.assertEqual(status_for("TASK4_PAUSED")["vehicles"]["usv"]["progress"], "PAUSED")
        fault = status_for("FAULT")
        self.assertEqual((fault["fsm_state"], fault["safety"]["state"]), ("FAILED", "SAFE_STOP"))

if __name__ == "__main__": unittest.main()
