"""Adapter from internal heartbeat dictionaries to RoboCommand ``RxReport`` protobufs."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.protobuf.timestamp_pb2 import Timestamp


_GEN_ROOT = Path(__file__).resolve().parents[4] / "RobotX_2026" / "gen" / "python"
if str(_GEN_ROOT) not in sys.path:
    sys.path.insert(0, str(_GEN_ROOT))

import common_pb2  # noqa: E402
from robotx import rx_common_pb2, rx_reports_pb2  # noqa: E402


def _enum(value: Any, module: Any, field: str) -> int:
    """Accept protobuf enum integers or their generated symbolic names."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and hasattr(module, value):
        return getattr(module, value)
    raise ValueError(f"invalid {field}: {value!r}")


class RxReportAdapter:
    """Build protobuf reports only; transport ownership remains outside this class."""

    def __init__(
        self,
        team_id: str,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not team_id:
            raise ValueError("team_id is required")
        self.team_id = team_id
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sequences: dict[str, int] = {}

    def to_proto(self, vehicle_id: str, heartbeat_payload: Mapping[str, Any]):
        """Create an ``rx_reports_pb2.RxReport`` containing a Heartbeat body."""
        if not vehicle_id:
            raise ValueError("vehicle_id is required")
        position = heartbeat_payload.get("position")
        if not isinstance(position, Mapping) or {"latitude", "longitude"} - set(position):
            raise ValueError("heartbeat position must contain latitude and longitude")

        seq = self._sequences.get(vehicle_id, 0) + 1
        self._sequences[vehicle_id] = seq
        sent_at = Timestamp()
        sent_at.FromDatetime(self._now())

        heartbeat = rx_reports_pb2.Heartbeat(
            state=_enum(heartbeat_payload.get("state", "STATE_UNKNOWN"), common_pb2, "state"),
            position=common_pb2.LatLng(
                latitude=float(position["latitude"]), longitude=float(position["longitude"]),
            ),
            spd_mps=float(heartbeat_payload["spd_mps"]),
            heading_deg=float(heartbeat_payload["heading_deg"]),
            roll_deg=float(heartbeat_payload["roll_deg"]),
            pitch_deg=float(heartbeat_payload["pitch_deg"]),
            altitude_hae_m=float(heartbeat_payload["altitude_hae_m"]),
            current_task=_enum(heartbeat_payload["current_task"], rx_common_pb2, "current_task"),
            vehicle_type=_enum(heartbeat_payload.get("vehicle_type", "TYPE_UNKNOWN"), rx_common_pb2, "vehicle_type"),
            flight_phase=_enum(heartbeat_payload.get("flight_phase", "FLIGHT_PHASE_UNKNOWN"), rx_common_pb2, "flight_phase"),
        )
        return rx_reports_pb2.RxReport(
            team_id=self.team_id,
            vehicle_id=vehicle_id,
            seq=seq,
            sent_at=sent_at,
            heartbeat=heartbeat,
        )
