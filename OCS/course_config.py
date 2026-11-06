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


def _point_on_segment(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> bool:
    return abs(_orientation(start, end, point)) <= 1e-12 and _on_segment(start, end, point)


def _point_in_or_on_polygon(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    ring = polygon[:-1]
    for index, start in enumerate(ring):
        if _point_on_segment(point, start, ring[(index + 1) % len(ring)]):
            return True
    inside = False
    latitude, longitude = point
    for index, start in enumerate(ring):
        end = ring[(index + 1) % len(ring)]
        if (start[0] > latitude) != (end[0] > latitude):
            intersection_longitude = (end[1] - start[1]) * (latitude - start[0]) / (end[0] - start[0]) + start[1]
            if longitude < intersection_longitude:
                inside = not inside
    return inside


def _edge_breakpoints(
    start: tuple[float, float], end: tuple[float, float], boundary: tuple[tuple[float, float], ...]
) -> list[float]:
    """Return edge parameters at boundary intersections without changing either ring."""
    delta_lat, delta_lon = end[0] - start[0], end[1] - start[1]
    length_sq = delta_lat * delta_lat + delta_lon * delta_lon
    values = [0.0, 1.0]
    for index, boundary_start in enumerate(boundary[:-1]):
        boundary_end = boundary[index + 1]
        if not _segments_intersect(start, end, boundary_start, boundary_end):
            continue
        denominator = delta_lat * (boundary_end[1] - boundary_start[1]) - delta_lon * (boundary_end[0] - boundary_start[0])
        if abs(denominator) > 1e-12:
            offset_lat, offset_lon = boundary_start[0] - start[0], boundary_start[1] - start[1]
            values.append((offset_lat * (boundary_end[1] - boundary_start[1]) - offset_lon * (boundary_end[0] - boundary_start[0])) / denominator)
        else:
            for point in (boundary_start, boundary_end):
                if _point_on_segment(point, start, end):
                    values.append(((point[0] - start[0]) * delta_lat + (point[1] - start[1]) * delta_lon) / length_sq)
    return sorted({max(0.0, min(1.0, value)) for value in values})


def validate_geofence_within_course(
    course_corners: Iterable[Any], uav_geofence: Iterable[Any],
    uav_transit_area: Iterable[Any] = (),
) -> tuple[tuple[float, float], ...]:
    """Conservatively validate a fence relative to Course OR Transit Area.

    Both received polygons are preserved verbatim. All fence vertices and
    edges must lie in their union. The sparse interior sampling is an extra
    safety check, NOT a substitute for certified FCU geofence verification.
    """
    _, _, course = validate_course_fields("course", 1, course_corners)
    _, _, fence = validate_course_fields("uav_geofence", 1, uav_geofence)
    transit_values = tuple(uav_transit_area)
    transit = validate_course_fields("uav_transit_area", 1, transit_values)[2] if transit_values else None
    regions = (course, transit) if transit is not None else (course,)
    all_longitudes = [p[1] for region in regions for p in region[:-1]] + [p[1] for p in fence[:-1]]
    if max(all_longitudes) - min(all_longitudes) > 180:
        raise ValueError("cannot validate geofence geometry across the antimeridian")

    def in_allowed(point):
        return any(_point_in_or_on_polygon(point, region) for region in regions)

    for index, point in enumerate(fence[:-1]):
        if not in_allowed(point):
            raise ValueError(f"uav_geofence vertex {index} is outside Course and UAV transit area")
    for index, start in enumerate(fence[:-1]):
        end = fence[index + 1]
        split = {0.0, 1.0}
        for region in regions:
            split.update(_edge_breakpoints(start, end, region))
        for left, right in zip(sorted(split), sorted(split)[1:]):
            midpoint = (start[0] + (end[0] - start[0]) * (left + right) / 2,
                        start[1] + (end[1] - start[1]) * (left + right) / 2)
            if not in_allowed(midpoint):
                raise ValueError(f"uav_geofence edge {index} leaves Course and UAV transit area")
    # Reject obvious interiors enclosing a disallowed gap or a hole in a
    # compound allowed region; flight safety still requires FCU confirmation.
    if transit is not None:
        latitudes = [p[0] for p in fence[:-1]]
        longitudes = [p[1] for p in fence[:-1]]
        for iy in range(21):
            lat = min(latitudes) + (max(latitudes) - min(latitudes)) * (iy + .5) / 21
            for ix in range(21):
                lon = min(longitudes) + (max(longitudes) - min(longitudes)) * (ix + .5) / 21
                pt = (lat, lon)
                if _point_in_or_on_polygon(pt, fence) and not in_allowed(pt):
                    raise ValueError("uav_geofence interior includes an area outside Course and UAV transit area")
    return fence


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


def _optional_polygon(points: Iterable[Any]) -> tuple[tuple[float, float], ...]:
    values = tuple(points)
    if not values:
        return ()
    # Transit area is an optional, independent closed polygon.  It never
    # replaces the official Course boundary.
    _, _, normalized = validate_course_fields("uav_transit_area", 1, values)
    return normalized


def make_payload(*, course_id: Any, pinger_freq_hz: Any, corners: Iterable[Any],
                 uav_transit_area: Iterable[Any] = (), source_sent_at: datetime | None,
                 timestamp: datetime | None = None) -> dict[str, Any]:
    course_id, frequency, points = validate_course_fields(course_id, pinger_freq_hz, corners)
    transit_area = _optional_polygon(uav_transit_area)
    return {
        "schema_version": SCHEMA_VERSION,
        "course_id": course_id,
        "pinger_freq_hz": frequency,
        "corners": [{"latitude": lat, "longitude": lng} for lat, lng in points],
        "uav_transit_area": [{"latitude": lat, "longitude": lng} for lat, lng in transit_area],
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
    return make_payload(course_id=payload.get("course_id"), pinger_freq_hz=payload.get("pinger_freq_hz"), corners=payload.get("corners", ()), uav_transit_area=payload.get("uav_transit_area", ()), source_sent_at=datetime.fromisoformat(source.replace("Z", "+00:00")) if source else None, timestamp=datetime.fromisoformat(timestamp.replace("Z", "+00:00")))


def fingerprint(payload: Mapping[str, Any]) -> str:
    normalized = validate_payload(payload)
    normalized.pop("timestamp")  # OCS retransmissions must remain idempotent.
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
