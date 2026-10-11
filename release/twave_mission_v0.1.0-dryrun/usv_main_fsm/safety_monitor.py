"""Evaluates injected local health events without controlling hardware."""
from .safety_models import SafetyDecision, SafetyEvent, SafetyFaultType, SafetyLevel
from .safety_policy import SafetyPolicy

class SafetyMonitor:
    def __init__(self, policy: SafetyPolicy | None = None) -> None:
        self.policy = policy or SafetyPolicy(); self._events: dict[str, SafetyEvent] = {}; self._seen: set[str] = set()
    def ingest(self, event: SafetyEvent, *, current_run_id: int | None) -> SafetyDecision | None:
        if event.event_id in self._seen or (event.run_id is not None and event.run_id != current_run_id): return None
        self._seen.add(event.event_id)
        if event.active: self._events[event.event_id] = event
        else: self._events.pop(event.clears_event_id or event.event_id, None)
        return self.evaluate()
    def mark_monitor_fault(self, detail: str = "monitor health unknown") -> SafetyDecision:
        self._events["monitor-unknown"] = SafetyEvent("monitor-unknown", None, SafetyFaultType.UNKNOWN_CRITICAL_DATA, True, "SafetyMonitor", 0.0, False, detail)
        return self.evaluate()
    def evaluate(self) -> SafetyDecision:
        active = tuple(self._events.values())
        if not active: return SafetyDecision(SafetyLevel.NORMAL, "no active safety events", ())
        level = max(self.policy.level_for(x.fault, trustworthy=x.trustworthy) for x in active)
        chosen = [x for x in active if self.policy.level_for(x.fault, trustworthy=x.trustworthy) == level]
        return SafetyDecision(level, "; ".join(f"{x.fault.value}: {x.detail}" for x in chosen), tuple(x.event_id for x in chosen))
