"""
Genesis OS â€” Execution Safety

LEVEL 3.6
---------

Central execution-safety boundary.

Responsibilities:

    - validate operation identity
    - consult CapabilityRegistry
    - enforce contract-validated policy denials (Policy)
    - reject unknown capabilities
    - reject disabled capabilities
    - expose dangerous capability metadata to the execution confirmation gate
    - return deterministic SafetyDecision objects
    - perform NO operating-system execution

Architecture:

    ActionPlan
        â†“
    CapabilityRegistry
        â†“
    ExecutionSafety
        â†“
    ActionExecutor
        â†“
    OSManager
        â†“
    Verification
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from genesis_os.capability_registry import (
    CapabilityRegistry,
)


@dataclass(frozen=True)
class SafetyDecision:
    """
    Immutable result of a safety evaluation.
    """

    operation: Any
    allowed: bool
    status: str
    reason: str

    def __post_init__(self) -> None:
        # Phase 1 contract: every safety verdict must map to a
        # PolicyDecision. An unmapped status is malformed and is
        # rejected at construction.
        from genesis_os.contracts import PolicyDecision
        PolicyDecision.from_safety_status(self.status)

    def to_dict(self) -> Dict[str, Any]:
        """
        Return JSON-safe decision data.
        """

        return {
            "operation": self.operation,
            "allowed": self.allowed,
            "status": self.status,
            "reason": self.reason,
        }


class ExecutionSafety:
    """
    Deterministic Genesis OS execution-safety policy.

    ExecutionSafety does not execute anything.

    It answers only:

        "May this operation proceed?"

    Possible statuses:

        supported
        denied
        unknown
        invalid
    """

    VERSION = "3.6.0"

    # Phase 1 contract authority: the deny-list mirrored as a
    # validated Policy (built once, loudly on malformed config).
    _POLICY: Any = None

    @classmethod
    def _policy(cls) -> Any:
        """Return the contract-validated authorization policy.

        Built from DENIED_OPERATIONS via Policy.from_safety_config,
        so an empty/malformed entry fails loudly at first use
        instead of silently weakening safety.
        """
        if cls._POLICY is None:
            from genesis_os.contracts import Policy as PolicyContract
            cls._POLICY = PolicyContract.from_safety_config(cls.DENIED_OPERATIONS)
        return cls._POLICY

    # Explicitly blocked operations.
    #
    # These remain blocked even if a future capability
    # registration accidentally exposes them.
    DENIED_OPERATIONS = frozenset(
        {
            "system.shutdown",
            "system.restart",
            "system.sleep",

            "filesystem.delete",
            "filesystem.move",
            "filesystem.rename",

            "shell.execute",

            "process.kill",
        }
    )

    @classmethod
    def check(
        cls,
        operation: Any,
    ) -> SafetyDecision:
        """
        Evaluate an operation against the safety policy.

        This method performs no OS action.
        """

        # -------------------------------------------------
        # TYPE VALIDATION
        # -------------------------------------------------

        if not isinstance(
            operation,
            str,
        ):
            return SafetyDecision(
                operation=operation,
                allowed=False,
                status="invalid",
                reason=(
                    "Execution operation must be "
                    "a string."
                ),
            )

        # -------------------------------------------------
        # NORMALIZATION
        # -------------------------------------------------

        normalized = operation.strip()

        # -------------------------------------------------
        # EMPTY OPERATION
        # -------------------------------------------------

        if not normalized:
            return SafetyDecision(
                operation=operation,
                allowed=False,
                status="invalid",
                reason=(
                    "Execution operation cannot "
                    "be empty."
                ),
            )

        # -------------------------------------------------
        # CONTRACT POLICY GATE (Phase 1 authority)
        # -------------------------------------------------
        #
        # The deny-list is enforced through the validated Policy
        # contract (built from DENIED_OPERATIONS at first use).
        # Verdict and reason are unchanged from the legacy
        # explicit block this replaces: deny-listed ops are
        # denied, everything else falls through to lookup.

        from genesis_os.contracts import PolicyDecision as _PolicyDecision

        if _PolicyDecision.DENY == cls._policy().evaluate(normalized):
            return SafetyDecision(
                operation=normalized,
                allowed=False,
                status="denied",
                reason=(
                    "Operation is explicitly blocked "
                    "by the Genesis OS execution "
                    "safety policy."
                ),
            )

        # -------------------------------------------------
        # CAPABILITY LOOKUP
        # -------------------------------------------------

        # -------------------------------------------------
        # UNKNOWN CAPABILITY
        # -------------------------------------------------

        if not CapabilityRegistry.exists(normalized):
            return SafetyDecision(
                operation=normalized,
                allowed=False,
                status="unknown",
                reason=(
                    "Operation is not recognized by "
                    "the current Genesis OS capability "
                    "registry."
                ),
            )

        capability = CapabilityRegistry.get(
            normalized
        )

        # -------------------------------------------------
        # DISABLED CAPABILITY
        # -------------------------------------------------

        if not capability.enabled:
            return SafetyDecision(
                operation=normalized,
                allowed=False,
                status="denied",
                reason=(
                    "Operation is registered but "
                    "currently disabled."
                ),
            )


        # -------------------------------------------------
        # SUPPORTED + SAFE
        # -------------------------------------------------

        return SafetyDecision(
            operation=normalized,
            allowed=True,
            status="supported",
            reason=(
                "Operation is registered, enabled, "
                "and permitted by the current "
                "Genesis OS execution-safety policy."
            ),
        )
    
