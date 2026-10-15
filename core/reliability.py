"""
Genesis OS
Reliability Utilities

Task:
    21.3 — Reliability Foundation

Purpose:
    Convert unexpected subsystem exceptions into
    controlled GenesisResult objects.

This module does NOT hide programming bugs silently.

It records the failure source and produces a controlled
failure result.
"""

from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, Optional

from .result import GenesisResult


class ReliabilityGuard:
    """
    Central safety boundary for Genesis subsystem calls.
    """

    VERSION = "1.0"

    # =====================================================
    # SAFE CALL
    # =====================================================

    @staticmethod
    def call(
        operation: Callable[..., Any],
        *args: Any,
        source: Optional[str] = None,
        default: Any = None,
        **kwargs: Any,
    ) -> GenesisResult:
        """
        Execute an operation safely.

        Any unexpected exception becomes a controlled
        GenesisResult failure.
        """

        try:

            result = operation(
                *args,
                **kwargs,
            )

            return GenesisResult.ok(
                data=result,
                source=source,
            )

        except Exception as exc:

            return GenesisResult.fail(
                error=str(exc),
                code="UNEXPECTED_ERROR",
                source=source,
                recoverable=True,
                metadata={
                    "exception_type": type(
                        exc
                    ).__name__,
                    "traceback": traceback.format_exc(),
                    "default": default,
                },
            )

    # =====================================================
    # SAFE VALUE
    # =====================================================

    @staticmethod
    def safe_value(
        value: Any,
        default: Any = None,
    ) -> Any:
        """
        Convert None into a safe default when appropriate.
        """

        if value is None:

            return default

        return value

    # =====================================================
    # SAFE STRING
    # =====================================================

    @staticmethod
    def safe_string(
        value: Any,
        default: str = "",
    ) -> str:
        """
        Guarantee a string value.
        """

        if value is None:

            return default

        return str(value)

    # =====================================================
    # SAFE DICT
    # =====================================================

    @staticmethod
    def safe_dict(
        value: Any,
    ) -> Dict[str, Any]:
        """
        Guarantee a dictionary.
        """

        if isinstance(
            value,
            dict,
        ):

            return value

        return {}