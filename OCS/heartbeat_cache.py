"""Validation and caching for internal vehicle heartbeat envelopes.

This module deliberately has no MQTT, ROS 2, or protobuf dependency so it can
be exercised on Windows.  It never invents telemetry values: a cache entry is
either complete and valid, or unavailable for official reporting.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Mapping


VALID_STATES = {"AUTO", "MANUAL", "KILLED"}
VALID_TYPES = {"usv", "uav"}


class HeartbeatRejected(ValueError):
    """A vehicle heartbeat that must not affect the official report cache."""


@dataclass(frozen=True)
class CachedHeartbeat:
    vehicle_id: str
    payload: dict[str, Any]
    sent_at_unix_ms: int
    received_monotonic: float
    run_id: int | None


class HeartbeatCache:
    def __init__(self, *, max_age_seconds: float = 3.0, now_ms=None, monotonic=None) -> None:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self.max_age_ms = int(max_age_seconds * 1000)
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.monotonic = monotonic or time.monotonic
        self._entries: dict[str, CachedHeartbeat] = {}
        self._seen_ids: set[str] = set()

    def accept(self, envelope: Mapping[str, Any], *, active_run_id: int | None) -> CachedHeartbeat:
        if envelope.get("kind") != "heartbeat":
            raise HeartbeatRejected("not a heartbeat")
        vehicle_id = envelope.get("vehicle_id")
        if vehicle_id not in {"T-Wave", "T-Sky"}:
            raise HeartbeatRejected("unsupported vehicle_id")
        message_id = envelope.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise HeartbeatRejected("missing message_id")
        if message_id in self._seen_ids:
            raise HeartbeatRejected("duplicate heartbeat")
        run_id = envelope.get("run_id")
        if active_run_id is not None and run_id != active_run_id:
            raise HeartbeatRejected("heartbeat is not for the active run")
        sent_at = envelope.get("sent_at_unix_ms")
        if not isinstance(sent_at, int) or isinstance(sent_at, bool):
            raise HeartbeatRejected("invalid heartbeat timestamp")
        skew = self.now_ms() - sent_at
        if skew > self.max_age_ms:
            raise HeartbeatRejected("stale heartbeat")
        if skew < -self.max_age_ms:
            raise HeartbeatRejected("heartbeat timestamp is too far in the future")
        payload = dict(envelope.get("payload") or {})
        self._validate_payload(vehicle_id, payload)
        old = self._entries.get(vehicle_id)
        if old is not None and sent_at <= old.sent_at_unix_ms:
            raise HeartbeatRejected("out-of-order heartbeat")
        self._seen_ids.add(message_id)
        entry = CachedHeartbeat(vehicle_id, payload, sent_at, self.monotonic(), run_id)
        self._entries[vehicle_id] = entry
        return entry

    def valid(self, vehicle_id: str, *, active_run_id: int | None) -> CachedHeartbeat | None:
        entry = self._entries.get(vehicle_id)
        if entry is None or (active_run_id is not None and entry.run_id != active_run_id):
            return None
        if self.now_ms() - entry.sent_at_unix_ms > self.max_age_ms:
            return None
        return entry

    @staticmethod
    def _number(value: Any, label: str, low: float, high: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise HeartbeatRejected(f"{label} must be a finite number")
        value = float(value)
        if not low <= value <= high:
            raise HeartbeatRejected(f"{label} out of range")
        return value

    def _validate_payload(self, vehicle_id: str, payload: Mapping[str, Any]) -> None:
        mode = payload.get("source_mode")
        if mode not in {"simulation", "real"}:
            raise HeartbeatRejected("source_mode must be simulation or real")
        expected_type = "uav" if vehicle_id == "T-Sky" else "usv"
        if payload.get("vehicle_type") != expected_type:
            raise HeartbeatRejected("vehicle_type does not match vehicle_id")
        if payload.get("state") not in VALID_STATES:
            raise HeartbeatRejected("state must be an explicit AUTO/MANUAL/KILLED value")
        position = payload.get("position")
        if not isinstance(position, Mapping) or position.get("frame_id") != "wgs84":
            raise HeartbeatRejected("position must be explicitly WGS84")
        self._number(position.get("latitude_deg"), "latitude_deg", -90, 90)
        self._number(position.get("longitude_deg"), "longitude_deg", -180, 180)
        self._number(position.get("altitude_hae_m"), "altitude_hae_m", -2000, 100000)
        self._number(payload.get("speed_mps"), "speed_mps", 0, 200)
        self._number(payload.get("heading_deg"), "heading_deg", 0, 360)
        self._number(payload.get("roll_deg"), "roll_deg", -180, 180)
        self._number(payload.get("pitch_deg"), "pitch_deg", -90, 90)
        health = payload.get("health")
        if not isinstance(health, Mapping) or health.get("fcu_connected") is not True:
            raise HeartbeatRejected("FCU connection is absent or false")
        if mode == "simulation" and health.get("simulator") is not True:
            raise HeartbeatRejected("simulation heartbeat must identify itself")
        if mode == "real" and health.get("simulator"):
            raise HeartbeatRejected("real heartbeat cannot carry simulator data")
        if expected_type == "uav" and payload.get("flight_phase") not in {"grounded", "airborne"}:
            raise HeartbeatRejected("UAV heartbeat requires an explicit flight_phase")
        registration = payload.get("uav_registration")
        if registration is not None and not isinstance(registration, str):
            raise HeartbeatRejected("uav_registration must be a string when supplied")
        if expected_type != "uav" and registration:
            raise HeartbeatRejected("uav_registration is only valid for a UAV heartbeat")
