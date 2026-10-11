"""Atomic persistence for the software SAFE_STOP latch."""
import json, os
from pathlib import Path
from .safety_models import SafetyStopRecord
class SafetyLatchStore:
    def __init__(self, path: str | Path) -> None: self.path = Path(path)
    def save(self, record: SafetyStopRecord) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True); temp = self.path.with_name(f".{self.path.name}.tmp")
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(record.to_dict(), handle, sort_keys=True); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp, self.path)
            # Persist the directory entry where supported; failure is unsafe.
            if hasattr(os, "O_DIRECTORY"):
                descriptor = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try: os.fsync(descriptor)
                finally: os.close(descriptor)
        except OSError as exc:
            raise SafetyLatchStoreError(f"SAFE_STOP latch write failed: {exc}") from exc
    def load(self) -> SafetyStopRecord | None:
        if not self.path.exists(): return None
        try:
            with self.path.open(encoding="utf-8") as handle: return SafetyStopRecord.from_dict(json.load(handle))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise SafetyLatchStoreError(f"SAFE_STOP latch is unreadable: {exc}") from exc
    def clear(self) -> None:
        try: self.path.unlink(missing_ok=True)
        except OSError as exc: raise SafetyLatchStoreError(f"SAFE_STOP latch clear failed: {exc}") from exc

class SafetyLatchStoreError(RuntimeError):
    pass
