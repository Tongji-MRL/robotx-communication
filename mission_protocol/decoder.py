"""Decoder for the standalone 14-bit Mission status protocol."""

from __future__ import annotations

from .command_code import COMMAND_CODES
from .error_code import ERROR_CODES
from .status_code import PROGRESS_CODES, TASK_CODES, VEHICLE_CODES


def _reverse(codes: dict[str, str]) -> dict[str, str]:
    return {bits: name for name, bits in codes.items()}


def _decode(field: str, bits: str, codes: dict[str, str]) -> str:
    try:
        return _reverse(codes)[bits]
    except KeyError as exc:
        raise ValueError(f"invalid {field} bits: {bits!r}") from exc


def decode_status(bits: str) -> dict[str, str]:
    """Decode exactly 14 binary characters into symbolic protocol fields."""
    if not isinstance(bits, str) or len(bits) != 14 or set(bits) - {"0", "1"}:
        raise ValueError("status code must be a 14-bit binary string")
    return {
        "vehicle": _decode("vehicle", bits[0:1], VEHICLE_CODES),
        "task": _decode("task", bits[1:3], TASK_CODES),
        "progress": _decode("progress", bits[3:7], PROGRESS_CODES),
        "error": _decode("error", bits[7:11], ERROR_CODES),
        "command": _decode("command", bits[11:14], COMMAND_CODES),
    }
