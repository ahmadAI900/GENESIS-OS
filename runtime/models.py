"""
Genesis OS — Runtime Data Models.

Structured models for task execution tracing, audit, and session persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskPhase(str, Enum):
    """Lifecycle phases of a Genesis task."""
    RECEIVED = "received"
    UNDERSTANDING = "understanding"
    CLASSIFIED = "classified"
    PLANNING = "planning"
    WAITING = "waiting"
    EXECUTING = "executing"
    OBSERVING = "observing"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskTrace:
    """Structured execution trace for a single task.

    Captures the full lifecycle from receipt to completion,
    enabling explainable execution and post-hoc analysis.
    """
    task_id: str
    goal: str
    intent: Optional[str] = None
    entities: List[Dict[str, Any]] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    selected_capabilities: List[str] = field(default_factory=list)
    selected_agents: List[str] = field(default_factory=list)
    phase: TaskPhase = TaskPhase.RECEIVED
    steps: List[Dict[str, Any]] = field(default_factory=list)
    observations: List[Dict[str, Any]] = field(default_factory=list)
    verifications: List[Dict[str, Any]] = field(default_factory=list)
    recovery_actions: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def trustworthy(self) -> bool:
        return (
            self.phase == TaskPhase.COMPLETED
            and bool(self.result)
            and not self.errors
            and bool(self.verifications)
            and all(
                verification.get("verified") is True
                for verification in self.verifications
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "intent": self.intent,
            "entities": self.entities,
            "constraints": self.constraints,
            "selected_capabilities": self.selected_capabilities,
            "selected_agents": self.selected_agents,
            "phase": self.phase.value,
            "steps": self.steps,
            "observations": self.observations,
            "verifications": self.verifications,
            "recovery_actions": self.recovery_actions,
            "errors": self.errors,
            "result": self.result,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "trustworthy": self.trustworthy,
            "metadata": self.metadata,
        }
