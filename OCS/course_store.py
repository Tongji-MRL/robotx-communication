"""Validated internal course configuration storage for the OCS boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from collections.abc import Iterable


@dataclass(frozen=True)
class CourseConfig:
    """Protobuf-free, immutable representation of the active RoboCommand course."""

    course_id: str
    pinger_freq_hz: int
    corners: tuple[tuple[float, float], ...]
    sent_at: datetime


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
        sent_at: datetime,
    ) -> None:
        if not course_id:
            raise ValueError("course_id is required")
        if not isinstance(pinger_freq_hz, int) or isinstance(pinger_freq_hz, bool) or pinger_freq_hz < 0:
            raise ValueError("pinger_freq_hz must be a non-negative integer")
        saved_corners = tuple((float(latitude), float(longitude)) for latitude, longitude in corners)
        if not isinstance(sent_at, datetime):
            raise ValueError("sent_at must be a datetime")
        self._course = CourseConfig(course_id, pinger_freq_hz, saved_corners, sent_at)

    def get(self) -> CourseConfig | None:
        return self._course
