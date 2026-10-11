"""Bounded JSONL audit log; never includes transport credentials."""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

class AuditLogError(RuntimeError): pass

class AuditLogger:
    def __init__(self, directory: str | Path, *, max_bytes: int = 5_000_000, backups: int = 10) -> None:
        self.path = Path(directory) / "coordinator" / "events.jsonl"; self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(self.path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    def event(self, event_type: str, *, run_id: int | None = None, source: str = "mission", **fields) -> None:
        forbidden = {"password", "token", "secret"}
        value = {"timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "event_type": event_type, "run_id": run_id, "source": source,
                 **{k:v for k,v in fields.items() if k.lower() not in forbidden}}
        try:
            self.handler.stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"); self.handler.flush(); os.fsync(self.handler.stream.fileno())
        except OSError as exc: raise AuditLogError(str(exc)) from exc
    def close(self) -> None: self.handler.close()

def query_run(directory: str | Path, run_id: int) -> list[dict]:
    result=[]
    for path in sorted((Path(directory)/"coordinator").glob("events.jsonl*")):
        if path.suffix != ".jsonl": continue
        for line in path.read_text(encoding="utf-8").splitlines():
            value=json.loads(line)
            if value.get("run_id") == run_id: result.append(value)
    return result
