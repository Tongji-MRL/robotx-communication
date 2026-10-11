import sys
import unittest
import uuid
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PACKAGE_ROOT.parents[2] / "usv_main_fsm"
sys.path[:0] = [str(PACKAGE_ROOT), str(CORE_ROOT.parent)]

from twave_mission_dryrun.bridge import MissionBridge
from twave_mission_dryrun.protocol import encode, envelope


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.checkpoint = Path.cwd() / f".bridge-test-{uuid.uuid4().hex}.json"
        self.bridge = MissionBridge(self.checkpoint, self.sent.append)

    def tearDown(self):
        self.checkpoint.unlink(missing_ok=True)
        self.bridge.coordinator.safety_latch_store.path.unlink(missing_ok=True)

    def publish(self, name, payload):
        self.sent.append((name, payload))

    def test_run_start_ack_then_explicit_event_starts_task3(self):
        self.bridge.publish = self.publish
        self.bridge.handle_command(encode(envelope(run_id=42, command_id="ocs-1", command="RUN_START", parameters={})))
        command = next(payload for name, payload in self.sent if name == "usv_command")
        self.assertEqual(command["task"], "TASK1")
        self.bridge.handle_ack(encode(envelope(run_id=42, command_id=command["command_id"], target="T-Wave", accepted=True)))
        self.assertFalse(any(p.get("task") == "TASK3" for n, p in self.sent if n == "usv_command"))
        self.bridge.handle_event(encode(envelope(run_id=42, event_id="task1-finished", task="TASK1", target="T-Wave", authoritative=True, succeeded=True)))
        self.assertTrue(any(p.get("task") == "TASK3" for n, p in self.sent if n == "usv_command"))

    def test_frozen_run_start_topic_mapping_publishes_status(self):
        self.bridge.publish = self.publish
        # A command field on the frozen topic cannot select another action.
        self.bridge.handle_run_start(encode(envelope(
            run_id=42, command_id="ocs-run-42", command="SAFE_STOP", parameters={},
        )))
        self.assertTrue(any(name == "usv_command" and payload["task"] == "TASK1"
                            for name, payload in self.sent))
        self.assertTrue(any(name == "status" and payload["state"] == "RUNNING_TASK1"
                            for name, payload in self.sent))

    def test_old_run_and_duplicate_ack_do_not_advance(self):
        self.bridge.publish = self.publish
        self.bridge.handle_command(encode(envelope(run_id=42, command_id="ocs-1", command="RUN_START", parameters={})))
        command = next(payload for name, payload in self.sent if name == "usv_command")
        self.bridge.handle_ack(encode(envelope(run_id=41, command_id=command["command_id"], target="T-Wave", accepted=True)))
        self.bridge.handle_ack(encode(envelope(run_id=42, command_id=command["command_id"], target="T-Wave", accepted=True)))
        self.bridge.handle_ack(encode(envelope(run_id=42, command_id=command["command_id"], target="T-Wave", accepted=True)))
        self.assertEqual(self.bridge.coordinator.pending_command_ids, frozenset())

    def test_safe_stop_latches(self):
        self.bridge.publish = self.publish
        self.bridge.handle_command(encode(envelope(run_id=42, command_id="ocs-1", command="RUN_START", parameters={})))
        self.bridge.handle_command(encode(envelope(run_id=42, command_id="ocs-stop", command="SAFE_STOP", parameters={"reason": "test"})))
        self.bridge.handle_command(encode(envelope(run_id=43, command_id="ocs-new", command="RUN_START", parameters={})))
        self.assertEqual(self.bridge.coordinator.state.value, "SAFE_STOP")

    def test_direct_task3_start_command_is_rejected_without_task3_publication(self):
        self.bridge.publish = self.publish
        self.bridge.handle_command(encode(envelope(run_id=42, command_id="run", command="RUN_START", parameters={})))
        self.bridge.handle_command(encode(envelope(run_id=42, command_id="illegal-task3", command="START_TASK3", parameters={})))
        commands = [payload for name, payload in self.sent if name == "usv_command"]
        faults = [payload for name, payload in self.sent if name == "fault"]
        self.assertFalse(any(item["action"] == "START_TASK" and item["task"] == "TASK3" for item in commands))
        self.assertTrue(any(item["code"] == "ILLEGAL_COMMAND" for item in faults))
        self.assertEqual(self.bridge.coordinator.state.value, "RUNNING_TASK1")

    def test_safe_stop_prevents_late_task4_release_event_and_ack_from_publishing_normal_actions(self):
        self.bridge.publish = self.publish
        self.bridge.handle_command(encode(envelope(run_id=42, command_id="run", command="RUN_START", parameters={})))
        self.bridge.handle_command(encode(envelope(run_id=42, command_id="preempt", command="TASK4_PREEMPT", parameters={})))
        pause = [p for name, p in self.sent if name == "usv_command" and p["action"] == "PAUSE_TASK"][0]
        self.bridge.handle_command(encode(envelope(run_id=42, command_id="stop", command="SAFE_STOP", parameters={})))
        stop_index = len(self.sent)

        self.bridge.handle_command(encode(envelope(run_id=42, command_id="release", command="TASK4_RELEASE", parameters={
            "recovery_permitted": True, "vehicles_safe": True,
        })))
        self.bridge.handle_event(encode(envelope(run_id=42, event_id="late-task1", task="TASK1", target="T-Wave", authoritative=True, succeeded=True)))
        self.bridge.handle_ack(encode(envelope(run_id=42, command_id=pause["command_id"], target="T-Wave", accepted=True,
            safe_paused=True, progress_marker="late")))

        late_commands = [payload for name, payload in self.sent[stop_index:] if name == "usv_command"]
        self.assertEqual(late_commands, [])
        all_commands = [payload for name, payload in self.sent if name == "usv_command"]
        self.assertTrue(any(item["action"] == "SAFE_STOP" for item in all_commands))
        self.assertFalse(any(item["action"] == "START_TASK" and item["task"] in {"TASK3", "TASK4"}
                             for item in all_commands[2:]))
        self.assertEqual(self.bridge.coordinator.state.value, "SAFE_STOP")

    def test_safety_input_hold_critical_and_isolated_reset(self):
        self.bridge.publish = self.publish
        self.bridge.handle_command(encode(envelope(run_id=42, command_id="run", command="RUN_START", parameters={})))
        self.bridge.handle_safety_input(encode(envelope(run_id=42, event_id="link-lost", fault="OCS_LINK_LOST", active=True,
            trustworthy=True, source="test", detail="timeout")))
        self.assertEqual(self.bridge.coordinator.state.value, "SAFE_HOLD")
        self.bridge.handle_safety_input(encode(envelope(run_id=42, event_id="estop", fault="MANUAL_ESTOP", active=True,
            trustworthy=True, source="test", detail="operator")))
        self.assertEqual(self.bridge.coordinator.state.value, "SAFE_STOP")
        self.bridge.handle_safety_input(encode(envelope(run_id=42, event_id="estop-cleared", fault="MANUAL_ESTOP", active=False,
            clears_event_id="estop", trustworthy=True, source="test", detail="cleared")))
        self.bridge.handle_safety_input(encode(envelope(run_id=42, event_id="link-cleared", fault="OCS_LINK_LOST", active=False,
            clears_event_id="link-lost", trustworthy=True, source="test", detail="cleared")))
        self.bridge.handle_safety_input(encode(envelope(run_id=42, event_id="bad-reset", kind="RESET_SAFE_STOP", test_only=True,
            authorization_id="test", authorization_run_id=41, severe_faults_clear=True, executors_safe=True,
            failsafe_cleared=True, reinitialize_ready=True)))
        self.assertEqual(self.bridge.coordinator.state.value, "SAFE_STOP")
        self.bridge.handle_safety_input(encode(envelope(run_id=42, event_id="good-reset", kind="RESET_SAFE_STOP", test_only=True,
            authorization_id="test", authorization_run_id=42, severe_faults_clear=True, executors_safe=True,
            failsafe_cleared=True, reinitialize_ready=True)))
        self.assertEqual(self.bridge.coordinator.state.value, "IDLE")
        self.assertIsNone(self.bridge.coordinator.run_id)


if __name__ == "__main__":
    unittest.main()
