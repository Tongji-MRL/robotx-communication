"""Test-only fake executor.  It never publishes hardware control topics."""

from __future__ import annotations

import json
from typing import Any

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .protocol import ProtocolError, decode, encode, envelope


BASE = "/test/twave/mission"


class FakeUSVExecutor(Node):
    """ACKs task commands; completion/fault is emitted only by ``usv_test_in``."""

    def __init__(self) -> None:
        super().__init__("fake_usv_executor_dryrun")
        self.declare_parameter("dry_run", True)
        if self.get_parameter("dry_run").value is not True:
            raise RuntimeError("dry_run=false is forbidden by this package")
        self.ack_pub = self.create_publisher(String, f"{BASE}/usv_ack", 10)
        self.event_pub = self.create_publisher(String, f"{BASE}/usv_event", 10)
        self.fault_pub = self.create_publisher(String, f"{BASE}/fault", 10)
        self.create_subscription(String, f"{BASE}/usv_command", self._command, 10)
        self.create_subscription(String, f"{BASE}/usv_test_in", self._test_input, 10)
        self.commands: dict[str, dict[str, Any]] = {}
        self.next_ack: dict[str, Any] = {"mode": "accept"}

    def _send(self, publisher, payload: dict[str, Any]) -> None:
        msg = String(); msg.data = encode(payload); publisher.publish(msg)

    def _command(self, msg: String) -> None:
        try:
            data = decode(msg.data, required={"schema_version", "timestamp", "run_id", "command_id", "target", "action", "task", "dry_run"})
            if data["target"] != "T-Wave" or data["dry_run"] is not True:
                raise ProtocolError("only dry-run T-Wave commands are accepted")
        except ProtocolError as exc:
            self.get_logger().warning(f"rejecting malformed command: {exc}")
            return
        self.commands[data["command_id"]] = data
        policy, self.next_ack = self.next_ack, {"mode": "accept"}
        if policy.get("mode") == "drop":
            return  # exercise coordinator ACK timeout; no completion is created.
        accepted = policy.get("mode") != "reject"
        is_pause = data["action"] == "PAUSE_TASK"
        self._send(self.ack_pub, envelope(run_id=data["run_id"], command_id=data["command_id"], target="T-Wave",
            accepted=accepted, safe_paused=accepted and is_pause,
            progress_marker="fake-safe-progress" if accepted and is_pause else None,
            detail=str(policy.get("detail", "fake executor ACK")), dry_run=True))

    def _test_input(self, msg: String) -> None:
        try:
            value = json.loads(msg.data)
            if not isinstance(value, dict) or value.get("dry_run") is not True:
                raise ValueError("test input must be a dry_run object")
            kind = value["kind"]
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            self.get_logger().warning(f"invalid usv_test_in: {exc}")
            return
        if kind == "next_ack":
            if value.get("mode") not in {"accept", "reject", "drop"}:
                self.get_logger().warning("next_ack mode must be accept, reject, or drop")
                return
            self.next_ack = {"mode": value["mode"], "detail": value.get("detail", "test policy")}
        elif kind == "complete":
            task, run_id = value.get("task"), value.get("run_id")
            if not isinstance(run_id, int) or not any(c["run_id"] == run_id and c["task"] == task for c in self.commands.values()):
                self.get_logger().warning("completion has no matching received task command")
                return
            self._send(self.event_pub, envelope(run_id=run_id, event_id=str(value.get("event_id", f"fake-{task}-done")),
                task=task, target="T-Wave", authoritative=True, succeeded=bool(value.get("succeeded", True)),
                detail=str(value.get("detail", "explicit test completion")), dry_run=True))
        elif kind == "fault":
            if not isinstance(value.get("run_id"), int) or value["run_id"] <= 0:
                self.get_logger().warning("fault requires a positive integer run_id")
                return
            self._send(self.fault_pub, envelope(run_id=value["run_id"], target="T-Wave",
                code=str(value.get("code", "FAKE_FAULT")), detail=str(value.get("detail", "explicit test fault")), dry_run=True))
        else:
            self.get_logger().warning(f"unsupported test input kind: {kind}")


def main() -> None:
    rclpy.init(); node = FakeUSVExecutor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node(); rclpy.shutdown()
