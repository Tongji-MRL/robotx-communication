"""运行模式到 RunDeclaration 输入的纯策略层。

本模块不连接 MQTT、ROS2 或设备，也不发布消息。Gateway 在启动前调用它，
将操作员选择的载具模式转为 OcsClient 已有的声明参数。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class VehicleMode(str, Enum):
    """启动时固定的声明载具集合；运行中不允许切换。"""

    UAV_ONLY = "uav_only"
    USV_ONLY = "usv_only"
    DUAL_VEHICLE = "dual_vehicle"


@dataclass(frozen=True)
class DeclarationSelection:
    """传给既有 ``publish_run_declaration`` 的模式化输入。"""

    vehicle_ids: list[str]
    uav_geofence: list[tuple[float, float]]
    uav_geofence_max_altitude_hae_m: float | None
    uav_pilot_callsign: str | None
    uav_geofence_mode: str


def select_declaration(
    mode: VehicleMode | str,
    *,
    uav_vehicle_id: str | None,
    usv_vehicle_id: str | None,
    uav_geofence: Iterable[tuple[float, float]],
    uav_geofence_max_altitude_hae_m: float | None,
    uav_pilot_callsign: str | None,
    uav_geofence_mode: str,
) -> DeclarationSelection:
    """按模式选择声明载具；非 UAV 模式不会携带 UAV 专属字段。"""
    try:
        selected_mode = VehicleMode(mode)
    except ValueError as exc:
        choices = ", ".join(item.value for item in VehicleMode)
        raise ValueError(f"vehicle mode must be one of: {choices}") from exc
    if selected_mode is VehicleMode.UAV_ONLY:
        if not uav_vehicle_id:
            raise ValueError("uav_only requires vehicles.uav.vehicle_id")
        vehicle_ids = [uav_vehicle_id]
    elif selected_mode is VehicleMode.USV_ONLY:
        if not usv_vehicle_id:
            raise ValueError("usv_only requires vehicles.usv.vehicle_id")
        vehicle_ids = [usv_vehicle_id]
    else:
        if not uav_vehicle_id or not usv_vehicle_id:
            raise ValueError("dual_vehicle requires both vehicles.uav and vehicles.usv vehicle_id")
        vehicle_ids = [uav_vehicle_id, usv_vehicle_id]
    if selected_mode is VehicleMode.USV_ONLY:
        # The official declaration must not imply a UAV fence/pilot in USV-only mode.
        return DeclarationSelection(vehicle_ids, [], None, None, "manual")
    return DeclarationSelection(
        vehicle_ids, list(uav_geofence), uav_geofence_max_altitude_hae_m,
        uav_pilot_callsign, uav_geofence_mode,
    )
