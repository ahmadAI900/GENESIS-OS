"""
Genesis OS — Level 3.8.6

Capability Resolution Models.

This module defines the result contract produced when Genesis
maps a workflow capability requirement onto a registered
capability.

Resolution is deliberately separate from execution.

The resolver answers:

    "Which Genesis capability can satisfy this requirement?"

It does NOT answer:

    "Execute it."

Execution remains owned by the established Level 3
ActionPlan -> Safety -> Executor pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .capabilities import CapabilityDescriptor
from .capability_registry import Capability


class CapabilityResolutionStatus(str, Enum):
    """
    Canonical outcome of capability resolution.
    """

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CapabilityResolutionEvidence:
    """
    Explains why a capability was selected.

    Evidence is intentionally structured rather than represented
    only as a free-form explanation so later workflow layers can
    inspect it programmatically.
    """

    match_type: str
    score: float
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_type": self.match_type,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ResolvedCapability:
    """
    Immutable result of capability resolution.

    This object contains no execution state.

    It is safe to pass from capability resolution into
    dynamic workflow planning.
    """

    status: CapabilityResolutionStatus

    capability: Optional[CapabilityDescriptor] = None

    confidence: float = 0.0

    requirement: Optional[Any] = None

    evidence: Tuple[
        CapabilityResolutionEvidence,
        ...
    ] = ()

    alternatives: Tuple[
        CapabilityDescriptor,
        ...
    ] = ()

    explanation: str = ""

    @property
    def resolved(self) -> bool:
        return (
            self.status
            == CapabilityResolutionStatus.RESOLVED
            and self.capability is not None
        )

    @property
    def dangerous(self) -> bool:
        """
        Propagate the established Level 3 safety classification.

        The resolver never changes safety policy. It only exposes
        the selected capability's existing safety metadata.
        """

        if self.capability is None:
            return False

        return self.capability.dangerous

    @property
    def requires_confirmation(self) -> bool:
        """
        Propagate confirmation metadata from the resolved
        capability.
        """

        if self.capability is None:
            return False

        metadata = self.capability.metadata or {}

        return bool(
            metadata.get(
                "confirmation_required",
                metadata.get(
                    "requires_confirmation",
                    False,
                ),
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "capability": (
                self.capability.to_dict()
                if self.capability is not None
                else None
            ),
            "confidence": self.confidence,
            "requirement": (
                self.requirement.to_dict()
                if hasattr(self.requirement, "to_dict")
                else self.requirement
            ),
            "evidence": [
                item.to_dict()
                for item in self.evidence
            ],
            "alternatives": [
                item.to_dict()
                for item in self.alternatives
            ],
            "explanation": self.explanation,
            "dangerous": self.dangerous,
            "requires_confirmation": (
                self.requires_confirmation
            ),
        }


def capability_resolution_metadata(
    resolution: Optional[ResolvedCapability],
) -> Dict[str, Any]:
    """
    Flatten a resolution into decision-layer metadata.

    Callers need the FULL verdict, not just status/id/confidence:
    safety classification (dangerous, requires_confirmation), risk
    tier, provider, ranked evidence, and the alternatives that were
    rejected are all required to make an auditable routing decision
    downstream. This is the single definition of that payload so the
    workflow-decision layer and the genesis runtime cannot drift.
    """

    if resolution is None:
        return {
            "status": CapabilityResolutionStatus.UNSUPPORTED.value,
            "capability_id": None,
            "capability": None,
            "confidence": 0.0,
            "dangerous": False,
            "requires_confirmation": False,
            "risk_level": None,
            "provider": None,
            "category": None,
            "operation": None,
            "explanation": (
                "No capability resolution was performed."
            ),
            "evidence": [],
            "alternatives": [],
            "alternatives_count": 0,
        }

    capability = resolution.capability
    payload = resolution.capability.to_dict() if capability is not None else {}

    return {
        "status": resolution.status.value,
        "capability_id": (
            capability.capability_id
            if capability is not None
            else None
        ),
        "capability": payload or None,
        "confidence": resolution.confidence,
        "dangerous": resolution.dangerous,
        "requires_confirmation": (
            resolution.requires_confirmation
        ),
        "risk_level": (
            str(getattr(capability, "risk_level", "") or "") or None
            if capability is not None
            else None
        ),
        "provider": (
            getattr(capability, "provider", None)
            if capability is not None
            else None
        ),
        "category": (
            getattr(
                getattr(capability, "category", None),
                "value",
                getattr(capability, "category", None),
            )
            if capability is not None
            else None
        ),
        "operation": (
            getattr(capability, "operation", None)
            if capability is not None
            else None
        ),
        "explanation": resolution.explanation,
        "evidence": [
            item.to_dict() for item in resolution.evidence
        ],
        "alternatives": [
            item.to_dict() for item in resolution.alternatives
        ],
        "alternatives_count": len(resolution.alternatives),
    }
# =========================================================
# SEMANTIC GROUNDING RESULT
# =========================================================


@dataclass(frozen=True)
class GroundingResult:
    """
    Verdict on whether a request genuinely asks Genesis to perform a
    registered computer capability.

    This is the reusable evidence object for the semantic selection
    layer. It exists because the lexical actionability probes cannot
    decide the question they are being asked: a real indirect command
    and ordinary conversation produce identical probe signals, so the
    answer has to come from semantics and has to be checkable.

    The verdict is deliberately CONSERVATIVE and built from evidence
    the rest of the system already produces:

      * FIDELITY. The model must quote a span that actually occurs in
        the request. This is the load-bearing check and the main
        defence against a fabricated justification.
      * SUBSTANCE. That span must contain a content word. A span made
        of function words and pronouns grounds nothing.
      * VALIDITY. The capability must be canonical and registered.
      * POLICY. Safety/authorization is consulted and is never
        bypassed. A capability that needs confirmation still passes
        and is handed to the existing approval flow.
      * RESOLUTION. The existing CapabilityResolver must independently
        agree, and its confidence and evidence are carried through.

    Deliberately NOT a requirement: lexical overlap between the span
    and the capability description. An indirect request ("note it down
    somewhere") names nothing in the description, and demanding that
    would reintroduce the very keyword rule this replaces. That
    figure is reported as `relevance` for consumers that want it.

    This object carries the descriptor facts a later stage needs for
    cross-domain arbitration (domain, category, operation, declared
    inputs, target, application, risk, alternatives) but implements no
    arbitration itself. Consuming layers must not infer policy from
    these fields.
    """

    grounded: bool

    lexical_tier: str = "ambiguous"

    capability_id: Optional[str] = None

    domain: Optional[str] = None

    category: Optional[str] = None

    operation: Optional[str] = None

    anchor: str = ""

    fidelity: bool = False

    substance: bool = False

    # A span that covers the WHOLE request proves nothing: it is
    # equally verbatim for every possible capability, so it cannot
    # discriminate this candidate from any other. MEASURED: a vague
    # request whose specific anchor correctly FAILED grounding was
    # accepted at full strength when the model quoted the entire
    # request back. Faithfulness is not discriminativeness.
    discriminative: bool = False

    relevance: float = 0.0

    confidence: float = 0.0

    declared_inputs: Tuple[str, ...] = ()

    target: Optional[str] = None

    application: Optional[str] = None

    risk_level: Optional[str] = None

    requires_confirmation: bool = False

    policy_allowed: bool = False

    status: Optional[str] = None

    alternatives: Tuple[str, ...] = ()

    evidence: Tuple[CapabilityResolutionEvidence, ...] = ()

    reasons: Tuple[str, ...] = ()

    @property
    def strength(self) -> float:
        """
        0.0-1.0 summary for confidence comparison between candidates.

        Fidelity and substance are hard gates, so they are weighted
        rather than averaged: an unfaithful or contentless anchor
        cannot be offset by high resolver confidence. `relevance` is
        excluded by design (see class docstring).
        """
        if not (self.fidelity and self.substance and self.discriminative):
            return 0.0
        return round(0.6 + 0.4 * float(self.confidence), 4)

    def to_dict(self) -> Dict[str, Any]:
        """Flat payload for decision-layer metadata and audit."""
        payload: Dict[str, Any] = {
            "grounded": self.grounded,
            "lexical_tier": self.lexical_tier,
            "capability_id": self.capability_id,
            "domain": self.domain,
            "category": self.category,
            "operation": self.operation,
            "anchor": self.anchor,
            "fidelity": self.fidelity,
            "substance": self.substance,
            "discriminative": self.discriminative,
            "relevance": self.relevance,
            "confidence": self.confidence,
            "declared_inputs": list(self.declared_inputs),
            "target": self.target,
            "application": self.application,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "policy_allowed": self.policy_allowed,
            "status": self.status,
            "alternatives": list(self.alternatives),
            "strength": self.strength,
            "evidence": [item.to_dict() for item in self.evidence],
            "reasons": list(self.reasons),
        }
        return payload

# =========================================================
# CROSS-DOMAIN CAPABILITY ARBITRATION RESULT
# =========================================================


@dataclass(frozen=True)
class ArbitrationResult:
    """
    Outcome of comparing a deterministic candidate against a
    semantically grounded candidate.

    WHY THIS EXISTS
    ---------------
    Deterministic routing answered first and returned before the
    semantic layer could be consulted. The hook that could raise a
    challenge only compared siblings INSIDE the matched capability's
    own domain, so a cross-domain mistake could never be detected —
    by construction, not by accident.

    The arbitration is therefore capability-first: both sides are
    concrete REGISTERED capability ids carrying their own structured
    evidence, never phrases, and neither domain is privileged.

    SELECTION RULES (conservative by construction)
    -----------------------------------------------
      * No arbitration, or arbitration inconclusive  -> DETERMINISTIC
      * Semantic candidate not grounded / not registered /
        not permitted by policy                      -> DETERMINISTIC
      * Semantic candidate selected only when it wins a
        capability-first comparison AND justifies itself
        with a span that is verbatim in the request   -> SEMANTIC
      * Ties always resolve to DETERMINISTIC.

    MEASURED PROBING NOTE
    ---------------------
    Three purely local signals were tested as an arbitration
    trigger before this design was chosen, and all three FAILED, so
    none is used here:

      * top per-domain vocabulary evidence — domain vocabularies
        differ in size by 15x, so a single incidental hit in a small
        domain outranked every genuine hit in a large one;
      * operation-token sharing — caught some classes, protected the
        Phase 0 guard, but missed others;
      * description affinity — tied on nearly every real request,
        because the request rarely repeats the description's words.

    Local lexical signal does not carry enough information to
    arbitrate. The comparison therefore happens in the semantic
    layer, where it is a comparison between two NAMED capabilities,
    which is a far easier question than open-ended selection.
    """

    selected: str  # "deterministic" or "semantic"

    arbitration_occurred: bool = False

    deterministic_capability: Optional[str] = None

    semantic_capability: Optional[str] = None

    selected_source: Optional[str] = None

    outcome: str = "inconclusive"

    deterministic_confidence: float = 0.0

    semantic_confidence: float = 0.0

    deterministic_strength: float = 0.0

    semantic_strength: float = 0.0

    deterministic_anchored: bool = False

    approval_required: bool = False

    reason: str = ""

    semantic_anchor: str = ""

    anchor_faithful: bool = False

    semantic_grounded: bool = False

    deterministic_evidence: Tuple[CapabilityResolutionEvidence, ...] = ()

    semantic_evidence: Tuple[CapabilityResolutionEvidence, ...] = ()

    policy_allowed: bool = False

    risk_level: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected": self.selected,
            "selected_source": self.selected_source,
            "outcome": self.outcome,
            "arbitration_occurred": self.arbitration_occurred,
            "deterministic_confidence": self.deterministic_confidence,
            "semantic_confidence": self.semantic_confidence,
            "deterministic_strength": self.deterministic_strength,
            "semantic_strength": self.semantic_strength,
            "deterministic_anchored": self.deterministic_anchored,
            "approval_required": self.approval_required,
            "deterministic_capability": self.deterministic_capability,
            "semantic_capability": self.semantic_capability,
            "reason": self.reason,
            "semantic_anchor": self.semantic_anchor,
            "anchor_faithful": self.anchor_faithful,
            "semantic_grounded": self.semantic_grounded,
            "policy_allowed": self.policy_allowed,
            "risk_level": self.risk_level,
            "deterministic_evidence": [
                item.to_dict() for item in self.deterministic_evidence
            ],
            "semantic_evidence": [
                item.to_dict() for item in self.semantic_evidence
            ],
        }
