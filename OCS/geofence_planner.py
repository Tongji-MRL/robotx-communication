"""Conservative RxCourse -> candidate UAV geofence calculation (no flight commands).

The generated polygon is an inscribed regular ring inside RxCourse.corners.
It deliberately does NOT attempt to automatically join the Course and optional
UAV transit polygons: the union can be concave, disconnected, or have holes.
An operator must verify the candidate covers the approved takeoff/landing and
flight area and matches the actual FCU/PX4 geofence before declaring a real run.
"""
from __future__ import annotations

import math
from typing import Iterable

try:
    from .course_config import validate_course_fields, validate_geofence_within_course
except ImportError:  # running from the OCS directory
    from course_config import validate_course_fields, validate_geofence_within_course

EARTH_RADIUS_M = 6371000.0
# The sample RoboCommand RC-test server uses 50m HAE. Never allow a local
# parameter to silently relax this official-sample maximum.
OFFICIAL_SAMPLE_MAX_ALTITUDE_HAE_M = 50.0


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def validate_geofence_altitude(requested_hae_m: object, *, limit_hae_m: object = 50.0) -> float:
    """Reject invalid request heights locally; do not transmit rejected tests to RBC.

    ``limit_hae_m`` is the operator-configured maximum (may be made STRICTER
    than the example server's limit). It is never an authorization to exceed
    the actual published competition/airspace ceiling, which must be verified.
    """
    requested = _finite_number(requested_hae_m, "uav_geofence_max_altitude_hae_m")
    limit = _finite_number(limit_hae_m, "uav_geofence_altitude_limit_hae_m")
    if not 0 < limit <= OFFICIAL_SAMPLE_MAX_ALTITUDE_HAE_M:
        raise ValueError("uav_geofence_altitude_limit_hae_m must be in (0, 50] for this RC-test schema")
    if not 0 < requested <= limit:
        raise ValueError(
            f"uav_geofence_max_altitude_hae_m={requested:g} exceeds the configured height gate "
            f"(0, {limit:g}] m HAE"
        )
    return requested


def calculate_geofence_from_course(
    corners: Iterable[tuple[float, float]], *,
    margin_m: float = 2.0, vertex_count: int = 12,
) -> list[tuple[float, float]]:
    """Build a candidate closed geofence guaranteed to lie within Course corners.

    Find an interior center with good clearance, then inscribe a regular polygon
    inside a disk that clears the course perimeter by at least ``margin_m``.
    This is intentionally conservative; it can be too small for operational use.
    Never automatically send to PX4 or assume this is the configured FCU fence.
    """
    margin = _finite_number(margin_m, "uav_geofence_margin_m")
    if margin < 0 or margin > 1000:
        raise ValueError("uav_geofence_margin_m must be between 0 and 1000")
    if isinstance(vertex_count, bool) or not isinstance(vertex_count, int) or not 3 <= vertex_count <= 64:
        raise ValueError("vertex_count must be an integer between 3 and 64")
    _, _, ring = validate_course_fields("RxCourse", 1, corners)
    latitudes = [p[0] for p in ring[:-1]]
    longitudes = [p[1] for p in ring[:-1]]
    if max(longitudes) - min(longitudes) > 1 or max(latitudes) - min(latitudes) > 1:
        raise ValueError("automatic local-meter geofence supports only compact courses (<1 degree extent)")
    lat0 = sum(latitudes) / len(latitudes)
    lon0 = sum(longitudes) / len(longitudes)
    cos_lat = math.cos(math.radians(lat0))
    if abs(cos_lat) < 1e-4:
        raise ValueError("automatic local-meter projection is not supported close to the poles")
    lon_factor = EARTH_RADIUS_M * math.pi / 180 * cos_lat
    lat_factor = EARTH_RADIUS_M * math.pi / 180
    xy = [((lon - lon0) * lon_factor, (lat - lat0) * lat_factor) for lat, lon in ring]
    segments = list(zip(xy, xy[1:]))
    xs, ys = [p[0] for p in xy[:-1]], [p[1] for p in xy[:-1]]

    def inside(pt: tuple[float, float]) -> bool:
        x, y = pt
        parity = False
        for (ax, ay), (bx, by) in segments:
            if ((ay > y) != (by > y)) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                parity = not parity
        return parity

    def dist_segment(pt: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        dx, dy = b[0] - a[0], b[1] - a[1]
        len2 = dx * dx + dy * dy
        t = 0.0 if len2 == 0 else max(0.0, min(1.0, ((pt[0]-a[0])*dx+(pt[1]-a[1])*dy)/len2))
        return math.hypot(pt[0] - (a[0]+t*dx), pt[1] - (a[1]+t*dy))

    def clearance(pt: tuple[float, float]) -> float:
        if not inside(pt):
            return -1.0
        return min(dist_segment(pt, a, b) for a, b in segments)

    # Fixed grid + local refinement searches for an interior center without
    # third-party geometry packages. A concave course is supported; disconnected
    # or very narrow areas fail closed when a usable safe disk cannot be found.
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    best = None
    radius = -1.0
    for iy in range(31):
        y = miny + (maxy-miny) * (iy + 0.5) / 31
        for ix in range(31):
            x = minx + (maxx-minx) * (ix + 0.5) / 31
            r = clearance((x, y))
            if r > radius:
                best, radius = (x, y), r
    if best is None or radius <= margin:
        raise ValueError("Course is too narrow to generate an automatic geofence with the chosen margin")
    step = max(maxx-minx, maxy-miny) / 31
    for _ in range(8):
        for dx in (-step, 0.0, step):
            for dy in (-step, 0.0, step):
                candidate = (best[0]+dx, best[1]+dy)
                r = clearance(candidate)
                if r > radius:
                    best, radius = candidate, r
        step *= 0.5
    safe_radius = (radius - margin) * 0.95
    if safe_radius <= 0.1:
        raise ValueError("No practical automatic geofence area remains after applying the safety margin")
    vertices = []
    for k in range(vertex_count):
        angle = 2 * math.pi * k / vertex_count
        x = best[0] + safe_radius * math.cos(angle)
        y = best[1] + safe_radius * math.sin(angle)
        vertices.append((lat0 + y / lat_factor, lon0 + x / lon_factor))
    vertices.append(vertices[0])
    # Preserve correctness even if floating point / projection error appears.
    validate_geofence_within_course(ring, vertices)
    return vertices
