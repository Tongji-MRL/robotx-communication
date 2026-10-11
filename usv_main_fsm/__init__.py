"""Pure-Python decision core for the RobotX T-Wave mission coordinator.

This package deliberately has no ROS 2, MQTT, PX4, or actuator dependency.
Its actions are domain intents that a future vehicle-specific adapter must map
to a frozen transport and execution interface.
"""

from .coordinator import MissionCoordinator
from .models import (
    Ack,
    Action,
    ActionType,
    Checkpoint,
    CompletionEvent,
    MainState,
    TaskId,
    Target,
)
from .safety_monitor import SafetyMonitor
from .safety_models import SafetyEvent, SafetyFaultType, SafetyLevel

__all__ = [
    "Ack", "Action", "ActionType", "Checkpoint", "CompletionEvent",
    "MainState", "MissionCoordinator", "TaskId", "Target",
    "SafetyEvent", "SafetyFaultType", "SafetyLevel", "SafetyMonitor",
]
