import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PACKAGE_ROOT.parents[2] / "usv_main_fsm"
sys.path[:0] = [str(PACKAGE_ROOT), str(CORE_ROOT.parent)]

from OCS import vehicle_protocol
from OCS.course_config import make_payload
from twave_mission_dryrun.bridge import MissionBridge
from twave_mission_dryrun.mqtt_runtime import TWaveMqttRuntime
from twave_mission_dryrun.protocol import encode


class TWaveMqttRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.mqtt, self.controls, self.courses = [], [], []
        self.checkpoint = Path.cwd() / f".mqtt-runtime-{uuid.uuid4().hex}.json"
        self.now = 2_000_000
        self.runtime = TWaveMqttRuntime(
            self.checkpoint, lambda topic, raw: self.mqtt.append((topic, raw)),
            lambda name, payload: self.controls.append((name, payload)),
            now_ms=lambda: self.now,
            publish_course=self.courses.append,
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

    def test_course_is_idempotent_versioned_and_never_creates_a_task_command(self):
        def send(payload, message_id):
            message = vehicle_protocol.make_message("T-Wave", "course_config", payload,
                                                    run_id=None, source="ocs", message_id=message_id)
            self.runtime.receive(vehicle_protocol.topic("T-Wave", "course_config"), vehicle_protocol.encode(message))
        first = make_payload(course_id="RX2026-A", pinger_freq_hz=27000,
                             corners=[(1, 2), (1, 3), (2, 3), (1, 2)],
                             source_sent_at=datetime(2026, 10, 17, 3, tzinfo=timezone.utc))
        send(first, "course-1")
        send(first, "course-duplicate")
        self.assertEqual(self.courses, [first])
        self.assertEqual(self.controls, [])
        older = dict(first); older["source_sent_at"] = "2026-10-17T02:00:00.000Z"
        older["pinger_freq_hz"] = 28000
        with self.assertRaisesRegex(ValueError, "old Course"):
            send(older, "course-old")
        newer = dict(first); newer["source_sent_at"] = "2026-10-17T04:00:00.000Z"
        newer["pinger_freq_hz"] = 28000
        send(newer, "course-new")
        self.assertEqual(self.courses[-1]["pinger_freq_hz"], 28000)


if __name__ == "__main__":
    unittest.main()
