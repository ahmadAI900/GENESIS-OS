"""
Genesis OS — Level 3.8.5
Workflow Context, State & Data Propagation.

This module provides the shared state model for multi-step
desktop workflows.

Core distinction:

    Context
        What information is available to the workflow.

    State
        What state the workflow currently believes it is in.

    Evidence
        What produced that information.

    Binding
        How one step consumes information produced by another.

This module does not execute OS operations.

It is deliberately independent from ActionExecutor so that
workflow intelligence and computer control remain separate.

Architecture:

    ActionResult
        ↓
    Context Update
        ↓
    WorkflowContext
        ↓
    DataBinding
        ↓
    Next ActionPlan
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, Iterable, Mapping, Optional
import copy


class WorkflowContextError(RuntimeError):
    """Base error for workflow-context operations."""


class ContextKeyError(WorkflowContextError):
    """Raised when a requested context value does not exist."""


class ContextVersionError(WorkflowContextError):
    """Raised when an invalid context version is requested."""


@dataclass(frozen=True)
class ContextValue:
    """
    A value stored in workflow context.

    Every value has provenance.

    Genesis should eventually be able to answer:

        "Why does Genesis think this is the current file?"

    The answer is represented by source/evidence metadata.
    """

    key: str

    value: Any

    source: str

    step_id: Optional[str] = None

    confidence: float = 1.0

    evidence: Optional[Any] = None

    created_at: str = field(
        default_factory=lambda: (
            datetime.now(timezone.utc).isoformat()
        )
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:

        if not self.key.strip():
            raise ValueError(
                "ContextValue.key cannot be empty."
            )

        if not self.source.strip():
            raise ValueError(
                "ContextValue.source cannot be empty."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "ContextValue.confidence must be "
                "between 0 and 1."
            )

    def to_dict(self) -> Dict[str, Any]:

        return {
            "key": self.key,
            "value": copy.deepcopy(self.value),
            "source": self.source,
            "step_id": self.step_id,
            "confidence": self.confidence,
            "evidence": copy.deepcopy(
                self.evidence
            ),
            "created_at": self.created_at,
            "metadata": copy.deepcopy(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class ContextSnapshot:
    """
    Immutable snapshot of workflow context.

    Snapshots make debugging and recovery possible.

    A future recovery engine can compare:

        snapshot N
        snapshot N+1

    to determine exactly what changed.
    """

    version: int

    values: Mapping[
        str,
        ContextValue,
    ]

    created_at: str = field(
        default_factory=lambda: (
            datetime.now(timezone.utc).isoformat()
        )
    )

    reason: str = "update"

    def get(
        self,
        key: str,
    ) -> Any:

        item = self.values.get(key)

        if item is None:
            raise ContextKeyError(
                f"Context key not found: {key}"
            )

        return copy.deepcopy(
            item.value
        )

    def get_entry(
        self,
        key: str,
    ) -> ContextValue:

        item = self.values.get(key)

        if item is None:
            raise ContextKeyError(
                f"Context key not found: {key}"
            )

        return item

    def has(
        self,
        key: str,
    ) -> bool:

        return key in self.values

    def to_dict(self) -> Dict[str, Any]:

        return {
            "version": self.version,
            "created_at": self.created_at,
            "reason": self.reason,
            "values": {
                key: value.to_dict()
                for key, value in self.values.items()
            },
        }


class WorkflowContext:
    """
    Thread-safe workflow context store.

    Important properties:

    - versioned
    - provenance-aware
    - snapshot-capable
    - deterministic
    - no arbitrary expression execution
    - supports step-scoped values
    - supports workflow-global values
    """

    VERSION = "3.8.5"

    GLOBAL_SCOPE = "workflow"

    def __init__(
        self,
        *,
        workflow_id: str = "",
    ) -> None:

        self.workflow_id = workflow_id

        self._lock = RLock()

        self._values: Dict[
            str,
            ContextValue,
        ] = {}

        self._version = 0

        self._snapshots: list[
            ContextSnapshot
        ] = []

        self._record_snapshot(
            reason="initial"
        )

    # =========================================================
    # WRITE
    # =========================================================

    def set(
        self,
        key: str,
        value: Any,
        *,
        source: str,
        step_id: Optional[str] = None,
        confidence: float = 1.0,
        evidence: Optional[Any] = None,
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> ContextSnapshot:

        entry = ContextValue(
            key=key,
            value=copy.deepcopy(value),
            source=source,
            step_id=step_id,
            confidence=confidence,
            evidence=copy.deepcopy(
                evidence
            ),
            metadata=copy.deepcopy(
                metadata or {}
            ),
        )

        with self._lock:

            self._values[key] = entry

            return self._record_snapshot(
                reason=f"set:{key}"
            )

    def set_many(
        self,
        values: Iterable[
            ContextValue
        ],
        *,
        reason: str = "batch_update",
    ) -> ContextSnapshot:

        with self._lock:

            for entry in values:

                if not isinstance(
                    entry,
                    ContextValue,
                ):
                    raise TypeError(
                        "set_many() accepts "
                        "ContextValue objects."
                    )

                self._values[
                    entry.key
                ] = entry

            return self._record_snapshot(
                reason=reason
            )

    # =========================================================
    # READ
    # =========================================================

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:

        with self._lock:

            item = self._values.get(
                key
            )

            if item is None:
                return default

            return copy.deepcopy(
                item.value
            )

    def require(
        self,
        key: str,
    ) -> Any:

        with self._lock:

            item = self._values.get(
                key
            )

            if item is None:
                raise ContextKeyError(
                    f"Required context key "
                    f"not found: {key}"
                )

            return copy.deepcopy(
                item.value
            )

    def get_entry(
        self,
        key: str,
    ) -> Optional[
        ContextValue
    ]:

        with self._lock:

            item = self._values.get(
                key
            )

            return (
                copy.deepcopy(item)
                if item is not None
                else None
            )

    def has(
        self,
        key: str,
    ) -> bool:

        with self._lock:
            return key in self._values

    # =========================================================
    # STEP-SCOPED CONTEXT
    # =========================================================

    def set_step_output(
        self,
        step_id: str,
        name: str,
        value: Any,
        *,
        source: str = "action_result",
        confidence: float = 1.0,
        evidence: Optional[Any] = None,
        metadata: Optional[
            Dict[str, Any]
        ] = None,
    ) -> ContextSnapshot:

        if not step_id.strip():
            raise ValueError(
                "step_id cannot be empty."
            )

        if not name.strip():
            raise ValueError(
                "output name cannot be empty."
            )

        key = (
            f"steps.{step_id}.outputs.{name}"
        )

        return self.set(
            key,
            value,
            source=source,
            step_id=step_id,
            confidence=confidence,
            evidence=evidence,
            metadata=metadata,
        )

    def get_step_output(
        self,
        step_id: str,
        name: str,
    ) -> Any:

        return self.require(
            f"steps.{step_id}.outputs.{name}"
        )

    def set_step_state(
        self,
        step_id: str,
        state: Any,
        *,
        source: str = "workflow_runtime",
        evidence: Optional[Any] = None,
    ) -> ContextSnapshot:

        return self.set(
            f"steps.{step_id}.state",
            state,
            source=source,
            step_id=step_id,
            evidence=evidence,
        )

    # =========================================================
    # TARGET STATE
    # =========================================================

    def set_resolved_target(
        self,
        step_id: str,
        target: Any,
        *,
        confidence: float = 1.0,
        evidence: Optional[Any] = None,
    ) -> ContextSnapshot:

        return self.set(
            f"steps.{step_id}.resolved_target",
            target,
            source="target_resolution",
            step_id=step_id,
            confidence=confidence,
            evidence=evidence,
        )

    # =========================================================
    # SNAPSHOTS
    # =========================================================

    def snapshot(self) -> ContextSnapshot:

        with self._lock:

            return ContextSnapshot(
                version=self._version,
                values=copy.deepcopy(
                    self._values
                ),
                reason="manual",
            )

    def snapshot_at(
        self,
        version: int,
    ) -> ContextSnapshot:

        with self._lock:

            if version < 0:
                raise ContextVersionError(
                    "Context version cannot be negative."
                )

            for snapshot in reversed(
                self._snapshots
            ):

                if (
                    snapshot.version
                    == version
                ):
                    return copy.deepcopy(
                        snapshot
                    )

        raise ContextVersionError(
            f"Context snapshot {version} "
            "does not exist."
        )

    @property
    def version(self) -> int:

        with self._lock:
            return self._version

    # =========================================================
    # SERIALIZATION
    # =========================================================

    def to_dict(self) -> Dict[str, Any]:

        return self.snapshot().to_dict()

    # =========================================================
    # INTERNAL
    # =========================================================

    def _record_snapshot(
        self,
        *,
        reason: str,
    ) -> ContextSnapshot:

        self._version += 1

        snapshot = ContextSnapshot(
            version=self._version,
            values=copy.deepcopy(
                self._values
            ),
            reason=reason,
        )

        self._snapshots.append(
            snapshot
        )

        return snapshot