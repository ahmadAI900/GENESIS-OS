"""
Genesis OS — Level 3.8.4 Target Resolution.

Converts:

    TargetQuery
        +
    TargetCandidate[]

into:

    ResolvedTarget

or an explicit clarification requirement.

The resolver never silently chooses a weak or ambiguous target.
"""

from __future__ import annotations

from typing import Iterable, Optional

from .target_models import (
    TargetCandidate,
    TargetQuery,
    TargetResolutionResult,
    ResolvedTarget,
)


class TargetResolutionError(RuntimeError):
    """Raised for invalid target resolution operations."""


class TargetResolver:
    """
    Deterministic target resolver.

    Resolution is confidence-based and conservative.

    Default policy:

        >= 0.85
            automatically resolvable

        0.60–0.849
            ambiguous / clarification

        < 0.60
            unresolved
    """

    VERSION = "3.8.4"

    AUTO_RESOLVE_THRESHOLD = 0.85

    AMBIGUITY_MARGIN = 0.10

    def resolve(
        self,
        query: TargetQuery,
        candidates: Iterable[
            TargetCandidate
        ],
    ) -> TargetResolutionResult:

        if not isinstance(
            query,
            TargetQuery,
        ):
            raise TypeError(
                "resolve() requires TargetQuery."
            )

        normalized = tuple(
            candidates
        )

        if not normalized:

            return TargetResolutionResult(
                query=query,
                candidates=(),
                resolved=None,
                requires_clarification=True,
                clarification_reason=(
                    "No matching target was found."
                ),
                metadata={
                    "version": self.VERSION,
                    "resolution": "not_found",
                },
            )

        ranked = sorted(
            normalized,
            key=lambda candidate: (
                candidate.confidence,
            ),
            reverse=True,
        )

        best = ranked[0]

        if best.confidence < (
            self.AUTO_RESOLVE_THRESHOLD
        ):

            return TargetResolutionResult(
                query=query,
                candidates=tuple(
                    ranked
                ),
                resolved=None,
                requires_clarification=True,
                clarification_reason=(
                    "No candidate has sufficient "
                    "confidence for automatic "
                    "resolution."
                ),
                metadata={
                    "version": self.VERSION,
                    "resolution": "low_confidence",
                },
            )

        if len(ranked) > 1:

            second = ranked[1]

            if (
                best.confidence
                - second.confidence
                < self.AMBIGUITY_MARGIN
            ):

                return TargetResolutionResult(
                    query=query,
                    candidates=tuple(
                        ranked
                    ),
                    resolved=None,
                    requires_clarification=True,
                    clarification_reason=(
                        "Multiple targets have "
                        "similar confidence and "
                        "the target is ambiguous."
                    ),
                    metadata={
                        "version": self.VERSION,
                        "resolution": "ambiguous",
                    },
                )

        resolved = ResolvedTarget(
            query=query,
            candidate=best,
            confidence=best.confidence,
            resolution_method=(
                "confidence_ranked"
            ),
            metadata={
                "version": self.VERSION,
                "candidate_count": len(
                    ranked
                ),
            },
        )

        return TargetResolutionResult(
            query=query,
            candidates=tuple(
                ranked
            ),
            resolved=resolved,
            requires_clarification=False,
            clarification_reason=None,
            metadata={
                "version": self.VERSION,
                "resolution": "resolved",
            },
        )