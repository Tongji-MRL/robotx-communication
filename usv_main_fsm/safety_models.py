"""Transport-neutral, provisional safety event contracts."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, IntEnum

class SafetyLevel(IntEnum):
    NORMAL = 0
    HOLD = 1
    CRITICAL = 2

class SafetyFaultType(str, Enum):
    OCS_LINK_LOST = "OCS_LINK_LOST"
    UAV_LINK_LOST = "UAV_LINK_LOST"
    USV_EXECUTOR_UNRESPONSIVE = "USV_EXECUTOR_UNRESPONSIVE"
    NAVIGATION_LOST = "NAVIGATION_LOST"
    FLIGHT_CONTROLLER_CRITICAL = "FLIGHT_CONTROLLER_CRITICAL"
    UNCONTROLLED_MOTION = "UNCONTROLLED_MOTION"
    MANUAL_ESTOP = "MANUAL_ESTOP"
    SENSOR_UNHEALTHY = "SENSOR_UNHEALTHY"
    UNKNOWN_CRITICAL_DATA = "UNKNOWN_CRITICAL_DATA"

@dataclass(frozen=True)
class SafetyEvent:
    event_id: str
    run_id: int | None
    fault: SafetyFaultType
    active: bool
    source: str
    timestamp: float
    trustworthy: bool = True
    detail: str = ""
    clears_event_id: str | None = None

@dataclass(frozen=True)
class SafetyDecision:
    level: SafetyLevel
    reason: str
    event_ids: tuple[str, ...]

@dataclass(frozen=True)
class SafetyStopRecord:
    run_id: int | None
    source: str
    reason: str
    triggered_at: float
    version: int = 1
    def to_dict(self) -> dict: return self.__dict__.copy()
    @classmethod
    def from_dict(cls, value: dict) -> "SafetyStopRecord":
        return cls(int(value["run_id"]) if value.get("run_id") is not None else None,
                   str(value["source"]), str(value["reason"]), float(value["triggered_at"]), int(value.get("version", 1)))
