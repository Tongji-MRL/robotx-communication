"""rclpy node wrapper; all mission decisions stay in :mod:`MissionBridge`."""

from __future__ import annotations

from pathlib import Path
import os

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .bridge import MissionBridge
from .protocol import encode
from usv_main_fsm.audit_log import AuditLogger


INTERNAL_BASE = "/test/twave/mission"
MISSION_BASE = "/tongji_mrl/mission"


class MissionCoordinatorNode(Node):
    def __init__(self) -> None:
        super().__init__("twave_mission_coordinator_dryrun")
        self.declare_parameter("dry_run", True)
        default_state = Path(os.environ.get("TWAVE_MISSION_STATE_DIR", Path.home() / ".local/state/twave-mission"))
        default_log = Path(os.environ.get("TWAVE_MISSION_LOG_DIR", Path.home() / "robotx_logs/twave-mission"))
        self.declare_parameter("checkpoint_path", str(default_state / "checkpoint.json"))
        if self.get_parameter("dry_run").value is not True:
            raise RuntimeError("dry_run=false is forbidden by this package")
        self._mission_publishers = {
            "usv_command": self.create_publisher(String, f"{INTERNAL_BASE}/usv_command", 10),
            "status": self.create_publisher(String, f"{MISSION_BASE}/status", 10),
            "task_report": self.create_publisher(String, f"{MISSION_BASE}/task_report", 10),
            "fault": self.create_publisher(String, f"{MISSION_BASE}/fault", 10),
        }
        self.bridge = MissionBridge(Path(self.get_parameter("checkpoint_path").value), self._publish, AuditLogger(default_log))
        self.create_subscription(String, f"{MISSION_BASE}/run_start", self._run_start, 10)
        self.create_subscription(String, f"{MISSION_BASE}/task4_cmd", self._task4_cmd, 10)
        self.create_subscription(String, f"{INTERNAL_BASE}/usv_ack", self._ack, 10)
        self.create_subscription(String, f"{INTERNAL_BASE}/usv_event", self._event, 10)
        self.create_subscription(String, f"{INTERNAL_BASE}/fault", self._fault, 10)
        self.create_subscription(String, f"{INTERNAL_BASE}/safety_input", self._safety_input, 10)
        self.create_timer(0.25, self.bridge.tick)
        self.bridge._publish_state("startup: no movement is resumed")

    def _publish(self, name: str, payload: dict) -> None:
        msg = String()
        msg.data = encode(payload)
        self._mission_publishers[name].publish(msg)

    def _run_start(self, msg: String) -> None:
        self.bridge.handle_run_start(msg.data)

    def _task4_cmd(self, msg: String) -> None:
        self.bridge.handle_task4_cmd(msg.data)

    def _ack(self, msg: String) -> None:
        self.bridge.handle_ack(msg.data)

    def _event(self, msg: String) -> None:
        self.bridge.handle_event(msg.data)

    def _fault(self, msg: String) -> None:
        self.bridge.handle_fault(msg.data)

    def _safety_input(self, msg: String) -> None:
        self.bridge.handle_safety_input(msg.data)


def main() -> None:
    rclpy.init()
    node = MissionCoordinatorNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
