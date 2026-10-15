"""
Genesis OS — Level 3 Explainable Execution Events.

Structured runtime events for progress reporting:

    UNDERSTANDING the task...
    FINDING the result folder...
    OPENING the spreadsheet...
    CALCULATING percentages...
    SORTING the results...
    SAVING the file...
    VERIFYING the output...
    DONE.

These events are emitted during execution and can be consumed
by any UI layer for progress display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class EventType(Enum):
    """Types of execution events."""
    TASK_RECEIVED = "task_received"
    UNDERSTANDING = "understanding"
    CLASSIFIED = "classified"
    PLANNING = "planning"
    PLAN_CREATED = "plan_created"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    STEP_RETRYING = "step_retrying"
    AGENT_INVOKED = "agent_invoked"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    OS_ACTION_INVOKED = "os_action_invoked"
    OS_ACTION_COMPLETED = "os_action_completed"
    OS_ACTION_FAILED = "os_action_failed"
    OBSERVING = "observing"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    REPLANNING = "replanning"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    PROGRESS_UPDATE = "progress_update"
    WAITING_FOR_DEPENDENCY = "waiting_for_dependency"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMATION_RECEIVED = "confirmation_received"


class EventSeverity(Enum):
    """Event severity for filtering."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ProgressEvent:
    """A single execution progress event."""
    event_id: str
    event_type: EventType
    timestamp: datetime
    task_id: str
    step_id: Optional[str] = None
    message: str = ""
    severity: EventSeverity = EventSeverity.INFO
    progress_percent: Optional[float] = None  # 0-100
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "task_id": self.task_id,
            "step_id": self.step_id,
            "message": self.message,
            "severity": self.severity.value,
            "progress_percent": self.progress_percent,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "metadata": self.metadata,
        }

    def format_for_user(self) -> str:
        """Format event for user display."""
        return self.message


class EventEmitter:
    """
    Emits structured execution events.
    
    Supports multiple listeners (callbacks) for different UI layers.
    """

    def __init__(self):
        self._listeners: List[Callable[[ProgressEvent], None]] = []
        self._event_history: List[ProgressEvent] = []
        self._event_counter = 0

    def add_listener(self, listener: Callable[[ProgressEvent], None]) -> None:
        """Add an event listener."""
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[ProgressEvent], None]) -> bool:
        """Remove an event listener."""
        try:
            self._listeners.remove(listener)
            return True
        except ValueError:
            return False

    def emit(
        self,
        event_type: EventType,
        task_id: str,
        message: str = "",
        step_id: Optional[str] = None,
        severity: EventSeverity = EventSeverity.INFO,
        progress_percent: Optional[float] = None,
        current_step: Optional[int] = None,
        total_steps: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProgressEvent:
        """Emit a progress event."""
        self._event_counter += 1
        event = ProgressEvent(
            event_id=f"evt-{self._event_counter:06d}",
            event_type=event_type,
            timestamp=datetime.now(),
            task_id=task_id,
            step_id=step_id,
            message=message,
            severity=severity,
            progress_percent=progress_percent,
            current_step=current_step,
            total_steps=total_steps,
            metadata=metadata or {},
        )

        self._event_history.append(event)

        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass  # Don't let listener errors break execution

        return event

    def get_history(self, task_id: Optional[str] = None) -> List[ProgressEvent]:
        """Get event history, optionally filtered by task."""
        if task_id:
            return [e for e in self._event_history if e.task_id == task_id]
        return list(self._event_history)

    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()
        self._event_counter = 0


# Standard message templates for common operations
PROGRESS_MESSAGES = {
    # Task lifecycle
    EventType.TASK_RECEIVED: "Received task: {objective}",
    EventType.UNDERSTANDING: "Understanding the task...",
    EventType.CLASSIFIED: "Task classified as {classification}",
    EventType.PLANNING: "Planning the workflow...",
    EventType.PLAN_CREATED: "Created plan with {step_count} step(s)",

    # Step execution
    EventType.STEP_STARTED: "Step {current}/{total}: {description}",
    EventType.STEP_COMPLETED: "Step {current}/{total} completed: {description}",
    EventType.STEP_FAILED: "Step {current}/{total} failed: {error}",
    EventType.STEP_RETRYING: "Retrying step {current}/{total} (attempt {attempt}/{max})",

    # Agent execution
    EventType.AGENT_INVOKED: "Invoking {agent_name} agent...",
    EventType.AGENT_COMPLETED: "{agent_name} agent completed",
    EventType.AGENT_FAILED: "{agent_name} agent failed: {error}",

    # OS actions
    EventType.OS_ACTION_INVOKED: "Executing {operation} on {target}...",
    EventType.OS_ACTION_COMPLETED: "{operation} on {target} completed",
    EventType.OS_ACTION_FAILED: "{operation} on {target} failed: {error}",

    # Observation & verification
    EventType.OBSERVING: "Observing system state...",
    EventType.VERIFYING: "Verifying results...",

    # Recovery
    EventType.RECOVERING: "Attempting recovery: {strategy}",
    EventType.REPLANNING: "Replanning workflow...",

    # Completion
    EventType.TASK_COMPLETED: "Task completed successfully in {duration:.1f}s",
    EventType.TASK_FAILED: "Task failed: {error}",
    EventType.TASK_CANCELLED: "Task cancelled",

    # Progress
    EventType.PROGRESS_UPDATE: "Progress: {percent:.0f}% ({current}/{total})",

    # Dependencies
    EventType.WAITING_FOR_DEPENDENCY: "Waiting for {dependency} to complete...",

    # Confirmation
    EventType.CONFIRMATION_REQUIRED: "Confirmation required: {details}",
    EventType.CONFIRMATION_RECEIVED: "Confirmation received, proceeding...",
}


def format_progress_message(event_type: EventType, **kwargs) -> str:
    """Format a standard progress message."""
    template = PROGRESS_MESSAGES.get(event_type, "{message}")
    try:
        return template.format(**kwargs)
    except KeyError:
        return template


class ProgressTracker:
    """
    Tracks execution progress and emits events.
    
    Integrates with workflow engine to provide real-time progress updates.
    """

    def __init__(self, emitter: Optional[EventEmitter] = None):
        self.emitter = emitter or EventEmitter()
        self._task_start_time: Optional[datetime] = None
        self._current_task_id: Optional[str] = None
        self._total_steps = 0
        self._completed_steps = 0

    def start_task(self, task_id: str, objective: str, total_steps: int) -> None:
        """Start tracking a new task."""
        self._current_task_id = task_id
        self._task_start_time = datetime.now()
        self._total_steps = total_steps
        self._completed_steps = 0

        self.emitter.emit(
            EventType.TASK_RECEIVED,
            task_id=task_id,
            message=format_progress_message(EventType.TASK_RECEIVED, objective=objective),
            total_steps=total_steps,
            metadata={"objective": objective},
        )

    def start_understanding(self) -> None:
        """Emit understanding event."""
        self.emitter.emit(
            EventType.UNDERSTANDING,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.UNDERSTANDING),
        )

    def classified(self, classification: str) -> None:
        """Emit classification event."""
        self.emitter.emit(
            EventType.CLASSIFIED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.CLASSIFIED, classification=classification),
        )

    def planning(self) -> None:
        """Emit planning event."""
        self.emitter.emit(
            EventType.PLANNING,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.PLANNING),
        )

    def plan_created(self, step_count: int) -> None:
        """Emit plan created event."""
        self.emitter.emit(
            EventType.PLAN_CREATED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.PLAN_CREATED, step_count=step_count),
            progress_percent=0,
            total_steps=step_count,
            metadata={"step_count": step_count},
        )

    def start_step(
        self,
        step_id: str,
        step_number: int,
        description: str,
    ) -> None:
        """Emit step started event."""
        self.emitter.emit(
            EventType.STEP_STARTED,
            task_id=self._current_task_id or "",
            step_id=step_id,
            message=format_progress_message(
                EventType.STEP_STARTED,
                current=step_number,
                total=self._total_steps,
                description=description,
            ),
            current_step=step_number,
            total_steps=self._total_steps,
            progress_percent=self._calculate_progress(step_number - 1),
            metadata={"step_description": description},
        )

    def complete_step(
        self,
        step_id: str,
        step_number: int,
        description: str,
    ) -> None:
        """Emit step completed event."""
        self._completed_steps = step_number
        self.emitter.emit(
            EventType.STEP_COMPLETED,
            task_id=self._current_task_id or "",
            step_id=step_id,
            message=format_progress_message(
                EventType.STEP_COMPLETED,
                current=step_number,
                total=self._total_steps,
                description=description,
            ),
            current_step=step_number,
            total_steps=self._total_steps,
            progress_percent=self._calculate_progress(step_number),
            metadata={"step_description": description},
        )

    def fail_step(
        self,
        step_id: str,
        step_number: int,
        error: str,
    ) -> None:
        """Emit step failed event."""
        self.emitter.emit(
            EventType.STEP_FAILED,
            task_id=self._current_task_id or "",
            step_id=step_id,
            message=format_progress_message(
                EventType.STEP_FAILED,
                current=step_number,
                total=self._total_steps,
                error=error,
            ),
            severity=EventSeverity.ERROR,
            current_step=step_number,
            total_steps=self._total_steps,
            metadata={"error": error},
        )

    def retry_step(
        self,
        step_id: str,
        step_number: int,
        attempt: int,
        max_attempts: int,
    ) -> None:
        """Emit step retrying event."""
        self.emitter.emit(
            EventType.STEP_RETRYING,
            task_id=self._current_task_id or "",
            step_id=step_id,
            message=format_progress_message(
                EventType.STEP_RETRYING,
                current=step_number,
                total=self._total_steps,
                attempt=attempt,
                max=max_attempts,
            ),
            severity=EventSeverity.WARNING,
            metadata={"attempt": attempt, "max_attempts": max_attempts},
        )

    def invoke_agent(self, agent_name: str) -> None:
        """Emit agent invoked event."""
        self.emitter.emit(
            EventType.AGENT_INVOKED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.AGENT_INVOKED, agent_name=agent_name),
            metadata={"agent_name": agent_name},
        )

    def complete_agent(self, agent_name: str) -> None:
        """Emit agent completed event."""
        self.emitter.emit(
            EventType.AGENT_COMPLETED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.AGENT_COMPLETED, agent_name=agent_name),
            metadata={"agent_name": agent_name},
        )

    def fail_agent(self, agent_name: str, error: str) -> None:
        """Emit agent failed event."""
        self.emitter.emit(
            EventType.AGENT_FAILED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.AGENT_FAILED, agent_name=agent_name, error=error),
            severity=EventSeverity.ERROR,
            metadata={"agent_name": agent_name, "error": error},
        )

    def invoke_os_action(self, operation: str, target: str) -> None:
        """Emit OS action invoked event."""
        self.emitter.emit(
            EventType.OS_ACTION_INVOKED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.OS_ACTION_INVOKED, operation=operation, target=target),
            metadata={"operation": operation, "target": target},
        )

    def complete_os_action(self, operation: str, target: str) -> None:
        """Emit OS action completed event."""
        self.emitter.emit(
            EventType.OS_ACTION_COMPLETED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.OS_ACTION_COMPLETED, operation=operation, target=target),
            metadata={"operation": operation, "target": target},
        )

    def fail_os_action(self, operation: str, target: str, error: str) -> None:
        """Emit OS action failed event."""
        self.emitter.emit(
            EventType.OS_ACTION_FAILED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.OS_ACTION_FAILED, operation=operation, target=target, error=error),
            severity=EventSeverity.ERROR,
            metadata={"operation": operation, "target": target, "error": error},
        )

    def observing(self) -> None:
        """Emit observing event."""
        self.emitter.emit(
            EventType.OBSERVING,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.OBSERVING),
        )

    def verifying(self) -> None:
        """Emit verifying event."""
        self.emitter.emit(
            EventType.VERIFYING,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.VERIFYING),
        )

    def recovering(self, strategy: str) -> None:
        """Emit recovering event."""
        self.emitter.emit(
            EventType.RECOVERING,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.RECOVERING, strategy=strategy),
            severity=EventSeverity.WARNING,
            metadata={"strategy": strategy},
        )

    def replanning(self) -> None:
        """Emit replanning event."""
        self.emitter.emit(
            EventType.REPLANNING,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.REPLANNING),
            severity=EventSeverity.WARNING,
        )

    def waiting_for_dependency(self, dependency: str) -> None:
        """Emit waiting for dependency event."""
        self.emitter.emit(
            EventType.WAITING_FOR_DEPENDENCY,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.WAITING_FOR_DEPENDENCY, dependency=dependency),
            metadata={"dependency": dependency},
        )

    def confirmation_required(self, details: str) -> None:
        """Emit confirmation required event."""
        self.emitter.emit(
            EventType.CONFIRMATION_REQUIRED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.CONFIRMATION_REQUIRED, details=details),
            severity=EventSeverity.WARNING,
            metadata={"details": details},
        )

    def confirmation_received(self) -> None:
        """Emit confirmation received event."""
        self.emitter.emit(
            EventType.CONFIRMATION_RECEIVED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.CONFIRMATION_RECEIVED),
        )

    def update_progress(self, percent: float) -> None:
        """Emit progress update."""
        self.emitter.emit(
            EventType.PROGRESS_UPDATE,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.PROGRESS_UPDATE, percent=percent, current=self._completed_steps, total=self._total_steps),
            progress_percent=percent,
            current_step=self._completed_steps,
            total_steps=self._total_steps,
        )

    def complete_task(self) -> None:
        """Emit task completed event."""
        duration = 0
        if self._task_start_time:
            duration = (datetime.now() - self._task_start_time).total_seconds()

        self.emitter.emit(
            EventType.TASK_COMPLETED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.TASK_COMPLETED, duration=duration),
            progress_percent=100,
            current_step=self._total_steps,
            total_steps=self._total_steps,
            metadata={"duration_seconds": duration},
        )

    def fail_task(self, error: str) -> None:
        """Emit task failed event."""
        self.emitter.emit(
            EventType.TASK_FAILED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.TASK_FAILED, error=error),
            severity=EventSeverity.ERROR,
            metadata={"error": error},
        )

    def cancel_task(self) -> None:
        """Emit task cancelled event."""
        self.emitter.emit(
            EventType.TASK_CANCELLED,
            task_id=self._current_task_id or "",
            message=format_progress_message(EventType.TASK_CANCELLED),
            severity=EventSeverity.WARNING,
        )

    def _calculate_progress(self, step_number: int) -> float:
        """Calculate progress percentage."""
        if self._total_steps == 0:
            return 0.0
        return round((step_number / self._total_steps) * 100, 1)


# Global event emitter instance (optional, for simple usage)
_global_emitter = EventEmitter()


def get_global_emitter() -> EventEmitter:
    """Get the global event emitter."""
    return _global_emitter


def emit_progress(
    event_type: EventType,
    task_id: str,
    message: str = "",
    **kwargs,
) -> ProgressEvent:
    """Emit a progress event using the global emitter."""
    return _global_emitter.emit(event_type, task_id, message, **kwargs)