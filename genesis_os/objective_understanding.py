"""
Genesis OS — Level 3.9 Objective Understanding.

Objective understanding converts one human request into a structured set of
intent-bearing workflow steps. It deliberately does not execute anything and
does not construct an executable WorkflowPlan. Planning remains a separate
responsibility.

Pipeline:

    Natural language objective
        -> ObjectiveUnderstanding
        -> structured step intents (with goal, entities, constraints, dependencies, required capabilities)
        -> WorkflowPlanner
        -> UniversalDesktopWorkflowEngine

The implementation reuses the existing WorkflowDecisionEngine rather than
creating a second intent taxonomy.

Key enhancement (Level 3.9): Extracts rich semantic information from objectives
including goal, entities, constraints, dependencies, required capabilities,
required agents, expected result, risk, and verification requirements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from genesis_os.contracts import Objective as ObjectiveContract


class ObjectiveUnderstandingError(ValueError):
    """Raised when an objective cannot be safely understood."""


@dataclass(frozen=True)
class ObjectiveStepIntent:
    """One understood part of a user's objective.

    Enhanced with rich semantic information for capability-driven planning.
    """

    step_id: str
    text: str
    sequence: int
    decision: Dict[str, Any]
    confidence: float
    level: int
    mode: str
    operation: Optional[str] = None
    target: Optional[str] = None
    application: Optional[str] = None
    requires_clarification: bool = False
    clarification_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ===== Level 3.9: Rich Semantic Information =====
    # These fields enable capability-driven planning
    goal: Optional[str] = None                    # What the user wants to achieve
    intent: Optional[str] = None                  # High-level intent category
    entities: Tuple[Dict[str, Any], ...] = ()     # Files, folders, apps, data, URLs
    constraints: Tuple[str, ...] = ()             # Conditions, limitations
    dependencies: Tuple[str, ...] = ()            # Step dependencies (e.g., "open app before write")
    required_capabilities: Tuple[str, ...] = ()   # Capability IDs needed (e.g., "application.open")
    required_agents: Tuple[str, ...] = ()         # Level 2 agent names needed
    expected_result: Optional[str] = None         # Description of expected outcome
    risk: Optional[str] = None                    # Risk level: low/medium/high
    verification_requirements: Tuple[str, ...] = ()  # What to verify after execution

    @property
    def is_level3(self) -> bool:
        return self.level == 3 and self.mode == "os"

    @property
    def executable_intent(self) -> bool:
        return (
            self.is_level3
            and not self.requires_clarification
            and bool(self.operation)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "text": self.text,
            "sequence": self.sequence,
            "decision": dict(self.decision),
            "confidence": self.confidence,
            "level": self.level,
            "mode": self.mode,
            "operation": self.operation,
            "target": self.target,
            "application": self.application,
            "requires_clarification": self.requires_clarification,
            "clarification_reason": self.clarification_reason,
            "metadata": dict(self.metadata),
            # Level 3.9 fields
            "goal": self.goal,
            "intent": self.intent,
            "entities": [dict(e) for e in self.entities],
            "constraints": list(self.constraints),
            "dependencies": list(self.dependencies),
            "required_capabilities": list(self.required_capabilities),
            "required_agents": list(self.required_agents),
            "expected_result": self.expected_result,
            "risk": self.risk,
            "verification_requirements": list(self.verification_requirements),
        }


@dataclass(frozen=True)
class ObjectiveUnderstandingResult:
    """Safe, explainable interpretation of one user objective."""

    objective: str
    steps: tuple[ObjectiveStepIntent, ...]
    confidence: float
    requires_clarification: bool
    clarification_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Level 3.9: Overall objective metadata
    goal: Optional[str] = None
    overall_intent: Optional[str] = None
    required_capabilities: Tuple[str, ...] = ()
    required_agents: Tuple[str, ...] = ()
    overall_risk: Optional[str] = None

    @property
    def fully_level3(self) -> bool:
        return bool(self.steps) and all(
            step.is_level3
            for step in self.steps
        )

    @property
    def executable(self) -> bool:
        return bool(self.steps) and all(
            step.executable_intent
            for step in self.steps
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "steps": [
                step.to_dict()
                for step in self.steps
            ],
            "confidence": self.confidence,
            "requires_clarification": self.requires_clarification,
            "clarification_reason": self.clarification_reason,
            "metadata": dict(self.metadata),
            "fully_level3": self.fully_level3,
            "executable": self.executable,
            # Level 3.9 fields
            "goal": self.goal,
            "overall_intent": self.overall_intent,
            "required_capabilities": list(self.required_capabilities),
            "required_agents": list(self.required_agents),
            "overall_risk": self.overall_risk,
        }


class ObjectiveUnderstanding:
    """
    Interpret natural-language objectives without executing them.

    The splitter is deliberately conservative.

    It recognizes workflow boundaries such as:

        then
        and then
        after that
        next
        ;

    It also recognizes action-leading conjunctions such as:

        open Chrome and search for music

    It does NOT split every occurrence of "and".

    That distinction is important because:

        "open the research and development folder"

    must remain one objective step.
    """

    VERSION = "3.8.2"

    # =================================================================
    # TIER 1 — CLOSED VERB LIST (Level 3.8)
    # =================================================================
    # The original list of action verbs explicitly enumerated during
    # implementation. Kept verbatim so every pre-3.18 splitter test
    # continues to pass.
    _TIER1_VERBS = (
        r"open|close|inspect|check|find|search|look|locate|read|"
        r"create|make|write|edit|modify|update|save|sort|filter|organize|"
        r"move|copy|rename|delete|connect|launch|start|stop|show|list|"
        r"download|upload|summarize|calculate|convert|play"
    )

    # =================================================================
    # TIER 2 — MEANING-BASED VERB FAMILIES (Level 3.18)
    # =================================================================
    # Each entry is a VERB FAMILY: a group of synonymous surface forms
    # that all share the same underlying meaning. A family pattern
    # usually includes the preposition (e.g. "navigate to", "turn on")
    # so the second clause of a compound has the SHAPE
    #     <verb-family> <target>
    # which is exactly the shape an action verb + target has.
    #
    # Architectural rule for inclusion in Tier 2:
    #   A verb family may be added ONLY when the family
    #   semantically introduces a NEW, DISTINCT OS action when
    #   it follows an "and" / "then" / comma boundary. Verb
    #   families that commonly appear as CLARIFICATIONS of the
    #   preceding clause (e.g. "give me a clean desktop" after
    #   "shut everything down") are deliberately excluded so
    #   the splitter does not over-split single user intents.
    #
    # This is NOT a list of hard-coded sentences. The family patterns
    # are MEANING-BASED: each pattern captures an entire meaning
    # category, and any natural-language verb belonging to that
    # category matches it. The intent is to extend the splitter to
    # unseen phrasings without enumerating individual sentences.
    #
    # Architectural invariants:
    # * The Tier 1 list is preserved unchanged (all pre-3.18
    #   tests still pass).
    # * Tier 2 only fires at conjunction boundaries (and / then /
    #   comma-after-letter) where the second clause's structure
    #   already signals a new action; it never fires on noun
    #   phrases like "research and development folder".
    _TIER2_VERB_FAMILIES = (
        # NAVIGATE-TO-DESTINATION: opens a URL/site/destination
        # after the first clause has set up the browser/app.
        r"navigate\s+to|go\s+to|head\s+to|head\s+over\s+to|"
        r"visit|browse\s+to|go\s+over\s+to|jump\s+to|hop\s+over\s+to"
        # OPEN-SYNONYM (with a target noun) — distinct action.
        # NOTE: "bring up X" is included ONLY when X is a noun
        # that names a different app/thing (e.g. "bring up the
        # calculator"); bare "bring up" used as a clarification
        # is guarded by the existing Tier 1 patterns and the
        # compound detector's executable check.
        r"|pull\s+up|fire\s+up|boot\s+up|spin\s+up|kick\s+off|"
        r"start\s+up|pop\s+open|pop\s+up|bring\s+up"
        # CLOSE-SYNONYM
        r"|shut\s+down|terminate\s+the|kill\s+the\s+app|"
        r"end\s+the\s+session|exit\s+out"
        # REVEAL — explicit synonym for "show"/"open" that
        # introduces a new visible surface (e.g. "reveal the
        # desktop" after "close chrome").
        r"|reveal"
        # ENABLE / TURN-ON (toggles a setting after opening the
        # settings app)
        r"|turn\s+on|switch\s+on|enable|activate|power\s+on"
        # DISABLE / TURN-OFF
        r"|turn\s+off|switch\s+off|disable|deactivate|power\s+off"
        # SEND / SHARE / FORWARD (sends the just-opened thing)
        r"|email\s+it|mail\s+it|send\s+it|share\s+it|"
        r"forward\s+it|hand\s+it\s+over|"
        r"pass\s+it\s+along|deliver\s+it|post\s+it"
        # QUEUE / VOLUME / INCREASE / DECREASE — distinct OS control
        r"|queue\s+up|queue|crank\s+up|pump\s+up|"
        r"turn\s+up|turn\s+down|crank\s+down"
        # FIND / SEARCH additional synonyms
        r"|look\s+for|look\s+up|hunt\s+for|seek|search\s+for|"
        r"search\s+up"
        # TYPE / CLICK / SCROLL / PASTE — interaction verbs
        r"|type\s+in|enter\s+the|input\s+the|"
        r"tap\s+on|press\s+the|hit\s+the|"
        r"page\s+down|page\s+up|"
        r"paste\s+in|drop\s+in"
        # CAPTURE / SCREENSHOT
        r"|capture\s+the|capture\s+my|"
        r"take\s+a\s+screenshot|grab\s+a\s+screenshot|"
        r"snap\s+a\s+shot"
        # INSTALL / UNINSTALL
        r"|set\s+up|get\s+rid\s+of"
        # BROWSER-ACTION VERBS (Level 3.20): actions that
        # are natural inside an already-open browser. These
        # are MEANING-BASED (browser control actions) not
        # hard-coded phrasings. Each verb introduces a new
        # browser action when it follows a conjunction.
        r"|bookmark(?:\s+this)?|bookmark\s+the\s+page|"
        r"add\s+to\s+bookmarks|save\s+to\s+bookmarks|"
        r"unbookmark|remove\s+bookmark|"
        r"clear\s+(?:my\s+)?(?:browsing\s+)?history|"
        r"clear\s+(?:my\s+)?cache|clear\s+cookies|"
        r"refresh(?:\s+the\s+page)?|reload(?:\s+the\s+page)?|"
        r"close\s+(?:the\s+)?(?:current\s+)?tab|"
        r"close\s+all\s+tabs|"
        r"reopen\s+(?:the\s+)?(?:last\s+)?tab|"
        r"undo\s+close\s+tab|"
        r"go\s+back|go\s+forward|navigate\s+back|navigate\s+forward|"
        r"zoom\s+in|zoom\s+out|"
        r"print\s+(?:this\s+)?page|"
        r"save\s+(?:this\s+)?page|"
        r"view\s+source|view\s+page\s+source|"
        r"open\s+(?:a\s+)?new\s+tab|"
        r"open\s+(?:a\s+)?new\s+(?:private|incognito)\s+window"
    )

    # The combined pattern used by both _ACTION_CONJUNCTION_RE and
    # _ACTION_START_RE. Tier 1 (closed list) is tried first via
    # the regex engine's leftmost match; Tier 2 is a parallel
    # alternation, so either can match.
    _ACTION_VERB_PATTERN = (
        rf"(?:{_TIER1_VERBS}|{_TIER2_VERB_FAMILIES})"
    )

    _ACTION_CONJUNCTION_RE = re.compile(
        rf"\s+and\s+(?={_ACTION_VERB_PATTERN}\b)",
        re.IGNORECASE,
    )

    _ACTION_START_RE = re.compile(
        rf"^(?:please\s+|genesis[,:]?\s+|could you\s+|can you\s+|"
        rf"would you\s+|kindly\s+)?"
        rf"(?:{_ACTION_VERB_PATTERN})\b",
        re.IGNORECASE,
    )

    # =================================================================
    # ITEM 16A (R8): "next" is NOT a clause boundary on its own.
    # =================================================================
    #
    # This used to be
    #
    #     r"\s*(?:;|\b(?:then|and then|after that|next)\b)\s*"
    #
    # A bare \bnext\b matches wherever the word appears, so every
    # "the next <noun>" was torn in half. Measured against the
    # original:
    #
    #     "play the next song"     -> ["play the", "song"]
    #     "go to the next slide"   -> ["go to the", "slide"]
    #     "open the next folder"   -> ["open the", "folder"]
    #     "download the next report" -> ["download the", "report"]
    #     "the next step is to open Chrome"
    #                             -> ["the", "step is to open Chrome"]
    #
    # "next" in English is overwhelmingly an ORDINAL DETERMINER ("the
    # next one"), not a conjunction. Treating it as a connector
    # invented a second objective step that the user never asked for,
    # out of a single instruction.
    #
    # The fix mirrors the stricter splitter in
    # agents/workflow_decision.py::_L3_VERB_SPLIT, which requires the
    # boundary word to be FOLLOWED BY A VERB before it is allowed to
    # split. "next" alone is not a boundary; "next open" is, because a
    # clause has started.
    #
    # This is why the regex is declared HERE rather than beside the
    # other class constants: it needs _ACTION_VERB_PATTERN, which is
    # built from the Tier 1 and Tier 2 verb lists further down.
    _BOUNDARY_RE = re.compile(
        rf"\s*(?:;|\b(?:then|and then|after that)\b|"
        rf"\bnext\s+(?={_ACTION_VERB_PATTERN}\b))\s*",
        re.IGNORECASE,
    )

    def __init__(self, decision_engine: Any):
        if (
            decision_engine is None
            or not hasattr(decision_engine, "decide")
        ):
            raise TypeError(
                "ObjectiveUnderstanding requires a "
                "WorkflowDecisionEngine-compatible object."
            )

        self.decision_engine = decision_engine

        # -------------------------------------------------
        # CONTEXT HINT RESOLVER (Level 3.19)
        # -------------------------------------------------
        # When a compound objective is decomposed into
        # fragments, the 2nd clause may be ambiguous without
        # the 1st clause's resolved target (e.g.
        # "open settings and turn on bluetooth" — the 2nd
        # clause names a settings sub-page). The resolver
        # carries the 1st clause's decision as structured
        # context and attempts a meaning-based re-resolution
        # of the 2nd clause. The resolver is read-only and
        # side-effect free; if no mapping applies the 2nd
        # clause falls through to its standalone decision
        # unchanged.
        try:
            from genesis_os.context_hint_resolver import (
                ContextHintResolver,
            )
            self._context_hint_resolver: Any = (
                ContextHintResolver()
            )
        except Exception:
            self._context_hint_resolver = None

    def understand(
        self,
        objective: str,
    ) -> ObjectiveUnderstandingResult:
        """
        Convert one human objective into structured intent steps.

        No execution occurs here.
        """

        normalized = self._normalize_objective(objective)

        if not normalized:
            empty_result = ObjectiveUnderstandingResult(
                objective="",
                steps=(),
                confidence=0.0,
                requires_clarification=True,
                clarification_reason=(
                    "The objective is empty."
                ),
                metadata={
                    "version": self.VERSION
                },
            )
            # Phase 1 contract: the empty-clarification shape must
            # itself satisfy the Objective boundary.
            ObjectiveContract.from_understanding_result(empty_result)
            return empty_result

        fragments = self.split_objective(
            normalized
        )

        intents = []
        # Track the most recent Level-3 OS decision so the
        # next fragment can be re-resolved with structured
        # context (Level 3.19). Only successful L3 OS
        # decisions contribute context; L1 conversation
        # fragments are skipped so a failed 1st clause
        # does not poison the 2nd.
        prior_l3_decision: Optional[Dict[str, Any]] = None

        for index, fragment in enumerate(
            fragments,
            start=1,
        ):
            intent = self._understand_fragment(
                fragment,
                index,
                prior_l3_decision=prior_l3_decision,
            )
            intents.append(intent)

            # If this fragment yielded a successful L3 OS
            # decision, carry it as context for the next
            # fragment.
            if (
                intent.level == 3
                and intent.mode == "os"
            ):
                # Carry the 1st-clause L3 decision as
                # context for the next fragment, even when
                # the standalone decision requires
                # clarification. In a compound request the
                # 2nd clause often provides the missing
                # context (e.g. "open the file manager and
                # rename my essay" — the 1st clause's
                # target=None is resolved by the 2nd
                # clause's noun). The context resolver
                # decides whether the prior decision is
                # useful.
                prior_l3_decision = dict(intent.decision)
                prior_l3_decision["_original_fragment"] = (
                    fragment
                )
            else:
                # Reset the chain so a conversational
                # fragment does not become "context" for
                # the next OS step.
                prior_l3_decision = None

        confidence = min(
            (
                step.confidence
                for step in intents
            ),
            default=0.0,
        )

        clarification = next(
            (
                step.clarification_reason
                for step in intents
                if step.requires_clarification
            ),
            None,
        )

        # Compute overall objective metadata
        overall_goal = self._compute_overall_goal(intents)
        overall_intent = self._compute_overall_intent(intents)
        required_capabilities = self._compute_required_capabilities(intents)
        required_agents = self._compute_required_agents(intents)
        overall_risk = self._compute_overall_risk(intents)

        # Phase 1 contract: every understood objective must satisfy
        # the Objective boundary before it leaves this method.
        understood = ObjectiveUnderstandingResult(
            objective=normalized,
            steps=tuple(intents),
            confidence=confidence,
            requires_clarification=(
                clarification is not None
            ),
            clarification_reason=clarification,
            metadata={
                "version": self.VERSION,
                "step_count": len(intents),
                "fully_level3": all(
                    step.is_level3
                    for step in intents
                ),
            },
            # Level 3.9 overall metadata
            goal=overall_goal,
            overall_intent=overall_intent,
            required_capabilities=required_capabilities,
            required_agents=required_agents,
            overall_risk=overall_risk,
        )
        ObjectiveContract.from_understanding_result(understood)
        return understood

    def _compute_overall_goal(self, intents: Tuple[ObjectiveStepIntent, ...]) -> Optional[str]:
        """Compute overall goal from all step intents."""
        goals = [step.goal for step in intents if step.goal]
        if not goals:
            return None
        if len(goals) == 1:
            return goals[0]
        return "; ".join(goals)

    def _compute_overall_intent(self, intents: Tuple[ObjectiveStepIntent, ...]) -> Optional[str]:
        """Compute overall intent from all step intents."""
        intents_list = [step.intent for step in intents if step.intent]
        if not intents_list:
            return None
        if len(intents_list) == 1:
            return intents_list[0]
        # Check for mixed intents
        unique_intents = set(intents_list)
        if len(unique_intents) == 1:
            return intents_list[0]
        return "mixed: " + ", ".join(sorted(unique_intents))

    def _compute_required_capabilities(self, intents: Tuple[ObjectiveStepIntent, ...]) -> Tuple[str, ...]:
        """Compute all required capabilities from all step intents."""
        capabilities = set()
        for step in intents:
            capabilities.update(step.required_capabilities)
        return tuple(sorted(capabilities))

    def _compute_required_agents(self, intents: Tuple[ObjectiveStepIntent, ...]) -> Tuple[str, ...]:
        """Compute all required agents from all step intents."""
        agents = set()
        for step in intents:
            agents.update(step.required_agents)
        return tuple(sorted(agents))

    def _compute_overall_risk(self, intents: Tuple[ObjectiveStepIntent, ...]) -> Optional[str]:
        """Compute overall risk level (highest risk among steps)."""
        risk_levels = {"high": 3, "medium": 2, "low": 1}
        max_risk = 0
        max_risk_label = "low"
        for step in intents:
            if step.risk:
                risk_value = risk_levels.get(step.risk, 1)
                if risk_value > max_risk:
                    max_risk = risk_value
                    max_risk_label = step.risk
        return max_risk_label

    def split_objective(
        self,
        objective: str,
    ) -> tuple[str, ...]:
        """
        Split only at explicit or action-leading boundaries.
        """

        text = self._normalize_objective(
            objective
        )

        if not text:
            return ()

        parts = [
            part.strip(" ,")
            for part in self._BOUNDARY_RE.split(text)
            if part.strip(" ,")
        ]

        fragments: list[str] = []

        for part in parts:
            candidates = [
                candidate.strip(" ,")
                for candidate in self._ACTION_CONJUNCTION_RE.split(
                    part
                )
                if candidate.strip(" ,")
            ]

            fragments.extend(
                candidate
                for candidate in candidates
                if candidate
            )

        final: list[str] = []

        for fragment in fragments:

            comma_parts = [
                part.strip()
                for part in re.split(
                    r",\s+(?=[A-Za-z])",
                    fragment,
                )
                if part.strip()
            ]

            if len(comma_parts) <= 1:
                final.append(fragment)
                continue

            current = comma_parts[0]

            for candidate in comma_parts[1:]:

                if self._ACTION_START_RE.match(
                    candidate
                ):
                    final.append(current)
                    current = candidate
                else:
                    current = (
                        f"{current}, {candidate}"
                    )

            final.append(current)

        return tuple(
            item
            for item in final
            if item
        )

    def _understand_fragment(
        self,
        fragment: str,
        sequence: int,
        prior_l3_decision: Optional[Dict[str, Any]] = None,
    ) -> ObjectiveStepIntent:

        decision = self.decision_engine.decide(
            fragment
        )

        # -------------------------------------------------
        # CONTEXT HINT RE-RESOLUTION (Level 3.19)
        # -------------------------------------------------
        # Two cases fire the context resolver:
        #   (a) The standalone decision is NOT a successful
        #       L3 OS intent. We try a context-aware
        #       re-resolution using the prior L3 decision.
        #   (b) The standalone decision IS a successful L3
        #       intent but its CATEGORY is wrong for the
        #       1st-clause context (e.g. a file.search in a
        #       browser context, or a file.rename after
        #       opening a file manager — both correct in
        #       isolation but wrong category). The resolver
        #       can override the category to the
        #       context-appropriate one.
        #   (c) Direct settings sub-page resolution: when no
        #       prior L3 decision exists but the fragment
        #       text names a settings sub-page (e.g. the
        #       standalone 2nd clause of "open accessibility
        #       and enable high contrast" when the splitter
        #       keeps it as one fragment).
        standalone_is_l3_os = (
            decision.get("level") == 3
            and decision.get("mode") == "os"
        )
        if self._context_hint_resolver is not None:
            try:
                resolution = (
                    self._context_hint_resolver.resolve(
                        prior_l3_decision,
                        fragment,
                        current_decision=(
                            dict(decision)
                            if standalone_is_l3_os
                            else None
                        ),
                    )
                )
            except Exception:
                resolution = None

            if resolution is not None and resolution.resolved:
                # Only override the standalone decision when
                # the context resolver either found a real
                # mapping for an ambiguous clause (case a) or
                # when the context's category is more
                # specific than the standalone one (case b:
                # a browser search is a better fit for
                # "search for X" in a browser context than a
                # file search).
                #
                # CONSERVATIVE GATE: never override a high-
                # confidence standalone application intent
                # with a non-application context intent.
                # When a user says "open Word" the standalone
                # decision is application.open with target
                # Word; the browser context from a prior
                # clause MUST NOT silently repurpose this
                # into browser.search. Application opens are
                # explicit, well-known user intent.
                standalone_intent = decision.get("intent") or ""
                standalone_confidence = float(
                    decision.get("confidence") or 0.0
                )
                standalone_app_target = (
                    decision.get("application")
                    or decision.get("target")
                    or ""
                )
                context_intent = resolution.decision.get(
                    "intent"
                ) or ""
                context_is_application = (
                    context_intent.startswith("application.")
                )
                standalone_is_application = (
                    standalone_intent.startswith("application.")
                )
                # If the user has explicitly and confidently
                # asked for a specific application, do not let
                # the context resolver repurpose the clause
                # into a different category (e.g. browser,
                # settings, file manager).
                standalone_is_explicit_app = (
                    standalone_is_application
                    and standalone_confidence >= 0.85
                    and bool(str(standalone_app_target).strip())
                )
                override_blocked_by_app = (
                    standalone_is_explicit_app
                    and not context_is_application
                )
                if (
                    not standalone_is_l3_os
                    or (
                        context_intent != standalone_intent
                        and not override_blocked_by_app
                    )
                ):
                    decision = dict(resolution.decision)
                    decision.setdefault("task", fragment)
                    decision.setdefault(
                        "reason", resolution.description
                    )
                    # Tag the decision so callers know it
                    # was context-resolved (useful for
                    # diagnostics and for the existing
                    # CompoundTaskRouter's observability).
                    decision.setdefault(
                        "source", "context_hint_resolver"
                    )

        if not isinstance(
            decision,
            dict,
        ):
            decision = {
                "level": 1,
                "mode": "conversation",
                "task": fragment,
                "confidence": 0.0,
                "reason": (
                    "The workflow decision engine "
                    "returned an invalid decision."
                ),
            }

        level = int(
            decision.get(
                "level",
                1,
            )
            or 1
        )

        mode = str(
            decision.get(
                "mode",
                "conversation",
            )
            or "conversation"
        )

        confidence = self._bounded_confidence(
            decision.get(
                "confidence",
                0.0,
            )
        )

        operation = (
            decision.get("operation")
            or decision.get("intent")
        )

        target = decision.get(
            "target"
        )

        application = decision.get(
            "application"
        )

        clarification_reason = None
        requires_clarification = False

        if (
            level != 3
            or mode != "os"
        ):
            requires_clarification = True

            clarification_reason = (
                "This objective step was not resolved "
                "as a Level 3 desktop operation. Genesis "
                "must not execute it through the Level 3 "
                "workflow engine."
            )

        elif not operation:

            requires_clarification = True

            clarification_reason = (
                "Genesis detected a desktop request but "
                "could not resolve its operation."
            )

        elif (
            decision.get(
                "parameters",
                {},
            ).get(
                "requires_target"
            )
            and not target
            and not application
        ):

            requires_clarification = True

            clarification_reason = (
                "The desktop operation requires a concrete "
                "target that has not been resolved."
            )

        elif confidence < 0.90:

            requires_clarification = True

            clarification_reason = (
                "Genesis does not have sufficient confidence "
                "to execute this consequential desktop step "
                "automatically."
            )

        # ===== Level 3.9: Extract rich semantic information =====
        # Extract goal, intent, entities, constraints, dependencies, etc.
        goal = self._extract_goal(fragment, decision)
        intent = self._extract_intent(fragment, decision)
        entities = self._extract_entities(fragment, decision)
        constraints = self._extract_constraints(fragment, decision)
        dependencies = self._extract_dependencies(fragment, decision)
        required_capabilities = self._extract_required_capabilities(fragment, decision)
        required_agents = self._extract_required_agents(fragment, decision)
        expected_result = self._extract_expected_result(fragment, decision)
        risk = self._extract_risk(fragment, decision)
        verification_requirements = self._extract_verification_requirements(fragment, decision)

        return ObjectiveStepIntent(
            step_id=(
                f"objective-step-{sequence}"
            ),
            text=fragment,
            sequence=sequence,
            decision=dict(decision),
            confidence=confidence,
            level=level,
            mode=mode,
            operation=operation,
            target=target,
            application=application,
            requires_clarification=(
                requires_clarification
            ),
            clarification_reason=(
                clarification_reason
            ),
            metadata={
                "understanding_version": self.VERSION
            },
            # Level 3.9 fields
            goal=goal,
            intent=intent,
            entities=entities,
            constraints=constraints,
            dependencies=dependencies,
            required_capabilities=required_capabilities,
            required_agents=required_agents,
            expected_result=expected_result,
            risk=risk,
            verification_requirements=verification_requirements,
        )

    # ===== Level 3.9: Semantic Extraction Methods =====

    def _extract_goal(self, fragment: str, decision: Dict[str, Any]) -> Optional[str]:
        """Extract the high-level goal from the fragment."""
        if not fragment:
            return None
        # Infer goal from operation and target
        operation = decision.get("operation") or decision.get("intent")
        target = decision.get("target") or decision.get("application")
        if operation and target:
            return f"{operation} {target}"
        return fragment.strip()

    def _extract_intent(self, fragment: str, decision: Dict[str, Any]) -> Optional[str]:
        """Extract high-level intent category from fragment."""
        operation = decision.get("operation") or decision.get("intent")
        if not operation:
            return None
        # Map operations to intent categories
        intent_map = {
            "application.open": "launch_application",
            "application.close": "close_application",
            "application.inspect": "inspect_application",
            "folder.open": "open_folder",
            "folder.create": "create_folder",
            "folder.organize": "organize_folder",
            "file.open": "open_file",
            "file.read": "read_file",
            "file.search": "search_files",
            "file.create": "create_file",
            "file.copy": "copy_file",
            "file.move": "move_file",
            "file.rename": "rename_file",
            "file.delete": "delete_file",
            "browser.open_url": "open_url",
            "browser.search": "search_web",
            "system.open_settings": "open_settings",
            "network.connect_wifi": "connect_wifi",
            "spreadsheet.sort": "sort_spreadsheet",
            "document.create_docx": "create_document",
        }
        return intent_map.get(operation, operation)

    def _extract_entities(self, fragment: str, decision: Dict[str, Any]) -> Tuple[Dict[str, Any], ...]:
        """Extract entities (files, folders, apps, data, URLs) from fragment."""
        entities = []
        target = decision.get("target")
        application = decision.get("application")
        parameters = decision.get("parameters", {})

        if target:
            entities.append({
                "type": self._infer_entity_type(target, decision),
                "value": target,
                "role": "target"
            })
        if application and application != target:
            entities.append({
                "type": "application",
                "value": application,
                "role": "application"
            })
        # Check for destination in parameters
        dest = parameters.get("destination")
        if dest:
            entities.append({
                "type": "folder",
                "value": dest,
                "role": "destination"
            })
        # Check for source files
        source = parameters.get("source")
        if source:
            entities.append({
                "type": "file",
                "value": source,
                "role": "source"
            })
        return tuple(entities)

    def _infer_entity_type(self, target: str, decision: Dict[str, Any]) -> str:
        """Infer entity type from target and decision."""
        operation = decision.get("operation") or decision.get("intent", "")
        if operation.startswith("application."):
            return "application"
        if operation.startswith("folder."):
            return "folder"
        if operation.startswith("file."):
            return "file"
        if operation.startswith("browser."):
            return "url"
        if operation.startswith("spreadsheet."):
            return "spreadsheet"
        if operation.startswith("document."):
            return "document"
        # Default inference from target string
        if target.startswith("http"):
            return "url"
        if any(target.endswith(ext) for ext in [".xlsx", ".xls", ".csv"]):
            return "spreadsheet"
        if any(target.endswith(ext) for ext in [".docx", ".doc", ".pdf", ".txt"]):
            return "document"
        return "unknown"

    def _extract_constraints(self, fragment: str, decision: Dict[str, Any]) -> Tuple[str, ...]:
        """Extract constraints from fragment and decision."""
        constraints = []
        parameters = decision.get("parameters", {})

        # Check for confirmation requirements.
        #
        # Item 12D (R6): both halves now use STRICT IDENTITY, so the
        # two flags mean the same kind of thing.
        #
        # Before, this read
        #
        #     parameters.get("requires_confirmation")
        #         or parameters.get("confirmed") is False
        #
        # -- truthiness for one and identity for the other, on the same
        # concept. Measured over the values these can actually take:
        #
        #     value      requires_confirmation   confirmed
        #     1          TRIGGERS                 -
        #     "yes"      TRIGGERS                 -
        #     "false"    TRIGGERS                 -      <-- the irony
        #     [1]        TRIGGERS                 -
        #     0          -                        -
        #
        # So the string "false" demanded confirmation while the boolean
        # False did not, and 0 and False -- the same idea -- disagreed
        # between the two flags.
        #
        # STRICT IDENTITY is the right predicate because every product
        # producer already assigns a real boolean here: 40 literal
        # assignments plus 10 that forward a typed attribute (one of them
        # an explicit bool(...)). Nothing depends on the truthiness
        # readings, so this narrows the accepted values without changing
        # a single real code path.
        if (parameters.get("requires_confirmation") is True
                or parameters.get("confirmed") is False):
            constraints.append("requires_confirmation")

        # Check for safety constraints from operation
        operation = decision.get("operation") or decision.get("intent") or ""
        if "delete" in operation:
            constraints.append("destructive_operation")
        if "move" in operation or "rename" in operation:
            constraints.append("modifies_existing")
        if "copy" in operation:
            constraints.append("preserves_source")

        # Check for natural language constraints
        fragment_lower = fragment.lower()
        if "latest" in fragment_lower or "newest" in fragment_lower:
            constraints.append("latest_only")
        if "largest" in fragment_lower:
            constraints.append("largest_only")
        if "smallest" in fragment_lower:
            constraints.append("smallest_only")
        if "duplicate" in fragment_lower:
            constraints.append("find_duplicates")
        if "organize" in fragment_lower:
            constraints.append("organize_by_type")

        return tuple(constraints)

    def _extract_dependencies(self, fragment: str, decision: Dict[str, Any]) -> Tuple[str, ...]:
        """Extract step dependencies from fragment."""
        dependencies = []
        fragment_lower = fragment.lower()

        # App must be open before file operations on it
        if "open" in fragment_lower and ("file" in fragment_lower or "document" in fragment_lower or "spreadsheet" in fragment_lower):
            dependencies.append("application_must_be_open")

        # Folder must exist before organizing
        if "organize" in fragment_lower:
            dependencies.append("folder_must_exist")

        # File must exist before move/copy/rename/delete
        if any(op in fragment_lower for op in ["move", "copy", "rename", "delete"]):
            dependencies.append("source_must_exist")

        return tuple(dependencies)

    def _extract_required_capabilities(self, fragment: str, decision: Dict[str, Any]) -> Tuple[str, ...]:
        """Extract required capabilities from decision and fragment."""
        capabilities = set()
        operation = decision.get("operation") or decision.get("intent")
        if operation:
            capabilities.add(operation)

        # Add additional capabilities inferred from fragment
        fragment_lower = fragment.lower()
        if "search" in fragment_lower or "find" in fragment_lower:
            capabilities.add("file.search")
        if "organize" in fragment_lower:
            capabilities.add("folder.organize")
        if "calculate" in fragment_lower or "percentage" in fragment_lower:
            capabilities.add("spreadsheet.sort")
        if "sort" in fragment_lower:
            capabilities.add("spreadsheet.sort")

        return tuple(sorted(capabilities))

    def _extract_required_agents(self, fragment: str, decision: Dict[str, Any]) -> Tuple[str, ...]:
        """Extract required Level 2 agents from fragment."""
        agents = set()
        fragment_lower = fragment.lower()

        if "research" in fragment_lower or "look up" in fragment_lower or "investigate" in fragment_lower:
            agents.add("Research Agent")
        if "analyze" in fragment_lower or "statistics" in fragment_lower or "percentage" in fragment_lower:
            agents.add("Data Agent")
        if "code" in fragment_lower or "script" in fragment_lower or "debug" in fragment_lower:
            agents.add("Coding Agent")
        if "summarize" in fragment_lower and ("pdf" in fragment_lower or "document" in fragment_lower):
            agents.add("Document Agent")
        if "plan" in fragment_lower or "schedule" in fragment_lower:
            agents.add("Planning Agent")

        return tuple(sorted(agents))

    def _extract_expected_result(self, fragment: str, decision: Dict[str, Any]) -> Optional[str]:
        """Extract expected result description from fragment."""
        operation = decision.get("operation") or decision.get("intent")
        target = decision.get("target") or decision.get("application")

        if not operation:
            return None

        result_map = {
            "application.open": f"{target} application is running",
            "application.close": f"{target} application is closed",
            "folder.open": f"{target} folder is open in explorer",
            "folder.create": f"{target} folder is created",
            "file.open": f"{target} file is opened in default application",
            "file.read": f"Content of {target} is read",
            "file.create": f"{target} file is created",
            "file.copy": f"{target} is copied to destination",
            "file.move": f"{target} is moved to destination",
            "file.rename": f"{target} is renamed",
            "file.delete": f"{target} is deleted",
            "browser.open_url": f"Browser opened to {target}",
            "browser.search": f"Search results for {target} displayed",
            "spreadsheet.sort": f"Spreadsheet sorted by specified column",
            "document.create_docx": f"Document created at {target}",
        }
        return result_map.get(operation, f"{operation} completed on {target}" if target else f"{operation} completed")

    def _extract_risk(self, fragment: str, decision: Dict[str, Any]) -> Optional[str]:
        """Extract risk level from fragment and decision."""
        operation = decision.get("operation") or decision.get("intent", "")

        # High risk operations
        high_risk_ops = {"file.delete", "folder.delete", "system.shutdown", "system.restart", "network.connect_wifi"}
        if operation in high_risk_ops:
            return "high"

        # Medium risk operations
        medium_risk_ops = {"file.move", "file.rename", "file.copy", "folder.move", "folder.rename", "application.close", "network.connect_wifi"}
        if operation in medium_risk_ops:
            return "medium"

        # Check fragment for risky language
        fragment_lower = fragment.lower()
        if any(word in fragment_lower for word in ["delete", "remove", "destroy", "wipe", "format"]):
            return "high"
        if any(word in fragment_lower for word in ["move", "rename", "overwrite", "replace"]):
            return "medium"

        return "low"

    def _extract_verification_requirements(self, fragment: str, decision: Dict[str, Any]) -> Tuple[str, ...]:
        """Extract verification requirements from fragment and decision."""
        requirements = []
        operation = decision.get("operation") or decision.get("intent") or ""

        # Always verify execution succeeded
        requirements.append("execution_succeeded")

        # Operation-specific verification
        if operation == "application.open":
            requirements.append("application_running")
        elif operation == "application.close":
            requirements.append("application_not_running")
        elif operation and operation.startswith("file."):
            requirements.append("file_operation_verified")
        elif operation and operation.startswith("folder."):
            requirements.append("folder_operation_verified")
        elif operation == "browser.open_url":
            requirements.append("browser_navigated")
        elif operation == "browser.search":
            requirements.append("search_results_displayed")
        elif operation == "spreadsheet.sort":
            requirements.append("spreadsheet_sorted_correctly")
        elif operation == "document.create_docx":
            requirements.append("document_created_and_readable")

        return tuple(requirements)

    @staticmethod
    def _normalize_objective(
        value: Any,
    ) -> str:

        if not isinstance(
            value,
            str,
        ):
            raise ObjectiveUnderstandingError(
                "Objective must be a string."
            )

        text = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

        text = re.sub(
            r"^genesis[,:]?\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )

        return text

    @staticmethod
    def _bounded_confidence(
        value: Any,
    ) -> float:

        try:
            confidence = float(value)

        except (
            TypeError,
            ValueError,
        ):
            return 0.0

        return max(
            0.0,
            min(
                1.0,
                confidence,
            ),
        )