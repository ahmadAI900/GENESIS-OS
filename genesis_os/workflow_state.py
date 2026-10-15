"""
Genesis OS — Level 3.8.5
Workflow Runtime State.

Tracks workflow-level and step-level state independently
from ActionPlan and ActionResult.

This distinction allows Genesis to represent:

    planned
    running
    succeeded
    verified
    failed
    blocked
    clarification_required
    verification_failed

without corrupting the underlying plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Any, Dict, Optional


class WorkflowRuntimeStatus(
    str,
    Enum,
):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_FOR_USER = (
        "waiting_for_user"
    )
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = (
        "partially_completed"
    )
    FAILED = "failed"
    BLOCKED = "blocked"


class StepRuntimeStatus(
    str,
    Enum,
):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    VERIFIED = "verified"
    ALREADY_SATISFIED = (
        "already_satisfied"
    )
    FAILED = "failed"
    VERIFICATION_FAILED = (
        "verification_failed"
    )
    BLOCKED = "blocked"
    WAITING_FOR_USER = (
        "waiting_for_user"
    )
    SKIPPED = "skipped"


@dataclass(frozen=True)
class StepState:
    step_id: str

    status: StepRuntimeStatus = (
        StepRuntimeStatus.PENDING
    )

    attempts: int = 0

    started_at: Optional[str] = None

    completed_at: Optional[str] = None

    error: Optional[str] = None

    verification: Optional[Any] = None

    evidence: Optional[Any] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class WorkflowStateSnapshot:
    workflow_id: str

    version: int

    status: WorkflowRuntimeStatus

    steps: Dict[
        str,
        StepState,
    ]

    active_step_id: Optional[str]

    updated_at: str

    reason: str


class WorkflowStateStore:
    """
    Thread-safe versioned workflow state store.

    State transitions are explicit.

    A step cannot silently jump from PENDING to VERIFIED.
    """

    VERSION = "3.8.5"

    def __init__(
        self,
        workflow_id: str,
    ) -> None:

        if not workflow_id.strip():
            raise ValueError(
                "workflow_id cannot be empty."
            )

        self.workflow_id = workflow_id

        self._lock = RLock()

        self._version = 0

        self._status = (
            WorkflowRuntimeStatus.CREATED
        )

        self._active_step_id = None

        self._steps: Dict[
            str,
            StepState,
        ] = {}

        self._history: list[
            WorkflowStateSnapshot
        ] = []

        self._snapshot(
            reason="initial"
        )

    # =========================================================
    # STEP REGISTRATION
    # =========================================================

    def register_step(
        self,
        step_id: str,
    ) -> None:

        with self._lock:

            if step_id in self._steps:
                return

            self._steps[
                step_id
            ] = StepState(
                step_id=step_id
            )

            self._snapshot(
                reason=f"register:{step_id}"
            )

    # =========================================================
    # WORKFLOW STATE
    # =========================================================

    @property
    def status(
        self,
    ) -> WorkflowRuntimeStatus:

        with self._lock:
            return self._status

    @property
    def version(self) -> int:

        with self._lock:
            return self._version

    @property
    def active_step_id(
        self,
    ) -> Optional[str]:

        with self._lock:
            return self._active_step_id

    def set_status(
        self,
        status: WorkflowRuntimeStatus,
        *,
        reason: str,
    ) -> WorkflowStateSnapshot:

        with self._lock:

            self._status = status

            return self._snapshot(
                reason=reason
            )

    # =========================================================
    # STEP TRANSITIONS
    # =========================================================

    def transition_step(
        self,
        step_id: str,
        status: StepRuntimeStatus,
        *,
        error: Optional[str] = None,
        verification: Optional[Any] = None,
        evidence: Optional[Any] = None,
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> WorkflowStateSnapshot:

        with self._lock:

            if step_id not in self._steps:
                raise KeyError(
                    f"Unknown workflow step: "
                    f"{step_id}"
                )

            previous = self._steps[
                step_id
            ]

            now = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )

            started_at = (
                previous.started_at
            )

            completed_at = (
                previous.completed_at
            )

            attempts = (
                previous.attempts
            )

            if status == (
                StepRuntimeStatus.RUNNING
            ):

                if started_at is None:
                    started_at = now

                attempts += 1

                self._active_step_id = (
                    step_id
                )

            if status in {
                StepRuntimeStatus.SUCCEEDED,
                StepRuntimeStatus.VERIFIED,
                StepRuntimeStatus.FAILED,
                StepRuntimeStatus.VERIFICATION_FAILED,
                StepRuntimeStatus.BLOCKED,
                StepRuntimeStatus.SKIPPED,
                StepRuntimeStatus.ALREADY_SATISFIED,
            }:

                completed_at = now

                if (
                    self._active_step_id
                    == step_id
                ):
                    self._active_step_id = None

            self._steps[
                step_id
            ] = StepState(
                step_id=step_id,
                status=status,
                attempts=attempts,
                started_at=started_at,
                completed_at=completed_at,
                error=error,
                verification=verification,
                evidence=evidence,
                metadata={
                    **previous.metadata,
                    **(
                        metadata or {}
                    ),
                },
            )

            return self._snapshot(
                reason=(
                    f"step:{step_id}:"
                    f"{status.value}"
                )
            )

    # =========================================================
    # READ
    # =========================================================

    def get_step(
        self,
        step_id: str,
    ) -> StepState:

        with self._lock:

            if step_id not in self._steps:
                raise KeyError(
                    f"Unknown workflow step: "
                    f"{step_id}"
                )

            return self._steps[
                step_id
            ]

    def snapshot(
        self,
    ) -> WorkflowStateSnapshot:

        with self._lock:

            return self._snapshot(
                reason="manual"
            )

    def history(
        self,
    ) -> tuple[
        WorkflowStateSnapshot,
        ...
    ]:

        with self._lock:
            return tuple(
                self._history
            )

    # =========================================================
    # INTERNAL
    # =========================================================

    def _snapshot(
        self,
        *,
        reason: str,
    ) -> WorkflowStateSnapshot:

        self._version += 1

        snapshot = WorkflowStateSnapshot(
            workflow_id=self.workflow_id,
            version=self._version,
            status=self._status,
            steps=dict(
                self._steps
            ),
            active_step_id=(
                self._active_step_id
            ),
            updated_at=(
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            reason=reason,
        )

        self._history.append(
            snapshot
        )

        return snapshot