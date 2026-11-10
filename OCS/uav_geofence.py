"""Frozen wire-format helpers for the OCS -> UAV-Orin horizontal geofence.

The confirmed ROS 2 interface is ``std_msgs/msg/String`` on
``/tongji_mrl/tsky/uav_geofense_sub``. Its ``data`` contains only a JSON
array of ``[latitude, longitude]`` pairs. It carries no height limit.
"""
from __future__ import annotations

import json
import math
from typing import Iterable, Sequence


UAV_GEOFENCE_APPLY_TOPIC = "/tongji_mrl/tsky/uav_geofense_sub"
UAV_GEOFENCE_READBACK_TOPIC = "/tongji_mrl/tsky/uav_geofense_pub"


def serialize_geofence(points: Iterable[Sequence[float]]) -> str:
    """Return the exact String.data JSON used by the confirmed Orin interface."""
    normalized: list[list[float]] = []
    for index, point in enumerate(points):
        if len(point) != 2:
            raise ValueError(f"geofence point {index} must contain [latitude, longitude]")
        latitude, longitude = point
        if (isinstance(latitude, bool) or isinstance(longitude, bool)
                or not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float))
                or not math.isfinite(latitude) or not math.isfinite(longitude)
                or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
            raise ValueError(f"geofence point {index} has invalid [latitude, longitude]")
        normalized.append([float(latitude), float(longitude)])
    if len(normalized) < 4:
        raise ValueError("geofence requires at least three vertices plus a closing point")
    if normalized[0] != normalized[-1]:
        raise ValueError("geofence must be closed (first point equals last point)")
    return json.dumps(normalized, separators=(",", ":"))


def parse_string_readback(raw: str) -> list[tuple[float, float]]:
    """Parse a String readback only when it is a bare coordinate JSON array.

    This is intentionally not a claim that every publisher on the readback
    topic has this format. The ROS graph type must first be confirmed as
    ``std_msgs/msg/String`` by the gateway.
    """
    try:
        decoded = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"readback is not JSON: {exc}") from exc
    if not isinstance(decoded, list):
        raise ValueError("readback JSON must be a coordinate array")
    # Reuse full coordinate/closure validation, then retain numeric pairs.
    serialize_geofence(decoded)
    return [(float(point[0]), float(point[1])) for point in decoded]


def parse_applied_geofence_readback(raw: str) -> tuple[list[tuple[float, float]], float]:
    """Parse the frozen FCU-applied readback supplied by the UAV team.

    ``max_altitude_m`` is an HAE value by the confirmed interface contract.
    The gateway additionally binds this readback to the currently published
    candidate and rejects it after the readback deadline.
    """
    try:
        decoded = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"readback is not JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError("readback JSON must be an object")
    if set(decoded) != {"points", "max_altitude_m"}:
        raise ValueError("readback must contain only points and max_altitude_m")
    points = parse_string_readback(json.dumps(decoded["points"], separators=(",", ":")))
    altitude = decoded["max_altitude_m"]
    if isinstance(altitude, bool) or not isinstance(altitude, (int, float)) or not math.isfinite(altitude):
        raise ValueError("max_altitude_m must be a finite number")
    if not 0 < float(altitude) <= 100000:
        raise ValueError("max_altitude_m must be greater than 0 and at most 100000")
    return points, float(altitude)


def compare_geofence(expected: Iterable[Sequence[float]], actual: Iterable[Sequence[float]], *,
                      tolerance_deg: float = 1e-6) -> None:
    """Require same ordered, closed vertices within a conservative tolerance."""
    if not isinstance(tolerance_deg, (int, float)) or tolerance_deg <= 0:
        raise ValueError("tolerance_deg must be positive")
    expected_points = parse_string_readback(serialize_geofence(expected))
    actual_points = parse_string_readback(serialize_geofence(actual))
    if len(expected_points) != len(actual_points):
        raise ValueError(f"vertex count differs: expected {len(expected_points)}, got {len(actual_points)}")
    for index, ((expected_lat, expected_lon), (actual_lat, actual_lon)) in enumerate(zip(expected_points, actual_points)):
        if abs(expected_lat - actual_lat) > tolerance_deg or abs(expected_lon - actual_lon) > tolerance_deg:
            raise ValueError(f"vertex {index} differs beyond {tolerance_deg:g} degrees")
