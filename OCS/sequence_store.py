"""Small durable store for RoboCommand sequence numbers.

RoboCommand sequences must not be reused after an OCS restart.  The store is
deliberately limited to counters; it is not a run database and contains no
vehicle state.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class SequenceStore:
    VERSION = 1

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._state = {
            "version": self.VERSION,
            "team_seq": 0,
            "report_seq": {},
            "last_command_seq": 0,
        }
        if self.path:
            self._load()

    @property
    def team_seq(self) -> int:
        return int(self._state["team_seq"])

    @property
    def report_seq(self) -> dict[str, int]:
        return {str(key): int(value) for key, value in self._state["report_seq"].items()}

    @property
    def last_command_seq(self) -> int:
        return int(self._state["last_command_seq"])

    def next_team_seq(self) -> int:
        self._state["team_seq"] = self.team_seq + 1
        self._save()
        return self.team_seq

    def next_report_seq(self, vehicle_id: str) -> int:
        report_seq = self.report_seq.get(vehicle_id, 0) + 1
        self._state["report_seq"][vehicle_id] = report_seq
        self._save()
        return report_seq

    def observe_command_seq(self, sequence: int) -> None:
        if sequence > self.last_command_seq:
            self._state["last_command_seq"] = int(sequence)
            self._save()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("version") != self.VERSION:
                raise ValueError("unsupported state version")
            if not isinstance(state.get("report_seq"), dict):
                raise ValueError("report_seq must be an object")
            self._state = {
                "version": self.VERSION,
                "team_seq": max(0, int(state.get("team_seq", 0))),
                "report_seq": {
                    str(key): max(0, int(value))
                    for key, value in state["report_seq"].items()
                },
                "last_command_seq": max(0, int(state.get("last_command_seq", 0))),
            }
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot load OCS sequence state {self.path}: {exc}") from exc

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
