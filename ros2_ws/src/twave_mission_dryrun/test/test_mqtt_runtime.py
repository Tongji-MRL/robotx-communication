import sys
import unittest
import uuid
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PACKAGE_ROOT.parents[2] / "usv_main_fsm"
sys.path[:0] = [str(PACKAGE_ROOT), str(CORE_ROOT.parent)]

from OCS import vehicle_protocol
from twave_mission_dryrun.bridge import MissionBridge
from twave_mission_dryrun.mqtt_runtime import TWaveMqttRuntime
from twave_mission_dryrun.protocol import encode


class TWaveMqttRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.mqtt, self.controls = [], []
        self.checkpoint = Path.cwd() / f".mqtt-runtime-{uuid.uuid4().hex}.json"
        self.now = 2_000_000
        self.runtime = TWaveMqttRuntime(
            self.checkpoint, lambda topic, raw: self.mqtt.append((topic, raw)),
            lambda name, payload: self.controls.append((name, payload)),
            now_ms=lambda: self.now,
        )

    def tearDown(self):
        self.checkpoint.unlink(missing_ok=True)
        if hasattr(self, "bridge"):
            self.bridge.coordinator.safety_latch_store.path.unlink(missing_ok=True)

    def command(self, command, *, run_id=42, seq=1, message_id=None, sent_at=None, parameters=None):
        message = vehicle_protocol.make_message(
            "T-Wave", "command", vehicle_protocol.command_payload(
                command, command_seq=seq, parameters=parameters,
            ), run_id=run_id, source="ocs", message_id=message_id,
        )
        message["sent_at_unix_ms"] = self.now if sent_at is None else sent_at
        self.runtime.receive(vehicle_protocol.topic("T-Wave", "command"), vehicle_protocol.encode(message))
        return vehicle_protocol.decode(self.mqtt[-1][1])

    def test_run_start_creates_frozen_topic_and_status_becomes_ocs_report(self):
        ack = self.command("run_start", seq=9, message_id="run-42")
        self.assertEqual(ack["kind"], "ack")
        self.assertTrue(ack["payload"]["accepted"])
        self.assertEqual(ack["payload"]["command_seq"], 9)
        self.assertEqual(self.controls[-1][0], "run_start")
        self.assertEqual(self.controls[-1][1]["command"], "RUN_START")
        self.runtime.receive_mission_report("status", {"run_id": 42, "state": "RUNNING_TASK1"})
        report = vehicle_protocol.decode(self.mqtt[-1][1])
        self.assertEqual(report["kind"], "task_report")
        self.assertEqual(report["payload"]["state"], "RUNNING_TASK1")

    def test_fake_robocommand_run_start_to_mission_status_to_ocs_report(self):
        """RoboCommand -> run_start -> coordinator status -> OCS report."""
        def coordinator_output(name, payload):
            if name in {"status", "task_report", "fault"}:
                self.runtime.receive_mission_report(name, payload)

        self.bridge = MissionBridge(self.checkpoint, coordinator_output)

        def deliver(name, payload):
            self.assertEqual(name, "run_start")
            self.bridge.handle_run_start(encode(payload))

        self.runtime.publish_mission = deliver
        ack = self.command("run_start", seq=9, message_id="fake-robocommand-run")
        self.assertTrue(ack["payload"]["accepted"])
        reports = [vehicle_protocol.decode(raw) for _topic, raw in self.mqtt[:-1]]
        self.assertTrue(any(
            report["kind"] == "task_report" and report["payload"]["state"] == "RUNNING_TASK1"
            for report in reports
        ))

    def test_duplicate_stale_old_sequence_and_old_run_are_rejected_or_safe(self):
        self.command("run_start", seq=10, message_id="start")
        duplicate = self.command("run_start", seq=10, message_id="start")
        self.assertEqual(duplicate["payload"]["state"], "DUPLICATE")
        old_sequence = self.command("task4_assistance", seq=9, message_id="old-seq")
        self.assertFalse(old_sequence["payload"]["accepted"])
        stale = self.command("task4_assistance", seq=11, message_id="stale", sent_at=self.now - 301_000)
        self.assertIn("stale", stale["payload"]["detail"])
        old_run = self.command("task4_assistance", run_id=41, seq=12, message_id="old-run")
        self.assertFalse(old_run["payload"]["accepted"])

    def test_task4_pending_policy_does_not_freeze_uav_or_resume(self):
        self.command("run_start", seq=1)
        controls_before = len(self.controls)
        ack = self.command("task4_all_clear", seq=2)
        self.assertTrue(ack["payload"]["accepted"])
        self.assertEqual(ack["payload"]["state"], "RECEIVED_PENDING_RECOVERY_POLICY")
        self.assertEqual(len(self.controls), controls_before)

    def test_task4_command_creates_only_frozen_task4_topic(self):
        self.command("run_start", seq=1)
        ack = self.command("task4_assistance", seq=2)
        self.assertTrue(ack["payload"]["accepted"])
        self.assertEqual(self.controls[-1][0], "task4_cmd")


if __name__ == "__main__":
    unittest.main()
