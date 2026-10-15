"""
Genesis OS — Application Identity & Confidence Engine

LEVEL 3.2.3C.1
---------------

Determines whether two application discovery records
represent the same underlying application.

Important principles:

1. Discovery never executes anything.
2. Strong evidence is preferred over name similarity.
3. Fuzzy name similarity is never sufficient by itself
   for a high-confidence merge.
4. Every identity decision contains evidence.
5. "Unknown" is safer than an incorrect merge.

Future layers can use this information for:

    - trusted application execution
    - explainability
    - security verification
    - automation
    - application lifecycle management
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os
import re
from typing import Any, Dict, List, Optional, Tuple


class IdentityDecision(str, Enum):
    """
    Final identity relationship between two records.
    """

    SAME = "same"
    DIFFERENT = "different"
    UNCERTAIN = "uncertain"


@dataclass
class IdentityEvidence:
    """
    One piece of evidence used during identity analysis.
    """

    signal: str
    score: int
    description: str
    strength: str

    def to_dict(self) -> dict:
        return {
            "signal": self.signal,
            "score": self.score,
            "description": self.description,
            "strength": self.strength,
        }


@dataclass
class IdentityResult:
    """
    Complete identity-analysis result.

    This is intentionally explainable.

    Genesis should eventually be able to say:

        "I believe these are the same application
         because their AppID matches."

    rather than simply returning True/False.
    """

    decision: IdentityDecision
    confidence: int
    evidence: List[IdentityEvidence] = field(
        default_factory=list
    )

    reasons: List[str] = field(
        default_factory=list
    )

    conflicts: List[str] = field(
        default_factory=list
    )

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "confidence": self.confidence,
            "evidence": [
                item.to_dict()
                for item in self.evidence
            ],
            "reasons": list(self.reasons),
            "conflicts": list(self.conflicts),
        }


class ApplicationIdentityEngine:
    """
    Determines application identity using layered evidence.

    Evidence priority:

        Tier 1
            AppID

        Tier 2
            Package identity

        Tier 3
            Executable identity

        Tier 4
            Installation location

        Tier 5
            Publisher

        Tier 6
            Human-readable name

        Tier 7
            Alias / normalized name similarity

    The engine deliberately separates:

        identity evidence

    from:

        launch authorization
    """

    VERSION = "1.0"

    # ---------------------------------------------------------
    # Confidence thresholds
    # ---------------------------------------------------------

    SAME_THRESHOLD = 75
    DIFFERENT_THRESHOLD = -60

    HIGH_CONFIDENCE = 90
    MEDIUM_CONFIDENCE = 75

    # ---------------------------------------------------------
    # Evidence weights
    # ---------------------------------------------------------

    APP_ID_EXACT = 100

    PACKAGE_NAME_EXACT = 95
    PACKAGE_FAMILY_EXACT = 95
    PACKAGE_FULL_NAME_EXACT = 95

    EXECUTABLE_EXACT = 90

    INSTALL_LOCATION_EXACT = 80

    PUBLISHER_EXACT = 25

    NAME_EXACT = 45
    ALIAS_EXACT = 35
    NAME_SIMILAR = 15

    # Conflicting evidence
    APP_ID_CONFLICT = -100
    PACKAGE_CONFLICT = -90
    EXECUTABLE_CONFLICT = -85

    def compare(
        self,
        first: Dict[str, Any],
        second: Dict[str, Any],
    ) -> IdentityResult:
        """
        Compare two discovery records.

        Returns a complete explainable identity result.
        """

        evidence: List[
            IdentityEvidence
        ] = []

        conflicts: List[str] = []

        # -----------------------------------------------------
        # Tier 1 — AppID
        # -----------------------------------------------------

        self._compare_identifier(
            first,
            second,
            "app_id",
            self.APP_ID_EXACT,
            self.APP_ID_CONFLICT,
            "AppID",
            evidence,
            conflicts,
        )

        # -----------------------------------------------------
        # Tier 2 — Package identity
        # -----------------------------------------------------

        self._compare_identifier(
            first,
            second,
            "package_name",
            self.PACKAGE_NAME_EXACT,
            self.PACKAGE_CONFLICT,
            "package name",
            evidence,
            conflicts,
        )

        self._compare_identifier(
            first,
            second,
            "package_family_name",
            self.PACKAGE_FAMILY_EXACT,
            self.PACKAGE_CONFLICT,
            "package family",
            evidence,
            conflicts,
        )

        self._compare_identifier(
            first,
            second,
            "package_full_name",
            self.PACKAGE_FULL_NAME_EXACT,
            self.PACKAGE_CONFLICT,
            "package full name",
            evidence,
            conflicts,
        )

        # -----------------------------------------------------
        # Tier 3 — Executable
        # -----------------------------------------------------

        self._compare_executable(
            first,
            second,
            evidence,
            conflicts,
        )

        # -----------------------------------------------------
        # Tier 4 — Installation location
        # -----------------------------------------------------

        self._compare_identifier(
            first,
            second,
            "install_location",
            self.INSTALL_LOCATION_EXACT,
            0,
            "installation location",
            evidence,
            conflicts,
        )

        # -----------------------------------------------------
        # Tier 5 — Publisher
        # -----------------------------------------------------

        self._compare_identifier(
            first,
            second,
            "publisher_id",
            self.PUBLISHER_EXACT,
            0,
            "publisher",
            evidence,
            conflicts,
        )

        # -----------------------------------------------------
        # Tier 6/7 — Names and aliases
        # -----------------------------------------------------

        self._compare_names(
            first,
            second,
            evidence,
        )

        # -----------------------------------------------------
        # Calculate final result
        # -----------------------------------------------------

        total = sum(
            item.score
            for item in evidence
        )

        return self._build_result(
            total,
            evidence,
            conflicts,
        )

    # =========================================================
    # IDENTIFIER COMPARISON
    # =========================================================

    def _compare_identifier(
        self,
        first: Dict[str, Any],
        second: Dict[str, Any],
        field: str,
        match_score: int,
        conflict_score: int,
        label: str,
        evidence: List[IdentityEvidence],
        conflicts: List[str],
    ) -> None:

        left = self._normalize_identifier(
            first.get(field)
        )

        right = self._normalize_identifier(
            second.get(field)
        )

        if not left or not right:
            return

        if left == right:

            evidence.append(
                IdentityEvidence(
                    signal=f"{field}.exact_match",
                    score=match_score,
                    description=(
                        f"{label} matches exactly."
                    ),
                    strength=(
                        "very_strong"
                        if match_score >= 90
                        else "strong"
                    ),
                )
            )

        elif conflict_score:

            evidence.append(
                IdentityEvidence(
                    signal=f"{field}.conflict",
                    score=conflict_score,
                    description=(
                        f"{label} values conflict."
                    ),
                    strength="critical",
                )
            )

            conflicts.append(
                f"{label} conflict"
            )

    # =========================================================
    # EXECUTABLE COMPARISON
    # =========================================================

    def _compare_executable(
        self,
        first: Dict[str, Any],
        second: Dict[str, Any],
        evidence: List[IdentityEvidence],
        conflicts: List[str],
    ) -> None:

        first_values = self._collect_values(
            first,
            [
                "executable",
                "path",
            ],
        )

        second_values = self._collect_values(
            second,
            [
                "executable",
                "path",
            ],
        )

        first_normalized = {
            self._normalize_path(value)
            for value in first_values
            if value
        }

        second_normalized = {
            self._normalize_path(value)
            for value in second_values
            if value
        }

        if not first_normalized or not second_normalized:
            return

        intersection = (
            first_normalized
            & second_normalized
        )

        if intersection:

            evidence.append(
                IdentityEvidence(
                    signal="executable.exact_match",
                    score=self.EXECUTABLE_EXACT,
                    description=(
                        "Executable/path identity matches."
                    ),
                    strength="very_strong",
                )
            )

            return

        # Different executables are not automatically
        # proof of different applications because a single
        # application can legitimately expose multiple
        # executables.

    # =========================================================
    # NAME COMPARISON
    # =========================================================

    def _compare_names(
        self,
        first: Dict[str, Any],
        second: Dict[str, Any],
        evidence: List[IdentityEvidence],
    ) -> None:

        first_names = self._collect_names(
            first
        )

        second_names = self._collect_names(
            second
        )

        if not first_names or not second_names:
            return

        # Exact normalized name
        if first_names & second_names:

            evidence.append(
                IdentityEvidence(
                    signal="name.exact_match",
                    score=self.NAME_EXACT,
                    description=(
                        "Human-readable application name "
                        "matches exactly."
                    ),
                    strength="medium",
                )
            )

            return

        # Similarity search
        best_similarity = 0.0

        for left in first_names:

            for right in second_names:

                similarity = (
                    self._name_similarity(
                        left,
                        right,
                    )
                )

                if similarity > best_similarity:

                    best_similarity = similarity

        if best_similarity >= 0.85:

            evidence.append(
                IdentityEvidence(
                    signal="name.similarity",
                    score=self.NAME_SIMILAR,
                    description=(
                        "Application names are highly similar."
                    ),
                    strength="weak",
                )
            )

    # =========================================================
    # RESULT BUILDING
    # =========================================================

    def _build_result(
        self,
        total: int,
        evidence: List[IdentityEvidence],
        conflicts: List[str],
    ) -> IdentityResult:

        # -----------------------------------------------------
        # Critical identity conflict
        # -----------------------------------------------------

        if any(
            item.score <= -90
            for item in evidence
        ):

            decision = (
                IdentityDecision.DIFFERENT
            )

            confidence = 100

            reasons = [
                "Strong identity evidence conflicts."
            ]

            return IdentityResult(
                decision=decision,
                confidence=confidence,
                evidence=evidence,
                reasons=reasons,
                conflicts=conflicts,
            )

        # -----------------------------------------------------
        # Strong positive identity
        # -----------------------------------------------------

        if total >= self.SAME_THRESHOLD:

            confidence = min(
                100,
                total
            )

            return IdentityResult(
                decision=IdentityDecision.SAME,
                confidence=confidence,
                evidence=evidence,
                reasons=[
                    self._primary_reason(
                        evidence,
                        "same",
                    )
                ],
                conflicts=conflicts,
            )

        # -----------------------------------------------------
        # Strong negative identity
        # -----------------------------------------------------

        if total <= self.DIFFERENT_THRESHOLD:

            return IdentityResult(
                decision=IdentityDecision.DIFFERENT,
                confidence=min(
                    100,
                    abs(total)
                ),
                evidence=evidence,
                reasons=[
                    "Identity evidence strongly disagrees."
                ],
                conflicts=conflicts,
            )

        # -----------------------------------------------------
        # Unknown / insufficient evidence
        # -----------------------------------------------------

        uncertainty = min(
            99,
            max(
                1,
                50 + abs(total) // 2,
            ),
        )

        return IdentityResult(
            decision=IdentityDecision.UNCERTAIN,
            confidence=uncertainty,
            evidence=evidence,
            reasons=[
                "Available evidence is insufficient "
                "for a safe automatic identity decision."
            ],
            conflicts=conflicts,
        )

    # =========================================================
    # PRIMARY EXPLANATION
    # =========================================================

    @staticmethod
    def _primary_reason(
        evidence: List[IdentityEvidence],
        relationship: str,
    ) -> str:

        if not evidence:

            return (
                "No identity evidence was available."
            )

        strongest = max(
            evidence,
            key=lambda item: abs(
                item.score
            ),
        )

        if relationship == "same":

            return (
                "Strongest matching evidence: "
                + strongest.description
            )

        return strongest.description

    # =========================================================
    # NAME COLLECTION
    # =========================================================

    def _collect_names(
        self,
        application: Dict[str, Any],
    ) -> set[str]:

        values = []

        values.append(
            application.get(
                "name"
            )
        )

        aliases = application.get(
            "aliases",
            []
        )

        if isinstance(
            aliases,
            list,
        ):

            values.extend(
                aliases
            )

        return {
            self._normalize_name(
                value
            )
            for value in values
            if value
        }

    # =========================================================
    # VALUE COLLECTION
    # =========================================================

    @staticmethod
    def _collect_values(
        application: Dict[str, Any],
        fields: List[str],
    ) -> List[str]:

        values = []

        for field in fields:

            value = application.get(
                field
            )

            if value:

                if isinstance(
                    value,
                    list,
                ):

                    values.extend(
                        value
                    )

                else:

                    values.append(
                        value
                    )

        return [
            str(value)
            for value in values
            if value
        ]

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize_identifier(
        value: Any
    ) -> str:

        if value is None:
            return ""

        return (
            str(value)
            .strip()
            .lower()
        )

    @staticmethod
    def _normalize_path(
        value: Any
    ) -> str:

        if value is None:
            return ""

        value = (
            str(value)
            .strip()
            .lower()
        )

        value = os.path.normpath(
            value
        )

        return value.replace(
            "/",
            "\\",
        )

    @staticmethod
    def _normalize_name(
        value: Any
    ) -> str:

        if value is None:
            return ""

        value = (
            str(value)
            .strip()
            .lower()
        )

        value = re.sub(
            r"\.exe$",
            "",
            value,
        )

        value = re.sub(
            r"[^a-z0-9]+",
            " ",
            value,
        )

        return " ".join(
            value.split()
        )

    # =========================================================
    # NAME SIMILARITY
    # =========================================================

    @staticmethod
    def _name_similarity(
        first: str,
        second: str,
    ) -> float:

        if not first or not second:
            return 0.0

        if first == second:
            return 1.0

        first_tokens = set(
            first.split()
        )

        second_tokens = set(
            second.split()
        )

        if not first_tokens or not second_tokens:
            return 0.0

        intersection = (
            first_tokens
            & second_tokens
        )

        union = (
            first_tokens
            | second_tokens
        )

        return (
            len(intersection)
            / len(union)
        )