"""
Genesis OS — Action Result

LEVEL 3.3
---------

Trusted execution result contract.

ActionResult answers four separate questions:

    1. Was execution attempted?
    2. Was the requested state verified?
    3. Is the requested final state known?
    4. Can Genesis safely tell the user it succeeded?

The key safety property is:

    success != trustworthy_success

A raw execution attempt is NOT enough.

Genesis should only expose trustworthy success when
the desired final state is known and verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ActionResult:
    """
    Standardized Level 3 execution result.
    """

    success: bool

    operation: str

    target: Optional[str] = None

    application: Optional[str] = None

    status: str = "unknown"

    message: str = ""

    executed: bool = False

    verified: bool = False

    already_in_desired_state: bool = False

    retry_count: int = 0

    error: Optional[str] = None

    execution: Dict[str, Any] = field(
        default_factory=dict
    )

    verification: Dict[str, Any] = field(
        default_factory=dict
    )

    plan: Dict[str, Any] = field(
        default_factory=dict
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    version: str = "3.3.2"

    def __post_init__(self) -> None:
        if self.error and self.success:
            self.success = False
            self.verified = False
            if self.status in {"success", "verified"}:
                self.status = "execution_failed"
        if not self.success and self.verified:
            self.verified = False
        if self.already_in_desired_state and (
            not self.verified or not self.verification
        ):
            self.already_in_desired_state = False


    @classmethod
    def success_result(
        cls,
        operation: str,
        target: Optional[str],
        application: Optional[str],
        message: str,
        *,
        executed: bool = True,
        verified: bool = True,
        status: str = "success",
        already_in_desired_state: bool = False,
        execution: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None,
        plan: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ActionResult":

        return cls(
            success=True,
            operation=operation,
            target=target,
            application=application,
            status=status,
            message=message,
            executed=executed,
            verified=verified,
            already_in_desired_state=(
                already_in_desired_state
            ),
            execution=execution or {},
            verification=verification or {},
            plan=plan or {},
            metadata=metadata or {},
        )

    # =========================================================
    # FAILURE FACTORY
    # =========================================================

    @classmethod
    def failure_result(
        cls,
        operation: str,
        target: Optional[str],
        application: Optional[str],
        message: str,
        *,
        status: str = "failed",
        error: Optional[str] = None,
        executed: bool = False,
        verified: bool = False,
        retry_count: int = 0,
        execution: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None,
        plan: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ActionResult":

        return cls(
            success=False,
            operation=operation,
            target=target,
            application=application,
            status=status,
            message=message,
            executed=executed,
            verified=verified,
            retry_count=retry_count,
            error=error,
            execution=execution or {},
            verification=verification or {},
            plan=plan or {},
            metadata=metadata or {},
        )

    # =========================================================
    # SERIALIZATION
    # =========================================================

    def to_dict(
        self,
    ) -> Dict[str, Any]:
        """
        Convert the complete result into a JSON-safe
        dictionary.
        """

        return {
            "success": self.success,

            "trustworthy_success": (
                self.trustworthy_success
            ),

            "operation": self.operation,

            "target": self.target,

            "application": self.application,

            "status": self.status,

            "message": self.message,

            "executed": self.executed,

            "verified": self.verified,

            "already_in_desired_state": (
                self.already_in_desired_state
            ),

            "retry_count": self.retry_count,

            "error": self.error,

            "execution": dict(
                self.execution
            ),

            "verification": dict(
                self.verification
            ),

            "plan": (
                self.plan.to_dict()
                if self.plan is not None
                and hasattr(self.plan, "to_dict")
                else (
                    dict(self.plan)
                    if isinstance(self.plan, dict)
                    else self.plan
                )
            ),

            "metadata": dict(
                self.metadata
            ),
            "final_state": self.final_state,

            "version": self.version,
        }

    # =========================================================
    # HUMAN RESPONSE
    # =========================================================

    def user_message(self) -> str:
        """
        Return a safe human-facing response.

        The message must never claim that an operation
        succeeded or was verified unless the result contract
        actually supports that claim.
        """

        # -----------------------------------------------------
        # VERIFIED SUCCESS
        # -----------------------------------------------------

        if self.trustworthy_success:
            if self.message:
                return self.message

            return (
                "Genesis completed the requested "
                "operation and the final state "
                "was verified."
            )

        # -----------------------------------------------------
        # ALREADY DESIRED STATE
        # -----------------------------------------------------

        if (
            self.success
            and self.already_in_desired_state
            and self.verified
        ):
            return (
                "The requested final state was already "
                "present and was verified."
            )

        # -----------------------------------------------------
        # EXECUTED BUT NOT VERIFIED
        # -----------------------------------------------------

        if (
            self.executed
            and not self.verified
        ):
            return (
                "Genesis executed the requested "
                "operation, but the final state "
                "could not be verified."
            )

        # -----------------------------------------------------
        # FAILURE WITH MESSAGE
        # -----------------------------------------------------

        if self.message:
            return self.message

        # -----------------------------------------------------
        # GENERIC SUCCESS
        # -----------------------------------------------------

        if self.success:
            return (
                "Genesis completed the requested "
                "operation successfully."
            )

        # -----------------------------------------------------
        # GENERIC FAILURE
        # -----------------------------------------------------

        return (
            "Genesis could not complete the "
            "requested operation."
        )

    def explain(self) -> str:
        """
    Return a deterministic human-readable explanation
    of the execution result.

    This method intentionally returns a string rather than
    a dictionary so that higher layers can safely present
    the explanation directly to the user.
        """

        operation = self.operation or "unknown operation"

        target = (
            self.target
            if self.target is not None
            else "no target"
        )

    # ---------------------------------------------------------
    # SAFETY BLOCK
    # ---------------------------------------------------------

        if self.status == "safety_blocked":
            safety_reason = (
                self.metadata.get(
                    "safety_reason"
                )
                if isinstance(
                    self.metadata,
                    dict,
                )
                else None
            )

            if safety_reason:
                return (
                    f"Genesis blocked '{operation}' "
                    f"for target '{target}' because "
                    f"the execution safety policy denied "
                    f"the operation. {safety_reason}"
                )

            return (
                f"Genesis blocked '{operation}' "
                f"for target '{target}' because "
                f"the execution safety policy denied "
                f"the operation."
            )

    # ---------------------------------------------------------
    # VERIFIED SUCCESS
    # ---------------------------------------------------------

        if self.status == "execution_failed" or self.error:
            if self.error and not self.executed:
                return (
                    f"Genesis could not execute '{operation}' "
                    f"for target '{target}': {self.error}"
                )
            if self.error:
                return (
                    f"Genesis attempted '{operation}' "
                    f"for target '{target}', but execution "
                    f"failed: {self.error}"
                )

            return (
                f"Genesis attempted '{operation}' "
                f"for target '{target}', but execution failed."
            )

        if self.trustworthy_success:
            return (
                f"Genesis executed '{operation}' "
                f"for target '{target}' successfully. "
                f"Execution completed successfully, and "
                f"verification confirmed the requested final state."
            )

        if self.already_in_desired_state and self.verified:
            return (
                f"Genesis did not need to execute "
                f"'{operation}' for target '{target}' "
                f"because the requested final state "
                f"was already satisfied."
            )

    # ---------------------------------------------------------
    # EXECUTED BUT NOT VERIFIED
    # ---------------------------------------------------------

        if (
            self.executed
            and not self.verified
        ):
            return (
                f"Genesis attempted '{operation}' "
                f"for target '{target}', but the "
                f"final state could not be verified."
            )

    # ---------------------------------------------------------
    # VERIFICATION FAILURE
    # ---------------------------------------------------------

        if self.status == "verification_failed":
            return (
                f"Genesis executed '{operation}' "
                f"for target '{target}', but verification "
                f"failed."
            )

    # ---------------------------------------------------------
    # INVALID PLAN
    # ---------------------------------------------------------

        if self.status == "invalid_plan":
            return (
                f"Genesis rejected '{operation}' "
                f"for target '{target}' because the "
                f"action plan was invalid."
            )

    # ---------------------------------------------------------
    # GENERIC FAILURE
    # ---------------------------------------------------------

        if not self.success:
            if self.message:
                return str(
                    self.message
                )

            if self.error:
                return (
                    f"Genesis could not complete "
                    f"'{operation}' for target "
                    f"'{target}': {self.error}"
                )

            return (
                f"Genesis could not complete "
                f"'{operation}' for target '{target}'."
            )

    # ---------------------------------------------------------
    # GENERIC SUCCESS
    # ---------------------------------------------------------

        if self.message:
            return str(
                self.message
            )

        return (
            f"Genesis completed '{operation}' "
            f"for target '{target}'."
        )

    @property
    def final_state(self) -> str:
        """
        Deterministic high-level description of the final
        execution state.

        Possible states:

            desired_state
            verified
            executed_unverified
            execution_failed
            verification_failed
            not_executed
            failed
        """

        if (self.status == "execution_failed" or self.error) and self.executed:
            return "execution_failed"

        if self.already_in_desired_state and self.verified:
            return "desired_state"

        if self.trustworthy_success:
            return "verified"

        if self.executed and not self.verified:
            if self.status == "verification_failed":
                return "verification_failed"

            return "executed_unverified"

        if self.status == "verification_failed":
            return "verification_failed"

        if not self.executed:
            return "not_executed"

        return "failed"

    @property
    def trustworthy_success(self) -> bool:
        """
        Whether Genesis has sufficient evidence to truthfully
        claim that the requested operation succeeded.

        Trustworthy success requires a coherent successful result
        with independently verified final-state evidence. Execution
        or a desired-state flag alone is never sufficient.
        """

        if not self.success or self.error:
            return False
        if self.status in {
            "confirmation_required",
            "error",
            "execution_failed",
            "failed",
            "invalid_plan",
            "safety_blocked",
        }:
            return False
        if not self.verified:
            return False
        try:
            from genesis_os.contracts import has_meaningful_result_evidence
            return has_meaningful_result_evidence(self)
        except Exception:
            return False
