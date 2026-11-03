"""Offline OCS/FSM contract tests; no ROS/DDS, MQTT broker or hardware needed."""
import unittest
from fsm_message_adapter import build_run_start, build_task4


class FsmInterfaceAlignmentTests(unittest.TestCase):
    def test_runstart_matches_fsm_contract(self):
        action = {"command": "RUN_START", "run_id": 42, "command_seq": 7}
        message = build_run_start(action)
        self.assertEqual(message["command"], "begin")
        self.assertEqual(message["schema_version"], "twave-mission-run-v1")
        self.assertEqual((message["run_id"], message["command_id"]),
                         (42, "robocommand:42:7:run-start"))
        self.assertEqual(message, build_run_start(action))

    def test_runstart_fails_closed(self):
        for action in (
            {"command": "RUN_START", "run_id": None, "command_seq": 7},
            {"command": "RUN_START", "run_id": 42, "command_seq": None},
            {"command": "RUN_START", "run_id": True, "command_seq": 7},
            {"command": "RUN_START", "run_id": 42, "command_seq": 0},
            {"command": "PING", "run_id": 42, "command_seq": 7},
        ):
            self.assertIsNone(build_run_start(action), action)

    def test_assistance_matches_fsm_task4_guard_schema(self):
        message = build_task4({
            "command": "TASK4_ASSISTANCE", "run_id": 42, "command_seq": 9,
            "parameters": {"official_command_seq": 9, "vehicle_type": 3,
                           "position": {"latitude": 1.28, "longitude": 103.85}},
        })
        self.assertEqual(message["schema_version"], "twave-mission-task4-v1")
        self.assertEqual(message["command_id"], "robocommand:42:9:assistance")
        self.assertEqual(message["vehicle"], "uav")
        self.assertEqual(message["command"]["type"], "ASSISTANCE_REQUEST")
        self.assertEqual(message["command"]["command_seq"], 9)

    def test_assistance_must_have_correlated_seq_and_position(self):
        base = {"command": "TASK4_ASSISTANCE", "run_id": 42, "command_seq": 9,
                "parameters": {"official_command_seq": 8, "vehicle_type": 1,
                               "position": {"latitude": 1.28, "longitude": 103.85}}}
        self.assertIsNone(build_task4(base))
        base["parameters"]["official_command_seq"] = 9
        base["parameters"]["position"]["longitude"] = float("nan")
        self.assertIsNone(build_task4(base))

    def test_readiness_confirm_fields(self):
        message = build_task4({
            "command": "TASK4_READINESS_CONFIRM", "run_id": 42, "command_seq": 21,
            "parameters": {"vehicle": "usv", "original_command_seq": 9,
                           "report_seq": 14},
        })
        self.assertEqual(message["command"]["type"], "READINESS_CONFIRM")
        self.assertEqual(message["command"]["original_command_seq"], 9)
        self.assertEqual(message["command"]["report_seq"], 14)
        self.assertEqual(message["command"]["official_confirmation_seq"], 21)

    def test_published_notice_fields(self):
        message = build_task4({
            "command": "TASK4_READINESS_REPORT_PUBLISHED", "run_id": 42,
            "parameters": {"vehicle": "uav", "original_command_seq": 9,
                           "report_seq": 14, "readiness_event_id": "event:readiness"},
        })
        self.assertEqual(message["command"]["type"], "READINESS_REPORT_PUBLISHED")
        self.assertEqual(message["command"]["internal_origin"], "ocs")
        self.assertEqual(message["command_id"], "event:readiness:published:14")

    def test_unimplemented_policy_not_exposed_as_actuation(self):
        for kind in ("TASK4_KEEP_OUT_ZONE", "TASK4_ALL_CLEAR", "TASK4_MOVING_OBJECT"):
            self.assertIsNone(build_task4({"command": kind, "run_id": 42,
                                           "command_seq": 12, "parameters": {}}))


if __name__ == "__main__":
    unittest.main()
