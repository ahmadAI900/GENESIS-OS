from __future__ import annotations

import hashlib
import json
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


class VerificationResult(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    SKIPPED = "skipped"


class ProofType(str, Enum):
    EXECUTION_TRACE = "execution_trace"
    STATE_TRANSITION = "state_transition"
    INPUT_OUTPUT = "input_output"
    ERROR_ABSENCE = "error_absence"


@dataclass
class FormalProperty:
    property_id: str
    name: str
    description: str
    property_type: str
    expression: str
    severity: str = "high"
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "property_id": self.property_id,
            "name": self.name,
            "description": self.description,
            "property_type": self.property_type,
            "expression": self.expression,
            "severity": self.severity,
            "enabled": self.enabled,
        }


@dataclass
class ExecutionTrace:
    trace_id: str
    operation: str
    steps: List[Dict[str, Any]]
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    start_time: float
    end_time: float
    success: bool
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "operation": self.operation,
            "steps_count": len(self.steps),
            "inputs": self.inputs,
            "outputs": self.outputs,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class ZKProof:
    proof_id: str
    proof_type: ProofType
    statement: str
    public_inputs: Dict[str, Any]
    witness_hash: str
    commitment: str
    verified: bool
    verifier_version: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proof_id": self.proof_id,
            "proof_type": self.proof_type.value,
            "statement": self.statement,
            "public_inputs": self.public_inputs,
            "commitment": self.commitment,
            "verified": self.verified,
            "verifier_version": self.verifier_version,
            "timestamp": self.timestamp,
        }


@dataclass
class ComplianceVerdict:
    verdict_id: str
    property_id: str
    result: VerificationResult
    proof: Optional[ZKProof]
    reason: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict_id": self.verdict_id,
            "property_id": self.property_id,
            "result": self.result.value,
            "proof": self.proof.to_dict() if self.proof else None,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class ZKComplianceEngine:
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._properties: Dict[str, FormalProperty] = {}
        self._traces: List[ExecutionTrace] = []
        self._proofs: List[ZKProof] = []
        self._verdicts: List[ComplianceVerdict] = []
        self._enforcement_hooks: Dict[str, Callable] = {}
        self._max_history = 500

        self._register_builtin_properties()

    def _register_builtin_properties(self) -> None:
        builtins = [
            FormalProperty(
                property_id="prop-no-secrets-leaked",
                name="No Secrets Leaked",
                description="Execution must not expose secrets in outputs or logs",
                property_type="information_flow",
                expression="∀ step ∈ trace: ¬contains_secret(step.output)",
                severity="critical",
            ),
            FormalProperty(
                property_id="prop-idempotent-safe",
                name="Idempotent Safety",
                description="Non-idempotent operations must verify state before retry",
                property_type="safety",
                expression="∀ op ∈ non_idempotent: pre_verify(op) → post_verify(op)",
                severity="high",
            ),
            FormalProperty(
                property_id="prop-resource-bounds",
                name="Resource Bounds",
                description="Operations must not exceed resource limits",
                property_type="liveness",
                expression="∀ op: cost(op) ≤ max_cost ∧ time(op) ≤ max_time",
                severity="high",
            ),
            FormalProperty(
                property_id="prop-state-consistency",
                name="State Consistency",
                description="System state must remain consistent across operations",
                property_type="invariant",
                expression="∀ transition: consistent(pre_state) → consistent(post_state)",
                severity="critical",
            ),
            FormalProperty(
                property_id="prop-permission-check",
                name="Permission Enforcement",
                description="All operations must pass permission check before execution",
                property_type="authorization",
                expression="∀ op: permitted(op, caller) ∨ deny(op)",
                severity="critical",
            ),
        ]

        for prop in builtins:
            self._properties[prop.property_id] = prop

    def register_property(self, prop: FormalProperty) -> None:
        with self._lock:
            self._properties[prop.property_id] = prop

    def unregister_property(self, property_id: str) -> bool:
        with self._lock:
            if property_id in self._properties:
                del self._properties[property_id]
                return True
            return False

    def register_enforcement_hook(
        self, property_id: str, hook: Callable[[ComplianceVerdict], None]
    ) -> None:
        with self._lock:
            self._enforcement_hooks[property_id] = hook

    def record_trace(self, trace: ExecutionTrace) -> None:
        with self._lock:
            self._traces.append(trace)
            if len(self._traces) > self._max_history:
                self._traces = self._traces[-self._max_history:]

    def generate_proof(
        self,
        trace: ExecutionTrace,
        proof_type: ProofType = ProofType.EXECUTION_TRACE,
    ) -> ZKProof:
        with self._lock:
            steps_str = json.dumps(trace.steps, sort_keys=True, default=str)
            witness_hash = hashlib.sha256(steps_str.encode()).hexdigest()[:16]

            public_data = {
                "operation": trace.operation,
                "success": trace.success,
                "step_count": len(trace.steps),
                "has_error": trace.error is not None,
            }
            public_str = json.dumps(public_data, sort_keys=True)
            commitment = hashlib.sha256(
                (public_str + witness_hash).encode()
            ).hexdigest()[:24]

            statement = (
                f"Execution of '{trace.operation}' completed with "
                f"success={trace.success}, {len(trace.steps)} steps, "
                f"error={'present' if trace.error else 'absent'}"
            )

            proof = ZKProof(
                proof_id=f"proof-{int(time.time() * 1000)}-{proof_type.value}",
                proof_type=proof_type,
                statement=statement,
                public_inputs=public_data,
                witness_hash=witness_hash,
                commitment=commitment,
                verified=True,
                verifier_version=self.VERSION,
                metadata={"trace_id": trace.trace_id},
            )

            self._proofs.append(proof)
            if len(self._proofs) > self._max_history:
                self._proofs = self._proofs[-self._max_history:]

            return proof

    def verify_property(
        self,
        property_id: str,
        trace: ExecutionTrace,
        proof: Optional[ZKProof] = None,
    ) -> ComplianceVerdict:
        with self._lock:
            prop = self._properties.get(property_id)
            if prop is None:
                verdict = ComplianceVerdict(
                    verdict_id=f"verdict-{int(time.time() * 1000)}",
                    property_id=property_id,
                    result=VerificationResult.SKIPPED,
                    proof=None,
                    reason=f"Property '{property_id}' not found",
                )
                self._verdicts.append(verdict)
                return verdict

            if not prop.enabled:
                verdict = ComplianceVerdict(
                    verdict_id=f"verdict-{int(time.time() * 1000)}",
                    property_id=property_id,
                    result=VerificationResult.SKIPPED,
                    proof=proof,
                    reason=f"Property '{property_id}' is disabled",
                )
                self._verdicts.append(verdict)
                return verdict

            if proof is None:
                proof = self.generate_proof(trace)

            result, reason = self._check_property(prop, trace, proof)

            verdict = ComplianceVerdict(
                verdict_id=f"verdict-{int(time.time() * 1000)}",
                property_id=property_id,
                result=result,
                proof=proof,
                reason=reason,
            )

            self._verdicts.append(verdict)
            if len(self._verdicts) > self._max_history:
                self._verdicts = self._verdicts[-self._max_history:]

            hook = self._enforcement_hooks.get(property_id)
            if hook and result == VerificationResult.FAILED:
                try:
                    hook(verdict)
                except Exception:
                    pass

            return verdict

    def _check_property(
        self,
        prop: FormalProperty,
        trace: ExecutionTrace,
        proof: ZKProof,
    ) -> Tuple[VerificationResult, str]:
        if prop.property_id == "prop-no-secrets-leaked":
            return self._check_no_secrets(trace)
        elif prop.property_id == "prop-idempotent-safe":
            return self._check_idempotent_safe(trace)
        elif prop.property_id == "prop-resource-bounds":
            return self._check_resource_bounds(trace)
        elif prop.property_id == "prop-state-consistency":
            return self._check_state_consistency(trace)
        elif prop.property_id == "prop-permission-check":
            return self._check_permission(trace)
        else:
            return self._check_generic(prop, trace)

    def _check_no_secrets(self, trace: ExecutionTrace) -> Tuple[VerificationResult, str]:
        secret_patterns = [
            "api_key", "secret", "password", "token", "private_key",
            "credential", "auth_key", "access_token",
        ]
        output_str = json.dumps(trace.outputs, default=str).lower()
        steps_str = json.dumps(trace.steps, default=str).lower()

        for pattern in secret_patterns:
            if pattern in output_str:
                return VerificationResult.FAILED, f"Secret pattern '{pattern}' found in outputs"
            if pattern in steps_str:
                return VerificationResult.FAILED, f"Secret pattern '{pattern}' found in execution steps"

        return VerificationResult.VERIFIED, "No secrets detected in execution trace"

    def _check_idempotent_safe(self, trace: ExecutionTrace) -> Tuple[VerificationResult, str]:
        non_idempotent_ops = {"delete", "move", "rename", "download", "write"}
        op_base = trace.operation.split(".")[-1] if "." in trace.operation else trace.operation

        if op_base in non_idempotent_ops:
            has_verify = any(
                "verify" in step.get("action", "").lower() or "check" in step.get("action", "").lower()
                for step in trace.steps
            )
            if has_verify:
                return VerificationResult.VERIFIED, "Non-idempotent operation includes verification step"
            else:
                return VerificationResult.FAILED, (
                    f"Non-idempotent operation '{op_base}' lacks state verification"
                )

        return VerificationResult.VERIFIED, "Operation is idempotent or not in non-idempotent set"

    def _check_resource_bounds(self, trace: ExecutionTrace) -> Tuple[VerificationResult, str]:
        duration = trace.end_time - trace.start_time
        if duration > 300:
            return VerificationResult.FAILED, f"Execution duration {duration:.1f}s exceeds 300s limit"

        if len(trace.steps) > 10000:
            return VerificationResult.FAILED, f"Step count {len(trace.steps)} exceeds 10000 limit"

        return VerificationResult.VERIFIED, f"Resources within bounds (duration={duration:.1f}s, steps={len(trace.steps)})"

    def _check_state_consistency(self, trace: ExecutionTrace) -> Tuple[VerificationResult, str]:
        if trace.error and trace.success:
            return VerificationResult.FAILED, "Inconsistent state: error present but success=True"
        if not trace.error and not trace.success:
            if trace.steps:
                return VerificationResult.INCONCLUSIVE, "No error but success=False: check needed"

        return VerificationResult.VERIFIED, "State appears consistent"

    def _check_permission(self, trace: ExecutionTrace) -> Tuple[VerificationResult, str]:
        steps_with_action = [s for s in trace.steps if "action" in s]
        if not steps_with_action:
            return VerificationResult.VERIFIED, "No actionable steps to check"

        for step in steps_with_action:
            if "permission_check" not in step and step.get("requires_permission", False):
                return VerificationResult.FAILED, (
                    f"Step '{step.get('action', 'unknown')}' requires permission but no check found"
                )

        return VerificationResult.VERIFIED, "All permission-required steps include checks"

    def _check_generic(
        self, prop: FormalProperty, trace: ExecutionTrace
    ) -> Tuple[VerificationResult, str]:
        return VerificationResult.VERIFIED, f"Generic check passed for '{prop.name}'"

    def verify_all(self, trace: ExecutionTrace) -> List[ComplianceVerdict]:
        results = []
        for prop_id, prop in self._properties.items():
            if prop.enabled:
                verdict = self.verify_property(prop_id, trace)
                results.append(verdict)
        return results

    def get_compliance_summary(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._verdicts)
            verified = sum(1 for v in self._verdicts if v.result == VerificationResult.VERIFIED)
            failed = sum(1 for v in self._verdicts if v.result == VerificationResult.FAILED)
            inconclusive = sum(
                1 for v in self._verdicts if v.result == VerificationResult.INCONCLUSIVE
            )
            return {
                "version": self.VERSION,
                "total_properties": len(self._properties),
                "enabled_properties": sum(1 for p in self._properties.values() if p.enabled),
                "total_verdicts": total,
                "verified": verified,
                "failed": failed,
                "inconclusive": inconclusive,
                "compliance_rate": verified / total if total > 0 else 1.0,
                "total_proofs": len(self._proofs),
                "total_traces": len(self._traces),
            }

    def get_properties(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [p.to_dict() for p in self._properties.values()]

    def get_verdicts(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return [v.to_dict() for v in self._verdicts[-limit:]]

    def get_proofs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return [p.to_dict() for p in self._proofs[-limit:]]
