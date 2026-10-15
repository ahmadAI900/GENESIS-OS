"""
Genesis OS
Core Result Contract

Task:
    21.1 — Reliability Foundation

Purpose:
    Provide a standardized result object for Genesis
    subsystems.

Design principle:

    Success and failure are both valid results.

    A subsystem should not need to crash the entire
    Genesis runtime merely because its operation failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class GenesisResult:
    """
    Standard result returned by Genesis subsystems.

    Examples:

        successful operation
        ---------------------
        GenesisResult.ok(
            data={"answer": "hello"}
        )

        failed operation
        -----------------
        GenesisResult.fail(
            error="Memory unavailable"
        )
    """

    success: bool

    data: Any = None

    error: Optional[str] = None

    code: Optional[str] = None

    source: Optional[str] = None

    recoverable: bool = True

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    # =====================================================
    # FACTORY — SUCCESS
    # =====================================================

    @classmethod
    def ok(
        cls,
        data: Any = None,
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "GenesisResult":

        return cls(
            success=True,
            data=data,
            error=None,
            code=None,
            source=source,
            recoverable=False,
            metadata=metadata or {},
        )

    # =====================================================
    # FACTORY — FAILURE
    # =====================================================

    @classmethod
    def fail(
        cls,
        error: str,
        code: Optional[str] = None,
        source: Optional[str] = None,
        recoverable: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "GenesisResult":

        return cls(
            success=False,
            data=None,
            error=str(error),
            code=code,
            source=source,
            recoverable=recoverable,
            metadata=metadata or {},
        )

    # =====================================================
    # BOOLEAN
    # =====================================================

    def __bool__(self) -> bool:
        return self.success

    # =====================================================
    # SERIALIZATION
    # =====================================================

    def to_dict(self) -> Dict[str, Any]:

        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "code": self.code,
            "source": self.source,
            "recoverable": self.recoverable,
            "metadata": self.metadata,
        }

    # =====================================================
    # HUMAN DESCRIPTION
    # =====================================================

    def describe(self) -> str:

        if self.success:

            return "Operation completed successfully."

        if self.error:

            return self.error

        return "Operation failed."