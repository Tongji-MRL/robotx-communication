"""Decode frozen 14-bit vehicle progress into a vehicle-tagged snapshot."""

from __future__ import annotations

from mission_protocol import decode_status


def decode_progress(vehicle: str, status_bits: str) -> dict[str, str]:
    """Decode one progress payload without changing or interpreting FSM state."""
    if not isinstance(vehicle, str) or not vehicle:
        raise ValueError("vehicle must be a non-empty string")
    decoded = decode_status(status_bits)
    # The frozen topic identifies the reporting vehicle; keep it as the public
    # vehicle label even though the wire code also carries a vehicle bit.
    return {**decoded, "vehicle": vehicle, "status_bits": status_bits}
