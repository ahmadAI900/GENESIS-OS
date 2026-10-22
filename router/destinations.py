"""Canonical routing destinations shared by the router and the brain.

Item 27A (L6): router/router.py returned "internet" (lower case) while
brain/brain.py compared ``destination == "Internet"`` (capital I). The
comparison could never be true, so the brain's internet branch was
dead code, and the router never named a "knowledge" destination at all,
so the brain's knowledge branch could never fire either.

One vocabulary, imported by BOTH sides, removes the whole class of
bug: the two sides cannot drift apart over a case difference or a
renamed literal any more.
"""
from __future__ import annotations


DEST_MEMORY = "memory"
DEST_INTERNET = "internet"
DEST_KNOWLEDGE = "knowledge"
DEST_AI = "ai"

ALL_DESTINATIONS = (
    DEST_MEMORY,
    DEST_INTERNET,
    DEST_KNOWLEDGE,
    DEST_AI,
)
