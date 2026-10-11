"""Adapter from frozen internal task reports to RoboCommand ``RxReport`` protobufs."""

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


def _position(payload: Mapping[str, Any], field: str):
    value = payload.get(field)
    if not isinstance(value, Mapping) or {"latitude", "longitude"} - set(value):
        raise ValueError(f"{field} must contain latitude and longitude")
    return common_pb2.LatLng(latitude=float(value["latitude"]), longitude=float(value["longitude"]))


def _beacon_state(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and hasattr(rx_common_pb2, value):
        return getattr(rx_common_pb2, value)
    raise ValueError(f"invalid buoy state: {value!r}")


class TaskReportAdapter:
    """Build task-result protobuf reports only; publishing remains external."""

    def __init__(self, team_id: str, *, now: Callable[[], datetime] | None = None) -> None:
        if not team_id:
            raise ValueError("team_id is required")
        self.team_id = team_id
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sequences: dict[str, int] = {}

    def to_proto(self, report: Mapping[str, Any]):
        """Convert one frozen task-report input to an ``RxReport`` protobuf.

        ``run_id`` remains an internal correlation value: ``RxReport`` has no
        matching field, so this adapter deliberately does not invent one.
        """
        run_id = report.get("run_id")
        vehicle_id = report.get("vehicle_id")
        task = report.get("task")
        result = report.get("result")
        payload = report.get("payload")
        if not isinstance(run_id, int) or isinstance(run_id, bool):
            raise ValueError("run_id must be an integer")
        if not isinstance(vehicle_id, str) or not vehicle_id:
            raise ValueError("vehicle_id is required")
        if not isinstance(task, str) or not isinstance(result, str) or not isinstance(payload, Mapping):
            raise ValueError("task, result, and payload are required")

        body_name, body = self._body(task, result, payload)
        seq = self._sequences.get(vehicle_id, 0) + 1
        self._sequences[vehicle_id] = seq
        sent_at = Timestamp()
        sent_at.FromDatetime(self._now())
        return rx_reports_pb2.RxReport(
            team_id=self.team_id,
            vehicle_id=vehicle_id,
            seq=seq,
            sent_at=sent_at,
            **{body_name: body},
        )

    @staticmethod
    def _body(task: str, result: str, payload: Mapping[str, Any]):
        if task == "TASK1" and result == "SUCCESS":
            buoys = payload.get("buoys")
            if not isinstance(buoys, list):
                raise ValueError("buoys must be a list")
            converted_buoys = []
            for buoy in buoys:
                if not isinstance(buoy, Mapping):
                    raise ValueError("each buoy must be an object")
                if "state" not in buoy:
                    raise ValueError("each buoy requires state")
                converted_buoys.append(rx_reports_pb2.BuoyDetection(
                    position=_position(buoy, "position"), state=_beacon_state(buoy["state"]),
                ))
            return "safe_passage", rx_reports_pb2.SafePassageReport(
                entry_position=_position(payload, "entry_position"),
                exit_position=_position(payload, "exit_position"),
                buoys=converted_buoys,
            )
        if task == "TASK3" and result == "DOCK_COMPLETE":
            if not isinstance(payload.get("bay_id"), int) or isinstance(payload["bay_id"], bool):
                raise ValueError("bay_id must be an integer")
            return "docking", rx_reports_pb2.DockingReport(bay_id=payload["bay_id"])
        if task == "TASK3" and result == "FIRE_COMPLETE":
            if not isinstance(payload.get("window_id"), int) or isinstance(payload["window_id"], bool):
                raise ValueError("window_id must be an integer")
            return "firefighting", rx_reports_pb2.FirefightingReport(window_id=payload["window_id"])
        raise ValueError(f"unsupported task result: {task}/{result}")
