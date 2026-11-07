"""Read-only evaluation of UAV telemetry against an observed declaration."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

EARTH_RADIUS_M = 6_371_000.0


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return float(value)


def _polygon(fence: Any) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    if not isinstance(fence, list) or not 4 <= len(fence) <= 1000:
        raise ValueError("geofence must contain a closed ring with at least three vertices")
    lat_lon: list[tuple[float, float]] = []
    for point in fence:
        if not isinstance(point, Mapping):
            raise ValueError("geofence point must be an object")
        latitude, longitude = _number(point.get("latitude"), "latitude"), _number(point.get("longitude"), "longitude")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("geofence coordinate out of range")
        lat_lon.append((latitude, longitude))
    if lat_lon[0] != lat_lon[-1] or len(set(lat_lon[:-1])) < 3:
        raise ValueError("geofence must be closed with three distinct vertices")
    lat0 = sum(point[0] for point in lat_lon[:-1]) / (len(lat_lon) - 1)
    lon0 = sum(point[1] for point in lat_lon[:-1]) / (len(lat_lon) - 1)
    if max(point[1] for point in lat_lon) - min(point[1] for point in lat_lon) >= 180:
        raise ValueError("antimeridian-spanning geofence is unsupported")
    cos_lat0 = math.cos(math.radians(lat0))
    if abs(cos_lat0) < 1e-4:
        raise ValueError("near-polar geofence is unsupported")
    ring = [((longitude - lon0) * math.pi / 180 * EARTH_RADIUS_M * cos_lat0,
             (latitude - lat0) * math.pi / 180 * EARTH_RADIUS_M)
            for latitude, longitude in lat_lon]
    area = abs(sum(ax * by - ay * bx for (ax, ay), (bx, by) in zip(ring, ring[1:]))) / 2
    if area < 0.01:
        raise ValueError("geofence has negligible area")
    return lat_lon, ring


def _inside(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    x, y = point
    result = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            result = not result
    return result


def _distance_to_ring(point: tuple[float, float], ring: list[tuple[float, float]]) -> float:
    x, y = point
    minimum = math.inf
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        dx, dy = bx - ax, by - ay
        factor = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        minimum = min(minimum, math.hypot(x - (ax + factor * dx), y - (ay + factor * dy)))
    return minimum


def evaluate_uav_fence(uav_status: Mapping[str, Any] | None, age_s: float | None,
                       declaration: Mapping[str, Any] | None, *, stale_after_s: float = 3.0,
                       near_boundary_m: float = 5.0, near_ceiling_m: float = 3.0) -> dict[str, Any]:
    """Return display-only fence status; UNKNOWN and STALE never mean safe."""
    result: dict[str, Any] = {
        "level": "UNKNOWN", "message": "No comparable observed declaration and telemetry.", "reasons": [],
        "horizontal": "UNKNOWN", "vertical": "UNKNOWN", "horizontal_clearance_m": None,
        "height_clearance_m": None, "current_height_hae_m": None, "max_height_hae_m": None,
        "geofence": [], "source": "NONE", "declaration_seq": None, "telemetry_age_s": age_s,
        "note": "Observed RunDeclaration is not RBC acceptance or flight-controller fence activation; height is HAE, not AGL.",
    }
    if declaration is None:
        result["message"] = "No valid observed T-Sky RunDeclaration; safety is unknown."
        return result
    result.update(source=str(declaration.get("source", "UNKNOWN")), declaration_seq=declaration.get("seq"))
    try:
        lat_lon, ring = _polygon(declaration.get("uav_geofence"))
        ceiling = _number(declaration.get("uav_geofence_max_altitude_hae_m"), "maximum HAE")
        if not 0 < ceiling <= 100000:
            raise ValueError("maximum HAE out of range")
    except (TypeError, ValueError) as exc:
        result["message"] = f"Observed declaration geofence is invalid: {exc}"
        return result
    result["geofence"] = [{"latitude": lat, "longitude": lon} for lat, lon in lat_lon]
    result["max_height_hae_m"] = ceiling
    if uav_status is None:
        result["message"] = "Observed declaration is available, but UAV telemetry is unavailable."
        return result
    if age_s is None or not math.isfinite(age_s) or age_s > stale_after_s:
        result.update(level="STALE", message="UAV telemetry is stale; safety cannot be determined.")
        result["reasons"] = [result["message"]]
        return result
    try:
        position = uav_status["position"]
        latitude = _number(position["latitude_deg"], "UAV latitude")
        longitude = _number(position["longitude_deg"], "UAV longitude")
        altitude = _number(position["altitude_hae_m"], "UAV altitude HAE")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("UAV coordinates out of range")
    except (KeyError, TypeError, ValueError) as exc:
        result["message"] = f"UAV position is unavailable: {exc}"
        return result
    lat0 = sum(lat for lat, _ in lat_lon[:-1]) / (len(lat_lon) - 1)
    lon0 = sum(lon for _, lon in lat_lon[:-1]) / (len(lat_lon) - 1)
    point = ((longitude - lon0) * math.pi / 180 * EARTH_RADIUS_M * math.cos(math.radians(lat0)),
             (latitude - lat0) * math.pi / 180 * EARTH_RADIUS_M)
    distance = _distance_to_ring(point, ring)
    within = distance < 0.05 or _inside(point, ring)
    horizontal = distance if within else -distance
    height = ceiling - altitude
    result.update(current_height_hae_m=round(altitude, 2), horizontal_clearance_m=round(horizontal, 2),
                  height_clearance_m=round(height, 2),
                  horizontal="OUTSIDE" if not within else "NEAR" if horizontal <= near_boundary_m else "INSIDE",
                  vertical="OVER" if height < 0 else "NEAR" if height <= near_ceiling_m else "BELOW")
    reasons = ([] if within else [f"Position is outside the observed fence by {distance:.1f} m"])
    if height < 0:
        reasons.append(f"HAE altitude exceeds the declared limit by {-height:.1f} m")
    if reasons:
        result.update(level="ALARM", message=" / ".join(reasons), reasons=reasons)
        return result
    if horizontal <= near_boundary_m:
        reasons.append(f"Fence clearance is {horizontal:.1f} m")
    if height <= near_ceiling_m:
        reasons.append(f"HAE clearance is {height:.1f} m")
    result.update(level="CAUTION" if reasons else "INSIDE",
                  message=" / ".join(reasons) if reasons else "Position and HAE altitude are within the observed declaration.",
                  reasons=reasons)
    return result
