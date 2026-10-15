"""
Genesis OS — Application Target Provider.

Adapter between the unified application discovery system
and Level 3.8.4 target discovery.
"""

from __future__ import annotations

from typing import Any, Iterable


class ApplicationTargetProvider:

    VERSION = "3.8.4"

    def __init__(
        self,
        application_discovery,
    ):
        self.application_discovery = (
            application_discovery
        )

    def discover(
        self,
        query,
    ) -> Iterable[Any]:
        """
        Delegate to the existing unified application
        discovery system.

        No duplicate application registry is created.

        The unified discovery exposes:
            search(text)  -> matching applications
            discover()    -> full application inventory

        A query MUST be answered through search(); calling
        discover(refresh=<text>) would rebuild the entire
        application index and return every installed
        application as an undifferentiated candidate list.
        """

        provider = (
            self.application_discovery
        )

        search = getattr(
            provider,
            "search",
            None,
        )

        if callable(search):
            return search(
                query.text
            )

        discover = getattr(
            provider,
            "discover",
            None,
        )

        if callable(discover):
            return discover()

        raise RuntimeError(
            "Unified application discovery "
            "does not expose a supported "
            "discovery interface."
        )