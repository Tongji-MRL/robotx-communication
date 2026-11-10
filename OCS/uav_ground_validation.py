#!/usr/bin/env python3
"""UAV-only ground screening: Course -> declaration -> real 2 Hz telemetry.

This entry directly subscribes to the UAV status ROS 2 topic (std_msgs/String).
Only the official RoboCommand link uses MQTT. There is no vehicle command publisher. RunStart is
validated and recorded, but never causes a flight or task action.
"""
from __future__ import annotations

import argparse
import json
import math
import queue
import re
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

try:
    from . import ocs_client as protocol
    from .uav_status import normalize_uav_status
except ImportError:
    import ocs_client as protocol
    from uav_status import normalize_uav_status

STATUS_TOPIC = "/tongji_mrl/tsky/uav_status"
# The UAV team supplied these ROS 2 String topic names and depth only.  Their
# JSON schema and the FCU readback contract have not yet been supplied, so this
# entry subscribes for diagnostics only and never publishes a guessed payload.
UAV_GEOFENCE_APPLY_TOPIC = "/tongji_mrl/tsky/uav_geofense_sub"
UAV_GEOFENCE_READBACK_TOPIC = "/tongji_mrl/tsky/uav_geofense_pub"
DEFAULT_CONFIG = Path(__file__).with_name("config.uav-ground.example.json")
MAX_STATUS_AGE_S = 3.0
HEARTBEAT_PERIOD_S = 0.5
HEARTBEAT_ACK_TIMEOUT_S = 5.0
MAX_PENDING_HEARTBEATS = 4
SCENARIOS = ("normal", "outside-course", "over-height")
TEST_SERVER_MAX_ALTITUDE_HAE_M = 50.0


def build_ground_heartbeat(normalized, *, registration=""):
    """Map measured fields; ground screening explicitly has no task attempt.

    The official edition-2024 schema preserves scalar presence. Unavailable
    attitude is left unset, not filled with synthetic zeros.
    """
    raw = normalized["raw"]
    position = normalized["position"]
    heartbeat = protocol.rx_reports_pb2.Heartbeat(
        state=protocol.STATE_MAP[normalized["state"].lower()],
        position=protocol._lat_lng(position["latitude_deg"], position["longitude_deg"]),
        spd_mps=normalized["speed_mps"], heading_deg=normalized["heading_deg"],
        altitude_hae_m=position["altitude_hae_m"],
        current_task=protocol.rx_common_pb2.TASK_NONE,
        vehicle_type=protocol.rx_common_pb2.TYPE_UAV,
        flight_phase=protocol.FLIGHT_PHASE_MAP[normalized["flight_phase"]],
    )
    for field, low, high in (("roll_deg", -180, 180), ("pitch_deg", -90, 90)):
        if field in raw:
            value = raw[field]
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not low <= value <= high):
                raise ValueError(f"{field} must be finite and in [{low}, {high}]")
            setattr(heartbeat, field, value)
    source_registration = raw.get("uav_registration", "")
    if not isinstance(source_registration, str):
        raise ValueError("uav_registration must be a string")
    if registration and source_registration and registration != source_registration:
        raise ValueError("UAV registration does not match configured aircraft")
    if registration or source_registration:
        heartbeat.uav_registration = registration or source_registration
    return heartbeat


class GroundOcsClient(protocol.OcsClient):
    """Process incoming state on the main thread, never block the Paho loop."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._events = queue.Queue(maxsize=256)
        self._overflow = False
        self._heartbeat_pending = {}
        self._heartbeat_early_pubacks = set()
        self._heartbeat_publish_reservations = 0
        self._heartbeat_stats = {"queued": 0, "confirmed": 0, "ack_timeouts": 0,
                                 "dropped_pending_limit": 0, "publish_errors": 0}
        self._heartbeat_lock = threading.RLock()
        self.expect_rejection = False
        self.unexpected_run_start = None
        self.client.on_publish = self._on_publish

    def _enqueue(self, event):
        try:
            self._events.put_nowait(event)
        except queue.Full:
            self._overflow = True

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self._enqueue(("connect", (client, userdata, flags, reason_code, properties)))

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = False
        self._enqueue(("disconnect", (client, userdata, flags, reason_code, properties)))

    def _on_message(self, _client, _userdata, message):
        self._enqueue(("message", SimpleNamespace(
            topic=message.topic, payload=bytes(message.payload), retain=message.retain)))

    def _on_publish(self, _client, _userdata, mid, _reason_code=None, _properties=None):
        with self._heartbeat_lock:
            pending = self._heartbeat_pending.pop(mid, None)
            if pending is None and self._heartbeat_publish_reservations:
                self._heartbeat_early_pubacks.add(mid)
            elif pending is not None:
                self._heartbeat_stats["confirmed"] += 1

    def _expire_heartbeat_pending(self, now=None):
        now = time.monotonic() if now is None else now
        with self._heartbeat_lock:
            for pending in self._heartbeat_pending.values():
                if not pending["timed_out"] and now - pending["queued_at"] >= HEARTBEAT_ACK_TIMEOUT_S:
                    pending["timed_out"] = True
                    self._heartbeat_stats["ack_timeouts"] += 1

    def heartbeat_transport_status(self):
        self._expire_heartbeat_pending()
        with self._heartbeat_lock:
            return {**self._heartbeat_stats, "pending": len(self._heartbeat_pending),
                    "timed_out_pending": sum(item["timed_out"] for item in self._heartbeat_pending.values())}

    def process_events(self):
        if self._overflow:
            raise RuntimeError("official MQTT input queue overflow; restart and inspect traffic")
        for _ in range(256):
            try:
                kind, value = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "connect":
                super()._on_connect(*value)
            elif kind == "disconnect":
                super()._on_disconnect(*value)
            elif value.topic == self.command_topic and value.retain:
                print("[Ground] ignored retained command; RunStart must be current", file=sys.stderr)
            else:
                super()._on_message(None, None, value)

    def _accept_command(self, command):
        if command.WhichOneof("body") != "run_start":
            print("[Ground] task command ignored: ground screening has no task execution")
            return
        if self.run_id is not None:
            if (command.run_start.run_id == self.run_id
                    and command.run_start.declaration_seq == self.declaration_seq):
                return
            raise ValueError("a different RunStart cannot replace this ground session")
        super()._accept_command(command)
        self.drain_internal_actions()  # No flight/task/USV command ever leaves this entry.
        if self.expect_rejection:
            # Keep this flag outside exceptions: OcsClient._on_message catches
            # malformed-message exceptions, but must not hide this test failure.
            self.unexpected_run_start = {
                "run_id": self.run_id, "declaration_seq": self.declaration_seq,
            }

    def _publish(self, topic, message):
        """Reliable synchronous path reserved for RunDeclaration."""
        result = self.client.publish(topic, message.SerializeToString(), qos=1, retain=False)
        if result.rc != protocol.mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"MQTT publish rejected: rc={result.rc}, topic={topic}")
        result.wait_for_publish(timeout=3.0)
        if not result.is_published():
            # An ambiguous declaration must not be blindly retried as a new flight.
            raise TimeoutError(f"MQTT PUBACK not received within 3s: {topic}")
        return result.mid

    def _publish_heartbeat(self, topic, message):
        """Queue one QoS1 Heartbeat without making the 2 Hz scheduler wait for PUBACK."""
        # Existing isolated unit fixtures replace _publish with an in-memory
        # serializer.  Preserve that explicit test seam; production instances
        # always use the non-blocking Paho path below.
        if "_publish" in self.__dict__:
            return self._publish(topic, message)
        self._expire_heartbeat_pending()
        with self._heartbeat_lock:
            if len(self._heartbeat_pending) >= MAX_PENDING_HEARTBEATS:
                self._heartbeat_stats["dropped_pending_limit"] += 1
                return None
            self._heartbeat_publish_reservations += 1
            try:
                result = self.client.publish(topic, message.SerializeToString(), qos=1, retain=False)
            finally:
                self._heartbeat_publish_reservations -= 1
        if result.rc != protocol.mqtt.MQTT_ERR_SUCCESS:
            with self._heartbeat_lock:
                self._heartbeat_stats["publish_errors"] += 1
            raise ConnectionError(f"MQTT heartbeat publish rejected: rc={result.rc}, topic={topic}")
        with self._heartbeat_lock:
            if result.mid in self._heartbeat_early_pubacks or result.is_published():
                self._heartbeat_early_pubacks.discard(result.mid)
                self._heartbeat_stats["confirmed"] += 1
            else:
                self._heartbeat_pending[result.mid] = {"queued_at": time.monotonic(), "timed_out": False}
                self._heartbeat_stats["queued"] += 1
        return result.mid

    def _publish_vehicle_body(self, vehicle_id, body_name, body):
        if body_name != "heartbeat":
            return super()._publish_vehicle_body(vehicle_id, body_name, body)
        self._check_vehicle(vehicle_id)
        seq = self._next_report_seq(vehicle_id)
        report = protocol.rx_reports_pb2.RxReport(
            team_id=self.team_id, vehicle_id=vehicle_id, seq=seq, sent_at=protocol.now_timestamp())
        getattr(report, body_name).CopyFrom(body)
        return self._publish_heartbeat(f"{protocol.TOPIC_ROOT}/{self.team_id}/{vehicle_id}/report", report)

    def connect(self):
        self.client.connect_async(self.broker_host, self.broker_port, keepalive=30)
        self.client.loop_start()


class GroundValidationSession:
    def __init__(self, config, *, ocs=None, clock=time.monotonic,
                 wall_clock=time.time, emit=None, scenario="normal",
                 test_max_altitude_hae=60.0, outside_offset_m=20.0):
        self.config = config
        self.clock, self.wall_clock = clock, wall_clock
        self.emit = emit or (lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
        if scenario not in SCENARIOS:
            raise ValueError(f"scenario must be one of {SCENARIOS}")
        if (type(test_max_altitude_hae) not in (int, float) or not math.isfinite(test_max_altitude_hae)
                or not TEST_SERVER_MAX_ALTITUDE_HAE_M < test_max_altitude_hae <= 100000):
            raise ValueError("test_max_altitude_hae must be finite and in (50, 100000] m HAE")
        if (type(outside_offset_m) not in (int, float) or not math.isfinite(outside_offset_m)
                or not 2 <= outside_offset_m <= 100000):
            raise ValueError("outside_offset_m must be finite and in [2, 100000] m, above server tolerance")
        self.scenario = scenario
        self.test_max_altitude_hae = protocol.rx_requests_pb2.RunDeclaration(
            uav_geofence_max_altitude_hae_m=float(test_max_altitude_hae),
        ).uav_geofence_max_altitude_hae_m
        if self.test_max_altitude_hae <= TEST_SERVER_MAX_ALTITUDE_HAE_M:
            raise ValueError("test_max_altitude_hae must remain above 50 m after protobuf encoding")
        self.outside_offset_m = float(outside_offset_m)
        self.expected_result = "accepted_when_ready" if scenario == "normal" else "rejected"
        vehicles = config.get("vehicles", {})
        if set(vehicles) != {"uav"}:
            raise ValueError("ground screening requires exactly one vehicles.uav entry")
        self.vehicle_id = vehicles["uav"].get("vehicle_id")
        if (not isinstance(self.vehicle_id, str)
                or (self.vehicle_id != "T-Sky" and re.fullmatch(r"UAV[A-Za-z0-9_-]*", self.vehicle_id) is None)):
            raise ValueError("ground vehicle_id must be T-Sky or a topic-safe UAV-prefixed ID such as UAV1")
        if scenario != "normal" and not self.vehicle_id.startswith("UAV"):
            raise ValueError("negative scenarios require a UAV-prefixed vehicle_id for official server validation")
        self.source_vehicle_id = vehicles["uav"].get("source_vehicle_id")
        if not isinstance(self.source_vehicle_id, str) or not self.source_vehicle_id.strip():
            raise ValueError("vehicles.uav.source_vehicle_id is required")
        self.registration = vehicles["uav"].get("uav_registration", "")
        if not isinstance(self.registration, str):
            raise ValueError("configured uav_registration must be a string")
        team, host, port, _ = protocol.config_values(config)
        if not isinstance(team, str) or re.fullmatch(r"[A-Za-z0-9_-]+", team) is None:
            raise ValueError("ground team_id must be a non-empty topic-safe identifier")
        self.declaration = protocol.declaration_values(config)
        self.geofence_options = protocol.geofence_options(config)
        if any(tier.lower() != "none" for tier in self.declaration[0]):
            raise ValueError("ground screening requires all four task tiers=none")
        if not isinstance(self.declaration[3], str) or not self.declaration[3].strip():
            raise ValueError("run_declaration.uav_pilot_callsign is required")
        self.ocs = ocs or GroundOcsClient(host, port, team)
        self.ocs.expect_rejection = scenario != "normal"
        self.telemetry_available = False
        self.latest_status = None
        self._status_received = None
        self._next_heartbeat = 0.0
        self._stage = None
        self._last_run_id = None
        self._connection_epoch = self.ocs._course_connection_epoch
        self._publish_error = None
        self._fatal_error = None
        self._submitted_declaration_seq = None
        self._submitted_course_fingerprint = None
        self._prepared_geofence = None
        self._geofence_block_reason = None
        self.heartbeat_count = 0

    def event(self, event, **fields):
        self.emit({"event": event, "timestamp_unix_ms": int(self.wall_clock() * 1000),
                   "team_id": self.ocs.team_id, "vehicle_id": self.vehicle_id,
                   "scenario": self.scenario, "expected_result": self.expected_result, **fields})

    def fail_scenario(self, reason, **fields):
        self._fatal_error = reason
        self.ocs.drain_internal_actions()
        self.event("SCENARIO_FAILED", outcome="failed", reason=reason,
                   vehicle_commands_sent=0, **fields)
        raise RuntimeError(reason)

    def prepare_declaration(self):
        """Validate the normal baseline, then apply one explicit test mutation."""
        tiers, fence, altitude, pilot = self.declaration
        mode, margin, limit = self.geofence_options
        baseline = self.ocs._build_run_declaration(
            [self.vehicle_id], tiers, fence,
            uav_geofence_max_altitude_hae_m=altitude, uav_pilot_callsign=pilot,
            uav_geofence_mode=mode, uav_geofence_margin_m=margin,
            uav_geofence_altitude_limit_hae_m=limit,
        )
        declaration = protocol.rx_requests_pb2.RunDeclaration()
        declaration.CopyFrom(baseline)
        if self.scenario == "over-height":
            declaration.uav_geofence_max_altitude_hae_m = self.test_max_altitude_hae
        elif self.scenario == "outside-course":
            course = self.ocs.course_store.get()
            allowed_points = list(course.corners) + list(course.uav_transit_area)
            northern_bound = max(latitude for latitude, _ in allowed_points)
            south_edge = min(point.latitude for point in declaration.uav_geofence)
            # Translate the entire closed ring beyond both received polygons.
            # The >=2 m margin also exceeds the sample server's 1 m tolerance.
            latitude_shift = northern_bound - south_edge + math.degrees(self.outside_offset_m / 6371000.0)
            translated = []
            for point in declaration.uav_geofence:
                latitude, longitude = point.latitude + latitude_shift, point.longitude
                if (not math.isfinite(latitude) or not math.isfinite(longitude)
                        or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
                    raise ValueError("outside-course translation exceeds valid latitude/longitude range")
                if latitude <= northern_bound:
                    raise ValueError("outside-course offset cannot be represented beyond the course extent")
                translated.append(protocol._lat_lng(latitude, longitude))
            del declaration.uav_geofence[:]
            declaration.uav_geofence.extend(translated)
        return declaration

    def stage(self, name):
        if name != self._stage:
            self._stage = name
            self.event("STAGE", state=name)

    def on_telemetry_unavailable(self):
        self.telemetry_available = False
        self.latest_status = None
        self._status_received = None

    def on_status(self, raw, *, received_monotonic=None):
        try:
            status = normalize_uav_status(raw, source_vehicle_id=self.source_vehicle_id,
                                          vehicle_id=self.vehicle_id,
                                          received_unix_ms=int(self.wall_clock() * 1000))
            source = status["raw"]
            if (source.get("source_mode") not in (None, "real")
                    or source.get("simulation") is True
                    or (isinstance(source.get("health"), dict) and source["health"].get("simulator"))):
                raise ValueError("simulated telemetry is not accepted by ground screening")
            stamp = source.get("sent_at_unix_ms", source.get("timestamp_unix_ms"))
            if stamp is not None:
                if type(stamp) is not int or abs(self.wall_clock() * 1000 - stamp) > MAX_STATUS_AGE_S * 1000:
                    raise ValueError("UAV source timestamp is invalid or stale")
            build_ground_heartbeat(status, registration=self.registration)
            self.latest_status = status
            self._status_received = self.clock() if received_monotonic is None else received_monotonic
            return True
        except (ValueError, TypeError, KeyError) as exc:
            self.latest_status = None
            self._status_received = None
            self.event("UAV_REJECTED", reason=str(exc))
            return False

    def tick(self):
        if self._fatal_error is not None:
            raise RuntimeError(self._fatal_error)
        if self._publish_error is not None:
            raise RuntimeError(f"ground publication failed; restart after checking broker: {self._publish_error}")
        self.ocs.process_events()
        if self.scenario != "normal" and self.ocs.unexpected_run_start is not None:
            self.fail_scenario("unexpected matching RunStart for a negative declaration",
                               **self.ocs.unexpected_run_start)
        if self.scenario != "normal" and self._submitted_declaration_seq is not None:
            if (not self.ocs.connected
                    or self.ocs._course_connection_epoch != self._connection_epoch
                    or self.ocs.declaration_seq != self._submitted_declaration_seq
                    or self.ocs.course_fingerprint != self._submitted_course_fingerprint):
                self.fail_scenario("negative declaration connection or Course changed; start a new session",
                                   declaration_seq=self._submitted_declaration_seq)
        if self.ocs._course_connection_epoch != self._connection_epoch:
            self._connection_epoch = self.ocs._course_connection_epoch
            self.latest_status = None
            self._status_received = None
        if not self.ocs.connected:
            self.stage("WAIT_ROBOCOMMAND")
            return
        if (self.ocs.course_store.get() is None
                or self.ocs._course_received_epoch != self.ocs._course_connection_epoch):
            self.stage("WAIT_COURSE")
            return
        if self.ocs.declaration_seq is None and self.geofence_options[0] in {"auto_course", "auto_course_union"}:
            if self._prepared_geofence is None:
                try:
                    self._prepared_geofence = self.prepare_declaration()
                except (ValueError, RuntimeError) as exc:
                    # A field session must fail closed: this mode has neither a
                    # verified UAV upload schema nor a verified FCU readback.
                    # Do not let an unavailable geometry engine turn into the
                    # legacy declaration path.
                    self._geofence_block_reason = f"geofence preparation blocked: {exc}"
                    self.stage("WAIT_UAV_VERIFICATION")
                    self.event("UAV_GEOFENCE_BLOCKED", topic=UAV_GEOFENCE_APPLY_TOPIC,
                               reason=self._geofence_block_reason)
                    return
                self.stage("GEOFENCE_PREPARED")
                self.event("GEOFENCE_PREPARED", course_id=self.ocs.course.course_id,
                           course_fingerprint=self.ocs.course_fingerprint,
                           maximum_height_hae_m=self._prepared_geofence.uav_geofence_max_altitude_hae_m,
                           vertices=len(self._prepared_geofence.uav_geofence))
            self.stage("WAIT_UAV_VERIFICATION")
            self.event("UAV_GEOFENCE_BLOCKED", topic=UAV_GEOFENCE_APPLY_TOPIC,
                       reason="UAV JSON upload and FCU readback protocol are not verified; declaration blocked")
            return
        if self.ocs.declaration_seq is None:
            self.stage("DECLARING")
            try:
                declaration = self.prepare_declaration()
                self.ocs._publish_run_declaration(declaration, preserve_report_sequences=True)
            except (ValueError, OSError, RuntimeError) as exc:
                self._publish_error = str(exc)
                raise
            self._submitted_declaration_seq = self.ocs.declaration_seq
            self._submitted_course_fingerprint = self.ocs.course_fingerprint
            self.event("DECLARATION_PUBLISHED", declaration_seq=self.ocs.declaration_seq,
                       course_id=self.ocs.course.course_id, pilot=declaration.uav_pilot_callsign,
                       maximum_height_hae_m=declaration.uav_geofence_max_altitude_hae_m,
                       uav_geofence=[{"latitude": point.latitude, "longitude": point.longitude}
                                     for point in declaration.uav_geofence],
                       outcome="acceptance_unknown", transport_ack="MQTT PUBACK only")
            self._next_heartbeat = self.clock()
        self.ocs.drain_internal_actions()
        if self.ocs.run_id != self._last_run_id:
            self._last_run_id = self.ocs.run_id
            if self.ocs.run_id is not None:
                self.event("RUN_START_RECORDED", run_id=self.ocs.run_id,
                           declaration_seq=self.ocs.declaration_seq, vehicle_commands_sent=0)
        if not self.telemetry_available or self.latest_status is None:
            self.stage("WAIT_UAV_TELEMETRY")
            return
        if self.clock() - self._status_received >= MAX_STATUS_AGE_S:
            self.stage("UAV_TELEMETRY_STALE")
            return
        source = self.latest_status["raw"]
        stamp = source.get("sent_at_unix_ms", source.get("timestamp_unix_ms"))
        if stamp is not None and abs(self.wall_clock() * 1000 - stamp) >= MAX_STATUS_AGE_S * 1000:
            self.stage("UAV_TELEMETRY_STALE")
            return
        self.stage("HEARTBEATING")
        if self.clock() < self._next_heartbeat:
            return
        heartbeat = build_ground_heartbeat(self.latest_status, registration=self.registration)
        # Schedule from publication start; do not add PUBACK latency to every period.
        self._next_heartbeat = self.clock() + HEARTBEAT_PERIOD_S
        try:
            self.ocs._publish_vehicle_body(self.vehicle_id, "heartbeat", heartbeat)
        except (OSError, RuntimeError) as exc:
            self._publish_error = str(exc)
            raise RuntimeError(f"heartbeat publication failed: {exc}") from exc
        self.heartbeat_count += 1
        self.event("HEARTBEAT_PUBLISHED", count=self.heartbeat_count,
                   report_seq=self.ocs._report_seq[self.vehicle_id], run_id=self.ocs.run_id,
                   state=self.latest_status["state"], flight_phase=self.latest_status["flight_phase"],
                   age_s=round(self.clock() - self._status_received, 3),
                   attitude_present=heartbeat.HasField("roll_deg") and heartbeat.HasField("pitch_deg"))


class Ros2StatusInput:
    """Read UAV JSON directly from DDS; no bridge and no command output.

    A dedicated executor keeps receiving while the main thread waits for an
    official MQTT PUBACK. Only pump() mutates the ground session, and each sample
    retains its callback receipt time so queued old data cannot look fresh.
    """

    def __init__(self, session):
        self.session = session
        self.events = queue.Queue(maxsize=256)
        self.geofence_events = queue.Queue(maxsize=32)
        self.overflow = False
        self.context = self.node = self.executor = self.subscription = self.geofence_subscription = None
        self.thread = None
        self._closing = False
        self._spin_error = None

    def _on_status(self, message):
        try:
            self.events.put_nowait((message.data, self.session.clock()))
        except queue.Full:
            self.overflow = True

    def _on_geofence_readback(self, message):
        """Receive untrusted raw FCU/UAV replies without treating them as proof."""
        try:
            self.geofence_events.put_nowait((message.data, self.session.clock()))
        except queue.Full:
            self.overflow = True

    def _spin(self):
        try:
            self.executor.spin()
            if not self._closing:
                self._spin_error = RuntimeError("ROS 2 executor stopped unexpectedly")
        except Exception as exc:
            if not self._closing:
                self._spin_error = exc

    def pump(self):
        if self._spin_error is not None:
            self.session.on_telemetry_unavailable()
            raise RuntimeError(f"ROS 2 status subscription failed: {self._spin_error}")
        if self.overflow:
            self.session.on_telemetry_unavailable()
            raise RuntimeError("UAV ROS 2 input queue overflow; inspect the status publisher")
        for _ in range(256):
            try:
                raw, received = self.events.get_nowait()
            except queue.Empty:
                break
            self.session.on_status(raw, received_monotonic=received)
        for _ in range(32):
            try:
                raw, received = self.geofence_events.get_nowait()
            except queue.Empty:
                break
            # Schema, coordinate order, altitude datum/units, and proof that
            # this is an FCU readback remain unverified.  Do not parse or use
            # it to unlock RunDeclaration.
            self.session.event("UAV_GEOFENCE_READBACK_UNVERIFIED",
                               topic=UAV_GEOFENCE_READBACK_TOPIC,
                               received_monotonic=received,
                               reason="UAV geofence JSON/readback protocol not yet verified")

    def connect(self):
        try:
            from rclpy.context import Context
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.node import Node
            from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
            from std_msgs.msg import String
        except ImportError as exc:
            raise RuntimeError(
                "Direct ROS 2 input requires rclpy and std_msgs. Source the ROS 2 "
                "environment and run with its Python interpreter; there is no MQTT bridge fallback."
            ) from exc
        self.context = Context()
        self.context.init(args=[])
        self.node = Node("robotx_uav_ground_validation", context=self.context)
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE)
        self.subscription = self.node.create_subscription(String, STATUS_TOPIC, self._on_status, qos)
        self.geofence_subscription = self.node.create_subscription(
            String, UAV_GEOFENCE_READBACK_TOPIC, self._on_geofence_readback, qos)
        self.executor = SingleThreadedExecutor(context=self.context)
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self._spin, name="ground-uav-ros2", daemon=True)
        self.thread.start()
        # Availability means the subscriber exists, not that a UAV was discovered.
        # Fresh valid messages are independently required before heartbeating.
        self.session.telemetry_available = True

    def close(self):
        self._closing = True
        self.session.on_telemetry_unavailable()
        if self.executor is not None:
            self.executor.shutdown(timeout_sec=2.0)
        if self.context is not None:
            self.context.try_shutdown()
        if self.thread is not None:
            self.thread.join(timeout=2.0)
        if self.node is not None:
            self.node.destroy_node()
        self.executor = self.context = self.node = self.subscription = self.geofence_subscription = self.thread = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--official-broker")
    parser.add_argument("--official-port", type=int)
    parser.add_argument("--team-id", help="RoboCommand team ID for this isolated test session")
    parser.add_argument("--pilot-callsign")
    parser.add_argument("--uav-registration")
    parser.add_argument("--vehicle-id", help="external RoboCommand UAV ID, e.g. UAV1; independent of the ROS source ID")
    parser.add_argument("--source-vehicle-id", help="exact vehicle_id received in the UAV ROS JSON")
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--test-max-altitude-hae", type=float,
                        help="over-height only: deliberate declaration ceiling, default 60 m HAE; actual telemetry is unchanged")
    parser.add_argument("--outside-offset-m", type=float,
                        help="outside-course only: move declaration fence north of Course and Transit, default 20 m (minimum 2)")
    parser.add_argument("--duration", type=float, default=0, help="0: continuous; seconds from program start otherwise")
    parser.add_argument("--log", type=Path, help="optional JSONL evidence log; never means MDF acceptance")
    args = parser.parse_args(argv)
    if args.test_max_altitude_hae is not None and args.scenario != "over-height":
        parser.error("--test-max-altitude-hae requires --scenario over-height")
    if args.outside_offset_m is not None and args.scenario != "outside-course":
        parser.error("--outside-offset-m requires --scenario outside-course")
    config = protocol.load_config(args.config)
    if args.team_id is not None:
        config["team_id"] = args.team_id
    for key, value in (("host", args.official_broker), ("port", args.official_port)):
        if value is not None:
            config.setdefault("robocommand", {})[key] = value
    if args.pilot_callsign is not None:
        config.setdefault("run_declaration", {})["uav_pilot_callsign"] = args.pilot_callsign
    for key, value in (("uav_registration", args.uav_registration), ("source_vehicle_id", args.source_vehicle_id),
                       ("vehicle_id", args.vehicle_id)):
        if value is not None:
            config["vehicles"]["uav"][key] = value
    if not math.isfinite(args.duration) or args.duration < 0:
        parser.error("duration must be nonnegative and finite")
    log = None
    session = None
    incoming = None
    try:
        session = GroundValidationSession(
            config, scenario=args.scenario,
            test_max_altitude_hae=60.0 if args.test_max_altitude_hae is None else args.test_max_altitude_hae,
            outside_offset_m=20.0 if args.outside_offset_m is None else args.outside_offset_m,
        )
        if args.log:
            args.log.parent.mkdir(parents=True, exist_ok=True)
            log = args.log.open("a", encoding="utf-8")
            def emit(event):
                line = json.dumps(event, ensure_ascii=False)
                print(line, flush=True)
                log.write(line + "\n")
                log.flush()
            session.emit = emit
        incoming = Ros2StatusInput(session)
        session.event("GROUND_SESSION_START", source_vehicle_id=session.source_vehicle_id,
                      source_transport="ros2", status_topic=STATUS_TOPIC,
                      current_task="TASK_NONE", vehicle_commands_enabled=False)
        incoming.connect()
        session.ocs.connect()
        end = time.monotonic() + args.duration if args.duration else None
        while end is None or time.monotonic() < end:
            incoming.pump()
            session.tick()
            time.sleep(0.02)
        session.event("GROUND_SESSION_END", heartbeats=session.heartbeat_count,
                      declaration_seq=session.ocs.declaration_seq, run_id=session.ocs.run_id,
                      outcome="run_start_observed" if session.ocs.run_id is not None else "acceptance_unknown",
                      rejection_evidence="inspect RoboCommand server refusal log" if session.scenario != "normal" else None,
                      mdf_acceptance="verify on MDF with assessor")
        return 0 if session.heartbeat_count else 2
    except KeyboardInterrupt:
        return 0
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f"[Ground] {exc}", file=sys.stderr)
        return 2
    finally:
        if incoming is not None:
            incoming.close()
        if session is not None:
            session.ocs.close()
        if log is not None:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
