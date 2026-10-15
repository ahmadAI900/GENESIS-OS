"""Genesis OS — Phase 1: Pydantic Cross-Layer Contracts.

Validated models for all 15 gate contracts: Objective, Entity,
Capability, Skill, Task, Workflow, Agent, Execution, Observation,
Verification, Recovery, Policy, Evidence, Session, Checkpoint.
These enforce strict contracts at runtime boundaries and reject
malformed or unsafe states early.

Native runtime types (dataclasses) are NOT mass-converted. Runtime
boundary models carry ``from_*`` adapters that validate native shapes
at their boundary modules; Skill has no runtime adapter yet because
its runtime is explicitly deferred to Phase 10.
"""
from __future__ import annotations

import posixpath
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator


class ContractViolationError(ValueError):
    """Raised when a native runtime shape fails its contract."""


# ============================================================
# SHARED ENUMS
# ============================================================

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    MODIFY = "modify"
    RESTRICT = "restrict"
    DENY = "deny"

    @classmethod
    def from_safety_status(cls, status: str) -> "PolicyDecision":
        """Map an ExecutionSafety verdict to a policy decision.

        Every safety status must map somewhere — an unmapped status
        is a malformed boundary state and is rejected loudly.
        """
        mapping = {
            "supported": cls.ALLOW,
            "denied": cls.DENY,
            "unknown": cls.CONFIRM,
            "invalid": cls.DENY,
        }
        try:
            return mapping[str(status).strip().lower()]
        except KeyError:
            raise ContractViolationError(
                f"safety status {status!r} has no policy decision mapping"
            )


class CheckpointStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class EvidenceType(str, Enum):
    DISPATCH_CONFIRMED = "dispatch_confirmed"
    CONTENT_VERIFIED = "content_verified"
    UIA_READBACK = "uia_readback"
    FILE_EXISTS = "file_exists"
    BROWSER_STATE = "browser_state"
    CLIPBOARD_READBACK = "clipboard_readback"
    MANUAL = "manual"


# ============================================================
# SKILL CONTRACT
# ============================================================

class SkillParameter(BaseModel):
    """A single parameter required by a skill."""
    name: str = Field(..., min_length=1)
    type: str = Field(default="str")
    description: str = ""
    required: bool = True
    default: Optional[Any] = None


class Skill(BaseModel):
    """Reusable task knowledge contract.

    A skill composes capabilities into reusable behavior with
    purpose, parameters, verification, recovery and risk metadata.
    """
    skill_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    purpose: str = ""
    required_capabilities: List[str] = Field(default_factory=list)
    workflow_pattern: str = "sequential"
    parameters: List[SkillParameter] = Field(default_factory=list)
    verification_steps: List[str] = Field(default_factory=list)
    recovery_steps: List[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False
    tags: List[str] = Field(default_factory=list)
    version: str = "1.0"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("skill_id")
    @classmethod
    def validate_skill_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("skill_id cannot be empty")
        return v.strip()

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# CHECKPOINT CONTRACT
# ============================================================

class Checkpoint(BaseModel):
    """Atomic workflow checkpoint for durable execution.

    Captures enough state to resume a workflow after interruption
    without corrupting state or repeating destructive actions.
    """
    checkpoint_id: str = Field(..., min_length=1)
    workflow_id: str = Field(..., min_length=1)
    step_id: str = Field(..., min_length=1)
    status: CheckpointStatus = CheckpointStatus.PENDING
    state_snapshot: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    is_idempotent: bool = True
    side_effects: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("checkpoint_id")
    @classmethod
    def validate_checkpoint_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("checkpoint_id cannot be empty")
        return v.strip()

    @classmethod
    def from_step_completion(
        cls,
        *,
        workflow_id: str,
        step_id: str,
        operation: str,
        success: bool,
        verified: bool,
        executed: bool,
        is_idempotent: bool = True,
        evidence: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> "Checkpoint":
        """Validate a native workflow-engine step completion.

        Boundary: WorkflowEngine step-success path. Every completed
        step produces a contract-validated checkpoint record
        (in-memory; durable resume is Phase 16). Malformed ids or
        incoherent states raise loudly instead of recording garbage.
        """
        from datetime import datetime, timezone

        status = CheckpointStatus.COMPLETED if success else CheckpointStatus.FAILED
        try:
            return cls(
                checkpoint_id=f"{workflow_id}:{step_id}",
                workflow_id=str(workflow_id or ""),
                step_id=str(step_id or ""),
                status=status,
                state_snapshot={
                    "operation": str(operation or ""),
                    "success": bool(success),
                    "verified": bool(verified),
                    "executed": bool(executed),
                },
                evidence=[dict(evidence or {})],
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=error,
                is_idempotent=bool(is_idempotent),
                side_effects=[] if bool(is_idempotent) else [str(operation or "")],
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Checkpoint shape: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# POLICY CONTRACT
# ============================================================

class PolicyRule(BaseModel):
    """A single authorization rule.

    Defines when a policy decision applies based on operation
    category, risk level, and conditions.
    """
    rule_id: str = Field(..., min_length=1)
    operation_pattern: str = Field(..., min_length=1)
    risk_level: RiskLevel = RiskLevel.LOW
    decision: PolicyDecision = PolicyDecision.ALLOW
    requires_confirmation: bool = False
    requires_explicit_auth: bool = False
    conditions: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    enabled: bool = True


class Policy(BaseModel):
    """Central authorization contract.

    Ensures the model proposes actions while Genesis determines
    whether and how they may execute. Policy is independent of
    model preference.
    """
    policy_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    rules: List[PolicyRule] = Field(default_factory=list)
    default_decision: PolicyDecision = PolicyDecision.ALLOW
    enabled: bool = True
    version: str = "1.0"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def evaluate(self, operation: str, risk_level: RiskLevel = RiskLevel.LOW) -> PolicyDecision:
        """Evaluate an operation against policy rules.

        Risk comparison uses severity ordering (LOW < MEDIUM < HIGH
        < CRITICAL), not string ordering — a rule fires when its own
        risk tier covers the operation's tier.
        """
        _SEVERITY = {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.CRITICAL: 3,
        }
        if not self.enabled:
            return PolicyDecision.ALLOW

        try:
            op_severity = _SEVERITY.get(risk_level, 0)
        except Exception:
            op_severity = 0
        for rule in self.rules:
            if not rule.enabled:
                continue
            if rule.operation_pattern == operation or rule.operation_pattern == "*":
                if _SEVERITY.get(rule.risk_level, 0) >= op_severity:
                    return rule.decision
        return self.default_decision

    @classmethod
    def from_safety_config(cls, denied_operations: Any) -> "Policy":
        """Validate native ExecutionSafety deny configuration.

        Boundary: ExecutionSafety first use. The deny-list becomes
        validated DENY rules; a malformed entry raises loudly instead
        of silently weakening the safety policy.
        """
        try:
            rules = []
            for op in (denied_operations or ()):
                name = str(op or "").strip()
                if not name:
                    raise ValueError("deny-list contains an empty operation")
                rules.append(
                    PolicyRule(
                        rule_id=f"deny:{name}",
                        operation_pattern=name,
                        # CRITICAL so the deny-list covers every risk
                        # tier: a denied operation is denied regardless
                        # of the caller's risk assessment.
                        risk_level=RiskLevel.CRITICAL,
                        decision=PolicyDecision.DENY,
                        reason="Genesis OS execution-safety deny-list",
                    )
                )
            return cls(
                policy_id="genesis-execution-safety",
                name="Genesis execution safety",
                description="Deny-list derived authorization policy.",
                rules=rules,
                default_decision=PolicyDecision.ALLOW,
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Policy shape: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# EVIDENCE CONTRACT
# ============================================================

class Evidence(BaseModel):
    """Verifiable proof of execution outcome.

    Every important result must have evidence before being
    reported as verified. Evidence is machine-readable and
    human-auditable.
    """
    evidence_id: str = Field(..., min_length=1)
    evidence_type: EvidenceType
    operation: str = Field(..., min_length=1)
    passed: bool = False
    expected: Optional[Any] = None
    actual: Optional[Any] = None
    reason: str = ""
    provider: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _passed_requires_metadata(self) -> "Evidence":
        if self.passed and not self.metadata:
            raise ValueError("passed evidence requires metadata")
        return self

    @field_validator("evidence_id")
    @classmethod
    def validate_evidence_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("evidence_id cannot be empty")
        return v.strip()

    @classmethod
    def from_result(cls, result: Any) -> "Evidence":
        evidence = getattr(result, "verification", None)
        if evidence is None:
            evidence = {}
        if not isinstance(evidence, dict):
            raise ContractViolationError("verification evidence must be a mapping")
        evidence = {
            key: value
            for key, value in evidence.items()
            if key != "verified"
        }
        operation = str(getattr(result, "operation", "") or "")
        if not operation:
            raise ContractViolationError("verification evidence requires an operation")
        verified = bool(getattr(result, "verified", False))
        if verified and not has_meaningful_result_evidence(result):
            raise ContractViolationError(
                "verified result lacks capability-specific evidence"
            )
        if evidence.get("content_match") is True or evidence.get("content_verification") is True:
            evidence_type = EvidenceType.CONTENT_VERIFIED
        elif any(
            key in evidence
            for key in ("url", "title", "actual_url", "actual_title", "tab_state_verified")
        ):
            evidence_type = EvidenceType.BROWSER_STATE
        elif any(
            key in evidence
            for key in ("file_exists", "folder_exists", "running", "process_found", "destination_exists")
        ):
            evidence_type = EvidenceType.FILE_EXISTS
        elif evidence.get("uia_readback") is True or evidence.get("read_method") in {"value_pattern", "text_pattern"}:
            evidence_type = EvidenceType.UIA_READBACK
        else:
            evidence_type = EvidenceType.DISPATCH_CONFIRMED
        return cls(
            evidence_id=f"{operation}:verification",
            evidence_type=evidence_type,
            operation=operation,
            passed=verified,
            reason=str(evidence.get("verification_reason", "")),
            metadata=evidence,
        )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# EVIDENCE GATE (enforced at execution/verification boundaries)
# ============================================================

# Default ports, used to normalise ``host:port`` so that an explicit
# default port compares equal to its absence.
_URL_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def canonical_url_identity(value: Any) -> Optional[Tuple[str, str, Optional[int], str, str]]:
    """Reduce a URL to the identity that proves it is the same resource.

    Returns ``(scheme, host, port, path, query)`` or ``None`` when the
    value is not a usable absolute URL.

    Normalisations applied, and why each is safe:

    * ``scheme``/``host`` lower-cased — DNS host names and URI schemes
      are case-insensitive (RFC 3986 §3.1, §3.2.2).
    * ``port`` — an explicit default port (``https://x:443``) is treated
      as identical to its absence, because they address the same
      endpoint. A non-default port is preserved and must match.
    * ``path`` — ``""`` and ``"/"`` are the same resource root, a
      trailing slash is dropped, and dot segments are resolved via
      ``posixpath.normpath``. This is what stops ``/a/../b`` from
      masquerading as ``/a``.
    * ``query`` — compared verbatim. A changed query string is a
      different resource, so it must not verify.
    * fragment — deliberately ignored: it is never sent to the server
      and does not change the retrieved document.

    ``host`` is taken from ``urlsplit().hostname``, which excludes any
    ``user@`` prefix and any ``:port`` suffix. That is what defeats
    ``https://example.com@evil.net/``, where the real host is
    ``evil.net`` and a naive prefix comparison would pass.

    Not handled (documented limitation): IDN/punycode equivalence and
    percent-encoding equivalence. Both would make a comparison
    *stricter* than necessary and can only produce a false negative
    (an honestly-opened URL reported unverified), never a false
    positive.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # Chromium and Gecko treat a backslash as a path separator, so a
    # value containing one can parse differently from what a naive
    # string comparison sees. Normalise before parsing.
    text = text.replace("\\", "/")
    try:
        parts = urlsplit(text)
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        port = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return None
    if not scheme or not host:
        return None
    if port == _URL_DEFAULT_PORTS.get(scheme):
        port = None
    path = posixpath.normpath(parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return scheme, host, port, path, parts.query


def urls_denote_same_resource(requested: Any, actual: Any) -> bool:
    """True when ``actual`` proves ``requested`` was really opened.

    TOLERATED DIFFERENCES, stated explicitly:

    1. Case in the scheme and host.
    2. An explicit default port versus none (``https://x`` ==
       ``https://x:443``).
    3. ``""`` versus ``"/"`` as the path, a trailing slash, and
       dot-segments (``/a/../b`` == ``/b``).
    4. A fragment difference (fragments are never transmitted).
    5. ``http`` -> ``https`` on the same host, port and path. This is a
       real server-side upgrade redirect that preserves the authority,
       so it still proves the requested resource was reached.

    Everything else is a mismatch and will not verify. In particular a
    different host, a host that merely *starts with* the requested
    host, a different port, a different path, or a different query
    string all fail. A scheme *downgrade* (https -> http) also fails:
    the transport guarantee the caller asked for is not the one they
    got.
    """
    requested_identity = canonical_url_identity(requested)
    actual_identity = canonical_url_identity(actual)
    if requested_identity is None or actual_identity is None:
        return False

    r_scheme, r_host, r_port, r_path, r_query = requested_identity
    a_scheme, a_host, a_port, a_path, a_query = actual_identity

    if (r_host, r_port, r_path, r_query) != (a_host, a_port, a_path, a_query):
        return False
    if a_scheme == r_scheme:
        return True
    # Documented tolerance 5: secure-scheme upgrade only. Directional
    # on purpose — a downgrade (https -> http) does not give the caller
    # the transport guarantee they asked for, so it must not verify.
    return r_scheme == "http" and a_scheme == "https"


# DECISION 2026-10-06 — falsy values ARE acceptable evidence, and this
# was measured rather than assumed.
#
# The concern was that `value not in (None, "", {}, [])` lets 0 and
# False through, so a field that merely defaulted to zero could
# certify a result. The alternative considered was requiring an
# explicit provenance signal (verification_type / verification_method /
# verification_reason) before trusting a falsy value. That change was
# implemented and then REVERTED, because it produced four false
# negatives in correct, load-bearing tests:
#
#   * hardware.battery  -> {"battery_present": False} on a desktop
#     with no battery. "I checked; there is no battery" is accurate.
#   * process.inspect   -> {"running": False, "pids": [], "count": 0}
#   * process.list      -> {"processes": [], "count": 0}
#   * application.list  -> {"applications": [], "count": 0}
#
# All four are honest observations of "the query ran and returned
# nothing". Requiring provenance traded a theoretical false positive
# for real false negatives, which is the wrong trade for a gate whose
# job is to reject *fabricated* success, not merely weak success.
#
# An audit of every live call site also found NO site that fabricates:
#   * clipboard_manager.py — empty clipboard emits empty: True with
#     verification_type, genuinely observed.
#   * folder_manager.py — empty folder emits count: 0 but also
#     folder_exists: True, so the operation-specific rule already
#     accepts it; the count is redundant, not load-bearing.
#   * verification_helpers.verify_doc_read — returns content_length
#     only after rejecting empty text, so it is never 0 when verified.
#   * file_manager.py summarize's no-summarizer branch emits
#     content_length but no verified flag, so it never reaches here.
#
# Residual, accepted risk: a provider that hardcodes `count: 0` while
# asserting verified=True without actually querying would still
# verify. The defence against that is provider honesty plus the
# operation-specific rules, not value falsiness.


def has_meaningful_result_evidence(result: Any) -> bool:
    verified = bool(getattr(result, "verified", False))
    if not verified:
        return False

    operation = str(getattr(result, "operation", "") or "")
    evidence = getattr(result, "verification", None) or {}
    if not isinstance(evidence, dict):
        return False

    for key in (
        "content_match",
        "content_verification",
        "all_passed",
        "url_readback",
        "search_verified",
        "tab_state_verified",
        "selection_verified",
        "click_postcondition_verified",
        "state_check_passed",
        "upload_readback_verified",
        "scroll_position_changed",
        "file_matches",
        "output_matches",
        "image_decoded",
    ):
        if evidence.get(key) is True:
            return True

    if operation in {"browser.open_url", "browser.search", "browser.open_tab"}:
        requested = evidence.get("requested_url")
        actual = evidence.get("actual_url") or evidence.get("url")
        if operation == "browser.open_tab" and requested is None:
            return bool(
                isinstance(actual, str)
                and actual
                and evidence.get("tab_state_verified") is True
            )
        if not requested or not isinstance(actual, str) or not actual:
            return False
        # Structural URL comparison, not a prefix match. A prefix match
        # accepted "https://example.com.evil.net/" for a request to
        # "https://example.com", and accepted the userinfo form
        # "https://example.com@evil.net/" whose real host is evil.net.
        # See urls_denote_same_resource for the tolerated differences.
        return urls_denote_same_resource(requested, actual)

    # "The application is gone" is the correct evidence for a close,
    # so that check is evaluated FIRST and is mutually exclusive with
    # the generic application.* rule below.
    #
    # The elif is load-bearing. Previously the generic rule ran first
    # and matched ANY application.* operation carrying a bool `running`,
    # so `application.close` with `running: True` -- the app still
    # running, which contradicts a successful close -- returned True
    # before the close-specific rule was ever reached. Reordering alone
    # would not have fixed it: the generic rule would still match on
    # the way back down. The close family must be excluded outright.
    if operation in {"application.close", "application.window_not_exists"}:
        if evidence.get("running") is False or evidence.get("process_found") is False:
            return True
    elif operation.startswith("application.") and isinstance(evidence.get("running"), bool):
        return True
    if operation in {"file.inspect", "file.read"} and evidence.get("file_exists") is True:
        return True
    if operation.startswith("document.") and evidence.get("file_exists") is True:
        return True
    if operation in {"folder.inspect", "folder.create", "folder.rename", "folder.move"} and evidence.get("folder_exists") is True:
        return True
    if operation == "folder.delete" and evidence.get("folder_exists") is False:
        return True
    if operation == "file.delete" and evidence.get("file_exists") is False:
        return True
    if operation == "file.copy" and evidence.get("file_matches") is True:
        return True
    if operation == "file.move" and evidence.get("file_matches") is True:
        return True
    if operation == "file.move" and evidence.get("destination_exists") is True:
        if evidence.get("source_removed") is True or evidence.get("old_path_exists") is False:
            return True
    if operation == "cleanup.empty_recycle_bin" and evidence.get("item_count") == 0:
        return True
    if operation == "file.rename" and (
        evidence.get("destination_exists") is True
        and evidence.get("old_path_exists") is False
    ):
        return True

    for key in (
        "content_preview",
        "content_length",
        "empty",
        "count",
        "row_count",
        "item_count",
        "muted",
        "volume_percent",
        "brightness_percent",
        "battery_percent",
        "battery_present",
        "plugged_in",
        "battery_status",
        "cpu_percent",
        "memory_percent",
        "memory_used_gb",
        "memory_total_gb",
        "uptime_hours",
        "uptime_minutes",
        "per_display",
        "local_time",
        "local_date",
        "report",
        "summary_verified",
        "drives",
        "platform",
        "release",
        "processes",
        "pids",
        "title",
        "url",
        "actual_url",
        "actual_title",
        "actual_value",
        "selected_value",
        "input_value",
        "rows",
        "headers",
        "values",
        "items",
        "matches",
        "tabs",
        "scroll_after",
        "records",
        "result",
        "result_count",
        "actual",
    ):
        value = evidence.get(key)
        if value not in (None, "", {}, []):
            return True

    verification_type = str(
        evidence.get("verification_type")
        or evidence.get("verification_method")
        or ""
    ).lower()
    if "search" in verification_type or "find" in verification_type:
        query = evidence.get("query") or evidence.get("text")
        if query and ("count" in evidence or "matches" in evidence):
            return True

    return False


def require_result_evidence(
    result: Any,
    evidence: Optional[Evidence] = None,
) -> Evidence:
    checked = evidence if evidence is not None else Evidence.from_result(result)
    if bool(getattr(result, "verified", False)):
        if not checked.passed or not has_meaningful_result_evidence(result):
            operation = getattr(result, "operation", "?")
            raise ContractViolationError(
                f"result for '{operation}' claims verified=True "
                f"without capability-specific evidence"
            )
    return checked

# ============================================================
# AGENT CONTRACT
# ============================================================

class AgentCapability(str, Enum):
    RESEARCH = "research"
    CODING = "coding"
    DATA = "data"
    OS = "os"
    BROWSER = "browser"
    FILESYSTEM = "filesystem"
    DOCUMENT = "document"
    GENERAL = "general"


class Agent(BaseModel):
    """Agent contract for Level 2 execution.

    Defines an agent's capabilities, constraints, and execution
    boundaries.
    """
    agent_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    capabilities: List[AgentCapability] = Field(default_factory=list)
    raw_capabilities: List[str] = Field(default_factory=list)
    max_concurrent_tasks: int = Field(default=1, ge=1)
    timeout_seconds: float = Field(default=300.0, gt=0)
    requires_confirmation: bool = False
    allowed_operations: List[str] = Field(default_factory=list)
    blocked_operations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("agent_id cannot be empty")
        return v.strip()

    def can_execute(self, operation: str) -> bool:
        """Check if this agent can execute an operation."""
        if operation in self.blocked_operations:
            return False
        if self.allowed_operations and operation not in self.allowed_operations:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_runtime(cls, agent: Any) -> "Agent":
        """Validate a live Level 2 agent object at registration.

        Runtime capability lists are free-form strings; known ones
        map to the enum, everything is preserved in
        ``raw_capabilities`` so nothing is silently dropped.
        """
        name = getattr(agent, "name", None)
        if name is None or not str(name).strip():
            raise ContractViolationError("agent must have a non-empty name")
        raw = [str(c) for c in (getattr(agent, "capabilities", []) or [])]
        known = []
        for cap in raw:
            try:
                known.append(AgentCapability(cap.strip().lower()))
            except ValueError:
                continue
        return cls(
            agent_id=str(name).strip(),
            name=str(name).strip(),
            description=str(getattr(agent, "description", "") or ""),
            capabilities=known,
            raw_capabilities=raw,
        )


# ============================================================
# OBJECTIVE CONTRACT (adapter over ObjectiveUnderstandingResult)
# ============================================================

class ObjectiveStep(BaseModel):
    """One structured intent step of an understood objective."""
    step_id: str = Field(..., min_length=1)
    text: str = ""
    sequence: int = Field(..., ge=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    level: int = Field(default=1, ge=1, le=3)
    mode: str = ""
    operation: Optional[str] = None
    target: Optional[str] = None
    requires_clarification: bool = False
    entities: List[Dict[str, Any]] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)
    required_agents: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _text_or_clarification(self) -> "ObjectiveStep":
        if not self.text.strip() and not self.requires_clarification:
            raise ValueError("objective step with empty text must require clarification")
        return self


class Objective(BaseModel):
    """Validated human objective (boundary: ObjectiveUnderstanding)."""
    objective: str = ""
    steps: List[ObjectiveStep] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requires_clarification: bool = False
    clarification_reason: Optional[str] = None
    goal: Optional[str] = None
    overall_intent: Optional[str] = None
    required_capabilities: List[str] = Field(default_factory=list)
    required_agents: List[str] = Field(default_factory=list)
    overall_risk: Optional[str] = None

    @model_validator(mode="after")
    def _coherent(self) -> "Objective":
        if not self.objective.strip() and not self.requires_clarification:
            raise ValueError("empty objective must require clarification")
        sequences = [s.sequence for s in self.steps]
        if sequences and (min(sequences) != 1 or sorted(sequences) != list(range(1, len(sequences) + 1))):
            raise ValueError("objective step sequences must run 1..N without gaps")
        return self

    @classmethod
    def from_understanding_result(cls, result: Any) -> "Objective":
        """Validate a native ObjectiveUnderstandingResult."""
        try:
            steps = []
            for intent in (getattr(result, "steps", None) or ()):
                entities = getattr(intent, "entities", None) or ()
                steps.append(ObjectiveStep(
                    step_id=str(getattr(intent, "step_id", "")),
                    text=str(getattr(intent, "text", "") or ""),
                    sequence=int(getattr(intent, "sequence", 0) or 0),
                    confidence=float(getattr(intent, "confidence", 0.0) or 0.0),
                    level=int(getattr(intent, "level", 1) or 1),
                    mode=str(getattr(intent, "mode", "") or ""),
                    operation=getattr(intent, "operation", None),
                    target=getattr(intent, "target", None),
                    requires_clarification=bool(getattr(intent, "requires_clarification", False)),
                    entities=[dict(e) for e in entities],
                    required_capabilities=[str(c) for c in (getattr(intent, "required_capabilities", None) or ())],
                    required_agents=[str(a) for a in (getattr(intent, "required_agents", None) or ())],
                ))
            return cls(
                objective=str(getattr(result, "objective", "") or ""),
                steps=steps,
                confidence=float(getattr(result, "confidence", 0.0) or 0.0),
                requires_clarification=bool(getattr(result, "requires_clarification", False)),
                clarification_reason=getattr(result, "clarification_reason", None),
                goal=getattr(result, "goal", None),
                overall_intent=getattr(result, "overall_intent", None),
                required_capabilities=[str(c) for c in (getattr(result, "required_capabilities", None) or ())],
                required_agents=[str(a) for a in (getattr(result, "required_agents", None) or ())],
                overall_risk=getattr(result, "overall_risk", None),
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Objective shape: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# ENTITY CONTRACT (adapter over EntityEntry)
# ============================================================

class EntityTypeName(str, Enum):
    FILE = "file"
    FOLDER = "folder"
    APPLICATION = "application"
    BROWSER_TAB = "browser_tab"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    NOTE = "note"
    CLIPBOARD = "clipboard"


class EntityActionName(str, Enum):
    CREATED = "created"
    OPENED = "opened"
    MODIFIED = "modified"
    ACCESSED = "accessed"
    CLOSED = "closed"
    REFERENCED = "referenced"


class Entity(BaseModel):
    """Tracked entity interaction (boundary: EntityHistory.record)."""
    entity_type: EntityTypeName
    entity_id: str = Field(..., min_length=1)
    action: EntityActionName
    timestamp: str = Field(..., min_length=1)
    source_level: int = Field(..., ge=1, le=3)
    source_operation: Optional[str] = None
    source_agent: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("entity_id")
    @classmethod
    def _non_empty_id(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("entity_id cannot be empty")
        return v

    @classmethod
    def from_entry(cls, entry: Any) -> "Entity":
        """Validate a native EntityEntry."""
        try:
            raw_type = getattr(entry, "entity_type", None)
            type_value = raw_type.value if hasattr(raw_type, "value") else str(raw_type)
            raw_action = getattr(entry, "action", None)
            action_value = raw_action.value if hasattr(raw_action, "value") else str(raw_action)
            raw_ts = getattr(entry, "timestamp", None)
            if isinstance(raw_ts, datetime):
                ts = raw_ts.isoformat()
            else:
                ts = str(raw_ts or "")
            source_level = getattr(entry, "source_level", None)
            if isinstance(source_level, bool) or not isinstance(source_level, int):
                raise ValueError(f"source_level must be an int, got {source_level!r}")
            return cls(
                entity_type=EntityTypeName(str(type_value).lower()),
                entity_id=str(getattr(entry, "entity_id", "")),
                action=EntityActionName(str(action_value).lower()),
                timestamp=ts,
                source_level=source_level,
                source_operation=getattr(entry, "source_operation", None),
                source_agent=getattr(entry, "source_agent", None),
                metadata=dict(getattr(entry, "metadata", None) or {}),
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Entity shape: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# CAPABILITY CONTRACT (adapter over CapabilityDescriptor)
# ============================================================

class Capability(BaseModel):
    """Validated capability descriptor (boundary: CapabilityResolver)."""
    capability_id: str = Field(..., min_length=1)
    category: str = ""
    operation: str = Field(..., min_length=1)
    description: str = ""
    provider: str = ""
    version: str = ""
    availability: str = ""
    priority: float = 0.0
    enabled: bool = True
    risk_level: str = "low"
    preconditions: List[str] = Field(default_factory=list)
    postconditions: List[str] = Field(default_factory=list)
    failure_modes: List[str] = Field(default_factory=list)
    supported_inputs: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)

    @field_validator("capability_id", "operation")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("capability_id/operation cannot be empty")
        return v.strip()

    @classmethod
    def from_descriptor(cls, descriptor: Any) -> "Capability":
        """Validate a native CapabilityDescriptor."""
        try:
            category = getattr(descriptor, "category", "")
            category_value = category.value if hasattr(category, "value") else str(category or "")
            availability = getattr(descriptor, "availability", "")
            availability_value = availability.value if hasattr(availability, "value") else str(availability or "")
            return cls(
                capability_id=str(getattr(descriptor, "capability_id", "")),
                category=category_value,
                operation=str(getattr(descriptor, "operation", "")),
                description=str(getattr(descriptor, "description", "") or ""),
                provider=str(getattr(descriptor, "provider", "") or ""),
                version=str(getattr(descriptor, "version", "") or ""),
                availability=availability_value,
                priority=float(getattr(descriptor, "priority", 0.0) or 0.0),
                enabled=bool(getattr(descriptor, "enabled", True)),
                risk_level=str(getattr(descriptor, "risk_level", "low") or "low"),
                preconditions=[str(x) for x in (getattr(descriptor, "preconditions", None) or [])],
                postconditions=[str(x) for x in (getattr(descriptor, "postconditions", None) or [])],
                failure_modes=[str(x) for x in (getattr(descriptor, "failure_modes", None) or [])],
                supported_inputs=[str(x) for x in (getattr(descriptor, "supported_inputs", None) or [])],
                permissions=[str(x) for x in (getattr(descriptor, "permissions", None) or [])],
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Capability shape: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# TASK CONTRACT (adapter over ActionPlan)
# ============================================================

class Task(BaseModel):
    """Validated unit of work (boundary: ActionExecutor dispatch)."""
    operation: str = Field(..., min_length=1)
    target: Optional[str] = None
    application: Optional[str] = None
    task: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    source: str = ""
    version: str = ""

    @field_validator("operation")
    @classmethod
    def _non_empty_operation(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("task operation must be a non-empty string")
        return v.strip()

    @field_validator("confidence", mode="before")
    @classmethod
    def _numeric_confidence(cls, v: Any) -> float:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("task confidence must be numeric")
        return float(v)

    @classmethod
    def from_action_plan(cls, plan: Any) -> "Task":
        """Validate a native ActionPlan at dispatch."""
        try:
            params = getattr(plan, "parameters", None) or {}
            return cls(
                operation=getattr(plan, "operation", ""),
                target=getattr(plan, "target", None),
                application=getattr(plan, "application", None),
                task=str(getattr(plan, "task", "") or ""),
                confidence=getattr(plan, "confidence", 1.0),
                parameters=dict(params),
                reason=str(getattr(plan, "reason", "") or ""),
                source=str(getattr(plan, "source", "") or ""),
                version=str(getattr(plan, "version", "") or ""),
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Task shape: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# WORKFLOW CONTRACT (adapter over WorkflowPlan)
# ============================================================

class WorkflowStepRef(BaseModel):
    """Identity of one workflow step."""
    step_id: str = Field(..., min_length=1)
    operation: str = ""


class Workflow(BaseModel):
    """Validated workflow plan (boundary: WorkflowEngine.validate)."""
    workflow_id: str = ""
    objective: str = ""
    steps: List[WorkflowStepRef] = Field(default_factory=list)
    version: str = ""

    @model_validator(mode="after")
    def _coherent(self) -> "Workflow":
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("workflow step_ids must be unique")
        if not self.steps and not self.objective.strip():
            raise ValueError("workflow needs at least an objective or one step")
        return self

    @classmethod
    def from_workflow_plan(cls, plan: Any) -> "Workflow":
        """Validate a native WorkflowPlan."""
        try:
            steps = []
            for step in (getattr(plan, "steps", None) or ()):
                sub = getattr(step, "plan", None)
                steps.append(WorkflowStepRef(
                    step_id=str(getattr(step, "step_id", "")),
                    operation=str(getattr(sub, "operation", "") or "") if sub is not None else "",
                ))
            return cls(
                workflow_id=str(getattr(plan, "workflow_id", "") or ""),
                objective=str(getattr(plan, "objective", "") or ""),
                steps=steps,
                version=str(getattr(plan, "version", "") or ""),
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Workflow shape: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# EXECUTION CONTRACT (adapter over ActionResult)
# ============================================================

class Execution(BaseModel):
    """Validated execution result (boundary: ActionExecutor)."""
    success: bool = False
    operation: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    executed: bool = False
    verified: bool = False
    already_in_desired_state: bool = False
    retry_count: int = Field(default=0, ge=0)
    message: str = ""
    error: Optional[str] = None

    @model_validator(mode="after")
    def _coherent_execution(self) -> "Execution":
        if self.error and self.success:
            raise ValueError("an execution with an error cannot be successful")
        if self.verified and not self.success:
            raise ValueError("an unsuccessful execution cannot be verified")
        return self

    @classmethod
    def from_action_result(cls, result: Any) -> "Execution":
        """Validate a native ActionResult."""
        try:
            retry = getattr(result, "retry_count", 0) or 0
            return cls(
                success=bool(getattr(result, "success", False)),
                operation=str(getattr(result, "operation", "")),
                status=str(getattr(result, "status", "")),
                executed=bool(getattr(result, "executed", False)),
                verified=bool(getattr(result, "verified", False)),
                already_in_desired_state=bool(getattr(result, "already_in_desired_state", False)),
                retry_count=int(retry),
                message=str(getattr(result, "message", "") or ""),
                error=getattr(result, "error", None),
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Execution shape: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# OBSERVATION CONTRACT (adapter over gui_observer.Observation)
# ============================================================

class Observation(BaseModel):
    """Validated OS-state observation (boundary: GUIObserver)."""
    timestamp: float = Field(...)
    foreground_window: Optional[Dict[str, Any]] = None
    window_count: int = Field(default=0, ge=0)
    text_content: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> "Observation":
        """Validate a native Observation (dataclass or its dict)."""
        try:
            if isinstance(snapshot, dict):
                data = dict(snapshot)
            elif hasattr(snapshot, "to_dict"):
                data = dict(snapshot.to_dict())
            else:
                data = {
                    "timestamp": getattr(snapshot, "timestamp", None),
                    "text_content": getattr(snapshot, "text_content", None),
                    "metadata": dict(getattr(snapshot, "metadata", None) or {}),
                }
                fg = getattr(snapshot, "foreground_window", None)
                data["foreground_window"] = fg.to_dict() if hasattr(fg, "to_dict") else fg
                windows = getattr(snapshot, "all_windows", None) or []
                data["window_count"] = len(windows)
            return cls(
                timestamp=float(data.get("timestamp", 0.0) or 0.0),
                foreground_window=data.get("foreground_window"),
                window_count=int(data.get("window_count", 0) or 0),
                text_content=data.get("text_content"),
                metadata=dict(data.get("metadata", None) or {}),
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Observation shape: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# VERIFICATION CONTRACT (adapter over VerificationResult/verdicts)
# ============================================================

class Verification(BaseModel):
    """Validated verification verdict (boundary: GUIVerifier/helpers).

    A verdict without a reason is malformed — honesty requires the
    reason to travel with the boolean.
    """
    verified: bool = False
    reason: str = Field(..., min_length=1)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    operation: str = ""

    @classmethod
    def from_gui_result(cls, result: Any, operation: str = "") -> "Verification":
        """Validate a native VerificationResult."""
        try:
            evidence = getattr(result, "evidence", None) or {}
            return cls(
                verified=bool(getattr(result, "verified", False)),
                reason=str(getattr(result, "reason", "") or ""),
                evidence=dict(evidence),
                operation=operation,
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Verification shape: {exc}") from exc

    @classmethod
    def from_verdict(cls, operation: str, verdict: Dict[str, Any]) -> "Verification":
        """Validate a verification_helpers verdict dict."""
        try:
            return cls(
                verified=bool(verdict.get("verified", False)),
                reason=str(verdict.get("reason", "") or ""),
                evidence={k: v for k, v in verdict.items() if k not in ("verified", "reason")},
                operation=str(operation or ""),
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Verification verdict: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# RECOVERY CONTRACT (adapter over RecoveryResult)
# ============================================================

class Recovery(BaseModel):
    """Validated recovery outcome (boundary: RecoveryEngine)."""
    original_step_id: str = Field(..., min_length=1)
    recovered: bool = False
    strategies_attempted: List[str] = Field(default_factory=list)
    final_error: Optional[str] = None
    has_final_plan: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> "Recovery":
        if self.recovered and self.final_error is not None:
            raise ValueError("recovered=True requires final_error=None")
        if self.recovered and not self.has_final_plan:
            raise ValueError("recovered=True requires a final plan")
        return self

    @classmethod
    def from_recovery_result(cls, result: Any) -> "Recovery":
        """Validate a native RecoveryResult."""
        try:
            attempts = []
            for attempt in (getattr(result, "strategies_attempted", None) or []):
                name = getattr(attempt, "strategy_name", None)
                if isinstance(attempt, dict):
                    name = attempt.get("strategy_name", name)
                attempts.append(str(name or ""))
            final_plan = getattr(result, "final_plan", None)
            return cls(
                original_step_id=str(getattr(result, "original_step_id", "")),
                recovered=bool(getattr(result, "recovered", False)),
                strategies_attempted=attempts,
                final_error=getattr(result, "final_error", None),
                has_final_plan=final_plan is not None,
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Recovery shape: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ============================================================
# SESSION CONTRACT (adapter over serialized SessionState)
# ============================================================

class Session(BaseModel):
    """Validated session snapshot (boundary: SessionPersistence)."""
    version: str = ""
    current_application: Optional[str] = None
    applications: Dict[str, Any] = Field(default_factory=dict)
    browser: Optional[Dict[str, Any]] = None
    current_folder: Optional[str] = None
    recent_files: List[str] = Field(default_factory=list)
    recent_folders: List[str] = Field(default_factory=list)
    active_document: Optional[str] = None
    current_task: Optional[Dict[str, Any]] = None
    task_history_count: int = Field(default=0, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _coherent(self) -> "Session":
        if self.current_task is not None and not self.current_task.get("task_id"):
            raise ValueError("current_task without task_id is malformed")
        return self

    @classmethod
    def from_serialized(cls, data: Dict[str, Any]) -> "Session":
        """Validate serialized session state before persist/restore."""
        try:
            if not isinstance(data, dict):
                raise ValueError("session snapshot must be a dict")
            count = data.get("task_history_count", 0) or 0
            return cls(
                version=str(data.get("version", "") or ""),
                current_application=data.get("current_application"),
                applications=dict(data.get("applications", None) or {}),
                browser=data.get("browser"),
                current_folder=data.get("current_folder"),
                recent_files=[str(x) for x in (data.get("recent_files", None) or [])],
                recent_folders=[str(x) for x in (data.get("recent_folders", None) or [])],
                active_document=data.get("active_document"),
                current_task=data.get("current_task"),
                task_history_count=int(count),
                metadata=dict(data.get("metadata", None) or {}),
            )
        except (ValueError, TypeError) as exc:
            raise ContractViolationError(f"invalid Session shape: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
