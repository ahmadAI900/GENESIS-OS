"""
Genesis OS
File Intelligence — Structured Result Contract

Level 3.3.1

This module defines the canonical result object used by the
File Intelligence subsystem.

Design principles:

    - deterministic
    - serializable
    - safe for user-facing messaging
    - explicit success/failure state
    - no exception leakage
    - future-ready for extraction/summarization
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class FileStatus:
    """
    Canonical filesystem operation statuses.

    These values are intentionally strings so they can be safely
    serialized and consumed by other Genesis subsystems.
    """

    OK = "ok"

    NOT_FOUND = "not_found"

    INVALID_PATH = "invalid_path"

    NOT_A_FILE = "not_a_file"

    NOT_A_DIRECTORY = "not_a_directory"

    PERMISSION_DENIED = "permission_denied"

    UNSAFE = "unsafe"

    NOT_SUPPORTED = "not_supported"

    UNKNOWN = "unknown"

    ERROR = "error"


@dataclass
class FileResult:
    """
    Canonical result of a File Intelligence operation.

    This object deliberately separates:

        success
        status
        operation
        identity
        metadata
        capabilities
        error
        evidence

    so higher layers never need to infer meaning from a
    message string.
    """

    success: bool

    status: str

    operation: str

    path: Optional[str] = None

    message: str = ""

    identity: Dict[str, Any] = field(
        default_factory=dict
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    capabilities: Dict[str, bool] = field(
        default_factory=dict
    )

    evidence: Dict[str, Any] = field(
        default_factory=dict
    )

    error: Optional[str] = None

    safety: Dict[str, Any] = field(
        default_factory=dict
    )

    version: str = "3.3.1"

    @classmethod
    def success_result(
        cls,
        operation: str,
        path: Optional[str] = None,
        message: str = "",
        identity: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        capabilities: Optional[Dict[str, bool]] = None,
        evidence: Optional[Dict[str, Any]] = None,
        safety: Optional[Dict[str, Any]] = None,
    ) -> "FileResult":
        """
        Construct a successful result.
        """

        return cls(
            success=True,
            status=FileStatus.OK,
            operation=operation,
            path=path,
            message=message,
            identity=identity or {},
            metadata=metadata or {},
            capabilities=capabilities or {},
            evidence=evidence or {},
            safety=safety or {},
        )

    @classmethod
    def failure_result(
        cls,
        operation: str,
        status: str,
        path: Optional[str] = None,
        message: str = "",
        error: Optional[str] = None,
        identity: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        capabilities: Optional[Dict[str, bool]] = None,
        evidence: Optional[Dict[str, Any]] = None,
        safety: Optional[Dict[str, Any]] = None,
    ) -> "FileResult":
        """
        Construct a failed result.

        Failure is represented explicitly rather than through
        exceptions crossing subsystem boundaries.
        """

        return cls(
            success=False,
            status=status,
            operation=operation,
            path=path,
            message=message,
            identity=identity or {},
            metadata=metadata or {},
            capabilities=capabilities or {},
            evidence=evidence or {},
            error=error,
            safety=safety or {},
        )

    @property
    def trustworthy_success(self) -> bool:
        """
        Whether Genesis can safely regard this result as successful.

        For the foundation layer, successful status is sufficient.

        Future versions can add verification requirements without
        changing the external result contract.
        """

        return (
            self.success
            and self.status == FileStatus.OK
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the result into a JSON-safe dictionary.
        """

        return {
            "success": self.success,
            "status": self.status,
            "operation": self.operation,
            "path": self.path,
            "message": self.message,
            "identity": dict(self.identity),
            "metadata": dict(self.metadata),
            "capabilities": dict(
                self.capabilities
            ),
            "evidence": dict(self.evidence),
            "error": self.error,
            "safety": dict(self.safety),
            "trustworthy_success": (
                self.trustworthy_success
            ),
            "version": self.version,
        }

    def explain(self) -> Dict[str, Any]:
        """
        Return a human-readable structured explanation.

        This prepares the file layer for Genesis's future
        Explainable Trust Layer.
        """

        return {
            "operation": self.operation,
            "path": self.path,
            "success": self.success,
            "status": self.status,
            "trustworthy_success": (
                self.trustworthy_success
            ),
            "message": self.message,
            "identity": dict(self.identity),
            "metadata": dict(self.metadata),
            "capabilities": dict(
                self.capabilities
            ),
            "safety": dict(self.safety),
            "error": self.error,
        }

    def user_message(self) -> str:
        """
        Produce a safe user-facing message.

        This method intentionally avoids exposing internal
        exception traces or implementation details.
        """

        if self.message:
            return self.message

        if self.success:
            return (
                f"{self.operation} completed successfully."
            )

        if self.status == FileStatus.NOT_FOUND:
            return (
                "Genesis could not find the requested file."
            )

        if self.status == FileStatus.PERMISSION_DENIED:
            return (
                "Genesis does not have permission to access "
                "the requested file."
            )

        if self.status == FileStatus.NOT_SUPPORTED:
            return (
                "Genesis does not currently support this "
                "file operation."
            )

        if self.status == FileStatus.UNSAFE:
            return (
                "Genesis blocked this file operation because "
                "it was considered unsafe."
            )

        return (
            "Genesis could not complete the file operation."
        )