"""Offline Task1 mission-state adapter for the OCS prototype.

This module has no ROS 2 or MQTT dependency. It only normalizes a dictionary
received from a future ROS 2 Bridge, so the mapping can be tested before the
real Orin message type and command interface are finalized.
"""

import argparse
import json
from typing import Any


STATE_MAP = {
    "ENTRY_CLOCKWISE_ORBIT": "RUNNING",
    "RECOVERY": "RECOVERY",
    "TASK_COMPLETE": "COMPLETE",
    "COMMAND_TIMEOUT": "FAULT",
    "MAVROS_DISCONNECTED": "FAULT",
}


def normalize_mission_state(message: dict[str, Any], vehicle_id: str, team_id: str = "TONG") -> dict[str, Any]:
    """Convert a future MissionState payload into an OCS-neutral report.

    Field aliases are intentionally small and conservative because the final
    MissionState definition is not available yet.
    """
    phase = message.get("phase") or message.get("state") or "UNKNOWN"
    reason = message.get("reason") or message.get("fault_reason") or ""
    if phase not in STATE_MAP and reason in STATE_MAP:
        phase = reason

    return {
        "team_id": team_id,
        "vehicle_id": vehicle_id,
        "task_id": "TASK1",
        "phase": phase,
        "ocs_state": STATE_MAP.get(phase, "UNKNOWN"),
        "passed_gate_count": message.get("passed_gate_count", message.get("gates_passed")),
        "current_gate": message.get("current_gate"),
        "recovery_count": message.get("recovery_count", 0),
        "reason": reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="演示 Task1 状态转换")
    parser.add_argument("--phase", default="ENTRY_CLOCKWISE_ORBIT")
    parser.add_argument("--vehicle-id", default="T-Wave")
    args = parser.parse_args()

    result = normalize_mission_state({"phase": args.phase}, args.vehicle_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
