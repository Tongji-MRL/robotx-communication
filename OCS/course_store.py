"""Validated internal course configuration storage for the OCS boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from collections.abc import Iterable
try:
    from .course_config import _optional_polygon, validate_course_fields
except ImportError:
    from course_config import _optional_polygon, validate_course_fields


@dataclass(frozen=True)
class CourseConfig:
    """Protobuf-free, immutable representation of the active RoboCommand course."""

    course_id: str
    pinger_freq_hz: int
    corners: tuple[tuple[float, float], ...]
    uav_transit_area: tuple[tuple[float, float], ...]
    sent_at: datetime | None


class CourseStore:
    """Store the one most recently validated course configuration."""

    def __init__(self) -> None:
        self._course: CourseConfig | None = None

    def update(
        self,
        *,
        course_id: str,
        pinger_freq_hz: int,
        corners: Iterable[tuple[float, float]],
        uav_transit_area: Iterable[tuple[float, float]] = (),
        sent_at: datetime | None,
    ) -> None:
        course_id, pinger_freq_hz, saved_corners = validate_course_fields(course_id, pinger_freq_hz, corners)
        if sent_at is not None and not isinstance(sent_at, datetime):
            raise ValueError("sent_at must be a datetime or null")
        # Reuse the frozen course validator for a non-empty optional transit
        # area, while preserving an official empty-area semantic.
        self._course = CourseConfig(
            course_id, pinger_freq_hz, saved_corners,
            _optional_polygon(uav_transit_area), sent_at,
        )

    def get(self) -> CourseConfig | None:
        return self._course
