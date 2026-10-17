"""Frozen, protobuf-free Course configuration contract helpers.

This module deliberately has no MQTT or ROS dependency so the same validation
is used by the OCS and the Ubuntu bridge and can be tested on Windows.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "twave-course-config-v1"


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("course timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[1] - a[1]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[1] - a[1])


def _on_segment(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]) -> bool:
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _segments_intersect(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    ab_c, ab_d = _orientation(a, b, c), _orientation(a, b, d)
    cd_a, cd_b = _orientation(c, d, a), _orientation(c, d, b)
    if ab_c == 0 and _on_segment(a, b, c): return True
    if ab_d == 0 and _on_segment(a, b, d): return True
    if cd_a == 0 and _on_segment(c, d, a): return True
    if cd_b == 0 and _on_segment(c, d, b): return True
    return (ab_c > 0) != (ab_d > 0) and (cd_a > 0) != (cd_b > 0)


def validate_course_fields(course_id: Any, pinger_freq_hz: Any, corners: Iterable[Any]) -> tuple[str, int, tuple[tuple[float, float], ...]]:
    if not isinstance(course_id, str) or not course_id.strip() or len(course_id) > 128:
        raise ValueError("course_id must be a non-empty string up to 128 characters")
    if isinstance(pinger_freq_hz, bool) or not isinstance(pinger_freq_hz, int) or not 1 <= pinger_freq_hz <= 1_000_000:
        raise ValueError("pinger_freq_hz must be an integer from 1 to 1000000")
    points: list[tuple[float, float]] = []
    for index, corner in enumerate(corners):
        if isinstance(corner, Mapping):
            latitude, longitude = corner.get("latitude"), corner.get("longitude")
        else:
            try:
                latitude, longitude = corner
            except (TypeError, ValueError) as exc:
                raise ValueError(f"corner {index} must contain latitude and longitude") from exc
        latitude, longitude = _number(latitude, f"corner {index} latitude"), _number(longitude, f"corner {index} longitude")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError(f"corner {index} latitude/longitude out of range")
        points.append((latitude, longitude))
    if len(points) < 4 or points[0] != points[-1]:
        raise ValueError("course polygon must have at least three vertices and be closed")
    ring = points[:-1]
    if len(set(ring)) < 3:
        raise ValueError("course polygon must contain three distinct vertices")
    area2 = sum(ring[i][1] * ring[(i + 1) % len(ring)][0] - ring[(i + 1) % len(ring)][1] * ring[i][0] for i in range(len(ring)))
    if abs(area2) < 1e-12:
        raise ValueError("course polygon has zero area")
    for i in range(len(ring)):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        if a == b:
            raise ValueError("course polygon cannot contain zero-length edges")
        for j in range(i + 1, len(ring)):
            if j in (i, (i - 1) % len(ring), (i + 1) % len(ring)):
                continue
            c, d = ring[j], ring[(j + 1) % len(ring)]
            if _segments_intersect(a, b, c, d):
                raise ValueError("course polygon must not self-intersect")
    return course_id.strip(), pinger_freq_hz, tuple(points)


def make_payload(*, course_id: Any, pinger_freq_hz: Any, corners: Iterable[Any], source_sent_at: datetime | None, timestamp: datetime | None = None) -> dict[str, Any]:
    course_id, frequency, points = validate_course_fields(course_id, pinger_freq_hz, corners)
    return {
        "schema_version": SCHEMA_VERSION,
        "course_id": course_id,
        "pinger_freq_hz": frequency,
        "corners": [{"latitude": lat, "longitude": lng} for lat, lng in points],
        "source_sent_at": _utc_iso(source_sent_at),
        "timestamp": _utc_iso(timestamp or datetime.now(timezone.utc)),
    }


def validate_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    source = payload.get("source_sent_at")
    if source is not None:
        if not isinstance(source, str):
            raise ValueError("source_sent_at must be an RFC3339 timestamp or null")
        try: datetime.fromisoformat(source.replace("Z", "+00:00"))
        except ValueError as exc: raise ValueError("source_sent_at must be RFC3339") from exc
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str): raise ValueError("timestamp must be an RFC3339 timestamp")
    try: datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc: raise ValueError("timestamp must be RFC3339") from exc
    return make_payload(course_id=payload.get("course_id"), pinger_freq_hz=payload.get("pinger_freq_hz"), corners=payload.get("corners", ()), source_sent_at=datetime.fromisoformat(source.replace("Z", "+00:00")) if source else None, timestamp=datetime.fromisoformat(timestamp.replace("Z", "+00:00")))


def fingerprint(payload: Mapping[str, Any]) -> str:
    normalized = validate_payload(payload)
    normalized.pop("timestamp")  # OCS retransmissions must remain idempotent.
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
