"""Genesis OS — RuntimeResolutionRecord: the trusted anaphoric waiver.

THE PROBLEM THIS SOLVES (Item 20B, S15)
----------------------------------------
``ActionPlan``'s conditional-target validator used to waive the
target requirement whenever ``parameters`` carried
``requires_runtime_resolution`` / ``source_is_anaphoric`` /
``anaphoric_target``. ``parameters`` is deserialized from
model-controlled JSON, so a model-supplied flag could construct a
targetless plan for an operation whose contract REQUIRES a target
(``file.delete`` with no path, for example). The model decided
whether a safety invariant applied to itself.

THE CHANNEL
-----------
``RuntimeResolutionRecord`` is a frozen record that can only be
minted by trusted server code deciding to say "this plan's target is
pending runtime entity-binder resolution". There is no constructor:
direct instantiation raises, and the module-private mint token is
not exported. ActionPlan refuses any JSON-shaped value for the field,
mirroring the ``AuthorizationGrant`` guard -- JSON cannot satisfy
the mint precondition.

What minting means: trusted code (``ActionPlan.from_decision``)
recognised a DETERMINISTIC-origin anaphoric reference in the user's
own words and built a structurally-valid plan whose target the
runtime binder will fill in. Model-origin decisions (the LLM
resolver, marked with ``_semantic_resolution``) never mint: their
targetless plans are refused outright.

The record is bound to the operation, so a waiver minted for one
operation cannot be replayed on another.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "RuntimeResolutionError",
    "RuntimeResolutionRecord",
    "issue_runtime_resolution_record",
]


class RuntimeResolutionError(ValueError):
    """Raised when a record cannot be minted or is presented invalidly."""


# Module-private. Not exported, not returned by anything, and not
# derivable from input. Possession of this object is what separates
# trusted server code from a caller holding model-supplied JSON.
_MINT_TOKEN = object()


@dataclass(frozen=True)
class RuntimeResolutionRecord:
    """Proof that TRUSTED code, not a model flag, waived the target.

    Immutable. Constructible only through
    :func:`issue_runtime_resolution_record`.
    """

    operation: str
    # Excluded from repr/compare so an assertion diff or log line
    # cannot trivially hand the record's shape to a forger.
    _mint: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._mint is not _MINT_TOKEN:
            raise RuntimeResolutionError(
                "RuntimeResolutionRecord cannot be constructed "
                "directly. It is minted only by "
                "issue_runtime_resolution_record() when trusted "
                "code recognises a deterministic-origin anaphoric "
                "reference; model-supplied JSON can never produce "
                "one."
            )


def issue_runtime_resolution_record(*, operation: str) -> RuntimeResolutionRecord:
    """Mint a target-waiver record. Trusted code paths only.

    The precondition is judgment, not an external artifact: the
    caller must be deterministic-origin code that has established
    the plan's targetless shape is a genuine pending-resolution
    reference (see ``ActionPlan.from_decision``, the single
    production caller). Because the record itself cannot be built
    from JSON and ActionPlan refuses JSON-shaped values for the
    field, a model cannot reach this waiver however its payload is
    spelled.

    Raises ``RuntimeResolutionError`` for an empty operation.
    """
    if not isinstance(operation, str) or not operation.strip():
        raise RuntimeResolutionError(
            "a non-empty operation is required to mint a "
            "runtime-resolution record"
        )
    return RuntimeResolutionRecord(
        operation=operation,
        _mint=_MINT_TOKEN,
    )
