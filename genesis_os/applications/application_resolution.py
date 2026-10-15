"""
Genesis OS — Application Resolution Intelligence

LEVEL 3.2.3C.3
---------------

Converts a human application reference into the most
appropriate canonical application discovered by the
Unified Application Discovery system.

IMPORTANT ARCHITECTURAL RULE:

    Resolution != Execution

This module NEVER launches, closes, kills, or modifies
applications.

It only answers:

    "Which installed application does the user mean?"

The result is explainable and confidence-aware so that
future Genesis Trust, Verification, Automation and
Autonomy layers can safely consume it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import re


# =============================================================
# ENUMS
# =============================================================


class ResolutionDecision(str, Enum):
    """Final resolution decision."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


class ResolutionConfidence(str, Enum):
    """Human-readable confidence classification."""

    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


# =============================================================
# EVIDENCE
# =============================================================


@dataclass
class ResolutionEvidence:
    """Explainable evidence supporting a candidate."""

    signal: str
    score: float
    description: str

    def to_dict(self) -> dict:
        return {
            "signal": self.signal,
            "score": round(self.score, 2),
            "description": self.description,
        }


# =============================================================
# CANDIDATE
# =============================================================


@dataclass
class ResolutionCandidate:
    """Application candidate with explainable evidence."""

    application: dict
    score: float
    evidence: List[ResolutionEvidence] = field(
        default_factory=list
    )

    @property
    def name(self) -> str:
        return str(
            self.application.get(
                "name",
                "",
            )
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": round(self.score, 2),
            "application": self.application,
            "evidence": [
                item.to_dict()
                for item in self.evidence
            ],
        }


# =============================================================
# RESULT
# =============================================================


@dataclass
class ResolutionResult:
    """Complete explainable resolution result."""

    decision: ResolutionDecision

    confidence: ResolutionConfidence

    query: str

    normalized_query: str

    application: Optional[dict]

    score: float

    candidates: List[ResolutionCandidate]

    reasons: List[str]

    safety: Dict[str, object]

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "confidence": self.confidence.value,
            "query": self.query,
            "normalized_query": self.normalized_query,
            "application": self.application,
            "score": round(self.score, 2),
            "candidates": [
                candidate.to_dict()
                for candidate in self.candidates
            ],
            "reasons": list(self.reasons),
            "safety": dict(self.safety),
        }


# =============================================================
# RESOLUTION ENGINE
# =============================================================


class ApplicationResolutionEngine:
    """
    Resolves human application references against the
    Unified Application Discovery index.

    Resolution signals:

    Strong:
        - explicit safe alias
        - exact canonical name
        - exact discovered alias

    Medium:
        - normalized name
        - abbreviation
        - exact token match

    Weak:
        - partial token match
        - partial phrase match

    IMPORTANT:

    Human-safe aliases have special priority.

    This prevents discovery records such as:

        explorer
        chrome
        code

    from incorrectly defeating intended human aliases
    such as:

        explorer -> File Explorer
        chrome   -> Google Chrome
        vscode   -> Visual Studio Code
    """

    VERSION = "1.2"

    # ---------------------------------------------------------
    # Scores
    # ---------------------------------------------------------

    SCORE_EXACT_NAME = 100.0
    SCORE_EXACT_ALIAS = 98.0
    SCORE_SAFE_ALIAS = 105.0

    SCORE_NORMALIZED_NAME = 92.0
    SCORE_ABBREVIATION = 82.0
    SCORE_TOKEN_EXACT = 80.0
    SCORE_TOKEN_PARTIAL = 65.0
    SCORE_PARTIAL = 55.0

    # ---------------------------------------------------------
    # Thresholds
    # ---------------------------------------------------------

    RESOLVE_THRESHOLD = 75.0

    HIGH_CONFIDENCE_THRESHOLD = 90.0

    VERY_HIGH_CONFIDENCE_THRESHOLD = 97.0

    AMBIGUITY_MARGIN = 10.0

    MAX_CANDIDATES = 10

    # ---------------------------------------------------------
    # Built-in human-safe aliases
    # ---------------------------------------------------------

    SAFE_ALIASES: Dict[str, List[str]] = {

        "Google Chrome": [
            "chrome",
            "google browser",
        ],

        "Visual Studio Code": [
            "vscode",
            "vs code",
            "code",
        ],

        "File Explorer": [
            "explorer",
            "windows explorer",
            "file manager",
        ],

        "Microsoft Edge": [
            "edge",
            "microsoft browser",
        ],

        "Notepad": [
            "text editor",
        ],

        "Command Prompt": [
            "cmd",
            "command line",
        ],

        "PowerShell": [
            "powershell",
            "pwsh",
        ],

        "Calculator": [
            "calc",
        ],

        "Settings": [
            "windows settings",
            "system settings",
        ],
    }

    # =========================================================
    # INITIALIZATION
    # =========================================================

    def __init__(
        self,
        discovery=None,
    ):
        """
        Parameters
        ----------
        discovery:
            UnifiedApplicationDiscovery instance.

        Dependency injection keeps the resolver independent
        from the discovery implementation.
        """

        self.discovery = discovery

    # =========================================================
    # PUBLIC API
    # =========================================================

    def resolve(
        self,
        query: str,
        refresh: bool = False,
    ) -> ResolutionResult:
        """
        Resolve a human application reference.

        NEVER executes the application.
        """

        original_query = (
            str(query)
            if query is not None
            else ""
        )

        normalized_query = self.normalize_query(
            original_query
        )

        if not normalized_query:
            return self._not_found(
                original_query,
                normalized_query,
                "The application query was empty.",
            )

        applications = self._get_applications(
            refresh=refresh
        )

        if not applications:
            return self._not_found(
                original_query,
                normalized_query,
                (
                    "No applications are available "
                    "in the discovery index."
                ),
            )

        # -----------------------------------------------------
        # Remove duplicate discovery records
        # -----------------------------------------------------

        applications = self._deduplicate_applications(
            applications
        )

        if not applications:
            return self._not_found(
                original_query,
                normalized_query,
                (
                    "No valid application candidates "
                    "remain after deduplication."
                ),
            )

        # -----------------------------------------------------
        # Score all applications
        # -----------------------------------------------------

        candidates: List[
            ResolutionCandidate
        ] = []

        for application in applications:

            candidate = self._score_application(
                normalized_query,
                application,
            )

            if candidate is not None:
                candidates.append(candidate)

        # -----------------------------------------------------
        # Sort
        # -----------------------------------------------------

        candidates.sort(
            key=self._candidate_sort_key,
            reverse=True,
        )

        candidates = candidates[
            : self.MAX_CANDIDATES
        ]

        if not candidates:
            return self._not_found(
                original_query,
                normalized_query,
                (
                    "No discovered application matched "
                    "the supplied reference."
                ),
            )

        best = candidates[0]

        second_score = (
            candidates[1].score
            if len(candidates) > 1
            else 0.0
        )

        # -----------------------------------------------------
        # Explicit safe alias protection
        #
        # If the best result comes from a safe alias,
        # it is considered intentional human language and
        # defeats a conflicting discovered/internal name.
        # -----------------------------------------------------

        if self._has_safe_alias_evidence(best):

            return self._resolved_result(
                original_query,
                normalized_query,
                best,
                candidates,
                alias_resolution=True,
            )

        # -----------------------------------------------------
        # Ambiguity protection
        # -----------------------------------------------------

        if (
            len(candidates) > 1
            and best.score < (
                second_score
                + self.AMBIGUITY_MARGIN
            )
            and best.score < (
                self.VERY_HIGH_CONFIDENCE_THRESHOLD
            )
        ):

            return ResolutionResult(
                decision=ResolutionDecision.AMBIGUOUS,
                confidence=self._confidence_for_score(
                    best.score
                ),
                query=original_query,
                normalized_query=normalized_query,
                application=None,
                score=best.score,
                candidates=candidates,
                reasons=[
                    (
                        "Multiple distinct applications "
                        "have similar resolution scores."
                    ),
                    (
                        "Genesis will not automatically "
                        "choose between ambiguous targets."
                    ),
                ],
                safety={
                    "execution_allowed": False,
                    "requires_confirmation": True,
                    "resolution_only": True,
                },
            )

        # -----------------------------------------------------
        # Resolution threshold
        # -----------------------------------------------------

        if best.score < self.RESOLVE_THRESHOLD:

            return ResolutionResult(
                decision=ResolutionDecision.NOT_FOUND,
                confidence=self._confidence_for_score(
                    best.score
                ),
                query=original_query,
                normalized_query=normalized_query,
                application=None,
                score=best.score,
                candidates=candidates,
                reasons=[
                    (
                        "The best candidate did not "
                        "reach the safe resolution threshold."
                    ),
                ],
                safety={
                    "execution_allowed": False,
                    "requires_confirmation": True,
                    "resolution_only": True,
                },
            )

        return self._resolved_result(
            original_query,
            normalized_query,
            best,
            candidates,
        )

    # =========================================================
    # RESULT BUILDERS
    # =========================================================

    def _resolved_result(
        self,
        original_query: str,
        normalized_query: str,
        best: ResolutionCandidate,
        candidates: List[ResolutionCandidate],
        alias_resolution: bool = False,
    ) -> ResolutionResult:
        """Build successful resolution result."""

        reasons = [
            evidence.description
            for evidence in best.evidence
        ]

        if alias_resolution:
            reasons.insert(
                0,
                (
                    "A Genesis safe human alias was "
                    "used to identify the intended application."
                ),
            )

        reasons.append(
            (
                f"Application resolved to "
                f"'{best.name}'."
            )
        )

        return ResolutionResult(
            decision=ResolutionDecision.RESOLVED,
            confidence=self._confidence_for_score(
                best.score
            ),
            query=original_query,
            normalized_query=normalized_query,
            application=best.application,
            score=best.score,
            candidates=candidates,
            reasons=reasons,
            safety={
                "execution_allowed": False,
                "requires_confirmation": False,
                "resolution_only": True,
            },
        )

    # =========================================================
    # CANDIDATE SORTING
    # =========================================================

    @staticmethod
    def _candidate_sort_key(
        candidate: ResolutionCandidate,
    ):
        """
        Deterministic candidate ordering.

        Safe aliases receive priority before ordinary
        discovery-name matches when scores are comparable.
        """

        safe_alias = (
            1
            if any(
                evidence.signal == "safe_alias"
                for evidence in candidate.evidence
            )
            else 0
        )

        exact_name = (
            1
            if any(
                evidence.signal == "exact_name"
                for evidence in candidate.evidence
            )
            else 0
        )

        return (
            candidate.score,
            safe_alias,
            exact_name,
            candidate.name.lower(),
        )

    # =========================================================
    # DISCOVERY
    # =========================================================

    def _get_applications(
        self,
        refresh: bool = False,
    ) -> List[dict]:
        """Retrieve applications from unified discovery."""

        if self.discovery is None:
            return []

        applications = self.discovery.discover(
            refresh=refresh
        )

        if not applications:
            return []

        return [
            application
            for application in applications
            if isinstance(application, dict)
        ]

    # =========================================================
    # DEDUPLICATION
    # =========================================================

    def _deduplicate_applications(
        self,
        applications: List[dict],
    ) -> List[dict]:
        """
        Remove duplicate representations of the same
        application using strong identity fields.
        """

        unique: List[dict] = []

        identity_to_index: Dict[
            str,
            int
        ] = {}

        for application in applications:

            identity = self._application_identity(
                application
            )

            if not identity:

                unique.append(application)
                continue

            if identity in identity_to_index:

                index = identity_to_index[
                    identity
                ]

                existing = unique[index]

                unique[index] = (
                    self._merge_resolution_records(
                        existing,
                        application,
                    )
                )

                continue

            identity_to_index[
                identity
            ] = len(unique)

            unique.append(application)

        return unique

    # =========================================================
    # APPLICATION IDENTITY
    # =========================================================

    def _application_identity(
        self,
        application: dict,
    ) -> str:
        """
        Generate deterministic strong application identity.

        Priority:

            1. canonical ID
            2. App IDs
            3. package family
            4. executable
            5. normalized canonical name
        """

        if not isinstance(application, dict):
            return ""

        # -----------------------------------------------------
        # Canonical ID
        # -----------------------------------------------------

        canonical_id = self._clean(
            application.get("id")
        )

        if canonical_id:

            return (
                "canonical:"
                + canonical_id.lower()
            )

        # -----------------------------------------------------
        # App ID collection
        # -----------------------------------------------------

        app_ids = application.get(
            "app_ids",
            []
        )

        if isinstance(app_ids, list):

            normalized = [
                self._clean(value).lower()
                for value in app_ids
                if self._clean(value)
            ]

            if normalized:

                return (
                    "appid:"
                    + "|".join(
                        sorted(
                            set(normalized)
                        )
                    )
                )

        # -----------------------------------------------------
        # Single App ID
        # -----------------------------------------------------

        app_id = self._clean(
            application.get("app_id")
        )

        if app_id:

            return (
                "appid:"
                + app_id.lower()
            )

        # -----------------------------------------------------
        # Package family collection
        # -----------------------------------------------------

        package_families = application.get(
            "package_family_names",
            []
        )

        if isinstance(
            package_families,
            list,
        ):

            normalized = [
                self._clean(value).lower()
                for value in package_families
                if self._clean(value)
            ]

            if normalized:

                return (
                    "package:"
                    + "|".join(
                        sorted(
                            set(normalized)
                        )
                    )
                )

        # -----------------------------------------------------
        # Single package family
        # -----------------------------------------------------

        package_family = self._clean(
            application.get(
                "package_family_name"
            )
        )

        if package_family:

            return (
                "package:"
                + package_family.lower()
            )

        # -----------------------------------------------------
        # Executables
        # -----------------------------------------------------

        executables = application.get(
            "executables",
            []
        )

        if isinstance(
            executables,
            list,
        ):

            normalized = [
                self._normalize_path(value)
                for value in executables
                if self._clean(value)
            ]

            normalized = [
                value
                for value in normalized
                if value
            ]

            if normalized:

                return (
                    "exe:"
                    + "|".join(
                        sorted(
                            set(normalized)
                        )
                    )
                )

        # -----------------------------------------------------
        # Single executable
        # -----------------------------------------------------

        executable = self._clean(
            application.get(
                "executable"
            )
        )

        if executable:

            return (
                "exe:"
                + self._normalize_path(
                    executable
                )
            )

        # -----------------------------------------------------
        # Canonical name fallback
        # -----------------------------------------------------

        name = self._clean(
            application.get("name")
        )

        normalized_name = self.normalize_query(
            name
        )

        if normalized_name:

            return (
                "name:"
                + normalized_name
            )

        return ""

    # =========================================================
    # RECORD MERGING
    # =========================================================

    @staticmethod
    def _merge_resolution_records(
        existing: dict,
        candidate: dict,
    ) -> dict:
        """Merge records proven to have the same identity."""

        merged = dict(existing)

        list_fields = [
            "aliases",
            "paths",
            "executables",
            "uris",
            "app_ids",
            "package_names",
            "package_full_names",
            "package_family_names",
            "versions",
            "publishers",
            "install_locations",
            "raw_records",
            "sources",
        ]

        for field_name in list_fields:

            left = merged.get(
                field_name,
                []
            )

            right = candidate.get(
                field_name,
                []
            )

            if not isinstance(left, list):
                left = []

            if not isinstance(right, list):
                right = []

            combined = []

            for value in left + right:

                if value not in combined:
                    combined.append(value)

            merged[field_name] = combined

        for field_name in (
            "id",
            "name",
            "normalized_name",
            "category",
        ):

            if (
                not merged.get(field_name)
                and candidate.get(field_name)
            ):

                merged[field_name] = candidate[
                    field_name
                ]

        merged["launchable"] = bool(
            merged.get(
                "launchable",
                False
            )
            or candidate.get(
                "launchable",
                False
            )
        )

        merged["available"] = bool(
            merged.get(
                "available",
                False
            )
            or candidate.get(
                "available",
                False
            )
        )

        return merged

    # =========================================================
    # SCORING
    # =========================================================

    def _score_application(
        self,
        query: str,
        application: dict,
    ) -> Optional[ResolutionCandidate]:
        """
        Calculate explainable resolution evidence.

        Safe aliases intentionally receive the strongest
        score because they represent explicit Genesis
        human-language mappings.
        """

        application_name = self._clean(
            application.get(
                "name",
                ""
            )
        )

        if not application_name:
            return None

        normalized_name = self.normalize_query(
            application_name
        )

        # -----------------------------------------------------
        # Discovered aliases
        # -----------------------------------------------------

        aliases: List[str] = []

        raw_aliases = application.get(
            "aliases",
            []
        )

        if isinstance(
            raw_aliases,
            list,
        ):

            aliases = [
                self.normalize_query(alias)
                for alias in raw_aliases
                if self.normalize_query(alias)
            ]

        evidence: List[
            ResolutionEvidence
        ] = []

        # -----------------------------------------------------
        # Safe human alias
        # -----------------------------------------------------

        if self._matches_safe_alias(
            query,
            application_name,
        ):

            evidence.append(
                ResolutionEvidence(
                    signal="safe_alias",
                    score=self.SCORE_SAFE_ALIAS,
                    description=(
                        "The query is a known safe "
                        "human alias for "
                        f"'{application_name}'."
                    ),
                )
            )

        # -----------------------------------------------------
        # Exact canonical name
        # -----------------------------------------------------

        if query == normalized_name:

            evidence.append(
                ResolutionEvidence(
                    signal="exact_name",
                    score=self.SCORE_EXACT_NAME,
                    description=(
                        "The query exactly matches "
                        "the canonical application name."
                    ),
                )
            )

        # -----------------------------------------------------
        # Exact discovered alias
        # -----------------------------------------------------

        if query in aliases:

            evidence.append(
                ResolutionEvidence(
                    signal="exact_alias",
                    score=self.SCORE_EXACT_ALIAS,
                    description=(
                        "The query exactly matches "
                        "a discovered application alias."
                    ),
                )
            )

        # -----------------------------------------------------
        # Normalized name
        # -----------------------------------------------------

        if query == normalized_name:

            evidence.append(
                ResolutionEvidence(
                    signal="normalized_name",
                    score=self.SCORE_NORMALIZED_NAME,
                    description=(
                        "The normalized query matches "
                        "the normalized application name."
                    ),
                )
            )

        # -----------------------------------------------------
        # Abbreviation
        # -----------------------------------------------------

        if self._is_abbreviation_match(
            query,
            application_name,
        ):

            evidence.append(
                ResolutionEvidence(
                    signal="abbreviation",
                    score=self.SCORE_ABBREVIATION,
                    description=(
                        "The query matches a recognized "
                        "abbreviation of the application name."
                    ),
                )
            )

        # -----------------------------------------------------
        # Token matching
        # -----------------------------------------------------

        query_tokens = self._tokens(query)

        name_tokens = self._tokens(
            application_name
        )

        if query_tokens and name_tokens:

            if query_tokens.issubset(
                name_tokens
            ):

                evidence.append(
                    ResolutionEvidence(
                        signal="token_exact",
                        score=self.SCORE_TOKEN_EXACT,
                        description=(
                            "All query tokens are present "
                            "in the application name."
                        ),
                    )
                )

            elif query_tokens.intersection(
                name_tokens
            ):

                evidence.append(
                    ResolutionEvidence(
                        signal="token_partial",
                        score=self.SCORE_TOKEN_PARTIAL,
                        description=(
                            "Some query tokens match "
                            "the application name."
                        ),
                    )
                )

        # -----------------------------------------------------
        # Partial phrase
        # -----------------------------------------------------

        if (
            query in normalized_name
            or any(
                query in alias
                for alias in aliases
            )
        ):

            evidence.append(
                ResolutionEvidence(
                    signal="partial_match",
                    score=self.SCORE_PARTIAL,
                    description=(
                        "The query partially matches "
                        "the application name or alias."
                    ),
                )
            )

        if not evidence:
            return None

        # -----------------------------------------------------
        # Strongest evidence wins
        # -----------------------------------------------------

        strongest = max(
            evidence,
            key=lambda item: item.score,
        )

        return ResolutionCandidate(
            application=application,
            score=strongest.score,
            evidence=evidence,
        )

    # =========================================================
    # SAFE ALIAS MATCHING
    # =========================================================

    def _matches_safe_alias(
        self,
        query: str,
        application_name: str,
    ) -> bool:
        """
        Determine whether query is an explicit Genesis
        safe alias for the supplied canonical application.
        """

        normalized_application = (
            self.normalize_query(
                application_name
            )
        )

        for (
            canonical_name,
            aliases,
        ) in self.SAFE_ALIASES.items():

            normalized_canonical = (
                self.normalize_query(
                    canonical_name
                )
            )

            if (
                normalized_canonical
                != normalized_application
            ):
                continue

            normalized_aliases = [
                self.normalize_query(alias)
                for alias in aliases
            ]

            if query in normalized_aliases:
                return True

        return False

    # =========================================================
    # SAFE ALIAS EVIDENCE
    # =========================================================

    @staticmethod
    def _has_safe_alias_evidence(
        candidate: ResolutionCandidate,
    ) -> bool:
        """Return True when candidate contains safe alias evidence."""

        return any(
            evidence.signal == "safe_alias"
            for evidence in candidate.evidence
        )

    # =========================================================
    # ABBREVIATION
    # =========================================================

    @staticmethod
    def _is_abbreviation_match(
        query: str,
        application_name: str,
    ) -> bool:
        """
        Detect simple initial-based abbreviations.

        Example:

            Visual Studio Code -> vsc
            Microsoft Store -> ms
        """

        query = (
            ApplicationResolutionEngine
            .normalize_query(query)
        )

        name = (
            ApplicationResolutionEngine
            .normalize_query(application_name)
        )

        words = name.split()

        if len(words) < 2:
            return False

        initials = "".join(
            word[0]
            for word in words
            if word
        )

        return (
            query == initials
            and len(query) >= 2
        )

    # =========================================================
    # TOKENIZATION
    # =========================================================

    @staticmethod
    def _tokens(
        value: str,
    ) -> set:
        """Convert normalized text into tokens."""

        value = (
            ApplicationResolutionEngine
            .normalize_query(value)
        )

        if not value:
            return set()

        return set(
            value.split()
        )

    # =========================================================
    # CLEANING
    # =========================================================

    @staticmethod
    def _clean(
        value,
    ) -> str:
        """Safely convert a value into a stripped string."""

        if value is None:
            return ""

        return str(value).strip()

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def normalize_query(
        value,
    ) -> str:
        """
        Normalize human application references.

        Examples:

            Open Chrome
                -> chrome

            launch Calculator.exe
                -> calculator

            Visual-Studio-Code
                -> visual studio code
        """

        if value is None:
            return ""

        value = str(
            value
        ).strip().lower()

        # -----------------------------------------------------
        # Remove command prefixes
        # -----------------------------------------------------

        value = re.sub(
            r"^(open|launch|start|run)\s+",
            "",
            value,
        )

        # -----------------------------------------------------
        # Remove executable extension
        # -----------------------------------------------------

        value = re.sub(
            r"\.exe$",
            "",
            value,
        )

        # -----------------------------------------------------
        # Normalize punctuation
        # -----------------------------------------------------

        value = re.sub(
            r"[_\-]+",
            " ",
            value,
        )

        # -----------------------------------------------------
        # Collapse whitespace
        # -----------------------------------------------------

        value = " ".join(
            value.split()
        )

        return value

    # =========================================================
    # PATH NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize_path(
        value,
    ) -> str:
        """Normalize executable/path identity."""

        if value is None:
            return ""

        return (
            str(value)
            .strip()
            .lower()
            .replace(
                "/",
                "\\",
            )
        )

    # =========================================================
    # CONFIDENCE
    # =========================================================

    @staticmethod
    def _confidence_for_score(
        score: float,
    ) -> ResolutionConfidence:

        if (
            score
            >= ApplicationResolutionEngine
            .VERY_HIGH_CONFIDENCE_THRESHOLD
        ):
            return ResolutionConfidence.VERY_HIGH

        if (
            score
            >= ApplicationResolutionEngine
            .HIGH_CONFIDENCE_THRESHOLD
        ):
            return ResolutionConfidence.HIGH

        if score >= 75:
            return ResolutionConfidence.MEDIUM

        if score > 0:
            return ResolutionConfidence.LOW

        return ResolutionConfidence.NONE

    # =========================================================
    # NOT FOUND
    # =========================================================

    @staticmethod
    def _not_found(
        query: str,
        normalized_query: str,
        reason: str,
    ) -> ResolutionResult:
        """Construct a safe NOT_FOUND result."""

        return ResolutionResult(
            decision=ResolutionDecision.NOT_FOUND,
            confidence=ResolutionConfidence.NONE,
            query=query,
            normalized_query=normalized_query,
            application=None,
            score=0.0,
            candidates=[],
            reasons=[reason],
            safety={
                "execution_allowed": False,
                "requires_confirmation": True,
                "resolution_only": True,
            },
        )