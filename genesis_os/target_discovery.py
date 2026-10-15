"""
Genesis OS — Level 3.8.4 Dynamic Target Discovery.

Discovers possible real-world targets for workflow actions.

This layer does NOT directly assume that a natural-language
target is a path, application name, or executable.

It delegates discovery to existing Genesis intelligence systems.

Architecture:

    TargetQuery
        ↓
    TargetDiscovery
        ↓
    existing File Intelligence
    existing Application Discovery
    existing Application Resolution
        ↓
    TargetCandidate[]
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from .target_models import (
    TARGET_TYPES,
    TargetCandidate,
    TargetQuery,
)


class TargetDiscoveryError(RuntimeError):
    """Raised when target discovery cannot proceed."""


class TargetDiscovery:
    """
    Unified discovery facade.

    Existing Genesis discovery systems are injected rather
    than duplicated.

    This is deliberate: Genesis should have one source of truth
    for file/application discovery.
    """

    VERSION = "3.8.4"

    def __init__(
        self,
        *,
        file_provider: Optional[Any] = None,
        folder_provider: Optional[Any] = None,
        application_provider: Optional[Any] = None,
        context: Optional[Any] = None,
    ):
        self.file_provider = file_provider
        self.folder_provider = folder_provider
        self.application_provider = application_provider
        self.context = context

    # =========================================================
    # PUBLIC API
    # =========================================================

    def discover(
        self,
        query: TargetQuery,
        *,
        context: Optional[Any] = None,
    ) -> tuple[TargetCandidate, ...]:

        if not isinstance(
            query,
            TargetQuery,
        ):
            raise TypeError(
                "discover() requires TargetQuery."
            )
        active_context = context if context is not None else self.context

        if query.target_type == "file":
            return self._discover_files(query, context=active_context)

        if query.target_type == "folder":
            if self.folder_provider is not None:
                return self._discover_folders(query, context=active_context)
            return self._discover_files(query, folders_only=True, context=active_context)

        if query.target_type == "application":
            return self._discover_applications(query, context=active_context)

        if query.target_type == "unknown":
            return self._discover_unknown(query, context=active_context)

        return ()

    def _discover_folders(
        self,
        query: TargetQuery,
        *,
        context: Optional[Any] = None,
    ) -> tuple[TargetCandidate, ...]:
        provider = self.folder_provider
        if provider is None:
            return ()
        raw = self._call_provider(provider, query, context=context)
        candidates = []
        for index, item in enumerate(raw):
            c = self._normalize_file_candidate(item, query, index, folders_only=True)
            if c is not None:
                candidates.append(c)
        return tuple(candidates)

    # =========================================================
    # FILE DISCOVERY
    # =========================================================

    def _discover_files(
        self,
        query: TargetQuery,
        *,
        folders_only: bool = False,
        context: Optional[Any] = None,
    ) -> tuple[TargetCandidate, ...]:

        provider = self.file_provider

        if provider is None:
            return ()

        raw_candidates = self._call_provider(
            provider,
            query,
            context=context,
        )

        candidates = []

        for index, item in enumerate(
            raw_candidates
        ):

            candidate = (
                self._normalize_file_candidate(
                    item,
                    query,
                    index,
                    folders_only,
                )
            )

            if candidate is not None:
                candidates.append(
                    candidate
                )

        return tuple(candidates)

    # =========================================================
    # APPLICATION DISCOVERY
    # =========================================================

    def _discover_applications(
        self,
        query: TargetQuery,
        *,
        context: Optional[Any] = None,
    ) -> tuple[TargetCandidate, ...]:

        provider = (
            self.application_provider
        )

        if provider is None:
            return ()

        raw_candidates = self._call_provider(
            provider,
            query,
            context=context,
        )

        candidates = []

        for index, item in enumerate(
            raw_candidates
        ):

            candidate = (
                self._normalize_application_candidate(
                    item,
                    query,
                    index,
                )
            )

            if candidate is not None:
                candidates.append(
                    candidate
                )

        return tuple(candidates)

    # =========================================================
    # UNKNOWN TARGETS
    # =========================================================

    def _discover_unknown(
        self,
        query: TargetQuery,
        *,
        context: Optional[Any] = None,
    ) -> tuple[TargetCandidate, ...]:

        candidates = []

        candidates.extend(
            self._discover_files(
                TargetQuery(
                    text=query.text,
                    target_type="file",
                    name=query.name,
                    extension=query.extension,
                    location_hint=(
                        query.location_hint
                    ),
                    metadata=query.metadata,
                ),
                context=context,
            )
        )

        candidates.extend(
            self._discover_applications(
                TargetQuery(
                    text=query.text,
                    target_type="application",
                    name=query.name,
                    application=query.application,
                    metadata=query.metadata,
                ),
                context=context,
            )
        )

        return tuple(candidates)

    # =========================================================
    # PROVIDER ADAPTER
    # =========================================================

    @staticmethod
    def _call_provider(
        provider: Any,
        query: TargetQuery,
        *,
        context: Optional[Any] = None,
    ) -> Iterable[Any]:

        # Preferred provider contract.
        discover = getattr(
            provider,
            "discover",
            None,
        )

        if callable(discover):
            try:
                result = discover(query, context=context)
            except TypeError:
                result = discover(query)

            if result is None:
                return ()

            return result

        # Existing providers may expose search().
        search = getattr(
            provider,
            "search",
            None,
        )

        if callable(search):
            result = search(
                query.text
            )

            if result is None:
                return ()

            return result

        raise TargetDiscoveryError(
            "Target provider must expose "
            "discover() or search()."
        )

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize_file_candidate(
        item: Any,
        query: TargetQuery,
        index: int,
        folders_only: bool,
    ) -> Optional[TargetCandidate]:

        if isinstance(
            item,
            TargetCandidate,
        ):
            return item

        if isinstance(
            item,
            str,
        ):

            return TargetCandidate(
                target_id=(
                    f"file-candidate-{index}"
                ),
                target_type=(
                    "folder"
                    if folders_only
                    else "file"
                ),
                display_name=item,
                value=item,
                confidence=0.5,
                source=(
                    "file_provider"
                ),
            )

        if not isinstance(
            item,
            dict,
        ):
            return None

        value = (
            item.get("path")
            or item.get("value")
            or item.get("target")
        )

        if not value:
            return None

        target_type = (
            "folder"
            if item.get("is_directory")
            or item.get("is_folder")
            or folders_only
            else "file"
        )

        confidence = float(
            item.get(
                "confidence",
                0.5,
            )
        )

        return TargetCandidate(
            target_id=str(
                item.get(
                    "id",
                    f"file-candidate-{index}",
                )
            ),
            target_type=target_type,
            display_name=str(
                item.get(
                    "name",
                    value,
                )
            ),
            value=str(value),
            confidence=max(
                0.0,
                min(
                    1.0,
                    confidence,
                ),
            ),
            source=str(
                item.get(
                    "source",
                    "file_provider",
                )
            ),
            metadata=dict(
                item.get(
                    "metadata",
                    {},
                )
            ),
        )

    @staticmethod
    def _normalize_application_candidate(
        item: Any,
        query: TargetQuery,
        index: int,
    ) -> Optional[TargetCandidate]:

        if isinstance(
            item,
            TargetCandidate,
        ):
            return item

        if isinstance(
            item,
            str,
        ):

            return TargetCandidate(
                target_id=(
                    f"application-candidate-{index}"
                ),
                target_type="application",
                display_name=item,
                value=item,
                confidence=0.5,
                source=(
                    "application_provider"
                ),
            )

        if not isinstance(
            item,
            dict,
        ):
            return None

        value = (
            item.get("path")
            or item.get("value")
            or item.get("command")
            or item.get("application")
            or item.get("name")
        )

        if not value:
            return None

        confidence = float(
            item.get(
                "confidence",
                0.5,
            )
        )

        return TargetCandidate(
            target_id=str(
                item.get(
                    "id",
                    f"application-candidate-{index}",
                )
            ),
            target_type="application",
            display_name=str(
                item.get(
                    "name",
                    value,
                )
            ),
            value=str(value),
            confidence=max(
                0.0,
                min(
                    1.0,
                    confidence,
                ),
            ),
            source=str(
                item.get(
                    "source",
                    "application_provider",
                )
            ),
            metadata=dict(
                item.get(
                    "metadata",
                    {},
                )
            ),
        )
    def build_query_from_action_plan(
        self,
        action_plan,
    ) -> TargetQuery:
        """
    Convert an ActionPlan's unresolved target into
    a normalized TargetQuery.

    No filesystem access occurs here.
        """

        from .target_models import TargetQuery

        target = (
            action_plan.target
            or ""
        )

        operation = (
            action_plan.operation
            or ""
        )

        application = (
            action_plan.application
        )

        target_type = "unknown"

        if (
            operation.startswith("file.")
            or operation.startswith("filesystem.")
        ):
            target_type = "file"

        elif (
            operation.startswith(
                "application."
            )
            or operation.startswith(
                "app."
            )
        ):
            target_type = "application"

        elif operation.startswith(
            "folder."
        ):
            target_type = "folder"

        extension = None

        if isinstance(
            target,
            str,
        ):

            lowered = target.lower()

            known_extensions = (
                ".xlsx",
                ".xls",
                ".csv",
                ".docx",
                ".doc",
                ".pdf",
                ".txt",
                ".pptx",
                ".ppt",
            )

            for suffix in known_extensions:

                if lowered.endswith(
                    suffix
                ):
                    extension = suffix
                    break

        return TargetQuery(
            text=str(target),
            target_type=target_type,
            name=(
                str(target)
                if target
                else None
            ),
            extension=extension,
            application=application,
            metadata={
                "operation": operation,
            },
        )

    def discover_and_resolve(
        self,
        query,
        *,
        resolver=None,
        context: Optional[Any] = None,
    ):
        """
    Discover candidates and resolve the target.

    This is the standard Level 3.8.4 target pipeline.
    """

        from .target_resolution import (
            TargetResolver,
        )

        active_resolver = (
            resolver
            if resolver is not None
            else TargetResolver()
        )

        candidates = self.discover(
            query,
            context=context,
        )

        return active_resolver.resolve(
            query,
            candidates,
        )