"""
Genesis OS — Level 3.8.5
ActionResult → WorkflowContext propagation.

The propagator converts execution results into structured
workflow knowledge.

It does not execute anything.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .workflow_context import (
    WorkflowContext,
)


class WorkflowContextPropagator:
    """
    Converts ActionResult information into workflow context.

    The propagator is intentionally conservative.

    It stores the result itself and common structured fields,
    while preserving the original result as evidence.
    """

    VERSION = "3.8.5"

    def __init__(
        self,
        context: WorkflowContext,
    ) -> None:

        self.context = context

    def propagate(
        self,
        *,
        step_id: str,
        action_result: Any,
    ) -> None:

        if not step_id.strip():
            raise ValueError(
                "step_id cannot be empty."
            )

        serialized = self._serialize_result(
            action_result
        )

        # -----------------------------------------------------
        # Canonical step result
        # -----------------------------------------------------

        self.context.set_step_output(
            step_id,
            "result",
            serialized,
            source="action_result",
            evidence=serialized,
        )

        # -----------------------------------------------------
        # Common result fields
        # -----------------------------------------------------

        for field_name in (
            "success",
            "status",
            "message",
            "error",
            "data",
            "output",
            "value",
            "path",
            "target",
            "verification",
            "evidence",
        ):

            value = self._get_field(
                action_result,
                field_name,
            )

            if value is None:
                continue

            self.context.set_step_output(
                step_id,
                field_name,
                value,
                source="action_result",
                evidence=serialized,
            )

    # =========================================================
    # SERIALIZATION
    # =========================================================

    @staticmethod
    def _serialize_result(
        result: Any,
    ) -> Any:

        if result is None:
            return None

        to_dict = getattr(
            result,
            "to_dict",
            None,
        )

        if callable(to_dict):

            try:
                return to_dict()
            except Exception:
                pass

        if isinstance(
            result,
            dict,
        ):
            return dict(result)

        if hasattr(
            result,
            "__dict__",
        ):

            try:
                return dict(
                    result.__dict__
                )
            except Exception:
                pass

        return result

    @staticmethod
    def _get_field(
        result: Any,
        field_name: str,
    ) -> Optional[Any]:

        if isinstance(
            result,
            dict,
        ):
            return result.get(
                field_name
            )

        return getattr(
            result,
            field_name,
            None,
        )