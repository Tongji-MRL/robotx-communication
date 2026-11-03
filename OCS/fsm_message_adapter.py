"""ROS 2 String/JSON messages matching Tongji-MRL/FSM feature/ocs-fsm-integration.

Pure functions: no ROS, MQTT, or actuator imports.  Invalid or unsupported
requests are rejected rather than guessed or silently converted to motion.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

RUN_SCHEMA = "twave-mission-run-v1"
TASK4_SCHEMA = "twave-mission-task4-v1"


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _position(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    lat, lon = value.get("latitude"), value.get("longitude")
    if (type(lat) not in (int, float) or type(lon) not in (int, float)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        return None
    return {"latitude": float(lat), "longitude": float(lon)}


def build_run_start(action: Mapping[str, Any]) -> dict[str, Any] | None:
    """The FSM requires a stable command ID derived from the official run/seq.

    Official RxCommand has no top-level command_id; the OCS intentionally
    derives its internal correlation ID from validated, nonzero fields.
    Never invent missing run IDs or command sequences.
    """
    if action.get("command") != "RUN_START":
        return None
    run_id, seq = action.get("run_id"), action.get("command_seq")
    if not _positive_int(run_id) or not _positive_int(seq):
        return None
    return {
        "schema_version": RUN_SCHEMA,
        "command": "begin",
        "run_id": run_id,
        "command_id": f"robocommand:{run_id}:{seq}:run-start",
        "official_command_seq": seq,
    }


def build_task4(action: Mapping[str, Any]) -> dict[str, Any] | None:
    """Supported Task4 transport messages only; never decide safety policy.

    KEEP_OUT_ZONE / ALL_CLEAR / MOVING_OBJECT are intentionally not treated as
    executable until the FSM owner implements and verifies their policy gates.
    """
    kind = action.get("command")
    run_id, seq = action.get("run_id"), action.get("command_seq")
    if not _positive_int(run_id):
        return None
    parameters = action.get("parameters")
    if not isinstance(parameters, Mapping):
        return None

    if kind == "TASK4_ASSISTANCE":
        original_seq = parameters.get("official_command_seq")
        if not _positive_int(seq) or original_seq != seq:
            return None
        vehicle = {1: "usv", 3: "uav"}.get(parameters.get("vehicle_type"))
        point = _position(parameters.get("position"))
        if vehicle is None or point is None:
            return None
        command_id = f"robocommand:{run_id}:{seq}:assistance"
        command = {"type": "ASSISTANCE_REQUEST", "command_seq": seq, "position": point}
    elif kind == "TASK4_READINESS_CONFIRM":
        report_seq = parameters.get("report_seq")
        original_seq = parameters.get("original_command_seq")
        vehicle = parameters.get("vehicle")
        if (not _positive_int(seq) or not _positive_int(original_seq)
                or not _positive_int(report_seq) or vehicle not in {"usv", "uav"}):
            return None
        command_id = f"robocommand:{run_id}:{seq}:readiness-confirm"
        command = {
            "type": "READINESS_CONFIRM",
            "command_seq": original_seq,
            "original_command_seq": original_seq,
            "report_seq": report_seq,
            "official_confirmation_seq": seq,
        }
    elif kind == "TASK4_READINESS_REPORT_PUBLISHED":
        report_seq = parameters.get("report_seq")
        original_seq = parameters.get("original_command_seq")
        event_id = parameters.get("readiness_event_id")
        vehicle = parameters.get("vehicle")
        if (not _positive_int(original_seq) or not _positive_int(report_seq)
                or not isinstance(event_id, str) or not event_id
                or vehicle not in {"usv", "uav"}):
            return None
        command_id = f"{event_id}:published:{report_seq}"
        command = {
            "type": "READINESS_REPORT_PUBLISHED",
            "command_seq": original_seq,
            "report_seq": report_seq,
            "readiness_event_id": event_id,
            "internal_origin": "ocs",
        }
    else:
        return None

    return {
        "schema_version": TASK4_SCHEMA,
        "run_id": run_id,
        "command_id": command_id,
        "vehicle": vehicle,
        "task": "TASK4",
        "command": command,
    }
