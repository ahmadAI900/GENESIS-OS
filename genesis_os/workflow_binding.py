"""
Genesis OS — Level 3.8.5
Workflow Data Binding Engine.

Provides safe, deterministic references between workflow steps.

Supported reference:

    ${context.key}

    ${steps.step-1.outputs.file}

    ${steps.step-2.state}

No arbitrary expressions are evaluated.

This module never executes commands.
"""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Any, Dict, Mapping

from .workflow_context import (
    ContextKeyError,
    WorkflowContext,
)


class DataBindingError(RuntimeError):
    """Base data-binding error."""


class UnresolvedBindingError(
    DataBindingError
):
    """Raised when a binding cannot be resolved."""


class InvalidBindingError(
    DataBindingError
):
    """Raised when a binding has invalid syntax."""


class WorkflowDataBinder:
    """
    Safe context-reference resolver.

    Only explicit Genesis context paths are accepted.
    """

    VERSION = "3.8.5"

    _REFERENCE_PATTERN = re.compile(
        r"\$\{([a-zA-Z0-9_.-]+)\}"
    )

    _FULL_REFERENCE_PATTERN = re.compile(
        r"^\$\{([a-zA-Z0-9_.-]+)\}$"
    )

    def __init__(
        self,
        context: WorkflowContext,
    ) -> None:

        self.context = context

    # =========================================================
    # PUBLIC
    # =========================================================

    def resolve(
        self,
        value: Any,
    ) -> Any:
        """
        Resolve bindings recursively.

        Supported:

            string
            dict
            list
            tuple

        Other values are returned unchanged.
        """

        if isinstance(
            value,
            str,
        ):
            return self._resolve_string(
                value
            )

        if isinstance(
            value,
            dict,
        ):
            return {
                key: self.resolve(item)
                for key, item in value.items()
            }

        if isinstance(
            value,
            list,
        ):
            return [
                self.resolve(item)
                for item in value
            ]

        if isinstance(
            value,
            tuple,
        ):
            return tuple(
                self.resolve(item)
                for item in value
            )

        return value

    def resolve_reference(
        self,
        reference: str,
    ) -> Any:

        match = (
            self._FULL_REFERENCE_PATTERN
            .match(reference)
        )

        if not match:
            raise InvalidBindingError(
                f"Invalid context reference: "
                f"{reference}"
            )

        path = match.group(1)

        return self._lookup_path(
            path
        )

    # =========================================================
    # ACTION PLAN SUPPORT
    # =========================================================

    def bind_action_plan(
        self,
        action_plan,
    ):
        """
        Return a new ActionPlan with all supported
        context references resolved.

        The original ActionPlan remains unchanged.
        """

        return replace(
            action_plan,
            target=self.resolve(
                action_plan.target
            ),
            application=self.resolve(
                action_plan.application
            ),
            parameters=self.resolve(
                action_plan.parameters
            ),
        )

    # =========================================================
    # INTERNAL
    # =========================================================

    def _resolve_string(
        self,
        value: str,
    ) -> Any:

        full_match = (
            self._FULL_REFERENCE_PATTERN
            .match(value)
        )

        # If the entire string is a reference,
        # preserve the original data type.
        #
        # Example:
        #
        # ${steps.step-1.outputs.count}
        #
        # remains int rather than becoming "42".
        if full_match:

            return self._lookup_path(
                full_match.group(1)
            )

        matches = list(
            self._REFERENCE_PATTERN.finditer(
                value
            )
        )

        if not matches:
            return value

        result = value

        for match in reversed(
            matches
        ):

            path = match.group(1)

            resolved = self._lookup_path(
                path
            )

            if isinstance(
                resolved,
                (dict, list, tuple),
            ):

                raise InvalidBindingError(
                    "Complex objects cannot be "
                    "embedded inside a string. "
                    f"Use a full reference instead: "
                    f"${{{path}}}"
                )

            replacement = str(
                resolved
            )

            result = (
                result[
                    :match.start()
                ]
                + replacement
                + result[
                    match.end():
                ]
            )

        return result

    def _lookup_path(
        self,
        path: str,
    ) -> Any:

        if path.startswith(
            "context."
        ):

            key = path[
                len("context.") :
            ]

            if not key:
                raise InvalidBindingError(
                    "Empty context reference."
                )

            return self.context.require(
                key
            )

        if path.startswith(
            "steps."
        ):

            if not self.context.has(
                path
            ):
                raise UnresolvedBindingError(
                    f"Workflow binding could not "
                    f"be resolved: ${{{path}}}"
                )

            return self.context.require(
                path
            )

        raise InvalidBindingError(
            "Unsupported binding namespace: "
            f"{path}"
        )
    def validate_bound_plan(
        self,
        action_plan,
    ):
        """
    Resolve context references and then validate the
    resulting ActionPlan.

    This ensures a binding cannot silently produce an
    invalid action.
        """

        bound = self.bind_action_plan(
            action_plan
        )

        bound.validate()

        return bound