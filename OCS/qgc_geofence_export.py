#!/usr/bin/env python3
"""将已验证的 Course/Transit 并集内缩围栏导出为 QGC Polygon Fence `.plan`。

这是离线文件导出工具：不连接 QGC、PX4、ROS2 或 MQTT，不上传围栏，也不生成飞行
任务。QGC 的 Home Position 必须由操作员通过命令行明确提供，绝不从围栏中心猜测。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from course_config import validate_payload
from geofence_planner import calculate_geofence_from_course_union


def _finite(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not low <= value <= high:
        raise ValueError(f"{name} out of range")
    return value


def _clockwise_open_ring(fence: Iterable[tuple[float, float]]) -> list[list[float]]:
    """移除闭合重复点，并按 QGC Polygon Fence 约定输出顺时针 `[lat, lon]` 顶点。"""
    ring = [(float(lat), float(lon)) for lat, lon in fence]
    if len(ring) >= 2 and ring[0] == ring[-1]:
        ring.pop()
    if len(ring) < 3:
        raise ValueError("QGC polygon requires at least three distinct vertices")
    area2 = sum(lon1 * lat2 - lat1 * lon2
                for (lat1, lon1), (lat2, lon2) in zip(ring, ring[1:] + ring[:1]))
    if area2 > 0:
        ring.reverse()
    return [[lat, lon] for lat, lon in ring]


def build_qgc_plan(
    fence: Iterable[tuple[float, float]], *, home_lat: float, home_lon: float,
    home_alt_amsl_m: float,
) -> dict[str, Any]:
    """构造仅含 Inclusion Polygon Fence 的 QGC Plan 字典，不含飞行任务项。"""
    home = [
        _finite(home_lat, "home_lat", -90, 90),
        _finite(home_lon, "home_lon", -180, 180),
        _finite(home_alt_amsl_m, "home_alt_amsl_m", -2000, 100000),
    ]
    return {
        "fileType": "Plan",
        "groundStation": "QGroundControl",
        "version": 1,
        "geoFence": {
            "version": 2,
            "circles": [],
            "polygons": [{"version": 1, "inclusion": True, "polygon": _clockwise_open_ring(fence)}],
        },
        # Deliberately empty: this exporter is for fence visualization, not flight planning.
        "mission": {
            "version": 2, "firmwareType": 12, "vehicleType": 2,
            "globalPlanAltitudeMode": 1, "cruiseSpeed": 0, "hoverSpeed": 0,
            "plannedHomePosition": home, "items": [],
        },
        "rallyPoints": {"version": 2, "points": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export auto_course_union as a QGroundControl polygon fence plan")
    parser.add_argument("--course-payload", type=Path, required=True,
                        help="validated twave-course-config-v1 JSON captured from the OCS/FSM course payload")
    parser.add_argument("--home-lat", type=float, required=True)
    parser.add_argument("--home-lon", type=float, required=True)
    parser.add_argument("--home-alt-amsl-m", type=float, required=True,
                        help="QGC planned Home altitude in AMSL metres; not UAV HAE fence ceiling")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.course_payload.open(encoding="utf-8") as handle:
        course = validate_payload(json.load(handle))
    fence = calculate_geofence_from_course_union(
        ((point["latitude"], point["longitude"]) for point in course["corners"]),
        ((point["latitude"], point["longitude"]) for point in course["uav_transit_area"]),
        margin_m=1.0,
    )
    plan = build_qgc_plan(fence, home_lat=args.home_lat, home_lon=args.home_lon,
                          home_alt_amsl_m=args.home_alt_amsl_m)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote QGC polygon-fence plan: {args.output} ({len(plan['geoFence']['polygons'][0]['polygon'])} vertices)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
