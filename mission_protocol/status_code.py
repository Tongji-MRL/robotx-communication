"""Definitions and encoder for the non-error portions of a mission status."""

from __future__ import annotations

from .command_code import COMMAND_CODES
from .error_code import ERROR_CODES


VEHICLE_CODES = {
    "TSKY": "0",
    "TWAVE": "1",
}

TASK_CODES = {
    "NOT_STARTED": "00",
    "TASK1": "01",
    "TASK3": "10",
    "TASK4": "11",
}

PROGRESS_CODES = {
    "READY": "0000",
    "STARTING": "0001",
    "RUNNING": "0010",
    "COMPLETE": "1111",
}


def _code_for(field: str, value: str, codes: dict[str, str]) -> str:
    if not isinstance(value, str) or value not in codes:
        raise ValueError(f"invalid {field}: {value!r}")
    return codes[value]


def encode_status(
    vehicle: str,
    task: str,
    progress: str,
    error: str,
    command: str,
) -> str:
    """Encode five symbolic fields as ``V TT PPPP EEEE CCC`` (14 bits)."""
    return "".join((
        _code_for("vehicle", vehicle, VEHICLE_CODES),
        _code_for("task", task, TASK_CODES),
        _code_for("progress", progress, PROGRESS_CODES),
        _code_for("error", error, ERROR_CODES),
        _code_for("command", command, COMMAND_CODES),
    ))
