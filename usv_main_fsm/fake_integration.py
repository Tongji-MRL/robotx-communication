"""In-memory end-to-end fixtures for the phase-two protocol simulation."""

from __future__ import annotations

from pathlib import Path

from OCS import fsm_protocol, vehicle_protocol

from .checkpoint_store import CheckpointStore
from .coordinator import MissionCoordinator
from .models import Action, CompletionEvent, Target, TaskId
from .ocs_adapter import OcsAdapter
from .ros2_adapter import FakeROS2Adapter
from .uav_adapter import FakeTransport, UavFsmAdapter


class FakeUAVFSM:
    """Candidate UAV endpoint; Task3 delivery is gated by real request data."""

    def __init__(self, adapter: UavFsmAdapter) -> None:
        self.adapter = adapter
        self.delivery_started = False
        self._ack_sequence = 0

    def accept(self, published) -> object:
        self._ack_sequence += 1
        is_pause = published.message["payload"]["domain_action"] == "PAUSE_TASK"
        return self.adapter.make_fake_ack(
            published, sequence=self._ack_sequence, accepted=True,
            safe_paused=is_pause,
            progress_marker="uav-safe-phase" if is_pause else None,
        )

    def accept_delivery_request(self, request: dict, *, scheduling_permitted: bool) -> bool:
        required = {"resource_color", "delivery_circle_color", "target_position"}
        if scheduling_permitted and required.issubset(request):
            self.delivery_started = True
            return True
        return False


class IntegrationHarness:
    def __init__(self, checkpoint_path: str | Path) -> None:
        self.coordinator = MissionCoordinator(CheckpointStore(checkpoint_path))
        self.ocs = OcsAdapter(self.coordinator)
        self.usv = FakeROS2Adapter()
        self.transport = FakeTransport()
        self.uav_adapter = UavFsmAdapter(self.transport)
        self.uav = FakeUAVFSM(self.uav_adapter)
        self.log: list[str] = []

    def ocs_command(self, command: str, *, run_id: int, parameters: dict | None = None,
                    message_id: str | None = None) -> None:
        envelope = vehicle_protocol.make_message(
            "T-Wave", "command", vehicle_protocol.command_payload(
                command, parameters=parameters, command_seq=1,
            ), run_id=run_id, source="ocs", message_id=message_id,
        )
        result = self.ocs.receive(vehicle_protocol.topic("T-Wave", "command"), vehicle_protocol.encode(envelope))
        self.log.append(f"OCS {command}: {result.response['payload']['state']}")
        self.dispatch(result.actions)

    def dispatch(self, actions: list[Action]) -> None:
        for action in actions:
            self.log.append(f"{action.command_id} {action.action_type.value} {action.task and action.task.value} -> {action.target.value}")
            if action.target == Target.USV:
                command = self.usv.send(action)
                ack = self.usv.ack(
                    command, accepted=True, safe_paused=action.action_type.value == "PAUSE_TASK",
                    progress_marker="usv-safe-phase" if action.action_type.value == "PAUSE_TASK" else None,
                )
                self.dispatch(self.coordinator.receive_ack(ack))
            else:
                published = self.uav_adapter.send(action)
                ack = self.uav.accept(published)
                domain_ack = self.uav_adapter.receive_ack(ack.topic, fsm_protocol.encode(ack.message))
                assert domain_ack is not None
                self.dispatch(self.coordinator.receive_ack(domain_ack))

    def complete(self, task: TaskId, event_id: str) -> None:
        self.dispatch(self.coordinator.complete_task(CompletionEvent(event_id, 42, task, Target.USV, True)))
