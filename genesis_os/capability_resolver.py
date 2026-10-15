"""
Genesis OS — Level 3.8.6

Capability Resolver.

Resolves workflow capability requirements against the canonical
Genesis CapabilityRegistry.

This module performs resolution only.

It MUST NOT:
    - execute operating-system actions
    - launch applications
    - modify files
    - invoke ActionExecutor
    - bypass ExecutionSafety
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Iterable, List, Sequence

from .capabilities import (
    CapabilityDescriptor,
    CapabilityRequirement,
)
from .capability_registry import (
    CapabilityRegistry,
    CapabilityNotFoundError,
)
from .capability_resolution import (
    CapabilityResolutionEvidence,
    CapabilityResolutionStatus,
    ResolvedCapability,
)
from genesis_os.contracts import Capability as CapabilityContract


class CapabilityUnavailableError(RuntimeError):
    """Raised when an explicitly requested capability is unavailable."""


class CapabilityResolver:
    """
    Deterministic capability resolver.

    Resolution precedence:

        1. exact capability ID
        2. exact operation compatibility
        3. declared requirement compatibility
        4. capability availability
        5. priority

    No execution occurs here.
    """

    VERSION = "3.8.6"

    def __init__(
        self,
        registry: type[CapabilityRegistry] = CapabilityRegistry,
        provider_registry: Any = None,
    ) -> None:
        self._registry = registry
        self._provider_registry = provider_registry

    def resolve(
        self,
        requirement: CapabilityRequirement,
    ) -> ResolvedCapability:
        """
        Resolve one capability requirement.

        A requirement must never cause execution as a side effect.
        """

        if requirement is None:
            return ResolvedCapability(
                status=CapabilityResolutionStatus.UNSUPPORTED,
                explanation=(
                    "No capability requirement was provided."
                ),
            )

        raw_capability_id = str(
            getattr(requirement, "capability_id", "") or ""
        ).strip()
        capability_id = self._normalize(raw_capability_id)

        operation = self._normalize(
            getattr(
                requirement,
                "operation",
                None,
            )
        )

        # ----------------------------------------------------
        # 1. Exact capability identity
        # ----------------------------------------------------

        if capability_id:
            try:
                capability = self._registry.get(
                    raw_capability_id or capability_id
                )
            except CapabilityNotFoundError:
                capability = None

            if capability is not None:
                return self._resolve_exact(
                    requirement=requirement,
                    capability=capability,
                    operation=operation,
                )

            raise CapabilityUnavailableError(
                f"Capability '{capability_id}' is not registered."
            )

        # ----------------------------------------------------
        # 2. Candidate discovery
        # ----------------------------------------------------

        candidates = self._find_candidates(
            requirement=requirement,
            operation=operation,
        )

        if not candidates:
            return ResolvedCapability(
                status=CapabilityResolutionStatus.UNSUPPORTED,
                requirement=requirement,
                explanation=(
                    "No registered Genesis capability can "
                    "satisfy this requirement."
                ),
            )

        ranked = self._rank_candidates(
            requirement=requirement,
            candidates=candidates,
        )

        best = ranked[0]
        best_capability, best_score, best_evidence = best

        alternatives = tuple(
            item[0]
            for item in ranked[1:]
        )

        # ----------------------------------------------------
        # 3. Confidence / ambiguity gate
        # ----------------------------------------------------

        if best_score < 0.60:
            return ResolvedCapability(
                status=CapabilityResolutionStatus.UNSUPPORTED,
                requirement=requirement,
                confidence=best_score,
                evidence=tuple(best_evidence),
                alternatives=alternatives,
                explanation=(
                    "A registered capability was found, but "
                    "the match confidence is insufficient."
                ),
            )

        if len(ranked) > 1:
            second_score = ranked[1][1]

            if (
                math.isfinite(second_score)
                and abs(best_score - second_score)
                < 0.05
            ):
                return ResolvedCapability(
                    status=CapabilityResolutionStatus.AMBIGUOUS,
                    requirement=requirement,
                    confidence=best_score,
                    evidence=tuple(best_evidence),
                    alternatives=alternatives,
                    explanation=(
                        "Multiple capabilities are similarly "
                        "well matched. Genesis will not guess."
                    ),
                )

        # ----------------------------------------------------
        # 4. Availability gate
        # ----------------------------------------------------

        if not best_capability.is_available:
            return ResolvedCapability(
                status=CapabilityResolutionStatus.UNAVAILABLE,
                capability=best_capability,
                requirement=requirement,
                confidence=best_score,
                evidence=tuple(best_evidence),
                alternatives=alternatives,
                explanation=(
                    "The capability exists but is currently "
                    "unavailable."
                ),
            )

        # Phase 1 contract: the selected descriptor must satisfy
        # the Capability boundary before a RESOLVED verdict ships.
        CapabilityContract.from_descriptor(best_capability)

        return ResolvedCapability(
            status=CapabilityResolutionStatus.RESOLVED,
            capability=best_capability,
            requirement=requirement,
            confidence=best_score,
            evidence=tuple(best_evidence),
            alternatives=alternatives,
            explanation=(
                f"Resolved capability "
                f"'{best_capability.capability_id}' "
                f"for the requested workflow operation."
            ),
        )

    def resolve_operation(
        self,
        operation: str,
        *,
        description: str = "",
        inputs: Iterable[str] = (),
        required_permissions: Iterable[str] = (),
    ) -> ResolvedCapability:
        """
        Resolve an already-decided operation identifier.

        This is a PROBE, not an explicit capability request, so it
        must never raise. Callers (workflow_decision, genesis
        run_level3) feed it raw decision intents that are not
        guaranteed to be registered capability IDs. An unknown or
        empty operation therefore yields a typed UNSUPPORTED
        result that callers can inspect, instead of an exception
        that would abort an otherwise valid request.
        """

        raw_operation = str(operation or "").strip()
        operation = self._normalize(raw_operation)

        if not operation:
            return self._unresolved_operation(
                raw_operation,
                "No operation was provided to resolve.",
            )

        descriptor = None
        if raw_operation:
            try:
                descriptor = self._registry.get(raw_operation)
            except CapabilityNotFoundError:
                descriptor = None

        if descriptor is None:
            return self._unresolved_operation(
                raw_operation,
                (
                    f"Operation '{raw_operation}' is not a registered "
                    "Genesis capability."
                ),
            )

        requirement = CapabilityRequirement(
            capability_id=descriptor.capability_id,
            category=descriptor.category,
            operation=descriptor.operation,
            description=description,
            required_inputs=frozenset(
                set(inputs)
                & set(
                    getattr(
                        descriptor,
                        "supported_inputs",
                        (),
                    )
                    or ()
                )
            ),
            required_permissions=frozenset(required_permissions),
        )

        try:
            return self.resolve(requirement)
        except CapabilityUnavailableError as exc:
            # Registry changed underneath us between the lookup above
            # and resolve(). Report it as a typed result, never an
            # exception.
            return ResolvedCapability(
                status=CapabilityResolutionStatus.UNAVAILABLE,
                requirement=requirement,
                explanation=str(exc),
            )

    def _unresolved_operation(
        self,
        operation: str,
        explanation: str,
    ) -> ResolvedCapability:
        """Typed, evidence-carrying unresolved result."""

        return ResolvedCapability(
            status=CapabilityResolutionStatus.UNSUPPORTED,
            explanation=explanation,
            evidence=(
                CapabilityResolutionEvidence(
                    match_type="unknown_operation",
                    score=0.0,
                    reason=explanation,
                ),
            ),
        )

    def _resolve_exact(
        self,
        *,
        requirement: CapabilityRequirement,
        capability: CapabilityDescriptor,
        operation: str,
    ) -> ResolvedCapability:
        """
        Resolve an exact capability ID.

        Exact identity receives the highest confidence, but the
        operation still has to be compatible.
        """

        capability_operation = self._normalize(
            getattr(
                capability,
                "operation",
                None,
            )
        )
        required_inputs = set(
            getattr(requirement, "required_inputs", None) or ()
        )
        if required_inputs and not required_inputs <= set(
            getattr(capability, "supported_inputs", None) or ()
        ):
            return ResolvedCapability(
                status=CapabilityResolutionStatus.UNSUPPORTED,
                requirement=requirement,
                explanation=(
                    f"Capability '{capability.capability_id}' "
                    f"does not support all required inputs."
                ),
            )
        required_permissions = set(
            getattr(requirement, "required_permissions", None) or ()
        )
        if required_permissions and not required_permissions <= set(
            getattr(capability, "permissions", None) or ()
        ):
            return ResolvedCapability(
                status=CapabilityResolutionStatus.UNSUPPORTED,
                requirement=requirement,
                explanation=(
                    f"Capability '{capability.capability_id}' "
                    f"does not grant all required permissions."
                ),
            )

        if (
            operation
            and capability_operation
            and operation != capability_operation
            and operation != capability.capability_id
        ):
            return ResolvedCapability(
                status=CapabilityResolutionStatus.UNSUPPORTED,
                requirement=requirement,
                explanation=(
                    f"Capability '{capability.capability_id}' "
                    f"does not support operation '{operation}'."
                ),
            )

        evidence = CapabilityResolutionEvidence(
            match_type="exact_capability_id",
            score=1.0,
            reason=(
                "The requested capability ID exactly matches "
                "a registered Genesis capability."
            ),
        )

        if not capability.is_available:
            return ResolvedCapability(
                status=CapabilityResolutionStatus.UNAVAILABLE,
                capability=capability,
                requirement=requirement,
                confidence=1.0,
                evidence=(evidence,),
                explanation=(
                    f"Capability '{capability.capability_id}' "
                    "is registered but unavailable."
                ),
            )

        # Phase 1 contract: exact-ID hits satisfy it too.
        CapabilityContract.from_descriptor(capability)

        # =================================================
        # DECLARED PRECONDITIONS — ENFORCED
        # =================================================
        # Roadmap task 3 requires preconditions to be part of
        # capability ranking, not decoration.
        #
        # Previously `preconditions` were read only inside
        # `_rank_candidates` (see the "Explicit preconditions"
        # block there), where they were a score nudge of +0.03 per
        # met and -0.05 per unmet, AND the whole block was skipped
        # unless the requirement itself declared inputs. A
        # requirement declaring nothing therefore resolved
        # unconditionally: document.transform declaring
        # ("output_path", "output_format") resolved successfully
        # while supplying neither.
        #
        # Every declared precondition in the registry is a REQUIRED
        # INPUT name — verified across all 17 precondition-bearing
        # capabilities and 23 preconditions, every one of which is
        # also that capability's declared supported input. There is
        # no prior-state or target-existence precondition anywhere,
        # so one mechanism covers the registry and no per-capability
        # mapping is needed.
        #
        # A precondition counts as satisfied when the input was
        # explicitly supplied (required_inputs) or is declared as
        # optional/context-resolvable (optional_inputs).
        #
        # Unmet preconditions do NOT resolve. UNAVAILABLE is used
        # rather than a new status: the capability exists and is
        # enabled, it simply cannot be used as specified until the
        # missing inputs exist. The explanation names exactly which
        # are missing, and the evidence entry makes it inspectable.
        #
        # Strict no-op for the 124 capabilities with no declared
        # preconditions: `preconditions` is empty, the loop body
        # never runs, and the RESOLVED return below is unchanged.
        preconditions = tuple(
            getattr(capability, "preconditions", None) or ()
        )
        if preconditions:
            supplied = set(
                getattr(requirement, "required_inputs", None) or ()
            ) | set(
                getattr(requirement, "optional_inputs", None) or ()
            )
            unmet = tuple(
                name for name in preconditions if name not in supplied
            )
            if unmet:
                return ResolvedCapability(
                    status=CapabilityResolutionStatus.UNAVAILABLE,
                    capability=capability,
                    requirement=requirement,
                    confidence=0.0,
                    evidence=(
                        evidence,
                        CapabilityResolutionEvidence(
                            match_type="preconditions_unmet",
                            score=0.0,
                            reason=(
                                f"{len(preconditions) - len(unmet)}/"
                                f"{len(preconditions)} preconditions "
                                f"satisfied; missing: "
                                f"{', '.join(unmet)}."
                            ),
                        ),
                    ),
                    explanation=(
                        f"Exact capability "
                        f"'{capability.capability_id}' was matched, but "
                        f"its declared preconditions are unmet: "
                        f"{', '.join(unmet)}. Supply the missing "
                        f"input(s) before this capability can be used."
                    ),
                )

        return ResolvedCapability(
            status=CapabilityResolutionStatus.RESOLVED,
            capability=capability,
            requirement=requirement,
            confidence=1.0,
            evidence=(evidence,),
            explanation=(
                f"Exact capability '{capability.capability_id}' "
                "was resolved."
            ),
        )

    def _find_candidates(
        self,
        *,
        requirement: CapabilityRequirement,
        operation: str,
    ) -> List[CapabilityDescriptor]:
        """
        Discover candidates without executing anything.
        """

        candidates = list(
            self._registry.all()
        )
        required_permissions = set(
            getattr(requirement, "required_permissions", None) or ()
        )
        if required_permissions:
            candidates = [
                capability
                for capability in candidates
                if required_permissions
                <= set(getattr(capability, "permissions", None) or ())
            ]
        required_category = getattr(requirement, "category", None)
        if (
            required_category is not None
            and getattr(required_category, "value", required_category)
            != "general"
        ):
            candidates = [
                capability
                for capability in candidates
                if getattr(capability, "category", None)
                == required_category
            ]

        if operation:
            matching = [
                capability
                for capability in candidates
                if self._normalize(
                    getattr(
                        capability,
                        "operation",
                        None,
                    )
                )
                == operation
            ]

            return matching

        return candidates

    def _rank_candidates(
        self,
        *,
        requirement: CapabilityRequirement,
        candidates: Sequence[CapabilityDescriptor],
    ) -> List[
        tuple[
            CapabilityDescriptor,
            float,
            List[CapabilityResolutionEvidence],
        ]
    ]:
        """
        Rank candidates deterministically (Phase 3 control plane).

        Score components (all evidenced, all deterministic):

            operation match ......... +0.60
            input coverage .......... +0.15 scaled (vacuous +0.10)
            availability ............ +0.05 static, live cache on top
            priority ................ +0.10 capped (legacy)
            description affinity .... +0.05 scaled
            preconditions ........... +0.03 each met / -0.05 each unmet
            risk tier ............... -0.00/-0.02/-0.05/-0.10
            no input overlap ........ -0.10 (when inputs declared)

        Keywords/regex remain the fast hint path upstream; this
        ranking is what makes selection semantic, context-aware,
        and risk-aware without embeddings.
        """

        from genesis_os.capabilities import RISK_PENALTIES

        operation = self._normalize(
            getattr(
                requirement,
                "operation",
                None,
            )
        )

        required_inputs = set(
            getattr(requirement, "required_inputs", None) or ()
        )
        optional_inputs = set(
            getattr(requirement, "optional_inputs", None) or ()
        )
        declared_inputs = required_inputs | optional_inputs

        requirement_text = " ".join(
            str(part or "")
            for part in (
                operation,
                getattr(requirement, "capability_id", ""),
                getattr(requirement, "description", ""),
            )
        )
        requirement_tokens = set(
            self._normalize(requirement_text).split()
        )

        live_chains = self._live_provider_chains()

        ranked = []

        for capability in candidates:
            capability_operation = self._normalize(
                getattr(
                    capability,
                    "operation",
                    None,
                )
            )

            score = 0.0
            evidence: List[
                CapabilityResolutionEvidence
            ] = []

            # --- 1. Operation match ---
            if (
                operation
                and capability_operation == operation
            ):
                score += 0.60

                evidence.append(
                    CapabilityResolutionEvidence(
                        match_type="operation",
                        score=0.60,
                        reason=(
                            "Capability operation matches "
                            "the workflow requirement."
                        ),
                    )
                )

            # --- 2. Input coverage (preconditions-aware) ---
            supported = set(
                getattr(capability, "supported_inputs", None) or ()
            )
            if not required_inputs:
                score += 0.10
                evidence.append(
                    CapabilityResolutionEvidence(
                        match_type="inputs_vacuous",
                        score=0.10,
                        reason=(
                            "Requirement declares no inputs; "
                            "no input conflict possible."
                        ),
                    )
                )
            else:
                covered = required_inputs & supported
                coverage = len(covered) / len(required_inputs)
                score += 0.15 * coverage
                evidence.append(
                    CapabilityResolutionEvidence(
                        match_type="input_coverage",
                        score=round(0.15 * coverage, 4),
                        reason=(
                            f"{len(covered)}/{len(required_inputs)} "
                            "required inputs supported."
                        ),
                    )
                )
                if not covered:
                    score -= 0.10
                    evidence.append(
                        CapabilityResolutionEvidence(
                            match_type="input_mismatch",
                            score=-0.10,
                            reason=(
                                "None of the required inputs "
                                "are supported."
                            ),
                        )
                    )

            # --- 3. Explicit preconditions (only when the
            # requirement declares inputs to judge against) ---
            preconditions = tuple(
                getattr(capability, "preconditions", None) or ()
            )
            if preconditions and declared_inputs:
                met = sum(
                    1 for p in preconditions if p in declared_inputs
                )
                unmet = len(preconditions) - met
                score += min(0.03 * met, 0.09)
                score -= 0.05 * unmet
                evidence.append(
                    CapabilityResolutionEvidence(
                        match_type="preconditions",
                        score=round(min(0.03 * met, 0.09) - 0.05 * unmet, 4),
                        reason=(
                            f"{met}/{len(preconditions)} "
                            "preconditions satisfied."
                        ),
                    )
                )

            # --- 4. Availability: static flag + live cache ---
            if capability.is_available:
                score += 0.05

                evidence.append(
                    CapabilityResolutionEvidence(
                        match_type="availability",
                        score=0.05,
                        reason=(
                            "Capability is currently "
                            "available."
                        ),
                    )
                )
            else:
                score -= 0.20
                evidence.append(
                    CapabilityResolutionEvidence(
                        match_type="availability",
                        score=-0.20,
                        reason="Capability is not available.",
                    )
                )

            live = live_chains.get(
                getattr(capability, "capability_id", ""), None
            )
            if live is not None:
                cached = live.get("results", [])
                observed = [
                    r for r in cached if r is not None
                ]
                if observed and all(r is False for r in observed):
                    score -= 0.15
                    evidence.append(
                        CapabilityResolutionEvidence(
                            match_type="provider_health",
                            score=-0.15,
                            reason=(
                                "All registered providers "
                                "last checked unhealthy."
                            ),
                        )
                    )
                elif observed and any(r is True for r in observed):
                    score += 0.05
                    evidence.append(
                        CapabilityResolutionEvidence(
                            match_type="provider_health",
                            score=0.05,
                            reason=(
                                "A registered provider last "
                                "checked healthy."
                            ),
                        )
                    )
                elif not observed:
                    # Honest reporting: no real health observation
                    # exists yet, so health neither helps nor
                    # penalises the score. Ranking never runs
                    # health checks itself.
                    evidence.append(
                        CapabilityResolutionEvidence(
                            match_type="provider_health",
                            score=0.0,
                            reason=(
                                "No provider health check has run "
                                "for this capability yet; health "
                                "is unknown and unscored."
                            ),
                        )
                    )
                if live.get("chain_length", 0) > 1:
                    score += 0.03
                    evidence.append(
                        CapabilityResolutionEvidence(
                            match_type="provider_redundancy",
                            score=0.03,
                            reason="Provider fallback chain exists.",
                        )
                    )

            # --- 5. Priority (legacy, capped) ---
            priority = getattr(
                capability,
                "priority",
                0,
            )

            if isinstance(priority, int):
                score += min(
                    max(priority, 0) / 100.0,
                    0.10,
                )

            # --- 6. Description affinity (token overlap) ---
            descriptor_text = " ".join(
                str(part or "")
                for part in (
                    capability_operation,
                    getattr(capability, "capability_id", ""),
                    getattr(capability, "description", ""),
                )
            )
            descriptor_tokens = set(
                self._normalize(descriptor_text).split()
            )
            if requirement_tokens and descriptor_tokens:
                overlap = requirement_tokens & descriptor_tokens
                affinity = len(overlap) / len(requirement_tokens)
                if affinity > 0:
                    score += 0.05 * affinity
                    evidence.append(
                        CapabilityResolutionEvidence(
                            match_type="description_affinity",
                            score=round(0.05 * affinity, 4),
                            reason=(
                                f"{len(overlap)} shared "
                                "description terms."
                            ),
                        )
                    )

            # --- 7. Risk tier (penalty only; resolution of
            # risky capabilities still succeeds — downstream
            # confirmation handles authorization) ---
            risk = str(
                getattr(capability, "risk_level", "low") or "low"
            ).lower()
            penalty = RISK_PENALTIES.get(risk, 0.0)
            if penalty:
                score -= penalty
                evidence.append(
                    CapabilityResolutionEvidence(
                        match_type="risk_tier",
                        score=-penalty,
                        reason=f"Capability risk tier: {risk}.",
                    )
                )

            # --- 8. Deterministic disambiguation (post-rank adjustment) ---
            # Fixes 3 known misroutes where keyword/regex hints upstream
            # produce near-tie scores and the wrong capability wins:
            #   (a) folder.organize -> file.move
            #   (b) browser.search -> web.research
            #   (c) cleanup.empty_recycle_bin -> cleanup.recycle_bin_query
            # All checks are pure lowercase substring tests on the
            # requirement text (operation + capability_id + description),
            # hence fully deterministic. Boosts are evidenced below.
            req_lower = requirement_text.lower()
            capability_id = getattr(capability, "capability_id", "") or ""
            if "organiz" in req_lower and "folder" in req_lower:
                if capability_id == "folder.organize":
                    score += 0.20
                    evidence.append(
                        CapabilityResolutionEvidence(
                            match_type="disambiguation_organize_folder",
                            score=0.20,
                            reason=(
                                "Requirement mentions organize + folder; "
                                "boost folder.organize over file.move."
                            ),
                        )
                    )
            if "search" in req_lower and (
                "browser" in req_lower
                or "web page" in req_lower
                or "webpage" in req_lower
            ):
                if capability_id == "browser.search":
                    score += 0.20
                    evidence.append(
                        CapabilityResolutionEvidence(
                            match_type="disambiguation_browser_search",
                            score=0.20,
                            reason=(
                                "Requirement mentions browser/web page + "
                                "search; boost browser.search over "
                                "web.research."
                            ),
                        )
                    )
            if "empty" in req_lower and "recycle" in req_lower:
                if capability_id == "cleanup.empty_recycle_bin":
                    score += 0.20
                    evidence.append(
                        CapabilityResolutionEvidence(
                            match_type="disambiguation_empty_recycle",
                            score=0.20,
                            reason=(
                                "Requirement mentions empty + recycle; "
                                "boost cleanup.empty_recycle_bin over "
                                "cleanup.recycle_bin_query."
                            ),
                        )
                    )

            score = min(max(score, 0.0), 1.0)

            ranked.append(
                (
                    capability,
                    score,
                    evidence,
                )
            )

        ranked.sort(
            key=lambda item: (
                -item[1],
                -getattr(
                    item[0],
                    "priority",
                    0,
                ),
                item[0].capability_id,
            )
        )

        return ranked

    def _live_provider_registry(self) -> Any:
        """
        The registry that actually carries live provider health.

        Defaults to the process-wide shared instance. A freshly
        constructed registry reports every provider as
        ``last_health_check_result=None``, which makes health-aware
        ranking silently inert — so a throwaway instance is never
        used unless one was explicitly injected.
        """

        registry = self._provider_registry
        if registry is not None:
            return registry

        try:
            from genesis_os.capability_provider_registry import (
                CapabilityProviderRegistry,
            )
            return CapabilityProviderRegistry.get_shared()
        except Exception:
            return None

    def _provider_chain_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """
        Cached-only view of provider chains.

        Reads last health-check results WITHOUT triggering new
        checks — ranking must never run subprocess probes.
        """
        snapshot: Dict[str, Dict[str, Any]] = {}
        registry = self._live_provider_registry()
        if registry is None:
            return snapshot
        try:
            for capability_id in registry.capability_ids():
                chain = registry.get_provider_chain(capability_id)
                snapshot[capability_id] = {
                    "chain_length": len(chain),
                    "results": [
                        entry.last_health_check_result
                        for entry in chain
                    ],
                }
        except Exception:
            pass
        return snapshot

    def _live_provider_chains(self) -> Dict[str, Dict[str, Any]]:
        now = time.monotonic()
        cache = self.__dict__.get("_provider_chain_cache")
        updated_at = self.__dict__.get("_provider_chain_cache_at", 0.0)
        if cache is None or now - updated_at >= 30.0:
            cache = self._provider_chain_snapshot()
            self.__dict__["_provider_chain_cache"] = cache
            self.__dict__["_provider_chain_cache_at"] = now
        return cache

    @staticmethod
    def _normalize(
        value: Any,
    ) -> str:
        if value is None:
            return ""

        return " ".join(
            str(value)
            .strip()
            .lower()
            .replace("_", " ")
            .replace("-", " ")
            .split()
        )