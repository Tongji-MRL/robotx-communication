"""Translate the UAV semantic map into the USV local NED frame.

The UAV map is expressed in the UAV launch-point NED frame.  The document
``UAV建立的地图如何被USV所用.pdf`` specifies that the UAV and USV NED axes
are aligned, so the conversion is a translation only::

    usv_map_position_ned = uav_map_position_ned + offset_to_add_m

The offset is the UAV mapping-origin GPS position expressed in the USV
origin's NED frame.  GPS/RTK values must use WGS84 ellipsoid height in metres.
This module deliberately has no ROS or MQTT dependency; an Orin adapter can
feed it the normalized values received by the OCS.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


# WGS84 ellipsoid constants.
WGS84_A_M = 6378137.0
WGS84_E2 = 6.6943799901413165e-3

NedVector = tuple[float, float, float]


@dataclass(frozen=True)
class GpsOrigin:
    """A GPS origin used for the local NED conversion."""

    latitude_deg: float
    longitude_deg: float
    altitude_ellipsoid_m: float

    def __post_init__(self) -> None:
        values = (self.latitude_deg, self.longitude_deg, self.altitude_ellipsoid_m)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("GPS values must be finite numbers")
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError("latitude_deg must be in [-90, 90]")
        if not -180.0 <= self.longitude_deg <= 180.0:
            raise ValueError("longitude_deg must be in [-180, 180]")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GpsOrigin":
        """Build an origin from the canonical normalized payload fields."""

        required = ("latitude_deg", "longitude_deg", "altitude_ellipsoid_m")
        missing = [name for name in required if name not in value]
        if missing:
            raise ValueError(f"missing GPS fields: {', '.join(missing)}")
        try:
            return cls(*(float(value[name]) for name in required))
        except (TypeError, ValueError) as exc:
            raise ValueError("GPS fields must be numeric") from exc


def geodetic_to_ecef(origin: GpsOrigin) -> tuple[float, float, float]:
    """Convert WGS84 latitude, longitude and ellipsoid height to ECEF metres."""

    lat = math.radians(origin.latitude_deg)
    lon = math.radians(origin.longitude_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    radius = WGS84_A_M / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (radius + origin.altitude_ellipsoid_m) * cos_lat * math.cos(lon)
    y = (radius + origin.altitude_ellipsoid_m) * cos_lat * math.sin(lon)
    z = (radius * (1.0 - WGS84_E2) + origin.altitude_ellipsoid_m) * sin_lat
    return x, y, z


def uav_origin_in_usv_ned(uav_origin: GpsOrigin, usv_origin: GpsOrigin) -> NedVector:
    """Return the ``[north, east, down]`` offset to add to UAV map points.

    The ECEF difference is rotated at the USV origin.  This follows the PDF's
    convention: both vehicles use the same north/east/down directions.  If the
    two local frames have an independent yaw, a separate rotation calibration
    is required; GPS translation alone cannot infer that yaw.
    """

    uav_ecef = geodetic_to_ecef(uav_origin)
    usv_ecef = geodetic_to_ecef(usv_origin)
    dx, dy, dz = (uav_ecef[i] - usv_ecef[i] for i in range(3))

    lat = math.radians(usv_origin.latitude_deg)
    lon = math.radians(usv_origin.longitude_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    north = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    east = -sin_lon * dx + cos_lon * dy
    down = -cos_lat * cos_lon * dx - cos_lat * sin_lon * dy - sin_lat * dz
    return north, east, down


def add_ned_offset(position: Sequence[float], offset: NedVector) -> list[float]:
    """Add a NED offset to a three-element position."""

    if len(position) != 3:
        raise ValueError("NED_position must contain exactly three numbers")
    try:
        values = [float(item) for item in position]
    except (TypeError, ValueError) as exc:
        raise ValueError("NED_position values must be numeric") from exc
    if not all(math.isfinite(value) for value in values):
        raise ValueError("NED_position values must be finite numbers")
    return [values[index] + offset[index] for index in range(3)]


def transform_semantic_map(
    semantic_map: Mapping[str, Any] | str | bytes,
    uav_origin: GpsOrigin,
    usv_origin: GpsOrigin,
) -> dict[str, Any]:
    """Return a copy of a semantic map translated into the USV NED frame.

    The expected map shape is the YAML/JSON structure shown in the PDF, with
    an ``objects`` list and each object's ``NED_position``.  Unknown fields are
    preserved.  A malformed or position-less object is rejected rather than
    silently leaving mixed coordinate frames in the result.
    """

    if isinstance(semantic_map, bytes):
        try:
            semantic_map = semantic_map.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("semantic map must be UTF-8 JSON") from exc
    if isinstance(semantic_map, str):
        try:
            value = json.loads(semantic_map)
        except json.JSONDecodeError as exc:
            raise ValueError(f"semantic map is not valid JSON: {exc}") from exc
    else:
        value = semantic_map
    if not isinstance(value, Mapping):
        raise ValueError("semantic map must be a JSON object")

    objects = value.get("objects")
    if not isinstance(objects, list):
        raise ValueError("semantic map must contain an objects list")

    offset = uav_origin_in_usv_ned(uav_origin, usv_origin)
    result = copy.deepcopy(dict(value))
    transformed_objects: list[dict[str, Any]] = []
    for index, item in enumerate(objects):
        if not isinstance(item, Mapping):
            raise ValueError(f"objects[{index}] must be a JSON object")
        if "NED_position" not in item:
            raise ValueError(f"objects[{index}] is missing NED_position")
        transformed = dict(item)
        transformed["NED_position"] = add_ned_offset(item["NED_position"], offset)
        transformed_objects.append(transformed)
    result["objects"] = transformed_objects
    result["source_coordinate_frame"] = "uav_ned"
    result["coordinate_frame"] = "usv_ned"
    result["offset_to_add_m"] = {
        "north": offset[0],
        "east": offset[1],
        "down": offset[2],
    }
    return result


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Calculate the NED offset from a UAV map origin to a USV origin"
    )
    for prefix in ("uav", "usv"):
        parser.add_argument(f"--{prefix}-lat", type=float, required=True)
        parser.add_argument(f"--{prefix}-lon", type=float, required=True)
        parser.add_argument(f"--{prefix}-alt", type=float, required=True,
                            help="WGS84 ellipsoid height in metres")
    args = parser.parse_args()
    uav = GpsOrigin(args.uav_lat, args.uav_lon, args.uav_alt)
    usv = GpsOrigin(args.usv_lat, args.usv_lon, args.usv_alt)
    north, east, down = uav_origin_in_usv_ned(uav, usv)
    print(json.dumps({
        "uav_ned_origin_gps": vars(uav),
        "usv_ned_origin_gps": vars(usv),
        "offset_to_add_m": {"north": north, "east": east, "down": down},
        "formula": "usv_map_position_ned = uav_map_position_ned + offset_to_add_m",
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
