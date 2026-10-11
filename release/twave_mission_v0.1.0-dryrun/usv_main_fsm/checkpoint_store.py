"""Atomic local persistence for a domain checkpoint."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import Checkpoint


class CheckpointStoreError(RuntimeError):
    pass


class CheckpointStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, checkpoint: Checkpoint) -> None:
        if not checkpoint.is_valid_for(checkpoint.run_id, checkpoint.task):
            raise CheckpointStoreError("refusing to persist an invalid checkpoint")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        try:
            with temporary_path.open(mode="w", encoding="utf-8") as handle:
                json.dump(checkpoint.to_dict(), handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise CheckpointStoreError(f"atomic checkpoint save failed: {exc}") from exc

    def load(self) -> Checkpoint | None:
        if not self.path.exists():
            return None
        try:
            with self.path.open(encoding="utf-8") as handle:
                return Checkpoint.from_dict(json.load(handle))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise CheckpointStoreError(f"checkpoint load failed: {exc}") from exc
