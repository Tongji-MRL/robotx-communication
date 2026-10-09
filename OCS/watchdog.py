"""Pure-Python communication watchdog for the OCS gateway.

It reports stale heartbeats and missing vehicle ACKs.  It never selects a
task or sends an automatic stop; those decisions remain with the USV.
"""

from __future__ import annotations


class OcsWatchdog:
    def __init__(self, heartbeat_timeout_s: float = 3.0, command_ack_timeout_s: float = 5.0) -> None:
        if heartbeat_timeout_s <= 0 or command_ack_timeout_s <= 0:
            raise ValueError("watchdog timeouts must be positive")
        self.heartbeat_timeout_s = float(heartbeat_timeout_s)
        self.command_ack_timeout_s = float(command_ack_timeout_s)
        self._expected: set[str] = set()
        self._last_heartbeat: dict[str, float] = {}
        self._pending_acks: dict[int, float] = {}
        self._reported_heartbeats: set[str] = set()
        self._reported_acks: set[int] = set()

    def start_run(self, vehicle_ids: list[str] | set[str], now: float) -> None:
        self._expected = set(vehicle_ids)
        self._last_heartbeat = {vehicle_id: now for vehicle_id in self._expected}
        self._pending_acks.clear()
        self._reported_heartbeats.clear()
        self._reported_acks.clear()

    def note_heartbeat(self, vehicle_id: str, now: float) -> None:
        if vehicle_id in self._expected:
            self._last_heartbeat[vehicle_id] = now
            self._reported_heartbeats.discard(vehicle_id)

    def note_command_sent(self, command_seq: int, now: float) -> None:
        self._pending_acks[int(command_seq)] = now
        self._reported_acks.discard(int(command_seq))

    def note_ack(self, command_seq: int) -> None:
        sequence = int(command_seq)
        self._pending_acks.pop(sequence, None)
        self._reported_acks.discard(sequence)

    def check(self, now: float) -> list[dict]:
        events: list[dict] = []
        for vehicle_id, last_seen in self._last_heartbeat.items():
            elapsed = now - last_seen
            if elapsed >= self.heartbeat_timeout_s and vehicle_id not in self._reported_heartbeats:
                self._reported_heartbeats.add(vehicle_id)
                events.append({
                    "kind": "heartbeat_timeout",
                    "vehicle_id": vehicle_id,
                    "elapsed_s": round(elapsed, 3),
                })
        for command_seq, sent_at in self._pending_acks.items():
            elapsed = now - sent_at
            if elapsed >= self.command_ack_timeout_s and command_seq not in self._reported_acks:
                self._reported_acks.add(command_seq)
                events.append({
                    "kind": "command_ack_timeout",
                    "command_seq": command_seq,
                    "elapsed_s": round(elapsed, 3),
                })
        return events
