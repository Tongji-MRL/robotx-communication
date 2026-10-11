import unittest
from pathlib import Path

from OCS import fsm_protocol, vehicle_protocol

from usv_main_fsm.checkpoint_store import CheckpointStore
from usv_main_fsm.coordinator import MissionCoordinator
from usv_main_fsm.models import Action, ActionType, MainState, Target, TaskId
from usv_main_fsm.ocs_adapter import OcsAdapter
from usv_main_fsm.uav_adapter import FakeTransport, UavFsmAdapter


class ProtocolAdapterTests(unittest.TestCase):
    def setUp(self):
        self.path = Path.cwd() / "usv_main_fsm" / ".protocol-checkpoint.json"
        self.path.unlink(missing_ok=True)
        self.coordinator = MissionCoordinator(CheckpointStore(self.path))

    def tearDown(self):
        self.path.unlink(missing_ok=True)

    @staticmethod
    def action(command_id="42-1", action_type=ActionType.START_TASK, task=TaskId.TASK1):
        return Action(command_id, 42, Target.UAV, action_type, task, 1.0)

    def test_uav_mapping_round_trip_ack_and_transport_deduplication(self):
        transport = FakeTransport()
        adapter = UavFsmAdapter(transport)
        sent = adapter.send(self.action())
        self.assertEqual(sent.topic, "tongji/robotx/fsm/v1/T-Wave/T-Sky/command")
        self.assertEqual(sent.message["payload"]["command_id"], "42-1")
        self.assertTrue(sent.message["payload"]["candidate_mapping"])
        self.assertFalse(transport.publish(sent.topic, fsm_protocol.encode(sent.message)))
        ack = adapter.make_fake_ack(sent, sequence=2, accepted=True)
        domain_ack = adapter.receive_ack(ack.topic, fsm_protocol.encode(ack.message))
        self.assertEqual(domain_ack.command_id, "42-1")
        self.assertTrue(domain_ack.accepted)

    def test_uav_rejects_wrong_target_and_out_of_order_ack(self):
        adapter = UavFsmAdapter(FakeTransport())
        wrong = Action("x", 42, Target.USV, ActionType.START_TASK, TaskId.TASK1, 1.0)
        with self.assertRaises(ValueError):
            adapter.send(wrong)
        one = adapter.send(self.action("42-1"))
        two = adapter.send(self.action("42-2"))
        newest = adapter.make_fake_ack(two, sequence=4, accepted=True)
        self.assertIsNotNone(adapter.receive_ack(newest.topic, fsm_protocol.encode(newest.message)))
        old = adapter.make_fake_ack(one, sequence=3, accepted=True)
        self.assertIsNone(adapter.receive_ack(old.topic, fsm_protocol.encode(old.message)))

    def test_ocs_adapter_validates_topic_target_run_and_duplicate(self):
        adapter = OcsAdapter(self.coordinator)
        envelope = vehicle_protocol.make_message(
            "T-Wave", "command", vehicle_protocol.command_payload("run_start", command_seq=9),
            run_id=42, source="ocs", message_id="run-start-1",
        )
        result = adapter.receive(vehicle_protocol.topic("T-Wave", "command"), vehicle_protocol.encode(envelope))
        self.assertEqual(len(result.actions), 2)
        self.assertTrue(result.response["payload"]["accepted"])
        duplicate = adapter.receive(vehicle_protocol.topic("T-Wave", "command"), vehicle_protocol.encode(envelope))
        self.assertEqual(duplicate.actions, [])
        self.assertEqual(duplicate.response["payload"]["state"], "DUPLICATE")
        with self.assertRaises(ValueError):
            adapter.receive(vehicle_protocol.topic("T-Wave", "command"), vehicle_protocol.encode(
                vehicle_protocol.make_message("T-Sky", "command", vehicle_protocol.command_payload("run_start"), run_id=42)
            ))
        with self.assertRaises(ValueError):
            adapter.receive(vehicle_protocol.topic("T-Wave", "command"), vehicle_protocol.encode(
                vehicle_protocol.make_message("T-Wave", "command", vehicle_protocol.command_payload("run_start"), run_id=42, source="unknown")
            ))
        old = vehicle_protocol.make_message("T-Wave", "command", vehicle_protocol.command_payload("task4_assistance"), run_id=41, source="ocs")
        rejected = adapter.receive(vehicle_protocol.topic("T-Wave", "command"), vehicle_protocol.encode(old))
        self.assertFalse(rejected.response["payload"]["accepted"])

    def test_ocs_candidate_task_report_and_fault_keep_existing_envelope(self):
        report = OcsAdapter.candidate_task_report(42, {"task": "TASK1", "phase": "RUNNING"})
        fault = OcsAdapter.candidate_fault(42, {"code": "LINK_LOST"})
        self.assertEqual(vehicle_protocol.decode(vehicle_protocol.encode(report))["kind"], "task_report")
        self.assertEqual(vehicle_protocol.decode(vehicle_protocol.encode(fault))["kind"], "fault")

    def test_task4_clear_is_parsed_but_never_auto_preempts_or_resumes(self):
        adapter = OcsAdapter(self.coordinator)
        start = vehicle_protocol.make_message("T-Wave", "command", vehicle_protocol.command_payload("run_start"), run_id=42, source="ocs")
        adapter.receive(vehicle_protocol.topic("T-Wave", "command"), vehicle_protocol.encode(start))
        clear = vehicle_protocol.make_message("T-Wave", "command", vehicle_protocol.command_payload("task4_all_clear"), run_id=42, source="ocs")
        result = adapter.receive(vehicle_protocol.topic("T-Wave", "command"), vehicle_protocol.encode(clear))
        self.assertEqual(result.actions, [])
        self.assertTrue(result.response["payload"]["accepted"])
        self.assertEqual(self.coordinator.state, MainState.RUNNING_TASK1)

    def test_uav_rejection_reaches_safe_hold_via_domain_ack(self):
        self.coordinator.start_run(42)
        action = next(item for item in self.coordinator._pending.values() if item.target == Target.UAV)
        adapter = UavFsmAdapter(FakeTransport())
        sent = adapter.send(action)
        rejected = adapter.make_fake_ack(sent, sequence=1, accepted=False, detail="UAV busy")
        self.coordinator.receive_ack(adapter.receive_ack(rejected.topic, fsm_protocol.encode(rejected.message)))
        self.assertEqual(self.coordinator.state, MainState.SAFE_HOLD)


if __name__ == "__main__":
    unittest.main()
