#!/usr/bin/env python3
"""官方 RoboCommand、ROS2 任务 API 与内部 MQTT 遥测的薄网关。

The gateway is intentionally thin:

* official RxCommand/RunStart is decoded by ``OcsClient``;
* validated Course/RunStart/supported Task4 actions use the formal ROS 2 API;
* MQTT is retained only for raw vehicle heartbeat telemetry;
* task selection and Task 4 arbitration remain inside the USV.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
import time
from pathlib import Path

from ocs_client import (
    DEFAULT_CONFIG,
    OcsClient,
    config_values,
    declaration_values,
    geofence_options,
    load_config,
)
from vehicle_link import VehicleLink
from fsm_message_adapter import build_run_start, build_task4
from course_config import fingerprint
from uav_status import normalize_uav_status
from operation_mode import VehicleMode, select_declaration
from uav_geofence import (
    UAV_GEOFENCE_APPLY_TOPIC, UAV_GEOFENCE_READBACK_TOPIC, compare_geofence,
    parse_applied_geofence_readback, serialize_geofence,
)


MISSION_TOPICS = {
    "course": "/tongji_mrl/mission/course_config",
    "run_start": "/tongji_mrl/mission/run_start",
    "offline_test_run_start": "/tongji_mrl/offline_test/run_start",
    "offline_test_receiver_ready": "/tongji_mrl/offline_test/receiver_ready",
    "task4": "/tongji_mrl/mission/task4_cmd",
    "status": "/tongji_mrl/mission/status",
    "task_report": "/tongji_mrl/mission/task_report",
    "fault": "/tongji_mrl/mission/fault",
    "uav_status": "/tongji_mrl/tsky/uav_status",
    "uav_geofence_apply": UAV_GEOFENCE_APPLY_TOPIC,
    "uav_geofence_readback": UAV_GEOFENCE_READBACK_TOPIC,
}
RUNSTART_PENDING_TIMEOUT_S = 5.0
GEOFENCE_READBACK_TIMEOUT_S = 10.0
GEOFENCE_ALTITUDE_TOLERANCE_M = 0.01


class Ros2MissionLink:
    """Non-blocking adapter for the frozen FSM ROS 2 String/JSON interface.

    Imports are deliberately lazy: Windows installations without ROS 2 can
    still run the official/MQTT diagnostics and report that mission transport
    is unavailable.  This class never falls back to MQTT for mission traffic.
    """

    def __init__(self, on_status, on_task_report, on_fault=None, on_uav_status=None,
                 uav_source_vehicle_id: str | None = None, uav_vehicle_id: str = "T-Sky",
                 uav_registration: str | None = None, on_uav_geofence_readback=None,
                 uav_status_trusted: bool = False,
                 uav_use_ocs_receipt_for_freshness: bool = False,
                 offline_test_receiver_token: str | None = None, offline_test_mode: bool = False) -> None:
        self.error: str | None = None
        self.available = False
        self._rclpy = None
        self._node = None
        self._thread: threading.Thread | None = None
        self._course_payload: str | None = None
        self._uav_geofence_readback_subscription = None
        self._uav_geofence_readback_callback = on_uav_geofence_readback
        self._offline_test_receiver_token = offline_test_receiver_token
        self._offline_test_receiver_ready = False
        self._offline_test_mode = offline_test_mode
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
                # In offline mode this publisher is intentionally absent, so
                # this process has no ROS path to the real RunStart topic.
                node_self.run_start_pub = None if offline_test_mode else node_self.create_publisher(
                    String, MISSION_TOPICS["run_start"], 10)
                node_self.offline_test_run_start_pub = node_self.create_publisher(
                    String, MISSION_TOPICS["offline_test_run_start"], 10)
                if offline_test_receiver_token:
                    node_self.create_subscription(
                        String, MISSION_TOPICS["offline_test_receiver_ready"],
                        lambda msg: self._accept_offline_test_receiver_ready(msg.data), 10,
                    )
                node_self.task4_pub = node_self.create_publisher(String, MISSION_TOPICS["task4"], 10)
                node_self.uav_geofence_pub = node_self.create_publisher(
                    String, MISSION_TOPICS["uav_geofence_apply"], 10)
                node_self.create_subscription(String, MISSION_TOPICS["status"], lambda msg: self._safe_callback(on_status, msg.data, "status"), 10)
                node_self.create_subscription(String, MISSION_TOPICS["task_report"], lambda msg: self._safe_callback(on_task_report, msg.data, "task_report"), 10)
                if on_fault is not None:
                    node_self.create_subscription(String, MISSION_TOPICS["fault"], lambda msg: self._safe_callback(on_fault, msg.data, "fault"), 10)
                if on_uav_status is not None and uav_source_vehicle_id:
                    uav_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                                         durability=DurabilityPolicy.VOLATILE)
                    def uav_callback(msg):
                        try:
                            on_uav_status(normalize_uav_status(
                                msg.data, source_vehicle_id=uav_source_vehicle_id,
                                vehicle_id=uav_vehicle_id, uav_registration=uav_registration,
                                trusted_status_source=uav_status_trusted,
                                use_ocs_receipt_for_freshness=uav_use_ocs_receipt_for_freshness,
                            ))
                        except Exception as exc:
                            self.error = f"invalid UAV status: {exc}"
                            node_self.get_logger().warning(self.error)
                            print(f"[UAV_STATUS_REJECTED] topic={MISSION_TOPICS['uav_status']} reason={exc}")
                    node_self.create_subscription(String, MISSION_TOPICS["uav_status"], uav_callback, uav_qos)
                    print(
                        f"[UAV_STATUS_SUBSCRIBED] topic={MISSION_TOPICS['uav_status']} "
                        f"qos=reliable/volatile source_vehicle_id={uav_source_vehicle_id!r} "
                        f"official_vehicle_id={uav_vehicle_id!r}"
                    )

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
            # The readback publisher can start after the gateway.  Keep the
            # type gate, but retry discovery from the executor so this
            # read-only subscription comes up automatically without a
            # geofence publish or a separate ``ros2 topic echo`` process.
            while self.available:
                self._rclpy.spin_once(self._node, timeout_sec=0.5)
                if self._uav_geofence_readback_subscription is None:
                    self._ensure_uav_geofence_readback_subscription()
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
            if self._offline_test_mode or self._node.run_start_pub is None:
                return False, "real RunStart publishing is disabled in offline test mode"
            if self._node.run_start_pub.get_subscription_count() == 0:
                return False, "no matching FSM RunStart subscriber"
            payload = build_run_start(action)
            if payload is None:
                return False, "RunStart missing valid run_id or official command_seq"
            self._node.run_start_pub.publish(self._string(json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            )))
            return True, None
        task4 = self._task4_payload(action)
        if task4 is None:
            return False, f"FSM has no supported ROS2 Task4 mapping for {command}"
        if self._node.task4_pub.get_subscription_count() == 0:
            return False, "no matching FSM Task4 subscriber"
        self._node.task4_pub.publish(self._string(json.dumps(task4, ensure_ascii=False, separators=(",", ":"))))
        return True, None

    def publish_offline_test_run_start(self, action: dict) -> tuple[bool, str | None]:
        """Publish only to the explicitly isolated, non-actuating test topic."""
        if not self.available or self._node is None:
            return False, self.error or "ROS 2 mission transport is unavailable"
        if not self._offline_test_receiver_ready:
            return False, "offline test receiver has not completed read-only capability registration"
        try:
            endpoints = self._node.get_subscriptions_info_by_topic(MISSION_TOPICS["offline_test_run_start"])
        except Exception as exc:
            return False, f"cannot inspect offline test receivers: {exc}"
        # A ROS graph cannot prove arbitrary subscriber code is non-actuating.
        # Fail closed unless exactly one receiver has explicitly registered the
        # non-actuating capability for this session; any extra endpoint is an
        # unknown potential consumer and blocks publication.
        if len(endpoints) != 1 or self._node.offline_test_run_start_pub.get_subscription_count() != 1:
            return False, "offline test topic has an unknown or non-exclusive receiver; refusing publication"
        payload = build_run_start(action)
        if (payload is None or not isinstance(action.get("official_team_id"), str)
                or not action["official_team_id"] or type(action.get("declaration_seq")) is not int
                or action["declaration_seq"] <= 0):
            return False, "RunStart is missing validated official identity fields"
        payload.update({"test_only": True, "official_team_id": action["official_team_id"],
                        "declaration_seq": action["declaration_seq"]})
        self._node.offline_test_run_start_pub.publish(self._string(json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        )))
        return True, None

    def _accept_offline_test_receiver_ready(self, raw: str) -> None:
        """Accept only the ephemeral explicit capability of the read-only tool."""
        try:
            value = json.loads(raw)
            expected = self._offline_test_receiver_token
            valid = (
                isinstance(value, dict) and isinstance(expected, str) and bool(expected)
                and value == {
                    "kind": "offline_test_receiver_ready",
                    "token": expected,
                    "read_only": True,
                    "actuation": False,
                    "topic": MISSION_TOPICS["offline_test_run_start"],
                }
            )
        except (TypeError, ValueError):
            valid = False
        if valid:
            self._offline_test_receiver_ready = True
            print("[OFFLINE_TEST_RECEIVER_READY] explicit read-only capability registered")
        else:
            print("[OFFLINE_TEST_RECEIVER_REJECTED] invalid or non-test capability registration")

    def publish_uav_geofence(self, points) -> tuple[bool, str | None]:
        """Publish the confirmed String.data ``[[latitude,longitude], ...]`` format.

        A ROS 2 publish is not treated as FCU write/readback confirmation.
        """
        if not self.available or self._node is None:
            return False, self.error or "ROS 2 mission transport is unavailable"
        try:
            payload = serialize_geofence(points)
        except ValueError as exc:
            return False, str(exc)
        readback_status = self._ensure_uav_geofence_readback_subscription()
        self._node.uav_geofence_pub.publish(self._string(payload))
        return True, readback_status

    def _ensure_uav_geofence_readback_subscription(self) -> str | None:
        """Discover the readback type before subscribing; never guess a type."""
        if getattr(self, "_uav_geofence_readback_subscription", None) is not None:
            return None
        if self._node is None:
            return "ROS 2 node is unavailable"
        try:
            discovered = dict(self._node.get_topic_names_and_types()).get(
                MISSION_TOPICS["uav_geofence_readback"], [])
        except Exception as exc:
            return f"cannot inspect readback topic type: {exc}"
        if discovered != ["std_msgs/msg/String"]:
            detail = ", ".join(discovered) if discovered else "not currently advertised"
            return f"readback type is unverified ({detail}); not subscribing"
        if getattr(self, "_uav_geofence_readback_callback", None) is None:
            return "readback callback is not configured"
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import String
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE)
        self._uav_geofence_readback_subscription = self._node.create_subscription(
            String, MISSION_TOPICS["uav_geofence_readback"],
            lambda msg: self._safe_callback(self._uav_geofence_readback_callback, msg.data, "uav_geofence_readback"),
            qos,
        )
        print(f"[GEOFENCE_READBACK_SUBSCRIBED] topic={MISSION_TOPICS['uav_geofence_readback']} type=std_msgs/msg/String")
        return None

    @staticmethod
    def _task4_payload(action: dict) -> dict | None:
        return build_task4(action)

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
        publishers = {"course": self._node.course_pub,
                      "offline_test_run_start": self._node.offline_test_run_start_pub, "task4": self._node.task4_pub}
        return {name: {"available": True, "matches": (
            int(publishers[name].get_subscription_count()) if name in publishers else
            (0 if name == "run_start" and self._node.run_start_pub is None else self._node.count_publishers(MISSION_TOPICS[name]))
        )} for name in MISSION_TOPICS}


class OcsGateway:
    """组合官方客户端、ROS2 MissionLink 与内部 VehicleLink 的运行协调器。

保存启动状态和待确认 RunStart；可触发内部/官方通信，必须由受授权的单一实例运行。
"""
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
        uav_source_vehicle_id: str | None = None,
        uav_vehicle_id: str = "T-Sky",
        uav_registration: str | None = None,
        uav_status_trusted: bool = False,
        uav_use_ocs_receipt_for_freshness: bool = False,
        vehicle_mode: VehicleMode | str = VehicleMode.DUAL_VEHICLE,
        allow_uav_geofence_apply: bool = False,
        offline_test_mode: bool = False,
        offline_test_receiver_token: str | None = None,
    ) -> None:
        self.ocs = OcsClient(
            official_broker,
            official_port,
            team_id=team_id,
            mission_coordinator=mission_coordinator,
        )
        self._start_lock = threading.RLock()
        self._clock = time.monotonic
        self.startup_state = "WAIT_COURSE"
        self.startup_reason = "waiting for valid retained RxCourse"
        self.pending_course: dict | None = None
        self.course_published_fingerprint: str | None = None
        self.uav_geofence_published_fingerprint: str | None = None
        self._expected_uav_geofence: tuple[tuple[float, float], ...] | None = None
        self._expected_uav_geofence_max_altitude_hae_m: float | None = None
        self._expected_uav_geofence_course_fingerprint: str | None = None
        self._geofence_readback_deadline: float | None = None
        self._uav_geofence_height_verified = False
        self._uav_auto_declaration: dict | None = None
        self._uav_auto_declaration_course_fingerprint: str | None = None
        self.pending_control_actions: list[dict] = []
        self._pending_run_starts: list[dict] = []
        self._published_run_starts: list[dict] = []
        self.vehicle_mode = VehicleMode(vehicle_mode)
        self.allow_uav_geofence_apply = allow_uav_geofence_apply
        self.offline_test_mode = offline_test_mode
        self.ros2 = Ros2MissionLink(self._on_fsm_status, self.ocs.accept_fsm_task_report,
                                    self._on_fsm_fault, self.ocs.accept_uav_status,
                                    uav_source_vehicle_id=uav_source_vehicle_id,
                                     uav_vehicle_id=uav_vehicle_id, uav_registration=uav_registration,
                                     on_uav_geofence_readback=self._on_uav_geofence_readback,
                                     uav_status_trusted=uav_status_trusted,
                                     uav_use_ocs_receipt_for_freshness=uav_use_ocs_receipt_for_freshness,
                                     offline_test_receiver_token=offline_test_receiver_token,
                                     offline_test_mode=offline_test_mode)
        self.vehicle_link = VehicleLink(
            internal_broker,
            internal_port,
            on_message=self.ocs.accept_vehicle_envelope,
            subscription_topic=internal_subscription_topic,
            username=internal_username,
            password=internal_password,
            active_run_id=lambda: self.ocs.run_id,
            on_uav_status=self.ocs.accept_uav_status,
            uav_source_vehicle_id=uav_source_vehicle_id,
            uav_vehicle_id=uav_vehicle_id,
            uav_registration=uav_registration,
        )

    def connect(self) -> None:
        self.ocs.connect()
        # UAV-only obtains its telemetry directly from ROS 2.  Do not make
        # official UAV Heartbeat reception depend on the unrelated internal
        # MQTT/USV transport.  USV and dual-vehicle behavior is unchanged.
        if self.vehicle_mode is not VehicleMode.UAV_ONLY:
            self.vehicle_link.connect()
        # Course is synchronized through the retained ROS 2 publisher only.
        self.ocs.queue_course_sync()

    def _set_startup_state(self, state: str, reason: str) -> None:
        if (self.startup_state, self.startup_reason) != (state, reason):
            print(f"[Startup] {state}: {reason}")
        self.startup_state, self.startup_reason = state, reason

    def _on_fsm_status(self, raw: str) -> None:
        self.ocs.accept_fsm_status(raw)
        # UAV-only has no verified T-Wave Course/RunStart contract.  Retain the
        # diagnostic snapshot in OcsClient, but never let it drive UAV state.
        if getattr(self, "vehicle_mode", VehicleMode.DUAL_VEHICLE) is VehicleMode.UAV_ONLY:
            return
        with self._start_lock:
            if self.ocs.is_current_course_ready():
                self._set_startup_state(
                    "COURSE_READY" if self.ocs.declaration_seq is not None else "COURSE_VALID",
                    "FSM applied the current Course fingerprint",
                )
            self._release_pending_run_starts()
            self._confirm_run_start_from_status()

    def _on_fsm_fault(self, raw: str) -> None:
        self.ocs.accept_fsm_fault(raw)
        with self._start_lock:
            self._set_startup_state("FAULT", "FSM reported a fault")

    def _on_uav_geofence_readback(self, raw: str) -> None:
        """Diagnose the current readback without treating an echo as FCU proof.

        The audited Orin adapter republishes the received String unchanged.
        Equality therefore proves only that the bridge echoed the candidate,
        never that PX4 accepted or applied it.
        """
        with self._start_lock:
            expected = self._expected_uav_geofence
            expected_altitude = self._expected_uav_geofence_max_altitude_hae_m
            expected_course = self._expected_uav_geofence_course_fingerprint
            if expected is None or expected_altitude is None or expected_course is None:
                print("[GEOFENCE_BLOCKED] readback received without a current published candidate")
                return
            try:
                if self._geofence_readback_deadline is None or self._clock() > self._geofence_readback_deadline:
                    raise ValueError("readback arrived after the current candidate verification deadline")
                if self.ocs.course_fingerprint != expected_course:
                    raise ValueError("readback does not match the current Course")
                actual, actual_altitude = parse_applied_geofence_readback(raw)
                compare_geofence(expected, actual)
                if not math.isclose(actual_altitude, expected_altitude,
                                    rel_tol=0.0, abs_tol=GEOFENCE_ALTITUDE_TOLERANCE_M):
                    raise ValueError(
                        f"max_altitude_m is {actual_altitude:g}, expected {expected_altitude:g} m HAE"
                    )
            except ValueError as exc:
                print(f"[GEOFENCE_BLOCKED] readback mismatch: {exc}")
                self._set_startup_state("GEOFENCE_BLOCKED", f"FCU geofence readback mismatch: {exc}")
                return
            self._uav_geofence_height_verified = False
            print(
                f"[GEOFENCE_READBACK_ECHO_UNTRUSTED] vertices={len(actual)} "
                f"horizontal_match=true max_hae_m={actual_altitude:g}"
            )
            self._set_startup_state(
                "FCU_GEOFENCE_UNVERIFIED",
                "readback matches candidate but has no FCU-applied provenance; Declaration remains blocked",
            )

    def publish_declaration(
        self,
        vehicle_ids: list[str],
        task_tiers: tuple[str, str, str, str],
        uav_geofence: list[tuple[float, float]],
        uav_geofence_max_altitude_hae_m: float | None,
        uav_pilot_callsign: str | None,
        uav_geofence_mode: str = "manual",
        uav_geofence_margin_m: float = 2.0,
        uav_geofence_altitude_limit_hae_m: float = 50.0,
    ) -> None:
        self.ocs.publish_run_declaration(
            vehicle_ids, task_tiers, uav_geofence,
            uav_geofence_max_altitude_hae_m=uav_geofence_max_altitude_hae_m,
            uav_pilot_callsign=uav_pilot_callsign,
            uav_geofence_mode=uav_geofence_mode,
            uav_geofence_margin_m=uav_geofence_margin_m,
            uav_geofence_altitude_limit_hae_m=uav_geofence_altitude_limit_hae_m,
        )
        with self._start_lock:
            if getattr(self, "vehicle_mode", VehicleMode.DUAL_VEHICLE) is VehicleMode.UAV_ONLY:
                self._set_startup_state("DECLARATION_SENT", "UAV-only Declaration sent; no T-Wave FSM ACK is required")
                return
            if self.ocs.is_current_course_ready():
                self._set_startup_state("COURSE_READY", "declaration matches FSM-applied Course")
            else:
                self._set_startup_state("DECLARED", "declaration sent; waiting for FSM Course-ready ACK")

    def arm_uav_auto_declaration(self, *, vehicle_ids: list[str], task_tiers: tuple[str, str, str, str],
                                 uav_geofence: list[tuple[float, float]],
                                 uav_geofence_max_altitude_hae_m: float | None,
                                 uav_pilot_callsign: str | None, uav_geofence_mode: str,
                                 uav_geofence_margin_m: float,
                                 uav_geofence_altitude_limit_hae_m: float) -> None:
        """Arm one automatic declaration per Course after FCU verification."""
        self._uav_auto_declaration = {
            "vehicle_ids": vehicle_ids, "task_tiers": task_tiers,
            "uav_geofence": uav_geofence,
            "uav_geofence_max_altitude_hae_m": uav_geofence_max_altitude_hae_m,
            "uav_pilot_callsign": uav_pilot_callsign,
            "uav_geofence_mode": uav_geofence_mode,
            "uav_geofence_margin_m": uav_geofence_margin_m,
            "uav_geofence_altitude_limit_hae_m": uav_geofence_altitude_limit_hae_m,
        }

    def _publish_verified_uav_declaration_locked(self, course_fingerprint: str) -> None:
        pending = self._uav_auto_declaration
        if pending is None or self._uav_auto_declaration_course_fingerprint == course_fingerprint:
            return
        if self.ocs.course_fingerprint != course_fingerprint or not self._uav_geofence_height_verified:
            return
        try:
            self.publish_declaration(**pending)
        except Exception as exc:
            self._set_startup_state("GEOFENCE_BLOCKED", f"verified fence but RunDeclaration was not sent: {exc}")
            return
        self._uav_auto_declaration_course_fingerprint = course_fingerprint

    def publish_uav_geofence_candidate(self, *, uav_vehicle_id: str, uav_geofence: list[tuple[float, float]],
                                       uav_geofence_max_altitude_hae_m: float | None,
                                       uav_geofence_mode: str, uav_geofence_margin_m: float,
                                       uav_geofence_altitude_limit_hae_m: float) -> bool:
        """Send the exact validated Declaration candidate as the Orin 2-D fence.

        The confirmed Orin wire format contains no altitude or FCU-identity
        fields.  Therefore this records publication but deliberately leaves the
        flight gate blocked until an authoritative readback contract is supplied.
        """
        candidate = self.ocs._build_run_declaration(
            [uav_vehicle_id], ("none", "none", "none", "none"), uav_geofence,
            uav_geofence_max_altitude_hae_m=uav_geofence_max_altitude_hae_m,
            uav_pilot_callsign="OCS-GEOFENCE-PRECHECK",
            uav_geofence_mode=uav_geofence_mode,
            uav_geofence_margin_m=uav_geofence_margin_m,
            uav_geofence_altitude_limit_hae_m=uav_geofence_altitude_limit_hae_m,
        )
        course_fingerprint = self.ocs.course_fingerprint
        if course_fingerprint == self.uav_geofence_published_fingerprint:
            return True
        points = [(point.latitude, point.longitude) for point in candidate.uav_geofence]
        print(f"[GEOFENCE_CANDIDATE] course={self.ocs.course.course_id if self.ocs.course else '?'} vertices={len(points)} max_hae_m={uav_geofence_max_altitude_hae_m}")
        if not getattr(self, "allow_uav_geofence_apply", False):
            self._uav_geofence_height_verified = False
            self._set_startup_state(
                "GEOFENCE_CANDIDATE_ONLY",
                "FCU geofence write is disabled until explicitly approved by the pilot",
            )
            print(f"[GEOFENCE_NOT_PUBLISHED] topic={UAV_GEOFENCE_APPLY_TOPIC} reason=pilot approval flag not set")
            return False
        self._expected_uav_geofence = tuple(points)
        self._expected_uav_geofence_max_altitude_hae_m = float(uav_geofence_max_altitude_hae_m)
        self._expected_uav_geofence_course_fingerprint = course_fingerprint
        self._geofence_readback_deadline = self._clock() + GEOFENCE_READBACK_TIMEOUT_S
        self._uav_geofence_height_verified = False
        published, readback_status = self.ros2.publish_uav_geofence(points)
        if not published:
            print(f"[GEOFENCE_BLOCKED] topic={UAV_GEOFENCE_APPLY_TOPIC} reason={readback_status}")
            self._set_startup_state("GEOFENCE_BLOCKED", f"UAV geofence not published: {readback_status}")
            return False
        self.uav_geofence_published_fingerprint = course_fingerprint
        print(f"[GEOFENCE_PUBLISHED] topic={UAV_GEOFENCE_APPLY_TOPIC} course_fingerprint={course_fingerprint} vertices={len(points)}")
        if readback_status:
            print(f"[GEOFENCE_BLOCKED] topic={UAV_GEOFENCE_READBACK_TOPIC} reason={readback_status}")
        self._set_startup_state("GEOFENCE_PUBLISHED_FCU_UNVERIFIED", "waiting for verified UAV FCU geofence readback")
        return True

    def flush_commands(self) -> None:
        with self._start_lock:
            controls: list[dict] = []
            for action in self.ocs.drain_internal_actions():
                if action.get("vehicle_id") != self.ocs.mission_coordinator:
                    raise ValueError(
                        "OCS gateway refuses to send a command directly to a non-USV vehicle"
                    )
                if action.get("kind") == "course_config":
                    if getattr(self, "vehicle_mode", VehicleMode.DUAL_VEHICLE) is VehicleMode.UAV_ONLY:
                        # Course is accepted by OCS and used to derive the UAV
                        # fence; it is not sent to or acknowledged by T-Wave.
                        self.pending_course = None
                        self.course_published_fingerprint = None
                        self._expected_uav_geofence = None
                        self._expected_uav_geofence_max_altitude_hae_m = None
                        self._expected_uav_geofence_course_fingerprint = None
                        self._geofence_readback_deadline = None
                        self._uav_geofence_height_verified = False
                        self.uav_geofence_published_fingerprint = None
                        self._set_startup_state("COURSE_RECEIVED", "valid RxCourse received; preparing UAV geofence")
                        pending = getattr(self, "_uav_auto_declaration", None)
                        if pending is not None:
                            self.publish_uav_geofence_candidate(
                                uav_vehicle_id=str(pending["vehicle_ids"][0]),
                                uav_geofence=pending["uav_geofence"],
                                uav_geofence_max_altitude_hae_m=pending["uav_geofence_max_altitude_hae_m"],
                                uav_geofence_mode=str(pending["uav_geofence_mode"]),
                                uav_geofence_margin_m=float(pending["uav_geofence_margin_m"]),
                                uav_geofence_altitude_limit_hae_m=float(pending["uav_geofence_altitude_limit_hae_m"]),
                            )
                        continue
                    self.pending_course = action["payload"]
                    self.course_published_fingerprint = None
                    self._set_startup_state("COURSE_VALID", "valid Course received; awaiting ROS2 publication and FSM ACK")
                else:
                    if (action.get("command") == "RUN_START" and
                            getattr(self, "vehicle_mode", VehicleMode.DUAL_VEHICLE) is VehicleMode.UAV_ONLY):
                        if getattr(self, "offline_test_mode", False):
                            sent, reason = self.ros2.publish_offline_test_run_start(action)
                            state = "OFFLINE_TEST_RUNSTART_FORWARDED" if sent else "OFFLINE_TEST_RUNSTART_NOT_FORWARDED"
                            record = {"action": action, "state": state, "reason": reason,
                                      "received_monotonic": self._clock()}
                            self.pending_control_actions.append(record)
                            self._set_startup_state(
                                "OFFLINE_TEST_RUNSTART_FORWARDED" if sent else "OFFLINE_TEST_RUNSTART_BLOCKED",
                                "RunStart sent only to isolated test receiver" if sent else str(reason),
                            )
                            continue
                        record = {
                            "action": action, "state": "BLOCKED_UAV_TASK_RECEIVER_UNAVAILABLE",
                            "reason": "no verified real-UAV Orin RunStart receiver/ACK contract",
                            "received_monotonic": self._clock(),
                        }
                        self.pending_control_actions.append(record)
                        self._set_startup_state("RUNSTART_ORIN_INTERFACE_UNAVAILABLE",
                                                "official RunStart received; " + record["reason"])
                        continue
                    controls.append(action)
            if self.pending_course is not None:
                if self.ros2.publish_course(self.pending_course):
                    self.course_published_fingerprint = fingerprint(self.pending_course)
                    self.pending_course = None
                elif self.ros2.available:
                    print("[ROS2] Course pending: no matching FSM subscriber")
            for action in controls:
                if action.get("command") == "RUN_START":
                    record = {
                        "action": action,
                        "state": "BLOCKED_COURSE_READY_ACK",
                        "reason": "waiting for a fresh, matching FSM Course-applied ACK",
                        "received_monotonic": self._clock(),
                    }
                    self.pending_control_actions.append(record)
                    self._pending_run_starts.append(record)
                    self._set_startup_state("RUNSTART_RECEIVED", "official RunStart validated and held for Course-ready ACK")
                else:
                    sent, reason = self.ros2.publish_action(action)
                    if not sent:
                        print(f"[ROS2] action {action.get('command')} not published: {reason}")
                        self.pending_control_actions.append({"action": action, "state": "NOT_SUBMITTED", "reason": reason})
                    else:
                        self.pending_control_actions.append({"action": action, "state": "SUBMITTED_UNCONFIRMED", "reason": None})
            self._release_pending_run_starts()

    def _release_pending_run_starts(self) -> None:
        """Release only matching, fresh RunStart records after an FSM Course ACK."""
        if getattr(self, "vehicle_mode", VehicleMode.DUAL_VEHICLE) is VehicleMode.UAV_ONLY:
            return
        now = self._clock()
        remaining: list[dict] = []
        for record in self._pending_run_starts:
            action = record["action"]
            if now - record["received_monotonic"] > RUNSTART_PENDING_TIMEOUT_S:
                record.update(state="BLOCKED_RUNSTART_TIMEOUT", reason="Course-ready ACK did not arrive before timeout")
                self._set_startup_state("BLOCKED", record["reason"])
                continue
            course_fingerprint = action.get("course_fingerprint")
            if course_fingerprint != self.ocs.course_fingerprint:
                record.update(state="BLOCKED_COURSE_CHANGED", reason="RunStart Course is no longer current")
                self._set_startup_state("BLOCKED", record["reason"])
                continue
            if self.course_published_fingerprint != course_fingerprint:
                record.update(state="BLOCKED_COURSE_NOT_PUBLISHED", reason="current Course has not been published to ROS2")
                self._set_startup_state("BLOCKED", record["reason"])
                remaining.append(record)
                continue
            if not self.ocs.is_current_course_ready(course_fingerprint):
                remaining.append(record)
                continue
            sent, reason = self.ros2.publish_action(action)
            if not sent:
                record.update(state="BLOCKED_RUNSTART_NOT_PUBLISHED", reason=reason)
                self._set_startup_state("BLOCKED", str(reason))
                remaining.append(record)
                continue
            record.update(state="RUNSTART_PUBLISHED_UNCONFIRMED", reason="ROS2 published; awaiting explicit FSM RunStart ACK")
            self._published_run_starts.append(record)
            self._set_startup_state("RUNSTART_RECEIVED", record["reason"])
        self._pending_run_starts = remaining

    def _confirm_run_start_from_status(self) -> None:
        """Accept only the future explicit RunStart ACK contract from the FSM."""
        if getattr(self, "vehicle_mode", VehicleMode.DUAL_VEHICLE) is VehicleMode.UAV_ONLY:
            return
        status = self.ocs.latest_fsm_status
        if not isinstance(status, dict) or status.get("simulation") is True:
            return
        ack = status.get("run_start")
        if not isinstance(ack, dict) or ack.get("accepted") is not True or ack.get("application_state") != "APPLIED":
            return
        for record in self._published_run_starts:
            action = record["action"]
            expected_id = f"robocommand:{action.get('run_id')}:{action.get('command_seq')}:run-start"
            if (ack.get("run_id") == action.get("run_id") and
                    ack.get("official_command_seq") == action.get("command_seq") and
                    ack.get("command_id") == expected_id):
                record.update(state="RUNNING", reason="FSM explicitly acknowledged applied RunStart")
                self._set_startup_state("RUNNING", record["reason"])

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
        if self.vehicle_mode is not VehicleMode.UAV_ONLY:
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
    parser.add_argument("--uav-source-vehicle-id", help="explicit ROS2 UAV JSON vehicle_id mapping; subscription disabled when omitted")
    parser.add_argument("--vehicle-mode", choices=[mode.value for mode in VehicleMode],
                        default=VehicleMode.DUAL_VEHICLE.value,
                        help="fixed RunDeclaration vehicle set; default preserves dual-vehicle behavior")
    parser.add_argument("--duration", type=float, default=0.0, help="0 means continuous")
    parser.add_argument("--ros2-diagnose", action="store_true", help="read-only ROS2 discovery; never connects MQTT")
    parser.add_argument(
        "--uav-status-diagnose",
        action="store_true",
        help="read-only UAV status/Heartbeat gate diagnosis; never connects MQTT or publishes reports",
    )
    parser.add_argument("--offline-test-mode", action="store_true",
                        help="UAV-only loopback test: isolated ROS RunStart forwarding; never a flight mode")
    parser.add_argument("--offline-test-receiver-token", help="required ephemeral token for the explicit read-only test receiver")
    parser.add_argument(
        "--publish-declaration",
        action="store_true",
        help="publish the configured RunDeclaration after connecting",
    )
    parser.add_argument(
        "--allow-uav-geofence-apply",
        action="store_true",
        help="explicit pilot authorization to publish the calculated candidate to the team UAV topic",
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
    # Command-line broker arguments are explicit operator input.  Apply the
    # official host before config validation so a reusable template with a
    # TBD placeholder remains usable with ``--official-broker``.
    if args.official_broker:
        config = {
            **config,
            "robocommand": {
                **config.get("robocommand", {}),
                "host": args.official_broker,
            },
        }
    team_id, config_official_host, config_official_port, vehicles = config_values(config)
    internal_config = config.get("internal_broker", {})
    official_host = args.official_broker or config_official_host
    official_port = args.official_port or config_official_port
    internal_host = args.internal_broker or str(internal_config.get("host", "127.0.0.1"))
    internal_port = args.internal_port or int(internal_config.get("port", 1883))
    if args.offline_test_mode:
        if args.vehicle_mode != VehicleMode.UAV_ONLY.value:
            parser.error("--offline-test-mode requires --vehicle-mode uav_only")
        if official_host != "127.0.0.1" or internal_host != "127.0.0.1":
            parser.error("--offline-test-mode requires 127.0.0.1 official and internal MQTT brokers")
        if os.environ.get("ROS_DOMAIN_ID") != "62" or os.environ.get("ROS_LOCALHOST_ONLY") != "0":
            parser.error("--offline-test-mode requires ROS_DOMAIN_ID=62 and ROS_LOCALHOST_ONLY=0")
        if not args.offline_test_receiver_token or len(args.offline_test_receiver_token) < 16:
            parser.error("--offline-test-mode requires a receiver token of at least 16 characters")
        print("[OFFLINE_TEST] No FCU/geofence write or readback is performed; this is not FCU-applied proof.")
    task_tiers, geofence, uav_altitude, uav_pilot_callsign = declaration_values(config)
    geofence_mode, geofence_margin, geofence_limit = geofence_options(config)
    vehicle_config = config.get("vehicles", {})
    selection = select_declaration(
        args.vehicle_mode,
        uav_vehicle_id=vehicle_config.get("uav", {}).get("vehicle_id"),
        usv_vehicle_id=vehicle_config.get("usv", {}).get("vehicle_id"),
        uav_geofence=geofence,
        uav_geofence_max_altitude_hae_m=uav_altitude,
        uav_pilot_callsign=uav_pilot_callsign,
        uav_geofence_mode=geofence_mode,
    )
    print(f"[Mode] {args.vehicle_mode}; declaration vehicles: {selection.vehicle_ids}")
    uav_config = vehicle_config.get("uav", {})
    uav_is_declared = uav_config.get("vehicle_id") in selection.vehicle_ids
    uav_source_vehicle_id = (args.uav_source_vehicle_id or uav_config.get("source_vehicle_id")) if uav_is_declared else None
    uav_status_trusted = uav_config.get("trusted_status_topic") is True
    uav_use_ocs_receipt_for_freshness = uav_config.get("use_ocs_receipt_for_freshness") is True

    if args.uav_status_diagnose:
        if not uav_source_vehicle_id:
            parser.error("--uav-status-diagnose requires vehicles.uav.source_vehicle_id")
        receiver = OcsClient("", 0, team_id=team_id)  # Never connected in diagnostic mode.
        # This is local eligibility context only; it neither publishes nor
        # claims that RBC has an active RunDeclaration.
        receiver._declared_vehicle_ids = {str(uav_config.get("vehicle_id", "T-Sky"))}
        link = Ros2MissionLink(
            receiver.accept_fsm_status, receiver.accept_fsm_task_report,
            on_uav_status=receiver.accept_uav_status,
            uav_source_vehicle_id=uav_source_vehicle_id,
            uav_vehicle_id=str(uav_config.get("vehicle_id", "T-Sky")),
            uav_registration=uav_config.get("uav_registration"),
            uav_status_trusted=uav_status_trusted,
            uav_use_ocs_receipt_for_freshness=uav_use_ocs_receipt_for_freshness,
        )
        print("[UAV_STATUS_DIAGNOSTIC] read-only; no MQTT, Declaration, command, geofence, or FCU operation")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
        finally:
            link.close()

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
        uav_source_vehicle_id=uav_source_vehicle_id,
        uav_vehicle_id=str(uav_config.get("vehicle_id", "T-Sky")),
        uav_registration=uav_config.get("uav_registration"),
        uav_status_trusted=uav_status_trusted,
        uav_use_ocs_receipt_for_freshness=uav_use_ocs_receipt_for_freshness,
        vehicle_mode=args.vehicle_mode,
        allow_uav_geofence_apply=args.allow_uav_geofence_apply,
        offline_test_mode=args.offline_test_mode,
        offline_test_receiver_token=args.offline_test_receiver_token,
    )
    try:
        gateway.connect()
        if args.publish_declaration:
            # Do not declare before the retained RxCourse arrives.
            deadline = time.monotonic() + 10.0
            while gateway.ocs.course_store.get() is None and time.monotonic() < deadline:
                time.sleep(0.1)
            if args.offline_test_mode:
                # Explicit test exception: no geofence is sent and no simulated
                # readback is accepted.  This cannot establish FCU readiness.
                gateway.publish_declaration(
                    selection.vehicle_ids, task_tiers, selection.uav_geofence,
                    selection.uav_geofence_max_altitude_hae_m, selection.uav_pilot_callsign,
                    selection.uav_geofence_mode, geofence_margin, geofence_limit,
                )
                print("[OFFLINE_TEST] Declaration published without FCU geofence verification (SIMULATED/OFFLINE ONLY).")
            elif args.vehicle_mode != VehicleMode.USV_ONLY.value:
                gateway.arm_uav_auto_declaration(
                    vehicle_ids=selection.vehicle_ids, task_tiers=task_tiers,
                    uav_geofence=selection.uav_geofence,
                    uav_geofence_max_altitude_hae_m=selection.uav_geofence_max_altitude_hae_m,
                    uav_pilot_callsign=selection.uav_pilot_callsign,
                    uav_geofence_mode=selection.uav_geofence_mode,
                    uav_geofence_margin_m=geofence_margin,
                    uav_geofence_altitude_limit_hae_m=geofence_limit,
                )
                geofence_published = gateway.publish_uav_geofence_candidate(
                    uav_vehicle_id=str(uav_config.get("vehicle_id", "T-Sky")),
                    uav_geofence=selection.uav_geofence,
                    uav_geofence_max_altitude_hae_m=selection.uav_geofence_max_altitude_hae_m,
                    uav_geofence_mode=selection.uav_geofence_mode,
                    uav_geofence_margin_m=geofence_margin,
                    uav_geofence_altitude_limit_hae_m=geofence_limit,
                )
                if geofence_published:
                    print("[GEOFENCE_BLOCKED] RunDeclaration withheld until the current FCU-applied readback verifies")
                else:
                    print("[GEOFENCE_BLOCKED] RunDeclaration withheld; continuing read-only ROS2 and official-message reception")
            else:
                gateway.publish_declaration(
                    selection.vehicle_ids, task_tiers, selection.uav_geofence,
                    selection.uav_geofence_max_altitude_hae_m, selection.uav_pilot_callsign,
                    selection.uav_geofence_mode, geofence_margin, geofence_limit,
                )
        gateway.run(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        gateway.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
