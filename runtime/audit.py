"""
Genesis OS — Execution Audit Trail.

Provides structured audit logging for task execution, enabling
traceability, debugging, and post-hoc analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import TaskPhase, TaskTrace


@dataclass
class AuditEntry:
    """Single audit entry for an execution event."""
    timestamp: datetime
    task_id: str
    phase: TaskPhase
    event: str
    details: Dict[str, Any] = field(default_factory=dict)
    severity: str = "info"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "task_id": self.task_id,
            "phase": self.phase.value,
            "event": self.event,
            "details": self.details,
            "severity": self.severity,
        }


class ExecutionAudit:
    """Audit trail for Genesis task execution.

    Records structured events throughout the task lifecycle
    for explainability and debugging.
    """

    VERSION = "3.0.0"

    def __init__(self, max_entries: int = 1000):
        self._entries: List[AuditEntry] = []
        self._traces: Dict[str, TaskTrace] = {}
        self._max_entries = max_entries

    def start_trace(self, task_id: str, goal: str) -> TaskTrace:
        """Begin a new task trace."""
        trace = TaskTrace(task_id=task_id, goal=goal)
        self._traces[task_id] = trace
        self._record(task_id, TaskPhase.RECEIVED, "task_received", {"goal": goal})
        return trace

    def get_trace(self, task_id: str) -> Optional[TaskTrace]:
        return self._traces.get(task_id)

    def record_phase(self, task_id: str, phase: TaskPhase, event: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Record a phase transition."""
        trace = self._traces.get(task_id)
        if trace:
            trace.phase = phase
        self._record(task_id, phase, event, details or {})

    def record_observation(self, task_id: str, observation: Dict[str, Any]) -> None:
        trace = self._traces.get(task_id)
        if trace:
            trace.observations.append(observation)
        self._record(task_id, TaskPhase.OBSERVING, "observation", observation)

    def record_verification(self, task_id: str, verification: Dict[str, Any]) -> None:
        trace = self._traces.get(task_id)
        if trace:
            trace.verifications.append(verification)
        self._record(task_id, TaskPhase.VERIFYING, "verification", verification)

    def record_recovery(self, task_id: str, recovery: Dict[str, Any]) -> None:
        trace = self._traces.get(task_id)
        if trace:
            trace.recovery_actions.append(recovery)
        self._record(task_id, TaskPhase.RECOVERING, "recovery", recovery)

    def complete_trace(self, task_id: str, success: bool, result: Optional[Dict[str, Any]] = None) -> None:
        trace = self._traces.get(task_id)
        if trace:
            trace.completed_at = datetime.now()
            trace.result = result
            phase = TaskPhase.COMPLETED if success else TaskPhase.FAILED
            trace.phase = phase
        self._record(task_id, TaskPhase.COMPLETED if success else TaskPhase.FAILED, "task_completed" if success else "task_failed", result or {})

    def get_entries(self, task_id: Optional[str] = None, limit: int = 100) -> List[AuditEntry]:
        entries = self._entries
        if task_id:
            entries = [e for e in entries if e.task_id == task_id]
        return entries[-limit:]

    def get_all_traces(self) -> List[TaskTrace]:
        return list(self._traces.values())

    def clear(self) -> None:
        self._entries.clear()
        self._traces.clear()

    def _record(self, task_id: str, phase: TaskPhase, event: str, details: Dict[str, Any]) -> None:
        entry = AuditEntry(
            timestamp=datetime.now(),
            task_id=task_id,
            phase=phase,
            event=event,
            details=details,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]
