"""Genesis OS — AuthorizationGrant: the trusted adapter→executor channel.

THE PROBLEM THIS SOLVES
-----------------------
Authorization previously travelled as ``plan.parameters["confirmed"]``.
``parameters`` is deserialized from model-controlled JSON, so that
channel is model-reachable whether or not the field is declared in the
tool schema. A boolean there cannot carry authority.

THE CHANNEL
-----------
``AuthorizationGrant`` is a frozen record that can only be minted by
passing a REAL, argument-hash-bound, single-use approval through
``ApprovalStore.consume_token``. There is no other constructor: direct
instantiation raises, and the module-private mint token is not
exported.

This is STRUCTURAL un-forgeability, not a convention. A grant cannot be
fabricated from JSON because JSON cannot satisfy the mint precondition
— it would need an approval entry that a human actually approved and
that has not already been consumed. Everything else is forgeable by
definition.

The grant is bound to the SAME canonical argument hash ApprovalStore
already computes and that Phase 2 / Step 1b proved, so a grant for one
target does not authorise another.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

__all__ = [
    "AuthorizationError",
    "AuthorizationGrant",
    "issue_authorization_grant",
    "grant_is_valid_for",
    "grant_from_consumed_record",
    "TARGET_BEARING_ARGUMENT_KEYS",
]


# Argument names that denote the acted-upon target. Used by the
# executor to confirm a plan's own target was among the approved
# arguments, so a grant for one target cannot authorise another.
TARGET_BEARING_ARGUMENT_KEYS = (
    "path", "file_path", "folder", "directory", "target", "source",
    "destination", "output", "output_path", "save_path", "package",
    "ssid", "application", "selector",
)


class AuthorizationError(PermissionError):
    """Raised when a grant cannot be minted or does not authorise."""


# Module-private. Not exported, not returned by anything, and not
# derivable from input. Possession of this object is what separates
# trusted server code from a caller holding model-supplied JSON.
_MINT_TOKEN = object()


@dataclass(frozen=True)
class AuthorizationGrant:
    """Proof that a human approved THIS operation with THESE arguments.

    Immutable. Constructible only through
    :func:`issue_authorization_grant`, which itself requires a real
    consumed approval.
    """

    operation: str
    arguments_hash: str
    approval_id: str
    # Excluded from repr/compare so a leaked grant cannot be trivially
    # reconstructed from a log line or an assertion diff.
    _mint: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._mint is not _MINT_TOKEN:
            raise AuthorizationError(
                "AuthorizationGrant cannot be constructed directly. "
                "It is minted only by issue_authorization_grant(), which "
                "requires a real, consumed, argument-bound approval."
            )


def issue_authorization_grant(
    *,
    operation: str,
    arguments: Optional[Mapping[str, Any]] = None,
    token: Any,
) -> AuthorizationGrant:
    """Mint a grant by consuming a real approval token.

    This is the single entry point, and it delegates the whole
    authorisation decision to ``ApprovalStore.consume_token`` — the
    mechanism already proven by Phase 2's 8-attack battery and extended
    to every Tier 1 capability in Step 1b. Its consumption logic is NOT
    modified or duplicated here.

    Raises ``AuthorizationError`` when the token is invalid, pending,
    already consumed, or bound to different arguments.
    """
    from .approval_store import (
        ApprovalStore,
        _approval_arguments_hash,
    )

    if not isinstance(token, str) or not token.strip():
        raise AuthorizationError("an approval token is required")

    args = dict(arguments or {})
    try:
        record = ApprovalStore.consume_token(token, arguments=args)
    except (TypeError, ValueError) as error:
        raise AuthorizationError(str(error)) from error

    return AuthorizationGrant(
        operation=str(operation),
        arguments_hash=_approval_arguments_hash(str(operation), args),
        approval_id=str(record.get("approval_id", "")),
        _mint=_MINT_TOKEN,
    )


def grant_from_consumed_record(
    *,
    operation: str,
    arguments: Optional[Mapping[str, Any]] = None,
    record: Any,
) -> AuthorizationGrant:
    """Mint a grant from an ALREADY-CONSUMED approval record.

    Required because the token is single-use: the adapter's approval
    gate consumes it, so minting by consuming it a second time is
    correctly refused. This is the same consumption, not a new one --
    it performs no ApprovalStore write and cannot be used to consume a
    token twice.

    ``record`` must be the dict ApprovalStore.consume_token returned;
    anything else is refused.

    The record is BOUND to the capability and arguments the human
    actually approved, so the grant is minted only from the record's own
    ``capability_id`` and ``arguments_hash``. Re-hashing caller-supplied
    arguments without comparing them to the record would let a single
    approval for ``file.delete`` of one path be re-pointed at another
    path, or at a different operation entirely.
    """
    if not isinstance(record, dict):
        raise AuthorizationError(
            "a consumed ApprovalStore record is required"
        )
    status = str(record.get("status", ""))
    if status != "consumed":
        raise AuthorizationError(
            f"approval record is not consumed (status={status!r})"
        )

    approved_capability = record.get("capability_id")
    if str(approved_capability) != str(operation):
        raise AuthorizationError(
            f"the consumed approval is for {approved_capability!r}, not "
            f"{operation!r}; a grant may not be re-pointed at a different "
            f"capability"
        )

    args = dict(arguments or {})
    from .approval_store import _approval_arguments_hash

    approved_hash = record.get("arguments_hash")
    presented_hash = _approval_arguments_hash(str(operation), args)
    if approved_hash != presented_hash:
        raise AuthorizationError(
            "the consumed approval is bound to different arguments; a "
            "grant may not be re-pointed at a different target"
        )

    return AuthorizationGrant(
        operation=str(operation),
        arguments_hash=presented_hash,
        approval_id=str(record.get("approval_id", "")),
        _mint=_MINT_TOKEN,
    )


def grant_is_valid_for(
    grant: Optional[AuthorizationGrant],
    *,
    operation: str,
    arguments: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Whether ``grant`` authorises this exact operation+arguments.

    Re-derives the canonical hash and compares. A grant minted for a
    different target, or for a different operation, fails here.
    """
    if not isinstance(grant, AuthorizationGrant):
        return False
    if str(operation) != grant.operation:
        return False
    from .approval_store import _approval_arguments_hash

    try:
        expected = _approval_arguments_hash(
            str(operation), dict(arguments or {})
        )
    except Exception:
        return False
    return expected == grant.arguments_hash
