"""Candidate safety policy; values are deliberately not production rules."""
from dataclasses import dataclass, field
from .safety_models import SafetyFaultType, SafetyLevel

@dataclass(frozen=True)
class SafetyPolicy:
    levels: dict[SafetyFaultType, SafetyLevel] = field(default_factory=lambda: {
        SafetyFaultType.OCS_LINK_LOST: SafetyLevel.HOLD, SafetyFaultType.UAV_LINK_LOST: SafetyLevel.HOLD,
        SafetyFaultType.USV_EXECUTOR_UNRESPONSIVE: SafetyLevel.HOLD, SafetyFaultType.NAVIGATION_LOST: SafetyLevel.HOLD,
        SafetyFaultType.FLIGHT_CONTROLLER_CRITICAL: SafetyLevel.CRITICAL, SafetyFaultType.UNCONTROLLED_MOTION: SafetyLevel.CRITICAL,
        SafetyFaultType.MANUAL_ESTOP: SafetyLevel.CRITICAL, SafetyFaultType.SENSOR_UNHEALTHY: SafetyLevel.HOLD,
        SafetyFaultType.UNKNOWN_CRITICAL_DATA: SafetyLevel.HOLD,
    })
    def level_for(self, fault: SafetyFaultType, *, trustworthy: bool) -> SafetyLevel:
        return self.levels.get(fault, SafetyLevel.HOLD) if trustworthy else SafetyLevel.HOLD
