#!/usr/bin/env python3
"""Bridge the official RoboCommand link, ROS 2 mission API, and MQTT telemetry.

The gateway is intentionally thin:

* official RxCommand/RunStart is decoded by ``OcsClient``;
* validated Course/RunStart/supported Task4 actions use the formal ROS 2 API;
* MQTT is retained only for raw vehicle heartbeat telemetry;
* task selection and Task 4 arbitration remain inside the USV.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

from ocs_client import (
    DEFAULT_CONFIG,
    OcsClient,
    config_values,
    declaration_values,
    load_config,
)
from vehicle_link import VehicleLink


MISSION_TOPICS = {
    "course": "/tongji_mrl/mission/course_config",
    "run_start": "/tongji_mrl/mission/run_start",
    "task4": "/tongji_mrl/mission/task4_cmd",
    "status": "/tongji_mrl/mission/status",
    "task_report": "/tongji_mrl/mission/task_report",
    "fault": "/tongji_mrl/mission/fault",
}


class Ros2MissionLink:
    """Non-blocking adapter for the frozen FSM ROS 2 String/JSON interface.

    Imports are deliberately lazy: Windows installations without ROS 2 can
    still run the official/MQTT diagnostics and report that mission transport
    is unavailable.  This class never falls back to MQTT for mission traffic.
    """

    def __init__(self, on_status, on_task_report, on_fault=None) -> None:
        self.error: str | None = None
        self.available = False
        self._rclpy = None
        self._node = None
        self._thread: threading.Thread | None = None
        self._course_payload: str | None = None
        try:
            import rclpy
            from rclpy.node import Node
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from std_msgs.msg import String
        except ImportError as exc:
            self.error = f"ROS 2 unavailable: {exc}"
            return

        class MissionNode(Node):
            def __init__(node_self) -> None:
                super().__init__("robotx_ocs_mission_gateway")
                course_qos = QoSProfile(
                    depth=1,
                    reliability=ReliabilityPolicy.RELIABLE,
                    durability=DurabilityPolicy.TRANSIENT_LOCAL,
                )
                node_self.course_pub = node_self.create_publisher(String, MISSION_TOPICS["course"], course_qos)
                node_self.run_start_pub = node_self.create_publisher(String, MISSION_TOPICS["run_start"], 10)
                node_self.task4_pub = node_self.create_publisher(String, MISSION_TOPICS["task4"], 10)
                node_self.create_subscription(String, MISSION_TOPICS["status"], lambda msg: self._safe_callback(on_status, msg.data, "status"), 10)
                node_self.create_subscription(String, MISSION_TOPICS["task_report"], lambda msg: self._safe_callback(on_task_report, msg.data, "task_report"), 10)
                if on_fault is not None:
                    node_self.create_subscription(String, MISSION_TOPICS["fault"], lambda msg: self._safe_callback(on_fault, msg.data, "fault"), 10)

        try:
            rclpy.init(args=None)
            self._node = MissionNode()
            self._rclpy = rclpy
            self.available = True
            self._thread = threading.Thread(target=self._spin, name="ocs-ros2-spin", daemon=True)
            self._thread.start()
        except Exception as exc:  # Keep the OCS alive when local ROS discovery is unavailable.
            self.error = f"ROS 2 initialization failed: {exc}"
            if rclpy.ok():
                rclpy.shutdown()

    def _spin(self) -> None:
        assert self._rclpy is not None and self._node is not None
        try:
            self._rclpy.spin(self._node)
        except Exception as exc:
            self.error = f"ROS 2 spin failed: {exc}"
            self.available = False

    def _safe_callback(self, callback, raw: str, name: str) -> None:
        try:
            callback(raw)
        except Exception as exc:
            self.error = f"invalid FSM {name}: {exc}"
            if self._node is not None:
                self._node.get_logger().error(self.error)

    def publish_course(self, payload: dict) -> bool:
        if not self.available or self._node is None:
            return False
        self._course_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        message = self._string(self._course_payload)
        # Transient Local retains the latest validated Course for a late FSM
        # subscriber; subscription count is logged but never treated as an ACK.
        if self._node.course_pub.get_subscription_count() == 0:
            return False
        self._node.course_pub.publish(message)
        return True

    def republish_course(self) -> bool:
        if self._course_payload is None or not self.available or self._node is None:
            return False
        self._node.course_pub.publish(self._string(self._course_payload))
        return True

    def publish_action(self, action: dict) -> tuple[bool, str | None]:
        if not self.available or self._node is None:
            return False, self.error or "ROS 2 mission transport is unavailable"
        command = action.get("command")
        if command == "RUN_START":
            if self._node.run_start_pub.get_subscription_count() == 0:
                return False, "no matching FSM RunStart subscriber"
            # This is intentionally the entire frozen FSM contract.
            self._node.run_start_pub.publish(self._string('{"command":"begin"}'))
            return True, None
        task4 = self._task4_payload(action)
        if task4 is None:
            return False, f"FSM has no supported ROS2 Task4 mapping for {command}"
        if self._node.task4_pub.get_subscription_count() == 0:
            return False, "no matching FSM Task4 subscriber"
        self._node.task4_pub.publish(self._string(json.dumps(task4, ensure_ascii=False, separators=(",", ":"))))
        return True, None

    @staticmethod
    def _task4_payload(action: dict) -> dict | None:
        parameters = dict(action.get("parameters") or {})
        if action.get("command") == "TASK4_ASSISTANCE":
            vehicle = {1: "usv", 3: "uav"}.get(parameters.get("vehicle_type"))
            position, command_seq = parameters.get("position"), parameters.get("official_command_seq")
            if vehicle is None or not isinstance(position, dict) or not isinstance(command_seq, int) or command_seq <= 0:
                return None
            return {"vehicle": vehicle, "task": "TASK4", "command": {"type": "ASSISTANCE_REQUEST", "command_seq": command_seq, "position": position}}
        if action.get("command") == "TASK4_READINESS_CONFIRM":
            report_seq = parameters.get("report_seq")
            original_command_seq = parameters.get("original_command_seq")
            vehicle = parameters.get("vehicle")
            if (
                not isinstance(report_seq, int) or report_seq <= 0
                or not isinstance(original_command_seq, int) or original_command_seq <= 0
                or vehicle not in {"usv", "uav"}
            ):
                return None
            return {
                "schema_version": "twave-mission-task4-v1",
                "run_id": action.get("run_id"),
                "command_id": f"robocommand:{action.get('command_seq')}:readiness-confirm",
                "vehicle": vehicle,
                "task": "TASK4",
                "command": {
                    "type": "READINESS_CONFIRM",
                    "command_seq": original_command_seq,
                    "original_command_seq": original_command_seq,
                    "report_seq": report_seq,
                },
            }
        if action.get("command") == "TASK4_READINESS_REPORT_PUBLISHED":
            report_seq = parameters.get("report_seq")
            original_command_seq = parameters.get("original_command_seq")
            readiness_event_id = parameters.get("readiness_event_id")
            vehicle = parameters.get("vehicle")
            if (
                not isinstance(report_seq, int) or report_seq <= 0
                or not isinstance(original_command_seq, int) or original_command_seq <= 0
                or not isinstance(readiness_event_id, str) or not readiness_event_id
                or vehicle not in {"usv", "uav"}
                or not isinstance(action.get("run_id"), int) or action["run_id"] <= 0
            ):
                return None
            return {
                "schema_version": "twave-mission-task4-v1",
                "run_id": action["run_id"],
                "command_id": f"{readiness_event_id}:published:{report_seq}",
                "vehicle": vehicle,
                "task": "TASK4",
                "command": {
                    "type": "READINESS_REPORT_PUBLISHED",
                    "command_seq": original_command_seq,
                    "report_seq": report_seq,
                    "readiness_event_id": readiness_event_id,
                    "internal_origin": "ocs",
                },
            }
        return None

    @staticmethod
    def _string(data: str):
        from std_msgs.msg import String
        message = String()
        message.data = data
        return message

    def close(self) -> None:
        if self._node is not None:
            self._node.destroy_node()
        if self._rclpy is not None and self._rclpy.ok():
            self._rclpy.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def diagnostics(self) -> dict[str, dict[str, int | bool]]:
        """Endpoint discovery only; it is not proof that any message arrived."""
        if not self.available or self._node is None:
            return {name: {"available": False, "matches": 0} for name in MISSION_TOPICS}
        publishers = {"course": self._node.course_pub, "run_start": self._node.run_start_pub, "task4": self._node.task4_pub}
        return {name: {"available": True, "matches": int(publishers[name].get_subscription_count()) if name in publishers else self._node.count_publishers(MISSION_TOPICS[name])} for name in MISSION_TOPICS}


class OcsGateway:
    def __init__(
        self,
        *,
        official_broker: str,
        official_port: int,
        internal_broker: str,
        internal_port: int,
        team_id: str = "TONG",
        mission_coordinator: str = "T-Wave",
        internal_command_topic: str | None = None,
        internal_subscription_topic: str | None = None,
        internal_username: str | None = None,
        internal_password: str | None = None,
    ) -> None:
        self.ocs = OcsClient(
            official_broker,
            official_port,
            team_id=team_id,
            mission_coordinator=mission_coordinator,
        )
        self.ros2 = Ros2MissionLink(self.ocs.accept_fsm_status, self.ocs.accept_fsm_task_report, self.ocs.accept_fsm_fault)
        self.pending_course: dict | None = None
        self.pending_control_actions: list[dict] = []
        self.vehicle_link = VehicleLink(
            internal_broker,
            internal_port,
            on_message=self.ocs.accept_vehicle_envelope,
            subscription_topic=internal_subscription_topic,
            username=internal_username,
            password=internal_password,
            active_run_id=lambda: self.ocs.run_id,
        )

    def connect(self) -> None:
        self.ocs.connect()
        self.vehicle_link.connect()
        # Course is synchronized through the retained ROS 2 publisher only.
        self.ocs.queue_course_sync()

    def publish_declaration(
        self,
        vehicle_ids: list[str],
        task_tiers: tuple[str, str, str, str],
        uav_geofence: list[tuple[float, float]],
        uav_geofence_max_altitude_hae_m: float | None,
        uav_pilot_callsign: str | None,
    ) -> None:
        self.ocs.publish_run_declaration(
            vehicle_ids, task_tiers, uav_geofence,
            uav_geofence_max_altitude_hae_m=uav_geofence_max_altitude_hae_m,
            uav_pilot_callsign=uav_pilot_callsign,
        )

    def flush_commands(self) -> None:
        for action in self.ocs.drain_internal_actions():
            if action.get("vehicle_id") != self.ocs.mission_coordinator:
                raise ValueError(
                    "OCS gateway refuses to send a command directly to a non-USV vehicle"
                )
            if action.get("kind") == "course_config":
                self.pending_course = action["payload"]
            else:
                sent, reason = self.ros2.publish_action(action)
                if not sent:
                    print(f"[ROS2] action {action.get('command')} not published: {reason}")
                    self.pending_control_actions.append({"action": action, "state": "NOT_SUBMITTED", "reason": reason})
                else:
                    self.pending_control_actions.append({"action": action, "state": "SUBMITTED_UNCONFIRMED", "reason": None})
        if self.pending_course is not None:
            if self.ros2.publish_course(self.pending_course):
                self.pending_course = None
            elif self.ros2.available:
                print("[ROS2] Course pending: no matching FSM subscriber")

    def run(self, duration: float = 0.0) -> None:
        deadline = time.monotonic() + duration if duration else None
        next_heartbeat = time.monotonic()
        while deadline is None or time.monotonic() < deadline:
            self.flush_commands()
            if time.monotonic() >= next_heartbeat:
                self.ocs.publish_cached_heartbeats()
                next_heartbeat = time.monotonic() + 0.5
            time.sleep(0.1)

    def close(self) -> None:
        self.vehicle_link.close()
        self.ros2.close()
        self.ocs.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OCS official RoboCommand to USV coordinator gateway"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--official-broker", help="computer B official broker")
    parser.add_argument("--official-port", type=int)
    parser.add_argument("--internal-broker", help="team internal broker")
    parser.add_argument("--internal-port", type=int)
    parser.add_argument("--mission-coordinator", default="T-Wave")
    parser.add_argument("--internal-command-topic", help=argparse.SUPPRESS)
    parser.add_argument("--internal-subscription-topic", default=None, help="heartbeat subscription filter (normally fixed formal topics)")
    parser.add_argument("--internal-username", help="internal MQTT username")
    parser.add_argument("--internal-password", help="internal MQTT password")
    parser.add_argument("--duration", type=float, default=0.0, help="0 means continuous")
    parser.add_argument("--ros2-diagnose", action="store_true", help="read-only ROS2 discovery; never connects MQTT")
    parser.add_argument(
        "--publish-declaration",
        action="store_true",
        help="publish the configured RunDeclaration after connecting",
    )
    args = parser.parse_args()

    if args.ros2_diagnose:
        receiver = OcsClient("", 0, team_id="TONG")  # never connected in diagnostic mode
        link = Ros2MissionLink(receiver.accept_fsm_status, receiver.accept_fsm_task_report)
        try:
            while True:
                print("[ROS2 diagnostic]", json.dumps(link.diagnostics(), ensure_ascii=False))
                time.sleep(2)
        except KeyboardInterrupt:
            return 0
        finally:
            link.close()

    config = load_config(args.config)
    team_id, config_official_host, config_official_port, vehicles = config_values(config)
    internal_config = config.get("internal_broker", {})
    official_host = args.official_broker or config_official_host
    official_port = args.official_port or config_official_port
    internal_host = args.internal_broker or str(internal_config.get("host", "127.0.0.1"))
    internal_port = args.internal_port or int(internal_config.get("port", 1883))
    task_tiers, geofence, uav_altitude, uav_pilot_callsign = declaration_values(config)

    gateway = OcsGateway(
        official_broker=official_host,
        official_port=official_port,
        internal_broker=internal_host,
        internal_port=internal_port,
        team_id=team_id,
        mission_coordinator=args.mission_coordinator,
        internal_command_topic=args.internal_command_topic,
        internal_subscription_topic=args.internal_subscription_topic,
        internal_username=args.internal_username,
        internal_password=args.internal_password,
    )
    try:
        gateway.connect()
        if args.publish_declaration:
            gateway.publish_declaration(
                vehicles, task_tiers, geofence, uav_altitude, uav_pilot_callsign,
            )
        gateway.run(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        gateway.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
