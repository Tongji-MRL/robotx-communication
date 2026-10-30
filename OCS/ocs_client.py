#!/usr/bin/env python3
"""Small official RoboCommand-side OCS client.

This module deliberately stops at the OCS boundary.  It connects the OCS to
the RoboCommand MQTT broker, decodes official downlink messages, and exposes
methods for publishing team declarations and vehicle reports.  The Orin/ROS 2
bridge can call these methods later; the demo mode below only sends clearly
marked synthetic data for broker/protobuf testing.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

try:
    from .course_store import CourseStore
    from .course_config import make_payload, fingerprint
except ImportError:  # Script/test execution directly from the OCS directory.
    from course_store import CourseStore
    from course_config import make_payload, fingerprint

try:
    import paho.mqtt.client as mqtt
    _MQTT_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - depends on local environment
    mqtt = None
    _MQTT_IMPORT_ERROR = exc

from google.protobuf.text_format import MessageToString
from google.protobuf.timestamp_pb2 import Timestamp
try:
    from .heartbeat_cache import HeartbeatCache, HeartbeatRejected
except ImportError:
    from heartbeat_cache import HeartbeatCache, HeartbeatRejected

# The official generated Python modules live beside this OCS directory.
HERE = Path(__file__).resolve().parent
GEN_ROOT = HERE.parent / "RobotX_2026" / "gen" / "python"
if str(GEN_ROOT) not in sys.path:
    sys.path.insert(0, str(GEN_ROOT))

import common_pb2  # noqa: E402
from robotx import rx_commands_pb2, rx_common_pb2, rx_course_pb2  # noqa: E402
from robotx import rx_reports_pb2, rx_requests_pb2  # noqa: E402



TOPIC_ROOT = "robocommand/robotx"
DEFAULT_CONFIG = HERE / "config.example.json"

TIER_MAP = {
    "unknown": common_pb2.TIER_UNKNOWN,
    "none": common_pb2.TIER_NONE,
    "core": common_pb2.TIER_CORE,
    "advanced": common_pb2.TIER_ADVANCED,
    "disruptive": common_pb2.TIER_DISRUPTIVE,
}
STATE_MAP = {
    "unknown": common_pb2.STATE_UNKNOWN,
    "killed": common_pb2.STATE_KILLED,
    "manual": common_pb2.STATE_MANUAL,
    "auto": common_pb2.STATE_AUTO,
}
TYPE_MAP = {
    "unknown": rx_common_pb2.TYPE_UNKNOWN,
    "usv": rx_common_pb2.TYPE_USV,
    "uuv": rx_common_pb2.TYPE_UUV,
    "uav": rx_common_pb2.TYPE_UAV,
}
TASK_MAP = {
    "unknown": rx_common_pb2.TASK_UNKNOWN,
    "none": rx_common_pb2.TASK_NONE,
    "safe-passage": rx_common_pb2.TASK_SAFE_PASSAGE,
    "infra-survey-repair": rx_common_pb2.TASK_INFRA_SURVEY_REPAIR,
    "coordinated-logistics": rx_common_pb2.TASK_COORDINATED_LOGISTICS,
    "dynamic-incident": rx_common_pb2.TASK_DYNAMIC_INCIDENT,
    "task1": rx_common_pb2.TASK_SAFE_PASSAGE,
    "task3": rx_common_pb2.TASK_COORDINATED_LOGISTICS,
    "task4": rx_common_pb2.TASK_DYNAMIC_INCIDENT,
}
FLIGHT_PHASE_MAP = {
    "unknown": rx_common_pb2.FLIGHT_PHASE_UNKNOWN,
    "grounded": rx_common_pb2.FLIGHT_PHASE_GROUNDED,
    "airborne": rx_common_pb2.FLIGHT_PHASE_AIRBORNE,
}
BEACON_MAP = {
    "unknown": rx_common_pb2.BEACON_STATE_UNKNOWN,
    "off": rx_common_pb2.BEACON_STATE_OFF,
    "flashing-red": rx_common_pb2.BEACON_STATE_FLASHING_RED,
    "flashing-green": rx_common_pb2.BEACON_STATE_FLASHING_GREEN,
    "flashing-blue": rx_common_pb2.BEACON_STATE_FLASHING_BLUE,
    "steady-blue": rx_common_pb2.BEACON_STATE_STEADY_BLUE,
}
COLOR_MAP = {
    "unknown": rx_common_pb2.COLOR_UNKNOWN,
    "red": rx_common_pb2.COLOR_RED,
    "green": rx_common_pb2.COLOR_GREEN,
    "blue": rx_common_pb2.COLOR_BLUE,
    "any": rx_common_pb2.COLOR_ANY,
}


def now_timestamp() -> Timestamp:
    value = Timestamp()
    value.GetCurrentTime()
    return value


def _enum(value: int | str, names: Mapping[str, int], label: str) -> int:
    if isinstance(value, int):
        return value
    key = value.lower()
    if key not in names:
        raise ValueError(f"{label} must be one of: {', '.join(names)}")
    return names[key]


def _lat_lng(latitude: float, longitude: float) -> common_pb2.LatLng:
    if not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")
    return common_pb2.LatLng(latitude=latitude, longitude=longitude)


class OcsClient:
    """MQTT client for the official RoboCommand topics."""

    def __init__(
        self,
        broker_host: str,
        broker_port: int,
        team_id: str = "TONG",
        mission_coordinator: str = "T-Wave",
    ) -> None:
        if mqtt is None:
            raise SystemExit(
                "缺少 paho-mqtt。请在 RobotX_2026 环境中安装官方 requirements，"
                "或执行: python -m pip install paho-mqtt"
            ) from _MQTT_IMPORT_ERROR
        if not team_id:
            raise ValueError("team_id must not be empty")
        if not mission_coordinator:
            raise ValueError("mission_coordinator must not be empty")
        self.team_id = team_id
        self.mission_coordinator = mission_coordinator
        self._team_seq = 0
        self._report_seq: dict[str, int] = {}
        self._report_lock = threading.Lock()
        self._declared_vehicle_ids: set[str] = set()
        self.declaration_seq: int | None = None
        self.run_id: int | None = None
        self.course: rx_course_pb2.RxCourse | None = None
        self.course_store = CourseStore()
        self._course_fingerprint: str | None = None
        self.last_rejection_reason: str | None = None
        self.last_command: rx_commands_pb2.RxCommand | None = None
        self._last_command_seq = 0
        # Actions are deliberately queued instead of published here. The
        # official RoboCommand broker and the team vehicle broker are separate
        # protocol boundaries; vehicle_link.py is the internal MQTT adapter.
        self._pending_internal_actions: list[dict] = []
        self._relayed_official_commands: dict[int, str] = {}
        # A ReadinessConfirm names the official per-vehicle RxReport sequence,
        # while the FSM must also recover the original AssistanceRequest
        # sequence.  Keep only the active-run, in-memory correlation here; a
        # fresh RunDeclaration clears it with the other active-run state.
        self._readiness_reports: dict[tuple[int, str, int], dict[str, object]] = {}
        self.heartbeat_cache = HeartbeatCache()
        self._authoritative_current_task: dict[str, str] = {}
        self.latest_fsm_status: dict | None = None
        self.latest_fsm_task_report: dict | None = None
        self.latest_fsm_fault: dict | None = None
        self.runtime_events: list[dict[str, object]] = []
        self.connected = False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    @property
    def request_topic(self) -> str:
        return f"{TOPIC_ROOT}/{self.team_id}/request"

    @property
    def command_topic(self) -> str:
        return f"{TOPIC_ROOT}/{self.team_id}/command"

    def connect(self) -> None:
        print(f"Connecting OCS to MQTT {self.broker_host}:{self.broker_port} ...")
        self.client.connect(self.broker_host, self.broker_port, keepalive=60)
        self.client.loop_start()

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        if reason_code != 0:
            self.connected = False
            self._record_runtime_event("mqtt", "connect_failed", detail=str(reason_code))
            print(f"[MQTT] connection failed: {reason_code}", file=sys.stderr)
            return
        self.connected = True
        client.subscribe([(f"{TOPIC_ROOT}/course", 1), (self.command_topic, 1)])
        print(f"[MQTT] connected; subscribed to {TOPIC_ROOT}/course and {self.command_topic}")

    def _on_disconnect(self, _client, _userdata, _disconnect_flags, reason_code, _properties=None) -> None:
        self.connected = False
        self._record_runtime_event("mqtt", "disconnected", detail=str(reason_code))
        print(f"[MQTT] disconnected: {reason_code}")

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            if message.topic == f"{TOPIC_ROOT}/course":
                decoded = rx_course_pb2.RxCourse()
                decoded.ParseFromString(message.payload)
                self._accept_course(decoded)
                print(f"[RxCourse] {message.topic}\n{MessageToString(decoded).rstrip()}")
            elif message.topic == self.command_topic:
                decoded = rx_commands_pb2.RxCommand()
                decoded.ParseFromString(message.payload)
                self._accept_command(decoded)
                print(f"[RxCommand] {message.topic}\n{MessageToString(decoded).rstrip()}")
            else:
                print(f"[MQTT] ignored unexpected topic: {message.topic}", file=sys.stderr)
        except Exception as exc:  # keep MQTT loop alive on malformed payloads
            self._record_runtime_event("mqtt", "decode_rejected", topic=message.topic, detail=str(exc))
            print(f"[MQTT] cannot decode {message.topic}: {exc}", file=sys.stderr)

    def _record_runtime_event(self, source: str, event: str, *, topic: str | None = None,
                              run_id: int | None = None, command_seq: int | None = None,
                              detail: str = "") -> None:
        """Keep bounded transport diagnostics; never retries control work."""
        self.runtime_events.append({
            "source": source, "event": event, "timestamp_unix_ms": int(time.time() * 1000),
            "topic": topic, "run_id": self.run_id if run_id is None else run_id,
            "command_seq": command_seq, "detail": detail, "state": "OBSERVED",
        })
        del self.runtime_events[:-100]

    @staticmethod
    def _validate_course(course: rx_course_pb2.RxCourse) -> None:
        # make_payload performs the frozen range and polygon validation.
        make_payload(
            course_id=course.course_id, pinger_freq_hz=course.pinger_freq_hz,
            corners=((item.latitude, item.longitude) for item in course.corners),
            uav_transit_area=((item.latitude, item.longitude) for item in course.uav_transit_area),
            source_sent_at=course.sent_at.ToDatetime(tzinfo=timezone.utc)
            if (course.sent_at.seconds or course.sent_at.nanos) else None,
        )

    def _accept_course(self, course: rx_course_pb2.RxCourse) -> None:
        self._validate_course(course)
        source_sent_at = course.sent_at.ToDatetime(tzinfo=timezone.utc) if (course.sent_at.seconds or course.sent_at.nanos) else None
        payload = make_payload(
            course_id=course.course_id, pinger_freq_hz=course.pinger_freq_hz,
            corners=((item.latitude, item.longitude) for item in course.corners),
            uav_transit_area=((item.latitude, item.longitude) for item in course.uav_transit_area),
            source_sent_at=source_sent_at,
        )
        new_fingerprint = fingerprint(payload)
        self.course = rx_course_pb2.RxCourse()
        self.course.CopyFrom(course)
        self.course_store.update(
            course_id=course.course_id,
            pinger_freq_hz=course.pinger_freq_hz,
            corners=((corner.latitude, corner.longitude) for corner in course.corners),
            uav_transit_area=((point.latitude, point.longitude) for point in course.uav_transit_area),
            sent_at=source_sent_at,
        )
        if new_fingerprint != self._course_fingerprint:
            self._course_fingerprint = new_fingerprint
            self._queue_internal_action({
                "kind": "course_config", "vehicle_id": self.mission_coordinator,
                "payload": payload,
            })

    def queue_course_sync(self) -> None:
        """Queue the latest valid Course after an internal-link reconnect.

        This is transport synchronization only, not an FSM-applied acknowledgement.
        """
        course = self.course_store.get()
        if course is None:
            return
        self._queue_internal_action({
            "kind": "course_config", "vehicle_id": self.mission_coordinator,
            "payload": make_payload(
                course_id=course.course_id, pinger_freq_hz=course.pinger_freq_hz,
                corners=course.corners, uav_transit_area=course.uav_transit_area,
                source_sent_at=course.sent_at,
            ),
        })

    def _accept_command(self, command: rx_commands_pb2.RxCommand) -> None:
        if command.team_id != self.team_id:
            raise ValueError("RxCommand.team_id does not match the configured team")
        if not command.seq or command.seq <= self._last_command_seq:
            raise ValueError("RxCommand.seq is missing or not increasing")
        body = command.WhichOneof("body")
        if body is None:
            raise ValueError("RxCommand must contain exactly one body")
        if body == "run_start":
            if self.declaration_seq is None:
                raise ValueError("RunStart received before a RunDeclaration")
            if command.run_start.declaration_seq != self.declaration_seq:
                raise ValueError("RunStart.declaration_seq does not match the declaration")
            if not command.run_start.run_id:
                raise ValueError("RunStart.run_id must not be zero")
            if self.course_store.get() is None:
                self.last_rejection_reason = "RunStart received before a valid RxCourse"
                raise ValueError(self.last_rejection_reason)
            self.run_id = command.run_start.run_id
            self.last_rejection_reason = None
            self._relayed_official_commands[command.seq] = "run_start"
            self._queue_internal_action({
                "kind": "internal_command",
                "vehicle_id": self.mission_coordinator,
                "run_id": self.run_id,
                "command": "RUN_START",
                "command_seq": command.seq,
                "priority": "NORMAL",
                "preempt": False,
                "parameters": {"role": "mission_coordinator"},
            })
            print(f"[RunStart] accepted declaration_seq={self.declaration_seq} run_id={self.run_id}")
        elif body in {
            "assistance_request", "keep_out_zone", "all_clear",
            "moving_object_alert", "readiness_confirm",
        }:
            action = self._relay_official_command(command)
            self._queue_internal_action(action)
            print(
                f"[OfficialRelay] queued {body} to {self.mission_coordinator} "
                f"for official command seq={command.seq}"
            )
        self._last_command_seq = command.seq
        self.last_command = rx_commands_pb2.RxCommand()
        self.last_command.CopyFrom(command)

    def _queue_internal_action(self, *actions: dict) -> None:
        self._pending_internal_actions.extend(actions)

    def drain_internal_actions(self) -> list[dict]:
        """Return and clear actions for the independent vehicle MQTT adapter.

        Each returned action is converted to the team JSON envelope by the
        internal adapter.  Keeping this as an explicit boundary prevents an
        official RoboCommand Protobuf from accidentally being sent to a
        vehicle topic.
        """
        actions = list(self._pending_internal_actions)
        self._pending_internal_actions.clear()
        return actions

    def accept_vehicle_ack(
        self,
        vehicle_id: str,
        *,
        command_seq: int,
        accepted: bool,
        detail: str = "",
        subject_vehicle_id: str | None = None,
    ) -> list[dict]:
        """Translate a vehicle ACK to the official IncidentAck when required.

        The OCS does not infer the vehicle's current task or change its task
        state. The USV is the owner of that decision; this method only applies
        the official response rule to an ACK already received from the link.
        """
        report_vehicle_id = subject_vehicle_id or vehicle_id
        self._check_vehicle(report_vehicle_id)
        body = self._relayed_official_commands.get(command_seq)
        if accepted and body in {"assistance_request", "keep_out_zone", "all_clear"}:
            self.publish_incident_ack(report_vehicle_id, command_seq)
        elif not accepted:
            print(
                f"[VehicleAck] rejected command_seq={command_seq} "
                f"vehicle={vehicle_id}: {detail}",
                file=sys.stderr,
            )
        return []

    def accept_vehicle_readiness_report(
        self,
        vehicle_id: str,
        *,
        command_seq: int,
        subject_vehicle_id: str | None = None,
        readiness_event_id: object = None,
    ) -> list[dict]:
        """Translate a USV readiness event into official ReadinessReport."""
        report_vehicle_id = subject_vehicle_id or vehicle_id
        report_seq, _publish_mid = self._publish_readiness_report_with_sequence(
            report_vehicle_id, command_seq
        )
        if readiness_event_id is not None:
            if not isinstance(readiness_event_id, str) or not readiness_event_id:
                raise ValueError("readiness_event_id must be a non-empty string")
            if self.run_id is None:
                raise ValueError("ReadinessReport cannot be correlated before an active run")
            self._readiness_reports[(self.run_id, report_vehicle_id, report_seq)] = {
                "original_command_seq": command_seq,
                "readiness_event_id": readiness_event_id,
            }
            self._queue_internal_action({
                "kind": "internal_command",
                "vehicle_id": self.mission_coordinator,
                "run_id": self.run_id,
                "command": "TASK4_READINESS_REPORT_PUBLISHED",
                "command_seq": command_seq,
                "priority": "OFFICIAL",
                "preempt": False,
                "parameters": {
                    "vehicle": "usv" if report_vehicle_id == "T-Wave" else "uav",
                    "original_command_seq": command_seq,
                    "report_seq": report_seq,
                    "readiness_event_id": readiness_event_id,
                },
            })
        return []

    def accept_vehicle_envelope(self, envelope: Mapping) -> None:
        """Translate one internal vehicle message to RoboCommand.

        This is deliberately a protocol adapter, not a task arbiter.  The
        USV may send an ``official_report`` after combining UAV/USV evidence;
        OCS publishes that explicitly supplied report without inferring task
        completion by itself.
        """
        vehicle_id = str(envelope.get("vehicle_id", ""))
        if vehicle_id not in self._declared_vehicle_ids:
            raise ValueError(f"vehicle_id {vehicle_id!r} was not declared for this run")
        if envelope.get("source") != vehicle_id:
            raise ValueError("vehicle envelope source must match vehicle_id")
        message_run_id = envelope.get("run_id")
        if self.run_id is not None and message_run_id not in (None, self.run_id):
            print(
                f"[Vehicle] ignored old run message vehicle={vehicle_id} "
                f"run_id={message_run_id}; current={self.run_id}",
                file=sys.stderr,
            )
            return
        kind = envelope.get("kind")
        payload = envelope.get("payload") or {}
        if kind == "heartbeat":
            self._accept_vehicle_heartbeat(envelope)
        elif kind == "ack":
            if payload.get("command_seq") is None:
                raise ValueError("vehicle ACK requires command_seq")
            self.accept_vehicle_ack(
                vehicle_id,
                command_seq=int(payload["command_seq"]),
                accepted=bool(payload.get("accepted", False)),
                detail=str(payload.get("detail", "")),
                subject_vehicle_id=payload.get("subject_vehicle_id"),
            )
        elif kind == "task_report":
            self.accept_vehicle_task_report(vehicle_id, payload)
        elif kind == "fault":
            print(f"[VehicleFault] {vehicle_id}: {payload}", file=sys.stderr)
        elif kind != "command":
            raise ValueError(f"unsupported vehicle message kind: {kind}")

    def accept_fsm_status(self, raw: str) -> None:
        """Record an opaque, formal ROS 2 FSM status without changing its contract."""
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("FSM status must be a JSON object")
        self.latest_fsm_status = value

    def accept_fsm_task_report(self, raw: str) -> None:
        """Consume an FSM ROS 2 report only when it explicitly carries an official report.

        OCS never infers a RoboCommand result from FSM progress/status.  This
        preserves the existing explicit ``official_report`` conversion rule.
        """
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("FSM task_report must be a JSON object")
        self.latest_fsm_task_report = value
        if not isinstance(value.get("official_report"), Mapping):
            return
        # MissionPlanner status uses its domain labels (``usv``/``uav``),
        # whereas RoboCommand identifies the declared vehicles as
        # ``T-Wave``/``T-Sky``.  Normalize only these two frozen labels at the
        # ROS2-to-OCS boundary; all other inputs remain rejected downstream.
        source_vehicle = value.get("vehicle_id", value.get("vehicle"))
        report_vehicle = value["official_report"].get("vehicle_id", source_vehicle)
        vehicle_id = self._official_vehicle_id(source_vehicle)
        official_vehicle_id = self._official_vehicle_id(report_vehicle)
        if vehicle_id is None or official_vehicle_id is None:
            raise ValueError("FSM task_report contains an unknown vehicle label")
        normalized = dict(value)
        normalized_report = dict(value["official_report"])
        normalized_report["vehicle_id"] = official_vehicle_id
        normalized["vehicle_id"] = vehicle_id
        normalized["official_report"] = normalized_report
        self.accept_vehicle_task_report(vehicle_id, normalized)

    def accept_fsm_fault(self, raw: str) -> None:
        """Record a formal FSM fault without inventing an official RxReport body."""
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("FSM fault must be a JSON object")
        self.latest_fsm_fault = dict(value)
        self._record_runtime_event(
            "ros2", "fsm_fault", topic="/tongji_mrl/mission/fault",
            run_id=value.get("run_id") if isinstance(value.get("run_id"), int) else None,
            command_seq=value.get("command_seq") if isinstance(value.get("command_seq"), int) else None,
            detail=str(value.get("error") or value.get("error_code") or "FSM fault"),
        )

    @staticmethod
    def _official_vehicle_id(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        if value in {"T-Wave", "T-Sky"}:
            return value
        return {"usv": "T-Wave", "uav": "T-Sky"}.get(value)

    def set_authoritative_current_task(self, vehicle_id: str, current_task: str | None) -> None:
        """Set task state only from a confirmed MissionCoordinator contract."""
        self._check_vehicle(vehicle_id)
        if current_task is None:
            self._authoritative_current_task.pop(vehicle_id, None)
            return
        _enum(current_task, TASK_MAP, "current_task")
        self._authoritative_current_task[vehicle_id] = current_task

    def _accept_vehicle_heartbeat(self, envelope: Mapping) -> None:
        try:
            self.heartbeat_cache.accept(envelope, active_run_id=self.run_id)
        except HeartbeatRejected as exc:
            print(f"[VehicleHeartbeat] rejected {envelope.get('vehicle_id')}: {exc}", file=sys.stderr)

    def publish_cached_heartbeats(self) -> int:
        """Publish fresh telemetry at the gateway's 2 Hz timer cadence."""
        count = 0
        for vehicle_id in sorted(self._declared_vehicle_ids):
            entry = self.heartbeat_cache.valid(vehicle_id, active_run_id=self.run_id)
            if entry is None:
                continue
            payload, position = entry.payload, entry.payload["position"]
            self.publish_heartbeat(
                vehicle_id, state=payload["state"],
                latitude=float(position["latitude_deg"]), longitude=float(position["longitude_deg"]),
                speed_mps=float(payload["speed_mps"]), heading_deg=float(payload["heading_deg"]),
                vehicle_type=str(payload["vehicle_type"]),
                current_task=self._authoritative_current_task.get(vehicle_id, "unknown"),
                roll_deg=float(payload["roll_deg"]), pitch_deg=float(payload["pitch_deg"]),
                altitude_hae_m=float(position["altitude_hae_m"]),
                depth_m=float(payload.get("depth_m", 0.0)),
                flight_phase=str(payload.get("flight_phase", "unknown")),
            )
            count += 1
        return count

    def accept_vehicle_task_report(self, vehicle_id: str, payload: Mapping) -> None:
        """Publish an explicitly supplied official report.

        A plain ``phase=COMPLETE`` is logged but is not converted into an
        official report.  For combined tasks, the USV coordinator should send
        one authoritative ``official_report`` after incorporating UAV data.
        """
        report = payload.get("official_report")
        if not isinstance(report, Mapping):
            print(f"[VehicleTaskReport] {vehicle_id}: no official_report; logged only")
            return
        report_type = str(report.get("type", "")).lower()
        report_vehicle_id = str(report.get("vehicle_id", vehicle_id))
        self._check_vehicle(report_vehicle_id)
        if report_type == "safe_passage":
            entry = report.get("entry_position")
            exit_position = report.get("exit_position")
            buoys = [
                (float(item["latitude"]), float(item["longitude"]), item.get("state", "unknown"))
                for item in report.get("buoys", [])
            ]
            self.publish_safe_passage_report(
                report_vehicle_id,
                entry_position=(float(entry["latitude"]), float(entry["longitude"])) if entry else None,
                exit_position=(float(exit_position["latitude"]), float(exit_position["longitude"])) if exit_position else None,
                buoys=buoys,
            )
        elif report_type == "docking":
            self.publish_docking_report(report_vehicle_id, int(report["bay_id"]))
        elif report_type == "firefighting":
            self.publish_firefighting_report(report_vehicle_id, int(report["window_id"]))
        elif report_type == "resource_delivery":
            self.publish_resource_delivery_request(
                report_vehicle_id,
                resource_color=report["resource_color"],
                delivery_circle_color=report["delivery_circle_color"],
            )
        elif report_type == "incident_ack":
            self.publish_incident_ack(report_vehicle_id, int(report["command_seq"]))
        elif report_type == "readiness":
            self.accept_vehicle_readiness_report(
                vehicle_id,
                command_seq=int(report["command_seq"]),
                subject_vehicle_id=report_vehicle_id,
                readiness_event_id=report.get("readiness_event_id"),
            )
        else:
            raise ValueError(f"unsupported official_report type: {report_type}")

    def _relay_official_command(self, command: rx_commands_pb2.RxCommand) -> dict:
        """Convert an official Task 4 command into one USV-facing action.

        This is routing and serialization only. The USV decides whether the
        command affects itself, the UAV, or the current task state.
        """
        body_name = command.WhichOneof("body")
        parameters: dict = {
            "official_command_seq": command.seq,
            "official_body": body_name,
            "official_vehicle_id": command.vehicle_id or None,
            "decision_owner": "USV",
        }
        body = getattr(command, body_name)
        if body_name == "assistance_request":
            parameters.update({
                "position": {
                    "latitude": body.position.latitude,
                    "longitude": body.position.longitude,
                },
                "vehicle_type": int(body.vehicle_type),
            })
        elif body_name == "keep_out_zone":
            parameters.update({
                "center": {
                    "latitude": body.center.latitude,
                    "longitude": body.center.longitude,
                },
                "radius_m": body.radius_m,
                "vehicle_type": int(body.vehicle_type),
            })
        elif body_name == "all_clear":
            parameters["vehicle_type"] = int(body.vehicle_type)
        elif body_name == "moving_object_alert":
            parameters.update({
                "position": {
                    "latitude": body.position.latitude,
                    "longitude": body.position.longitude,
                },
                "heading_deg": body.heading_deg,
                "speed_mps": body.speed_mps,
                "affected_vehicle_types": [int(value) for value in body.affected_vehicle_types],
                # Preserve the official scalar exactly.  Proto3 uses 0.0 for
                # an omitted field; the OCS must not replace it with a local
                # fixed radius.
                "keep_out_radius_m": body.keep_out_radius_m,
            })
        elif body_name == "readiness_confirm":
            vehicle_id = self._official_vehicle_id(body.vehicle_id)
            if vehicle_id is None or self.run_id is None:
                raise ValueError("ReadinessConfirm vehicle_id or active run is invalid")
            record = self._readiness_reports.get((self.run_id, vehicle_id, body.report_seq))
            if record is None:
                raise ValueError("ReadinessConfirm does not match an OCS-published ReadinessReport")
            parameters.update({
                "report_seq": body.report_seq,
                "vehicle_id": vehicle_id,
                "vehicle": "usv" if vehicle_id == "T-Wave" else "uav",
                "original_command_seq": record["original_command_seq"],
                "readiness_event_id": record["readiness_event_id"],
            })
        else:
            raise ValueError(f"unsupported official command body: {body_name}")

        self._relayed_official_commands[command.seq] = body_name
        return {
            "kind": "internal_command",
            "vehicle_id": self.mission_coordinator,
            "run_id": self.run_id,
            "command": {
                "assistance_request": "TASK4_ASSISTANCE",
                "keep_out_zone": "TASK4_KEEP_OUT_ZONE",
                "all_clear": "TASK4_ALL_CLEAR",
                "moving_object_alert": "TASK4_MOVING_OBJECT",
                "readiness_confirm": "TASK4_READINESS_CONFIRM",
            }[body_name],
            "command_seq": command.seq,
            # OCS transports the official event.  The USV owns the local
            # priority/preemption decision and must not rely on this flag.
            "priority": "OFFICIAL",
            "preempt": False,
            "parameters": parameters,
        }

    def _check_vehicle(self, vehicle_id: str) -> None:
        if not vehicle_id:
            raise ValueError("vehicle_id must not be empty")
        if self._declared_vehicle_ids and vehicle_id not in self._declared_vehicle_ids:
            raise ValueError(f"vehicle_id {vehicle_id!r} was not declared for this run")

    def _next_report_seq(self, vehicle_id: str) -> int:
        with self._report_lock:
            seq = self._report_seq.get(vehicle_id, 0) + 1
            self._report_seq[vehicle_id] = seq
            return seq

    def _publish_vehicle_body(self, vehicle_id: str, body_name: str, body) -> int:
        self._check_vehicle(vehicle_id)
        seq = self._next_report_seq(vehicle_id)
        report = rx_reports_pb2.RxReport(
            team_id=self.team_id,
            vehicle_id=vehicle_id,
            seq=seq,
            sent_at=now_timestamp(),
        )
        getattr(report, body_name).CopyFrom(body)
        topic = f"{TOPIC_ROOT}/{self.team_id}/{vehicle_id}/report"
        return self._publish(topic, report)

    def _publish(self, topic: str, message) -> int:
        result = self.client.publish(topic, message.SerializeToString(), qos=1)
        result.wait_for_publish()
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            self._record_runtime_event("mqtt", "publish_failed", topic=topic, detail=str(result.rc))
            raise RuntimeError(f"publish failed ({result.rc}) on {topic}")
        print(f"Published {type(message).__name__} -> {topic}")
        return result.mid

    def publish_run_declaration(
        self,
        vehicle_ids: Sequence[str],
        task_tiers: Sequence[int | str] = ("disruptive", "none", "disruptive", "disruptive"),
        uav_geofence: Iterable[tuple[float, float]] = (),
        uav_geofence_max_altitude_hae_m: float | None = None,
        uav_pilot_callsign: str | None = None,
    ) -> int:
        ids = [item.strip() for item in vehicle_ids if item.strip()]
        if not ids:
            raise ValueError("at least one vehicle_id is required")
        if len(set(ids)) != len(ids):
            raise ValueError("vehicle_ids must be unique")
        if len(task_tiers) != 4:
            raise ValueError("task_tiers must contain Task1 through Task4")
        fence = [_lat_lng(lat, lng) for lat, lng in uav_geofence]
        if fence and fence[0] != fence[-1]:
            raise ValueError("uav_geofence must be a closed polygon (first point = last point)")
        if "T-Sky" in ids:
            if not fence:
                raise ValueError("a declared UAV requires a non-empty uav_geofence")
            if (isinstance(uav_geofence_max_altitude_hae_m, bool)
                    or not isinstance(uav_geofence_max_altitude_hae_m, (int, float))
                    or not 0 < float(uav_geofence_max_altitude_hae_m) <= 50):
                raise ValueError("a declared UAV requires uav_geofence_max_altitude_hae_m in (0, 50]")
            if not isinstance(uav_pilot_callsign, str) or not uav_pilot_callsign.strip():
                raise ValueError("a declared UAV requires a non-empty uav_pilot_callsign")
        self._declared_vehicle_ids = set(ids)
        self.run_id = None
        self.last_command = None
        self._last_command_seq = 0
        self._report_seq.clear()
        self.heartbeat_cache = HeartbeatCache()
        self._authoritative_current_task.clear()
        self._pending_internal_actions.clear()
        self._relayed_official_commands.clear()
        self._readiness_reports.clear()
        self._team_seq += 1
        declaration = rx_requests_pb2.RunDeclaration(
            vehicle_ids=ids,
            task1_tier=_enum(task_tiers[0], TIER_MAP, "task1 tier"),
            task2_tier=_enum(task_tiers[1], TIER_MAP, "task2 tier"),
            task3_tier=_enum(task_tiers[2], TIER_MAP, "task3 tier"),
            task4_tier=_enum(task_tiers[3], TIER_MAP, "task4 tier"),
            uav_geofence=fence,
            uav_geofence_max_altitude_hae_m=float(uav_geofence_max_altitude_hae_m or 0),
            uav_pilot_callsign=(uav_pilot_callsign or "").strip(),
        )
        request = rx_requests_pb2.RxRequest(
            team_id=self.team_id,
            seq=self._team_seq,
            sent_at=now_timestamp(),
            run_declaration=declaration,
        )
        self.declaration_seq = request.seq
        return self._publish(self.request_topic, request)

    def publish_heartbeat(
        self,
        vehicle_id: str,
        *,
        state: int | str = "auto",
        latitude: float,
        longitude: float,
        speed_mps: float = 0.0,
        heading_deg: float = 0.0,
        vehicle_type: int | str = "usv",
        current_task: int | str = "none",
        roll_deg: float = 0.0,
        pitch_deg: float = 0.0,
        altitude_hae_m: float = 0.0,
        depth_m: float = 0.0,
        flight_phase: int | str = "unknown",
        uav_registration: str | None = None,
    ) -> int:
        self._check_vehicle(vehicle_id)
        resolved_vehicle_type = _enum(vehicle_type, TYPE_MAP, "vehicle_type")
        if uav_registration is not None and not isinstance(uav_registration, str):
            raise ValueError("uav_registration must be a string or null")
        if uav_registration and resolved_vehicle_type != rx_common_pb2.TYPE_UAV:
            raise ValueError("uav_registration is only valid for a UAV heartbeat")
        seq = self._next_report_seq(vehicle_id)
        report = rx_reports_pb2.RxReport(
            team_id=self.team_id,
            vehicle_id=vehicle_id,
            seq=seq,
            sent_at=now_timestamp(),
            heartbeat=rx_reports_pb2.Heartbeat(
                state=_enum(state, STATE_MAP, "state"),
                position=_lat_lng(latitude, longitude),
                spd_mps=speed_mps,
                heading_deg=heading_deg,
                roll_deg=roll_deg,
                pitch_deg=pitch_deg,
                altitude_hae_m=altitude_hae_m,
                depth_m=depth_m,
                current_task=_enum(current_task, TASK_MAP, "current_task"),
                vehicle_type=resolved_vehicle_type,
                flight_phase=_enum(flight_phase, FLIGHT_PHASE_MAP, "flight_phase"),
                uav_registration=uav_registration or "",
            ),
        )
        topic = f"{TOPIC_ROOT}/{self.team_id}/{vehicle_id}/report"
        return self._publish(topic, report)

    def publish_safe_passage_report(
        self,
        vehicle_id: str,
        *,
        entry_position: tuple[float, float] | None = None,
        exit_position: tuple[float, float] | None = None,
        buoys: Iterable[tuple[float, float, int | str]] = (),
    ) -> int:
        """Publish the current Task 1 buoy map from a ROS/vehicle adapter."""
        body = rx_reports_pb2.SafePassageReport()
        if entry_position:
            body.entry_position.CopyFrom(_lat_lng(*entry_position))
        if exit_position:
            body.exit_position.CopyFrom(_lat_lng(*exit_position))
        for lat, lng, state in buoys:
            detection = body.buoys.add()
            detection.position.CopyFrom(_lat_lng(lat, lng))
            detection.state = _enum(state, BEACON_MAP, "beacon state")
        return self._publish_vehicle_body(vehicle_id, "safe_passage", body)

    def publish_docking_report(self, vehicle_id: str, bay_id: int) -> int:
        if not 1 <= bay_id <= 3:
            raise ValueError("bay_id must be between 1 and 3")
        return self._publish_vehicle_body(
            vehicle_id, "docking", rx_reports_pb2.DockingReport(bay_id=bay_id)
        )

    def publish_firefighting_report(self, vehicle_id: str, window_id: int) -> int:
        if window_id <= 0:
            raise ValueError("window_id must be positive")
        return self._publish_vehicle_body(
            vehicle_id,
            "firefighting",
            rx_reports_pb2.FirefightingReport(window_id=window_id),
        )

    def publish_resource_delivery_request(
        self,
        vehicle_id: str,
        *,
        resource_color: int | str,
        delivery_circle_color: int | str,
        task: int | str = "coordinated-logistics",
    ) -> int:
        body = rx_reports_pb2.ResourceDeliveryRequest(
            task=_enum(task, TASK_MAP, "task"),
            resource_color=_enum(resource_color, COLOR_MAP, "resource_color"),
            delivery_circle_color=_enum(
                delivery_circle_color, COLOR_MAP, "delivery_circle_color"
            ),
        )
        return self._publish_vehicle_body(vehicle_id, "resource_delivery", body)

    def publish_incident_ack(self, vehicle_id: str, command_seq: int) -> int:
        if command_seq <= 0:
            raise ValueError("command_seq must be positive")
        return self._publish_vehicle_body(
            vehicle_id, "incident_ack", rx_reports_pb2.IncidentAck(command_seq=command_seq)
        )

    def publish_readiness_report(self, vehicle_id: str, command_seq: int) -> int:
        if command_seq <= 0:
            raise ValueError("command_seq must be positive")
        _report_seq, publish_mid = self._publish_readiness_report_with_sequence(
            vehicle_id, command_seq
        )
        return publish_mid

    def _publish_readiness_report_with_sequence(
        self, vehicle_id: str, command_seq: int
    ) -> tuple[int, int]:
        """Publish ReadinessReport and retain its official per-vehicle seq."""
        if command_seq <= 0:
            raise ValueError("command_seq must be positive")
        self._check_vehicle(vehicle_id)
        report_seq = self._next_report_seq(vehicle_id)
        report = rx_reports_pb2.RxReport(
            team_id=self.team_id,
            vehicle_id=vehicle_id,
            seq=report_seq,
            sent_at=now_timestamp(),
            readiness=rx_reports_pb2.ReadinessReport(command_seq=command_seq),
        )
        topic = f"{TOPIC_ROOT}/{self.team_id}/{vehicle_id}/report"
        return report_seq, self._publish(topic, report)


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def config_values(config: dict) -> tuple[str, str, int, list[str]]:
    team_id = config.get("team_id", "TONG")
    official = config.get("robocommand", {})
    internal = config.get("internal_broker", {})
    host = str(official.get("host") or "")
    if not host or host.startswith(("TBD", "COURSE_HOST")):
        raise ValueError("robocommand.host must be explicitly configured; internal_broker is heartbeat-only")
    port = int(official.get("port", 1883))
    vehicles = [
        str(item["vehicle_id"])
        for item in config.get("vehicles", {}).values()
        if item.get("vehicle_id")
    ]
    return team_id, host, port, vehicles or ["T-Sky", "T-Wave"]


def declaration_values(config: dict) -> tuple[tuple[str, str, str, str], list[tuple[float, float]], float | None, str | None]:
    declaration = config.get("run_declaration", {})
    tiers = declaration.get("task_tiers", {})
    task_tiers = (
        str(tiers.get("task1", "disruptive")),
        str(tiers.get("task2", "none")),
        str(tiers.get("task3", "disruptive")),
        str(tiers.get("task4", "disruptive")),
    )
    geofence = [
        (float(point["latitude"]), float(point["longitude"]))
        for point in declaration.get("uav_geofence", [])
    ]
    altitude = declaration.get("uav_geofence_max_altitude_hae_m")
    callsign = declaration.get("uav_pilot_callsign")
    return task_tiers, geofence, altitude, callsign


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tongji OCS client for the official RoboCommand MQTT interface",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--broker", help="override broker host; default comes from config")
    parser.add_argument("--port", type=int, help="override broker port; default comes from config")
    parser.add_argument("--duration", type=float, default=10.0, help="seconds to keep the client connected")
    parser.add_argument("--publish-declaration", action="store_true", help="publish current TONG declaration")
    parser.add_argument("--demo-heartbeats", action="store_true", help="publish synthetic heartbeats at 2 Hz")
    parser.add_argument(
        "--demo-task3",
        action="store_true",
        help="publish synthetic Task 3 reports after RunStart (local broker test only)",
    )
    args = parser.parse_args()

    if args.demo_task3 and not (args.publish_declaration and args.demo_heartbeats):
        parser.error("--demo-task3 requires --publish-declaration and --demo-heartbeats")

    config = load_config(args.config)
    team_id, host, port, vehicles = config_values(config)
    task_tiers, uav_geofence, uav_altitude, uav_pilot_callsign = declaration_values(config)
    host = args.broker or host
    port = args.port or port
    client = OcsClient(host, port, team_id)
    try:
        client.connect()
        if args.publish_declaration:
            client.publish_run_declaration(
                vehicles, task_tiers, uav_geofence,
                uav_geofence_max_altitude_hae_m=uav_altitude,
                uav_pilot_callsign=uav_pilot_callsign,
            )
        if args.demo_heartbeats:
            deadline = time.monotonic() + args.duration
            task3_published = False
            while time.monotonic() < deadline:
                for vehicle_id in vehicles:
                    vehicle_type = "uav" if "sky" in vehicle_id.lower() else "usv"
                    client.publish_heartbeat(
                        vehicle_id,
                        latitude=1.2806142,
                        longitude=103.8557120,
                        vehicle_type=vehicle_type,
                        flight_phase="grounded" if vehicle_type == "uav" else "unknown",
                    )
                if args.demo_task3 and client.run_id is not None and not task3_published:
                    client.publish_docking_report("T-Wave", bay_id=1)
                    client.publish_firefighting_report("T-Wave", window_id=1)
                    client.publish_resource_delivery_request(
                        "T-Wave",
                        resource_color="red",
                        delivery_circle_color="blue",
                    )
                    print(f"[DemoTask3] published with run_id={client.run_id}")
                    task3_published = True
                time.sleep(0.5)
        else:
            time.sleep(max(0.0, args.duration))
    except KeyboardInterrupt:
        print("\nStopping OCS client...")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
