"""
Genesis OS â€” Unified Application Discovery

LEVEL 3.2.3C
------------

Combines:

    3.2.3A
        Start Menu + PATH discovery

    3.2.3B
        Windows AppX + StartApps discovery

    3.2.3C.1
        Application Identity & Confidence Engine

    3.2.3C.2
        Identity-Aware Deduplication

Important architectural rule:

    Discovery != Execution

This module only discovers, merges, classifies and
deduplicates application information.

It does NOT launch applications.

Architecture:

    Discovery Sources
            |
            v
    Raw Application Records
            |
            v
    Canonical Key Check
            |
            v
    Identity & Confidence Engine
            |
       +----+----+
       |         |
      SAME    UNCERTAIN /
       |       DIFFERENT
       v         |
     MERGE       |
                 v
              KEEP SEPARATE

Safety principle:

    UNCERTAIN is NEVER treated as SAME.

Genesis must have strong evidence before two
applications are automatically merged.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from genesis_os.applications.app_discovery import (
    ApplicationDiscovery
)

from genesis_os.applications.windows_registered_apps import (
    WindowsRegisteredApplicationDiscovery
)

from genesis_os.applications.application_identity import (
    ApplicationIdentityEngine,
    IdentityDecision,
)


class UnifiedApplicationDiscovery:
    """
    Unified application discovery engine.

    Responsibilities:

        - collect all discovery sources
        - normalize names
        - identify probable duplicates
        - create canonical records
        - preserve source records
        - classify applications
        - provide search
        - provide resolution
        - perform identity-aware deduplication
        - preserve explainable identity evidence

    This class never launches an application.
    """

    VERSION = "1.1"

    def __init__(self):

        # =====================================================
        # DISCOVERY SOURCES
        # =====================================================

        self.traditional_discovery = (
            ApplicationDiscovery()
        )

        self.registered_discovery = (
            WindowsRegisteredApplicationDiscovery()
        )

        # =====================================================
        # IDENTITY ENGINE
        # =====================================================

        self.identity_engine = (
            ApplicationIdentityEngine()
        )

        # =====================================================
        # CANONICAL APPLICATION REGISTRY
        # =====================================================

        self._applications: Dict[str, dict] = {}

        # =====================================================
        # IDENTITY STATISTICS
        # =====================================================

        self._identity_statistics = (
            self._new_identity_statistics()
        )

        # =====================================================
        # EXPLAINABLE IDENTITY DECISIONS
        # =====================================================

        self._merge_decisions = []

    # =========================================================
    # INTERNAL STATE
    # =========================================================

    @staticmethod
    def _new_identity_statistics() -> dict:
        """
        Create a fresh identity-statistics structure.
        """

        return {
            "records_seen": 0,
            "records_merged": 0,
            "same_decisions": 0,
            "different_decisions": 0,
            "uncertain_decisions": 0,
        }

    # =========================================================
    # PUBLIC DISCOVERY
    # =========================================================

    def discover(
        self,
        refresh: bool = False
    ) -> List[dict]:
        """
        Discover and unify all available applications.

        refresh=False:
            Return cached canonical applications.

        refresh=True:
            Rebuild the complete application index.
        """

        # -----------------------------------------------------
        # CACHE
        # -----------------------------------------------------

        if (
            self._applications
            and not refresh
        ):

            return list(
                self._applications.values()
            )

        # -----------------------------------------------------
        # RESET STATE
        # -----------------------------------------------------

        self._applications = {}

        self._identity_statistics = (
            self._new_identity_statistics()
        )

        self._merge_decisions = []

        # -----------------------------------------------------
        # SOURCE A â€” Traditional discovery
        # -----------------------------------------------------

        traditional = (
            self.traditional_discovery.discover(
                refresh=refresh
            )
        )

        # -----------------------------------------------------
        # SOURCE B â€” Windows registered apps
        # -----------------------------------------------------

        registered = (
            self.registered_discovery.discover()
        )

        # -----------------------------------------------------
        # ADD TRADITIONAL RECORDS
        # -----------------------------------------------------

        for application in traditional:

            self._add_or_merge(
                application,
                source_group="traditional"
            )

        # -----------------------------------------------------
        # ADD WINDOWS REGISTERED RECORDS
        # -----------------------------------------------------

        for application in registered:

            self._add_or_merge(
                application,
                source_group="registered"
            )

        # -----------------------------------------------------
        # RETURN CANONICAL INDEX
        # -----------------------------------------------------

        return list(
            self._applications.values()
        )

    # =========================================================
    # ADD / MERGE
    # =========================================================

    def _add_or_merge(
        self,
        application: dict,
        source_group: str
    ) -> None:
        """
        Add a raw discovery record to the canonical registry.

        Identity-aware process:

            1. Validate the record.
            2. Try deterministic canonical-key matching.
            3. If no match exists, perform identity analysis
               against existing canonical applications.
            4. Merge ONLY when identity says SAME.
            5. Keep UNCERTAIN records separate.
            6. Keep DIFFERENT applications separate.
            7. Create a new canonical record when no safe
               identity match exists.

        Important:

            UNCERTAIN != SAME
            DIFFERENT != SAME
        """

        name = self._clean(
            application.get("name")
        )

        if not name:
            return

        # -----------------------------------------------------
        # Record statistics
        # -----------------------------------------------------

        self._identity_statistics[
            "records_seen"
        ] += 1

        # -----------------------------------------------------
        # Deterministic canonical key
        # -----------------------------------------------------

        canonical_key = (
            self._canonical_key(
                application
            )
        )

        # -----------------------------------------------------
        # FIRST PATH
        #
        # Exact canonical-key match.
        # -----------------------------------------------------

        existing = (
            self._applications.get(
                canonical_key
            )
        )

        if existing is not None:

            result = (
                self._compare_existing_with_candidate(
                    existing,
                    application,
                )
            )

            self._record_identity_decision(
                existing,
                application,
                result,
                method="canonical_key",
            )

            if (
                result.decision
                == IdentityDecision.SAME
            ):

                self._merge_record(
                    existing,
                    application,
                    source_group,
                )

                self._identity_statistics[
                    "records_merged"
                ] += 1

                return

        # -----------------------------------------------------
        # SECOND PATH
        #
        # Identity-aware comparison against existing
        # canonical applications.
        #
        # This is deliberately outside the previous
        # "existing is not None" block.
        # -----------------------------------------------------

        for existing in list(
            self._applications.values()
        ):

            # Don't compare the exact same canonical object
            # against itself.
            if existing is application:
                continue

            result = (
                self._compare_existing_with_candidate(
                    existing,
                    application,
                )
            )

            self._record_identity_decision(
                existing,
                application,
                result,
                method="identity_engine",
            )

            if (
                result.decision
                == IdentityDecision.SAME
            ):

                self._merge_record(
                    existing,
                    application,
                    source_group,
                )

                self._identity_statistics[
                    "records_merged"
                ] += 1

                return

        # -----------------------------------------------------
        # NO SAFE MATCH
        #
        # This includes:
        #
        #     DIFFERENT
        #     UNCERTAIN
        #
        # Both remain separate.
        # -----------------------------------------------------

        self._applications[
            self._make_unique_registry_key(
                canonical_key
            )
        ] = (
            self._create_canonical_record(
                application,
                source_group,
            )
        )

    # =========================================================
    # IDENTITY BRIDGE
    # =========================================================

    def _compare_existing_with_candidate(
        self,
        existing: dict,
        candidate: dict,
    ):
        """
        Compare a canonical application against a raw
        discovery record.

        Canonical records intentionally contain collections:

            app_ids
            package_names
            executables
            paths
            aliases

        The identity engine operates on discovery-style
        identity fields.

        Therefore we compare the candidate against each
        preserved raw record belonging to the canonical
        application.

        If ANY raw record provides strong SAME evidence,
        the applications are considered the same.

        This preserves the original discovery evidence
        instead of throwing it away during canonicalization.
        """

        raw_records = existing.get(
            "raw_records",
            []
        )

        # -----------------------------------------------------
        # No raw records should normally be impossible, but
        # handle it safely.
        # -----------------------------------------------------

        if not raw_records:

            return (
                self.identity_engine.compare(
                    existing,
                    candidate,
                )
            )

        best_result = None

        # -----------------------------------------------------
        # Compare candidate against every raw representation.
        # -----------------------------------------------------

        for raw_record in raw_records:

            result = (
                self.identity_engine.compare(
                    raw_record,
                    candidate,
                )
            )

            # -------------------------------------------------
            # Strong SAME immediately wins.
            # -------------------------------------------------

            if (
                result.decision
                == IdentityDecision.SAME
            ):

                return result

            # -------------------------------------------------
            # Preserve the strongest non-SAME result so that
            # the caller still receives useful evidence.
            # -------------------------------------------------

            if best_result is None:

                best_result = result

            else:

                if (
                    result.confidence
                    > best_result.confidence
                ):

                    best_result = result

        # -----------------------------------------------------
        # If no raw records produced a result, fall back to
        # the canonical record.
        # -----------------------------------------------------

        if best_result is None:

            return (
                self.identity_engine.compare(
                    existing,
                    candidate,
                )
            )

        return best_result

    # =========================================================
    # UNIQUE REGISTRY KEY
    # =========================================================

    def _make_unique_registry_key(
        self,
        canonical_key: str
    ) -> str:
        """
        Prevent accidental registry overwrites.

        Normally canonical keys are unique.

        If two uncertain records produce the same key,
        preserve both rather than silently destroying one.
        """

        if (
            canonical_key
            not in self._applications
        ):

            return canonical_key

        counter = 2

        while True:

            candidate_key = (
                f"{canonical_key}"
                f":instance:{counter}"
            )

            if (
                candidate_key
                not in self._applications
            ):

                return candidate_key

            counter += 1

    # =========================================================
    # IDENTITY DECISION RECORDING
    # =========================================================

    def _record_identity_decision(
        self,
        existing: dict,
        candidate: dict,
        result,
        method: str,
    ) -> None:
        """
        Preserve explainable identity decisions.

        This information will later support the Genesis
        Explainable Trust Layer.

        Statistics:

            SAME
            DIFFERENT
            UNCERTAIN

        are kept separately.

        A bounded decision history prevents uncontrolled
        memory growth.
        """

        if (
            result.decision
            == IdentityDecision.SAME
        ):

            self._identity_statistics[
                "same_decisions"
            ] += 1

        elif (
            result.decision
            == IdentityDecision.DIFFERENT
        ):

            self._identity_statistics[
                "different_decisions"
            ] += 1

        else:

            self._identity_statistics[
                "uncertain_decisions"
            ] += 1

        # -----------------------------------------------------
        # Keep at most 500 explainable decisions.
        # -----------------------------------------------------

        if len(
            self._merge_decisions
        ) >= 500:

            return

        self._merge_decisions.append(
            {
                "existing": existing.get(
                    "name"
                ),

                "candidate": candidate.get(
                    "name"
                ),

                "decision": (
                    result.decision.value
                ),

                "confidence": (
                    result.confidence
                ),

                "method": method,

                "evidence": [
                    item.to_dict()
                    for item in result.evidence
                ],

                "reasons": list(
                    result.reasons
                ),

                "conflicts": list(
                    result.conflicts
                ),
            }
        )

    # =========================================================
    # CANONICAL RECORD
    # =========================================================

    def _create_canonical_record(
        self,
        application: dict,
        source_group: str
    ) -> dict:
        """
        Create the canonical application representation.
        """

        name = self._clean(
            application.get("name")
        )

        record = {
            "id": self._canonical_key(
                application
            ),

            "name": name,

            "normalized_name":
                self._normalize_name(
                    name
                ),

            "category":
                self._classify(
                    application
                ),

            "launchable":
                self._is_launchable(
                    application
                ),

            "available":
                bool(
                    application.get(
                        "available",
                        True
                    )
                ),

            "sources": [],

            "aliases": [],

            "paths": [],

            "executables": [],

            "uris": [],

            "app_ids": [],

            "package_names": [],

            "package_full_names": [],

            "package_family_names": [],

            "versions": [],

            "publishers": [],

            "install_locations": [],

            "raw_records": [],
        }

        self._merge_record(
            record,
            application,
            source_group
        )

        return record

    # =========================================================
    # MERGE RECORD
    # =========================================================

    def _merge_record(
        self,
        target: dict,
        application: dict,
        source_group: str
    ) -> None:
        """
        Enrich a canonical application record.
        """

        name = self._clean(
            application.get("name")
        )

        # -----------------------------------------------------
        # Source
        # -----------------------------------------------------

        source = self._clean(
            application.get(
                "source"
            )
        )

        source_entry = {
            "group": source_group,
            "source": source,
            "type": application.get(
                "type"
            ),
        }

        if source_entry not in target[
            "sources"
        ]:

            target[
                "sources"
            ].append(
                source_entry
            )

        # -----------------------------------------------------
        # Raw record preservation
        # -----------------------------------------------------

        if application not in target[
            "raw_records"
        ]:

            target[
                "raw_records"
            ].append(
                dict(application)
            )

        # -----------------------------------------------------
        # Alias
        # -----------------------------------------------------

        if name:

            self._append_unique(
                target[
                    "aliases"
                ],
                name
            )

        # -----------------------------------------------------
        # Path
        # -----------------------------------------------------

        path = self._clean(
            application.get(
                "path"
            )
        )

        if path:

            self._append_unique(
                target[
                    "paths"
                ],
                path
            )

        # -----------------------------------------------------
        # Executable
        # -----------------------------------------------------

        executable = self._clean(
            application.get(
                "executable"
            )
        )

        if executable:

            self._append_unique(
                target[
                    "executables"
                ],
                executable
            )

        # -----------------------------------------------------
        # URI
        # -----------------------------------------------------

        uri = self._clean(
            application.get(
                "uri"
            )
        )

        if uri:

            self._append_unique(
                target[
                    "uris"
                ],
                uri
            )

        # -----------------------------------------------------
        # App ID
        # -----------------------------------------------------

        app_id = self._clean(
            application.get(
                "app_id"
            )
        )

        if app_id:

            self._append_unique(
                target[
                    "app_ids"
                ],
                app_id
            )

        # -----------------------------------------------------
        # Package information
        # -----------------------------------------------------

        self._append_field(
            target,
            application,
            "package_name",
            "package_names"
        )

        self._append_field(
            target,
            application,
            "package_full_name",
            "package_full_names"
        )

        self._append_field(
            target,
            application,
            "package_family_name",
            "package_family_names"
        )

        # -----------------------------------------------------
        # Version
        # -----------------------------------------------------

        self._append_field(
            target,
            application,
            "version",
            "versions"
        )

        # -----------------------------------------------------
        # Publisher
        # -----------------------------------------------------

        self._append_field(
            target,
            application,
            "publisher_id",
            "publishers"
        )

        # -----------------------------------------------------
        # Installation location
        # -----------------------------------------------------

        self._append_field(
            target,
            application,
            "install_location",
            "install_locations"
        )

        # -----------------------------------------------------
        # Launchability
        # -----------------------------------------------------

        if self._is_launchable(
            application
        ):

            target[
                "launchable"
            ] = True

        # -----------------------------------------------------
        # Availability
        # -----------------------------------------------------

        if application.get(
            "available",
            False
        ):

            target[
                "available"
            ] = True

        # -----------------------------------------------------
        # Better human-readable name
        # -----------------------------------------------------

        self._choose_better_name(
            target,
            application
        )

        # -----------------------------------------------------
        # Recalculate category
        # -----------------------------------------------------

        target[
            "category"
        ] = self._classify_canonical(
            target
        )

    # =========================================================
    # CANONICAL KEY
    # =========================================================

    def _canonical_key(
        self,
        application: dict
    ) -> str:
        """
        Generate a stable identity key.

        Priority:

            1. App ID
            2. executable path
            3. package family
            4. normalized human name
        """

        app_id = self._clean(
            application.get(
                "app_id"
            )
        )

        if app_id:

            return (
                "appid:"
                + self._normalize_identifier(
                    app_id
                )
            )

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

        package_family = self._clean(
            application.get(
                "package_family_name"
            )
        )

        if package_family:

            return (
                "package:"
                + self._normalize_identifier(
                    package_family
                )
            )

        name = self._clean(
            application.get("name")
        )

        return (
            "name:"
            + self._normalize_name(
                name
            )
        )

    # =========================================================
    # CLASSIFICATION
    # =========================================================

    def _classify(
        self,
        application: dict
    ) -> str:
        """
        Classify an individual discovery record.
        """

        app_type = self._clean(
            application.get(
                "type"
            )
        ).lower()

        name = self._normalize_name(
            application.get(
                "name",
                ""
            )
        )

        if (
            app_type
            == "packaged_application"
        ):

            return "windows_packaged"

        if (
            app_type
            == "registered_application"
        ):

            return "windows_registered"

        if (
            app_type
            == "shortcut"
        ):

            return "user_application"

        if (
            app_type
            == "executable"
        ):

            return self._classify_executable(
                name
            )

        return "unknown"

    # =========================================================
    # CANONICAL CLASSIFICATION
    # =========================================================

    def _classify_canonical(
        self,
        application: dict
    ) -> str:
        """
        Classify a unified application.

        Registered/packaged applications take priority
        over raw system executable signals.
        """

        categories = []

        for source in application.get(
            "sources",
            []
        ):

            source_type = self._clean(
                source.get(
                    "type"
                )
            )

            if source_type:

                categories.append(
                    source_type
                )

        if (
            "packaged_application"
            in categories
        ):

            return "windows_packaged"

        if (
            "registered_application"
            in categories
        ):

            return "windows_registered"

        if (
            "shortcut"
            in categories
        ):

            return "user_application"

        if (
            "executable"
            in categories
        ):

            return "executable"

        return "unknown"

    # =========================================================
    # EXECUTABLE CLASSIFICATION
    # =========================================================

    @staticmethod
    def _classify_executable(
        name: str
    ) -> str:
        """
        Basic safety-oriented classification for raw
        executable discovery.

        This does NOT determine whether a process is
        malicious.

        That belongs to the future Security layer.
        """

        system_names = {
            "audiodg",
            "autochk",
            "autoconv",
            "attrib",
            "cmd",
            "conhost",
            "csrss",
            "dwm",
            "explorer",
            "fontdrvhost",
            "lsass",
            "msconfig",
            "msedge",
            "notepad",
            "regedit",
            "rundll32",
            "services",
            "smartscreen",
            "spoolsv",
            "svchost",
            "taskhostw",
            "taskkill",
            "tasklist",
            "wininit",
            "winlogon",
        }

        if name in system_names:

            return "system_executable"

        return "executable"

    # =========================================================
    # LAUNCHABILITY
    # =========================================================

    @staticmethod
    def _is_launchable(
        application: dict
    ) -> bool:
        """
        Determine whether a discovery record appears
        launchable.

        This is NOT authorization.

        It only means that the record contains enough
        information to potentially be launched.
        """

        if application.get(
            "launch_target"
        ):

            return True

        if application.get(
            "executable"
        ):

            return True

        if application.get(
            "app_id"
        ):

            return True

        if application.get(
            "uri"
        ):

            return True

        if application.get(
            "path"
        ):

            path = str(
                application.get(
                    "path"
                )
            )

            if path.lower().endswith(
                ".lnk"
            ):

                return True

        return False

    # =========================================================
    # SEARCH
    # =========================================================

    def search(
        self,
        query: str,
        refresh: bool = False
    ) -> List[dict]:
        """
        Search the unified application index.
        """

        query = self._normalize_name(
            query
        )

        if not query:

            return []

        applications = self.discover(
            refresh=refresh
        )

        results = []

        for application in applications:

            names = [
                application.get(
                    "name",
                    ""
                )
            ]

            names.extend(
                application.get(
                    "aliases",
                    []
                )
            )

            normalized_names = [
                self._normalize_name(
                    value
                )
                for value in names
            ]

            if any(
                query in value
                for value in normalized_names
                if value
            ):

                results.append(
                    application
                )

        return results

    # =========================================================
    # EXACT RESOLUTION
    # =========================================================

    def resolve(
        self,
        name: str,
        refresh: bool = False
    ) -> Optional[dict]:
        """
        Resolve a human application name.

        Resolution order:

            1. exact canonical name
            2. exact alias
            3. unique partial match
            4. otherwise None
        """

        query = self._normalize_name(
            name
        )

        if not query:

            return None

        applications = self.discover(
            refresh=refresh
        )

        # -----------------------------------------------------
        # Exact canonical name
        # -----------------------------------------------------

        for application in applications:

            if (
                application.get(
                    "normalized_name"
                )
                == query
            ):

                return application

        # -----------------------------------------------------
        # Exact alias
        # -----------------------------------------------------

        exact_aliases = []

        for application in applications:

            aliases = [
                self._normalize_name(
                    alias
                )
                for alias in application.get(
                    "aliases",
                    []
                )
            ]

            if query in aliases:

                exact_aliases.append(
                    application
                )

        if len(
            exact_aliases
        ) == 1:

            return exact_aliases[0]

        # -----------------------------------------------------
        # Partial search
        # -----------------------------------------------------

        matches = self.search(
            query
        )

        if len(
            matches
        ) == 1:

            return matches[0]

        # -----------------------------------------------------
        # Ambiguous
        # -----------------------------------------------------

        return None

    # =========================================================
    # STATISTICS
    # =========================================================

    def statistics(
        self
    ) -> dict:
        """
        Return useful unified-discovery statistics.
        """

        applications = self.discover()

        categories: Dict[
            str,
            int
        ] = {}

        source_counts: Dict[
            str,
            int
        ] = {}

        multi_source = 0

        for application in applications:

            category = application.get(
                "category",
                "unknown"
            )

            categories[
                category
            ] = (
                categories.get(
                    category,
                    0
                ) + 1
            )

            sources = application.get(
                "sources",
                []
            )

            if len(
                sources
            ) > 1:

                multi_source += 1

            for source in sources:

                source_name = (
                    source.get(
                        "source",
                        "unknown"
                    )
                )

                source_counts[
                    source_name
                ] = (
                    source_counts.get(
                        source_name,
                        0
                    ) + 1
                )

        return {
            "version": self.VERSION,

            "total_applications": len(
                applications
            ),

            "multi_source_applications":
                multi_source,

            "categories":
                categories,

            "sources":
                source_counts,

            "identity":
                dict(
                    self._identity_statistics
                ),

            "merge_decisions_recorded":
                len(
                    self._merge_decisions
                ),
        }

    # =========================================================
    # IDENTITY REPORT
    # =========================================================

    def identity_report(
        self
    ) -> dict:
        """
        Return explainable identity information.

        This will eventually provide evidence to the
        Genesis Explainable Trust Layer.
        """

        self.discover()

        return {
            "version":
                self.identity_engine.VERSION,

            "statistics":
                dict(
                    self._identity_statistics
                ),

            "decisions":
                list(
                    self._merge_decisions
                ),
        }

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _append_unique(
        target: list,
        value
    ) -> None:

        if value not in target:

            target.append(
                value
            )

    @staticmethod
    def _append_field(
        target: dict,
        source: dict,
        source_field: str,
        target_field: str
    ) -> None:

        value = source.get(
            source_field
        )

        if (
            value is not None
            and value != ""
        ):

            UnifiedApplicationDiscovery._append_unique(
                target[
                    target_field
                ],
                value
            )

    @staticmethod
    def _clean(
        value
    ) -> str:

        if value is None:

            return ""

        return str(
            value
        ).strip()

    @staticmethod
    def _normalize_name(
        value
    ) -> str:

        if not isinstance(
            value,
            str
        ):

            return ""

        value = (
            value
            .strip()
            .lower()
        )

        value = re.sub(
            r"\.exe$",
            "",
            value
        )

        return " ".join(
            value.split()
        )

    @staticmethod
    def _normalize_identifier(
        value
    ) -> str:

        return (
            str(value)
            .strip()
            .lower()
        )

    @staticmethod
    def _normalize_path(
        value
    ) -> str:

        return (
            str(value)
            .strip()
            .lower()
            .replace(
                "/",
                "\\"
            )
        )

    @staticmethod
    def _choose_better_name(
        target: dict,
        application: dict
    ) -> None:
        """
        Prefer human-friendly names over package identifiers.
        """

        candidate = str(
            application.get(
                "name",
                ""
            )
        ).strip()

        current = str(
            target.get(
                "name",
                ""
            )
        ).strip()

        if not candidate:

            return

        if not current:

            target["name"] = candidate

            target[
                "normalized_name"
            ] = (
                UnifiedApplicationDiscovery
                ._normalize_name(
                    candidate
                )
            )

            return

        candidate_score = (
            UnifiedApplicationDiscovery
            ._human_name_score(
                candidate
            )
        )

        current_score = (
            UnifiedApplicationDiscovery
            ._human_name_score(
                current
            )
        )

        if candidate_score > current_score:

            target["name"] = candidate

            target[
                "normalized_name"
            ] = (
                UnifiedApplicationDiscovery
                ._normalize_name(
                    candidate
                )
            )

    @staticmethod
    def _human_name_score(
        value: str
    ) -> int:
        """
        Estimate whether a name looks human-friendly.

        This is deliberately conservative.
        """

        score = 0

        if " " in value:

            score += 3

        if not re.fullmatch(
            r"[A-Za-z0-9._-]+",
            value
        ):

            score += 1

        if not re.fullmatch(
            r"[A-Za-z0-9._-]+![A-Za-z0-9._-]+",
            value
        ):

            score += 1

        if not re.fullmatch(
            r"[0-9a-fA-F-]{20,}",
            value
        ):

            score += 1

        return score
